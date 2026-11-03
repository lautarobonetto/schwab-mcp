"""Live-captured provider price-history payload fixtures (feature 011, T002/T034).

Captured 2026-11-02 (evening ET, after a fresh interactive
``schwab-mcp auth``) with an authorized ``schwabdev`` client against
``/marketdata/v1/pricehistory`` (T034: live evidence replacing the
derived fallback fixtures of T002).  Fixture constants only: no
credentials, tokens, or account identifiers appear below (FR-011).

Live facts these fixtures pin (see the implementing commit message):

- **Intraday (minute) candles are stamped at PERIOD START** (research
  D8): the regular-session 30-minute candles run 09:30 .. 15:30 ET —
  the last regular candle's stamp starts its 30-minute window ending
  16:00.  :data:`STAMPING_CONVENTION` is ``"period_start"``, PINNED.
- **Daily candles are stamped at 05:00 UTC** (01:00 ET during EDT; the
  stamp's calendar date is the session date).  Neither session open nor
  session close — the D6 rule (``period end = session close at/after
  the stamp``) holds unchanged: a 01:00 ET stamp resolves to the same
  day's 16:00 close.
- **Weekly candles are stamped at the ISO week's FIRST session**
  (Monday-only stamps observed) — :data:`WEEKLY_STAMP_CONVENTION` is
  ``"week_open"``, PINNED.  FR-019 therefore requires the D7
  relabel-forward path: every weekly ``t`` is relabelled to the closing
  session.  Cross-verified live: the relabelled label of the current
  week equals the provider's own daily stamp of that Friday (both
  05:00-UTC-style stamps), so the weekly path agrees with the daily
  path.
- The default daily window (``periodType="month", period=1``) delivered
  23 sessions (Sep 30 – Oct 30, 2026); 30-minute ``5d`` regular
  delivered 65 candles (13/session); the extended pair delivered 218
  candles (pre-market from 07:00 ET, post-market to 19:30 ET — the
  derived fixtures' 04:00/20:00 assumption was WRONG).
- The response envelope is ``{"candles": [...], "symbol": str,
  "empty": bool}`` with ``datetime`` in epoch milliseconds.

:data:`EMPTY_PAYLOAD` stays synthetic (an empty response cannot be
captured for a valid listed symbol).  The ``build_*`` builders remain —
they are SYNTHETIC worst-case generators for ceiling/budget tests
(documented per builder), not live captures; their stamp times follow
the convention parameters so convention-parameterized tests keep
exercising both branches.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
"""Exchange timezone used for every stamp and bucket rule (data-model)."""

UTC = timezone.utc

MS_PER_MINUTE = 60_000
MS_PER_HOUR = 3_600_000

# ----------------------------------------------------------------------
# Symbols (grammar examples of contracts/mcp-tools.md §1)
# ----------------------------------------------------------------------

SYMBOL = "SPY"
"""Equity symbol of the live daily capture."""

INDEX_SYMBOL = "$SPX"
"""Index symbol (leading ``$`` kind)."""

OPTION_SYMBOL = "AAPL 261127C350"
"""Option-contract symbol (quickstart S5) — rejected as ``unsupported_symbol_kind``."""

OPTION_SYMBOL_CANONICAL = "AAPL  261127C350000"
"""Canonical OCC option-contract spelling — also rejected (D9)."""

NO_HISTORY_SYMBOL = "ZZZZ"
"""Symbol used for the empty-candle fixture (delisted instrument)."""

# ----------------------------------------------------------------------
# Stamping conventions (research D6/D7/D8 — PINNED by the live capture)
# ----------------------------------------------------------------------

STAMPING_CONVENTION = "period_start"
"""PINNED (live capture 2026-11-02): intraday candles are stamped at
their period START (30-minute regular session: 09:30 .. 15:30 ET).
"""

STAMPING_CONVENTION_PINNED = True
"""The live capture pinned the intraday convention."""

STAMPING_CONVENTIONS = ("period_start", "period_end")
"""Both candidate conventions (D8) still exercised by parameterized
synthetic tests (the builders accept either); production uses the
pinned :data:`STAMPING_CONVENTION`."""

WEEKLY_STAMP_CONVENTION = "week_open"
"""PINNED (live capture 2026-11-02): weekly candles are stamped at the
ISO week's FIRST session (Monday).  FR-019 needs the D7 relabel-forward
path (pass-through would violate the closing-session requirement).
"""

WEEKLY_STAMP_CONVENTION_PINNED = True
"""The live capture pinned the weekly convention."""

WEEKLY_STAMP_CONVENTIONS = ("week_open", "week_close")
"""Both candidate weekly conventions (D7) still exercised by
parameterized synthetic tests."""

DAILY_STAMP_UTC_HOUR = 5
"""PINNED (live capture): daily candles are stamped at 05:00 UTC —
01:00 ET under EDT (00:00 under EST).  The stamp's calendar date is the
session date, so the D6 period-end rule (session close at/after the
stamp) resolves to the same day's 16:00 close under either DST regime.
"""

SESSION_OPEN = (9, 30)
SESSION_CLOSE = (16, 0)


# ----------------------------------------------------------------------
# Calendar / period helpers (deterministic; no network, no clock reads)
# ----------------------------------------------------------------------

def _et_ms(y: int, m: int, d: int, hh: int, mm: int = 0) -> int:
    return int(datetime(y, m, d, hh, mm, tzinfo=ET).timestamp() * 1000)


def _utc_ms(y: int, m: int, d: int, hh: int, mm: int = 0) -> int:
    return int(datetime(y, m, d, hh, mm, tzinfo=UTC).timestamp() * 1000)


def _weekday_dates(end: tuple[int, int, int], count: int) -> list[tuple[int, int, int]]:
    """The *count* weekdays ending at *end* (inclusive), oldest first."""
    cur = datetime(*end)
    out: list[datetime] = []
    while len(out) < count:
        if cur.weekday() < 5:
            out.append(cur)
        cur -= timedelta(days=1)
    return [(d.year, d.month, d.day) for d in reversed(out)]


def _daily_live_stamp(date: tuple[int, int, int]) -> int:
    """The observed daily stamp for a session date: 05:00 UTC (D8)."""
    return _utc_ms(*date, DAILY_STAMP_UTC_HOUR, 0)


def _stamp(
    date: tuple[int, int, int],
    convention: str = STAMPING_CONVENTION,
    *,
    kind: str = "intraday",
) -> int:
    """Stamp a session per *convention* (synthetic builders only).

    Intraday ``period_start``/``period_end`` use the session open/close
    (09:30/16:00 ET); daily uses the observed 05:00-UTC stamp for
    ``period_start`` and the 16:00 close for ``period_end``.
    """
    if kind == "daily":
        if convention == "period_end":
            return _et_ms(*date, *SESSION_CLOSE)
        return _daily_live_stamp(date)
    hh, mm = SESSION_OPEN if convention == "period_start" else SESSION_CLOSE
    return _et_ms(*date, hh, mm)


# ----------------------------------------------------------------------
# Period-end / label helpers (D6/D7 rules, convention-parameterized)
# ----------------------------------------------------------------------

def daily_period_end(
    stamp_ms: int, convention: str = STAMPING_CONVENTION
) -> int:
    """Period end of a daily candle: the session close (16:00 ET).

    Under the pinned convention the stamp (05:00 UTC / 01:00 ET) is the
    session's start-side stamp, so the close is the same day's 16:00.
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

    Regular session 09:30–16:00 ET.  Under the pinned
    ``"period_start"`` a regular candle stamps in ``[09:30, 16:00)``;
    under ``"period_end"`` in ``(09:30, 16:00]``.
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
    stamped in the provider's own convention — the stamp's time-of-day
    is preserved so the label matches what the provider would stamp for
    that Friday session (live cross-check: the relabelled current-week
    label equals the daily capture's Friday stamp, both 05:00-UTC-style).
    """
    dt = datetime.fromtimestamp(stamp_ms / 1000, ET)
    friday = dt + timedelta(days=4 - dt.weekday())
    relabeled = dt.replace(year=friday.year, month=friday.month, day=friday.day)
    return int(relabeled.timestamp() * 1000)


def weekly_period_end(stamp_ms: int) -> int:
    """Period end of a weekly candle: the closing session's close (16:00 ET)."""
    return daily_period_end(iso_week_close_session(stamp_ms), STAMPING_CONVENTION)


# ----------------------------------------------------------------------
# Synthetic payload builders (WORST-CASE geometry for ceiling/budget
# tests — deterministic, NOT live captures; stamps follow the
# convention parameters so parameterized tests keep both branches)
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
    end: tuple[int, int, int] = (2026, 10, 30),
) -> dict[str, Any]:
    """SYNTHETIC daily candles (worst-case sizes: ``sessions=252`` for the
    1y ceiling).  Stamps: 05:00-UTC-style under ``period_start`` (the
    pinned live convention), 16:00 close under ``period_end``."""
    candles = []
    for i, date in enumerate(_weekday_dates(end, sessions)):
        bar = _bar(i, base=580.0, drift=0.31, tick=0.17, vol=41_000_000)
        bar["datetime"] = _stamp(date, convention, kind="daily")
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
    """SYNTHETIC weekly candles (worst-case sizes: ``weeks=260`` for the
    5y ceiling).  Weeks anchored on their Friday closing sessions;
    ``week_open`` stamps the Monday, ``week_close`` the Friday."""
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
    """SYNTHETIC 30-minute candles (uniform 13/session regular geometry;
    the live extended capture has uneven pre/post coverage, so worst-case
    ceiling tests use this uniform builder instead).  Regular session
    09:30–16:00 → 13 candles; with *extended*, 04:00–09:30 and 16:00–20:00
    added → 32/session."""
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
    """SYNTHETIC empty response (no live capture possible for a valid
    listed symbol) — FR-008 shape."""
    return {"candles": [], "symbol": symbol, "empty": True}


