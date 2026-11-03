"""RED-phase in-progress derivation tests for ``get_price_history`` (T006 + T016).

TDD red-phase: ``schwab_mcp.price_history`` exposes the skeleton only
(``NotImplementedError``), so every test here fails until the minimal
implementation lands.

Pins the D6 rule of
``specs/011-price-history-ohlcv/data-model.md``: a candle is
``in_progress: true`` iff its period end exceeds the injected
``fetch_time`` (epoch ms, frozen in tests), and at most one candle per
response carries the marker (FR-017).  Period ends are derived
**exclusively through the fixture helpers** (``fx.daily_period_end`` /
``fx.minute_period_end``) so these tests stay valid when the D8
stamping-convention constant is flipped: the daily cases are
parameterized over ``fx.STAMPING_CONVENTIONS`` and build payloads with
the matching builder convention.  No period offset and no session time
is hard-coded anywhere (research D8 — never assume a convention).

T006 (US1): the daily forming-candle rule, the strict ``>`` boundary at
the period end, the fully closed session with no marker at all, and
earlier candles always closed while the trailing session forms.

T016 (US2, unit level): the same rule for native 30-minute candles and
for the trailing post-market candle served under ``extended_hours=true``
(extended payload) — the D6 rule is frequency- and session-agnostic.
"""

from __future__ import annotations

import pytest

from tests.unit.fixtures import price_history_payloads as fx
from tests.unit.helpers import FakePriceHistoryClient


def _curated_candles(
    client: FakePriceHistoryClient,
    *,
    symbol: str,
    frequency: str,
    period: str,
    fetch_time: int,
    extended_hours: bool = False,
) -> list[dict]:
    """Invoke ``get_price_history`` and return the ok envelope's candles."""
    from schwab_mcp.price_history import get_price_history

    result = get_price_history(
        client,
        symbol,
        frequency=frequency,
        period=period,
        extended_hours=extended_hours,
        fetch_time=fetch_time,
    )
    assert result["outcome"] == "ok", result
    return result["candles"]


def _daily_period_ends(stamps: list[int], convention: str) -> list[int]:
    """Period end of every daily fixture stamp via the helper (D6/D8)."""
    return [fx.daily_period_end(s, convention=convention) for s in stamps]


# =============================================================================
# T006 (US1) — daily candles: the D6 in-progress rule
# =============================================================================


class TestDailyInProgress:
    """Last daily candle is ``in_progress`` iff its period end > fetch_time.

    Expectations derive from the builder's stamps through
    ``fx.daily_period_end`` — valid under both D8 conventions.
    """

    @pytest.mark.parametrize("convention", fx.STAMPING_CONVENTIONS)
    def test_last_candle_in_progress_iff_period_end_exceeds_fetch_time(
        self, convention
    ) -> None:
        payload = fx.build_daily_payload(convention=convention)
        stamps = [c["datetime"] for c in payload["candles"]]
        last_end = _daily_period_ends(stamps, convention)[-1]

        # Probes around the trailing period end: strictly inside, at the
        # boundary, and after (a 1 ms boundary probe is convention-free).
        probes = [
            (last_end - fx.MS_PER_MINUTE, True, "inside the trailing session"),
            (last_end - 1, True, "one ms before the period end"),
            (last_end, False, "exactly at the period end"),
            (last_end + 1, False, "one ms after the period end"),
            (last_end + fx.MS_PER_HOUR, False, "after the session closes"),
        ]
        for fetch_time, expected, why in probes:
            client = FakePriceHistoryClient(payload=payload)
            candles = _curated_candles(
                client,
                symbol=fx.SYMBOL,
                frequency="daily",
                period="1m",
                fetch_time=fetch_time,
            )
            assert len(candles) == len(stamps), "one candle per delivered session"
            assert candles[-1]["in_progress"] is expected, (
                f"fetch_time {why}: period end {last_end} vs fetch_time {fetch_time}"
            )
            # The normative D6 statement against the curated candle itself.
            assert candles[-1]["in_progress"] is (
                fx.daily_period_end(candles[-1]["t"], convention=convention)
                > fetch_time
            )

    @pytest.mark.parametrize("convention", fx.STAMPING_CONVENTIONS)
    def test_earlier_candles_closed_while_trailing_session_forms(
        self, convention
    ) -> None:
        payload = fx.build_daily_payload(convention=convention)
        stamps = [c["datetime"] for c in payload["candles"]]
        last_end = _daily_period_ends(stamps, convention)[-1]
        fetch_time = last_end - fx.MS_PER_MINUTE  # inside the trailing session

        client = FakePriceHistoryClient(payload=payload)
        candles = _curated_candles(
            client,
            symbol=fx.SYMBOL,
            frequency="daily",
            period="1m",
            fetch_time=fetch_time,
        )

        assert candles[-1]["in_progress"] is True
        assert all(c["in_progress"] is False for c in candles[:-1]), (
            "earlier candles are never in progress"
        )
        assert sum(1 for c in candles if c["in_progress"]) == 1

    @pytest.mark.parametrize("convention", fx.STAMPING_CONVENTIONS)
    def test_at_most_one_candle_in_progress_per_response(self, convention) -> None:
        """FR-017: the marker never appears on more than one candle."""
        payload = fx.build_daily_payload(convention=convention)
        stamps = [c["datetime"] for c in payload["candles"]]
        last_end = _daily_period_ends(stamps, convention)[-1]

        for fetch_time in (
            last_end - fx.MS_PER_MINUTE,
            last_end,
            last_end + fx.MS_PER_MINUTE,
            last_end + fx.MS_PER_HOUR,
        ):
            client = FakePriceHistoryClient(payload=payload)
            candles = _curated_candles(
                client,
                symbol=fx.SYMBOL,
                frequency="daily",
                period="1m",
                fetch_time=fetch_time,
            )
            assert sum(1 for c in candles if c["in_progress"]) <= 1

    def test_fully_closed_session_marks_every_candle_closed(self) -> None:
        """Quickstart S4: after the session closes, no candle is in progress.

        Uses the default-convention fixture constant (fx.DAILY_PAYLOAD)
        with expectations through ``fx.daily_period_end`` and the default
        convention constant (fx.STAMPING_CONVENTION).
        """
        payload = fx.DAILY_PAYLOAD
        stamps = [c["datetime"] for c in payload["candles"]]
        last_end = _daily_period_ends(stamps, fx.STAMPING_CONVENTION)[-1]
        fetch_time = last_end + fx.MS_PER_HOUR  # fetch strictly after the close

        client = FakePriceHistoryClient(payload=payload)
        candles = _curated_candles(
            client,
            symbol=fx.SYMBOL,
            frequency="daily",
            period="1m",
            fetch_time=fetch_time,
        )

        assert candles, "the fixture delivers a full window"
        assert all(c["in_progress"] is False for c in candles)
        assert sum(1 for c in candles if c["in_progress"]) == 0


