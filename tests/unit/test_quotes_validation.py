"""RED-phase input-validation tests for ``get_quotes`` (T004, US1).

TDD red-phase: ``schwab_mcp.quotes`` exposes the skeleton only
(``NotImplementedError``), so every test fails until T009 lands.

Pins (research D5 + contracts/mcp-tools.md §1, FR-005/FR-007/FR-013):

- the three symbol-kind grammars on the normalized (strip + uppercase)
  form: index ``$[A-Z0-9]{1,5}``, option contract root + optional
  separator + ``YYMMDD`` + ``C``/``P`` + strike, equity/ETF
  ``[A-Z0-9]{1,6}`` with at most one embedded ``.``;
- fail-before-upcall: every validation failure returns a structured
  ``validation_error`` envelope and the provider client receives ZERO
  calls;
- normalization and de-duplication before the 20-distinct limit, the
  limit stated on overflow, and exactly 20 proceeding.

Live-evidence extensions (captured 2026-10-27, see the implementing
commit message and tests/unit/fixtures/quotes_payloads.py): the provider
quotes option contracts by canonical OCC form only (root padded to six
columns + 8-digit strike x 1000), so validation additionally accepts the
canonical OCC spelling and normalization rewrites every accepted option
spelling to that canonical form before the upcall.
"""

from __future__ import annotations

import pytest

from tests.unit.fixtures.quotes_payloads import UNKNOWN_SYMBOL_PAYLOAD
from tests.unit.helpers import (
    FakeQuotesClient,
    build_quote_entry,
    build_quotes_payload,
)

# Distinct synthetic equity symbols inside the equity grammar (TST01..).
SYNTH = [f"TST{i:02d}" for i in range(1, 22)]


def _unknown_client() -> FakeQuotesClient:
    """Client whose provider cannot quote anything (unknown-symbol body)."""
    return FakeQuotesClient(quotes_payload=UNKNOWN_SYMBOL_PAYLOAD)


def _synthetic_ok_client(symbols: list[str]) -> FakeQuotesClient:
    """Client serving one synthetic quote per *symbols* entry."""
    payload = build_quotes_payload([build_quote_entry(s) for s in symbols])
    return FakeQuotesClient(quotes_payload=payload)


# =============================================================================
# Empty symbol list (FR-005)
# =============================================================================


class TestEmptySymbolList:
    """/symbols/ empty or missing content -> ``validation_error`` /
    ``empty_symbol_list`` before any upcall."""

    @pytest.mark.parametrize(
        "symbols", [[], "", "   "], ids=["empty-list", "empty-string", "blank-string"]
    )
    def test_empty_symbols_return_validation_error(self, symbols) -> None:
        """Empty list and empty/blank string inputs share one structured state."""
        from schwab_mcp.quotes import get_quotes

        client = _unknown_client()
        result = get_quotes(client, symbols)

        assert result["outcome"] == "validation_error"
        assert result["detail"] == "empty_symbol_list"
        assert result["retryable"] is False

    @pytest.mark.parametrize("symbols", [[], ""], ids=["empty-list", "empty-string"])
    def test_zero_provider_calls_on_empty_list(self, symbols) -> None:
        """Fail-before-upcall (FR-005): no quotes() and no market_hours()."""
        from schwab_mcp.quotes import get_quotes

        client = _unknown_client()
        get_quotes(client, symbols)

        assert client.call_count == 0
        assert client.quotes_calls == []
        assert client.market_hours_calls == []

    def test_validation_error_carries_no_quotes_object(self) -> None:
        """Validation failures never carry partial quote data (FR-006)."""
        from schwab_mcp.quotes import get_quotes

        result = get_quotes(_unknown_client(), [])
        assert "quotes" not in result


# =============================================================================
# Malformed symbols (FR-005 / FR-013 — every offender named)
# =============================================================================

MALFORMED = [
    ("BAD SYMBOL", "internal space in equity symbol"),
    ("$BAD$", "index with invalid characters"),
    ("TOOLONGSYM", "equity longer than 6 characters"),
    ("BRK.B.A", "two embedded dots"),
    ("AAPL 251127X200", "option with invalid C/P letter"),
    ("AAPL 2511C200", "option with non-numeric expiration"),
    ("AAPL 251127C", "option without strike"),
    ("AAPL 251127C200.5.5", "option with malformed strike"),
    ("$TOOLONG1", "index root longer than 5 characters"),
    ("AAPL@", "illegal character"),
]


