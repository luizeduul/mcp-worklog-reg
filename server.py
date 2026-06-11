"""
MCP server for reading Jira Cloud issues/worklogs and logging time.

This server is read/append only by design (least privilege). It can search and
read issues, read and log worklogs, and add comments. It CANNOT create, edit,
transition, assign, or delete issues, comments, or worklogs.

Tools:
- jira_whoami: confirms auth and returns the current user when available.
- jira_search_issues: finds issues from open issues, free text, or raw JQL.
- jira_get_issue: returns a compact view of one issue.
- jira_add_comment: adds a comment to an issue.
- jira_log_work: logs one worklog.
- jira_log_work_batch: logs multiple worklogs, skipping same-time duplicates.
- jira_get_worklogs: lists worklogs from one issue.

Daily bucket: pass issue_key="daily" (or "dayli") to log into a recurring monthly
issue without guessing its key. The server resolves it via the JIRA_DAILY_JQL
template, filling {month}/{year} from the worklog date. Disabled if unset.

Config, loaded from .env next to this file (optional) or from the MCP client env:
JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN. Optional: JIRA_DAILY_JQL.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from jira_client import JiraClient, JiraError

# Load .env beside this file if present. The file is optional; missing .env is fine.
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

mcp = FastMCP("JiraWorklogMCP", log_level="ERROR")

_HHMM_RE = re.compile(r"^(\d+):([0-5]\d)$")
_JIRA_DURATION_RE = re.compile(r"(\d+)\s*([hm])")

# Issue-key sentinels that mean "the recurring monthly bucket", resolved from the
# JIRA_DAILY_JQL template instead of being treated as a literal issue key.
_DAILY_SENTINELS = {"daily", "dayli"}
_PT_MONTHS = (
    "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
)
_DAILY_JQL_EXAMPLE = 'project = MYPROJ AND summary ~ "Timesheet {month} de {year}" ORDER BY created DESC'


def parse_time_spent(value: str) -> int:
    """Convert '2:40' (H:MM), '1h 30m', '45m', or '2h' to seconds."""
    value = (value or "").strip()
    match = _HHMM_RE.match(value)
    if match:
        seconds = (int(match.group(1)) * 60 + int(match.group(2))) * 60
    else:
        total_seconds = 0
        found_duration = False
        for amount, unit in _JIRA_DURATION_RE.findall(value.lower()):
            found_duration = True
            total_seconds += int(amount) * (3600 if unit == "h" else 60)
        if not found_duration:
            raise ValueError(
                f"Invalid time value: '{value}'. Use 'H:MM' (for example '2:40') "
                "or '1h 30m'."
            )
        seconds = total_seconds
    if seconds <= 0:
        raise ValueError("Time spent must be greater than zero.")
    return seconds


def to_jira_datetime(value: str) -> str:
    """
    Convert 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM[:SS]' to Jira's datetime format
    with the local machine offset.
    """
    value = (value or "").strip()
    parsed_datetime = None
    for date_format in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed_datetime = datetime.strptime(value, date_format)
            break
        except ValueError:
            continue
    if parsed_datetime is None:
        raise ValueError(
            f"Invalid date/time: '{value}'. Use 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'."
        )
    local_datetime = parsed_datetime.astimezone()
    milliseconds = f"{local_datetime.microsecond // 1000:03d}"
    return (
        local_datetime.strftime("%Y-%m-%dT%H:%M:%S.")
        + milliseconds
        + local_datetime.strftime("%z")
    )


def _escape_jql_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_adf_comment(text: str) -> dict[str, Any]:
    """Build a one-paragraph ADF comment."""
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


def _error(exc: Exception) -> dict[str, Any]:
    """Format handled exceptions as structured output."""
    if isinstance(exc, JiraError):
        output: dict[str, Any] = {"error": exc.message}
        if exc.detail:
            output["detail"] = exc.detail
        return output
    return {"error": str(exc)}


def _client() -> JiraClient:
    """Build the Jira client lazily so importing this module does not require env."""
    return JiraClient.from_env()


def _resolve_started(started: str) -> str:
    if (started or "").strip():
        return to_jira_datetime(started)
    return to_jira_datetime(datetime.now().strftime("%Y-%m-%d %H:%M"))


def _is_daily_key(issue_key: str) -> bool:
    return (issue_key or "").strip().lower() in _DAILY_SENTINELS


def _render_daily_jql(template: str, started_jira: str) -> str:
    """Fill {month}/{month_num}/{year} from the worklog date into the JQL template."""
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
    """
    Resolve a 'daily'/'dayli' sentinel to the month's bucket issue via JIRA_DAILY_JQL.

    Returns (resolved_key, is_daily). Non-sentinel keys pass through unchanged.
    The cache maps a rendered JQL to its resolved key so a batch searches once per month.
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


def _instant_minute(value: str) -> str | None:
    """Normalize a Jira datetime to a UTC minute key for duplicate detection."""
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")


