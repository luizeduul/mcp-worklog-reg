"""Artia provider — wraps :class:`ArtiaClient` behind the :class:`TaskProvider` interface."""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any

from src.artia_client import ArtiaClient
from src.errors import ArtiaError
from src.models.provider_capabilities import ProviderCapabilities
from src.models.task import Task
from src.models.worklog import Worklog
from src.providers.base import BaseProvider


def _text_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("displayName", "name", "title", "label", "value"):
            text = value.get(key)
            if text:
                return str(text)
    return ""


def _labels(item: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for key in ("labels", "categories"):
        values = item.get(key) or []
        if isinstance(values, list):
            for value in values:
                label = _text_value(value)
                if label and label not in labels:
                    labels.append(label)
    return labels


def _responsible_id(item: dict[str, Any]) -> str:
    responsible = item.get("responsible") or item.get("assignee") or {}
    if isinstance(responsible, dict):
        return str(
            responsible.get("id")
            or responsible.get("accountId")
            or responsible.get("uid")
            or ""
        )
    return ""


def _display_duration(seconds: int) -> str:
    if seconds <= 0:
        return "0m"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def _to_seconds(item: dict[str, Any]) -> int:
    seconds = item.get("durationSeconds")
    if isinstance(seconds, (int, float)):
        return max(0, int(round(float(seconds))))

    minutes = item.get("durationMinutes")
    if isinstance(minutes, (int, float)):
        return max(0, int(round(float(minutes) * 60)))

    duration = item.get("duration")
    if isinstance(duration, (int, float)):
        return max(0, int(round(float(duration))))
    if isinstance(duration, str):
        value = duration.strip()
        if value.isdigit():
            return int(value)
        match = re.fullmatch(r"(\d+)\s*h\s*(\d+)?\s*m?", value.lower())
        if match:
            hours = int(match.group(1))
            mins = int(match.group(2) or 0)
            return hours * 3600 + mins * 60
    return 0


def _started_datetime(value: str) -> datetime:
    raw = (value or "").strip()
    if not raw:
        return datetime.now().astimezone()

    normalized = raw
    if re.search(r"[+-]\d{4}$", raw):
        normalized = f"{raw[:-5]}{raw[-5:-2]}:{raw[-2:]}"
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    raise ArtiaError(
        "Invalid started value. Use 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'."
    )


def _date_and_time(started: str) -> tuple[str, str]:
    dt = _started_datetime(started)
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def _build_started(item: dict[str, Any]) -> str:
    date_at = str(item.get("dateAt") or item.get("date") or "").strip()
    start_time = str(item.get("startTime") or item.get("time") or "").strip()
    if date_at and start_time:
        hhmm = start_time[:5]
        return f"{date_at}T{hhmm}:00+00:00"
    if date_at:
        return f"{date_at}T00:00:00+00:00"
    return ""


def _author(item: dict[str, Any]) -> tuple[str, str]:
    for key in ("author", "user", "responsible"):
        value = item.get(key)
        if isinstance(value, dict):
            return _text_value(value), str(value.get("id") or "")
    return "", ""


class ArtiaProvider(BaseProvider):
    def __init__(self, client: ArtiaClient, account_id: str, folder_id: str = "") -> None:
        self._client = client
        self._account_id = account_id
        self._folder_id = folder_id
        self._worklog_status_id = os.getenv("ARTIA_WORKLOG_STATUS_ID", "").strip()

    @classmethod
    def from_env(cls) -> "ArtiaProvider":
        return cls(
            ArtiaClient.from_env(),
            os.getenv("ARTIA_ACCOUNT_ID", "").strip(),
            os.getenv("ARTIA_FOLDER_ID", "").strip(),
        )

    @property
    def name(self) -> str:
        return "artia"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_comments=False, supports_worklogs=True)

    def whoami(self) -> dict[str, Any]:
        try:
            account = self._client.account() or {}
        except ArtiaError as exc:
            detail = (exc.detail or "").lower()
            if self._account_id and (
                "cannot query field" in detail or "unknown field" in detail
            ):
                account = {}
            else:
                raise
        account_id = str(
            account.get("id") or account.get("accountId") or self._account_id or ""
        )
        display_name = (
            account.get("displayName")
            or account.get("name")
            or account.get("fullName")
            or account_id
        )
        return {
            "provider": self.name,
            "ok": bool(account_id),
            "accountId": account_id,
            "displayName": display_name,
        }

    def current_account_id(self) -> str | None:
        return self._account_id or None

    def search_tasks(
        self, query: str = "", max_results: int = 20, native_query: str = ""
    ) -> list[Task]:
        folder_id = (native_query or self._folder_id).strip()
        if not folder_id:
            raise ArtiaError(
                "ARTIA_FOLDER_ID must be set, or native_query must provide a folder id."
            )
        activities = self._client.list_activities(
            folder_id, max_results, query=(query or "").strip()
        )
        if self._account_id:
            mine = [item for item in activities if _responsible_id(item) == self._account_id]
            if mine:
                activities = mine
        tasks: list[Task] = []
        for item in activities:
            tasks.append(
                Task(
                    id=str(item.get("id", "")),
                    provider=self.name,
                    summary=_text_value(item.get("title") or item.get("name") or item.get("summary")),
                    status=_text_value(item.get("status")),
                    task_type=_text_value(item.get("type") or item.get("activityType")),
                    assignee=_text_value(item.get("responsible") or item.get("assignee")),
                    labels=_labels(item),
                    description=str(item.get("description", "") or ""),
                    updated=str(item.get("updatedAt") or item.get("updated_at") or ""),
                    url=str(item.get("url") or item.get("htmlUrl") or item.get("link") or ""),
                )
            )
        return tasks

    def get_task(self, task_id: str) -> Task:
        if not self._account_id:
            raise ArtiaError("ARTIA_ACCOUNT_ID must be set to read an activity.")
        item = self._client.get_activity(self._account_id, task_id) or {}
        return Task(
            id=str(item.get("id", task_id)),
            provider=self.name,
            summary=_text_value(item.get("title") or item.get("name") or item.get("summary")),
            status=_text_value(item.get("status")),
            task_type=_text_value(item.get("type") or item.get("activityType")),
            assignee=_text_value(item.get("responsible") or item.get("assignee")),
            labels=_labels(item),
            description=str(item.get("description", "") or ""),
            updated=str(item.get("updatedAt") or item.get("updated_at") or ""),
            url=str(item.get("url") or item.get("htmlUrl") or item.get("link") or ""),
        )

    def log_work(
        self,
        task_id: str,
        time_spent_seconds: int,
        started: str,
        comment: str = "",
    ) -> Worklog:
        if not self._account_id:
            raise ArtiaError("ARTIA_ACCOUNT_ID must be set to log work.")
        if time_spent_seconds <= 0:
            raise ArtiaError("time_spent_seconds must be greater than zero.")
        date_at, start_time = _date_and_time(started)
        data = self._client.create_time_entry(
            self._account_id,
            task_id,
            date_at,
            start_time,
            time_spent_seconds,
            self._worklog_status_id or None,
        )
        return Worklog(
            id=str(data.get("id") or ""),
            provider=self.name,
            task_id=task_id,
            author="",
            time_spent_seconds=time_spent_seconds,
            time_spent_display=_display_duration(time_spent_seconds),
            started=_build_started({"dateAt": date_at, "startTime": start_time}),
            comment=comment,
        )

    def get_worklogs(self, task_id: str) -> list[Worklog]:
        if not self._account_id:
            raise ArtiaError("ARTIA_ACCOUNT_ID must be set to list worklogs.")
        entries = self._client.list_time_entries(self._account_id, task_id)
        worklogs: list[Worklog] = []
        for item in entries:
            seconds = _to_seconds(item)
            author, author_id = _author(item)
            worklogs.append(
                Worklog(
                    id=str(item.get("id") or ""),
                    provider=self.name,
                    task_id=task_id,
                    author=author,
                    time_spent_seconds=seconds,
                    time_spent_display=_display_duration(seconds),
                    started=_build_started(item),
                    comment=str(item.get("comment") or item.get("description") or ""),
                    author_id=author_id,
                )
            )
        return worklogs