"""End-to-end integration tests for ``get_quotes`` with a provider double.

TDD red-phase for the tasks' RED groups: T008 (US1 flows), T013 (US2
batch), T016 (US3 extended).  The suite runs WITHOUT network and WITHOUT
a token: a :class:`FakeQuotesClient` (tests.unit.helpers) records every
upcall and answers with the LIVE-captured payloads of
``tests/unit/fixtures/quotes_payloads.py`` wrapped in real
``requests.Response`` objects.

Covers
------
- S1: single-symbol ``ok`` envelope end to end (quickstart S1)
- unknown symbol -> ``quote_unavailable`` / ``not_found``, NO partial data
  (FR-006, quickstart S4)
- provider 5xx/408/429 -> retryable ``provider_unreachable``
- 401/403 -> ``reauth_needed`` (shared taxonomy via ``provider.response_json``)
- US2: 4-kind batch keyed by symbol, de-duplication, ONE provider call
  carrying the whole list, mixed missing symbol -> whole invocation
  ``quote_unavailable`` with per-symbol errors (clarification Q3)
- US3: ``extended=true`` -> curated ``quotes`` + raw ``provider`` channel
  (SC-006, verified against the fields="all" fixture), the provider call
  uses ``fields="all"``, curated portion still budgeted
"""

from __future__ import annotations

import copy
import json

import pytest

from tests.unit.fixtures.quotes_payloads import (
    BATCH_ALL_PAYLOAD,
    BATCH_QUOTE_PAYLOAD,
    EQUITY_ALL_ENTRY,
    EQUITY_QUOTE_ENTRY,
    INDEX_QUOTE_ENTRY,
    MIXED_UNKNOWN_PAYLOAD,
    OPTION_QUOTE_ENTRY,
    UNKNOWN_SYMBOL_PAYLOAD,
)
from tests.unit.helpers import (
    FakeQuotesClient,
    build_quote_entry,
    build_quotes_payload,
)

OPTION_SYMBOL = "AAPL  261028C00345000"


def _tokens(result: dict) -> float:
    """Approximate token size (compact serialized chars / 4)."""
    return len(json.dumps(result, separators=(",", ":"))) / 4


# =============================================================================
# S1 — single-symbol curated quote (quickstart S1)
# =============================================================================


class TestSingleSymbolOk:
    """``{"symbols": "AAPL"}`` -> the complete ``ok`` envelope in one
    invocation."""

    def test_ok_envelope_end_to_end(self) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY})
        result = get_quotes(client, "AAPL")

        assert result["outcome"] == "ok"
        assert result["detail"] == "quotes_retrieved"
        assert result["requested_count"] == 1
        assert result["extended"] is False
        assert set(result["quote_fields"]) == {
            "symbol", "description", "last", "bid", "ask",
            "volume", "net_change", "net_change_pct",
            "data_state", "trade_time",
        }
        quote = result["quotes"]["AAPL"]
        assert quote["data_state"] in ("realtime", "delayed", "closed")
        assert "trade_time" in quote

    def test_single_provider_quotes_call_with_quote_fields(self) -> None:
        """One quotes() call with fields="quote", indicative=false, plus
        exactly one market-hours check (research D4)."""
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY})
        get_quotes(client, "AAPL")

        assert len(client.quotes_calls) == 1
        call = client.quotes_calls[0]
        assert call["symbols"] == ["AAPL"]
        assert call["fields"] == "quote"
        assert call["indicative"] is False
        assert len(client.market_hours_calls) == 1

    def test_no_partial_data_and_no_pagination_keys(self) -> None:
        """FR-006/FR-011: the success response is self-contained."""
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY})
        result = get_quotes(client, "AAPL")

        keys = set()
        def _collect(obj):
            if isinstance(obj, dict):
                keys.update(obj)
                for value in obj.values():
                    _collect(value)
            elif isinstance(obj, list):
                for item in obj:
                    _collect(item)
        _collect(result)
        assert not (keys & {"cursor", "offset", "has_more", "page"})


# =============================================================================
# Unknown symbol -> quote_unavailable, no partial data (quickstart S4)
# =============================================================================