class TestMalformedSymbols:
    """A symbol matching no kind grammar -> ``validation_error`` /
    ``malformed_symbol`` with ``errors[symbol]`` naming it, zero upcalls."""

    @pytest.mark.parametrize(
        "symbol,case", MALFORMED, ids=[s.replace(" ", "-") for s, _ in MALFORMED]
    )
    def test_malformed_symbol_names_offender(self, symbol, case) -> None:
        """Each malformed spelling fails validation naming the symbol."""
        from schwab_mcp.quotes import get_quotes

        client = _unknown_client()
        result = get_quotes(client, [symbol])

        assert result["outcome"] == "validation_error", case
        assert result["detail"] == "malformed_symbol"
        assert result["retryable"] is False
        assert result["errors"] == {symbol.strip().upper(): "malformed_symbol"}

    @pytest.mark.parametrize(
        "symbol,case", MALFORMED, ids=[s.replace(" ", "-") for s, _ in MALFORMED]
    )
    def test_zero_provider_calls_on_malformed(self, symbol, case) -> None:
        """Fail-before-upcall (FR-005): the whole invocation fetches nothing."""
        from schwab_mcp.quotes import get_quotes

        client = _unknown_client()
        get_quotes(client, [symbol])

        assert client.call_count == 0, case

    def test_all_offenders_named_in_one_error(self) -> None:
        """FR-005: a structured validation error naming EVERY offending
        symbol; valid neighbours do not trigger a fetch either."""
        from schwab_mcp.quotes import get_quotes

        client = _unknown_client()
        result = get_quotes(client, ["AAPL", "BAD SYMBOL", "$BAD$"])

        assert result["outcome"] == "validation_error"
        assert result["detail"] == "malformed_symbol"
        assert result["errors"] == {
            "BAD SYMBOL": "malformed_symbol",
            "$BAD$": "malformed_symbol",
        }
        assert "AAPL" not in result["errors"]
        assert client.call_count == 0


# =============================================================================
# Accepted symbol kinds and canonicalization (FR-013)
# =============================================================================


class TestAcceptedSymbolKinds:
    """Every accepted spelling reaches exactly one quotes() call carrying
    the provider form of each symbol."""

    @pytest.mark.parametrize(
        "requested,expected_provider",
        [
            ("$SPX", ["$SPX"]),
            ("$spx", ["$SPX"]),
            ("aapl", ["AAPL"]),
            ("BRK.B", ["BRK.B"]),
            ("  nOk  ", ["NOK"]),
        ],
        ids=["index", "index-lowercase", "equity-lowercase", "class-shares", "stripped"],
    )
    def test_equity_index_spells_normalized(self, requested, expected_provider) -> None:
        """Index and equity symbols travel uppercased and stripped."""
        from schwab_mcp.quotes import get_quotes

        client = _unknown_client()
        get_quotes(client, [requested])

        assert client.call_count == 2, "validation passed: one market-hours + one quotes call"
        assert client.quotes_calls[0]["symbols"] == expected_provider

    @pytest.mark.parametrize(
        "requested,expected_provider",
        [
            ("AAPL 251127C200", "AAPL  251127C00200000"),
            ("AAPL_251127P200.5", "AAPL  251127P00200500"),
            ("AAPL251127C200", "AAPL  251127C00200000"),
            ("AAPL 261127C00200000", "AAPL  261127C00200000"),
            ("AAPL  261028C00345000", "AAPL  261028C00345000"),
        ],
        ids=[
            "compact-space",
            "compact-underscore-decimal",
            "compact-no-separator",
            "single-space-occ-strike",
            "canonical-occ",
        ],
    )
    def test_option_spells_canonicalized_to_occ(self, requested, expected_provider) -> None:
        """Contract compact spellings AND the canonical OCC form are
        accepted; the provider call always carries the canonical OCC
        symbol (the only form the provider quotes — live evidence)."""
        from schwab_mcp.quotes import get_quotes

        client = _unknown_client()
        get_quotes(client, [requested])

        assert client.call_count == 2, "validation passed: one market-hours + one quotes call"
        assert client.quotes_calls[0]["symbols"] == [expected_provider]


