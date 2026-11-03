"""End-to-end integration tests for ``get_price_history`` with a provider double.

TDD red-phase for the tasks' RED groups: T008 (US1 default-window flows),
T016 (US2 extended hours, integration portion), T017 (US2 selection),
T023 (US3 extended mode).  The suite runs WITHOUT network and WITHOUT a
token: a :class:`FakePriceHistoryClient` (tests.unit.helpers) records every
upcall and answers with the payloads of
``tests/unit/fixtures/price_history_payloads.py`` wrapped in real
``requests.Response`` objects.

Covers
------
- S1: default daily window ``ok`` envelope end to end (quickstart S1) with
  curated ``candles``, ``candle_count``, ``window``, and the effective
  selection echo
- exactly ONE ``price_history()`` provider call per invocation (research D1)
- empty candle list -> ``history_unavailable`` / ``source_returned_no_candles``
  with NO ``candles`` array (FR-008, quickstart S5)
- provider 5xx/408/429 -> retryable ``provider_unreachable``; 401/403 ->
  ``reauth_needed`` (shared taxonomy via ``provider.response_json``, mirror
  of tests/integration/test_quotes.py)
- US2: ``extended_hours`` wired to ``needExtendedHoursData`` on the recorded
  call (research D4); the Phase 1 extended-hours pair (regular vs extended
  intraday payloads, quickstart S3)
- US2: preset-table provider-parameter mapping for every frequency/preset
  (``1h`` fetches 30-minute candles, research D2/D3), one call per
  invocation, effective ``frequency``/``period`` echo, and the 260-candle
  ceiling by construction at every preset's worst case (SC-003)
- US3: ``extended=true`` -> curated ``candles`` + raw ``provider`` channel
  equal to the fixture payload (SC-006); for ``1h`` the raw channel carries
  the underlying 30-minute payload (research D2); extended-mode errors keep
  the structured envelope with no partial data
"""

from __future__ import annotations

from datetime import datetime

import pytest

from tests.unit.fixtures import price_history_payloads as fx
from tests.unit.helpers import FakePriceHistoryClient

# =============================================================================
# Synthetic worst-case payload builders (deterministic, no clock reads)
# =============================================================================

_STEP_MINUTES = {"5m": 5, "15m": 15, "30m": 30}


def _synthetic_minute_payload(count: int, step_minutes: int) -> dict:
    """Provider payload of *count* minute candles, ``step_minutes`` apart.

    Deterministic synthetic candles (worst-case size tests): the stamps are
    plain arithmetic, so the requests run with ``extended_hours=True`` and no
    regular-session filtering can ever drop a candle.
    """
    base = int(datetime(2026, 10, 5, 4, 0, tzinfo=fx.ET).timestamp() * 1000)
    candles = []
    for i in range(count):
        price = 100.0 + 0.01 * i
        candles.append(
            {
                "open": price,
                "high": price + 0.5,
                "low": price - 0.5,
                "close": price + 0.25,
                "volume": 10_000 + i,
                "datetime": base + i * step_minutes * fx.MS_PER_MINUTE,
            }
        )
    return {"candles": candles, "symbol": fx.SYMBOL, "empty": False}


def _synthetic_hourly_fetch_payload(hour_buckets: int) -> dict:
    """Provider 30-minute payload aggregating to *hour_buckets* clock hours.

    Every clock-hour bucket holds exactly two candles (``hh:00``/``hh:30``
    stamps), so the D2 two-candle-per-hour aggregation of *hour_buckets*
    buckets fetches ``2 * hour_buckets`` raw candles.  Stamps are plain
    arithmetic and the requests run with ``extended_hours=True`` (no
    regular-session filtering can drop a candle).
    """
    base = int(datetime(2026, 10, 5, 4, 0, tzinfo=fx.ET).timestamp() * 1000)
    candles = []
    for bucket in range(hour_buckets):
        for minutes in (0, 30):
            price = 200.0 + 0.01 * bucket
            candles.append(
                {
                    "open": price,
                    "high": price + 0.5,
                    "low": price - 0.5,
                    "close": price + 0.25,
                    "volume": 5_000 + bucket,
                    "datetime": base
                    + (bucket * 60 + minutes) * fx.MS_PER_MINUTE,
                }
            )
    return {"candles": candles, "symbol": fx.SYMBOL, "empty": False}


def _closed_fetch_time(payload: dict) -> int:
    """Frozen ``fetch_time`` after the payload's last daily period end (D6)."""
    last_stamp = payload["candles"][-1]["datetime"]
    return fx.daily_period_end(last_stamp) + 1


