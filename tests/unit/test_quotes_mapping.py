"""RED-phase curated-mapping tests for ``get_quotes`` (T005, US1).

TDD red-phase: ``schwab_mcp.quotes`` exposes the skeleton only, so every
test fails until T010 lands.

Pins the provider -> curated field mapping of data-model.md (research
D6) on the LIVE-captured payload shape (fixtures from T002): entries
nest market fields under ``quote{}``; the net-change source field is
``netChange``; ``tradeTime`` is epoch milliseconds; ``reference.description``
is the description source.  Recorded deviations from the D6 table are in
the implementing commit message.

Rounding: 2 decimals for equity/ETF/index symbols, 4 decimals for
option-contract symbols (decided by the REQUESTED symbol's kind);
``net_change_pct`` computed as ``net_change / closePrice * 100`` with
``null`` when ``closePrice`` is missing or 0 (FR-002); missing provider
fields become explicit ``null`` (FR-012); the response declares
``quote_fields`` (pattern of 008's ``contract_fields``).
"""

from __future__ import annotations

import copy

import pytest

from tests.unit.fixtures.quotes_payloads import (
    BATCH_QUOTE_PAYLOAD,
    EQUITY_QUOTE_ENTRY,
    INDEX_QUOTE_ENTRY,
    OPTION_QUOTE_ENTRY,
)
from tests.unit.helpers import FakeQuotesClient, build_quote_entry, build_quotes_payload

EXPECTED_QUOTE_FIELDS = [
    "symbol",
    "description",
    "last",
    "bid",
    "ask",
    "volume",
    "net_change",
    "net_change_pct",
    "data_state",
    "trade_time",
]


def _client(entry: dict, symbol: str) -> FakeQuotesClient:
    """Client serving one provider entry keyed by *symbol*."""
    payload = {symbol: entry}
    return FakeQuotesClient(quotes_payload=payload)


def _quote(client: FakeQuotesClient, symbols) -> dict:
    from schwab_mcp.quotes import get_quotes

    result = get_quotes(client, symbols)
    assert result["outcome"] == "ok", result
    return result


# =============================================================================
# Ok envelope (contract §2)
# =============================================================================


class TestOkEnvelope:
    """The success envelope matches contracts/mcp-tools.md §2."""

    def test_envelope_fields(self) -> None:
        result = _quote(_client(EQUITY_QUOTE_ENTRY, "AAPL"), "AAPL")

        assert result["outcome"] == "ok"
        assert result["detail"] == "quotes_retrieved"
        assert result["requested_count"] == 1
        assert result["extended"] is False

    def test_quote_fields_declared_in_fixed_order(self) -> None:
        """``quote_fields`` declares the curated schema (pattern of 008)."""
        result = _quote(_client(EQUITY_QUOTE_ENTRY, "AAPL"), "AAPL")

        assert result["quote_fields"] == EXPECTED_QUOTE_FIELDS


# =============================================================================
# Live fixture mappings (exact values, T002 evidence)
# =============================================================================


class TestLiveEquityMapping:
    """The live AAPL ``fields="quote"`` entry maps to the curated schema
    with 2-decimal prices and computed percent change."""

    def test_curated_values_are_exact(self) -> None:
        result = _quote(_client(EQUITY_QUOTE_ENTRY, "AAPL"), "AAPL")

        assert result["quotes"]["AAPL"] == {
            "symbol": "AAPL",
            "description": None,
            "last": 346.18,
            "bid": 346.18,
            "ask": 346.2,
            "volume": 12672238,
            "net_change": 2.27,
            "net_change_pct": 0.66,
            "data_state": "realtime",
            "trade_time": "2026-10-27T16:14:38+00:00",
        }


class TestLiveIndexMapping:
    """The live ``$SPX`` entry has no bid/ask at all -> explicit nulls
    (FR-012) and no ``quoteType`` -> freshness from the ``realtime`` flag."""

    def test_curated_values_are_exact(self) -> None:
        result = _quote(_client(INDEX_QUOTE_ENTRY, "$SPX"), "$SPX")

        assert result["quotes"]["$SPX"] == {
            "symbol": "$SPX",
            "description": None,
            "last": 7727.51,
            "bid": None,
            "ask": None,
            "volume": 986489882,
            "net_change": 50.74,
            "net_change_pct": 0.66,
            "data_state": "realtime",
            "trade_time": "2026-10-27T16:14:40+00:00",
        }


