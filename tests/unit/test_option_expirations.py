"""Unit tests for the curated expiration-chain mapping (feature 012, T003).

TDD red-phase suite: ``schwab_mcp.options_chain`` does not expose
``build_expiration_result`` yet, so every test fails with ``ImportError``
until T006 lands.

Covers (from tasks.md T003)
---------------------------
- entry fields pass through unmodified: ``expiration_date`` (provider
  ``expirationDate``), ``settlement_type`` (provider ``settlementType``);
- ``dte`` is calendar days computed locally from today — the provider's
  ``daysToExpiration`` is NEVER reused (research R4);
- explicit ``null`` for missing provider fields — values are never
  invented (research R6); unparseable dates keep the entry with a null
  ``dte`` (never a silent drop);
- ascending order by ``expiration_date``; same-date entries kept as
  separate rows distinguished by ``settlement_type`` (data-model §2
  identity rule — never merged or deduplicated).

References
----------
- specs/012-option-expiration-list/data-model.md §2 (result schema)
- specs/012-option-expiration-list/research.md (R2, R4, R6)
- tests/unit/fixtures/expiration_chain_payloads.py (pinned provider shape)
"""

from __future__ import annotations

from datetime import date

import pytest

from schwab_mcp.options_chain import OptionChainQuery, build_expiration_result
from tests.unit.fixtures.expiration_chain_payloads import (
    CAPTURE_DATE,
    EXPIRATION_CHAIN_PAYLOAD,
)
from tests.unit.helpers import (
    FakeExpirationClient,
    build_expiration_chain_payload,
    chain_expiry_date,
)

TODAY = date(2026, 11, 3)
"""Fixed "today" for deterministic DTE assertions (the T002 capture date)."""


def _query(symbol: str = "TEST", dte_max: int | None = None) -> OptionChainQuery:
    return OptionChainQuery(symbol=symbol, dte_max=dte_max)


# =============================================================================
# Curated field mapping (data-model §2)
# =============================================================================


class TestCuratedFieldMapping:
    """Each curated entry carries exactly the three curated fields."""

    def test_entries_carry_exactly_the_curated_fields(self) -> None:
        payload = build_expiration_chain_payload(
            [("2026-11-06", 3, "C"), ("2026-11-13", 10, "C")]
        )
        result = build_expiration_result(payload, _query(), TODAY)
        for entry in result["expirations"]:
            assert set(entry) == {"expiration_date", "dte", "settlement_type"}

    def test_expiration_date_passes_through_unmodified(self) -> None:
        payload = build_expiration_chain_payload([("2026-11-06", 3, "C")])
        result = build_expiration_result(payload, _query(), TODAY)
        assert result["expirations"][0]["expiration_date"] == "2026-11-06"

    def test_settlement_type_passes_through_unmodified(self) -> None:
        payload = build_expiration_chain_payload([("2026-11-06", 3, "A")])
        result = build_expiration_result(payload, _query(), TODAY)
        assert result["expirations"][0]["settlement_type"] == "A"

    def test_settlement_type_b_passes_through_unmodified(self) -> None:
        """Observed live provider value (bug ``settlement-type-a``): a
        letter beyond the documented ``C``/``P``/``A`` set passes through
        verbatim — never dropped, never rewritten."""
        payload = build_expiration_chain_payload([("2026-11-20", 17, "B")])
        result = build_expiration_result(payload, _query(), TODAY)
        assert result["expirations"][0]["settlement_type"] == "B"

    def test_dte_is_calendar_days_from_today_not_provider_value(self) -> None:
        """The provider day count (here deliberately 999) is ignored (R4)."""
        payload = build_expiration_chain_payload([("2026-11-13", 999, "C")])
        result = build_expiration_result(payload, _query(), TODAY)
        assert result["expirations"][0]["dte"] == (
            date(2026, 11, 13) - TODAY
        ).days == 10

    def test_dte_ignores_provider_trading_day_count(self) -> None:
        """A provider count that differs from calendar days (e.g. 8 trading
        days) never changes the curated ``dte`` (research R4)."""
        payload = build_expiration_chain_payload([("2026-11-13", 8, "C")])
        result = build_expiration_result(payload, _query(), TODAY)
        assert result["expirations"][0]["dte"] == 10