# =============================================================================
# T016 (US2) — intraday candles and the extended-hours interplay
# =============================================================================


class TestIntradayInProgress:
    """The D6 rule for native 30-minute candles: ``fx.minute_period_end``.

    Period ends derive from the curated ``t`` through the fixture helper
    (stamp + frequency span); fetch_time probes sit inside and after the
    trailing candle's helper-derived period.
    """

    def test_30m_trailing_candle_in_progress_while_period_forms(self) -> None:
        payload = fx.MINUTE_30M_PAYLOAD
        last_stamp = payload["candles"][-1]["datetime"]
        period_end = fx.minute_period_end(last_stamp, 30)
        fetch_time = period_end - fx.MS_PER_MINUTE  # inside the trailing period

        client = FakePriceHistoryClient(payload=payload)
        candles = _curated_candles(
            client,
            symbol=payload["symbol"],
            frequency="30m",
            period="5d",
            fetch_time=fetch_time,
        )

        assert len(candles) == len(payload["candles"]), (
            "one candle per delivered 30-minute period"
        )
        last = candles[-1]
        assert last["in_progress"] is (
            fx.minute_period_end(last["t"], 30) > fetch_time
        )
        assert last["in_progress"] is True
        assert all(c["in_progress"] is False for c in candles[:-1])
        assert sum(1 for c in candles if c["in_progress"]) == 1

    def test_30m_trailing_candle_closed_after_period_ends(self) -> None:
        payload = fx.MINUTE_30M_PAYLOAD
        last_stamp = payload["candles"][-1]["datetime"]
        period_end = fx.minute_period_end(last_stamp, 30)
        fetch_time = period_end + fx.MS_PER_MINUTE  # after the trailing period

        client = FakePriceHistoryClient(payload=payload)
        candles = _curated_candles(
            client,
            symbol=payload["symbol"],
            frequency="30m",
            period="5d",
            fetch_time=fetch_time,
        )

        assert candles[-1]["in_progress"] is (
            fx.minute_period_end(candles[-1]["t"], 30) > fetch_time
        )
        assert all(c["in_progress"] is False for c in candles)
        assert sum(1 for c in candles if c["in_progress"]) == 0

    def test_extended_hours_post_market_candle_follows_d6_rule(self) -> None:
        """Under ``extended_hours=true`` the trailing post-market candle of
        the extended payload follows the same D6 rule (research D4)."""
        payload = fx.INTRADAY_EXTENDED_PAYLOAD
        last_stamp = payload["candles"][-1]["datetime"]
        assert fx.in_regular_session(last_stamp) is False, (
            "the trailing fixture candle is a post-market candle"
        )
        period_end = fx.minute_period_end(last_stamp, 30)

        probes = [
            (period_end - fx.MS_PER_MINUTE, True, "inside the post-market period"),
            (period_end + fx.MS_PER_MINUTE, False, "after the post-market period"),
        ]
        for fetch_time, expected, why in probes:
            client = FakePriceHistoryClient(payload=payload)
            candles = _curated_candles(
                client,
                symbol=payload["symbol"],
                frequency="30m",
                period="5d",
                extended_hours=True,
                fetch_time=fetch_time,
            )
            assert len(candles) == len(payload["candles"]), (
                "extended-hours candles are not filtered out of the response"
            )
            last = candles[-1]
            assert last["in_progress"] is expected, f"fetch_time {why}"
            assert last["in_progress"] is (
                fx.minute_period_end(last["t"], 30) > fetch_time
            )
            assert all(c["in_progress"] is False for c in candles[:-1])
            assert sum(1 for c in candles if c["in_progress"]) <= 1