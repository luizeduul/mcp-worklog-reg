"""Maps provider names to provider instances (lazy singletons).

Providers are built on first use so importing this module never requires
credentials. Caching the instance keeps per-provider state (e.g. the Jira daily
bucket cache) warm across a batch and across tool calls.
"""

from __future__ import annotations

from collections.abc import Callable

from src.config import DEFAULT_PROVIDER
from src.providers.base import TaskProvider
from src.providers.artia_provider import ArtiaProvider
from src.providers.github_provider import GitHubProvider
from src.providers.jira_provider import JiraProvider
from src.providers.redmine_provider import RedmineProvider


class ProviderRegistry:
    """Registry of provider factories with lazily-built, cached instances."""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], TaskProvider]] = {}
        self._instances: dict[str, TaskProvider] = {}

    def register(self, name: str, factory: Callable[[], TaskProvider]) -> None:
        self._factories[name] = factory

    def get(self, name: str | None = None) -> TaskProvider:
        name = name or DEFAULT_PROVIDER
        if name not in self._instances:
            try:
                factory = self._factories[name]
            except KeyError:
                known = ", ".join(sorted(self._factories)) or "none"
                raise KeyError(
                    f"Unknown provider '{name}'. Registered: {known}."
                )
            self._instances[name] = factory()
        return self._instances[name]

    def reset(self) -> None:
        """Drop cached instances so the next :meth:`get` rebuilds them."""
        self._instances.clear()


registry = ProviderRegistry()
registry.register("artia", ArtiaProvider.from_env)
registry.register("jira", JiraProvider.from_env)
registry.register("redmine", RedmineProvider.from_env)
registry.register("github", GitHubProvider.from_env)


def get_provider(name: str | None = None) -> TaskProvider:
    """Return the active (or named) provider from the default registry."""
    return registry.get(name)