# =============================================================================
# Missing fields — explicit null, never invented (research R6)
# =============================================================================


class TestMissingFields:
    """Absent provider fields surface as explicit ``null`` values."""

    def test_missing_settlement_type_yields_explicit_null(self) -> None:
        payload = build_expiration_chain_payload([("2026-11-06", 3, None)])
        result = build_expiration_result(payload, _query(), TODAY)
        assert result["expirations"][0]["settlement_type"] is None

    def test_all_fields_missing_yield_all_nulls_kept_in_output(self) -> None:
        """An entry without any provider field is kept with three explicit
        nulls — never dropped, never invented (research R6)."""
        payload = build_expiration_chain_payload([(None, None, None)])
        result = build_expiration_result(payload, _query(), TODAY)
        assert result["expirations"] == [
            {
                "expiration_date": None,
                "dte": None,
                "settlement_type": None,
            }
        ]

    def test_unparseable_date_keeps_entry_with_null_dte(self) -> None:
        """An unparseable ``expirationDate`` passes through unmodified and
        yields a null ``dte`` — the entry is NOT silently dropped (R6)."""
        payload = build_expiration_chain_payload([("not-a-date", 3, "C")])
        result = build_expiration_result(payload, _query(), TODAY)
        assert result["expirations"] == [
            {
                "expiration_date": "not-a-date",
                "dte": None,
                "settlement_type": "C",
            }
        ]


# =============================================================================
# Ordering and identity (data-model §2)
# =============================================================================


class TestOrderingAndIdentity:
    """Ascending dates; same-date rows are never merged."""

    def test_entries_sorted_ascending_by_expiration_date(self) -> None:
        payload = build_expiration_chain_payload(
            [("2026-12-18", 45, "C"), ("2026-11-06", 3, "C"), ("2026-11-20", 17, "C")]
        )
        result = build_expiration_result(payload, _query(), TODAY)
        assert [e["expiration_date"] for e in result["expirations"]] == [
            "2026-11-06",
            "2026-11-20",
            "2026-12-18",
        ]

    def test_same_date_entries_kept_as_separate_rows(self) -> None:
        """SPX-style AM/PM settlement on the same date: two rows, never
        merged (clarification 2026-11-03, Q2 option B)."""
        payload = build_expiration_chain_payload(
            [("2026-11-20", 17, "A"), ("2026-11-20", 17, "P")]
        )
        result = build_expiration_result(payload, _query(), TODAY)
        entries = result["expirations"]
        assert len(entries) == 2
        assert [e["settlement_type"] for e in entries] == ["A", "P"]
        assert all(e["expiration_date"] == "2026-11-20" for e in entries)

    def test_same_date_ties_keep_provider_order(self) -> None:
        payload = build_expiration_chain_payload(
            [("2026-11-20", 17, "P"), ("2026-11-20", 17, "A")]
        )
        result = build_expiration_result(payload, _query(), TODAY)
        assert [e["settlement_type"] for e in result["expirations"]] == ["P", "A"]

    def test_identical_rows_are_never_deduplicated(self) -> None:
        """Identity rule: entries are kept exactly as returned by the
        provider (data-model §2)."""
        payload = build_expiration_chain_payload(
            [("2026-11-20", 17, "C"), ("2026-11-20", 17, "C")]
        )
        result = build_expiration_result(payload, _query(), TODAY)
        assert len(result["expirations"]) == 2


# =============================================================================
# Pinned provider shape (T002 fixture — research R2)
# =============================================================================


