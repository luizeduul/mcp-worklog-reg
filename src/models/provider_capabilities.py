"""Declares which optional operations a provider supports."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Feature flags exposed by each provider.

    Tools check these before dispatching optional operations so that
    unsupported calls are rejected early with a clear message.
    """

    supports_comments: bool = False
    supports_worklogs: bool = False
