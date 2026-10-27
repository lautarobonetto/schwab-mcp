"""Unwrapping of schwabdev SDK responses (single source of truth).

The schwabdev client returns ``requests.Response`` objects for every API
call.  Features 003 and 006 both need the parsed JSON body plus the shared
error mapping for non-2xx statuses (Constitution II — one authoritative
representation of this knowledge; Constitution III — one new module
justified by reuse across two features).
"""

from __future__ import annotations

from typing import Any

from schwab_mcp.errors import ConnectivityError, ReauthorizationRequiredError


def response_json(response: Any) -> Any:
    """Return the parsed JSON body of a provider ``requests.Response``.

    Status classification (shared error taxonomy):

    - ``401``/``403`` → ``ReauthorizationRequiredError``
    - ``5xx``, ``408``, ``429`` → ``ConnectivityError`` (transient)
    - other ``4xx`` → ``ValueError`` (provider rejected the request;
      callers classify it as a per-account ``provider_error``)
    - malformed JSON body → ``ConnectivityError``
    - empty body → ``{}``

    When invoked inside ``tokens.retry_call``, every raised error is wrapped
    in ``ConnectivityError`` with the original as ``__cause__``, which the
    orchestrations already inspect for outcome classification.
    """
    status = getattr(response, "status_code", None)
    if status is None:
        # Already-parsed payload (test doubles may return dicts/lists
        # directly) — unwrapping is a no-op on those.
        if isinstance(response, (dict, list)):
            return response
        raise TypeError("response_json() expects a requests.Response object")

    if status in (401, 403):
        raise ReauthorizationRequiredError(
            detail=f"Provider returned HTTP {status}; re-authorization required"
        )
    if status >= 500 or status in (408, 429):
        raise ConnectivityError(detail=f"Provider returned HTTP {status}")
    if status >= 400:
        raise ValueError(f"Provider returned HTTP {status}")

    if not getattr(response, "content", b""):
        return {}

    try:
        return response.json()
    except ValueError as exc:
        raise ConnectivityError(
            detail="Provider returned a malformed JSON body"
        ) from exc


def trade_time_value(raw: Any) -> Any:
    """Normalise a provider trade timestamp to an ISO-8601 UTC string.

    Shared by every market-data feature (Constitution II): epoch
    milliseconds (the live ``tradeTime``/``tradeTimeInLong`` shape) are
    converted; strings pass through; anything else keeps its value.  A
    zero epoch means "never traded" and maps to ``None`` — values are
    never invented (found live 2026-10-24).
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        if raw == 0:
            return None
        from datetime import datetime, timezone

        return datetime.fromtimestamp(
            raw / 1000, timezone.utc
        ).isoformat(timespec="seconds")
    return raw
