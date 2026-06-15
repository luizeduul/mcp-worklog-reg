"""HTTP client for the Redmine REST API. This module does not know about MCP.

Read/append only by design: it can read the current user, search and read
issues, read and create time entries, and append a note to an issue. It exposes
no method that edits issue fields, transitions, or deletes anything.
"""

from __future__ import annotations

import atexit
import os
from typing import Any
from urllib.parse import urlparse

import httpx

from src.errors import ProviderError

# One shared connection pool for the whole process, reused across every request.
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


class RedmineError(ProviderError):
    """Handled Redmine error with a user-friendly message."""


def _validate_base_url(base_url: str) -> str:
    """Allow HTTP/HTTPS Redmine hosts (self-hosted setups are often intranet)."""
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        raise RedmineError(
            "REDMINE_URL must use HTTP or HTTPS. "
            "Example: https://redmine.example.com"
        )
    if not parsed.hostname:
        raise RedmineError(
            "REDMINE_URL must include a host. Example: https://redmine.example.com"
        )
    return base_url.rstrip("/")


class RedmineClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0):
        if not (base_url and api_key):
            raise RedmineError("REDMINE_URL and REDMINE_API_KEY must be set.")
        self.base_url = _validate_base_url(base_url)
        self._headers = {
            "X-Redmine-API-Key": api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._timeout = timeout

    @classmethod
    def from_env(cls) -> "RedmineClient":
        return cls(
            base_url=os.getenv("REDMINE_URL", ""),
            api_key=os.getenv("REDMINE_API_KEY", ""),
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
            raise RedmineError("Network failure while accessing Redmine.", detail=str(exc))
        if response.status_code >= 400:
            raise self._map_error(response)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def _map_error(self, response: httpx.Response) -> RedmineError:
        status = response.status_code
        detail = self._extract_detail(response)
        if status == 401:
            message = "Invalid Redmine API key. Check REDMINE_API_KEY."
        elif status == 403:
            message = "Missing permission for this action in Redmine."
        elif status == 404:
            message = "Resource not found, or the current account cannot access it."
        elif status == 422:
            message = "Invalid request. Check the data (issue id, activity, values)."
        elif status == 429:
            message = "Redmine rate limit reached (HTTP 429). Wait and try again."
        elif status >= 500:
            message = f"Redmine service error (HTTP {status}). Try again shortly."
        else:
            message = f"Redmine returned HTTP {status}."
        return RedmineError(message, status=status, detail=detail)

    @staticmethod
    def _extract_detail(response: httpx.Response) -> str:
        try:
            data = response.json()
        except Exception:
            return response.text[:300]
        if isinstance(data, dict) and data.get("errors"):
            return "; ".join(str(item) for item in data["errors"])
        return str(data)[:300]

    # -- read ---------------------------------------------------------------

    def current_user(self) -> dict[str, Any] | None:
        data = self._request("GET", "/users/current.json")
        return (data or {}).get("user")

    def search_issues(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._request("GET", "/issues.json", params=params)

    def search_text(self, query: str, limit: int = 20) -> dict[str, Any]:
        return self._request(
            "GET",
            "/search.json",
            params={"q": query, "issues": 1, "limit": limit},
        )

    def get_issue(self, issue_id: str) -> dict[str, Any]:
        return self._request("GET", f"/issues/{issue_id}.json")

    def get_time_entries(self, issue_id: str, limit: int = 100) -> dict[str, Any]:
        return self._request(
            "GET",
            "/time_entries.json",
            params={"issue_id": issue_id, "limit": limit},
        )

    # -- append -------------------------------------------------------------

    def add_note(self, issue_id: str, note: str) -> None:
        """Append a journal note to an issue (does not change any field)."""
        self._request(
            "PUT",
            f"/issues/{issue_id}.json",
            json_body={"issue": {"notes": note}},
        )

    def log_time(
        self,
        issue_id: str,
        hours: float,
        spent_on: str,
        activity_id: int | None = None,
        comments: str = "",
    ) -> dict[str, Any]:
        time_entry: dict[str, Any] = {
            "issue_id": issue_id,
            "hours": hours,
            "spent_on": spent_on,
        }
        if activity_id is not None:
            time_entry["activity_id"] = activity_id
        if comments:
            time_entry["comments"] = comments
        data = self._request(
            "POST", "/time_entries.json", json_body={"time_entry": time_entry}
        )
        return (data or {}).get("time_entry", {})
