"""HTTP client for the Artia GraphQL API. This module does not know about MCP.

Read/append only by design: it can read the current account, list activities,
read one activity, and list/create time entries. It exposes no method that
creates, edits, transitions, assigns, or deletes activities or comments.
"""

from __future__ import annotations

import atexit
import os
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from src.errors import ArtiaError

_DEFAULT_API = "https://api.artia.com/graphql"

_http_client: httpx.Client | None = None


def _get_http_client() -> httpx.Client:
    global _http_client
    if _http_client is None:
        _http_client = httpx.Client(
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _http_client


@atexit.register
def _close_http_client() -> None:
    global _http_client
    if _http_client is not None:
        _http_client.close()
        _http_client = None


class ArtiaClient:
    def __init__(
        self,
        client_id: str,
        secret: str,
        base_url: str = _DEFAULT_API,
        timeout: float = 30.0,
    ):
        if not (client_id and secret):
            raise ArtiaError("ARTIA_CLIENT_ID and ARTIA_SECRET must be set.")
        self.base_url = _validate_base_url(base_url or _DEFAULT_API)
        self._client_id = client_id
        self._secret = secret
        self._timeout = timeout
        self._token: str | None = None

    @classmethod
    def from_env(cls) -> "ArtiaClient":
        return cls(
            client_id=os.getenv("ARTIA_CLIENT_ID", ""),
            secret=os.getenv("ARTIA_SECRET", ""),
            base_url=os.getenv("ARTIA_API_URL", _DEFAULT_API) or _DEFAULT_API,
        )

    def _headers(self, authenticated: bool) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if authenticated:
            if not self._token:
                raise ArtiaError("Artia authentication failed.")
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _send(
        self,
        query: str,
        variables: dict[str, Any] | None,
        *,
        authenticated: bool,
    ) -> httpx.Response:
        return _get_http_client().post(
            self.base_url,
            headers=self._headers(authenticated),
            json={"query": query, "variables": variables or {}},
            timeout=self._timeout,
        )

    def _post(
        self,
        query: str,
        variables: dict[str, Any] | None,
        *,
        retries: int = 3,
    ) -> dict[str, Any]:
        authenticated = not self._is_auth_query(query)
        if authenticated and self._token is None:
            self._authenticate()
        return self._post_graphql(query, variables, retries=retries, authenticated=authenticated)

    def _post_graphql(
        self,
        query: str,
        variables: dict[str, Any] | None,
        *,
        retries: int,
        authenticated: bool,
    ) -> dict[str, Any]:
        backoffs = (0.5, 1.0, 2.0)
        attempt = 0
        reauthed = False
        while True:
            try:
                response = self._send(query, variables, authenticated=authenticated)
            except httpx.HTTPError as exc:
                if attempt < retries:
                    time.sleep(backoffs[min(attempt, len(backoffs) - 1)])
                    attempt += 1
                    continue
                raise ArtiaError(
                    "Network failure while accessing Artia.", detail=str(exc)
                )

            if response.status_code == 401:
                if authenticated and not reauthed:
                    self._authenticate()
                    reauthed = True
                    continue
                raise self._map_error(response)

            if response.status_code == 429 or response.status_code >= 500:
                if attempt < retries:
                    time.sleep(backoffs[min(attempt, len(backoffs) - 1)])
                    attempt += 1
                    continue
                raise self._map_error(response)

            if response.status_code >= 400:
                raise self._map_error(response)

            body = self._decode(response)
            errors = body.get("errors") if isinstance(body, dict) else None
            if errors:
                raise self._map_graphql_error(response, errors)
            return body

    def _authenticate(self) -> None:
        body = self._post_graphql(
            _AUTHENTICATION_MUTATION,
            {"clientId": self._client_id, "secret": self._secret},
            retries=3,
            authenticated=False,
        )
        payload = self._extract_node(body, "authenticationByClient") or {}
        token = payload.get("token") if isinstance(payload, dict) else None
        if not token:
            raise ArtiaError("Artia authentication did not return a token.")
        self._token = str(token)

    def _map_error(self, response: httpx.Response) -> ArtiaError:
        status = response.status_code
        detail = self._extract_detail(response)
        if status == 400:
            message = "Invalid Artia request. Check the folder, activity id, and values."
        elif status == 401:
            message = "Invalid or expired Artia token. Check ARTIA_CLIENT_ID and ARTIA_SECRET."
        elif status == 403:
            message = "Missing permission for this Artia action."
        elif status == 404:
            message = "Artia resource not found, or the account cannot access it."
        elif status == 429:
            message = "Artia rate limit reached (HTTP 429). Wait and try again."
        elif status >= 500:
            message = f"Artia service error (HTTP {status}). Try again shortly."
        else:
            message = f"Artia returned HTTP {status}."
        return ArtiaError(message, status=status, detail=detail)

    def _map_graphql_error(
        self, response: httpx.Response, errors: Any
    ) -> ArtiaError:
        messages = self._error_messages(errors)
        message = messages[0] if messages else "Artia returned a GraphQL error."
        detail = self._extract_detail(response, errors)
        return ArtiaError(message, status=response.status_code, detail=detail)

    @staticmethod
    def _decode(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except Exception as exc:
            raise ArtiaError(
                "Artia returned an invalid JSON response.",
                status=response.status_code,
                detail=str(exc),
            )
        return body if isinstance(body, dict) else {"data": body}

    @staticmethod
    def _is_auth_query(query: str) -> bool:
        return "authenticationByClient" in query

    @staticmethod
    def _error_messages(errors: Any) -> list[str]:
        messages: list[str] = []
        if not isinstance(errors, list):
            return messages
        for item in errors:
            if isinstance(item, dict):
                message = item.get("message")
                if message:
                    messages.append(str(message))
            elif item:
                messages.append(str(item))
        return messages

    @staticmethod
    def _extract_detail(response: httpx.Response, errors: Any | None = None) -> str:
        try:
            body = response.json()
        except Exception:
            return response.text[:300]
        if isinstance(body, dict):
            if isinstance(errors, list):
                parts: list[str] = []
                for item in errors:
                    if isinstance(item, dict):
                        message = item.get("message")
                        path = item.get("path")
                        if message and path:
                            parts.append(f"{message} ({path})")
                        elif message:
                            parts.append(str(message))
                    elif item:
                        parts.append(str(item))
                if parts:
                    return "; ".join(parts)[:300]
            message = body.get("message")
            if message:
                return str(message)[:300]
            error = body.get("error")
            if error:
                return str(error)[:300]
        return str(body)[:300]

    @staticmethod
    def _extract_node(data: Any, *keys: str) -> dict[str, Any] | None:
        payload = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
        if not isinstance(payload, dict):
            return None
        for key in keys:
            node = payload.get(key)
            if isinstance(node, dict):
                return node
        return None

    @staticmethod
    def _extract_collection(data: Any, *keys: str) -> list[dict[str, Any]]:
        node = ArtiaClient._extract_node(data, *keys)
        if isinstance(node, list):
            return [item for item in node if isinstance(item, dict)]
        if isinstance(node, dict):
            for key in ("items", "nodes", "activities", "results"):
                value = node.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
            if "id" in node:
                return [node]
        return []

    def account(self) -> dict[str, Any]:
        data = self._post(_ACCOUNT_QUERY, {})
        return self._extract_node(data, "me", "account", "viewer", "currentUser") or {}

    def list_activities(
        self, folder_id: str, limit: int = 20, query: str = ""
    ) -> list[dict[str, Any]]:
        data = self._post(
            _LIST_ACTIVITIES_QUERY,
            {"folderId": folder_id, "limit": limit, "query": query or None},
        )
        return self._extract_collection(data, "activities", "listActivities", "folderActivities")

    def get_activity(self, account_id: str, activity_id: str) -> dict[str, Any]:
        data = self._post(
            _GET_ACTIVITY_QUERY,
            {"accountId": account_id, "activityId": activity_id},
        )
        return self._extract_node(data, "activity", "getActivity", "viewActivity") or {}

    def list_time_entries(
        self, account_id: str, activity_id: str
    ) -> list[dict[str, Any]]:
        data = self._post(
            _LIST_TIME_ENTRIES_QUERY,
            {"accountId": account_id, "activityId": activity_id},
        )
        return self._extract_collection(
            data,
            "timeEntries",
            "listTimeEntries",
            "activityTimeEntries",
        )

    def create_time_entry(
        self,
        account_id: str,
        activity_id: str,
        date_at: str,
        start_time: str,
        duration: int,
        status_id: str | None = None,
    ) -> dict[str, Any]:
        variables: dict[str, Any] = {
            "accountId": account_id,
            "activityId": activity_id,
            "dateAt": date_at,
            "startTime": start_time,
            "duration": duration,
        }
        if (status_id or "").strip():
            variables["statusId"] = status_id
        data = self._post(_CREATE_TIME_ENTRY_MUTATION, variables)
        return (
            self._extract_node(data, "createTimeEntry", "timeEntry", "addTimeEntry")
            or {}
        )


_AUTHENTICATION_MUTATION = """
mutation AuthenticationByClient($clientId: String!, $secret: String!) {
  authenticationByClient(clientId: $clientId, secret: $secret) {
    token
  }
}
"""

_ACCOUNT_QUERY = """
query Account {
  me {
    id
    name
    displayName
    email
  }
}
"""

_LIST_ACTIVITIES_QUERY = """
query ListActivities($folderId: ID!, $limit: Int!, $query: String) {
  activities(folderId: $folderId, limit: $limit, query: $query) {
    items {
      id
      title
      name
      status
      url
      description
      updatedAt
      responsible {
        id
        name
        displayName
      }
      categories {
        name
      }
      labels {
        name
      }
    }
  }
}
"""

_GET_ACTIVITY_QUERY = """
query GetActivity($accountId: ID!, $activityId: ID!) {
  activity(accountId: $accountId, activityId: $activityId) {
    id
    title
    name
    status
    url
    description
    updatedAt
    responsible {
      id
      name
      displayName
    }
    categories {
      name
    }
    labels {
      name
    }
  }
}
"""

_LIST_TIME_ENTRIES_QUERY = """
query ListTimeEntries($accountId: ID!, $activityId: ID!) {
    timeEntries(accountId: $accountId, activityId: $activityId) {
        items {
            id
            dateAt
            startTime
            duration
            durationSeconds
            durationMinutes
            comment
            description
            user {
                id
                name
                displayName
            }
            author {
                id
                name
                displayName
            }
            status {
                id
                name
            }
        }
    }
}
"""

_CREATE_TIME_ENTRY_MUTATION = """
mutation CreateTimeEntry(
    $accountId: ID!,
    $activityId: ID!,
    $dateAt: String!,
    $startTime: String!,
    $duration: Int!,
    $statusId: ID
) {
    createTimeEntry(
        accountId: $accountId,
        activityId: $activityId,
        dateAt: $dateAt,
        startTime: $startTime,
        duration: $duration,
        statusId: $statusId
    ) {
        id
        dateAt
        startTime
        duration
        durationSeconds
        durationMinutes
        comment
        description
    }
}
"""


def _validate_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        raise ArtiaError(
            "ARTIA_API_URL must use HTTP or HTTPS. Example: https://api.artia.com/graphql"
        )
    if not parsed.hostname:
        raise ArtiaError(
            "ARTIA_API_URL must include a host. Example: https://api.artia.com/graphql"
        )
    normalized = base_url.rstrip("/")
    parsed = urlparse(normalized)
    if parsed.path in ("", "/"):
        normalized = f"{normalized}/graphql"
    return normalized