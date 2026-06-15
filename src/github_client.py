"""HTTP client for the GitHub REST API. This module does not know about MCP.

Read/append only by design: it can read the authenticated user, search and read
issues, and append a comment to an issue. It exposes no method that edits issue
fields, closes issues, transitions state, or deletes anything.
"""

from __future__ import annotations

import atexit
import os
from typing import Any
from urllib.parse import urlparse

import httpx

from src.errors import ProviderError

_DEFAULT_API = "https://api.github.com"

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


class GitHubError(ProviderError):
    """Handled GitHub error with a user-friendly message."""


def _validate_base_url(base_url: str) -> str:
    """Allow HTTP/HTTPS API hosts (GitHub Enterprise can be self-hosted)."""
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        raise GitHubError(
            "GITHUB_API_URL must use HTTP or HTTPS. Example: https://api.github.com"
        )
    if not parsed.hostname:
        raise GitHubError(
            "GITHUB_API_URL must include a host. Example: https://api.github.com"
        )
    return base_url.rstrip("/")


class GitHubClient:
    def __init__(
        self, token: str, base_url: str = _DEFAULT_API, timeout: float = 30.0
    ):
        if not token:
            raise GitHubError("GITHUB_TOKEN must be set.")
        self.base_url = _validate_base_url(base_url or _DEFAULT_API)
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._timeout = timeout

    @classmethod
    def from_env(cls) -> "GitHubClient":
        return cls(
            token=os.getenv("GITHUB_TOKEN", ""),
            base_url=os.getenv("GITHUB_API_URL", _DEFAULT_API) or _DEFAULT_API,
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
            raise GitHubError("Network failure while accessing GitHub.", detail=str(exc))
        if response.status_code >= 400:
            raise self._map_error(response)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def _map_error(self, response: httpx.Response) -> GitHubError:
        status = response.status_code
        detail = self._extract_detail(response)
        if status == 401:
            message = "Invalid GitHub token. Check GITHUB_TOKEN."
        elif status == 403:
            message = "Forbidden or rate-limited by GitHub (HTTP 403)."
        elif status == 404:
            message = "Resource not found, or the token cannot access it."
        elif status == 422:
            message = "Invalid request. Check the issue ref and values."
        elif status == 429:
            message = "GitHub rate limit reached (HTTP 429). Wait and try again."
        elif status >= 500:
            message = f"GitHub service error (HTTP {status}). Try again shortly."
        else:
            message = f"GitHub returned HTTP {status}."
        return GitHubError(message, status=status, detail=detail)

    @staticmethod
    def _extract_detail(response: httpx.Response) -> str:
        try:
            data = response.json()
        except Exception:
            return response.text[:300]
        if isinstance(data, dict):
            message = str(data.get("message", ""))
            errors = data.get("errors")
            if errors:
                joined = "; ".join(str(item) for item in errors)
                return f"{message}: {joined}"[:300]
            return message[:300]
        return str(data)[:300]

    # -- read ---------------------------------------------------------------

    def current_user(self) -> dict[str, Any] | None:
        return self._request("GET", "/user")

    def search_issues(self, query: str, limit: int = 20, sort: str = "") -> dict[str, Any]:
        params: dict[str, Any] = {"q": query, "per_page": limit}
        if sort:
            params["sort"] = sort
            params["order"] = "desc"
        return self._request("GET", "/search/issues", params=params)

    def get_issue(self, owner: str, repo: str, number: str) -> dict[str, Any]:
        return self._request("GET", f"/repos/{owner}/{repo}/issues/{number}")

    # -- append -------------------------------------------------------------

    def add_comment(
        self, owner: str, repo: str, number: str, body: str
    ) -> dict[str, Any]:
        """Append a comment to an issue (does not change any field or state)."""
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{number}/comments",
            json_body={"body": body},
        )
