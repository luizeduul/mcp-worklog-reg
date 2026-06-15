"""Canonical comment model returned by providers that support comments."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Comment:
    """Provider-agnostic representation of a task comment."""

    id: str
    provider: str
    task_id: str
    author: str
    body: str
    created: str