def _existing_worklog_minutes(
    client: JiraClient, issue_key: str, cache: dict[str, dict[str, str]]
) -> dict[str, str]:
    """Map 'UTC minute -> worklog id' for an issue, fetched once and cached."""
    if issue_key in cache:
        return cache[issue_key]
    mapping: dict[str, str] = {}
    try:
        data = client.get_worklogs(issue_key)
        for worklog in data.get("worklogs", []):
            minute_key = _instant_minute(worklog.get("started", ""))
            if minute_key and minute_key not in mapping:
                mapping[minute_key] = worklog.get("id")
    except JiraError:
        mapping = {}
    cache[issue_key] = mapping
    return mapping


@mcp.tool(
    name="jira_whoami",
    description="Checks whether Jira authentication works and returns identity when available.",
)
def jira_whoami() -> dict[str, Any]:
    """
    Use this before logging work to validate JIRA_BASE_URL, JIRA_EMAIL, and
    JIRA_API_TOKEN.
    """
    try:
        client = _client()
        user = client.current_user()
        if user:
            return {
                "ok": True,
                "accountId": user.get("accountId"),
                "displayName": user.get("displayName"),
                "emailAddress": user.get("emailAddress"),
            }
        client.search_issues("assignee = currentUser() ORDER BY updated DESC", 1)
        return {
            "ok": True,
            "identity": os.getenv("JIRA_EMAIL"),
            "note": (
                "This token cannot access /myself; identity comes from JIRA_EMAIL. "
                "Auth was validated with an issue search."
            ),
        }
    except (JiraError, ValueError) as exc:
        return _error(exc)


@mcp.tool(
    name="jira_search_issues",
    description=(
        "Finds Jira issues. No args: current user's open issues. "
        "'query': free text. 'jql': raw JQL."
    ),
)
def jira_search_issues(
    query: Annotated[str, Field(description='Free text. Becomes: text ~ "<query>".')] = "",
    jql: Annotated[str, Field(description="Raw JQL. Takes priority over query.")] = "",
    max_results: Annotated[int, Field(description="Maximum returned issues.")] = 20,
) -> dict[str, Any]:
    """Find an issue key before logging work, or run direct free-text/JQL searches."""
    try:
        if (jql or "").strip():
            final_jql = jql.strip()
        elif (query or "").strip():
            final_jql = f'text ~ "{_escape_jql_text(query.strip())}" ORDER BY updated DESC'
        else:
            final_jql = (
                "assignee = currentUser() AND statusCategory != Done "
                "ORDER BY updated DESC"
            )
        data = _client().search_issues(final_jql, max_results)
        issues = []
        for item in data.get("issues", []):
            fields = item.get("fields") or {}
            status = fields.get("status") or {}
            issues.append(
                {
                    "key": item.get("key"),
                    "summary": fields.get("summary"),
                    "status": status.get("name"),
                }
            )
        return {"jql": final_jql, "count": len(issues), "issues": issues}
    except (JiraError, ValueError) as exc:
        return _error(exc)


@mcp.tool(
    name="jira_get_issue",
    description=(
        "Returns a compact view of one issue: key, summary, status, type, "
        "assignee, priority, labels, and description text."
    ),
)
def jira_get_issue(
    issue_key: Annotated[str, Field(description="Issue key, for example PROJ-123.")],
) -> dict[str, Any]:
    """Read a single issue without the heavy raw Jira payload."""
    try:
        data = _client().get_issue(issue_key)
        fields = data.get("fields") or {}
        status = fields.get("status") or {}
        issue_type = fields.get("issuetype") or {}
        assignee = fields.get("assignee") or {}
        priority = fields.get("priority") or {}
        return {
            "key": data.get("key"),
            "summary": fields.get("summary"),
            "status": status.get("name"),
            "type": issue_type.get("name"),
            "assignee": assignee.get("displayName"),
            "priority": priority.get("name"),
            "labels": fields.get("labels") or [],
            "updated": fields.get("updated"),
            "description": _adf_to_text(fields.get("description")),
        }
    except (JiraError, ValueError) as exc:
        return _error(exc)


@mcp.tool(
    name="jira_add_comment",
    description="Adds a comment to an issue. Plain text is converted to Jira ADF.",
)
def jira_add_comment(
    issue_key: Annotated[str, Field(description="Issue key, for example PROJ-123.")],
    comment: Annotated[str, Field(description="Comment text.")],
) -> dict[str, Any]:
    """Add a single plain-text comment to an issue."""
    try:
        text = (comment or "").strip()
        if not text:
            return {"error": "comment must not be empty."}
        result = _client().add_comment(issue_key, build_adf_comment(text))
        return {
            "id": result.get("id"),
            "issue_key": issue_key,
            "created": result.get("created"),
        }
    except (JiraError, ValueError) as exc:
        return _error(exc)