class TestPinnedFixtureShape:
    """The live-captured AAPL payload maps cleanly with the recorded field names."""

    def test_pinned_payload_entries_map_with_local_dte(self) -> None:
        query = _query(symbol="AAPL", dte_max=365)
        result = build_expiration_result(
            EXPIRATION_CHAIN_PAYLOAD, query, date.fromisoformat(CAPTURE_DATE)
        )
        entries = result["expirations"]
        # Live capture 2026-11-03: 18 entries within dte_max=365 (dte 1..318).
        assert [e["expiration_date"] for e in entries] == [
            "2026-11-04",
            "2026-11-06",
            "2026-11-09",
            "2026-11-11",
            "2026-11-13",
            "2026-11-16",
            "2026-11-18",
            "2026-11-20",
            "2026-11-27",
            "2026-12-04",
            "2026-12-11",
            "2026-12-18",
            "2027-01-15",
            "2027-02-19",
            "2027-03-19",
            "2027-04-16",
            "2027-06-17",
            "2027-09-17",
        ]
        assert [e["dte"] for e in entries] == [
            1, 3, 6, 8, 10, 13, 15, 17, 24, 31, 38, 45,
            73, 108, 136, 164, 226, 318,
        ]
        assert all(e["settlement_type"] == "P" for e in entries)

    def test_pinned_payload_default_ceiling_excludes_beyond_60(self) -> None:
        """The live payload's 12 entries beyond the 60-day ceiling are
        excluded by the default window (dte 73..808)."""
        result = build_expiration_result(
            EXPIRATION_CHAIN_PAYLOAD, _query(symbol="AAPL"), date.fromisoformat(CAPTURE_DATE)
        )
        assert result["outcome"] == "ok"
        assert result["expiration_count"] == 12
        assert max(e["dte"] for e in result["expirations"]) == 45


# =============================================================================
# DTE ceiling (US2 — data-model §1, clarification 2026-11-03 Q1 option A)
# =============================================================================


class TestDteCeiling:
    """``dte_max`` behaves exactly like ``get_option_chain``."""

    def test_dte_max_30_excludes_entries_beyond_the_ceiling(self) -> None:
        payload = build_expiration_chain_payload(
            [
                (chain_expiry_date(7), 7, "C"),
                (chain_expiry_date(30), 30, "C"),
                (chain_expiry_date(70), 70, "C"),
            ]
        )
        result = build_expiration_result(payload, _query(dte_max=30), TODAY)
        assert [e["dte"] for e in result["expirations"]] == [7, 30]
        assert all(e["dte"] <= 30 for e in result["expirations"])

    def test_dte_max_365_accepted_without_hard_upper_limit(self) -> None:
        """``dte_max=365`` replaces the default — no cap beyond it."""
        payload = build_expiration_chain_payload(
            [
                (chain_expiry_date(7), 7, "C"),
                (chain_expiry_date(200), 200, "C"),
                (chain_expiry_date(360), 360, "C"),
            ]
        )
        result = build_expiration_result(payload, _query(dte_max=365), TODAY)
        assert [e["dte"] for e in result["expirations"]] == [7, 200, 360]
        assert result["filters"]["dte_max_effective"] == 365

    def test_default_ceiling_is_60_when_dte_max_is_none(self) -> None:
        payload = build_expiration_chain_payload([(chain_expiry_date(70), 70, "C")])
        result = build_expiration_result(payload, _query(), TODAY)
        assert result["outcome"] == "no_expirations_in_range"
        assert result["filters"] == {
            "dte_max_requested": None,
            "dte_max_effective": 60,
        }


# =============================================================================
# Validation errors before any upcall (US2 — contracts/mcp-tools.md §4)
# =============================================================================


