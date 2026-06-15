"""TaskProvider protocol and BaseProvider convenience class."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from src.models.comment import Comment
from src.models.provider_capabilities import ProviderCapabilities
from src.models.task import Task
from src.models.worklog import Worklog


@runtime_checkable
class TaskProvider(Protocol):
    """Interface that every provider must satisfy.

    Required methods: :meth:`whoami`, :meth:`search_tasks`, :meth:`get_task`.

    Optional methods (gated by :attr:`capabilities`):
    :meth:`add_comment`, :meth:`log_work`, :meth:`get_worklogs`.
    """

    @property
    def name(self) -> str:
        """Short, unique provider name (e.g. ``"jira"``, ``"github"``)."""
        ...

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Declare which optional operations this provider supports."""
        ...

    # --- Required ---

    def whoami(self) -> dict[str, Any]:
        """Return identity information for the authenticated user."""
        ...

    def search_tasks(
        self, query: str = "", max_results: int = 20, native_query: str = ""
    ) -> list[Task]:
        """Search tasks by free text or provider-native query syntax.

        *native_query* is a raw, provider-specific query (e.g. JQL for Jira) and
        takes priority over *query* when set.
        """
        ...

    def get_task(self, task_id: str) -> Task:
        """Return a single task by its provider-specific identifier."""
        ...

    def resolve_task_alias(self, task_id: str, started: str) -> tuple[str, bool]:
        """Resolve a logical alias (e.g. ``"daily"``) to a concrete task id.

        Returns ``(resolved_id, was_alias)``. Real ids pass through unchanged.
        """
        ...

    def current_account_id(self) -> str | None:
        """Return the authenticated user's account id, or ``None`` if unavailable."""
        ...

    def group_entries(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge normalized batch entries before logging.

        Each entry is a dict with keys ``task_id``, ``seconds``, ``started``,
        ``comment``, ``is_daily``. The default returns them unchanged; providers
        whose time model is coarser (e.g. Redmine, one entry per task/day) may
        collapse entries, summing seconds and joining comments.
        """
        ...

    # --- Optional (gated by capabilities) ---

    def add_comment(self, task_id: str, comment: str) -> Comment:
        """Add a plain-text comment to a task."""
        ...

    def log_work(
        self,
        task_id: str,
        time_spent_seconds: int,
        started: str,
        comment: str = "",
    ) -> Worklog:
        """Log a time-tracking entry on a task."""
        ...

    def get_worklogs(self, task_id: str) -> list[Worklog]:
        """Return all worklogs for a task."""
        ...


class BaseProvider:
    """Convenience base class with default implementations for optional methods.

    Providers *may* extend this instead of implementing the protocol from
    scratch.  The default optional-method implementations raise
    :class:`NotImplementedError` so that a missing override is caught at
    runtime rather than silently returning ``None``.
    """

    @property
    def name(self) -> str:
        raise NotImplementedError

    @property
    def capabilities(self) -> ProviderCapabilities:
        raise NotImplementedError

    def whoami(self) -> dict[str, Any]:
        raise NotImplementedError

    def search_tasks(
        self, query: str = "", max_results: int = 20, native_query: str = ""
    ) -> list[Task]:
        raise NotImplementedError

    def get_task(self, task_id: str) -> Task:
        raise NotImplementedError

    def resolve_task_alias(self, task_id: str, started: str) -> tuple[str, bool]:
        # Default: no provider-specific aliases, the id is already concrete.
        return task_id, False

    def current_account_id(self) -> str | None:
        # Default: identity is unavailable; callers degrade gracefully.
        return None

    def group_entries(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Default: one logged entry per input entry, order preserved.
        return entries

    # Optional — override only when capabilities declare support.

    def add_comment(self, task_id: str, comment: str) -> Comment:
        raise NotImplementedError(
            f"Provider '{self.name}' does not support comments."
        )

    def log_work(
        self,
        task_id: str,
        time_spent_seconds: int,
        started: str,
        comment: str = "",
    ) -> Worklog:
        raise NotImplementedError(
            f"Provider '{self.name}' does not support worklogs."
        )

    def get_worklogs(self, task_id: str) -> list[Worklog]:
        raise NotImplementedError(
            f"Provider '{self.name}' does not support worklogs."
        )
