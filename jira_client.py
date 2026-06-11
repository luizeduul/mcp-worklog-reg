"""HTTP client for Jira Cloud REST v3. This module does not know about MCP.

This client is intentionally read/append only: it can search, read issues and
worklogs, log work, and add comments. It exposes no method that can create,
edit, transition, or delete issues, comments, or worklogs.
"""

from __future__ import annotations

import atexit
import base64
import os
from typing import Any
from urllib.parse import urlparse

import httpx

JIRA_API = "/rest/api/3"

# One shared connection pool for the whole process. Reused across every request
# so we do not open a new connection per call.
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


class JiraError(Exception):
    """Handled Jira error with a user-friendly message."""

    def __init__(self, message: str, status: int | None = None, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.detail = detail


def _validate_base_url(base_url: str) -> str:
    """Allow only HTTPS Jira Cloud sites (https://<site>.atlassian.net)."""
    parsed = urlparse(base_url)
    if parsed.scheme != "https":
        raise JiraError(
            "JIRA_BASE_URL must use HTTPS. "
            "Example: https://your-site.atlassian.net"
        )
    host = (parsed.hostname or "").lower()
    if not host.endswith(".atlassian.net"):
        raise JiraError(
            "JIRA_BASE_URL must be a Jira Cloud site ending in '.atlassian.net'. "
            "Example: https://your-site.atlassian.net"
        )
    return base_url.rstrip("/")


class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str, timeout: float = 30.0):
        if not (base_url and email and api_token):
            raise JiraError("JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN must be set.")
        self.base_url = _validate_base_url(base_url)
        self.email = email
        token = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        self._headers = {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._timeout = timeout

    @classmethod
    def from_env(cls) -> "JiraClient":
        return cls(
            base_url=os.getenv("JIRA_BASE_URL", ""),
            email=os.getenv("JIRA_EMAIL", ""),
            api_token=os.getenv("JIRA_API_TOKEN", ""),
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = _get_http_client().request(
                method,
                url,
                headers=self._headers,
                json=json_body,
                params=params,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise JiraError("Network failure while accessing Jira.", detail=str(exc))
        if response.status_code >= 400:
            raise self._map_error(response)
        if response.status_code == 204:
            return None
        if not response.content:
            raise JiraError(
                f"Jira returned an empty response with HTTP {response.status_code}.",
                status=response.status_code,
            )
        return response.json()

    def _map_error(self, response: httpx.Response) -> JiraError:
        status = response.status_code
        detail = self._extract_detail(response)
        if status == 400:
            message = "Invalid request. Check the data format and values."
        elif status == 401:
            message = "Invalid or expired token. Generate a new one at id.atlassian.com."
        elif status == 403:
            message = "Missing permission for this action. Check Jira permissions and token scopes."
        elif status == 404:
            message = "Resource not found, or the current account cannot access it."
        elif status == 429:
            message = "Jira rate limit reached (HTTP 429). Wait a few seconds and try again."
        elif status >= 500:
            message = f"Jira service error (HTTP {status}). Try again shortly."
        else:
            message = f"Jira returned HTTP {status}."
        return JiraError(message, status=status, detail=detail)

    @staticmethod
    def _extract_detail(response: httpx.Response) -> str:
        try:
            data = response.json()
        except Exception:
            return response.text[:300]
        if isinstance(data, dict):
            messages = data.get("errorMessages") or []
            errors = data.get("errors") or {}
            parts = list(messages) + [f"{key}: {value}" for key, value in errors.items()]
            if parts:
                return "; ".join(parts)
        return str(data)[:300]

    def current_user(self) -> dict[str, Any] | None:
        """
        Return the current user identity when Jira exposes it.

        Classic API tokens can usually access /myself. Scoped tokens may receive
        401 there, so the client falls back to user/search by email. Atlassian can
        hide email addresses, in which case None means identity is unavailable.
        """
        try:
            return self._request("GET", f"{JIRA_API}/myself")
        except JiraError as exc:
            if exc.status != 401:
                raise
        results = self._request(
            "GET", f"{JIRA_API}/user/search", params={"query": self.email}
        )
        for user in results or []:
            if (user.get("emailAddress") or "").lower() == self.email.lower():
                return user
        return results[0] if results else None

    def search_issues(self, jql: str, max_results: int = 20) -> dict[str, Any]:
        body = {
            "jql": jql,
            "maxResults": max_results,
            "fields": ["summary", "status"],
        }
        return self._request("POST", f"{JIRA_API}/search/jql", json_body=body)

    def get_issue(self, issue_key: str) -> dict[str, Any]:
        """Read one issue, requesting only the fields the tools surface."""
        return self._request(
            "GET",
            f"{JIRA_API}/issue/{issue_key}",
            params={
                "fields": "summary,status,issuetype,assignee,priority,labels,description,updated"
            },
        )

    def get_worklogs(self, issue_key: str) -> dict[str, Any]:
        return self._request("GET", f"{JIRA_API}/issue/{issue_key}/worklog")

    def log_work(
        self,
        issue_key: str,
        time_spent_seconds: int,
        started: str,
        comment_adf: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "timeSpentSeconds": time_spent_seconds,
            "started": started,
        }
        if comment_adf:
            body["comment"] = comment_adf
        return self._request(
            "POST", f"{JIRA_API}/issue/{issue_key}/worklog", json_body=body
        )

    def add_comment(self, issue_key: str, comment_adf: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            f"{JIRA_API}/issue/{issue_key}/comment",
            json_body={"body": comment_adf},
        )
