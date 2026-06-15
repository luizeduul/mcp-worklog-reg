"""Redmine provider — wraps :class:`RedmineClient` behind the :class:`TaskProvider`
interface.

Notes on the Redmine time model: a time entry tracks ``hours`` (decimal) on a
``spent_on`` date (no time-of-day) and an optional ``activity_id``. Worklog
seconds are converted to hours and the started datetime is reduced to its date.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import parse_qsl

from src.models.comment import Comment
from src.models.provider_capabilities import ProviderCapabilities
from src.models.task import Task
from src.models.worklog import Worklog
from src.providers.base import BaseProvider
from src.redmine_client import RedmineClient


def _full_name(user: dict[str, Any]) -> str:
    name = f"{user.get('firstname', '')} {user.get('lastname', '')}".strip()
    return name or user.get("name", "") or user.get("login", "")


class RedmineProvider(BaseProvider):
    """Redmine implementation of :class:`TaskProvider`.

    Composes :class:`RedmineClient` for HTTP and translates raw Redmine payloads
    into canonical :mod:`src.models` objects.
    """

    def __init__(self, client: RedmineClient, activity_id: int | None = None) -> None:
        self._client = client
        self._activity_id = activity_id

    @classmethod
    def from_env(cls) -> "RedmineProvider":
        """Build from ``REDMINE_URL``, ``REDMINE_API_KEY`` and optional
        ``REDMINE_ACTIVITY_ID``."""
        raw_activity = os.getenv("REDMINE_ACTIVITY_ID", "").strip()
        activity_id = int(raw_activity) if raw_activity.isdigit() else None
        return cls(RedmineClient.from_env(), activity_id)

    # -- identity -----------------------------------------------------------

    @property
    def name(self) -> str:
        return "redmine"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_comments=True, supports_worklogs=True)

    def whoami(self) -> dict[str, Any]:
        user = self._client.current_user() or {}
        return {
            "provider": self.name,
            "ok": bool(user),
            "accountId": str(user.get("id", "")),
            "displayName": _full_name(user),
            "emailAddress": user.get("mail", ""),
        }

    def current_account_id(self) -> str | None:
        user = self._client.current_user()
        return str(user["id"]) if user and user.get("id") is not None else None

    def group_entries(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Collapse entries by (task, day): Redmine time entries have no
        time-of-day, so several lines for the same task on the same date become
        one entry with summed hours and joined descriptions."""
        groups: dict[tuple[str, str], dict[str, Any]] = {}
        order: list[tuple[str, str]] = []
        for entry in entries:
            key = (entry["task_id"], (entry["started"] or "")[:10])
            group = groups.get(key)
            if group is None:
                group = {
                    "task_id": entry["task_id"],
                    "seconds": 0,
                    "started": entry["started"],
                    "comments": [],
                    "is_daily": entry.get("is_daily", False),
                }
                groups[key] = group
                order.append(key)
            group["seconds"] += entry["seconds"]
            comment = (entry.get("comment") or "").strip()
            if comment and comment not in group["comments"]:
                group["comments"].append(comment)
        return [
            {
                "task_id": groups[key]["task_id"],
                "seconds": groups[key]["seconds"],
                "started": groups[key]["started"],
                "comment": "; ".join(groups[key]["comments"]),
                "is_daily": groups[key]["is_daily"],
            }
            for key in order
        ]

    # -- required -----------------------------------------------------------

    def search_tasks(
        self, query: str = "", max_results: int = 20, native_query: str = ""
    ) -> list[Task]:
        if (native_query or "").strip():
            params = dict(parse_qsl(native_query.strip()))
            params.setdefault("limit", max_results)
            return self._issues_to_tasks(self._client.search_issues(params))
        if (query or "").strip():
            data = self._client.search_text(query.strip(), max_results)
            tasks: list[Task] = []
            for item in data.get("results", []):
                tasks.append(
                    Task(
                        id=str(item.get("id", "")),
                        provider=self.name,
                        summary=item.get("title", ""),
                        status="",
                        url=item.get("url", ""),
                    )
                )
            return tasks
        params = {
            "assigned_to_id": "me",
            "status_id": "open",
            "sort": "updated_on:desc",
            "limit": max_results,
        }
        return self._issues_to_tasks(self._client.search_issues(params))

    def _issues_to_tasks(self, data: dict[str, Any]) -> list[Task]:
        tasks: list[Task] = []
        for item in data.get("issues", []):
            status = item.get("status") or {}
            tasks.append(
                Task(
                    id=str(item.get("id", "")),
                    provider=self.name,
                    summary=item.get("subject", ""),
                    status=status.get("name", ""),
                )
            )
        return tasks

    def get_task(self, task_id: str) -> Task:
        item = (self._client.get_issue(task_id) or {}).get("issue") or {}
        status = item.get("status") or {}
        tracker = item.get("tracker") or {}
        assignee = item.get("assigned_to") or {}
        priority = item.get("priority") or {}
        issue_id = str(item.get("id", task_id))
        return Task(
            id=issue_id,
            provider=self.name,
            summary=item.get("subject", ""),
            status=status.get("name", ""),
            task_type=tracker.get("name", ""),
            assignee=assignee.get("name", ""),
            priority=priority.get("name", ""),
            description=item.get("description", "") or "",
            updated=item.get("updated_on", ""),
            url=f"{self._client.base_url}/issues/{issue_id}",
        )

    # -- optional (comments + worklogs) -------------------------------------

    def add_comment(self, task_id: str, comment: str) -> Comment:
        self._client.add_note(task_id, comment)
        # Redmine's note PUT returns no body, so there is no note id to surface.
        return Comment(
            id="",
            provider=self.name,
            task_id=task_id,
            author="",
            body=comment,
            created="",
        )

    def log_work(
        self,
        task_id: str,
        time_spent_seconds: int,
        started: str,
        comment: str = "",
    ) -> Worklog:
        """Post a time entry. *started* is trusted as-is and reduced to its date
        for ``spent_on`` (Redmine time entries have no time-of-day)."""
        hours = round(time_spent_seconds / 3600, 2)
        spent_on = (started or "")[:10]
        result = self._client.log_time(
            task_id, hours, spent_on, self._activity_id, comment
        )
        return Worklog(
            id=str(result.get("id", "")),
            provider=self.name,
            task_id=task_id,
            author="",
            time_spent_seconds=time_spent_seconds,
            time_spent_display=f"{hours}h",
            started=spent_on,
            comment=comment,
        )

    def get_worklogs(self, task_id: str) -> list[Worklog]:
        data = self._client.get_time_entries(task_id)
        worklogs: list[Worklog] = []
        for entry in data.get("time_entries", []):
            user = entry.get("user") or {}
            hours = float(entry.get("hours", 0) or 0)
            worklogs.append(
                Worklog(
                    id=str(entry.get("id", "")),
                    provider=self.name,
                    task_id=task_id,
                    author=user.get("name", ""),
                    time_spent_seconds=int(round(hours * 3600)),
                    time_spent_display=f"{hours}h",
                    started=entry.get("spent_on", ""),
                    comment=entry.get("comments", "") or "",
                    author_id=str(user.get("id", "")),
                )
            )
        return worklogs