# ----------------------------------------------------------------------
# LIVE-captured fixture constants (2026-11-02, authorized session)
# ----------------------------------------------------------------------
"""Live daily ``1m`` window: 23 sessions (SPY, Sep 30 – Oct 30 2026),
stamped at 05:00 UTC (01:00 ET) — the D8 daily-stamp pin."""

DAILY_PAYLOAD: dict = {'symbol': 'SPY', 'empty': False, 'candles': [{'open': 766.45, 'high': 769.41, 'low': 762.18, 'close': 762.63, 'volume': 62110041, 'datetime': 1790744400000}, {'open': 764.36, 'high': 765.65, 'low': 758.7901, 'close': 763.99, 'volume': 47708058, 'datetime': 1790830800000}, {'open': 770.58, 'high': 772.65, 'low': 767.145, 'close': 769.64, 'volume': 46335295, 'datetime': 1790917200000}, {'open': 769.69, 'high': 776.605, 'low': 769.63, 'close': 774.83, 'volume': 44840163, 'datetime': 1791176400000}, {'open': 778.15, 'high': 781.62, 'low': 777.96, 'close': 779.09, 'volume': 36054294, 'datetime': 1791262800000}, {'open': 775.77, 'high': 779.1021, 'low': 773.61, 'close': 777.22, 'volume': 31049546, 'datetime': 1791349200000}, {'open': 774.86, 'high': 777.09, 'low': 770.435, 'close': 773.93, 'volume': 40500302, 'datetime': 1791435600000}, {'open': 776.24, 'high': 779.42, 'low': 775.14, 'close': 778.57, 'volume': 22676398, 'datetime': 1791522000000}, {'open': 778.78, 'high': 779.397, 'low': 777.05, 'close': 778.1, 'volume': 18748981, 'datetime': 1791781200000}, {'open': 777.34, 'high': 778.75, 'low': 775.95, 'close': 778.01, 'volume': 25954304, 'datetime': 1791867600000}, {'open': 774.92, 'high': 776.35, 'low': 766.71, 'close': 769.6, 'volume': 55794122, 'datetime': 1791954000000}, {'open': 766.25, 'high': 772.87, 'low': 764.43, 'close': 771.79, 'volume': 43453373, 'datetime': 1792040400000}, {'open': 773.24, 'high': 773.25, 'low': 760.64, 'close': 763.25, 'volume': 64470602, 'datetime': 1792126800000}, {'open': 767.23, 'high': 770.46, 'low': 765.824, 'close': 766.48, 'volume': 38864730, 'datetime': 1792386000000}, {'open': 765.86, 'high': 772.29, 'low': 764.25, 'close': 769.05, 'volume': 35132493, 'datetime': 1792472400000}, {'open': 771.17, 'high': 774.44, 'low': 768.4, 'close': 773.09, 'volume': 32017185, 'datetime': 1792558800000}, {'open': 766.37, 'high': 767.71, 'low': 761.165, 'close': 763.96, 'volume': 54248094, 'datetime': 1792645200000}, {'open': 759.896, 'high': 763.47, 'low': 758.68, 'close': 759.97, 'volume': 33539738, 'datetime': 1792731600000}, {'open': 762.25, 'high': 767.73, 'low': 761.63, 'close': 765.37, 'volume': 31840892, 'datetime': 1792990800000}, {'open': 767.34, 'high': 771.14, 'low': 765.21, 'close': 769.66, 'volume': 28681358, 'datetime': 1793077200000}, {'open': 771.43, 'high': 773.36, 'low': 769.24, 'close': 772.31, 'volume': 30205811, 'datetime': 1793163600000}, {'open': 768.79, 'high': 770.76, 'low': 766.62, 'close': 769.36, 'volume': 40452131, 'datetime': 1793250000000}, {'open': 761.38, 'high': 761.46, 'low': 750.36, 'close': 755.72, 'volume': 77859729, 'datetime': 1793336400000}]}



"""Live weekly ``1y``: 52 candles (AAPL), ALL stamped at the ISO week's
Monday 01:00 (week_open) — the D7 relabel-forward pin for FR-019."""

