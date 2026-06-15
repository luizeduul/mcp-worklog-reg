"""Canonical worklog model returned by providers that support worklogs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Worklog:
    """Provider-agnostic representation of a time-tracking entry."""

    id: str
    provider: str
    task_id: str
    author: str
    time_spent_seconds: int
    time_spent_display: str
    """Human-readable duration, e.g. ``"2h 40m"``."""

    started: str
    comment: str = ""
    author_id: str = ""
    """Provider-specific account identifier of the author, used to filter
    'my worklogs'. Empty when the provider does not expose it."""
