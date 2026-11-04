"""RED-phase curated-mapping tests for ``get_price_history`` (T005, US1).

TDD red-phase: ``schwab_mcp.price_history`` exposes the skeleton only, so
every test here fails (``NotImplementedError``) until the implementation
lands.

Pins the provider -> curated candle mapping of data-model.md on the Phase 1
fixtures (``tests/unit/fixtures/price_history_payloads.py``): ``datetime`` ->
``t`` (epoch milliseconds, kept as-is — the D6/D8 stamping conventions are
PARAMETERIZED and unverified, so no stamping assumption is hard-coded here),
``open`` -> ``o``, ``high`` -> ``h``, ``low`` -> ``l``, ``close`` -> ``c``,
``volume`` -> ``v``.  All values pass through AS DELIVERED — no rounding, no
adjustment (FR-012, research D9).  Also pins: chronological order oldest
first (FR-005), ``candle_count`` / ``window`` metadata (FR-015), the ok
envelope echoing the effective selection including defaults (FR-002) and the
normalized symbol (contracts/mcp-tools.md §2), ``v`` = ``null`` only when the
source omits ``volume``, and the uniform candle shape with ``in_progress`` on
every candle (quickstart S1, FR-013/FR-017).
"""

from __future__ import annotations

import copy

from tests.unit.fixtures import price_history_payloads as fx
from tests.unit.helpers import FakePriceHistoryClient

CANDLE_KEYS = {"t", "o", "h", "l", "c", "v", "in_progress"}

MAPPED_FIELDS = ("t", "o", "h", "l", "c", "v")


def _client(payload: dict) -> FakePriceHistoryClient:
    """Provider double serving a deep copy of *payload* (fixture safety)."""
    return FakePriceHistoryClient(payload=copy.deepcopy(payload))


def _history(client: FakePriceHistoryClient, symbol: str = fx.SYMBOL, **kwargs) -> dict:
    from schwab_mcp.price_history import get_price_history

    result = get_price_history(client, symbol, **kwargs)
    assert result["outcome"] == "ok", result
    return result


def _mapped(candle: dict) -> dict:
    """The six mapped fields of one curated candle (order-independent)."""
    return {key: candle[key] for key in MAPPED_FIELDS}


def _expected_candles(payload: dict) -> list[dict]:
    """Fixture provider bars mapped to the curated field names (values
    as delivered — this is the mapping under test)."""
    return [
        {
            "t": bar["datetime"],
            "o": bar["open"],
            "h": bar["high"],
            "l": bar["low"],
            "c": bar["close"],
            "v": bar["volume"],
        }
        for bar in payload["candles"]
    ]


def _payload(candles: list[dict], symbol: str = fx.SYMBOL) -> dict:
    """A minimal provider payload with the documented shape."""
    return {"candles": candles, "symbol": symbol, "empty": False}


# =============================================================================
# Ok envelope (contract §2) — effective selection echo (FR-002)
# =============================================================================


class TestOkEnvelope:
    """The success envelope matches contracts/mcp-tools.md §2 and echoes
    the effective selection, defaults included."""

    def test_default_selection_echoed(self) -> None:
        """Omitted ``frequency``/``period``/flags resolve to the defaults
        ``daily``/``1m``/``false``/``false`` and are echoed as such."""
        result = _history(_client(fx.DAILY_PAYLOAD), fx.SYMBOL)

        assert result["outcome"] == "ok"
        assert result["detail"] == "price_history_retrieved"
        assert result["symbol"] == "SPY"
        assert result["frequency"] == "daily"
        assert result["period"] == "1m"
        assert result["extended_hours"] is False
        assert result["extended"] is False

    def test_explicit_selection_echoed(self) -> None:
        """A non-default selection echoes exactly what was requested."""
        result = _history(
            _client(fx.MINUTE_30M_PAYLOAD),
            "AAPL",
            frequency="30m",
            period="5d",
            extended_hours=True,
            extended=True,
        )

        assert result["outcome"] == "ok"
        assert result["detail"] == "price_history_retrieved"
        assert result["symbol"] == "AAPL"
        assert result["frequency"] == "30m"
        assert result["period"] == "5d"
        assert result["extended_hours"] is True
        assert result["extended"] is True

    def test_symbol_echo_is_normalized(self) -> None:
        """``symbol`` echoes the normalized request (strip + uppercase)."""
        result = _history(_client(fx.DAILY_PAYLOAD), "  spy  ")

        assert result["symbol"] == "SPY"


