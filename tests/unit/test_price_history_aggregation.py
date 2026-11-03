"""RED-phase aggregation and weekly-label tests for ``get_price_history``
(T014 + T015, US2).

TDD red-phase: ``schwab_mcp.price_history`` exposes the skeleton only, so
every test here fails until the minimal implementations land.

T014 pins ``aggregate_hourly`` (data-model.md "Hourly (1h)", D2/D6):
regular-session filtering BEFORE bucketing unless ``extended_hours=True``
(clarification Q1, research D2); clock-hour buckets in the exchange
timezone whose ``t`` is the bucket END (``fx.hour_bucket_end``);
``o`` = first, ``h`` = max, ``l`` = min, ``c`` = last, ``v`` = sum;
single-candle session-edge buckets emitted; the trailing partial bucket
emitted with its partial data and marked ``in_progress: true`` against the
frozen ``fetch_time`` (D6: bucket period end > fetch_time).

T015 pins ``normalize_weekly_labels`` and the end-to-end weekly path
(FR-019, research D7): every weekly ``t`` equals the closing session's
timestamp (``fx.iso_week_close_session``, clarification Q5).  The D7
branch follows ``fx.WEEKLY_STAMP_CONVENTION`` (UNVERIFIED contingency):
``"week_close"`` stamps are a pass-through, ``"week_open"`` stamps are
relabelled forward — expectations derive from the constant and the
fixture helper so the assertions stay valid when the constant is flipped
after a live capture.  Relabeling is idempotent.

All convention-dependent expectations come from the fixture helpers
(``fx.hour_bucket_end``, ``fx.in_regular_session``,
``fx.iso_week_close_session``, ``fx.weekly_period_end``) — no clock times
or time offsets are hard-coded.  Provider candles are curated here with a
one-line adapter; the production mapping lives in ``schwab_mcp.price_history``.
"""

from __future__ import annotations

import copy

import pytest

from tests.unit.fixtures import price_history_payloads as fx
from tests.unit.helpers import FakePriceHistoryClient


# =============================================================================
# Local helpers (curated-candle adapter and expectation derivation)
# =============================================================================


def _curate(payload: dict) -> list[dict]:
    """Provider candle -> curated candle (keys ``t/o/h/l/c/v``) — one-line
    adapter only; the production mapping is what these tests drive."""
    return [
        {
            "t": c["datetime"],
            "o": c["open"],
            "h": c["high"],
            "l": c["low"],
            "c": c["close"],
            "v": c["volume"],
        }
        for c in payload["candles"]
    ]


def _after_last_bucket(candles: list[dict]) -> int:
    """Frozen fetch time at the end of the last hour bucket — every bucket
    is complete (D6: no ``in_progress`` candle)."""
    return fx.hour_bucket_end(max(c["t"] for c in candles))


def _expected_hourly(
    candles: list[dict],
    *,
    extended_hours: bool = False,
    fetch_time: int,
    convention: str = fx.STAMPING_CONVENTION,
) -> list[dict]:
    """Expected hourly candles per data-model D2/D6 (fixture helpers only).

    Regular-session filtering before bucketing unless *extended_hours*;
    grouping by ``fx.hour_bucket_end`` (clock-hour floor rule); first /
    max / min / last / sum aggregation; ``in_progress`` iff the bucket end
    is still ahead of *fetch_time* (D6).
    """
    kept = [
        c
        for c in candles
        if extended_hours or fx.in_regular_session(c["t"], convention)
    ]
    buckets: dict[int, list[dict]] = {}
    for candle in kept:
        buckets.setdefault(fx.hour_bucket_end(candle["t"]), []).append(candle)
    expected: list[dict] = []
    for end in sorted(buckets):
        members = buckets[end]
        expected.append(
            {
                "t": end,
                "o": members[0]["o"],
                "h": max(m["h"] for m in members),
                "l": min(m["l"] for m in members),
                "c": members[-1]["c"],
                "v": sum(m["v"] for m in members),
                "in_progress": end > fetch_time,
            }
        )
    return expected


