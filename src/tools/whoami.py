"""jira_whoami — validate authentication and return identity when available."""

from __future__ import annotations

from typing import Any

from src.errors import ProviderError
from src.services import get_provider
from src.tools import format_error


def whoami() -> dict[str, Any]:
    """Use this before logging work to validate the configured credentials."""
    try:
        return get_provider().whoami()
    except (ProviderError, ValueError) as exc:
        return format_error(exc)


def register(mcp: Any) -> None:
    mcp.tool(
        name="jira_whoami",
        description="Checks whether Jira authentication works and returns identity when available.",
    )(whoami)
