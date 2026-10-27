"""RED-phase audit-event tests for ``get_quotes`` (T007, US1).

TDD red-phase: ``schwab_mcp.quotes`` exposes the skeleton only, so every
test fails until T010 lands.

Pins the audit surface of contracts/mcp-tools.md §6 (pattern of
``options_chain_query_*``):

- ``quotes_query_start`` (outcome ``initiated``) on every invocation;
- ``quotes_query_failure`` classified ``validation`` / ``error`` /
  ``reauth`` / ``provider_unreachable`` on every failure path;
- no credentials, tokens, or account identifiers in any event or output
  (FR-010).
"""

from __future__ import annotations

import json

import pytest

from tests.unit.fixtures.quotes_payloads import (
    EQUITY_QUOTE_ENTRY,
    MARKET_HOURS_CLOSED_PAYLOAD,
)
from tests.unit.helpers import FakeQuotesClient, build_quote_entry

FAILURE_CLASSIFICATIONS = {"validation", "error", "reauth", "provider_unreachable"}


@pytest.fixture
def events(monkeypatch):
    """Record every ``auth_event`` emitted by the quotes module."""
    calls: list[tuple] = []

    def _record(event, outcome, detail=None):
        calls.append((event, outcome, detail))

    monkeypatch.setattr("schwab_mcp.quotes.auth_event", _record)
    return calls


# =============================================================================
# Start event
# =============================================================================


class TestStartEvent:
    """``quotes_query_start`` (initiated) heads every invocation."""

    def test_success_emits_start_first(self, events) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY})
        get_quotes(client, "AAPL")

        assert events[0][0] == "quotes_query_start"
        assert events[0][1] == "initiated"

    @pytest.mark.parametrize(
        "symbols,payload_kwargs",
        [
            ([], {}),
            (["BAD SYMBOL"], {}),
            (["AAPL"], {"quotes_status": 500}),
        ],
        ids=["empty", "malformed", "provider-down"],
    )
    def test_failure_paths_also_emit_start_first(self, events, symbols, payload_kwargs) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(
            quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY}, **payload_kwargs
        )
        get_quotes(client, symbols)

        assert events[0][0] == "quotes_query_start"
        assert events[0][1] == "initiated"

    def test_success_emits_no_failure_event(self, events) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY})
        get_quotes(client, "AAPL")

        names = [name for name, _outcome, _detail in events]
        assert "quotes_query_failure" not in names


# =============================================================================
# Failure classification (contract §6)
# =============================================================================


class TestFailureClassification:
    """Every failure path emits ``quotes_query_failure`` with a
    classification from {validation, error, reauth, provider_unreachable}."""

    def _failure(self, events):
        failures = [e for e in events if e[0] == "quotes_query_failure"]
        assert len(failures) == 1, f"expected exactly one failure event: {events}"
        return failures[0]

    @pytest.mark.parametrize(
        "symbols",
        [[], ["AAPL", "TOOLONGSYM"], [f"T{i:04d}" for i in range(1, 22)]],
        ids=["empty-list", "malformed", "too-many"],
    )
    def test_validation_failures_classified_validation(self, events, symbols) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY})
        get_quotes(client, symbols)

        name, outcome, detail = self._failure(events)
        assert name == "quotes_query_failure"
        assert outcome == "validation"

    def test_quote_unavailable_classified_error(self, events) -> None:
        """The source cannot quote a requested symbol -> ``error``."""
        from tests.unit.fixtures.quotes_payloads import UNKNOWN_SYMBOL_PAYLOAD

        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload=UNKNOWN_SYMBOL_PAYLOAD)
        get_quotes(client, "ZOMB")

        _name, outcome, _detail = self._failure(events)
        assert outcome == "error"

    @pytest.mark.parametrize("status", [500, 429], ids=["500", "429"])
    def test_provider_down_classified_provider_unreachable(self, events, status) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(
            quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY}, quotes_status=status
        )
        get_quotes(client, "AAPL")

        _name, outcome, _detail = self._failure(events)
        assert outcome == "provider_unreachable"

    def test_market_hours_failure_classified_provider_unreachable(self, events) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(
            quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY},
            market_hours_payload={},
        )
        get_quotes(client, "AAPL")

        _name, outcome, _detail = self._failure(events)
        assert outcome == "provider_unreachable"

    def test_reauth_classified_reauth(self, events) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(
            quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY}, quotes_status=401
        )
        get_quotes(client, "AAPL")

        _name, outcome, _detail = self._failure(events)
        assert outcome == "reauth"

    def test_failure_classification_is_from_the_documented_set(self, events) -> None:
        from tests.unit.fixtures.quotes_payloads import UNKNOWN_SYMBOL_PAYLOAD

        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload=UNKNOWN_SYMBOL_PAYLOAD)
        get_quotes(client, "ZOMB")

        for name, outcome, _detail in events:
            if name == "quotes_query_failure":
                assert outcome in FAILURE_CLASSIFICATIONS


# =============================================================================
# Credential safety (FR-010)
# =============================================================================


class TestNoSecretsInEventsOrOutput:
    """Neither audit events nor tool output carry credential/token or
    account-identifier material (FR-010)."""

    FAKE_SECRET = "should-not-leak-12345"

    def test_events_carry_no_secret_material(self, events) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY})
        result = get_quotes(client, "AAPL")

        for _name, _outcome, detail in events:
            if detail is not None:
                assert self.FAKE_SECRET not in detail
        assert self.FAKE_SECRET not in json.dumps(result)

    def test_output_carries_no_account_identifiers(self, events) -> None:
        """No account number/hash key may appear in the quotes output —
        the tool answers with market data only."""
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY})
        result = get_quotes(client, "AAPL")

        text = json.dumps(result).lower()
        for marker in ("accountnumber", "account_number", "account_hash", "token"):
            assert marker not in text

    def test_failure_output_carries_no_secret_material(self, events) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(
            quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY}, quotes_status=500
        )
        result = get_quotes(client, "AAPL")

        assert self.FAKE_SECRET not in json.dumps(result)
        for _name, _outcome, detail in events:
            if detail is not None:
                assert self.FAKE_SECRET not in detail
