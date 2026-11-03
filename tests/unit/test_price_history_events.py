"""RED-phase audit-event tests for ``get_price_history`` (T007, US1).

TDD red-phase: ``schwab_mcp.price_history`` exposes the skeleton only, so
every test fails until the GREEN implementation lands (T009/T010).

Pins the audit surface of contracts/mcp-tools.md §6 (pattern of
``quotes_query_*``):

- ``price_history_query_start`` (outcome ``initiated``) on every
  invocation;
- ``price_history_query_failure`` classified ``validation`` / ``error`` /
  ``reauth`` / ``provider_unreachable`` on every failure path;
- ``price_history_query_success`` (outcome ``ok``) on the ok path;
- symbol and selection are logged; no credentials, tokens, or account
  identifiers in any event or output (FR-011).

Classification assumptions pinned here (mirrors
``tests/unit/test_quotes_events.py`` plus the contracts/mcp-tools.md §3
error table):

- validation error envelope (``validation_error``) -> ``validation``;
- source returned no candles (``history_unavailable``) -> ``error``
  (the quotes precedent classifies "the source cannot serve the request"
  as ``error`` — see ``quote_unavailable`` there);
- 401/403 (``reauth_needed``) -> ``reauth``;
- 5xx/408/429/transport (``provider_unreachable``) ->
  ``provider_unreachable``.
"""

from __future__ import annotations

import json

import pytest

from tests.unit.fixtures import price_history_payloads as fx
from tests.unit.helpers import FakePriceHistoryClient

START_EVENT = "price_history_query_start"
FAILURE_EVENT = "price_history_query_failure"
SUCCESS_EVENT = "price_history_query_success"

FAILURE_CLASSIFICATIONS = {"validation", "error", "reauth", "provider_unreachable"}
ALLOWED_EVENT_NAMES = {START_EVENT, FAILURE_EVENT, SUCCESS_EVENT}
ALLOWED_OUTCOMES = {"initiated", "ok"} | FAILURE_CLASSIFICATIONS

CREDENTIAL_MARKERS = (
    "accountnumber",
    "account_number",
    "account_hash",
    "token",
    "refresh",
    "app_key",
    "app_secret",
    "secret",
    "authorization",
    "bearer",
    "password",
    "credential",
)


@pytest.fixture
def events(monkeypatch):
    """Record every ``auth_event`` emitted by the price-history module."""
    calls: list[tuple] = []

    def _record(event, outcome, detail=None):
        calls.append((event, outcome, detail))

    monkeypatch.setattr("schwab_mcp.price_history.auth_event", _record)
    return calls


# =============================================================================
# Start event
# =============================================================================


class TestStartEvent:
    """``price_history_query_start`` (initiated) heads every invocation."""

    def test_success_emits_start_first(self, events) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD)
        get_price_history(client, fx.SYMBOL)

        assert events[0][0] == START_EVENT
        assert events[0][1] == "initiated"

    @pytest.mark.parametrize(
        "symbol,call_kwargs,client_kwargs",
        [
            ("", {}, {}),
            ("BAD SYMBOL", {}, {}),
            (fx.OPTION_SYMBOL, {}, {}),
            (fx.SYMBOL, {"frequency": "13m"}, {}),
            (fx.SYMBOL, {"period": "10y"}, {}),
            (fx.SYMBOL, {"extended_hours": True}, {}),
            (fx.SYMBOL, {}, {"status": 500}),
        ],
        ids=[
            "missing",
            "malformed",
            "option-kind",
            "bad-frequency",
            "bad-period",
            "extended-hours",
            "provider-down",
        ],
    )
    def test_failure_paths_also_emit_start_first(
        self, events, symbol, call_kwargs, client_kwargs
    ) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD, **client_kwargs)
        get_price_history(client, symbol, **call_kwargs)

        assert events[0][0] == START_EVENT
        assert events[0][1] == "initiated"

    def test_success_emits_no_failure_event(self, events) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD)
        get_price_history(client, fx.SYMBOL)

        names = [name for name, _outcome, _detail in events]
        assert FAILURE_EVENT not in names


# =============================================================================
# Success event (contract §6 — price_history_query_success)
# =============================================================================


class TestSuccessEvent:
    """``price_history_query_success`` (ok) terminates the ok path."""

    def test_ok_path_emits_success_with_outcome_ok(self, events) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD)
        get_price_history(client, fx.SYMBOL)

        successes = [e for e in events if e[0] == SUCCESS_EVENT]
        assert len(successes) == 1, f"expected exactly one success event: {events}"
        assert successes[0][1] == "ok"

    def test_success_is_terminal_and_comes_after_start(self, events) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD)
        get_price_history(client, fx.SYMBOL)

        assert events[0][0] == START_EVENT
        assert events[-1][0] == SUCCESS_EVENT
        terminal = [e for e in events if e[0] in (SUCCESS_EVENT, FAILURE_EVENT)]
        assert len(terminal) == 1

    def test_failure_paths_emit_no_success_event(self, events) -> None:
        from schwab_mcp.price_history import get_price_history

        ok_client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD)
        down_client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD, status=500)
        empty_client = FakePriceHistoryClient(payload=fx.EMPTY_PAYLOAD)

        get_price_history(ok_client, fx.OPTION_SYMBOL)
        get_price_history(down_client, fx.SYMBOL)
        get_price_history(empty_client, fx.NO_HISTORY_SYMBOL)

        names = [name for name, _outcome, _detail in events]
        assert SUCCESS_EVENT not in names


