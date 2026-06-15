"""jira_search_issues — find issues by free text, raw JQL, or the default view."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from src.errors import ProviderError
from src.services import get_provider
from src.tools import format_error


def search_tasks(
    query: Annotated[str, Field(description='Free text. Becomes: text ~ "<query>".')] = "",
    jql: Annotated[str, Field(description="Raw JQL. Takes priority over query.")] = "",
    max_results: Annotated[int, Field(description="Maximum returned issues.")] = 20,
) -> dict[str, Any]:
    """Find an issue key before logging work, or run direct free-text/JQL searches."""
    try:
        tasks = get_provider().search_tasks(
            query=query, max_results=max_results, native_query=jql
        )
        issues = [
            {"key": task.id, "summary": task.summary, "status": task.status}
            for task in tasks
        ]
        return {"count": len(issues), "issues": issues}
    except (ProviderError, ValueError) as exc:
        return format_error(exc)


def register(mcp: Any) -> None:
    mcp.tool(
        name="jira_search_issues",
        description=(
            "Finds Jira issues. No args: current user's open issues. "
            "'query': free text. 'jql': raw JQL."
        ),
    )(search_tasks)