WEEKLY_PAYLOAD: dict = {'symbol': 'AAPL', 'empty': False, 'candles': [{'open': 270.42, 'high': 273.4, 'low': 266.25, 'close': 268.47, 'volume': 242583911, 'datetime': 1762149600000}, {'open': 268.96, 'high': 276.699, 'low': 267.455, 'close': 272.41, 'volume': 232952837, 'datetime': 1762754400000}, {'open': 268.815, 'high': 275.43, 'low': 265.32, 'close': 271.49, 'volume': 235974430, 'datetime': 1763359200000}, {'open': 270.9, 'high': 280.38, 'low': 270.9, 'close': 278.85, 'volume': 166067059, 'datetime': 1763964000000}, {'open': 278.01, 'high': 288.62, 'low': 276.14, 'close': 278.78, 'volume': 235050842, 'datetime': 1764568800000}, {'open': 278.13, 'high': 280.03, 'low': 273.81, 'close': 278.28, 'volume': 176224279, 'datetime': 1765173600000}, {'open': 280.15, 'high': 280.15, 'low': 266.95, 'close': 273.67, 'volume': 334459218, 'datetime': 1765778400000}, {'open': 272.86, 'high': 275.43, 'low': 269.56, 'close': 273.4, 'volume': 105646202, 'datetime': 1766383200000}, {'open': 272.69, 'high': 277.84, 'low': 269.0, 'close': 271.01, 'volume': 110986523, 'datetime': 1766988000000}, {'open': 270.64, 'high': 271.51, 'low': 255.7, 'close': 259.37, 'volume': 236725388, 'datetime': 1767592800000}, {'open': 259.16, 'high': 261.82, 'low': 254.93, 'close': 255.53, 'volume': 242545372, 'datetime': 1768197600000}, {'open': 252.73, 'high': 254.79, 'low': 243.42, 'close': 248.04, 'volume': 216306564, 'datetime': 1768802400000}, {'open': 251.48, 'high': 261.95, 'low': 249.8, 'close': 259.48, 'volume': 306601893, 'datetime': 1769407200000}, {'open': 260.03, 'high': 280.905, 'low': 259.205, 'close': 278.12, 'volume': 332284645, 'datetime': 1770012000000}, {'open': 277.905, 'high': 280.18, 'low': 255.45, 'close': 255.78, 'volume': 268299479, 'datetime': 1770616800000}, {'open': 258.05, 'high': 266.82, 'low': 255.54, 'close': 264.58, 'volume': 165588224, 'datetime': 1771221600000}, {'open': 263.49, 'high': 276.11, 'low': 262.89, 'close': 264.18, 'volume': 222748737, 'datetime': 1771826400000}, {'open': 262.41, 'high': 266.53, 'low': 254.37, 'close': 257.46, 'volume': 210978656, 'datetime': 1772431200000}, {'open': 255.69, 'high': 262.48, 'low': 249.52, 'close': 250.12, 'volume': 172752234, 'datetime': 1773032400000}, {'open': 252.105, 'high': 255.13, 'low': 246.0, 'close': 247.99, 'volume': 223388854, 'datetime': 1773637200000}, {'open': 253.97, 'high': 257.0, 'low': 248.07, 'close': 248.8, 'volume': 203871715, 'datetime': 1774242000000}, {'open': 250.07, 'high': 256.18, 'low': 245.51, 'close': 255.92, 'volume': 160393106, 'datetime': 1774846800000}, {'open': 256.51, 'high': 262.19, 'low': 245.7, 'close': 260.48, 'volume': 191923740, 'datetime': 1775451600000}, {'open': 259.73, 'high': 272.3, 'low': 256.66, 'close': 270.23, 'volume': 239278259, 'datetime': 1776056400000}, {'open': 270.33, 'high': 275.77, 'low': 265.4, 'close': 271.06, 'volume': 201605879, 'datetime': 1776661200000}, {'open': 266.09, 'high': 287.22, 'low': 265.07, 'close': 280.14, 'volume': 283297245, 'datetime': 1777266000000}, {'open': 279.655, 'high': 294.76, 'low': 274.8601, 'close': 293.32, 'volume': 252233247, 'datetime': 1777870800000}, {'open': 291.979, 'high': 303.2, 'low': 290.23, 'close': 300.23, 'volume': 230867434, 'datetime': 1778475600000}, {'open': 300.24, 'high': 311.4, 'low': 294.91, 'close': 308.82, 'volume': 201591715, 'datetime': 1779080400000}, {'open': 309.56, 'high': 315.0, 'low': 307.67, 'close': 312.06, 'volume': 216678556, 'datetime': 1779685200000}, {'open': 309.625, 'high': 316.94, 'low': 305.02, 'close': 307.34, 'volume': 254400992, 'datetime': 1780290000000}, {'open': 308.739, 'high': 317.4, 'low': 287.38, 'close': 291.13, 'volume': 282208483, 'datetime': 1780894800000}, {'open': 294.12, 'high': 302.07, 'low': 291.7, 'close': 298.01, 'volume': 214314239, 'datetime': 1781499600000}, {'open': 297.31, 'high': 302.42, 'low': 273.75, 'close': 283.78, 'volume': 519001814, 'datetime': 1782104400000}, {'open': 286.73, 'high': 309.42, 'low': 279.85, 'close': 308.63, 'volume': 257092016, 'datetime': 1782709200000}, {'open': 307.36, 'high': 316.91, 'low': 307.0, 'close': 315.32, 'volume': 219660273, 'datetime': 1783314000000}, {'open': 317.015, 'high': 334.99, 'low': 311.91, 'close': 333.74, 'volume': 266929954, 'datetime': 1783918800000}, {'open': 333.505, 'high': 334.37, 'low': 319.35, 'close': 333.02, 'volume': 221893050, 'datetime': 1784523600000}, {'open': 334.54, 'high': 344.5699, 'low': 300.0, 'close': 308.91, 'volume': 364861110, 'datetime': 1785128400000}, {'open': 309.58, 'high': 316.2894, 'low': 301.32, 'close': 313.33, 'volume': 273068777, 'datetime': 1785733200000}, {'open': 306.83, 'high': 309.97, 'low': 300.57, 'close': 305.93, 'volume': 192525682, 'datetime': 1786338000000}, {'open': 306.21, 'high': 320.28, 'low': 302.939, 'close': 309.35, 'volume': 229935446, 'datetime': 1786942800000}, {'open': 311.47, 'high': 322.37, 'low': 308.21, 'close': 319.7, 'volume': 165636509, 'datetime': 1787547600000}, {'open': 319.6, 'high': 330.81, 'low': 312.8, 'close': 319.97, 'volume': 205019207, 'datetime': 1788152400000}, {'open': 317.1, 'high': 336.22, 'low': 309.9, 'close': 332.27, 'volume': 221845830, 'datetime': 1788757200000}, {'open': 334.79, 'high': 338.49, 'low': 328.35, 'close': 336.13, 'volume': 230286759, 'datetime': 1789362000000}, {'open': 335.28, 'high': 345.34, 'low': 333.05, 'close': 341.07, 'volume': 162105444, 'datetime': 1789966800000}, {'open': 340.37, 'high': 342.988, 'low': 325.81, 'close': 333.69, 'volume': 190872343, 'datetime': 1790571600000}, {'open': 332.815, 'high': 341.57, 'low': 330.62, 'close': 336.64, 'volume': 172384524, 'datetime': 1791176400000}, {'open': 338.215, 'high': 348.1499, 'low': 337.6, 'close': 343.46, 'volume': 215095387, 'datetime': 1791781200000}, {'open': 340.775, 'high': 351.73, 'low': 338.7, 'close': 347.725, 'volume': 192946702, 'datetime': 1792386000000}, {'open': 343.92, 'high': 351.43, 'low': 334.35, 'close': 344.63, 'volume': 229312223, 'datetime': 1792990800000}]}



"""Live 30-minute ``5d`` regular session: 65 candles (AAPL, 13/session),
stamped at period start 09:30 .. 15:30 — the D8 intraday pin."""