# =============================================================================
# S1 — default daily window, one symbol (quickstart S1, T008)
# =============================================================================


class TestDefaultWindowOk:
    """``{"symbol": "SPY"}`` (defaults ``daily``/``1m``) -> the complete
    ``ok`` envelope in one invocation."""

    def test_ok_envelope_end_to_end(self) -> None:
        from schwab_mcp.price_history import get_price_history

        payload = fx.DAILY_PAYLOAD
        client = FakePriceHistoryClient(payload=payload)
        result = get_price_history(
            client,
            fx.SYMBOL,
            fetch_time=_closed_fetch_time(payload),
        )

        assert result["outcome"] == "ok"
        assert result["detail"] == "price_history_retrieved"
        assert result["symbol"] == fx.SYMBOL
        assert result["frequency"] == "daily"
        assert result["period"] == "1m"
        assert result["extended_hours"] is False
        assert result["extended"] is False
        assert result["candle_count"] == len(payload["candles"])
        assert result["candle_count"] == len(result["candles"])

        stamps = [candle["t"] for candle in result["candles"]]
        assert stamps == sorted(stamps), "candles are chronological (oldest first)"
        assert result["window"]["first"] == stamps[0]
        assert result["window"]["last"] == stamps[-1]

    def test_candles_are_curated_as_delivered(self) -> None:
        """FR-012: OHLCV values travel as delivered — no rounding, no
        adjustment; ``t`` keeps the provider epoch-ms stamp (T005 mapping)."""
        from schwab_mcp.price_history import get_price_history

        payload = fx.DAILY_PAYLOAD
        client = FakePriceHistoryClient(payload=payload)
        result = get_price_history(
            client,
            fx.SYMBOL,
            fetch_time=_closed_fetch_time(payload),
        )

        for curated, source in zip(
            (result["candles"][0], result["candles"][-1]),
            (payload["candles"][0], payload["candles"][-1]),
        ):
            assert curated["t"] == source["datetime"]
            assert curated["o"] == source["open"]
            assert curated["h"] == source["high"]
            assert curated["l"] == source["low"]
            assert curated["c"] == source["close"]
            assert curated["v"] == source["volume"]

    def test_exactly_one_provider_call_with_default_preset(self) -> None:
        """Research D1: one ``price_history()`` call per invocation, with the
        default preset's provider parameters (``1m`` -> month 1, daily x1)."""
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD)
        get_price_history(
            client, fx.SYMBOL, fetch_time=_closed_fetch_time(fx.DAILY_PAYLOAD)
        )

        assert client.call_count == 1
        assert len(client.price_history_calls) == 1
        call = client.price_history_calls[0]
        assert call["symbol"] == fx.SYMBOL
        assert call["periodType"] == "month"
        assert call["period"] == 1
        assert call["frequencyType"] == "daily"
        assert call["frequency"] == 1

    def test_single_forming_marker_at_most_on_last_candle(self) -> None:
        """FR-017 / quickstart S1: ``in_progress`` is true at most on the
        last candle; every earlier candle is final."""
        from schwab_mcp.price_history import get_price_history

        payload = fx.DAILY_PAYLOAD
        client = FakePriceHistoryClient(payload=payload)
        result = get_price_history(
            client, fx.SYMBOL, fetch_time=_closed_fetch_time(payload)
        )

        candles = result["candles"]
        assert "in_progress" in candles[-1]
        forming = [i for i, c in enumerate(candles) if c.get("in_progress")]
        assert len(forming) <= 1
        assert all(i == len(candles) - 1 for i in forming)


# =============================================================================
# Empty source -> history_unavailable, no partial data (FR-008, quickstart S5)
# =============================================================================


class TestEmptySource:
    """A valid request whose source returns no candles is reported as
    ``history_unavailable`` with NO ``candles`` array (FR-008)."""

    def test_empty_candle_list_is_history_unavailable(self) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.EMPTY_PAYLOAD)
        result = get_price_history(client, fx.NO_HISTORY_SYMBOL)

        assert result["outcome"] == "history_unavailable"
        assert result["detail"] == "source_returned_no_candles"
        assert result["retryable"] is False

    def test_empty_candle_list_returns_no_candles_array(self) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.EMPTY_PAYLOAD)
        result = get_price_history(client, fx.NO_HISTORY_SYMBOL)

        assert "candles" not in result, "no partial data"


# =============================================================================
# Source down -> retryable provider_unreachable (T008, shared taxonomy)
# =============================================================================


