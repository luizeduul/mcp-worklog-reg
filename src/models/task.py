"""Canonical task model returned by all providers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Task:
    """Provider-agnostic representation of a task/issue."""

    id: str
    """Provider-specific identifier (e.g. ``PROJ-123`` for Jira)."""

    provider: str
    """Name of the provider that owns this task (e.g. ``"jira"``)."""

    summary: str
    status: str
    task_type: str = ""
    assignee: str = ""
    priority: str = ""
    labels: list[str] = field(default_factory=list)
    description: str = ""
    updated: str = ""
    url: str = ""