MINUTE_30M_PAYLOAD: dict = {'symbol': 'AAPL', 'empty': False, 'candles': [{'open': 343.92, 'high': 346.215, 'low': 341.03, 'close': 343.24, 'volume': 4061806, 'datetime': 1793021400000}, {'open': 343.21, 'high': 345.63, 'low': 343.02, 'close': 345.46, 'volume': 1616567, 'datetime': 1793023200000}, {'open': 345.42, 'high': 346.9196, 'low': 344.63, 'close': 346.575, 'volume': 1551169, 'datetime': 1793025000000}, {'open': 346.6, 'high': 347.09, 'low': 345.59, 'close': 345.65, 'volume': 1327919, 'datetime': 1793026800000}, {'open': 345.615, 'high': 345.85, 'low': 344.44, 'close': 344.57, 'volume': 1258252, 'datetime': 1793028600000}, {'open': 344.6, 'high': 345.01, 'low': 343.85, 'close': 344.69, 'volume': 880966, 'datetime': 1793030400000}, {'open': 344.705, 'high': 344.705, 'low': 342.16, 'close': 343.68, 'volume': 1753888, 'datetime': 1793032200000}, {'open': 343.67, 'high': 344.32, 'low': 343.5, 'close': 343.8, 'volume': 904467, 'datetime': 1793034000000}, {'open': 343.79, 'high': 343.97, 'low': 342.4301, 'close': 343.54, 'volume': 1268127, 'datetime': 1793035800000}, {'open': 343.55, 'high': 343.77, 'low': 342.935, 'close': 343.19, 'volume': 812189, 'datetime': 1793037600000}, {'open': 343.19, 'high': 343.29, 'low': 342.45, 'close': 342.96, 'volume': 987725, 'datetime': 1793039400000}, {'open': 342.92, 'high': 344.06, 'low': 342.72, 'close': 343.55, 'volume': 1193472, 'datetime': 1793041200000}, {'open': 343.575, 'high': 344.75, 'low': 343.445, 'close': 343.98, 'volume': 3012918, 'datetime': 1793043000000}, {'open': 343.165, 'high': 345.1, 'low': 342.39, 'close': 342.9461, 'volume': 2760817, 'datetime': 1793107800000}, {'open': 342.93, 'high': 345.09, 'low': 342.92, 'close': 344.75, 'volume': 1404239, 'datetime': 1793109600000}, {'open': 344.76, 'high': 346.57, 'low': 344.76, 'close': 346.507, 'volume': 1844366, 'datetime': 1793111400000}, {'open': 346.51, 'high': 347.78, 'low': 346.495, 'close': 347.35, 'volume': 2338054, 'datetime': 1793113200000}, {'open': 347.34, 'high': 347.605, 'low': 346.56, 'close': 346.93, 'volume': 1044629, 'datetime': 1793115000000}, {'open': 346.945, 'high': 347.0, 'low': 345.83, 'close': 346.252, 'volume': 1005405, 'datetime': 1793116800000}, {'open': 346.26, 'high': 346.87, 'low': 345.9, 'close': 346.21, 'volume': 729974, 'datetime': 1793118600000}, {'open': 346.19, 'high': 346.36, 'low': 345.2125, 'close': 345.49, 'volume': 876742, 'datetime': 1793120400000}, {'open': 345.5, 'high': 346.22, 'low': 345.41, 'close': 345.98, 'volume': 583502, 'datetime': 1793122200000}, {'open': 345.96, 'high': 346.06, 'low': 345.37, 'close': 345.565, 'volume': 566689, 'datetime': 1793124000000}, {'open': 345.556, 'high': 346.47, 'low': 345.46, 'close': 346.46, 'volume': 757721, 'datetime': 1793125800000}, {'open': 346.46, 'high': 347.44, 'low': 345.86, 'close': 347.17, 'volume': 1461920, 'datetime': 1793127600000}, {'open': 347.17, 'high': 347.56, 'low': 346.25, 'close': 347.08, 'volume': 2963002, 'datetime': 1793129400000}, {'open': 346.94, 'high': 347.2, 'low': 344.71, 'close': 344.785, 'volume': 2561667, 'datetime': 1793194200000}, {'open': 344.76, 'high': 345.65, 'low': 344.62, 'close': 344.66, 'volume': 1151828, 'datetime': 1793196000000}, {'open': 344.69, 'high': 345.61, 'low': 344.57, 'close': 345.47, 'volume': 1253023, 'datetime': 1793197800000}, {'open': 345.51, 'high': 345.65, 'low': 344.96, 'close': 345.56, 'volume': 893434, 'datetime': 1793199600000}, {'open': 345.55, 'high': 345.6, 'low': 344.81, 'close': 345.29, 'volume': 623917, 'datetime': 1793201400000}, {'open': 345.285, 'high': 345.7784, 'low': 345.22, 'close': 345.51, 'volume': 680945, 'datetime': 1793203200000}, {'open': 345.52, 'high': 346.3299, 'low': 345.49, 'close': 345.9, 'volume': 971376, 'datetime': 1793205000000}, {'open': 345.92, 'high': 345.94, 'low': 345.33, 'close': 345.45, 'volume': 758436, 'datetime': 1793206800000}, {'open': 345.456, 'high': 345.8, 'low': 345.12, 'close': 345.235, 'volume': 800264, 'datetime': 1793208600000}, {'open': 345.235, 'high': 345.73, 'low': 344.1, 'close': 344.665, 'volume': 1192960, 'datetime': 1793210400000}, {'open': 344.68, 'high': 345.2848, 'low': 344.13, 'close': 344.38, 'volume': 1113116, 'datetime': 1793212200000}, {'open': 344.37, 'high': 344.98, 'low': 343.9, 'close': 344.13, 'volume': 1092150, 'datetime': 1793214000000}, {'open': 344.12, 'high': 344.87, 'low': 343.52, 'close': 343.86, 'volume': 3488236, 'datetime': 1793215800000}, {'open': 348.1, 'high': 351.43, 'low': 347.3, 'close': 349.73, 'volume': 5812675, 'datetime': 1793280600000}, {'open': 349.75, 'high': 350.71, 'low': 349.39, 'close': 349.851, 'volume': 1928196, 'datetime': 1793282400000}, {'open': 349.83, 'high': 350.17, 'low': 348.41, 'close': 349.135, 'volume': 1298491, 'datetime': 1793284200000}, {'open': 349.18, 'high': 349.77, 'low': 348.36, 'close': 348.915, 'volume': 967921, 'datetime': 1793286000000}, {'open': 348.915, 'high': 349.55, 'low': 348.66, 'close': 349.26, 'volume': 940557, 'datetime': 1793287800000}, {'open': 349.26, 'high': 349.61, 'low': 348.93, 'close': 349.4651, 'volume': 868825, 'datetime': 1793289600000}, {'open': 349.465, 'high': 350.13, 'low': 349.07, 'close': 349.7701, 'volume': 1211362, 'datetime': 1793291400000}, {'open': 349.77, 'high': 349.99, 'low': 349.61, 'close': 349.78, 'volume': 751659, 'datetime': 1793293200000}, {'open': 349.79, 'high': 349.89, 'low': 349.32, 'close': 349.725, 'volume': 843779, 'datetime': 1793295000000}, {'open': 349.725, 'high': 350.15, 'low': 349.7, 'close': 349.87, 'volume': 929559, 'datetime': 1793296800000}, {'open': 349.88, 'high': 350.6, 'low': 349.78, 'close': 350.1, 'volume': 1115288, 'datetime': 1793298600000}, {'open': 350.1, 'high': 350.395, 'low': 350.02, 'close': 350.39, 'volume': 1107616, 'datetime': 1793300400000}, {'open': 350.3831, 'high': 350.44, 'low': 348.27, 'close': 348.94, 'volume': 3715876, 'datetime': 1793302200000}, {'open': 346.63, 'high': 348.7696, 'low': 344.13, 'close': 345.33, 'volume': 5113553, 'datetime': 1793367000000}, {'open': 345.29, 'high': 346.48, 'low': 344.89, 'close': 346.33, 'volume': 2275171, 'datetime': 1793368800000}, {'open': 346.3, 'high': 349.19, 'low': 346.19, 'close': 348.48, 'volume': 2761972, 'datetime': 1793370600000}, {'open': 348.495, 'high': 348.7, 'low': 347.41, 'close': 347.69, 'volume': 1550784, 'datetime': 1793372400000}, {'open': 347.69, 'high': 347.88, 'low': 346.73, 'close': 346.925, 'volume': 1754864, 'datetime': 1793374200000}, {'open': 346.94, 'high': 347.72, 'low': 345.6711, 'close': 347.5, 'volume': 2113429, 'datetime': 1793376000000}, {'open': 347.495, 'high': 347.97, 'low': 346.83, 'close': 346.955, 'volume': 1799163, 'datetime': 1793377800000}, {'open': 346.98, 'high': 347.2199, 'low': 346.245, 'close': 346.55, 'volume': 1936724, 'datetime': 1793379600000}, {'open': 346.56, 'high': 346.6899, 'low': 344.31, 'close': 344.585, 'volume': 2134894, 'datetime': 1793381400000}, {'open': 344.59, 'high': 344.705, 'low': 334.35, 'close': 343.1342, 'volume': 3043503, 'datetime': 1793383200000}, {'open': 343.14, 'high': 343.84, 'low': 342.35, 'close': 343.275, 'volume': 2003560, 'datetime': 1793385000000}, {'open': 343.29, 'high': 343.86, 'low': 342.61, 'close': 343.52, 'volume': 2030657, 'datetime': 1793386800000}, {'open': 343.52, 'high': 346.0, 'low': 343.14, 'close': 344.8, 'volume': 5102233, 'datetime': 1793388600000}]}



"""Live 30-minute ``5d`` with ``needExtendedHoursData=true``: 218 candles
(pre-market from 07:00 ET, post-market to 19:30 ET) — the extended-hours
pair evidence; the derived 04:00/20:00 assumption was wrong."""

