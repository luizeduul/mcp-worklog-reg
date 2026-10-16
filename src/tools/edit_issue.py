"""jira_edit_issue — edit an issue created by or assigned to the current user."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from src.errors import ProviderError
from src.services import get_provider
from src.tools import format_error


def edit_issue(
    issue_key: Annotated[str, Field(description="Issue key, for example PROJ-123.")],
    summary: Annotated[str | None, Field(description="New title. Omit to keep.")] = None,
    description: Annotated[str | None, Field(description="New description (replaces the old one). Omit to keep.")] = None,
    labels: Annotated[list[str] | None, Field(description="New labels (replaces all). Omit to keep; [] clears.")] = None,
    priority: Annotated[str | None, Field(description="New priority name. Omit to keep.")] = None,
    confirm: Annotated[bool, Field(description="false = preview only. true = save; only after the user explicitly approved the preview.")] = False,
) -> dict[str, Any]:
    """Edit an issue. Without confirm it only returns the preview."""
    try:
        changes: dict[str, Any] = {}
        if summary is not None:
            if not summary.strip():
                return {"error": "summary must not be empty."}
            changes["summary"] = summary.strip()
        if description is not None:
            changes["description"] = description.strip()
        if labels is not None:
            changes["labels"] = labels
        if priority is not None:
            changes["priority"] = priority.strip()
        if not changes:
            return {"error": "Nothing to change. Pass summary, description, labels or priority."}

        provider = get_provider()
        if not confirm:
            key = provider.ensure_editable(issue_key)
            current = provider.get_task(key)
            current_values = {
                "summary": current.summary,
                "description": current.description,
                "labels": current.labels,
                "priority": current.priority,
            }
            return {
                "updated": False,
                "issue_key": key,
                "current": {field: current_values[field] for field in changes},
                "changes": changes,
                "note": (
                    "Nothing was saved. Show this preview to the user and call "
                    "again with confirm=true only after they explicitly approve it."
                ),
            }
        provider.update_task(issue_key, changes)
        return {
            "updated": True,
            "issue_key": issue_key.strip().upper(),
            "fields": sorted(changes),
        }
    except (ProviderError, ValueError, NotImplementedError) as exc:
        return format_error(exc)


def register(mcp: Any) -> None:
    mcp.tool(
        name="jira_edit_issue",
        description=(
            "Edits summary, description, labels or priority of a Jira issue. Only "
            "issues created by the current user or assigned to them can be edited "
            "(enforced by the server). Use ONLY when the user explicitly asks; "
            "first call with confirm=false to get a preview, show it, and call with "
            "confirm=true only after the user approves. There is no delete tool."
        ),
    )(edit_issue)