class TestLiveOptionMapping:
    """The live option-contract entry maps with 4-decimal prices (kind of
    the requested symbol)."""

    def test_curated_values_are_exact(self) -> None:
        result = _quote(
            _client(OPTION_QUOTE_ENTRY, "AAPL  261028C00345000"),
            "AAPL  261028C00345000",
        )

        assert result["quotes"]["AAPL  261028C00345000"] == {
            "symbol": "AAPL  261028C00345000",
            "description": None,
            "last": 2.56,
            "bid": 2.51,
            "ask": 2.57,
            "volume": 39375,
            "net_change": 0.41,
            "net_change_pct": 19.07,
            "data_state": "realtime",
            "trade_time": "2026-10-27T16:19:35+00:00",
        }


# =============================================================================
# Rounding rules (research D6)
# =============================================================================


class TestRounding:
    """2 decimals for equity/ETF/index symbols, 4 decimals for option
    contract symbols; ``net_change_pct`` always 2 decimals."""

    def test_equity_prices_round_to_2_decimals(self) -> None:
        entry = build_quote_entry("AAPL", last=1.23456, bid=9.876, ask=9.999, net_change=0.1234)
        result = _quote(_client(entry, "AAPL"), "AAPL")

        quote = result["quotes"]["AAPL"]
        assert quote["last"] == 1.23
        assert quote["bid"] == 9.88
        assert quote["ask"] == 10.0
        assert quote["net_change"] == 0.12

    def test_option_prices_round_to_4_decimals(self) -> None:
        entry = build_quote_entry(
            "AAPL  251127C00200000", last=1.23456, bid=0.99999, ask=2.00006, net_change=0.12346
        )
        result = _quote(_client(entry, "AAPL  251127C00200000"), "AAPL 251127C200")

        quote = result["quotes"]["AAPL 251127C200"]
        assert quote["last"] == 1.2346
        assert quote["bid"] == 1.0
        assert quote["ask"] == 2.0001
        assert quote["net_change"] == 0.1235

    def test_index_prices_round_to_2_decimals(self) -> None:
        entry = build_quote_entry("$SPX", last=7727.516, net_change=50.744)
        result = _quote(_client(entry, "$SPX"), "$SPX")

        quote = result["quotes"]["$SPX"]
        assert quote["last"] == 7727.52
        assert quote["net_change"] == 50.74


# =============================================================================
# description (data-model D6, user decision 2026-10-27)
# =============================================================================


class TestDescription:
    """``description`` comes from ``reference.description`` (live
    location) and is truncated to 80 chars; absent -> explicit null.
    The curated ``fields="quote"`` fetch never carries it (live fact)."""

    def test_live_quote_payload_yields_null_description(self) -> None:
        result = _quote(_client(EQUITY_QUOTE_ENTRY, "AAPL"), "AAPL")
        assert result["quotes"]["AAPL"]["description"] is None

    def test_reference_description_passes_through(self) -> None:
        entry = build_quote_entry("AAPL", description="APPLE INC")
        result = _quote(_client(entry, "AAPL"), "AAPL")
        assert result["quotes"]["AAPL"]["description"] == "APPLE INC"

    def test_description_truncated_to_80_chars(self) -> None:
        long_description = "X" * 100
        entry = build_quote_entry("AAPL", description=long_description)
        result = _quote(_client(entry, "AAPL"), "AAPL")

        description = result["quotes"]["AAPL"]["description"]
        assert len(description) == 80
        assert description == "X" * 80

    def test_live_option_reference_description_reaches_curated(self) -> None:
        """The fields="all" option entry carries a description; the
        curated mapping truncates/echoes it when present."""
        from tests.unit.fixtures.quotes_payloads import OPTION_ALL_ENTRY

        result = _quote(
            _client(copy.deepcopy(OPTION_ALL_ENTRY), "AAPL  261028C00345000"),
            "AAPL  261028C00345000",
        )
        assert result["quotes"]["AAPL  261028C00345000"]["description"] == (
            "AAPL 10/28/2026 345.00 C"
        )


# =============================================================================
# net_change_pct (FR-002) and missing fields (FR-012)
# =============================================================================