# =============================================================================
# T014 — hourly aggregation (data-model D2, in_progress D6)
# =============================================================================


class TestAggregateHourly:
    """``aggregate_hourly``: curated 30-minute candles -> hourly candles."""

    def test_regular_session_candles_pair_into_clock_hour_buckets(self) -> None:
        """One output candle per clock-hour bucket (D2 rules 2–4), exact
        first/max/min/last/sum values and bucket-end labels."""
        candles = _curate(fx.MINUTE_30M_PAYLOAD)
        fetch_time = _after_last_bucket(candles)

        from schwab_mcp.price_history import aggregate_hourly

        result = aggregate_hourly(candles, fetch_time=fetch_time)

        assert result == _expected_hourly(candles, fetch_time=fetch_time)
        assert len(result) < len(candles)
        assert [c["t"] for c in result] == sorted(
            {fx.hour_bucket_end(c["t"]) for c in candles}
        )

    def test_hourly_t_is_the_hour_bucket_end(self) -> None:
        """End-labeling (D2 rule 4): ``t`` is the bucket end — after every
        member stamp, and equal to ``fx.hour_bucket_end`` of each member."""
        candles = _curate(fx.MINUTE_30M_PAYLOAD)
        fetch_time = _after_last_bucket(candles)

        from schwab_mcp.price_history import aggregate_hourly

        result = aggregate_hourly(candles, fetch_time=fetch_time)

        assert [c["t"] for c in result] == sorted(
            {fx.hour_bucket_end(c["t"]) for c in candles}
        )
        for out in result:
            members = [
                c for c in candles if fx.hour_bucket_end(c["t"]) == out["t"]
            ]
            assert out["t"] == fx.hour_bucket_end(members[0]["t"])
            assert out["t"] > members[-1]["t"]

    def test_regular_session_filtering_happens_before_bucketing(self) -> None:
        """Clarification Q1 / D2 rule 2: without ``extended_hours`` the
        regular session is selected via ``fx.in_regular_session`` BEFORE
        bucketing — the extended payload yields exactly the regular
        fixture's bucket structure."""
        extended = _curate(fx.INTRADAY_EXTENDED_PAYLOAD)
        regular = _curate(fx.MINUTE_30M_PAYLOAD)
        fetch_time = _after_last_bucket(regular)

        from schwab_mcp.price_history import aggregate_hourly

        result = aggregate_hourly(
            extended, extended_hours=False, fetch_time=fetch_time
        )

        # Session membership comes from the fixture helper, never clock times.
        kept = [c for c in extended if fx.in_regular_session(c["t"])]
        assert [c["t"] for c in kept] == [c["t"] for c in regular]
        assert result == _expected_hourly(
            extended, extended_hours=False, fetch_time=fetch_time
        )
        assert [c["t"] for c in result] == [
            c["t"] for c in aggregate_hourly(regular, fetch_time=fetch_time)
        ]

    def test_extended_hours_aggregates_pre_and_post_market_too(self) -> None:
        """``extended_hours=True`` skips the session filter (D2 rule 2), so
        pre/post-market candles land in their own clock-hour buckets."""
        extended = _curate(fx.INTRADAY_EXTENDED_PAYLOAD)
        fetch_time = _after_last_bucket(extended)

        from schwab_mcp.price_history import aggregate_hourly

        result = aggregate_hourly(
            extended, extended_hours=True, fetch_time=fetch_time
        )

        assert result == _expected_hourly(
            extended, extended_hours=True, fetch_time=fetch_time
        )
        assert {c["t"] for c in result} == {
            fx.hour_bucket_end(c["t"]) for c in extended
        }
        regular_only = aggregate_hourly(
            extended, extended_hours=False, fetch_time=fetch_time
        )
        assert len(result) > len(regular_only)

    def test_session_edge_bucket_with_single_candle_is_emitted(self) -> None:
        """The bucket holding only the session's first or last 30-minute
        candle (09:30 open or last regular candle, per the stamping
        convention) is emitted with that single candle's values."""
        candles = _curate(fx.MINUTE_30M_PAYLOAD)
        fetch_time = _after_last_bucket(candles)

        from schwab_mcp.price_history import aggregate_hourly

        result = aggregate_hourly(candles, fetch_time=fetch_time)

        buckets: dict[int, list[dict]] = {}
        for candle in candles:
            buckets.setdefault(fx.hour_bucket_end(candle["t"]), []).append(
                candle
            )
        singles = {
            end: members[0]
            for end, members in buckets.items()
            if len(members) == 1
        }
        assert singles  # the fixture has one session-edge bucket per session
        by_t = {c["t"]: c for c in result}
        for end, member in singles.items():
            assert by_t[end] == {
                "t": end,
                "o": member["o"],
                "h": member["h"],
                "l": member["l"],
                "c": member["c"],
                "v": member["v"],
                "in_progress": False,
            }

    def test_trailing_partial_bucket_emitted_marked_in_progress(self) -> None:
        """D6: a trailing bucket not yet a full hour at *fetch_time* is
        still emitted with its partial data and marked ``in_progress:
        true``; every earlier bucket is ``false``."""
        # Drop the newest 30-minute candle: the trailing hour is incomplete.
        candles = _curate(fx.MINUTE_30M_PAYLOAD)[:-1]
        fetch_time = candles[-1]["t"]

        from schwab_mcp.price_history import aggregate_hourly

        result = aggregate_hourly(candles, fetch_time=fetch_time)

        assert result == _expected_hourly(candles, fetch_time=fetch_time)
        assert result[-1]["t"] == fx.hour_bucket_end(candles[-1]["t"])
        assert result[-1]["in_progress"] is True
        assert [c["in_progress"] for c in result[:-1]] == [False] * (
            len(result) - 1
        )

    def test_no_in_progress_when_fetch_time_reaches_last_bucket_end(self) -> None:
        """D6: once the last bucket's period end has passed *fetch_time*,
        every candle is ``in_progress: false`` (at most one may be true)."""
        candles = _curate(fx.MINUTE_30M_PAYLOAD)
        fetch_time = _after_last_bucket(candles)

        from schwab_mcp.price_history import aggregate_hourly

        result = aggregate_hourly(candles, fetch_time=fetch_time)

        assert result == _expected_hourly(candles, fetch_time=fetch_time)
        assert [c["in_progress"] for c in result] == [False] * len(result)

    @pytest.mark.parametrize("convention", fx.STAMPING_CONVENTIONS)
    def test_aggregation_holds_for_both_stamping_conventions(
        self, convention: str
    ) -> None:
        """D8 contingency: the D2/D6 rules hold under either stamping
        convention, whichever the live capture later pins.

        GREEN reconciliation: session membership of the two boundary
        stamps (09:30 / 16:00 ET) is genuinely ambiguous without knowing
        the convention, so ``aggregate_hourly`` takes it as an explicit
        ``convention`` parameter (documented in the module) rather than
        guessing.  The test passes it through so both branches stay
        exercised.
        """
        candles = _curate(fx.build_30m_payload(convention=convention))
        fetch_time = _after_last_bucket(candles)

        from schwab_mcp.price_history import aggregate_hourly

        result = aggregate_hourly(
            candles, fetch_time=fetch_time, convention=convention
        )

        assert result == _expected_hourly(
            candles, fetch_time=fetch_time, convention=convention
        )


