"""jira_get_worklogs — list worklogs from an issue, optionally only mine."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from src.errors import ProviderError
from src.services import get_provider
from src.tools import format_error


def get_worklogs(
    issue_key: Annotated[str, Field(description="Issue key.")],
    mine_only: Annotated[bool, Field(description="Only my worklogs.")] = False,
) -> dict[str, Any]:
    """Check what was logged in an issue."""
    try:
        provider = get_provider()
        my_account_id = None
        note = None
        if mine_only:
            my_account_id = provider.current_account_id()
            if my_account_id is None:
                note = "mine_only ignored: current user identity is unavailable."
        worklogs = []
        for worklog in provider.get_worklogs(issue_key):
            if (
                mine_only
                and my_account_id is not None
                and worklog.author_id != my_account_id
            ):
                continue
            worklogs.append(
                {
                    "id": worklog.id,
                    "author": worklog.author,
                    "time_spent": worklog.time_spent_display,
                    "started": worklog.started,
                    "comment": worklog.comment,
                }
            )
        output = {"issue_key": issue_key, "count": len(worklogs), "worklogs": worklogs}
        if note:
            output["note"] = note
        return output
    except (ProviderError, ValueError) as exc:
        return format_error(exc)


def register(mcp: Any) -> None:
    mcp.tool(
        name="jira_get_worklogs",
        description="Lists worklogs from one issue. mine_only filters current user's worklogs.",
    )(get_worklogs)
