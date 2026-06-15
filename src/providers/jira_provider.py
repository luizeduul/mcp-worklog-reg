"""Jira Cloud provider — wraps :class:`JiraClient` behind the :class:`TaskProvider` interface."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from src.jira_client import JiraClient, JiraError
from src.models.comment import Comment
from src.models.provider_capabilities import ProviderCapabilities
from src.models.task import Task
from src.models.worklog import Worklog
from src.providers.base import BaseProvider


# ---------------------------------------------------------------------------
# Jira-specific helpers (moved from the old server.py)
# ---------------------------------------------------------------------------

_DAILY_SENTINELS = {"daily", "dayli"}
_PT_MONTHS = (
    "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
)
_DAILY_JQL_EXAMPLE = (
    'project = MYPROJ AND summary ~ "Timesheet {month} de {year}" '
    "ORDER BY created DESC"
)


def build_adf_comment(text: str) -> dict[str, Any]:
    """Build a one-paragraph Atlassian Document Format comment."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
        ],
    }


def _adf_to_text(adf: Any) -> str:
    """Best-effort plain text extraction from an ADF document."""
    if not isinstance(adf, dict):
        return ""
    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "text" and isinstance(node.get("text"), str):
                parts.append(node["text"])
            for child in node.get("content", []) or []:
                walk(child)

    walk(adf)
    return " ".join(parts).strip()


def _escape_jql_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _is_daily_key(issue_key: str) -> bool:
    return (issue_key or "").strip().lower() in _DAILY_SENTINELS


def _render_daily_jql(template: str, started_jira: str) -> str:
    """Fill ``{month}/{month_num}/{year}`` from the worklog date into the JQL template."""
    try:
        moment = datetime.fromisoformat(started_jira)
    except (ValueError, TypeError):
        moment = datetime.now()
    try:
        return template.format(
            month=_PT_MONTHS[moment.month], month_num=moment.month, year=moment.year
        )
    except (KeyError, IndexError, ValueError) as exc:
        raise JiraError(
            "Invalid JIRA_DAILY_JQL template. Use only {month}, {month_num}, and "
            f"{{year}} placeholders. Detail: {exc}"
        )


def _resolve_issue_key(
    client: JiraClient, issue_key: str, started_jira: str, cache: dict[str, str]
) -> tuple[str, bool]:
    """Resolve a ``'daily'``/``'dayli'`` sentinel to the month's bucket issue.

    Returns ``(resolved_key, is_daily)``.  Non-sentinel keys pass through unchanged.
    The *cache* maps a rendered JQL to its resolved key so a batch searches once
    per month.
    """
    if not _is_daily_key(issue_key):
        return issue_key, False
    template = os.getenv("JIRA_DAILY_JQL", "").strip()
    if not template:
        raise JiraError(
            "Daily entry, but JIRA_DAILY_JQL is not configured. Set it in .env, e.g. "
            f"{_DAILY_JQL_EXAMPLE}"
        )
    jql = _render_daily_jql(template, started_jira)
    if jql in cache:
        return cache[jql], True
    data = client.search_issues(jql, 5)
    issues = data.get("issues", [])
    if not issues:
        raise JiraError(f"No daily bucket issue found for this month. JQL: {jql}")
    resolved = issues[0].get("key")
    cache[jql] = resolved
    return resolved, True


# ---------------------------------------------------------------------------
# JiraProvider
# ---------------------------------------------------------------------------