# =============================================================================
# T015 — weekly labels (FR-019, research D7) — pure function
# =============================================================================


@pytest.mark.parametrize("convention", fx.WEEKLY_STAMP_CONVENTIONS)
class TestNormalizeWeeklyLabels:
    """``normalize_weekly_labels``: every ``t`` is the closing session's
    timestamp (FR-019); the pass-through/relabel branch derives from the
    stamping convention under test."""

    def test_labels_are_the_closing_session_timestamps(
        self, convention: str
    ) -> None:
        candles = _curate(fx.build_weekly_payload(stamp_convention=convention))

        from schwab_mcp.price_history import normalize_weekly_labels

        result = normalize_weekly_labels(candles)

        assert len(result) == len(candles)
        for out, src in zip(result, candles):
            assert out["t"] == fx.iso_week_close_session(src["t"])

    def test_branch_follows_the_stamping_convention(
        self, convention: str
    ) -> None:
        """``"week_close"`` stamps already are the closing session -> the
        normalization is a pass-through (output ``t`` == input ``t``);
        ``"week_open"`` stamps are relabelled forward to the ISO week's
        closing session (output ``t`` != input ``t``)."""
        candles = _curate(fx.build_weekly_payload(stamp_convention=convention))

        from schwab_mcp.price_history import normalize_weekly_labels

        result = normalize_weekly_labels(candles)

        for out, src in zip(result, candles):
            if convention == "week_close":
                assert out["t"] == src["t"]
            else:
                assert out["t"] == fx.iso_week_close_session(src["t"])
                assert out["t"] != src["t"]

    def test_relabeling_is_idempotent(self, convention: str) -> None:
        """Normalizing already-normalized candles changes nothing."""
        candles = _curate(fx.build_weekly_payload(stamp_convention=convention))

        from schwab_mcp.price_history import normalize_weekly_labels

        once = normalize_weekly_labels(candles)

        assert normalize_weekly_labels(once) == once

    def test_values_and_order_are_preserved(self, convention: str) -> None:
        candles = _curate(fx.build_weekly_payload(stamp_convention=convention))

        from schwab_mcp.price_history import normalize_weekly_labels

        result = normalize_weekly_labels(candles)

        for out, src in zip(result, candles):
            for key in ("o", "h", "l", "c", "v"):
                assert out[key] == src[key]
        assert [c["t"] for c in result] == sorted(c["t"] for c in result)