INTRADAY_EXTENDED_PAYLOAD: dict = {'symbol': 'AAPL', 'empty': False, 'candles': [{'open': 343.375, 'high': 343.8672, 'low': 343.18, 'close': 343.61, 'volume': 60149, 'datetime': 1793012400000}, {'open': 343.6, 'high': 343.64, 'low': 341.35, 'close': 342.36, 'volume': 195059, 'datetime': 1793014200000}, {'open': 342.15, 'high': 343.5, 'low': 341.65, 'close': 343.2883, 'volume': 161915, 'datetime': 1793016000000}, {'open': 343.4, 'high': 343.5, 'low': 342.68, 'close': 343.5, 'volume': 113817, 'datetime': 1793017800000}, {'open': 343.7768, 'high': 344.51, 'low': 343.2, 'close': 343.9, 'volume': 189463, 'datetime': 1793019600000}, {'open': 343.92, 'high': 346.215, 'low': 341.03, 'close': 343.24, 'volume': 4061806, 'datetime': 1793021400000}, {'open': 343.21, 'high': 345.63, 'low': 343.02, 'close': 345.46, 'volume': 1616567, 'datetime': 1793023200000}, {'open': 345.42, 'high': 346.9196, 'low': 344.63, 'close': 346.575, 'volume': 1551169, 'datetime': 1793025000000}, {'open': 346.6, 'high': 347.09, 'low': 345.59, 'close': 345.65, 'volume': 1327919, 'datetime': 1793026800000}, {'open': 345.615, 'high': 345.85, 'low': 344.44, 'close': 344.57, 'volume': 1258252, 'datetime': 1793028600000}, {'open': 344.6, 'high': 345.01, 'low': 343.85, 'close': 344.69, 'volume': 880966, 'datetime': 1793030400000}, {'open': 344.705, 'high': 344.705, 'low': 342.16, 'close': 343.68, 'volume': 1753888, 'datetime': 1793032200000}, {'open': 343.67, 'high': 344.32, 'low': 343.5, 'close': 343.8, 'volume': 904467, 'datetime': 1793034000000}, {'open': 343.79, 'high': 343.97, 'low': 342.4301, 'close': 343.54, 'volume': 1268127, 'datetime': 1793035800000}, {'open': 343.55, 'high': 343.77, 'low': 342.935, 'close': 343.19, 'volume': 812189, 'datetime': 1793037600000}, {'open': 343.19, 'high': 343.29, 'low': 342.45, 'close': 342.96, 'volume': 987725, 'datetime': 1793039400000}, {'open': 342.92, 'high': 344.06, 'low': 342.72, 'close': 343.55, 'volume': 1193472, 'datetime': 1793041200000}, {'open': 343.575, 'high': 344.75, 'low': 343.445, 'close': 343.98, 'volume': 3012918, 'datetime': 1793043000000}, {'open': 343.99, 'high': 344.2, 'low': 343.87, 'close': 344.2, 'volume': 10262049, 'datetime': 1793044800000}, {'open': 344.0587, 'high': 344.27, 'low': 343.91, 'close': 343.91, 'volume': 91825, 'datetime': 1793046600000}, {'open': 343.9324, 'high': 344.0, 'low': 343.8, 'close': 343.8007, 'volume': 7387, 'datetime': 1793048400000}, {'open': 343.94, 'high': 343.94, 'low': 343.5, 'close': 343.5, 'volume': 12934, 'datetime': 1793050200000}, {'open': 343.55, 'high': 343.55, 'low': 342.82, 'close': 343.0, 'volume': 23218, 'datetime': 1793052000000}, {'open': 343.09, 'high': 343.5, 'low': 343.08, 'close': 343.2, 'volume': 8610, 'datetime': 1793053800000}, {'open': 343.02, 'high': 343.47, 'low': 342.85, 'close': 343.3409, 'volume': 9928, 'datetime': 1793055600000}, {'open': 343.47, 'high': 343.87, 'low': 343.31, 'close': 343.5639, 'volume': 30199, 'datetime': 1793057400000}, {'open': 343.25, 'high': 343.75, 'low': 343.21, 'close': 343.4, 'volume': 2824, 'datetime': 1793059200000}, {'open': 343.39, 'high': 343.63, 'low': 343.35, 'close': 343.38, 'volume': 1121, 'datetime': 1793061000000}, {'open': 343.4, 'high': 343.54, 'low': 343.04, 'close': 343.3, 'volume': 5034, 'datetime': 1793062800000}, {'open': 343.19, 'high': 343.44, 'low': 343.08, 'close': 343.44, 'volume': 1865, 'datetime': 1793064600000}, {'open': 343.36, 'high': 343.36, 'low': 343.02, 'close': 343.26, 'volume': 2458, 'datetime': 1793066400000}, {'open': 343.25, 'high': 343.41, 'low': 343.02, 'close': 343.3, 'volume': 2697, 'datetime': 1793068200000}, {'open': 343.26, 'high': 343.33, 'low': 342.83, 'close': 343.13, 'volume': 5472, 'datetime': 1793070000000}, {'open': 343.2, 'high': 343.39, 'low': 343.12, 'close': 343.33, 'volume': 762, 'datetime': 1793071800000}, {'open': 343.33, 'high': 343.38, 'low': 343.06, 'close': 343.16, 'volume': 1815, 'datetime': 1793073600000}, {'open': 343.1, 'high': 343.28, 'low': 342.9, 'close': 343.04, 'volume': 3932, 'datetime': 1793075400000}, {'open': 343.02, 'high': 343.18, 'low': 342.53, 'close': 342.77, 'volume': 5312, 'datetime': 1793077200000}, {'open': 342.76, 'high': 343.19, 'low': 342.27, 'close': 343.12, 'volume': 4914, 'datetime': 1793079000000}, {'open': 343.12, 'high': 343.18, 'low': 342.75, 'close': 342.8, 'volume': 1439, 'datetime': 1793080800000}, {'open': 342.8, 'high': 343.0, 'low': 342.55, 'close': 342.78, 'volume': 1443, 'datetime': 1793082600000}, {'open': 342.7, 'high': 343.21, 'low': 342.52, 'close': 343.14, 'volume': 2981, 'datetime': 1793084400000}, {'open': 343.14, 'high': 343.2, 'low': 342.77, 'close': 343.2, 'volume': 1890, 'datetime': 1793086200000}, {'open': 343.37, 'high': 343.37, 'low': 342.8, 'close': 342.81, 'volume': 9010, 'datetime': 1793088000000}, {'open': 342.75, 'high': 343.0, 'low': 342.6, 'close': 343.0, 'volume': 10034, 'datetime': 1793089800000}, {'open': 343.24, 'high': 343.48, 'low': 342.91, 'close': 343.25, 'volume': 11066, 'datetime': 1793091600000}, {'open': 343.22, 'high': 343.22, 'low': 342.6, 'close': 342.75, 'volume': 10932, 'datetime': 1793093400000}, {'open': 342.78, 'high': 342.78, 'low': 342.2, 'close': 342.48, 'volume': 16101, 'datetime': 1793095200000}, {'open': 342.25, 'high': 343.48, 'low': 342.0, 'close': 342.35, 'volume': 21101, 'datetime': 1793097000000}, {'open': 342.48, 'high': 343.22, 'low': 342.23, 'close': 342.9, 'volume': 38058, 'datetime': 1793098800000}, {'open': 342.77, 'high': 342.8599, 'low': 342.31, 'close': 342.5699, 'volume': 31860, 'datetime': 1793100600000}, {'open': 342.59, 'high': 343.24, 'low': 342.41, 'close': 342.85, 'volume': 29630, 'datetime': 1793102400000}, {'open': 342.7, 'high': 342.99, 'low': 342.3, 'close': 342.6, 'volume': 34798, 'datetime': 1793104200000}, {'open': 342.714, 'high': 343.37, 'low': 342.39, 'close': 343.27, 'volume': 76581, 'datetime': 1793106000000}, {'open': 343.165, 'high': 345.1, 'low': 342.39, 'close': 342.9461, 'volume': 2760817, 'datetime': 1793107800000}, {'open': 342.93, 'high': 345.09, 'low': 342.92, 'close': 344.75, 'volume': 1404239, 'datetime': 1793109600000}, {'open': 344.76, 'high': 346.57, 'low': 344.76, 'close': 346.507, 'volume': 1844366, 'datetime': 1793111400000}, {'open': 346.51, 'high': 347.78, 'low': 346.495, 'close': 347.35, 'volume': 2338054, 'datetime': 1793113200000}, {'open': 347.34, 'high': 347.605, 'low': 346.56, 'close': 346.93, 'volume': 1044629, 'datetime': 1793115000000}, {'open': 346.945, 'high': 347.0, 'low': 345.83, 'close': 346.252, 'volume': 1005405, 'datetime': 1793116800000}, {'open': 346.26, 'high': 346.87, 'low': 345.9, 'close': 346.21, 'volume': 729974, 'datetime': 1793118600000}, {'open': 346.19, 'high': 346.36, 'low': 345.2125, 'close': 345.49, 'volume': 876742, 'datetime': 1793120400000}, {'open': 345.5, 'high': 346.22, 'low': 345.41, 'close': 345.98, 'volume': 583502, 'datetime': 1793122200000}, {'open': 345.96, 'high': 346.06, 'low': 345.37, 'close': 345.565, 'volume': 566689, 'datetime': 1793124000000}, {'open': 345.556, 'high': 346.47, 'low': 345.46, 'close': 346.46, 'volume': 757721, 'datetime': 1793125800000}, {'open': 346.46, 'high': 347.44, 'low': 345.86, 'close': 347.17, 'volume': 1461920, 'datetime': 1793127600000}, {'open': 347.17, 'high': 347.56, 'low': 346.25, 'close': 347.08, 'volume': 2963002, 'datetime': 1793129400000}, {'open': 347.07, 'high': 347.78, 'low': 347.0, 'close': 347.15, 'volume': 8274419, 'datetime': 1793131200000}, {'open': 347.0108, 'high': 347.33, 'low': 347.0, 'close': 347.3, 'volume': 67484, 'datetime': 1793133000000}, {'open': 347.1851, 'high': 347.3, 'low': 347.1577, 'close': 347.2, 'volume': 3826, 'datetime': 1793134800000}, {'open': 347.2, 'high': 347.4, 'low': 347.0, 'close': 347.23, 'volume': 17712, 'datetime': 1793136600000}, {'open': 347.19, 'high': 347.19, 'low': 346.81, 'close': 347.15, 'volume': 6030, 'datetime': 1793138400000}, {'open': 347.14, 'high': 347.29, 'low': 347.0872, 'close': 347.1591, 'volume': 4272, 'datetime': 1793140200000}, {'open': 347.16, 'high': 347.4, 'low': 347.07, 'close': 347.3791, 'volume': 12475, 'datetime': 1793142000000}, {'open': 347.28, 'high': 347.4, 'low': 347.1, 'close': 347.1077, 'volume': 7990, 'datetime': 1793143800000}, {'open': 346.99, 'high': 347.17, 'low': 346.74, 'close': 346.83, 'volume': 3203, 'datetime': 1793145600000}, {'open': 346.85, 'high': 346.85, 'low': 346.51, 'close': 346.51, 'volume': 2211, 'datetime': 1793147400000}, {'open': 346.52, 'high': 346.76, 'low': 346.34, 'close': 346.67, 'volume': 7267, 'datetime': 1793149200000}, {'open': 346.67, 'high': 346.73, 'low': 346.19, 'close': 346.43, 'volume': 6957, 'datetime': 1793151000000}, {'open': 346.43, 'high': 346.57, 'low': 346.3, 'close': 346.46, 'volume': 5999, 'datetime': 1793152800000}, {'open': 346.48, 'high': 346.65, 'low': 346.3, 'close': 346.43, 'volume': 2198, 'datetime': 1793154600000}, {'open': 346.44, 'high': 346.59, 'low': 346.31, 'close': 346.33, 'volume': 4765, 'datetime': 1793156400000}, {'open': 346.44, 'high': 346.59, 'low': 345.98, 'close': 346.47, 'volume': 15739, 'datetime': 1793158200000}, {'open': 346.47, 'high': 346.51, 'low': 346.26, 'close': 346.39, 'volume': 4279, 'datetime': 1793160000000}, {'open': 346.39, 'high': 346.49, 'low': 346.36, 'close': 346.48, 'volume': 1874, 'datetime': 1793161800000}, {'open': 346.45, 'high': 346.5, 'low': 346.26, 'close': 346.38, 'volume': 2907, 'datetime': 1793163600000}, {'open': 346.48, 'high': 346.53, 'low': 346.39, 'close': 346.45, 'volume': 2539, 'datetime': 1793165400000}, {'open': 346.46, 'high': 346.49, 'low': 346.26, 'close': 346.39, 'volume': 6750, 'datetime': 1793167200000}, {'open': 346.4, 'high': 346.52, 'low': 346.33, 'close': 346.48, 'volume': 3247, 'datetime': 1793169000000}, {'open': 346.47, 'high': 346.72, 'low': 346.35, 'close': 346.45, 'volume': 4218, 'datetime': 1793170800000}, {'open': 346.46, 'high': 346.64, 'low': 346.0, 'close': 346.13, 'volume': 6710, 'datetime': 1793172600000}, {'open': 346.12, 'high': 346.39, 'low': 346.01, 'close': 346.12, 'volume': 14066, 'datetime': 1793174400000}, {'open': 346.19, 'high': 346.66, 'low': 346.19, 'close': 346.55, 'volume': 6264, 'datetime': 1793176200000}, {'open': 346.41, 'high': 346.52, 'low': 346.03, 'close': 346.03, 'volume': 3454, 'datetime': 1793178000000}, {'open': 346.18, 'high': 346.18, 'low': 345.7, 'close': 345.98, 'volume': 10175, 'datetime': 1793179800000}, {'open': 346.01, 'high': 346.16, 'low': 345.13, 'close': 345.2, 'volume': 21057, 'datetime': 1793181600000}, {'open': 345.15, 'high': 345.6, 'low': 345.0, 'close': 345.1792, 'volume': 20386, 'datetime': 1793183400000}, {'open': 345.25, 'high': 345.5, 'low': 344.62, 'close': 345.45, 'volume': 31378, 'datetime': 1793185200000}, {'open': 345.36, 'high': 346.0, 'low': 345.32, 'close': 345.56, 'volume': 29213, 'datetime': 1793187000000}, {'open': 345.6, 'high': 346.35, 'low': 345.48, 'close': 346.1306, 'volume': 20928, 'datetime': 1793188800000}, {'open': 346.18, 'high': 346.5264, 'low': 345.9, 'close': 346.44, 'volume': 23730, 'datetime': 1793190600000}, {'open': 346.47, 'high': 346.87, 'low': 346.22, 'close': 346.84, 'volume': 37778, 'datetime': 1793192400000}, {'open': 346.94, 'high': 347.2, 'low': 344.71, 'close': 344.785, 'volume': 2561667, 'datetime': 1793194200000}, {'open': 344.76, 'high': 345.65, 'low': 344.62, 'close': 344.66, 'volume': 1151828, 'datetime': 1793196000000}, {'open': 344.69, 'high': 345.61, 'low': 344.57, 'close': 345.47, 'volume': 1253023, 'datetime': 1793197800000}, {'open': 345.51, 'high': 345.65, 'low': 344.96, 'close': 345.56, 'volume': 893434, 'datetime': 1793199600000}, {'open': 345.55, 'high': 345.6, 'low': 344.81, 'close': 345.29, 'volume': 623917, 'datetime': 1793201400000}, {'open': 345.285, 'high': 345.7784, 'low': 345.22, 'close': 345.51, 'volume': 680945, 'datetime': 1793203200000}, {'open': 345.52, 'high': 346.3299, 'low': 345.49, 'close': 345.9, 'volume': 971376, 'datetime': 1793205000000}, {'open': 345.92, 'high': 345.94, 'low': 345.33, 'close': 345.45, 'volume': 758436, 'datetime': 1793206800000}, {'open': 345.456, 'high': 345.8, 'low': 345.12, 'close': 345.235, 'volume': 800264, 'datetime': 1793208600000}, {'open': 345.235, 'high': 345.73, 'low': 344.1, 'close': 344.665, 'volume': 1192960, 'datetime': 1793210400000}, {'open': 344.68, 'high': 345.2848, 'low': 344.13, 'close': 344.38, 'volume': 1113116, 'datetime': 1793212200000}, {'open': 344.37, 'high': 344.98, 'low': 343.9, 'close': 344.13, 'volume': 1092150, 'datetime': 1793214000000}, {'open': 344.12, 'high': 344.87, 'low': 343.52, 'close': 343.86, 'volume': 3488236, 'datetime': 1793215800000}, {'open': 343.86, 'high': 345.59, 'low': 343.82, 'close': 344.9, 'volume': 8905501, 'datetime': 1793217600000}, {'open': 344.9, 'high': 346.5, 'low': 343.83, 'close': 345.96, 'volume': 156634, 'datetime': 1793219400000}, {'open': 345.99, 'high': 346.0, 'low': 345.4007, 'close': 345.96, 'volume': 31459, 'datetime': 1793221200000}, {'open': 345.99, 'high': 346.0, 'low': 344.14, 'close': 344.42, 'volume': 45917, 'datetime': 1793223000000}, {'open': 344.47, 'high': 345.37, 'low': 344.1428, 'close': 345.37, 'volume': 36899, 'datetime': 1793224800000}, {'open': 344.96, 'high': 345.48, 'low': 344.96, 'close': 345.03, 'volume': 32679, 'datetime': 1793226600000}, {'open': 345.0333, 'high': 345.94, 'low': 345.0333, 'close': 345.42, 'volume': 10227, 'datetime': 1793228400000}, {'open': 345.43, 'high': 345.94, 'low': 345.123, 'close': 345.71, 'volume': 12713, 'datetime': 1793230200000}, {'open': 345.77, 'high': 346.45, 'low': 345.38, 'close': 345.87, 'volume': 20966, 'datetime': 1793232000000}, {'open': 345.91, 'high': 346.4, 'low': 345.91, 'close': 346.36, 'volume': 7131, 'datetime': 1793233800000}, {'open': 346.36, 'high': 347.0, 'low': 346.32, 'close': 346.8, 'volume': 12228, 'datetime': 1793235600000}, {'open': 346.8, 'high': 346.87, 'low': 346.1, 'close': 346.8, 'volume': 12187, 'datetime': 1793237400000}, {'open': 346.72, 'high': 346.82, 'low': 346.22, 'close': 346.48, 'volume': 4940, 'datetime': 1793239200000}, {'open': 346.47, 'high': 346.6, 'low': 346.12, 'close': 346.12, 'volume': 2537, 'datetime': 1793241000000}, {'open': 346.15, 'high': 346.25, 'low': 346.0, 'close': 346.03, 'volume': 1957, 'datetime': 1793242800000}, {'open': 346.01, 'high': 346.37, 'low': 346.0, 'close': 346.35, 'volume': 2556, 'datetime': 1793244600000}, {'open': 346.35, 'high': 346.49, 'low': 346.01, 'close': 346.14, 'volume': 2310, 'datetime': 1793246400000}, {'open': 346.08, 'high': 346.5, 'low': 346.06, 'close': 346.3, 'volume': 1137, 'datetime': 1793248200000}, {'open': 346.33, 'high': 346.95, 'low': 346.24, 'close': 346.75, 'volume': 7701, 'datetime': 1793250000000}, {'open': 346.74, 'high': 346.78, 'low': 346.51, 'close': 346.57, 'volume': 1837, 'datetime': 1793251800000}, {'open': 346.69, 'high': 346.95, 'low': 346.57, 'close': 346.75, 'volume': 1924, 'datetime': 1793253600000}, {'open': 346.66, 'high': 346.98, 'low': 346.4, 'close': 346.7, 'volume': 2911, 'datetime': 1793255400000}, {'open': 346.8, 'high': 347.2, 'low': 346.67, 'close': 346.79, 'volume': 4825, 'datetime': 1793257200000}, {'open': 346.67, 'high': 346.67, 'low': 346.16, 'close': 346.39, 'volume': 1988, 'datetime': 1793259000000}, {'open': 346.33, 'high': 347.5, 'low': 346.07, 'close': 347.39, 'volume': 11836, 'datetime': 1793260800000}, {'open': 347.43, 'high': 347.6, 'low': 346.8, 'close': 347.23, 'volume': 15938, 'datetime': 1793262600000}, {'open': 347.3, 'high': 347.68, 'low': 347.23, 'close': 347.42, 'volume': 10056, 'datetime': 1793264400000}, {'open': 347.42, 'high': 348.19, 'low': 347.0643, 'close': 348.02, 'volume': 14895, 'datetime': 1793266200000}, {'open': 348.02, 'high': 348.05, 'low': 347.6, 'close': 347.66, 'volume': 7247, 'datetime': 1793268000000}, {'open': 347.7874, 'high': 348.49, 'low': 347.76, 'close': 348.14, 'volume': 18832, 'datetime': 1793269800000}, {'open': 348.0, 'high': 348.75, 'low': 347.8002, 'close': 348.41, 'volume': 60621, 'datetime': 1793271600000}, {'open': 348.33, 'high': 348.75, 'low': 348.1001, 'close': 348.325, 'volume': 42912, 'datetime': 1793273400000}, {'open': 348.3, 'high': 348.6, 'low': 347.9102, 'close': 348.27, 'volume': 61318, 'datetime': 1793275200000}, {'open': 348.3, 'high': 348.3, 'low': 347.49, 'close': 347.8718, 'volume': 54969, 'datetime': 1793277000000}, {'open': 348.11, 'high': 348.55, 'low': 347.35, 'close': 348.04, 'volume': 119956, 'datetime': 1793278800000}, {'open': 348.1, 'high': 351.43, 'low': 347.3, 'close': 349.73, 'volume': 5812675, 'datetime': 1793280600000}, {'open': 349.75, 'high': 350.71, 'low': 349.39, 'close': 349.851, 'volume': 1928196, 'datetime': 1793282400000}, {'open': 349.83, 'high': 350.17, 'low': 348.41, 'close': 349.135, 'volume': 1298491, 'datetime': 1793284200000}, {'open': 349.18, 'high': 349.77, 'low': 348.36, 'close': 348.915, 'volume': 967921, 'datetime': 1793286000000}, {'open': 348.915, 'high': 349.55, 'low': 348.66, 'close': 349.26, 'volume': 940557, 'datetime': 1793287800000}, {'open': 349.26, 'high': 349.61, 'low': 348.93, 'close': 349.4651, 'volume': 868825, 'datetime': 1793289600000}, {'open': 349.465, 'high': 350.13, 'low': 349.07, 'close': 349.7701, 'volume': 1211362, 'datetime': 1793291400000}, {'open': 349.77, 'high': 349.99, 'low': 349.61, 'close': 349.78, 'volume': 751659, 'datetime': 1793293200000}, {'open': 349.79, 'high': 349.89, 'low': 349.32, 'close': 349.725, 'volume': 843779, 'datetime': 1793295000000}, {'open': 349.725, 'high': 350.15, 'low': 349.7, 'close': 349.87, 'volume': 929559, 'datetime': 1793296800000}, {'open': 349.88, 'high': 350.6, 'low': 349.78, 'close': 350.1, 'volume': 1115288, 'datetime': 1793298600000}, {'open': 350.1, 'high': 350.395, 'low': 350.02, 'close': 350.39, 'volume': 1107616, 'datetime': 1793300400000}, {'open': 350.3831, 'high': 350.44, 'low': 348.27, 'close': 348.94, 'volume': 3715876, 'datetime': 1793302200000}, {'open': 348.95, 'high': 352.6, 'low': 348.73, 'close': 350.46, 'volume': 7396505, 'datetime': 1793304000000}, {'open': 350.4228, 'high': 351.34, 'low': 348.91, 'close': 351.225, 'volume': 138533, 'datetime': 1793305800000}, {'open': 351.225, 'high': 351.25, 'low': 350.32, 'close': 350.75, 'volume': 80354, 'datetime': 1793307600000}, {'open': 350.64, 'high': 350.99, 'low': 350.2799, 'close': 350.9, 'volume': 34387, 'datetime': 1793309400000}, {'open': 350.97, 'high': 351.29, 'low': 350.53, 'close': 350.54, 'volume': 45799, 'datetime': 1793311200000}, {'open': 350.57, 'high': 352.0, 'low': 350.52, 'close': 352.0, 'volume': 44291, 'datetime': 1793313000000}, {'open': 351.7487, 'high': 352.37, 'low': 351.5767, 'close': 352.12, 'volume': 44693, 'datetime': 1793314800000}, {'open': 352.19, 'high': 352.47, 'low': 351.71, 'close': 352.05, 'volume': 34744, 'datetime': 1793316600000}, {'open': 352.21, 'high': 352.93, 'low': 351.6, 'close': 352.22, 'volume': 20562, 'datetime': 1793318400000}, {'open': 352.29, 'high': 352.65, 'low': 351.77, 'close': 351.98, 'volume': 12862, 'datetime': 1793320200000}, {'open': 351.86, 'high': 351.88, 'low': 350.05, 'close': 350.5, 'volume': 27103, 'datetime': 1793322000000}, {'open': 350.51, 'high': 350.87, 'low': 349.91, 'close': 350.14, 'volume': 15086, 'datetime': 1793323800000}, {'open': 350.15, 'high': 350.43, 'low': 349.83, 'close': 350.25, 'volume': 10222, 'datetime': 1793325600000}, {'open': 350.28, 'high': 350.48, 'low': 350.09, 'close': 350.1, 'volume': 8752, 'datetime': 1793327400000}, {'open': 350.14, 'high': 350.28, 'low': 349.71, 'close': 350.14, 'volume': 4682, 'datetime': 1793329200000}, {'open': 350.05, 'high': 350.14, 'low': 349.81, 'close': 349.98, 'volume': 2944, 'datetime': 1793331000000}, {'open': 349.98, 'high': 350.16, 'low': 349.81, 'close': 350.14, 'volume': 1711, 'datetime': 1793332800000}, {'open': 350.06, 'high': 350.2, 'low': 350.0, 'close': 350.15, 'volume': 3504, 'datetime': 1793334600000}, {'open': 350.23, 'high': 350.63, 'low': 350.16, 'close': 350.58, 'volume': 5573, 'datetime': 1793336400000}, {'open': 350.58, 'high': 350.88, 'low': 350.51, 'close': 350.65, 'volume': 6692, 'datetime': 1793338200000}, {'open': 350.61, 'high': 350.99, 'low': 350.38, 'close': 350.99, 'volume': 3399, 'datetime': 1793340000000}, {'open': 350.97, 'high': 351.0, 'low': 350.51, 'close': 350.85, 'volume': 3563, 'datetime': 1793341800000}, {'open': 350.78, 'high': 350.89, 'low': 350.5, 'close': 350.78, 'volume': 3107, 'datetime': 1793343600000}, {'open': 350.78, 'high': 351.67, 'low': 350.69, 'close': 351.56, 'volume': 8826, 'datetime': 1793345400000}, {'open': 350.76, 'high': 351.45, 'low': 349.0, 'close': 349.47, 'volume': 52570, 'datetime': 1793347200000}, {'open': 349.6, 'high': 350.2, 'low': 349.25, 'close': 349.981, 'volume': 40010, 'datetime': 1793349000000}, {'open': 349.9, 'high': 350.1928, 'low': 346.47, 'close': 346.74, 'volume': 87951, 'datetime': 1793350800000}, {'open': 346.74, 'high': 347.19, 'low': 344.03, 'close': 345.14, 'volume': 210028, 'datetime': 1793352600000}, {'open': 345.14, 'high': 345.35, 'low': 344.7349, 'close': 344.92, 'volume': 57664, 'datetime': 1793354400000}, {'open': 345.0, 'high': 345.59, 'low': 344.95, 'close': 345.31, 'volume': 53256, 'datetime': 1793356200000}, {'open': 345.32, 'high': 345.95, 'low': 342.89, 'close': 344.3704, 'volume': 298944, 'datetime': 1793358000000}, {'open': 344.37, 'high': 348.038, 'low': 341.63, 'close': 342.4647, 'volume': 283869, 'datetime': 1793359800000}, {'open': 342.3, 'high': 344.4, 'low': 341.34, 'close': 344.17, 'volume': 296138, 'datetime': 1793361600000}, {'open': 344.27, 'high': 345.85, 'low': 344.0, 'close': 345.28, 'volume': 171516, 'datetime': 1793363400000}, {'open': 345.35, 'high': 346.87, 'low': 344.26, 'close': 346.77, 'volume': 169058, 'datetime': 1793365200000}, {'open': 346.63, 'high': 348.7696, 'low': 344.13, 'close': 345.33, 'volume': 5113553, 'datetime': 1793367000000}, {'open': 345.29, 'high': 346.48, 'low': 344.89, 'close': 346.33, 'volume': 2275171, 'datetime': 1793368800000}, {'open': 346.3, 'high': 349.19, 'low': 346.19, 'close': 348.48, 'volume': 2761972, 'datetime': 1793370600000}, {'open': 348.495, 'high': 348.7, 'low': 347.41, 'close': 347.69, 'volume': 1550784, 'datetime': 1793372400000}, {'open': 347.69, 'high': 347.88, 'low': 346.73, 'close': 346.925, 'volume': 1754864, 'datetime': 1793374200000}, {'open': 346.94, 'high': 347.72, 'low': 345.6711, 'close': 347.5, 'volume': 2113429, 'datetime': 1793376000000}, {'open': 347.495, 'high': 347.97, 'low': 346.83, 'close': 346.955, 'volume': 1799163, 'datetime': 1793377800000}, {'open': 346.98, 'high': 347.2199, 'low': 346.245, 'close': 346.55, 'volume': 1936724, 'datetime': 1793379600000}, {'open': 346.56, 'high': 346.6899, 'low': 344.31, 'close': 344.585, 'volume': 2134894, 'datetime': 1793381400000}, {'open': 344.59, 'high': 344.705, 'low': 334.35, 'close': 343.1342, 'volume': 3043503, 'datetime': 1793383200000}, {'open': 343.14, 'high': 343.84, 'low': 342.35, 'close': 343.275, 'volume': 2003560, 'datetime': 1793385000000}, {'open': 343.29, 'high': 343.86, 'low': 342.61, 'close': 343.52, 'volume': 2030657, 'datetime': 1793386800000}, {'open': 343.52, 'high': 346.0, 'low': 343.14, 'close': 344.8, 'volume': 5102233, 'datetime': 1793388600000}, {'open': 344.8, 'high': 345.1, 'low': 344.17, 'close': 344.55, 'volume': 12987000, 'datetime': 1793390400000}, {'open': 344.5694, 'high': 344.93, 'low': 344.55, 'close': 344.7026, 'volume': 39936, 'datetime': 1793392200000}, {'open': 344.8, 'high': 344.97, 'low': 344.6, 'close': 344.8, 'volume': 17370, 'datetime': 1793394000000}, {'open': 344.8972, 'high': 344.95, 'low': 344.55, 'close': 344.7304, 'volume': 52839, 'datetime': 1793395800000}, {'open': 344.74, 'high': 345.07, 'low': 344.7356, 'close': 344.98, 'volume': 16622, 'datetime': 1793397600000}, {'open': 345.0, 'high': 345.0, 'low': 344.76, 'close': 344.7775, 'volume': 11780, 'datetime': 1793399400000}, {'open': 344.9121, 'high': 345.0, 'low': 344.7601, 'close': 344.93, 'volume': 3644, 'datetime': 1793401200000}, {'open': 344.925, 'high': 345.18, 'low': 344.8, 'close': 345.1, 'volume': 10699, 'datetime': 1793403000000}]}



EMPTY_PAYLOAD: dict = {'candles': [], 'symbol': 'ZZZZ', 'empty': True}


INTRADAY_REGULAR_PAYLOAD: dict = MINUTE_30M_PAYLOAD