class JiraProvider(BaseProvider):
    """Jira Cloud implementation of :class:`TaskProvider`.

    Composes :class:`JiraClient` for HTTP, translates raw Jira payloads
    into canonical :mod:`src.models` objects.
    """

    def __init__(self, client: JiraClient) -> None:
        self._client = client
        self._daily_cache: dict[str, str] = {}

    @classmethod
    def from_env(cls) -> "JiraProvider":
        """Build from ``JIRA_BASE_URL``, ``JIRA_EMAIL``, ``JIRA_API_TOKEN``."""
        return cls(JiraClient.from_env())

    # -- identity -----------------------------------------------------------

    @property
    def name(self) -> str:
        return "jira"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_comments=True, supports_worklogs=True)

    # -- required -----------------------------------------------------------

    def whoami(self) -> dict[str, Any]:
        user = self._client.current_user()
        if user:
            return {
                "provider": self.name,
                "ok": True,
                "accountId": user.get("accountId"),
                "displayName": user.get("displayName"),
                "emailAddress": user.get("emailAddress"),
            }
        # Scoped token: identity endpoint unavailable, validate via search.
        self._client.search_issues(
            "assignee = currentUser() ORDER BY updated DESC", 1
        )
        return {
            "provider": self.name,
            "ok": True,
            "identity": os.getenv("JIRA_EMAIL"),
            "note": (
                "This token cannot access /myself; identity comes from JIRA_EMAIL. "
                "Auth was validated with an issue search."
            ),
        }

    def search_tasks(
        self, query: str = "", max_results: int = 20, native_query: str = ""
    ) -> list[Task]:
        if (native_query or "").strip():
            jql = native_query.strip()
        elif (query or "").strip():
            jql = f'text ~ "{_escape_jql_text(query.strip())}" ORDER BY updated DESC'
        else:
            jql = (
                "assignee = currentUser() AND statusCategory != Done "
                "ORDER BY updated DESC"
            )
        data = self._client.search_issues(jql, max_results)
        tasks: list[Task] = []
        for item in data.get("issues", []):
            fields = item.get("fields") or {}
            status = fields.get("status") or {}
            tasks.append(
                Task(
                    id=item.get("key", ""),
                    provider=self.name,
                    summary=fields.get("summary", ""),
                    status=status.get("name", ""),
                )
            )
        return tasks

    def resolve_task_alias(self, task_id: str, started: str) -> tuple[str, bool]:
        """Resolve a ``'daily'``/``'dayli'`` sentinel to the month's bucket issue.

        Real issue keys pass through unchanged. Caches the resolution per rendered
        JQL so a batch searches once per month.
        """
        return _resolve_issue_key(
            self._client, task_id, started, self._daily_cache
        )

    def current_account_id(self) -> str | None:
        user = self._client.current_user()
        return user.get("accountId") if user else None

    def get_task(self, task_id: str) -> Task:
        data = self._client.get_issue(task_id)
        fields = data.get("fields") or {}
        status = fields.get("status") or {}
        issue_type = fields.get("issuetype") or {}
        assignee = fields.get("assignee") or {}
        priority = fields.get("priority") or {}
        return Task(
            id=data.get("key", ""),
            provider=self.name,
            summary=fields.get("summary", ""),
            status=status.get("name", ""),
            task_type=issue_type.get("name", ""),
            assignee=assignee.get("displayName", ""),
            priority=priority.get("name", ""),
            labels=fields.get("labels") or [],
            description=_adf_to_text(fields.get("description")),
            updated=fields.get("updated", ""),
        )

    # -- optional (comments + worklogs) -------------------------------------

    def add_comment(self, task_id: str, comment: str) -> Comment:
        adf = build_adf_comment(comment)
        result = self._client.add_comment(task_id, adf)
        return Comment(
            id=result.get("id", ""),
            provider=self.name,
            task_id=task_id,
            author="",  # Jira response doesn't always include the author
            body=comment,
            created=result.get("created", ""),
        )

    def log_work(
        self,
        task_id: str,
        time_spent_seconds: int,
        started: str,
        comment: str = "",
    ) -> Worklog:
        """Post a worklog. *task_id* and *started* are trusted as-is: callers
        resolve aliases (:meth:`resolve_task_alias`) and format *started* first.
        """
        adf_comment = build_adf_comment(comment) if (comment or "").strip() else None
        result = self._client.log_work(
            task_id, time_spent_seconds, started, adf_comment
        )
        return Worklog(
            id=result.get("id", ""),
            provider=self.name,
            task_id=task_id,
            author="",
            time_spent_seconds=time_spent_seconds,
            time_spent_display=result.get("timeSpent", ""),
            started=started,
            comment=comment,
        )

    def get_worklogs(self, task_id: str) -> list[Worklog]:
        data = self._client.get_worklogs(task_id)
        worklogs: list[Worklog] = []
        for entry in data.get("worklogs", []):
            author = entry.get("author") or {}
            worklogs.append(
                Worklog(
                    id=entry.get("id", ""),
                    provider=self.name,
                    task_id=task_id,
                    author=author.get("displayName", ""),
                    time_spent_seconds=entry.get("timeSpentSeconds", 0),
                    time_spent_display=entry.get("timeSpent", ""),
                    started=entry.get("started", ""),
                    comment=_adf_to_text(entry.get("comment")),
                    author_id=author.get("accountId", ""),
                )
            )
        return worklogs