# =============================================================================
# T015 — weekly labels end to end (get_price_history, FR-019)
# =============================================================================


class TestWeeklyEndToEnd:
    """The ``frequency="weekly"`` path labels every candle with the closing
    session's timestamp, derived from ``fx.WEEKLY_STAMP_CONVENTION`` so the
    assertions stay valid when the constant is flipped after a live
    capture."""

    def _weekly_result(self):
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(
            payload=copy.deepcopy(fx.WEEKLY_PAYLOAD)
        )
        fetch_time = fx.weekly_period_end(
            fx.WEEKLY_PAYLOAD["candles"][-1]["datetime"]
        )
        result = get_price_history(
            client,
            fx.WEEKLY_PAYLOAD["symbol"],
            frequency="weekly",
            period="1y",
            fetch_time=fetch_time,
        )
        assert result["outcome"] == "ok", result
        return result

    def test_every_t_is_the_closing_session_timestamp(self) -> None:
        result = self._weekly_result()
        source = _curate(fx.WEEKLY_PAYLOAD)

        assert result["candle_count"] == len(source)
        candles = result["candles"]
        assert len(candles) == len(source)
        for out, src in zip(candles, source):
            assert out["t"] == fx.iso_week_close_session(src["t"])
            if fx.WEEKLY_STAMP_CONVENTION == "week_close":
                assert out["t"] == src["t"]
            else:
                assert out["t"] != src["t"]
        assert [c["t"] for c in candles] == sorted(c["t"] for c in candles)

    def test_source_values_pass_through(self) -> None:
        result = self._weekly_result()
        source = _curate(fx.WEEKLY_PAYLOAD)

        for out, src in zip(result["candles"], source):
            for key in ("o", "h", "l", "c", "v"):
                assert out[key] == src[key]