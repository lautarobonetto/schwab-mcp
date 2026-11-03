"""Price History OHLCV — the ``get_price_history`` MCP tool (feature 011).

One symbol per invocation, a declared frequency set (``5m``/``15m``/
``30m``/``1h``/``daily``/``weekly``), named period presets bounded per
frequency, a 260-candle global ceiling by construction, an
``extended_hours`` opt-in for intraday requests, and an explicit
``in_progress`` marker on the forming candle.

Normative contracts:
``specs/011-price-history-ohlcv/contracts/mcp-tools.md`` (envelopes,
presets, budgets) and ``specs/011-price-history-ohlcv/data-model.md``
(candle mapping, aggregation rules, D6 in-progress derivation).

Reuse (constitution Principles II–III): the unwrap/error taxonomy is
``schwab_mcp.provider.response_json``, retries are
``schwab_mcp.tokens.retry_call``, audit events go through
``schwab_mcp.log.auth_event``, and the symbol grammars are the ones
already owned by ``schwab_mcp.quotes._classify`` (single source of truth
for equity/ETF, index, and option-contract shapes).

Stamping convention (research D8 — unverified empirical constant): the
provider's ``datetime`` semantics (period start vs period end) are not
documented.  :data:`STAMPING_CONVENTION` records the assumption and
every convention-dependent rule parameterizes on it; the fixture-pinned
helpers in ``tests/unit/fixtures/price_history_payloads.py`` are the
regression pin.  Rules are written so they hold under either convention
where purely arithmetic (see :func:`_session_close_at_or_after`).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from schwab_mcp.errors import (
    ConnectivityError,
    ReauthorizationRequiredError,
)
from schwab_mcp.log import auth_event
from schwab_mcp.provider import response_json
from schwab_mcp.quotes import _OPTION_RE, _classify
from schwab_mcp.tokens import retry_call

__all__ = [
    "PRESET_TABLE",
    "aggregate_hourly",
    "get_price_history",
    "get_price_history_tool",
    "normalize_weekly_labels",
]

# =============================================================================
# Constants (contracts/mcp-tools.md §1-§2, data-model.md preset matrix)
# =============================================================================

ET = ZoneInfo("America/New_York")
"""Exchange timezone of every session/bucket rule (data-model.md)."""

MS_PER_MINUTE = 60_000
MS_PER_HOUR = 3_600_000

SESSION_OPEN_MINUTES = 9 * 60 + 30
"""Regular session open, 09:30 ET (data-model "Aggregation rules")."""

SESSION_CLOSE_MINUTES = 16 * 60
"""Regular session close, 16:00 ET."""

STAMPING_CONVENTION = "period_start"
"""Assumed provider stamping convention — UNVERIFIED (research D8).

