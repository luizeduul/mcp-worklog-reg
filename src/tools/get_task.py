"""jira_get_issue — compact view of a single issue."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from src.errors import ProviderError
from src.services import get_provider
from src.tools import format_error


def get_task(
    issue_key: Annotated[str, Field(description="Issue key, for example PROJ-123.")],
) -> dict[str, Any]:
    """Read a single issue without the heavy raw Jira payload."""
    try:
        task = get_provider().get_task(issue_key)
        return {
            "key": task.id,
            "summary": task.summary,
            "status": task.status,
            "type": task.task_type,
            "assignee": task.assignee,
            "priority": task.priority,
            "labels": task.labels,
            "updated": task.updated,
            "description": task.description,
        }
    except (ProviderError, ValueError) as exc:
        return format_error(exc)


def register(mcp: Any) -> None:
    mcp.tool(
        name="jira_get_issue",
        description=(
            "Returns a compact view of one issue: key, summary, status, type, "
            "assignee, priority, labels, and description text."
        ),
    )(get_task)
