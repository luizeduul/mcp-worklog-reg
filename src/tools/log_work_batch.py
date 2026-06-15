"""jira_log_work_batch — log many worklogs, skipping same-time duplicates."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from src.providers.base import TaskProvider
from src.errors import ProviderError
from src.services import get_provider
from src.utils import instant_minute, parse_time_spent, resolve_started


def _existing_minutes(
    provider: TaskProvider, issue_key: str, cache: dict[str, dict[str, str]]
) -> dict[str, str]:
    """Map 'UTC minute -> worklog id' for an issue, fetched once and cached."""
    if issue_key in cache:
        return cache[issue_key]
    mapping: dict[str, str] = {}
    try:
        for worklog in provider.get_worklogs(issue_key):
            minute_key = instant_minute(worklog.started)
            if minute_key and minute_key not in mapping:
                mapping[minute_key] = worklog.id
    except (ProviderError, ValueError):
        mapping = {}
    cache[issue_key] = mapping
    return mapping


def log_work_batch(
    entries: Annotated[list[dict], Field(description="List of {issue_key, time_spent, started?, comment?}. issue_key may be 'daily'.")],
    skip_duplicates: Annotated[bool, Field(description="Skip entries already logged at the same date/time.")] = True,
) -> dict[str, Any]:
    """Log a full time-sheet, skipping same-time duplicates for user confirmation."""
    provider = get_provider()
    results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    # Phase 1 — normalize each input entry (parse time, resolve started + alias).
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        issue_key = entry.get("issue_key", "?")
        try:
            seconds = parse_time_spent(entry["time_spent"])
            started_jira = resolve_started(entry.get("started", ""))
            target_key, is_daily = provider.resolve_task_alias(
                entry["issue_key"], started_jira
            )
            normalized.append(
                {
                    "task_id": target_key,
                    "seconds": seconds,
                    "started": started_jira,
                    "comment": entry.get("comment", ""),
                    "is_daily": is_daily,
                }
            )
        except (ProviderError, ValueError, KeyError) as exc:
            results.append({"issue_key": issue_key, "ok": False, "error": str(exc)})

    # Phase 2 — let the provider collapse entries (e.g. Redmine: per task/day).
    planned = provider.group_entries(normalized)
    grouped = len(planned) < len(normalized)

    # Phase 3 — log each planned entry, skipping same-time duplicates.
    worklog_cache: dict[str, dict[str, str]] = {}
    for item in planned:
        target_key = item["task_id"]
        try:
            if skip_duplicates:
                existing = _existing_minutes(provider, target_key, worklog_cache)
                minute_key = instant_minute(item["started"])
                if minute_key and minute_key in existing:
                    skipped.append(
                        {
                            "issue_key": target_key,
                            "started": item["started"],
                            "time_spent_seconds": item["seconds"],
                            "existing_worklog_id": existing[minute_key],
                        }
                    )
                    continue
            worklog = provider.log_work(
                target_key, item["seconds"], item["started"], item["comment"]
            )
            row = {
                "issue_key": worklog.task_id,
                "ok": True,
                "id": worklog.id,
                "started": worklog.started,
            }
            if item["is_daily"]:
                row["resolved_from"] = "daily"
            results.append(row)
        except (ProviderError, ValueError) as exc:
            results.append({"issue_key": target_key, "ok": False, "error": str(exc)})

    logged = sum(1 for result in results if result["ok"])
    output: dict[str, Any] = {
        "total": len(entries),
        "logged": logged,
        "failed": len(results) - logged,
        "skipped": len(skipped),
        "skipped_duplicates": skipped,
        "results": results,
    }
    notes: list[str] = []
    if grouped:
        notes.append(
            f"Entries grouped per task/day for '{provider.name}': "
            f"{len(normalized)} entries collapsed into {len(planned)} time "
            "entries (hours summed, descriptions joined)."
        )
    if skipped:
        notes.append(
            "Some entries already have a worklog at the same date/time and were "
            "skipped. Ask the user whether to log them anyway (call jira_log_work "
            "per entry) or leave them as is."
        )
    if notes:
        output["note"] = " ".join(notes)
    return output


def register(mcp: Any) -> None:
    mcp.tool(
        name="jira_log_work_batch",
        description=(
            "Logs multiple worklogs. entries: list of "
            "{issue_key, time_spent, started?, comment?}. issue_key may be 'daily' to "
            "log into the configured monthly bucket (JIRA_DAILY_JQL). By default, "
            "entries that already have a worklog at the same date/time are skipped and "
            "returned for confirmation. Reports each row result."
        ),
    )(log_work_batch)
