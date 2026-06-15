"""GitHub provider — wraps :class:`GitHubClient` behind the :class:`TaskProvider`
interface.

GitHub issues are the tasks. There is no native time tracking, so this provider
does not support worklogs; only identity, search, read and comment are exposed.
An issue id is ``owner/repo#number`` (or a bare number when ``GITHUB_REPO`` is
set).
"""

from __future__ import annotations

import os
from typing import Any

from src.github_client import GitHubClient, GitHubError
from src.models.comment import Comment
from src.models.provider_capabilities import ProviderCapabilities
from src.models.task import Task
from src.providers.base import BaseProvider


def _parse_ref(task_id: str, default_repo: str) -> tuple[str, str, str]:
    """Resolve a task id to ``(owner, repo, number)``.

    Accepts ``owner/repo#number`` or a bare ``number`` when *default_repo*
    (``owner/repo``) is configured.
    """
    ref = (task_id or "").strip()
    if "#" in ref:
        repo_part, _, number = ref.partition("#")
        owner, _, repo = repo_part.partition("/")
        if owner and repo and number:
            return owner, repo, number
    if ref.isdigit() and default_repo:
        owner, _, repo = default_repo.partition("/")
        if owner and repo:
            return owner, repo, ref
    raise GitHubError(
        f"Invalid GitHub issue ref '{task_id}'. Use 'owner/repo#number', or set "
        "GITHUB_REPO and pass just the number."
    )


def _ref_from_item(item: dict[str, Any]) -> str:
    """Build ``owner/repo#number`` from a search result's repository_url."""
    number = item.get("number", "")
    parts = str(item.get("repository_url", "")).rstrip("/").split("/")
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}#{number}"
    return str(number)


class GitHubProvider(BaseProvider):
    """GitHub Issues implementation of :class:`TaskProvider`.

    Composes :class:`GitHubClient` for HTTP and translates raw GitHub payloads
    into canonical :mod:`src.models` objects.
    """

    def __init__(self, client: GitHubClient, default_repo: str = "") -> None:
        self._client = client
        self._default_repo = default_repo

    @classmethod
    def from_env(cls) -> "GitHubProvider":
        """Build from ``GITHUB_TOKEN`` and optional ``GITHUB_API_URL`` /
        ``GITHUB_REPO`` (``owner/repo``)."""
        return cls(GitHubClient.from_env(), os.getenv("GITHUB_REPO", "").strip())

    # -- identity -----------------------------------------------------------

    @property
    def name(self) -> str:
        return "github"

    @property
    def capabilities(self) -> ProviderCapabilities:
        # GitHub has no native time tracking — worklogs are unsupported.
        return ProviderCapabilities(supports_comments=True, supports_worklogs=False)

    def whoami(self) -> dict[str, Any]:
        user = self._client.current_user() or {}
        return {
            "provider": self.name,
            "ok": bool(user),
            "accountId": str(user.get("id", "")),
            "displayName": user.get("name") or user.get("login", ""),
            "emailAddress": user.get("email", "") or "",
        }

    def current_account_id(self) -> str | None:
        user = self._client.current_user()
        return str(user["id"]) if user and user.get("id") is not None else None

    # -- required -----------------------------------------------------------

    def search_tasks(
        self, query: str = "", max_results: int = 20, native_query: str = ""
    ) -> list[Task]:
        if (native_query or "").strip():
            q = native_query.strip()
        elif (query or "").strip():
            q = self._scope(query.strip())
        else:
            q = self._scope("assignee:@me state:open")
        data = self._client.search_issues(q, max_results, sort="updated")
        tasks: list[Task] = []
        for item in data.get("items", []):
            tasks.append(
                Task(
                    id=_ref_from_item(item),
                    provider=self.name,
                    summary=item.get("title", ""),
                    status=item.get("state", ""),
                    url=item.get("html_url", ""),
                )
            )
        return tasks

    def _scope(self, query: str) -> str:
        """Restrict a search to ``GITHUB_REPO`` when it is configured."""
        if self._default_repo:
            return f"{query} repo:{self._default_repo}"
        return query

    def get_task(self, task_id: str) -> Task:
        owner, repo, number = _parse_ref(task_id, self._default_repo)
        item = self._client.get_issue(owner, repo, number) or {}
        assignee = item.get("assignee") or {}
        labels = [
            label.get("name", "")
            for label in (item.get("labels") or [])
            if isinstance(label, dict)
        ]
        issue_number = item.get("number", number)
        return Task(
            id=f"{owner}/{repo}#{issue_number}",
            provider=self.name,
            summary=item.get("title", ""),
            status=item.get("state", ""),
            task_type="pull_request" if "pull_request" in item else "issue",
            assignee=assignee.get("login", ""),
            labels=labels,
            description=item.get("body", "") or "",
            updated=item.get("updated_at", ""),
            url=item.get("html_url", ""),
        )

    # -- optional (comments) ------------------------------------------------

    def add_comment(self, task_id: str, comment: str) -> Comment:
        owner, repo, number = _parse_ref(task_id, self._default_repo)
        result = self._client.add_comment(owner, repo, number, comment) or {}
        user = result.get("user") or {}
        return Comment(
            id=str(result.get("id", "")),
            provider=self.name,
            task_id=f"{owner}/{repo}#{number}",
            author=user.get("login", ""),
            body=comment,
            created=result.get("created_at", ""),
        )