class TestNetChangePct:
    """``net_change_pct`` is computed from the raw provider values as
    ``net_change / closePrice * 100`` and never invented."""

    def test_computed_percent_change(self) -> None:
        entry = build_quote_entry("AAPL", net_change=2.0, close=80.0)
        result = _quote(_client(entry, "AAPL"), "AAPL")
        assert result["quotes"]["AAPL"]["net_change_pct"] == 2.5

    def test_percent_change_rounded_to_2_decimals(self) -> None:
        entry = build_quote_entry("AAPL", net_change=1.0, close=3.0)
        result = _quote(_client(entry, "AAPL"), "AAPL")
        assert result["quotes"]["AAPL"]["net_change_pct"] == 33.33

    def test_null_when_close_price_missing(self) -> None:
        entry = build_quote_entry("AAPL", net_change=1.0, close=None)
        result = _quote(_client(entry, "AAPL"), "AAPL")
        assert result["quotes"]["AAPL"]["net_change_pct"] is None

    def test_null_when_close_price_zero(self) -> None:
        entry = build_quote_entry("AAPL", net_change=1.0, close=0)
        result = _quote(_client(entry, "AAPL"), "AAPL")
        assert result["quotes"]["AAPL"]["net_change_pct"] is None


class TestMissingFieldsExplicitNull:
    """FR-012: unavailable fields are explicit null — never defaulted,
    substituted, or interpolated."""

    def test_only_last_price_present(self) -> None:
        entry = build_quote_entry(
            "AAPL",
            last=10.0,
            bid=None,
            ask=None,
            volume=None,
            net_change=None,
            close=None,
            trade_time=None,
            description=None,
        )
        result = _quote(_client(entry, "AAPL"), "AAPL")

        assert result["quotes"]["AAPL"] == {
            "symbol": "AAPL",
            "description": None,
            "last": 10.0,
            "bid": None,
            "ask": None,
            "volume": None,
            "net_change": None,
            "net_change_pct": None,
            "data_state": "realtime",  # default live signals: realtime=True
            "trade_time": None,
        }

    def test_integral_volume_float_coerced_to_int(self) -> None:
        entry = build_quote_entry("AAPL", volume=12345.0)
        result = _quote(_client(entry, "AAPL"), "AAPL")
        assert result["quotes"]["AAPL"]["volume"] == 12345
        assert isinstance(result["quotes"]["AAPL"]["volume"], int)


# =============================================================================
# trade_time (data-model D6: ISO 8601 UTC)
# =============================================================================


class TestTradeTime:
    """``tradeTime`` epoch milliseconds become ISO 8601 UTC; zero means
    never traded -> null (pattern of 008's trade-time normalization)."""

    def test_epoch_milliseconds_become_iso_utc(self) -> None:
        entry = build_quote_entry("AAPL", trade_time=1793117678969)
        result = _quote(_client(entry, "AAPL"), "AAPL")
        assert result["quotes"]["AAPL"]["trade_time"] == "2026-10-27T16:14:38+00:00"

    def test_zero_epoch_maps_to_null(self) -> None:
        entry = build_quote_entry("AAPL", trade_time=0)
        result = _quote(_client(entry, "AAPL"), "AAPL")
        assert result["quotes"]["AAPL"]["trade_time"] is None

    def test_missing_trade_time_maps_to_null(self) -> None:
        entry = build_quote_entry("AAPL", trade_time=None)
        result = _quote(_client(entry, "AAPL"), "AAPL")
        assert result["quotes"]["AAPL"]["trade_time"] is None


# =============================================================================
# Keyed by requested symbol (clarification Q3, research D6)
# =============================================================================


class TestKeyedByRequestedSymbol:
    """``quotes`` is keyed by the normalized REQUESTED symbol (D6:
    "as requested (normalized)"), even when the provider keys the entry by
    the canonical OCC spelling."""

    def test_compact_option_request_keys_by_requested_form(self) -> None:
        canonical = "AAPL  251127C00200000"
        entry = build_quote_entry(canonical, last=2.5)
        result = _quote(_client(entry, canonical), "AAPL 251127C200")

        assert list(result["quotes"]) == ["AAPL 251127C200"]
        assert result["quotes"]["AAPL 251127C200"]["symbol"] == "AAPL 251127C200"

    def test_batch_keys_are_distinct_requested_symbols(self) -> None:
        client = FakeQuotesClient(quotes_payload=copy.deepcopy(BATCH_QUOTE_PAYLOAD))
        result = _quote(client, ["AAPL", "$SPX", "AAPL  261028C00345000"])

        assert sorted(result["quotes"]) == [
            "$SPX",
            "AAPL",
            "AAPL  261028C00345000",
        ]
