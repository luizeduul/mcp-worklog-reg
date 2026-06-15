"""jira_add_comment — add a plain-text comment to an issue."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from src.errors import ProviderError
from src.services import get_provider
from src.tools import format_error


def add_comment(
    issue_key: Annotated[str, Field(description="Issue key, for example PROJ-123.")],
    comment: Annotated[str, Field(description="Comment text.")],
) -> dict[str, Any]:
    """Add a single plain-text comment to an issue."""
    try:
        text = (comment or "").strip()
        if not text:
            return {"error": "comment must not be empty."}
        result = get_provider().add_comment(issue_key, text)
        return {
            "id": result.id,
            "issue_key": result.task_id,
            "created": result.created,
        }
    except (ProviderError, ValueError) as exc:
        return format_error(exc)


def register(mcp: Any) -> None:
    mcp.tool(
        name="jira_add_comment",
        description="Adds a comment to an issue. Plain text is converted to Jira ADF.",
    )(add_comment)
