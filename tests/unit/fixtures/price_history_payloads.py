"""Provider price-history payload fixtures (feature 011, T002).

.. warning::
   **T002 fallback deviation (research D8/T002):** these payloads are
   *derived from the documented provider response shape*
   (``specs/011-price-history-ohlcv/data-model.md``,
   ``specs/011-price-history-ohlcv/contracts/mcp-tools.md``) and the
   ``schwabdev`` 4.0.0 client source — they are **not** live captures.
   The local token store's refresh token is expired (the SDK refuses and
   demands an interactive ``schwab-mcp auth`` browser round trip), so no
   authorized live session was available at implement time.  The
   D6/D7/D8 stamping-convention rules stay **parameterized** below
   (:data:`STAMPING_CONVENTION`, :data:`WEEKLY_STAMP_CONVENTION`); they
   MUST NOT be treated as pinned facts.  Replace these fixtures with
   live-captured payloads in a later commit (quickstart S6) and flip
   ``*_PINNED`` to ``True`` once the real convention is observed.

Fixture constants only: no credentials, tokens, or account identifiers
appear below (FR-011).  All values are synthetic and deterministic.

Documented provider response shape (Schwab ``/marketdata/v1/pricehistory``)::

    {"candles": [{"open": float, "high": float, "low": float,
                  "close": float, "volume": int, "datetime": int}],
     "symbol": str, "empty": bool}

``datetime`` is epoch milliseconds (research D8: period start vs period
end is the one empirical constant, kept parameterized here).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
"""Exchange timezone used for every stamp and bucket rule (data-model)."""

MS_PER_MINUTE = 60_000
MS_PER_HOUR = 3_600_000

# ----------------------------------------------------------------------
# Symbols (grammar examples of contracts/mcp-tools.md §1)
# ----------------------------------------------------------------------

SYMBOL = "SPY"
"""Equity/ETF symbol used by the default daily fixture."""

INDEX_SYMBOL = "$SPX"
"""Index symbol (leading ``$`` kind)."""

OPTION_SYMBOL = "AAPL 261127C350"
"""Option-contract symbol (quickstart S5) — rejected as ``unsupported_symbol_kind``."""

OPTION_SYMBOL_CANONICAL = "AAPL  261127C350000"
"""Canonical OCC option-contract spelling — also rejected (D9)."""

NO_HISTORY_SYMBOL = "ZZZZ"
"""Symbol used for the empty-candle fixture (delisted instrument)."""

# ----------------------------------------------------------------------
# Stamping conventions (research D6/D7/D8 — PARAMETERIZED, unverified)
# ----------------------------------------------------------------------

STAMPING_CONVENTION = "period_start"
"""Assumed daily/intraday stamping convention — UNVERIFIED (D8).

``"period_start"``: a candle's ``datetime`` is the start of its period
(session open 09:30 ET for daily; bucket start for intraday).
``"period_end"``: the stamp is the period end (session close 16:00 ET).
Tests parameterized on this constant MUST hold under both values.
"""

STAMPING_CONVENTION_PINNED = False
"""Never ``True`` until a live capture pins the real convention."""

STAMPING_CONVENTIONS = ("period_start", "period_end")
"""Both candidate conventions (D8) for parameterized tests."""

WEEKLY_STAMP_CONVENTION = "week_open"
"""Assumed weekly stamping convention — UNVERIFIED (D7).

