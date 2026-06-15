"""Provider-agnostic utility functions."""

from __future__ import annotations

import re
from datetime import datetime, timezone


_HHMM_RE = re.compile(r"^(\d+):([0-5]\d)$")
_DURATION_RE = re.compile(r"(\d+)\s*([hm])")


def parse_time_spent(value: str) -> int:
    """Convert ``'2:40'`` (H:MM), ``'1h 30m'``, ``'45m'``, or ``'2h'`` to seconds.

    Raises :class:`ValueError` on invalid or zero-length durations.
    """
    value = (value or "").strip()
    match = _HHMM_RE.match(value)
    if match:
        seconds = (int(match.group(1)) * 60 + int(match.group(2))) * 60
    else:
        total_seconds = 0
        found_duration = False
        for amount, unit in _DURATION_RE.findall(value.lower()):
            found_duration = True
            total_seconds += int(amount) * (3600 if unit == "h" else 60)
        if not found_duration:
            raise ValueError(
                f"Invalid time value: '{value}'. Use 'H:MM' (for example '2:40') "
                "or '1h 30m'."
            )
        seconds = total_seconds
    if seconds <= 0:
        raise ValueError("Time spent must be greater than zero.")
    return seconds


def to_jira_datetime(value: str) -> str:
    """Convert ``'YYYY-MM-DD'`` or ``'YYYY-MM-DD HH:MM[:SS]'`` to Jira's
    datetime format with the local machine offset.

    Raises :class:`ValueError` when *value* cannot be parsed.
    """
    value = (value or "").strip()
    parsed_datetime = None
    for date_format in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed_datetime = datetime.strptime(value, date_format)
            break
        except ValueError:
            continue
    if parsed_datetime is None:
        raise ValueError(
            f"Invalid date/time: '{value}'. Use 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'."
        )
    local_datetime = parsed_datetime.astimezone()
    milliseconds = f"{local_datetime.microsecond // 1000:03d}"
    return (
        local_datetime.strftime("%Y-%m-%dT%H:%M:%S.")
        + milliseconds
        + local_datetime.strftime("%z")
    )


def resolve_started(started: str) -> str:
    """Return a Jira-formatted datetime, defaulting to *now* when *started* is empty."""
    if (started or "").strip():
        return to_jira_datetime(started)
    return to_jira_datetime(datetime.now().strftime("%Y-%m-%d %H:%M"))


def instant_minute(value: str) -> str | None:
    """Normalize a datetime string to a UTC ``YYYY-MM-DDTHH:MM`` key for duplicate
    detection. Returns ``None`` when *value* cannot be parsed."""
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")