``"period_start"``: a candle's ``datetime`` is the start of its period
(session open for daily, bucket start for intraday).  ``"period_end"``:
the stamp is the period end.  Rules that cannot be written convention-
agnostically (regular-session membership of a boundary stamp) take this
value as an explicit parameter so the assumed convention is visible and
re-pinning it after a live capture is a one-line change.
"""

INTRADAY_FREQUENCIES: tuple[str, ...] = ("5m", "15m", "30m", "1h")
"""Frequencies where ``extended_hours`` applies (research D4)."""

NATIVE_INTRADAY_SPAN: dict[str, int] = {"5m": 5, "15m": 15, "30m": 30}
"""Period span in minutes of every native intraday frequency (D6)."""

MAX_CANDLES = 260
"""Global candle ceiling per invocation, enforced by construction (FR-004)."""

START_EVENT = "price_history_query_start"
SUCCESS_EVENT = "price_history_query_success"
FAILURE_EVENT = "price_history_query_failure"

# frequency -> period preset -> (periodType, period, frequencyType, frequency)
# data-model.md "Period presets × frequency matrix" (normative, D3).
PRESET_TABLE: dict[str, dict[str, tuple[str, int, str, int]]] = {
    "5m": {
        "1d": ("day", 1, "minute", 5),
        "2d": ("day", 2, "minute", 5),
        "3d": ("day", 3, "minute", 5),
    },
    "15m": {
        "1d": ("day", 1, "minute", 15),
        "2d": ("day", 2, "minute", 15),
        "5d": ("day", 5, "minute", 15),
        "10d": ("day", 10, "minute", 15),
    },
    "30m": {
        "1d": ("day", 1, "minute", 30),
        "2d": ("day", 2, "minute", 30),
        "5d": ("day", 5, "minute", 30),
        "10d": ("day", 10, "minute", 30),
    },
    # 1h has no provider frequency: fetch 30-minute candles and aggregate
    # 2:1 locally (research D2).
    "1h": {
        "1d": ("day", 1, "minute", 30),
        "2d": ("day", 2, "minute", 30),
        "5d": ("day", 5, "minute", 30),
        "10d": ("day", 10, "minute", 30),
    },
    "daily": {
        "1m": ("month", 1, "daily", 1),
        "3m": ("month", 3, "daily", 1),
        "6m": ("month", 6, "daily", 1),
        "1y": ("year", 1, "daily", 1),
        "ytd": ("ytd", 1, "daily", 1),
    },
    "weekly": {
        "1m": ("month", 1, "weekly", 1),
        "3m": ("month", 3, "weekly", 1),
        "6m": ("month", 6, "weekly", 1),
        "1y": ("year", 1, "weekly", 1),
        "2y": ("year", 2, "weekly", 1),
        "3y": ("year", 3, "weekly", 1),
        "5y": ("year", 5, "weekly", 1),
        "ytd": ("ytd", 1, "weekly", 1),
    },
}


# =============================================================================
# Result envelopes (contracts/mcp-tools.md §2-§3; shared shape, FR-009)
# =============================================================================


def _validation_error(detail: str, symbol: str, **extra: Any) -> dict:
    return {
        "outcome": "validation_error",
        "detail": detail,
        "retryable": False,
        "symbol": symbol,
        **extra,
    }


def _provider_unreachable(symbol: str, detail: str = "provider_unreachable") -> dict:
    return {
        "outcome": "provider_unreachable",
        "detail": detail,
        "retryable": True,
        "symbol": symbol,
    }


def _reauth_needed(symbol: str) -> dict:
    return {
        "outcome": "reauth_needed",
        "detail": "reauth_needed",
        "retryable": False,
        "symbol": symbol,
    }


def _history_unavailable(symbol: str) -> dict:
    return {
        "outcome": "history_unavailable",
        "detail": "source_returned_no_candles",
        "retryable": False,
        "symbol": symbol,
    }


# =============================================================================
# Audit-event detail (contract §6: symbol and selection are logged)
# =============================================================================


def _selection_detail(
    symbol: Any,
    frequency: Any,
    period: Any,
    extended_hours: Any,
    extended: Any,
) -> str:
    """Selection-only event detail — never credentials (FR-011).

    Symbol and selection are the only facts this tool can log: the
    request carries no account or token material.
    """
    name = symbol.strip().upper() if isinstance(symbol, str) else ""
    return (
        f"symbol={name} frequency={frequency} period={period} "
        f"extended_hours={bool(extended_hours)} extended={bool(extended)}"
    )


def _fail(
    detail: str,
    symbol: str,
    frequency: Any,
    period: Any,
    extended_hours: Any,
    extended: Any,
    **extra: Any,
) -> dict:
    """Emit the failure event and return the validation envelope.

    *symbol* is the already-normalized request symbol, which both the
    audit event and the envelope carry (FR-008/US1-AC3: the error names
    the offending symbol).
    """
    auth_event(
        FAILURE_EVENT,
        "validation",
        detail=f"{detail} " + _selection_detail(symbol, frequency, period, extended_hours, extended),
    )
    return _validation_error(detail, symbol, **extra)


# =============================================================================
# Timestamp rules (D6/D7/D8)
# =============================================================================


def _resolve_fetch_time(fetch_time: int | None) -> int:
    """Frozen clock in epoch milliseconds (D6 injects it in tests)."""
    if fetch_time is not None:
        return int(fetch_time)
    return int(time.time() * 1000)


def _et(stamp_ms: int) -> datetime:
    return datetime.fromtimestamp(stamp_ms / 1000, ET)


def _to_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _session_close_at_or_after(stamp_ms: int) -> int:
    """The 16:00 ET close of the session a stamp belongs to (D6/D8).

    Convention-agnostic by construction: a stamp at the session open
    (``period_start``) and a stamp at the session close (``period_end``)
    both resolve to that session's 16:00 close, and a close stamp resolves
    to itself.  Later-than-close stamps roll to the next day's close.
    """
    moment = _et(stamp_ms)
    close = moment.replace(
        hour=16, minute=0, second=0, microsecond=0
    )
    if close < moment:
        close += timedelta(days=1)
    return _to_ms(close)


def _period_end(stamp_ms: int, frequency: str) -> int:
    """End of the period a curated candle covers (D6, normative).

    Native intraday: stamp + frequency span.  Daily: the session close at
    or after the stamp.  Weekly: the closing session's close of the ISO
    week (labels are normalized first, so the day is already the Friday).
    """
    if frequency in NATIVE_INTRADAY_SPAN:
        return stamp_ms + NATIVE_INTRADAY_SPAN[frequency] * MS_PER_MINUTE
    return _session_close_at_or_after(stamp_ms)


def _session_minutes(stamp_ms: int) -> int:
    moment = _et(stamp_ms)
    return moment.hour * 60 + moment.minute


def _in_regular_session(stamp_ms: int, convention: str) -> bool:
    """Whether a stamp belongs to the regular 09:30–16:00 ET session.

    Under ``"period_start"`` a regular candle stamps in
    ``[09:30, 16:00)``; under ``"period_end"`` in ``(09:30, 16:00]``.
    The boundary stamps are the only ambiguous ones (research D8), which
    is why the convention is an explicit parameter.
    """
    minutes = _session_minutes(stamp_ms)
    if convention == "period_end":
        return SESSION_OPEN_MINUTES < minutes <= SESSION_CLOSE_MINUTES
    return SESSION_OPEN_MINUTES <= minutes < SESSION_CLOSE_MINUTES


def _hour_bucket_end(stamp_ms: int) -> int:
    """End of the clock-hour bucket holding *stamp_ms* (ET, D2 rule 3/4)."""
    moment = _et(stamp_ms)
    bucket_start = moment.replace(minute=0, second=0, microsecond=0)
    return _to_ms(bucket_start + timedelta(hours=1))


# =============================================================================
# Curation (data-model.md "Candle"; FR-005/FR-012/FR-015)
# =============================================================================


def _curate(bar: dict) -> dict:
    """Map one provider bar to the curated candle — values as delivered."""
    return {
        "t": bar.get("datetime"),
        "o": bar.get("open"),
        "h": bar.get("high"),
        "l": bar.get("low"),
        "c": bar.get("close"),
        "v": bar.get("volume"),
        "in_progress": False,
    }


def _curated_candles(payload: dict, frequency: str) -> list[dict]:
    """Provider payload -> curated candles, oldest first (FR-005).

    One curated candle per delivered provider bar; gaps are never
    interpolated.  Weekly labels are normalized to the closing session
    (FR-019) before the in-progress derivation.
    """
    bars = payload.get("candles")
    if not isinstance(bars, list):
        return []
    candles = sorted(
        (_curate(bar) for bar in bars if isinstance(bar, dict)),
        key=lambda candle: candle["t"],
    )
    if frequency == "weekly":
        candles = normalize_weekly_labels(candles)
    return candles


def _mark_in_progress(candles: list[dict], frequency: str, fetch_time: int) -> None:
    """D6: ``in_progress`` iff the period end is still ahead of *fetch_time*.

    Applied to the last candle only, so at most one candle per response
    can carry the marker (FR-017).
    """
    if not candles:
        return
    last = candles[-1]
    last["in_progress"] = _period_end(last["t"], frequency) > fetch_time


# =============================================================================
# Hourly aggregation (data-model "Hourly (1h)", D2; pure function)
# =============================================================================


def aggregate_hourly(
    candles: list[dict],
    *,
    extended_hours: bool = False,
    fetch_time: int | None = None,
    convention: str = STAMPING_CONVENTION,
) -> list[dict]:
    """Aggregate curated 30-minute *candles* into hourly candles (D2).

    Pure function: regular-session filtering before bucketing unless
    ``extended_hours``; clock-hour buckets in the exchange timezone with
    ``t`` = bucket end; ``o`` = first, ``h`` = max, ``l`` = min,
    ``c`` = last, ``v`` = sum; the trailing partial bucket is still
    emitted and marked ``in_progress`` per the D6 rule against
    *fetch_time*.
    """
    clock = _resolve_fetch_time(fetch_time)
    kept = [
        candle
        for candle in candles
        if extended_hours or _in_regular_session(candle["t"], convention)
    ]

    buckets: dict[int, list[dict]] = {}
    for candle in kept:
        buckets.setdefault(_hour_bucket_end(candle["t"]), []).append(candle)

    aggregated: list[dict] = []
    for end in sorted(buckets):
        members = buckets[end]
        volumes = [m["v"] for m in members if m.get("v") is not None]
        aggregated.append(
            {
                "t": end,
                "o": members[0]["o"],
                "h": max(m["h"] for m in members),
                "l": min(m["l"] for m in members),
                "c": members[-1]["c"],
                "v": sum(volumes) if volumes else None,
                "in_progress": end > clock,
            }
        )
    return aggregated


# =============================================================================
# Weekly label normalization (data-model "Weekly", D7; pure function)
# =============================================================================


def normalize_weekly_labels(candles: list[dict]) -> list[dict]:
    """Relabel weekly candles to their ISO week's closing session (D7).

    Pure function guaranteeing FR-019: every ``t`` becomes the closing
    session's timestamp of that ISO week (the Friday), preserving the
    stamp's time of day so the provider's start/end convention survives.
    Idempotent — a closing-session stamp maps to itself.
    """
    normalized: list[dict] = []
    for candle in candles:
        moment = _et(candle["t"])
        friday = moment + timedelta(days=4 - moment.weekday())
        relabeled = dict(candle)
        relabeled["t"] = _to_ms(
            moment.replace(
                year=friday.year, month=friday.month, day=friday.day
            )
        )
        normalized.append(relabeled)
    return normalized


# =============================================================================
# Orchestration: get_price_history (research D1/D3/D4/D9)
# =============================================================================


def get_price_history(
    client: Any,
    symbol: str,
    frequency: str = "daily",
    period: str = "1m",
    extended_hours: bool = False,
    extended: bool = False,
    *,
    fetch_time: int | None = None,
) -> dict:
    """Fetch curated OHLCV candles for one *symbol* (research D1).

    Exactly one ``price_history()`` provider call per invocation with the
    parameters from the preset table.  Validation runs before any upcall
    (FR-007); failures return the shared structured envelopes (contract
    §3) and never partial data (FR-008).  ``frequency`` defaults to
    ``"daily"`` and ``period`` to ``"1m"`` (FR-002); ``extended_hours``
    maps to ``needExtendedHoursData`` and is intraday-only (D4);
    ``extended=True`` adds the raw provider payload under ``"provider"``
    (SC-006).  ``fetch_time`` (epoch ms) is the injected D6 clock.
    """
    auth_event(
        START_EVENT,
        "initiated",
        detail=_selection_detail(
            symbol, frequency, period, extended_hours, extended
        ),
    )

    # ------------------------------------------------------------------
    # 1. Tool-boundary types (the wrapper converts these to ToolError)
    # ------------------------------------------------------------------
    if symbol is not None and not isinstance(symbol, str):
        auth_event(
            FAILURE_EVENT,
            "validation",
            detail="invalid_request "
            + _selection_detail(
                symbol, frequency, period, extended_hours, extended
            ),
        )
        raise TypeError(
            "symbol must be a string (contract §1: one symbol per "
            f"invocation); got {type(symbol).__name__}"
        )

    # ------------------------------------------------------------------
    # 2. Normalization + validation before any upcall (FR-007, D9)
    # ------------------------------------------------------------------
    normalized = (symbol or "").strip().upper()
    if not normalized:
        return _fail(
            "malformed_symbol", normalized, frequency, period, extended_hours, extended
        )

    classified = _classify(normalized)
    if classified is None:
        # An option-shaped symbol is still recognizably an option contract
        # even when its strike cannot be re-encoded (D9): the price-history
        # endpoint serves underlyings, so the kind rejection comes first.
        # The OCC shape grammar is reused from ``quotes`` (Principle II).
        if _OPTION_RE.match(normalized):
            return _fail(
                "unsupported_symbol_kind",
                normalized,
                frequency,
                period,
                extended_hours,
                extended,
            )
        return _fail(
            "malformed_symbol",
            normalized,
            frequency,
            period,
            extended_hours,
            extended,
        )
    if classified[0] == "option":
        return _fail(
            "unsupported_symbol_kind",
            normalized,
            frequency,
            period,
            extended_hours,
            extended,
        )

    if frequency not in PRESET_TABLE:
        return _fail(
            "unsupported_frequency",
            normalized,
            frequency,
            period,
            extended_hours,
            extended,
            valid_frequencies=list(PRESET_TABLE),
        )

    presets = PRESET_TABLE[frequency]
    if period not in presets:
        return _fail(
            "unsupported_period",
            normalized,
            frequency,
            period,
            extended_hours,
            extended,
            valid_presets=list(presets),
        )

    if extended_hours and frequency not in INTRADAY_FREQUENCIES:
        return _fail(
            "extended_hours_not_applicable",
            normalized,
            frequency,
            period,
            extended_hours,
            extended,
        )

    # ------------------------------------------------------------------
    # 3. One provider fetch through the shared retry/unwrap plumbing
    # ------------------------------------------------------------------
    period_type, period_value, frequency_type, frequency_value = presets[period]
    try:
        response = retry_call(
            client.price_history,
            0,
            normalized,
            periodType=period_type,
            period=period_value,
            frequencyType=frequency_type,
            frequency=frequency_value,
            needExtendedHoursData=bool(extended_hours),
        )
        payload = retry_call(response_json, 0, response=response)
    except ConnectivityError as exc:
        if isinstance(
            exc.__cause__, (ReauthorizationRequiredError, PermissionError)
        ):
            auth_event(
                FAILURE_EVENT,
                "reauth",
                detail="reauth_needed "
                + _selection_detail(
                    normalized, frequency, period, extended_hours, extended
                ),
            )
            return _reauth_needed(normalized)
        auth_event(
            FAILURE_EVENT,
            "provider_unreachable",
            detail="provider_unreachable "
            + _selection_detail(
                normalized, frequency, period, extended_hours, extended
            ),
        )
        return _provider_unreachable(normalized)

    if not isinstance(payload, dict):
        payload = {}

    # ------------------------------------------------------------------
    # 4. Curation: no candles -> history_unavailable (FR-008)
    # ------------------------------------------------------------------
    candles = _curated_candles(payload, frequency)
    if not candles:
        auth_event(
            FAILURE_EVENT,
            "error",
            detail="history_unavailable "
            + _selection_detail(
                normalized, frequency, period, extended_hours, extended
            ),
        )
        return _history_unavailable(normalized)

    # ------------------------------------------------------------------
    # 5. Frequency-specific derivation + in-progress marking (D6)
    # ------------------------------------------------------------------
    clock = _resolve_fetch_time(fetch_time)
    if frequency == "1h":
        # The aggregation computes the bucket-end labels AND the D6
        # marker over the fetched 30-minute candles (research D2).
        candles = aggregate_hourly(
            candles, extended_hours=bool(extended_hours), fetch_time=clock
        )
    else:
        _mark_in_progress(candles, frequency, clock)

    # ------------------------------------------------------------------
    # 6. Curated envelope (contract §2)
    # ------------------------------------------------------------------
    result = {
        "outcome": "ok",
        "detail": "price_history_retrieved",
        "symbol": normalized,
        "frequency": frequency,
        "period": period,
        "extended_hours": bool(extended_hours),
        "extended": bool(extended),
        "candle_count": len(candles),
        "window": {
            "first": candles[0]["t"],
            "last": candles[-1]["t"],
        },
        "candles": candles,
    }
    if extended:
        result["provider"] = payload

    auth_event(
        SUCCESS_EVENT,
        "ok",
        detail="price_history_retrieved "
        + _selection_detail(
            symbol, frequency, period, extended_hours, extended
        )
        + f" candle_count={len(candles)}",
    )
    return result


# =============================================================================
# MCP tool entry point (actionable errors for the MCP client)
# =============================================================================


def get_price_history_tool(
    client: Any,
    symbol: str,
    frequency: str = "daily",
    period: str = "1m",
    extended_hours: bool = False,
    extended: bool = False,
) -> dict:
    """MCP tool wrapper around :func:`get_price_history`.

    Converts tool-boundary type errors (``ValueError``/``TypeError``)
    into the MCP SDK's ``ToolError`` so the actionable message reaches
    the agent (pattern: ``quotes.get_quotes_tool``).  All expected
    failures return structured result envelopes and pass through
    unchanged.
    """
    from mcp.server.mcpserver.exceptions import ToolError

    try:
        return get_price_history(
            client,
            symbol,
            frequency=frequency,
            period=period,
            extended_hours=extended_hours,
            extended=extended,
        )
    except (ValueError, TypeError) as exc:
        raise ToolError(str(exc)) from exc