@mcp.tool(
    name="jira_log_work",
    description=(
        "Logs one worklog. time_spent accepts 'H:MM' (for example '2:40') or "
        "'1h 30m'. started: 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM' (empty = now). "
        "Set issue_key='daily' to log into the configured monthly bucket "
        "(JIRA_DAILY_JQL) instead of guessing the key."
    ),
)
def jira_log_work(
    issue_key: Annotated[str, Field(description="Issue key (e.g. PROJ-123), or 'daily' for the monthly bucket.")],
    time_spent: Annotated[str, Field(description="Duration: 'H:MM' or '1h 30m'.")],
    started: Annotated[str, Field(description="Start: 'YYYY-MM-DD HH:MM'. Empty = now.")] = "",
    comment: Annotated[str, Field(description="Worklog comment.")] = "",
) -> dict[str, Any]:
    """Log one worklog in a specific issue."""
    try:
        seconds = parse_time_spent(time_spent)
        started_jira = _resolve_started(started)
        client = _client()
        target_key, is_daily = _resolve_issue_key(client, issue_key, started_jira, {})
        adf_comment = build_adf_comment(comment) if (comment or "").strip() else None
        result = client.log_work(target_key, seconds, started_jira, adf_comment)
        output = {
            "id": result.get("id"),
            "issue_key": target_key,
            "time_spent_seconds": seconds,
            "started": started_jira,
        }
        if is_daily:
            output["resolved_from"] = "daily"
        return output
    except (JiraError, ValueError) as exc:
        return _error(exc)


@mcp.tool(
    name="jira_log_work_batch",
    description=(
        "Logs multiple worklogs. entries: list of "
        "{issue_key, time_spent, started?, comment?}. issue_key may be 'daily' to "
        "log into the configured monthly bucket (JIRA_DAILY_JQL). By default, "
        "entries that already have a worklog at the same date/time are skipped and "
        "returned for confirmation. Reports each row result."
    ),
)
def jira_log_work_batch(
    entries: Annotated[list[dict], Field(description="List of {issue_key, time_spent, started?, comment?}. issue_key may be 'daily'.")],
    skip_duplicates: Annotated[bool, Field(description="Skip entries already logged at the same date/time.")] = True,
) -> dict[str, Any]:
    """Log a full time-sheet, skipping same-time duplicates for user confirmation."""
    client = _client()
    results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    worklog_cache: dict[str, dict[str, str]] = {}
    daily_cache: dict[str, str] = {}
    for entry in entries:
        issue_key = entry.get("issue_key", "?")
        try:
            seconds = parse_time_spent(entry["time_spent"])
            started_jira = _resolve_started(entry.get("started", ""))
            target_key, is_daily = _resolve_issue_key(
                client, entry["issue_key"], started_jira, daily_cache
            )
            if skip_duplicates:
                existing = _existing_worklog_minutes(client, target_key, worklog_cache)
                minute_key = _instant_minute(started_jira)
                if minute_key and minute_key in existing:
                    skipped.append(
                        {
                            "issue_key": target_key,
                            "started": started_jira,
                            "time_spent": entry.get("time_spent"),
                            "existing_worklog_id": existing[minute_key],
                        }
                    )
                    continue
            comment = entry.get("comment", "")
            adf_comment = build_adf_comment(comment) if (comment or "").strip() else None
            result = client.log_work(target_key, seconds, started_jira, adf_comment)
            row = {
                "issue_key": target_key,
                "ok": True,
                "id": result.get("id"),
                "started": started_jira,
            }
            if is_daily:
                row["resolved_from"] = "daily"
            results.append(row)
        except (JiraError, ValueError, KeyError) as exc:
            results.append({"issue_key": issue_key, "ok": False, "error": str(exc)})
    logged = sum(1 for result in results if result["ok"])
    output: dict[str, Any] = {
        "total": len(entries),
        "logged": logged,
        "failed": len(results) - logged,
        "skipped": len(skipped),
        "skipped_duplicates": skipped,
        "results": results,
    }
    if skipped:
        output["note"] = (
            "Some entries already have a worklog at the same date/time and were "
            "skipped. Ask the user whether to log them anyway (call jira_log_work "
            "per entry) or leave them as is."
        )
    return output


@mcp.tool(
    name="jira_get_worklogs",
    description="Lists worklogs from one issue. mine_only filters current user's worklogs.",
)
def jira_get_worklogs(
    issue_key: Annotated[str, Field(description="Issue key.")],
    mine_only: Annotated[bool, Field(description="Only my worklogs.")] = False,
) -> dict[str, Any]:
    """Check what was logged in an issue."""
    try:
        client = _client()
        data = client.get_worklogs(issue_key)
        current_account_id = None
        note = None
        if mine_only:
            user = client.current_user()
            current_account_id = user.get("accountId") if user else None
            if current_account_id is None:
                note = "mine_only ignored: current user identity is unavailable."
        worklogs = []
        for worklog in data.get("worklogs", []):
            author = worklog.get("author") or {}
            if (
                mine_only
                and current_account_id is not None
                and author.get("accountId") != current_account_id
            ):
                continue
            worklogs.append(
                {
                    "id": worklog.get("id"),
                    "author": author.get("displayName"),
                    "time_spent": worklog.get("timeSpent"),
                    "started": worklog.get("started"),
                    "comment": _adf_to_text(worklog.get("comment")),
                }
            )
        output = {"issue_key": issue_key, "count": len(worklogs), "worklogs": worklogs}
        if note:
            output["note"] = note
        return output
    except (JiraError, ValueError) as exc:
        return _error(exc)


if __name__ == "__main__":
    mcp.run(transport="stdio")