class TestSourceDown:
    """5xx/408/429 on the price-history call -> structured retryable
    ``provider_unreachable``, exactly one upstream call, no partial data."""

    @pytest.mark.parametrize(
        "status", [500, 502, 408, 429], ids=["500", "502", "408", "429"]
    )
    def test_transient_status_is_provider_unreachable(self, status) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD, status=status)
        result = get_price_history(client, fx.SYMBOL)

        assert result["outcome"] == "provider_unreachable"
        assert result["retryable"] is True
        assert "candles" not in result
        assert len(client.price_history_calls) == 1

    def test_network_error_is_provider_unreachable(self) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(error=ConnectionError("network down"))
        result = get_price_history(client, fx.SYMBOL)

        assert result["outcome"] == "provider_unreachable"
        assert result["retryable"] is True


# =============================================================================
# 401/403 -> reauth_needed (shared taxonomy via provider.response_json)
# =============================================================================


class TestReauthRequired:
    """Provider 401/403 map through the shared taxonomy to a structured
    ``reauth_needed`` result (user action, not retryable)."""

    @pytest.mark.parametrize("status", [401, 403], ids=["401", "403"])
    def test_reauth_needed_on_auth_failure(self, status) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD, status=status)
        result = get_price_history(client, fx.SYMBOL)

        assert result["outcome"] == "reauth_needed"
        assert result["retryable"] is False
        assert "candles" not in result


# =============================================================================
# T016 (integration) — extended_hours flag wiring (research D4)
# =============================================================================


class TestExtendedHoursFlagWiring:
    """``extended_hours`` travels to the provider as ``needExtendedHoursData``
    on the single ``price_history()`` call (research D1/D4)."""

    def test_extended_hours_true_maps_to_need_extended_hours_data_true(self) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.INTRADAY_EXTENDED_PAYLOAD)
        get_price_history(
            client, "AAPL", "30m", "5d", extended_hours=True
        )

        assert len(client.price_history_calls) == 1
        assert client.price_history_calls[0]["needExtendedHoursData"] is True

    def test_default_extended_hours_is_false_or_absent(self) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.INTRADAY_REGULAR_PAYLOAD)
        get_price_history(client, "AAPL", "30m", "5d")

        assert len(client.price_history_calls) == 1
        assert client.price_history_calls[0]["needExtendedHoursData"] in (
            False,
            None,
        )

    def test_explicit_false_is_false_or_absent(self) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.INTRADAY_REGULAR_PAYLOAD)
        get_price_history(
            client, "AAPL", "30m", "5d", extended_hours=False
        )

        assert len(client.price_history_calls) == 1
        assert client.price_history_calls[0]["needExtendedHoursData"] in (
            False,
            None,
        )


# =============================================================================
# T016 (integration) — extended-hours candle coverage (quickstart S3)
# =============================================================================


class TestExtendedHoursCandleCoverage:
    """The Phase 1 pair (regular vs extended intraday payloads): the
    extended response covers more (or equal) candles than the regular one,
    regular-only responses carry regular-session stamps only, and the
    extended opt-in surfaces pre/post-market stamps (quickstart S3)."""

    def test_extended_response_has_more_or_equal_candles_than_regular(self) -> None:
        from schwab_mcp.price_history import get_price_history

        client_regular = FakePriceHistoryClient(
            payload=fx.INTRADAY_REGULAR_PAYLOAD
        )
        result_regular = get_price_history(
            client_regular, "AAPL", "30m", "5d", extended_hours=False
        )
        client_extended = FakePriceHistoryClient(
            payload=fx.INTRADAY_EXTENDED_PAYLOAD
        )
        result_extended = get_price_history(
            client_extended, "AAPL", "30m", "5d", extended_hours=True
        )

        assert result_regular["outcome"] == "ok"
        assert result_extended["outcome"] == "ok"
        assert (
            result_extended["candle_count"] >= result_regular["candle_count"]
        ), "extended hours cover more (or equal) candles than regular-only"

    def test_regular_only_requests_exclude_pre_post_stamps(self) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.INTRADAY_REGULAR_PAYLOAD)
        result = get_price_history(
            client, "AAPL", "30m", "5d", extended_hours=False
        )

        assert result["outcome"] == "ok"
        assert result["candles"], "regular session delivered candles"
        for candle in result["candles"]:
            assert fx.in_regular_session(
                candle["t"]
            ), f"pre/post stamp outside the regular session: {candle['t']}"

    def test_extended_requests_include_pre_post_stamps(self) -> None:
        from schwab_mcp.price_history import get_price_history

        payload = fx.INTRADAY_EXTENDED_PAYLOAD
        client = FakePriceHistoryClient(payload=payload)
        result = get_price_history(
            client, "AAPL", "30m", "5d", extended_hours=True
        )

        assert result["outcome"] == "ok"
        assert result["candle_count"] == len(payload["candles"])
        assert any(
            not fx.in_regular_session(candle["t"])
            for candle in result["candles"]
        ), "the extended opt-in surfaces pre/post-market stamps"


