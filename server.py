"""
MCP server for logging and checking Jira Cloud worklogs.

Tools:
- jira_whoami: confirms auth and returns the current user when available.
- jira_search_issues: finds issue keys from open issues, free text, or raw JQL.
- jira_resolve_daily_issue: finds the daily issue using an env text/template.
- jira_log_work: logs one worklog.
- jira_log_work_batch: logs multiple worklogs and reports each row result.
- jira_get_worklogs: lists worklogs from one issue.
- jira_delete_worklog: deletes one worklog.

Config, loaded from .env next to this file or from the MCP client env:
JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_DAILY_SEARCH_TEXT (optional),
JIRA_DAILY_PROJECT (optional).
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from jira_client import JiraClient, JiraError

# Load .env beside this file, independent of the MCP client's working directory.
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

mcp = FastMCP("JiraWorklogMCP", log_level="ERROR")

_HHMM_RE = re.compile(r"^(\d+):([0-5]\d)$")
_JIRA_DURATION_RE = re.compile(r"(\d+)\s*([hm])")
_MONTH_NAMES_EN = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_MONTH_NAMES_PT = (
    "janeiro",
    "fevereiro",
    "marco",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)


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


def _parse_reference_date(value: str) -> datetime:
    value = (value or "").strip()
    if not value:
        return datetime.now()
    for date_format in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, date_format)
        except ValueError:
            continue
    raise ValueError(
        f"Invalid date/time: '{value}'. Use 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'."
    )


def render_daily_search_text(reference_date: str = "") -> str:
    """
    Render JIRA_DAILY_SEARCH_TEXT for the provided reference date.

    Supported placeholders: {date}, {year}, {month}, {month_number},
    {month_name_en}, {month_name_pt}.
    """
    template = (os.getenv("JIRA_DAILY_SEARCH_TEXT") or "").strip()
    if not template:
        raise ValueError("JIRA_DAILY_SEARCH_TEXT must be set to resolve daily issues.")
    reference_datetime = _parse_reference_date(reference_date)
    values = {
        "date": reference_datetime.strftime("%Y-%m-%d"),
        "year": reference_datetime.strftime("%Y"),
        "month": f"{reference_datetime.month:02d}",
        "month_number": str(reference_datetime.month),
        "month_name_en": _MONTH_NAMES_EN[reference_datetime.month - 1],
        "month_name_pt": _MONTH_NAMES_PT[reference_datetime.month - 1],
    }
    try:
        return template.format(**values).strip()
    except KeyError as exc:
        raise ValueError(
            f"Invalid placeholder in JIRA_DAILY_SEARCH_TEXT: {{{exc.args[0]}}}."
        )


def _escape_jql_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_daily_jql(reference_date: str = "") -> tuple[str, str]:
    search_text = render_daily_search_text(reference_date)
    project_key = (os.getenv("JIRA_DAILY_PROJECT") or "").strip()
    clauses = []
    if project_key:
        clauses.append(f'project = "{_escape_jql_text(project_key)}"')
    clauses.append(f'text ~ "{_escape_jql_text(search_text)}"')
    return " AND ".join(clauses) + " ORDER BY updated DESC", search_text


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
    """Best-effort plain text extraction from an ADF comment."""
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
    """Create the Jira client lazily so importing this module does not require env."""
    return JiraClient.from_env()


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
            safe_query = query.strip().replace('"', '\\"')
            final_jql = f'text ~ "{safe_query}" ORDER BY updated DESC'
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
    name="jira_resolve_daily_issue",
    description=(
        "Finds the daily issue using JIRA_DAILY_SEARCH_TEXT as a search template "
        "and JIRA_DAILY_PROJECT as an optional project filter."
    ),
)
def jira_resolve_daily_issue(
    reference_date: Annotated[str, Field(description="Reference date: 'YYYY-MM-DD'. Empty = today.")] = "",
    max_results: Annotated[int, Field(description="Maximum returned issues.")] = 5,
) -> dict[str, Any]:
    """Resolve a daily row that does not include an explicit issue key."""
    try:
        final_jql, search_text = build_daily_jql(reference_date)
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
        return {
            "jql": final_jql,
            "search_text": search_text,
            "count": len(issues),
            "issues": issues,
        }
    except (JiraError, ValueError) as exc:
        return _error(exc)


def _resolve_started(started: str) -> str:
    if (started or "").strip():
        return to_jira_datetime(started)
    return to_jira_datetime(datetime.now().strftime("%Y-%m-%d %H:%M"))


@mcp.tool(
    name="jira_log_work",
    description=(
        "Logs one worklog. time_spent accepts 'H:MM' (for example '2:40') or "
        "'1h 30m'. started: 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM' (empty = now)."
    ),
)
def jira_log_work(
    issue_key: Annotated[str, Field(description="Issue key, for example PROJ-123.")],
    time_spent: Annotated[str, Field(description="Duration: 'H:MM' or '1h 30m'.")],
    started: Annotated[str, Field(description="Start: 'YYYY-MM-DD HH:MM'. Empty = now.")] = "",
    comment: Annotated[str, Field(description="Worklog comment.")] = "",
) -> dict[str, Any]:
    """Log one worklog in a specific issue."""
    try:
        seconds = parse_time_spent(time_spent)
        started_jira = _resolve_started(started)
        adf_comment = build_adf_comment(comment) if (comment or "").strip() else None
        result = _client().log_work(issue_key, seconds, started_jira, adf_comment)
        return {
            "id": result.get("id"),
            "issue_key": issue_key,
            "time_spent_seconds": seconds,
            "started": started_jira,
        }
    except (JiraError, ValueError) as exc:
        return _error(exc)


@mcp.tool(
    name="jira_log_work_batch",
    description=(
        "Logs multiple worklogs. entries: list of "
        "{issue_key, time_spent, started?, comment?}. Reports each row result."
    ),
)
def jira_log_work_batch(
    entries: Annotated[list[dict], Field(description="List of {issue_key, time_spent, started?, comment?}.")],
) -> dict[str, Any]:
    """Log a full time-sheet preview after user confirmation."""
    client = _client()
    results: list[dict[str, Any]] = []
    for entry in entries:
        issue_key = entry.get("issue_key", "?")
        try:
            seconds = parse_time_spent(entry["time_spent"])
            started_jira = _resolve_started(entry.get("started", ""))
            comment = entry.get("comment", "")
            adf_comment = build_adf_comment(comment) if (comment or "").strip() else None
            result = client.log_work(entry["issue_key"], seconds, started_jira, adf_comment)
            results.append(
                {
                    "issue_key": issue_key,
                    "ok": True,
                    "id": result.get("id"),
                    "started": started_jira,
                }
            )
        except (JiraError, ValueError, KeyError) as exc:
            results.append({"issue_key": issue_key, "ok": False, "error": str(exc)})
    ok_count = sum(1 for result in results if result["ok"])
    return {
        "total": len(results),
        "ok": ok_count,
        "failed": len(results) - ok_count,
        "results": results,
    }


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


@mcp.tool(
    name="jira_delete_worklog",
    description="Deletes one worklog. Requires permission to delete Jira worklogs.",
)
def jira_delete_worklog(
    issue_key: Annotated[str, Field(description="Issue key.")],
    worklog_id: Annotated[str, Field(description="Worklog ID from jira_get_worklogs.")],
) -> dict[str, Any]:
    """Delete a wrong worklog entry."""
    try:
        return _client().delete_worklog(issue_key, worklog_id)
    except (JiraError, ValueError) as exc:
        return _error(exc)


@mcp.tool(
    name="jira_ensure_person_daily",
    description=(
        "Checks whether a '<person> <month> de <year>' issue exists on the GREDOM board "
        "for the given month/year. If not found, searches for the GREDOM project generically "
        "and creates the issue, assigning it to the current user. "
        "person_name defaults to JIRA_DAILY_PERSON_NAME env var. "
        "Trigger this when the term 'daily' or 'dayli' is used."
    ),
)
def jira_ensure_person_daily(
    reference_date: Annotated[str, Field(description="Reference date 'YYYY-MM-DD'. Empty = today.")] = "",
    person_name: Annotated[str, Field(description="Person name for the summary. Empty = JIRA_DAILY_PERSON_NAME env var.")] = "",
) -> dict[str, Any]:
    """Ensure the monthly person daily issue exists on the GREDOM board."""
    try:
        name = (person_name or "").strip() or (os.getenv("JIRA_DAILY_PERSON_NAME") or "").strip()
        if not name:
            return {"error": "person_name is required (or set JIRA_DAILY_PERSON_NAME in env)."}

        ref = _parse_reference_date(reference_date)
        month_name_pt = _MONTH_NAMES_PT[ref.month - 1]
        year = ref.strftime("%Y")
        expected_summary = f"{name} {month_name_pt} de {year}"

        client = _client()

        # Search for existing issue
        safe = _escape_jql_text(expected_summary)
        jql = f'text ~ "{safe}" ORDER BY created DESC'
        data = client.search_issues(jql, max_results=5)
        issues = [
            {
                "key": item.get("key"),
                "summary": (item.get("fields") or {}).get("summary"),
            }
            for item in data.get("issues", [])
        ]
        if issues:
            return {"found": True, "summary": expected_summary, "issues": issues}

        # Not found — locate GREDOM project
        projects = client.search_projects("GREDOM")
        if not projects:
            return {"error": "GREDOM project not found via search."}
        project_key = projects[0]["key"]

        # Resolve current user for assignee
        user = client.current_user()
        assignee_id = user.get("accountId") if user else None

        # Create the issue
        created = client.create_issue(project_key, expected_summary, assignee_account_id=assignee_id)
        return {
            "found": False,
            "created": True,
            "key": created.get("key"),
            "summary": expected_summary,
            "project": project_key,
            "assignee": assignee_id,
        }
    except (JiraError, ValueError) as exc:
        return _error(exc)


if __name__ == "__main__":
    mcp.run(transport="stdio")