class TestValidationBeforeUpcall:
    """Every validation failure raises before any provider call."""

    @pytest.mark.parametrize("dte_max", [0, -1])
    def test_dte_max_below_one_raises_value_error(self, dte_max) -> None:
        from schwab_mcp.options_chain import get_option_expiration_chain

        client = FakeExpirationClient(build_expiration_chain_payload([]))
        with pytest.raises(ValueError) as excinfo:
            get_option_expiration_chain(client, "TEST", dte_max=dte_max)
        message = str(excinfo.value)
        assert "dte_max" in message and ">= 1" in message
        assert client.call_count == 0

    @pytest.mark.parametrize("dte_max", ["30", True, False, 2.5])
    def test_dte_max_wrong_type_raises_type_error(self, dte_max) -> None:
        """``dte_max`` must be int or None — bool is not int (008 semantics)."""
        from schwab_mcp.options_chain import get_option_expiration_chain

        client = FakeExpirationClient(build_expiration_chain_payload([]))
        with pytest.raises(TypeError) as excinfo:
            get_option_expiration_chain(client, "TEST", dte_max=dte_max)
        assert "dte_max" in str(excinfo.value)
        assert client.call_count == 0

    @pytest.mark.parametrize("symbol", ["", "   ", "\t", "BRK B", "BAD SYMBOL"])
    def test_invalid_symbols_raise_value_error_before_upcall(self, symbol) -> None:
        from schwab_mcp.options_chain import get_option_expiration_chain

        client = FakeExpirationClient(build_expiration_chain_payload([]))
        with pytest.raises(ValueError) as excinfo:
            get_option_expiration_chain(client, symbol)
        assert "symbol" in str(excinfo.value)
        assert client.call_count == 0

    def test_unknown_parameter_names_the_parameter(self) -> None:
        """``max_strikes`` is a ``get_option_chain`` concern and is rejected
        by the fixed signature (contracts/mcp-tools.md §4)."""
        from schwab_mcp.options_chain import (
            get_option_expiration_chain,
            get_option_expiration_chain_tool,
        )

        client = FakeExpirationClient(build_expiration_chain_payload([]))
        with pytest.raises(TypeError) as excinfo:
            get_option_expiration_chain(client, "TEST", max_strikes=5)
        assert "max_strikes" in str(excinfo.value)
        assert client.call_count == 0

        with pytest.raises(TypeError) as tool_excinfo:
            get_option_expiration_chain_tool(client, "TEST", max_strikes=5)
        assert "max_strikes" in str(tool_excinfo.value)
        assert client.call_count == 0


# =============================================================================
# Tool boundary: ToolError conversion (T020 — contracts/mcp-tools.md §4)
# =============================================================================


class TestToolWrapperToolErrorConversion:
    """The MCP tool wrapper converts domain validation errors into
    ``ToolError`` with the actionable message — never a raw stack trace
    (US1 AC3, contracts/mcp-tools.md §4)."""

    @pytest.mark.parametrize(
        ("kwargs", "symbol"),
        [({"dte_max": 0}, "TEST"), ({}, ""), ({}, "   ")],
        ids=["dte_max=0", "empty-symbol", "whitespace-symbol"],
    )
    def test_validation_errors_become_tool_error(self, kwargs, symbol) -> None:
        from mcp.server.mcpserver.exceptions import ToolError

        from schwab_mcp.options_chain import get_option_expiration_chain_tool

        client = FakeExpirationClient(build_expiration_chain_payload([]))
        with pytest.raises(ToolError) as excinfo:
            get_option_expiration_chain_tool(client, symbol, **kwargs)
        # The actionable message names the violated parameter and constraint.
        message = str(excinfo.value)
        if kwargs:
            assert "dte_max" in message and ">= 1" in message
        else:
            assert "symbol" in message
        # No upcall before validation (FR-007).
        assert client.call_count == 0
        # The original error is preserved as the cause.
        assert excinfo.value.__cause__ is not None

    def test_wrong_type_dte_max_becomes_tool_error(self) -> None:
        from mcp.server.mcpserver.exceptions import ToolError

        from schwab_mcp.options_chain import get_option_expiration_chain_tool

        client = FakeExpirationClient(build_expiration_chain_payload([]))
        with pytest.raises(ToolError) as excinfo:
            get_option_expiration_chain_tool(client, "TEST", dte_max="30")
        assert "dte_max" in str(excinfo.value)
        assert client.call_count == 0