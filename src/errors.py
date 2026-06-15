"""Shared provider error type.

Lives at the package root (not under ``src.providers``) so the HTTP clients can
import it without triggering the providers package ``__init__``, which would
create an import cycle.

Every provider raises a :class:`ProviderError` (or a subclass) for handled,
user-facing failures so the tool layer can catch one type across providers.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Handled provider error with a user-friendly message."""

    def __init__(
        self,
        message: str,
        status: int | None = None,
        detail: str | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status = status
        self.detail = detail
