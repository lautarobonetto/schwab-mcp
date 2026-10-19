"""Redaction filter and auth event logging (FR-006, FR-014)."""

import logging
import sys
from datetime import datetime, timezone
from typing import Set

_secrets: Set[str] = set()
_installed_filters: dict = {}  # logger name -> _RedactionFilter instance

ALLOWED_EVENTS = frozenset({
    "auth_start",
    "auth_success",
    "auth_failure",
    "renew_start",
    "renewal_success",
    "renewal_failure",
})

_ALLOWED_OUTCOMES = {
    "auth_start": {"initiated"},
    "auth_success": {"ok"},
    "auth_failure": {"cancelled", "failed", "refused_concurrent"},
    "renew_start": {"initiated"},
    "renewal_success": {"ok", "not_needed"},
    "renewal_failure": {"connectivity", "reauth_required"},
}


def clear_secrets() -> None:
    """Clear all registered secrets and filter cache (used in tests)."""
    _secrets.clear()
    _installed_filters.clear()


def register_secret(value: str) -> None:
    """Register a secret value that will be redacted from all log records."""
    if value is None:
        raise TypeError("secret value cannot be None")
    if not value or not value.strip():
        raise ValueError("secret cannot be empty")
    _secrets.add(value)


class _RedactionFilter(logging.Filter):
    """A logging Filter that replaces all registered secrets with ``***``."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        redacted = msg
        for secret in sorted(_secrets, key=len, reverse=True):
            redacted = redacted.replace(secret, "***")
        if redacted == msg:
            return True  # No secrets found; pass through unchanged
        record.msg = redacted
        record.args = ()
        return False  # Secrets were redacted


def install_redaction_filter(logger: logging.Logger) -> logging.Filter:
    """Install a redaction filter on *logger*.

    Returns the filter instance so callers can remove it later.
    Idempotent — if a filter is already installed on this logger the
    existing instance is returned.
    """
    key = logger.name
    existing = _installed_filters.get(key)
    if existing is not None:
        return existing
    flt = _RedactionFilter()
    logger.addFilter(flt)
    _installed_filters[key] = flt
    return flt


def auth_event(event: str, outcome: str, detail: str | None = None) -> None:
    """Emit a single-line authentication event to *stderr* (never stdout).

    Format:  ``<ISO-8601 UTC timestamp> auth_event=<event> outcome=<outcome> [detail=<detail>]``

    Parameters
    ----------
    event:
        One of ``ALLOWED_EVENTS``.
    outcome:
        A valid outcome for the given event (see ``_ALLOWED_OUTCOMES``).
    detail:
        Optional free-text detail appended after ``detail=``.  Spaces are
        preserved (the field is the remainder of the line).

    Raises
    ------
    ValueError
        If *event* or *outcome* are not in the allowed set.
    """
    if event not in ALLOWED_EVENTS:
        raise ValueError(f"Invalid auth event: {event!r}")

    outcomes = _ALLOWED_OUTCOMES.get(event)
    if outcome not in outcomes:
        raise ValueError(
            f"Invalid outcome {outcome!r} for event {event!r}"
        )

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z+00:00")

    line = f"{ts} auth_event={event} outcome={outcome}"
    if detail is not None:
        # Redact any registered secrets from the detail text (FR-006).
        for secret in sorted(_secrets, key=len, reverse=True):
            detail = detail.replace(secret, "***")
        line += f" detail={detail}"

    print(line, file=sys.stderr)