# =============================================================================
# Normalization and de-duplication (FR-001 edge cases)
# =============================================================================


class TestNormalizationAndDeduplication:
    """strip + uppercase, then de-duplicate; the limit applies to distinct
    instruments."""

    def test_duplicates_de_deduplicated_before_provider(self) -> None:
        """Case/whitespace duplicates collapse to one distinct symbol."""
        from schwab_mcp.quotes import get_quotes

        client = _synthetic_ok_client(["AAPL"])
        result = get_quotes(client, ["AAPL", " aapl ", "AAPL"])

        assert result["outcome"] == "ok"
        assert result["requested_count"] == 1
        assert client.quotes_calls[0]["symbols"] == ["AAPL"]

    def test_option_alias_spellings_de_deduplicated(self) -> None:
        """Two spellings of one contract are ONE distinct instrument."""
        from schwab_mcp.quotes import get_quotes

        client = _unknown_client()
        result = get_quotes(
            client, ["AAPL 251127C200", "AAPL  251127C00200000"]
        )

        assert result["requested_count"] == 1
        assert client.quotes_calls[0]["symbols"] == ["AAPL  251127C00200000"]

    def test_deduplication_applies_before_limit(self) -> None:
        """21 entries with 20 distinct instruments proceed (the limit
        counts distinct symbols)."""
        from schwab_mcp.quotes import get_quotes

        client = _synthetic_ok_client(SYNTH[:20])
        result = get_quotes(client, [*SYNTH[:20], "tst01"])

        assert result["outcome"] == "ok"
        assert result["requested_count"] == 20


# =============================================================================
# Symbol limit (FR-007)
# =============================================================================


class TestSymbolLimit:
    """> 20 distinct symbols -> ``validation_error`` / ``too_many_symbols``
    stating the limit; exactly 20 proceeds."""

    def test_over_limit_rejected_stating_the_limit(self) -> None:
        """21 distinct symbols are rejected before any upcall, and the
        error states the 20-symbol limit."""
        from schwab_mcp.quotes import get_quotes

        client = _synthetic_ok_client(SYNTH[:21])
        result = get_quotes(client, SYNTH[:21])

        assert result["outcome"] == "validation_error"
        assert result["detail"] == "too_many_symbols"
        assert result["retryable"] is False
        assert result["limit"] == 20, "the error must state the limit"
        assert result["requested_count"] == 21
        assert client.call_count == 0

    def test_exact_limit_proceeds(self) -> None:
        """Exactly 20 distinct symbols succeeds (edge case)."""
        from schwab_mcp.quotes import get_quotes

        client = _synthetic_ok_client(SYNTH[:20])
        result = get_quotes(client, SYNTH[:20])

        assert result["outcome"] == "ok"
        assert result["requested_count"] == 20
        assert len(result["quotes"]) == 20
        assert client.call_count == 2


# =============================================================================
# Wrong input types (tool-boundary errors)
# =============================================================================


class TestInputTypeError:
    """``symbols`` must be a string or list of strings; anything else is a
    tool-boundary ``TypeError`` (surfaced as MCP ``ToolError``)."""

    @pytest.mark.parametrize("symbols", [42, None, {"AAPL": 1}])
    def test_non_string_container_raises_type_error(self, symbols) -> None:
        from schwab_mcp.quotes import get_quotes

        with pytest.raises(TypeError):
            get_quotes(_unknown_client(), symbols)

    def test_non_string_entry_raises_type_error(self) -> None:
        from schwab_mcp.quotes import get_quotes

        with pytest.raises(TypeError):
            get_quotes(_unknown_client(), ["AAPL", 42])

    def test_tool_wrapper_converts_to_tool_error(self) -> None:
        """``get_quotes_tool`` converts TypeError into the MCP ToolError
        so the actionable message reaches the agent (D7)."""
        from mcp.server.mcpserver.exceptions import ToolError

        from schwab_mcp.quotes import get_quotes_tool

        with pytest.raises(ToolError):
            get_quotes_tool(_unknown_client(), 42)