class TestUnknownSymbol:
    """A well-formed symbol the source cannot quote is reported per
    symbol with NO partial ``quotes`` object (FR-006)."""

    def test_unknown_symbol_structured_error(self) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload=dict(UNKNOWN_SYMBOL_PAYLOAD))
        result = get_quotes(client, "ZOMB")

        assert result["outcome"] == "quote_unavailable"
        assert result["detail"] == "source_could_not_quote_all_symbols"
        assert result["errors"] == {"ZOMB": "not_found"}
        assert result["retryable"] is False
        assert result["requested_count"] == 1

    def test_no_partial_quotes_object(self) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload=dict(UNKNOWN_SYMBOL_PAYLOAD))
        result = get_quotes(client, "ZOMB")

        assert "quotes" not in result

    def test_expired_option_contract_is_not_found(self) -> None:
        """An expired/unquoted option contract surfaces as not_found —
        never a fabricated quote (spec edge cases)."""
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(
            quotes_payload={"errors": {"invalidSymbols": [OPTION_SYMBOL]}}
        )
        result = get_quotes(client, OPTION_SYMBOL)

        assert result["outcome"] == "quote_unavailable"
        assert result["errors"] == {OPTION_SYMBOL: "not_found"}


# =============================================================================
# Source down -> retryable provider_unreachable (quickstart S4)
# =============================================================================


class TestSourceDown:
    """5xx/408/429 on the quotes call -> structured retryable
    ``provider_unreachable``, exactly one upstream call, no partial data."""

    @pytest.mark.parametrize("status", [500, 502, 408, 429], ids=["500", "502", "408", "429"])
    def test_transient_status_is_provider_unreachable(self, status) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(
            quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY}, quotes_status=status
        )
        result = get_quotes(client, "AAPL")

        assert result["outcome"] == "provider_unreachable"
        assert result["retryable"] is True
        assert "quotes" not in result
        assert len(client.quotes_calls) == 1

    def test_network_error_is_provider_unreachable(self) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_error=ConnectionError("network down"))
        result = get_quotes(client, "AAPL")

        assert result["outcome"] == "provider_unreachable"
        assert result["retryable"] is True


# =============================================================================
# 401/403 -> reauth_needed (shared taxonomy)
# =============================================================================


class TestReauthRequired:
    """Provider 401/403 map through the shared taxonomy to a structured
    ``reauth_needed`` result (user action, not retryable)."""

    @pytest.mark.parametrize("status", [401, 403], ids=["401", "403"])
    def test_reauth_needed_on_auth_failure(self, status) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(
            quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY}, quotes_status=status
        )
        result = get_quotes(client, "AAPL")

        assert result["outcome"] == "reauth_needed"
        assert result["retryable"] is False
        assert "quotes" not in result


# =============================================================================
# US2 (T013) — batch quotes for several instruments
# =============================================================================


