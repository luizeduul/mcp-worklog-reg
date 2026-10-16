"""jira_create_issue — create an issue, only after the user approved a preview."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from src.errors import ProviderError
from src.services import get_provider
from src.tools import format_error


def create_issue(
    project: Annotated[str, Field(description="Project key, for example PROJ.")],
    issue_type: Annotated[str, Field(description="Issue type name, for example Task, Bug, Story, Subtask.")],
    summary: Annotated[str, Field(description="Issue title.")],
    description: Annotated[str, Field(description="Plain text; each line becomes a paragraph.")] = "",
    labels: Annotated[list[str] | None, Field(description="Labels.")] = None,
    priority: Annotated[str, Field(description="Priority name, for example High.")] = "",
    parent: Annotated[str, Field(description="Parent issue key (subtask or epic child).")] = "",
    assign_to_me: Annotated[bool, Field(description="Assign the new issue to the current user.")] = False,
    confirm: Annotated[bool, Field(description="false = preview only. true = create; only after the user explicitly approved the preview.")] = False,
) -> dict[str, Any]:
    """Create an issue. Without confirm it only returns the preview."""
    try:
        if not (project or "").strip() or not (issue_type or "").strip() or not (summary or "").strip():
            return {"error": "project, issue_type and summary are required."}
        request = {
            "project": project.strip().upper(),
            "issue_type": issue_type.strip(),
            "summary": summary.strip(),
            "description": (description or "").strip(),
            "labels": labels or [],
            "priority": (priority or "").strip(),
            "parent": (parent or "").strip().upper(),
            "assign_to_me": assign_to_me,
        }
        if not confirm:
            return {
                "created": False,
                "preview": request,
                "note": (
                    "Nothing was created. Show this preview to the user and call "
                    "again with confirm=true only after they explicitly approve it."
                ),
            }
        return {"created": True, **get_provider().create_task(**request)}
    except (ProviderError, ValueError, NotImplementedError) as exc:
        return format_error(exc)


def register(mcp: Any) -> None:
    mcp.tool(
        name="jira_create_issue",
        description=(
            "Creates a Jira issue. Use ONLY when the user explicitly asks to create "
            "one; never on your own initiative. First call with confirm=false to get "
            "a preview, show it, and call with confirm=true only after the user "
            "approves. There is no delete tool."
        ),
    )(create_issue)
