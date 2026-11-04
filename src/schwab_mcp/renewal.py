"""Token renewal and auth-health support.

Three responsibilities (td-018 docstring fix — this module is more than
value types):

- Value types: ``RenewalOutcome`` (FR-003) and ``AuthHealth`` (FR-008),
  frozen dataclasses that serialise to a single compact JSON line.
- The renewal orchestrator: ``renew`` / ``_do_renew`` with per-store-path
  single-flight locks (``_renew_locks``).
- The store lifetime reader (FR-008, research.md D5): ``StoreLifetime`` /
  ``read_store_lifetime``.

No secret/credential values are ever included in payloads (FR-004).
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import logging
import os
import threading
import time
from typing import Optional

from schwab_mcp.errors import (
    ConnectivityError,
    ReauthorizationRequiredError,
)
from schwab_mcp.log import auth_event
from schwab_mcp.provider import response_json
from schwab_mcp.tokens import _read_schwabdev_row
from schwab_mcp.tokens import issued_to_epoch as _tokens_issued_to_epoch


_VALID_OUTCOMES = frozenset(
    {"renewed", "not_needed", "transient_failure", "reauth_required"}
)
_VALID_DETAILS = frozenset(
    {
        "access_renewed",
        "still_valid",
        "provider_unreachable",
        "refresh_rejected",
        "renewal_unverified",
        "reauth_needed",
        "store_absent",
        "store_corrupted",
    }
)
_VALID_STATES = frozenset({"valid", "reauth_required", "store_absent", "store_corrupted"})


@dataclasses.dataclass(frozen=True)
class RenewalOutcome:
    """Structured result for a single token renewal attempt (FR-003)."""

    outcome: str
    expires_in_seconds: Optional[int]
    retryable: bool
    detail: str

    def __post_init__(self) -> None:
        if self.outcome not in _VALID_OUTCOMES:
            raise ValueError(f"Invalid outcome: {self.outcome!r}")
        if self.detail not in _VALID_DETAILS:
            raise ValueError(f"Invalid detail: {self.detail!r}")
        if self.expires_in_seconds is not None and self.expires_in_seconds < 0:
            raise ValueError(
                f"expires_in_seconds must be >= 0, got {self.expires_in_seconds}"
            )
        if self.outcome in ("renewed", "not_needed") and self.retryable:
            raise ValueError(
                f"{self.outcome} must have retryable=False"
            )
        if self.outcome == "transient_failure" and not self.retryable:
            raise ValueError("transient_failure must have retryable=True")

    def to_json(self) -> str:
        """Serialize to a compact single-line JSON string."""
        return json.dumps(
            dataclasses.asdict(self), separators=(",", ":"), sort_keys=True
        )

    @classmethod
    def from_json(cls, data: str) -> "RenewalOutcome":
        """Deserialize from a compact JSON string produced by to_json()."""
        return cls(**json.loads(data))


@dataclasses.dataclass(frozen=True)
class AuthHealth:
    """Result of the authentication health query (FR-008)."""

    state: str
    access_expires_in_seconds: Optional[int]
    refresh_expires_in_seconds: Optional[int]

    def __post_init__(self) -> None:
        if self.state not in _VALID_STATES:
            raise ValueError(f"Invalid state: {self.state!r}")
        for field in ("access_expires_in_seconds", "refresh_expires_in_seconds"):
            val = getattr(self, field)
            if val is not None and val < 0:
                raise ValueError(f"{field} must be >= 0, got {val}")

    def to_json(self) -> str:
        """Serialize to a compact single-line JSON string."""
        return json.dumps(
            dataclasses.asdict(self), separators=(",", ":"), sort_keys=True
        )

    @classmethod
    def from_json(cls, data: str) -> "AuthHealth":
        """Deserialize from a compact JSON string produced by to_json()."""
        return cls(**json.loads(data))


# ---------------------------------------------------------------------------
# Renewal orchestrator and per-store-path single-flight locks
# ---------------------------------------------------------------------------

# Per-store-path locks for single-flight coordination within this process
# (complements schwabdev's internal SQLite-level coordination).
_renew_locks: dict[str, threading.Lock] = {}
_renew_locks_lock = threading.Lock()

_logger = logging.getLogger(__name__)

ACCESS_MARGIN = 61  # schwabdev's built-in preventive margin (seconds)
RETRIES = 2  # max retry attempts (retry_call default)


def _seconds_from_store(store_path: str) -> Optional[int]:
    """Read the remaining access token lifetime from the store, or None."""
    lifetime = read_store_lifetime(store_path)
    if lifetime is None:
        return None
    return lifetime.access_remaining_seconds


def _not_needed_outcome(lifetime: StoreLifetime) -> RenewalOutcome:
    """Build the ``not_needed`` outcome from a store lifetime reading."""
    return RenewalOutcome(
        outcome="not_needed",
        expires_in_seconds=lifetime.access_remaining_seconds,
        retryable=False,
        detail="still_valid",
    )


def _make_renewed_outcome(store_path: Optional[str]) -> RenewalOutcome:
    """Build a ``renewed`` outcome, reading remaining seconds from the store."""
    remaining = _seconds_from_store(store_path) if store_path else None
    return RenewalOutcome(
        outcome="renewed",
        expires_in_seconds=remaining,
        retryable=False,
        detail="access_renewed",
    )


def _tie_breaker_probe(client: object,
                       store_path: Optional[str] = None) -> RenewalOutcome:
    """Probe the provider to distinguish between transient failure and reauth.

    Called when ``update_tokens()`` returns ``False`` (ambiguous result).
    A successful ``linked_accounts()`` call means another process already
    renewed (the library's concurrency coordination won).  A rejected
    response indicates the refresh credential is permanently unusable.

    Bug renew-phantom-success: schwabdev client methods return
    ``requests.Response`` objects and an HTTP 401 does **not** raise, so the
    response status must be classified explicitly.  The shared
    ``provider.response_json`` unwrapper is reused (Constitution II): it
    raises ``ReauthorizationRequiredError`` on 401/403 and
    ``ConnectivityError`` on 5xx/408/429/malformed bodies, while dict/list
    test doubles pass through unchanged.

    The success branch is additionally verified against the store (Issue 3
    consistency): a ``renewed`` outcome must correspond to a store write,
    so the store must actually hold a fresh access token.
    """
    try:
        response_json(client.linked_accounts())
    except ReauthorizationRequiredError:
        return RenewalOutcome(
            outcome="reauth_required",
            expires_in_seconds=None,
            retryable=False,
            detail="refresh_rejected",
        )
    except ConnectivityError:
        # Provider unreachable / malformed body — not evidence of a dead
        # refresh credential; classified as retryable instead.
        return RenewalOutcome(
            outcome="transient_failure",
            expires_in_seconds=None,
            retryable=True,
            detail="provider_unreachable",
        )
    except Exception:
        return RenewalOutcome(
            outcome="reauth_required",
            expires_in_seconds=None,
            retryable=False,
            detail="refresh_rejected",
        )

    # Probe succeeded (2xx).  Before claiming a renewal, confirm the store
    # actually holds a fresh access token — a 2xx probe with a stale or
    # unreadable store cannot be a verified renewal (nothing was written).
    if store_path is not None:
        remaining = _seconds_from_store(store_path)
        if remaining is None or remaining <= ACCESS_MARGIN:
            return RenewalOutcome(
                outcome="reauth_required",
                expires_in_seconds=None,
                retryable=False,
                detail="renewal_unverified",
            )
    return _make_renewed_outcome(store_path)


@contextlib.contextmanager
def _store_lock(store_path: Optional[str]):
    """Hold the per-store renewal lock for the duration of the block.

    Single-flight coordination (FR-005): concurrent callers for the same
    store serialise on a blocking acquire, and the release is paired with
    the acquire by the context manager — it can never double-release a
    lock this thread does not own (bug TD-001).  With no store there is
    nothing to coordinate, so the block runs unlocked.
    """
    if store_path is None:
        yield  # No store → no coordination needed
        return
    with _renew_locks_lock:
        lock = _renew_locks.setdefault(store_path, threading.Lock())
    with lock:
        yield


def renew(client: object, store_path: Optional[str] = None,
          trigger_detail: str = "margin_trigger") -> RenewalOutcome:
    """Renew the access credential and return a classified outcome.

    Parameters
    ----------
    client
        A schwabdev ``Client`` instance (or mock) with ``update_tokens()``
        and optionally ``tokens_db`` and ``linked_accounts()``.
    store_path
        Path to the token store.  Falls back to ``client.tokens_db`` when
        ``None``.

    Returns
    -------
    RenewalOutcome
        One of the four classification outcomes per FR-003.
    """
    if store_path is None:
        store_path = getattr(client, "tokens_db", None)

    if store_path is None:
        return _do_renew(client, store_path, trigger_detail=trigger_detail)

    # 1. Margin short-circuit — no network call if enough validity remains
    #    (advisory fast path; the authoritative re-check runs under the lock).
    lifetime = read_store_lifetime(store_path)
    if lifetime is not None and lifetime.access_remaining_seconds > ACCESS_MARGIN:
        return _not_needed_outcome(lifetime)

    # 2. Single-flight critical section (bug TD-001): blocking acquire, then
    #    re-check the margin INSIDE the lock so a renewal completed by
    #    another thread is observed here — otherwise renew under the lock,
    #    which is held across the whole attempt (including retries).
    with _store_lock(store_path):
        lifetime = read_store_lifetime(store_path)
        if lifetime is not None and lifetime.access_remaining_seconds > ACCESS_MARGIN:
            return _not_needed_outcome(lifetime)
        return _do_renew(client, store_path, trigger_detail=trigger_detail)


def _do_renew(client: object, store_path: Optional[str],
              trigger_detail: str = "margin_trigger") -> RenewalOutcome:
    """Execute a single renewal attempt with bounded retries (under lock).

    Parameters
    ----------
    client
        A schwabdev ``Client`` instance (or mock).
    store_path
        Path to the token store (for reading remaining lifetime).
    trigger_detail
        Value for the ``renew_start`` event ``detail`` field:
        ``"margin_trigger"`` (automatic path) or ``"explicit_command"``
        (``schwab-mcp renew``).
    """
    auth_event("renew_start", "initiated", detail=trigger_detail)

    for attempt in range(1 + RETRIES):  # initial + RETRIES retries
        try:
            result = client.update_tokens()
        except ReauthorizationRequiredError:
            outcome = RenewalOutcome(
                outcome="reauth_required",
                expires_in_seconds=None,
                retryable=False,
                detail="reauth_needed",
            )
            auth_event("renewal_failure", "reauth_required",
                       detail="run: schwab-mcp auth")
            return outcome
        except Exception as exc:
            if attempt < RETRIES:
                _logger.warning(
                    "Renewal attempt %d failed; retrying: %s", attempt + 1, exc
                )
                time.sleep(0.5)
            continue

        # ``update_tokens()`` returned without raising.
        if result is True:
            outcome = _make_renewed_outcome(store_path)
            auth_event("renewal_success", "ok", detail="access token renewed")
            return outcome
        # ``result`` is ``False`` — ambiguous; probe to disambiguate.
        probe_outcome = _tie_breaker_probe(client, store_path)
        if probe_outcome.outcome == "renewed":
            auth_event("renewal_success", "ok", detail="access token renewed")
        elif probe_outcome.outcome == "transient_failure":
            auth_event("renewal_failure", "connectivity",
                       detail="retries exhausted")
        else:
            auth_event("renewal_failure", "reauth_required",
                       detail="run: schwab-mcp auth")
        return probe_outcome

    # All retries exhausted.
    outcome = RenewalOutcome(
        outcome="transient_failure",
        expires_in_seconds=None,
        retryable=True,
        detail="provider_unreachable",
    )
    auth_event("renewal_failure", "connectivity",
               detail="retries exhausted")
    return outcome


# ---------------------------------------------------------------------------
# Store lifetime reader (FR-008, research.md D5)
# ---------------------------------------------------------------------------


class StoreLifetime:
    """Remaining lifetimes read from a token store.

    Attributes
    ----------
    access_remaining_seconds
        Seconds until the access token expires, or 0 if already expired.
    refresh_remaining_seconds
        Seconds until the refresh token expires (7-day Schwab lifetime),
        or 0 if already expired.
    """

    __slots__ = ("access_remaining_seconds", "refresh_remaining_seconds")

    def __init__(self, access_remaining_seconds: int, refresh_remaining_seconds: int) -> None:
        self.access_remaining_seconds = access_remaining_seconds
        self.refresh_remaining_seconds = refresh_remaining_seconds


def read_store_lifetime(path: str | os.PathLike) -> Optional[StoreLifetime]:
    """Read the token store and compute remaining lifetimes.

    Consumes ``tokens._read_schwabdev_row`` — the single store-read
    implementation (TD-003, Constitution II).  Reads ``expires_in``,
    ``access_token_issued``, and ``refresh_token_issued`` from the
    ``schwabdev`` row to compute remaining seconds.

    Returns
    -------
    StoreLifetime or None
        ``None`` when the store is absent, empty, or corrupted.
    """
    status, row = _read_schwabdev_row(path)
    if status != "present" or row is None:
        return None
    expires_in, access_issued, refresh_issued = row

    now = time.time()
    access_epoch = _issued_to_epoch(access_issued)
    refresh_epoch = _issued_to_epoch(refresh_issued)
    if access_epoch is None or refresh_epoch is None or expires_in is None:
        return None
    access_remaining = max(0, int(expires_in) - int(now - access_epoch))
    # Schwab refresh token lifetime is 7 days
    refresh_remaining = max(0, 7 * 24 * 3600 - int(now - refresh_epoch))
    return StoreLifetime(access_remaining, refresh_remaining)


def _issued_to_epoch(value: object) -> Optional[float]:
    """Convert a stored ``*_token_issued`` value to epoch seconds.

    schwabdev 4.0.0 writes ISO-8601 timestamps as TEXT (e.g.
    ``2026-10-19T22:00:27.004577+00:00``); numeric epoch seconds are
    accepted for compatibility.  Returns ``None`` when the value is
    missing or unparseable (treated as a corrupted store by the caller).

    Single source of truth (Constitution II): the parse logic lives in
    ``tokens.issued_to_epoch`` / ``tokens.parse_issued_datetime`` — the
    same definition ``peek_store_status`` uses for its (stricter)
    corrupted-store classification.
    """
    return _tokens_issued_to_epoch(value, strict=False)