# =============================================================================
# Provider -> curated field mapping (data-model "Candle", exact values)
# =============================================================================


class TestFieldMapping:
    """``datetime``->``t`` (epoch ms as-is), ``open``->``o``,
    ``high``->``h``, ``low``->``l``, ``close``->``c``, ``volume``->``v`` —
    every value exactly as delivered (FR-012, research D9)."""

    def test_daily_candles_map_fields_exactly(self) -> None:
        result = _history(_client(fx.DAILY_PAYLOAD), fx.SYMBOL)

        assert [_mapped(candle) for candle in result["candles"]] == (
            _expected_candles(fx.DAILY_PAYLOAD)
        )

    def test_minute_candles_map_fields_exactly(self) -> None:
        result = _history(
            _client(fx.MINUTE_30M_PAYLOAD), "AAPL", frequency="30m", period="5d"
        )

        assert [_mapped(candle) for candle in result["candles"]] == (
            _expected_candles(fx.MINUTE_30M_PAYLOAD)
        )

    def test_values_pass_through_unrounded_and_unadjusted(self) -> None:
        """FR-012: no rounding and no price adjustment — sub-cent
        precision survives the mapping bit-exact."""
        bar = {
            "open": 585.123456,
            "high": 586.987654321,
            "low": 583.00001,
            "close": 585.5555,
            "volume": 41_234_567,
            "datetime": 1_730_419_200_000,
        }
        result = _history(_client(_payload([bar])), fx.SYMBOL)

        assert _mapped(result["candles"][0]) == {
            "t": 1_730_419_200_000,
            "o": 585.123456,
            "h": 586.987654321,
            "l": 583.00001,
            "c": 585.5555,
            "v": 41_234_567,
        }

    def test_timestamp_is_epoch_milliseconds_kept_as_is(self) -> None:
        """``t`` is the provider ``datetime`` verbatim — an integer epoch
        in milliseconds, never re-based or unit-converted (the D6/D8
        stamping convention stays out of this mapping)."""
        result = _history(_client(fx.DAILY_PAYLOAD), fx.SYMBOL)

        for candle, bar in zip(result["candles"], fx.DAILY_PAYLOAD["candles"]):
            assert candle["t"] == bar["datetime"]
            assert isinstance(candle["t"], int)


# =============================================================================
# Chronological order (FR-005)
# =============================================================================


class TestChronologicalOrder:
    """``candles`` is a chronological array, oldest first (FR-005)."""

    def test_candles_are_oldest_first(self) -> None:
        result = _history(_client(fx.DAILY_PAYLOAD), fx.SYMBOL)

        stamps = [candle["t"] for candle in result["candles"]]
        assert stamps == sorted(stamps)
        assert stamps == [bar["datetime"] for bar in fx.DAILY_PAYLOAD["candles"]]

    def test_out_of_order_source_is_curated_ascending(self) -> None:
        """Curation guarantees the order even if the source delivers
        descending (contract §4: "curate: chronological array")."""
        bars = [
            {
                "open": 3.0,
                "high": 3.5,
                "low": 2.9,
                "close": 3.2,
                "volume": 300,
                "datetime": 1_730_419_200_000 + offset,
            }
            for offset in (120_000, 60_000, 0)
        ]
        result = _history(_client(_payload(bars)), fx.SYMBOL)

        assert [candle["t"] for candle in result["candles"]] == [
            1_730_419_200_000,
            1_730_419_260_000,
            1_730_419_320_000,
        ]


# =============================================================================
# Coverage metadata (FR-015)
# =============================================================================


class TestWindowAndCount:
    """``candle_count`` and ``window`` state the covered span without
    forcing the agent to count (FR-015, SC-005)."""

    def test_candle_count_matches_candle_list(self) -> None:
        result = _history(_client(fx.DAILY_PAYLOAD), fx.SYMBOL)

        assert result["candle_count"] == len(result["candles"])
        assert result["candle_count"] == len(fx.DAILY_PAYLOAD["candles"])

    def test_window_matches_first_and_last_timestamp(self) -> None:
        result = _history(_client(fx.DAILY_PAYLOAD), fx.SYMBOL)

        assert result["window"]["first"] == result["candles"][0]["t"]
        assert result["window"]["last"] == result["candles"][-1]["t"]
        assert result["window"]["first"] == fx.DAILY_PAYLOAD["candles"][0]["datetime"]
        assert result["window"]["last"] == fx.DAILY_PAYLOAD["candles"][-1]["datetime"]