class TestBatchQuotes:
    """One invocation quotes every requested instrument: one keyed entry
    per distinct symbol (clarification Q3)."""

    def test_four_kind_batch_returns_one_entry_per_symbol(self) -> None:
        """equity + ETF + index + option contract in one response."""
        from schwab_mcp.quotes import get_quotes

        etf_entry = build_quote_entry("SPY", last=680.5)
        payload = copy.deepcopy(BATCH_QUOTE_PAYLOAD)
        payload["SPY"] = etf_entry
        client = FakeQuotesClient(quotes_payload=payload)

        result = get_quotes(
            client,
            ["AAPL", "SPY", "$SPX", OPTION_SYMBOL],
        )

        assert result["outcome"] == "ok"
        assert result["requested_count"] == 4
        assert sorted(result["quotes"]) == sorted(
            ["AAPL", "SPY", "$SPX", OPTION_SYMBOL]
        )
        for symbol, quote in result["quotes"].items():
            assert quote["symbol"] == symbol

    def test_duplicates_de_deduplicated_requested_count_distinct(self) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload=copy.deepcopy(BATCH_QUOTE_PAYLOAD))
        result = get_quotes(client, ["AAPL", "$SPX", "aapl", OPTION_SYMBOL])

        assert result["outcome"] == "ok"
        assert result["requested_count"] == 3
        assert sorted(result["quotes"]) == sorted(["AAPL", "$SPX", OPTION_SYMBOL])

    def test_single_provider_call_carries_the_whole_list(self) -> None:
        """D1: one quotes() call per invocation — no per-symbol calls."""
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload=copy.deepcopy(BATCH_QUOTE_PAYLOAD))
        get_quotes(client, ["AAPL", "$SPX", OPTION_SYMBOL])

        assert len(client.quotes_calls) == 1
        assert sorted(client.quotes_calls[0]["symbols"]) == sorted(
            ["AAPL", "$SPX", OPTION_SYMBOL]
        )
        assert len(client.market_hours_calls) == 1

    def test_mixed_batch_missing_symbol_is_whole_invocation_error(self) -> None:
        """FR-006: one unquotable symbol poisons nothing partially — the
        invocation is ``quote_unavailable`` with per-symbol errors."""
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload=copy.deepcopy(MIXED_UNKNOWN_PAYLOAD))
        result = get_quotes(client, ["AAPL", "ZOMB"])

        assert result["outcome"] == "quote_unavailable"
        assert result["errors"] == {"ZOMB": "not_found"}
        assert "quotes" not in result, "no partial data"

    def test_option_aliases_are_one_distinct_symbol(self) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload=copy.deepcopy(BATCH_QUOTE_PAYLOAD))
        result = get_quotes(
            client, ["AAPL 261028C00345000", OPTION_SYMBOL]
        )

        assert result["outcome"] == "ok"
        assert result["requested_count"] == 1


# =============================================================================
# US3 (T016) — extended raw payload
# =============================================================================


class TestExtended:
    """``extended=true`` returns the curated view AND the complete raw
    provider payload (SC-006)."""

    def test_extended_true_carries_curated_and_provider(self) -> None:
        from schwab_mcp.quotes import get_quotes

        payload = {"AAPL": copy.deepcopy(EQUITY_ALL_ENTRY)}
        client = FakeQuotesClient(quotes_payload=payload)
        result = get_quotes(client, "AAPL", extended=True)

        assert result["outcome"] == "ok"
        assert result["extended"] is True
        assert result["quotes"]["AAPL"]["last"] is not None
        assert result["provider"] == payload, "complete raw payload, no curation"

    def test_extended_provider_call_uses_fields_all(self) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(
            quotes_payload={"AAPL": copy.deepcopy(EQUITY_ALL_ENTRY)}
        )
        get_quotes(client, "AAPL", extended=True)

        assert client.quotes_calls[0]["fields"] == "all"
        assert client.quotes_calls[0]["indicative"] is False

    def test_default_mode_omits_provider_channel(self) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY})
        result = get_quotes(client, "AAPL")

        assert "provider" not in result

    def test_curated_portion_respects_budget_in_extended_mode(self) -> None:
        """The raw channel is not budget-capped (contract §5) but the
        curated portion alone still fits the per-symbol budget."""
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(
            quotes_payload={"AAPL": copy.deepcopy(EQUITY_ALL_ENTRY)}
        )
        result = get_quotes(client, "AAPL", extended=True)

        curated = {k: v for k, v in result.items() if k != "provider"}
        assert _tokens(curated) <= 250

    def test_extended_error_follows_same_envelope(self) -> None:
        """Errors in extended mode are the same structured envelopes —
        no partial data (FR-006)."""
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload=dict(UNKNOWN_SYMBOL_PAYLOAD))
        result = get_quotes(client, "ZOMB", extended=True)

        assert result["outcome"] == "quote_unavailable"
        assert "quotes" not in result
        assert "provider" not in result

    def test_extended_batch_matches_fields_all_fixture(self) -> None:
        """SC-006: the raw channel equals the captured fields="all"
        payload for the whole batch."""
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload=copy.deepcopy(BATCH_ALL_PAYLOAD))
        result = get_quotes(
            client, ["AAPL", "$SPX", OPTION_SYMBOL], extended=True
        )

        assert result["outcome"] == "ok"
        assert result["provider"] == BATCH_ALL_PAYLOAD