# =============================================================================
# T017 — selection: preset mapping, one call per invocation, ceiling (S2/S3)
# =============================================================================


class TestSelection:
    """Every declared frequency/preset drives exactly one provider call with
    the matrix parameters (data-model "Period presets × frequency matrix"),
    and the response echoes the effective selection."""

    @pytest.mark.parametrize(
        ("frequency", "period", "period_type", "period_value",
         "frequency_type", "frequency_value"),
        [
            ("5m", "1d", "day", 1, "minute", 5),
            ("5m", "2d", "day", 2, "minute", 5),
            ("5m", "3d", "day", 3, "minute", 5),
            ("15m", "1d", "day", 1, "minute", 15),
            ("15m", "2d", "day", 2, "minute", 15),
            ("15m", "5d", "day", 5, "minute", 15),
            ("15m", "10d", "day", 10, "minute", 15),
            ("30m", "1d", "day", 1, "minute", 30),
            ("30m", "2d", "day", 2, "minute", 30),
            ("30m", "5d", "day", 5, "minute", 30),
            ("30m", "10d", "day", 10, "minute", 30),
            # 1h: 30-minute fetch aggregated 2:1 locally (research D2).
            ("1h", "1d", "day", 1, "minute", 30),
            ("1h", "2d", "day", 2, "minute", 30),
            ("1h", "5d", "day", 5, "minute", 30),
            ("1h", "10d", "day", 10, "minute", 30),
            ("daily", "1m", "month", 1, "daily", 1),
            ("daily", "3m", "month", 3, "daily", 1),
            ("daily", "6m", "month", 6, "daily", 1),
            ("daily", "1y", "year", 1, "daily", 1),
            ("daily", "ytd", "ytd", 1, "daily", 1),
            ("weekly", "1m", "month", 1, "weekly", 1),
            ("weekly", "3m", "month", 3, "weekly", 1),
            ("weekly", "6m", "month", 6, "weekly", 1),
            ("weekly", "1y", "year", 1, "weekly", 1),
            ("weekly", "2y", "year", 2, "weekly", 1),
            ("weekly", "3y", "year", 3, "weekly", 1),
            ("weekly", "5y", "year", 5, "weekly", 1),
            ("weekly", "ytd", "ytd", 1, "weekly", 1),
        ],
    )
    def test_preset_maps_to_provider_parameters_in_one_call(
        self, frequency, period, period_type, period_value,
        frequency_type, frequency_value,
    ) -> None:
        from schwab_mcp.price_history import get_price_history

        if frequency == "weekly":
            payload = fx.WEEKLY_PAYLOAD
        elif frequency == "daily":
            payload = fx.DAILY_PAYLOAD
        else:
            # 5m/15m/30m/1h — for 1h the provider serves 30-minute candles.
            payload = fx.MINUTE_30M_PAYLOAD
        symbol = payload["symbol"]

        client = FakePriceHistoryClient(payload=payload)
        result = get_price_history(client, symbol, frequency, period)

        assert client.call_count == 1
        assert len(client.price_history_calls) == 1
        call = client.price_history_calls[0]
        assert call["symbol"] == symbol
        assert call["periodType"] == period_type
        assert call["period"] == period_value
        assert call["frequencyType"] == frequency_type
        assert call["frequency"] == frequency_value

        assert result["outcome"] == "ok"
        assert result["frequency"] == frequency
        assert result["period"] == period
        assert result["symbol"] == symbol

    def test_1h_requests_30m_and_returns_hourly_candles(self) -> None:
        """Research D2: ``1h`` fetches 30-minute candles and returns hourly
        candles labeled at the hour-bucket end (data-model rule 4)."""
        from schwab_mcp.price_history import get_price_history

        payload = fx.MINUTE_30M_PAYLOAD
        client = FakePriceHistoryClient(payload=payload)
        result = get_price_history(
            client, "AAPL", "1h", "5d", extended_hours=True
        )

        call = client.price_history_calls[0]
        assert call["frequencyType"] == "minute"
        assert call["frequency"] == 30
        assert call["periodType"] == "day"
        assert call["period"] == 5

        assert result["outcome"] == "ok"
        assert result["candle_count"] < len(payload["candles"])
        expected = sorted(
            {fx.hour_bucket_end(c["datetime"]) for c in payload["candles"]}
        )
        assert [c["t"] for c in result["candles"]] == expected

    # Worst case of every ceiling-driving preset (data-model "Max candles"):
    # emitted counts never exceed the row maximum and never exceed 260
    # (SC-003 — ceiling by construction, FR-004).  Intraday synthetic
    # payloads run with extended_hours=True so no session filtering can
    # disturb the worst-case counts.
    @pytest.mark.parametrize(
        ("frequency", "period", "fetched", "expected", "row_max"),
        [
            pytest.param("5m", "1d", 78, 78, 234, id="5m-1d"),
            pytest.param("5m", "2d", 156, 156, 234, id="5m-2d"),
            pytest.param("5m", "3d", 234, 234, 234, id="5m-3d"),
            pytest.param("15m", "10d", 260, 260, 260, id="15m-10d"),
            pytest.param("30m", "10d", 130, 130, 130, id="30m-10d"),
            pytest.param("1h", "10d", 130, 65, 65, id="1h-10d"),
            pytest.param("daily", "1y", 252, 252, 252, id="daily-1y"),
            pytest.param("weekly", "5y", 260, 260, 260, id="weekly-5y"),
        ],
    )
    def test_worst_case_preset_stays_within_the_260_candle_ceiling(
        self, frequency, period, fetched, expected, row_max
    ) -> None:
        from schwab_mcp.price_history import get_price_history

        if frequency in ("5m", "15m", "30m"):
            payload = _synthetic_minute_payload(fetched, _STEP_MINUTES[frequency])
        elif frequency == "1h":
            payload = _synthetic_hourly_fetch_payload(fetched // 2)
        elif frequency == "daily":
            payload = fx.build_daily_payload(sessions=fetched)
        else:
            payload = fx.build_weekly_payload(weeks=fetched)
        assert len(payload["candles"]) == fetched

        client = FakePriceHistoryClient(payload=payload)
        result = get_price_history(
            client,
            payload["symbol"],
            frequency,
            period,
            extended_hours=frequency in ("5m", "15m", "30m", "1h"),
        )

        assert result["outcome"] == "ok"
        assert result["candle_count"] == len(result["candles"])
        assert result["candle_count"] == expected
        assert result["candle_count"] <= row_max
        assert result["candle_count"] <= 260, "SC-003 global candle ceiling"


# =============================================================================
# T023 — extended raw payload channel (quickstart S6, SC-006)
# =============================================================================


class TestExtendedMode:
    """``extended=true`` returns the curated view AND the complete raw
    provider payload (SC-006)."""

    def test_extended_true_carries_curated_and_provider(self) -> None:
        from schwab_mcp.price_history import get_price_history

        payload = fx.DAILY_PAYLOAD
        client = FakePriceHistoryClient(payload=payload)
        result = get_price_history(
            client,
            fx.SYMBOL,
            extended=True,
            fetch_time=_closed_fetch_time(payload),
        )

        assert result["outcome"] == "ok"
        assert result["extended"] is True
        assert result["candles"], "curated array remains present"
        assert result["candle_count"] == len(payload["candles"])
        assert result["provider"] == payload, (
            "complete raw payload, no curation"
        )

    def test_default_mode_omits_provider_channel(self) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD)
        result = get_price_history(client, fx.SYMBOL)

        assert "provider" not in result

    def test_1h_provider_channel_carries_underlying_30m_payload(self) -> None:
        """Research D2: for ``1h`` the raw channel carries the underlying
        30-minute provider payload while ``candles`` stays hourly."""
        from schwab_mcp.price_history import get_price_history

        payload = fx.MINUTE_30M_PAYLOAD
        client = FakePriceHistoryClient(payload=payload)
        result = get_price_history(
            client, "AAPL", "1h", "5d", extended=True, extended_hours=True
        )

        assert result["outcome"] == "ok"
        assert result["provider"] == payload
        assert result["candles"]
        assert result["candle_count"] == len(result["candles"])
        assert result["candle_count"] < len(payload["candles"])

    def test_extended_error_follows_same_envelope(self) -> None:
        """Errors in extended mode are the same structured envelopes — no
        partial data (FR-008)."""
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.EMPTY_PAYLOAD)
        result = get_price_history(client, fx.NO_HISTORY_SYMBOL, extended=True)

        assert result["outcome"] == "history_unavailable"
        assert result["detail"] == "source_returned_no_candles"
        assert "candles" not in result
        assert "provider" not in result

    def test_extended_transient_error_follows_same_envelope(self) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD, status=500)
        result = get_price_history(client, fx.SYMBOL, extended=True)

        assert result["outcome"] == "provider_unreachable"
        assert result["retryable"] is True
        assert "candles" not in result
        assert "provider" not in result