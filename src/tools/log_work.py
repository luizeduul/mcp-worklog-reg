"""jira_log_work — log one worklog, resolving the 'daily' bucket when used."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from src.errors import ProviderError
from src.services import get_provider
from src.tools import format_error
from src.utils import parse_time_spent, resolve_started


def log_work(
    issue_key: Annotated[str, Field(description="Issue key (e.g. PROJ-123), or 'daily' for the monthly bucket.")],
    time_spent: Annotated[str, Field(description="Duration: 'H:MM' or '1h 30m'.")],
    started: Annotated[str, Field(description="Start: 'YYYY-MM-DD HH:MM'. Empty = now.")] = "",
    comment: Annotated[str, Field(description="Worklog comment.")] = "",
) -> dict[str, Any]:
    """Log one worklog in a specific issue."""
    try:
        seconds = parse_time_spent(time_spent)
        started_jira = resolve_started(started)
        provider = get_provider()
        target_key, is_daily = provider.resolve_task_alias(issue_key, started_jira)
        worklog = provider.log_work(target_key, seconds, started_jira, comment)
        output = {
            "id": worklog.id,
            "issue_key": worklog.task_id,
            "time_spent_seconds": seconds,
            "started": worklog.started,
        }
        if is_daily:
            output["resolved_from"] = "daily"
        return output
    except (ProviderError, ValueError) as exc:
        return format_error(exc)


def register(mcp: Any) -> None:
    mcp.tool(
        name="jira_log_work",
        description=(
            "Logs one worklog. time_spent accepts 'H:MM' (for example '2:40') or "
            "'1h 30m'. started: 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM' (empty = now). "
            "Set issue_key='daily' to log into the configured monthly bucket "
            "(JIRA_DAILY_JQL) instead of guessing the key."
        ),
    )(log_work)