``"week_open"``: weekly candles are stamped at the ISO week's first
session (non-closing stamp → the D7 relabel-forward path applies).
``"week_close"``: stamped at the ISO week's closing session (the D7
pass-through path applies).
"""

WEEKLY_STAMP_CONVENTION_PINNED = False
"""Never ``True`` until a live capture pins the real convention."""

WEEKLY_STAMP_CONVENTIONS = ("week_open", "week_close")
"""Both candidate weekly conventions (D7) for parameterized tests."""

SESSION_OPEN = (9, 30)
SESSION_CLOSE = (16, 0)
PRE_MARKET_OPEN = (4, 0)
POST_MARKET_CLOSE = (20, 0)


# ----------------------------------------------------------------------
# Calendar helpers (deterministic; no network, no clock reads)
# ----------------------------------------------------------------------

def _et_ms(y: int, m: int, d: int, hh: int, mm: int = 0) -> int:
    return int(datetime(y, m, d, hh, mm, tzinfo=ET).timestamp() * 1000)


def _weekday_dates(end: tuple[int, int, int], count: int) -> list[tuple[int, int, int]]:
    """The *count* weekdays ending at *end* (inclusive), oldest first."""
    cur = datetime(*end)
    out: list[datetime] = []
    while len(out) < count:
        if cur.weekday() < 5:
            out.append(cur)
        cur -= timedelta(days=1)
    return [(d.year, d.month, d.day) for d in reversed(out)]


def _stamp(date: tuple[int, int, int], convention: str = STAMPING_CONVENTION) -> int:
    hh, mm = SESSION_OPEN if convention == "period_start" else SESSION_CLOSE
    return _et_ms(*date, hh, mm)


# ----------------------------------------------------------------------
# Period-end / label helpers (D6/D7 rules, convention-parameterized)
# ----------------------------------------------------------------------

def daily_period_end(
    stamp_ms: int, convention: str = STAMPING_CONVENTION
) -> int:
    """Period end of a daily candle: the session close (16:00 ET).

    Under ``"period_end"`` the stamp already *is* the close.
    """
    if convention == "period_end":
        return stamp_ms
    dt = datetime.fromtimestamp(stamp_ms / 1000, ET)
    return _et_ms(dt.year, dt.month, dt.day, *SESSION_CLOSE)


def minute_period_end(stamp_ms: int, frequency_minutes: int) -> int:
    """Period end of a native intraday candle: stamp + frequency span (D6)."""
    return stamp_ms + frequency_minutes * MS_PER_MINUTE


def in_regular_session(
    stamp_ms: int, convention: str = STAMPING_CONVENTION
) -> bool:
    """Whether the candle stamped *stamp_ms* belongs to the regular session.

    Regular session 09:30–16:00 ET.  Under ``"period_start"`` a regular
    candle stamps in ``[09:30, 16:00)``; under ``"period_end"`` in
    ``(09:30, 16:00]`` (the pre-market candle ending at 09:30 and the
    post-market candle starting at 16:00 stay excluded).
    """
    dt = datetime.fromtimestamp(stamp_ms / 1000, ET)
    minutes = dt.hour * 60 + dt.minute
    open_m = SESSION_OPEN[0] * 60 + SESSION_OPEN[1]
    close_m = SESSION_CLOSE[0] * 60 + SESSION_CLOSE[1]
    if convention == "period_end":
        return open_m < minutes <= close_m
    return open_m <= minutes < close_m


def hour_bucket_end(stamp_ms: int) -> int:
    """End timestamp of the clock-hour bucket holding *stamp_ms* (ET).

    The bucket start is the stamp's hour floored in the exchange
    timezone; the end is one hour later (data-model aggregation rule 4,
    end-labeling).
    """
    dt = datetime.fromtimestamp(stamp_ms / 1000, ET)
    start = dt.replace(minute=0, second=0, microsecond=0)
    return int((start + timedelta(hours=1)).timestamp() * 1000)


def iso_week_close_session(stamp_ms: int) -> int:
    """The closing session's timestamp of the ISO week containing *stamp_ms*.

    FR-019: every weekly ``t`` must equal the closing session's stamp.
    The closing session is the last weekday (Friday) of that ISO week,
    stamped per :data:`STAMPING_CONVENTION`.  Weekday arithmetic only —
    no holidays in the fixture calendars.
    """
    dt = datetime.fromtimestamp(stamp_ms / 1000, ET)
    monday = dt - timedelta(days=dt.weekday())
    friday = monday + timedelta(days=4)
    return _stamp((friday.year, friday.month, friday.day))


def weekly_period_end(stamp_ms: int) -> int:
    """Period end of a weekly candle: the closing session's close (16:00 ET)."""
    return daily_period_end(iso_week_close_session(stamp_ms), STAMPING_CONVENTION)


# ----------------------------------------------------------------------
# Payload builders (deterministic, synthetic — see module warning)
# ----------------------------------------------------------------------

def _bar(i: int, base: float, drift: float, tick: float, vol: int) -> dict[str, Any]:
    close = round(base + drift * i + ((i * 37) % 11 - 5) * tick, 2)
    open_ = round(close - ((i * 13) % 7 - 3) * tick * 0.7, 2)
    high = round(max(open_, close) + ((i * 7) % 5) * tick + tick, 2)
    low = round(min(open_, close) - ((i * 11) % 5) * tick - tick, 2)
    return {
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": vol + (i * 1_337_331) % (vol // 2),
        "datetime": 0,  # stamped below
    }


def build_daily_payload(
    symbol: str = SYMBOL,
    *,
    convention: str = STAMPING_CONVENTION,
    sessions: int = 22,
    end: tuple[int, int, int] = (2026, 11, 2),
) -> dict[str, Any]:
    """Daily candles for the default ``1m`` window (``periodType="month",
    period=1``), *sessions* weekday sessions ending at *end*."""
    candles = []
    for i, date in enumerate(_weekday_dates(end, sessions)):
        bar = _bar(i, base=580.0, drift=0.31, tick=0.17, vol=41_000_000)
        bar["datetime"] = _stamp(date, convention)
        candles.append(bar)
    return {"candles": candles, "symbol": symbol, "empty": False}


