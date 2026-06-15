"""MCP tools. Each module exposes a plain function plus a ``register(mcp)`` hook.

Functions are provider-agnostic: they call the active provider through
:func:`src.services.get_provider` and serialise canonical models into compact,
LLM-friendly dictionaries.
"""

from __future__ import annotations

from typing import Any

from src.errors import ProviderError


def format_error(exc: Exception) -> dict[str, Any]:
    """Render a handled exception as a structured, single-line error payload."""
    if isinstance(exc, ProviderError):
        output: dict[str, Any] = {"error": exc.message}
        if exc.detail:
            output["detail"] = exc.detail
        return output
    return {"error": str(exc)}


def register_all(mcp: Any) -> None:
    """Register every tool on the given FastMCP instance."""
    from src.tools import (
        add_comment,
        get_task,
        get_worklogs,
        log_work,
        log_work_batch,
        search_tasks,
        whoami,
    )

    for module in (
        whoami,
        search_tasks,
        get_task,
        add_comment,
        log_work,
        log_work_batch,
        get_worklogs,
    ):
        module.register(mcp)