# =============================================================================
# Failure classification (contract §6 / §3 error table)
# =============================================================================


class TestFailureClassification:
    """Every failure path emits ``price_history_query_failure`` with a
    classification from {validation, error, reauth, provider_unreachable}."""

    def _failure(self, events):
        failures = [e for e in events if e[0] == FAILURE_EVENT]
        assert len(failures) == 1, f"expected exactly one failure event: {events}"
        return failures[0]

    @pytest.mark.parametrize(
        "symbol,call_kwargs",
        [
            ("", {}),
            ("BAD SYMBOL", {}),
            (fx.OPTION_SYMBOL, {}),
            (fx.SYMBOL, {"frequency": "13m"}),
            (fx.SYMBOL, {"period": "10y"}),
            (fx.SYMBOL, {"extended_hours": True}),
        ],
        ids=[
            "missing",
            "malformed",
            "option-kind",
            "bad-frequency",
            "bad-period",
            "extended-hours",
        ],
    )
    def test_validation_failures_classified_validation(
        self, events, symbol, call_kwargs
    ) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD)
        get_price_history(client, symbol, **call_kwargs)

        name, outcome, _detail = self._failure(events)
        assert name == FAILURE_EVENT
        assert outcome == "validation"

    def test_no_candles_classified_error(self, events) -> None:
        """The source returns no candles for a valid symbol -> ``error``
        (quotes precedent: ``quote_unavailable`` is classified ``error``)."""
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.EMPTY_PAYLOAD)
        get_price_history(client, fx.NO_HISTORY_SYMBOL)

        _name, outcome, _detail = self._failure(events)
        assert outcome == "error"

    @pytest.mark.parametrize(
        "status", [500, 502, 408, 429], ids=["500", "502", "408", "429"]
    )
    def test_provider_down_classified_provider_unreachable(
        self, events, status
    ) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD, status=status)
        get_price_history(client, fx.SYMBOL)

        _name, outcome, _detail = self._failure(events)
        assert outcome == "provider_unreachable"

    def test_transport_error_classified_provider_unreachable(self, events) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(error=ConnectionError("network down"))
        get_price_history(client, fx.SYMBOL)

        _name, outcome, _detail = self._failure(events)
        assert outcome == "provider_unreachable"

    @pytest.mark.parametrize("status", [401, 403], ids=["401", "403"])
    def test_reauth_classified_reauth(self, events, status) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD, status=status)
        get_price_history(client, fx.SYMBOL)

        _name, outcome, _detail = self._failure(events)
        assert outcome == "reauth"

    def test_failure_classification_is_from_the_documented_set(self, events) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.EMPTY_PAYLOAD)
        get_price_history(client, fx.NO_HISTORY_SYMBOL)

        for name, outcome, _detail in events:
            if name == FAILURE_EVENT:
                assert outcome in FAILURE_CLASSIFICATIONS


# =============================================================================
# Symbol and selection are logged (contract §6)
# =============================================================================


class TestSymbolAndSelectionLogged:
    """contract §6: 'symbol and selection are logged'."""

    def test_events_log_the_symbol_and_the_selection(self, events) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD)
        get_price_history(client, fx.SYMBOL, frequency="daily", period="1m")

        text = " ".join(detail for _name, _outcome, detail in events if detail)
        text = text.lower()
        assert fx.SYMBOL.lower() in text
        assert "daily" in text
        assert "1m" in text


# =============================================================================
# Credential safety (FR-011)
# =============================================================================


class TestNoSecretsInEventsOrOutput:
    """Neither audit events nor tool output carry credential/token or
    account-identifier material (FR-011)."""

    FAKE_SECRET = "should-not-leak-12345"

    def test_events_carry_no_secret_material(self, events) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD)
        result = get_price_history(client, fx.SYMBOL)

        for _name, _outcome, detail in events:
            if detail is not None:
                assert self.FAKE_SECRET not in detail
        assert self.FAKE_SECRET not in json.dumps(result)

    def test_event_fields_carry_only_symbol_selection_classification_data(
        self, events
    ) -> None:
        """Event names, outcomes, and details stay inside the
        symbol/selection/classification vocabulary (contract §6)."""
        from schwab_mcp.price_history import get_price_history

        ok_client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD)
        get_price_history(ok_client, fx.SYMBOL, frequency="daily", period="1m")
        down_client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD, status=500)
        get_price_history(down_client, fx.SYMBOL)
        validation_client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD)
        get_price_history(validation_client, fx.OPTION_SYMBOL)

        assert events, "expected at least one audit event"
        for name, outcome, detail in events:
            assert name in ALLOWED_EVENT_NAMES
            assert outcome in ALLOWED_OUTCOMES
            if detail is not None:
                lowered = detail.lower()
                for marker in CREDENTIAL_MARKERS:
                    assert marker not in lowered

    def test_output_carries_no_account_identifiers(self, events) -> None:
        """No account number/hash key may appear in the price-history
        output — the tool answers with market data only."""
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD)
        result = get_price_history(client, fx.SYMBOL)

        text = json.dumps(result).lower()
        for marker in ("accountnumber", "account_number", "account_hash", "token"):
            assert marker not in text

    def test_failure_output_and_events_carry_no_secret_material(self, events) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD, status=500)
        result = get_price_history(client, fx.SYMBOL)

        assert self.FAKE_SECRET not in json.dumps(result)
        for _name, _outcome, detail in events:
            if detail is not None:
                assert self.FAKE_SECRET not in detail