def build_weekly_payload(
    symbol: str = "AAPL",
    *,
    stamp_convention: str = WEEKLY_STAMP_CONVENTION,
    session_convention: str = STAMPING_CONVENTION,
    weeks: int = 52,
    end: tuple[int, int, int] = (2026, 11, 2),
) -> dict[str, Any]:
    """Weekly candles for ``1y`` (``periodType="year", period=1``).

    Weeks are anchored on their closing sessions (Fridays) — 52
    completed ISO weeks ending on or before *end*.  Stamps follow
    *stamp_convention*: ``"week_open"`` stamps the ISO week's first
    session (Monday); ``"week_close"`` stamps the closing session —
    both per *session_convention*.
    """
    fridays: list[datetime] = []
    cur = datetime(*end) - timedelta(days=(datetime(*end).weekday() - 4) % 7)
    while len(fridays) < weeks:
        fridays.append(cur)
        cur -= timedelta(days=7)
    candles = []
    for i, friday in enumerate(reversed(fridays)):
        bar = _bar(i, base=250.0, drift=1.7, tick=0.55, vol=88_000_000)
        if stamp_convention == "week_close":
            bar["datetime"] = _stamp(
                (friday.year, friday.month, friday.day), session_convention
            )
        else:
            monday = friday - timedelta(days=4)
            bar["datetime"] = _stamp(
                (monday.year, monday.month, monday.day), session_convention
            )
        candles.append(bar)
    return {"candles": candles, "symbol": symbol, "empty": False}


def build_30m_payload(
    symbol: str = "AAPL",
    *,
    extended: bool = False,
    convention: str = STAMPING_CONVENTION,
    sessions: int = 5,
    end: tuple[int, int, int] = (2026, 10, 30),
) -> dict[str, Any]:
    """30-minute candles for ``periodType="day", period=5``.

    Regular session 09:30–16:00 ET → 13 candles per session.  With
    *extended*, pre-market 04:00–09:30 (11) and post-market 16:00–20:00
    (8) candles are added per session → 32 per session.  Stamps follow
    *convention*: the candle's period start (09:30, 10:00, ...) or its
    period end (10:00, 10:30, ...).
    """
    offset = 30 * MS_PER_MINUTE if convention == "period_end" else 0
    stamps: list[int] = []
    for date in _weekday_dates(end, sessions):
        if extended:
            stamps.extend(
                _et_ms(*date, 4, 0) + k * 30 * MS_PER_MINUTE + offset
                for k in range(11)
            )
        stamps.extend(
            _et_ms(*date, 9, 30) + k * 30 * MS_PER_MINUTE + offset
            for k in range(13)
        )
        if extended:
            stamps.extend(
                _et_ms(*date, 16, 0) + k * 30 * MS_PER_MINUTE + offset
                for k in range(8)
            )
    candles = []
    for i, stamp in enumerate(stamps):
        bar = _bar(i, base=585.0, drift=0.013, tick=0.09, vol=1_200_000)
        bar["datetime"] = stamp
        candles.append(bar)
    return {"candles": candles, "symbol": symbol, "empty": False}


def build_empty_payload(symbol: str = NO_HISTORY_SYMBOL) -> dict[str, Any]:
    """Response for a valid symbol with no candles (FR-008)."""
    return {"candles": [], "symbol": symbol, "empty": True}


# ----------------------------------------------------------------------
# Fixture constants (derived from the builders above)
# ----------------------------------------------------------------------

DAILY_PAYLOAD: dict[str, Any] = build_daily_payload()
"""Daily ``1m`` window fixture — 22 candles, symbol ``SPY`` (T005/T006)."""

WEEKLY_PAYLOAD: dict[str, Any] = build_weekly_payload()
"""Weekly ``1y`` fixture — 52 candles, symbol ``AAPL`` (T015)."""

MINUTE_30M_PAYLOAD: dict[str, Any] = build_30m_payload()
"""30-minute ``5d`` fixture — 65 regular-session candles (T014)."""

INTRADAY_REGULAR_PAYLOAD: dict[str, Any] = MINUTE_30M_PAYLOAD
"""Regular-session side of the extended-hours pair (T016)."""

INTRADAY_EXTENDED_PAYLOAD: dict[str, Any] = build_30m_payload(extended=True)
"""``needExtendedHoursData=true`` side of the pair — 160 candles (T016)."""

EMPTY_PAYLOAD: dict[str, Any] = build_empty_payload()
"""Empty-candle response for ``ZZZZ`` (FR-008)."""