# =============================================================================
# Volume (data-model: ``v`` integer | null)
# =============================================================================


class TestVolume:
    """``v`` is ``null`` only when the source omits ``volume`` — never
    invented, never zeroed (FR-012)."""

    def test_missing_volume_maps_to_null(self) -> None:
        bar = {
            "open": 585.0,
            "high": 586.0,
            "low": 584.0,
            "close": 585.5,
            "datetime": 1_730_419_200_000,
        }
        result = _history(_client(_payload([bar])), fx.SYMBOL)

        assert result["candles"][0]["v"] is None

    def test_zero_volume_passes_through_as_zero(self) -> None:
        """A delivered ``0`` volume is data, not a missing value."""
        bar = {
            "open": 585.0,
            "high": 586.0,
            "low": 584.0,
            "close": 585.5,
            "volume": 0,
            "datetime": 1_730_419_200_000,
        }
        result = _history(_client(_payload([bar])), fx.SYMBOL)

        assert result["candles"][0]["v"] == 0

    def test_delivered_volume_passes_through_exactly(self) -> None:
        result = _history(_client(fx.DAILY_PAYLOAD), fx.SYMBOL)

        for candle, bar in zip(result["candles"], fx.DAILY_PAYLOAD["candles"]):
            assert candle["v"] == bar["volume"]


# =============================================================================
# Uniform candle shape (quickstart S1, FR-013/FR-017)
# =============================================================================


class TestInProgressShape:
    """Every candle carries ``in_progress`` (quickstart S1: "in_progress
    on every candle"); the shape is uniform and derived values are never
    present (FR-013).  The ``true``/``false`` derivation itself (D6) is
    convention-parameterized and pinned elsewhere."""

    def test_every_candle_carries_in_progress(self) -> None:
        result = _history(_client(fx.DAILY_PAYLOAD), fx.SYMBOL)

        assert len(result["candles"]) == len(fx.DAILY_PAYLOAD["candles"])
        for candle in result["candles"]:
            assert "in_progress" in candle
            assert isinstance(candle["in_progress"], bool)

    def test_candle_shape_is_uniform_with_no_derived_fields(self) -> None:
        result = _history(
            _client(fx.MINUTE_30M_PAYLOAD), "AAPL", frequency="30m", period="5d"
        )

        assert len(result["candles"]) == 65
        for candle in result["candles"]:
            assert set(candle) == CANDLE_KEYS


# =============================================================================
# Shared envelope builders (bug td-004) — parity with the pre-dedup shapes
# =============================================================================


class TestSharedEnvelopeBuilders:
    """The shared builders in ``tool_errors`` emit exactly the shapes the
    module-private helpers emitted before the dedup: the ``symbol`` key sits
    between ``retryable`` and any extra keys (contracts/mcp-tools.md §3)."""

    def test_validation_error_names_symbol_before_extra(self) -> None:
        from schwab_mcp.tool_errors import validation_error

        envelope = validation_error("invalid_period", "SPX", limit=5)
        assert envelope == {
            "outcome": "validation_error",
            "detail": "invalid_period",
            "retryable": False,
            "symbol": "SPX",
            "limit": 5,
        }
        assert list(envelope) == [
            "outcome",
            "detail",
            "retryable",
            "symbol",
            "limit",
        ]

    def test_provider_unreachable_names_symbol(self) -> None:
        from schwab_mcp.tool_errors import provider_unreachable

        envelope = provider_unreachable(symbol="SPX")
        assert envelope == {
            "outcome": "provider_unreachable",
            "detail": "provider_unreachable",
            "retryable": True,
            "symbol": "SPX",
        }
        assert list(envelope) == ["outcome", "detail", "retryable", "symbol"]

    def test_reauth_needed_names_symbol(self) -> None:
        from schwab_mcp.tool_errors import reauth_needed

        envelope = reauth_needed(symbol="SPX")
        assert envelope == {
            "outcome": "reauth_needed",
            "detail": "reauth_needed",
            "retryable": False,
            "symbol": "SPX",
        }
        assert list(envelope) == ["outcome", "detail", "retryable", "symbol"]

    def test_history_unavailable_shape(self) -> None:
        from schwab_mcp.tool_errors import history_unavailable

        envelope = history_unavailable(symbol="SPX")
        assert envelope == {
            "outcome": "history_unavailable",
            "detail": "source_returned_no_candles",
            "retryable": False,
            "symbol": "SPX",
        }
        assert list(envelope) == ["outcome", "detail", "retryable", "symbol"]