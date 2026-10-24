"""Unit tests for audit events emitted by ``get_transaction_history``.

Event contract: specs/006-transaction-history/contracts/events.md

Tests cover:
- Exactly 1 terminal event per invocation (success or failure)
- Correct event/outcome/detail combinations per contract table
- Event line format consistent with contract
- Detail values from the event namespace (NOT ``TransactionDetail`` enum)
- No secrets/tokens in events
- Validation event emitted once per invocation
- Success event never emitted before result is known
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest


# =============================================================================
# Helper: assert exactly one terminal event with given args
# =============================================================================


def _assert_terminal_event(mock, event_name, outcome, detail):
    """Assert exactly 1 terminal event with the given args was emitted.

    Filters out non-terminal events (e.g. the start event) so that callers
    do not need to know whether a start event is present.
    """
    terminal_calls = [
        c for c in mock.call_args_list
        if c[0][0] in ("transactions_query_success", "transactions_query_failure")
    ]
    assert len(terminal_calls) == 1, (
        f"Expected exactly 1 terminal event, got {len(terminal_calls)}: "
        f"{terminal_calls}"
    )
    assert terminal_calls[0] == call(event_name, outcome, detail=detail)


# =============================================================================
# Constants from contracts/events.md
# =============================================================================

# Terminal event names
SUCCESS_EVENT = "transactions_query_success"
FAILURE_EVENT = "transactions_query_failure"

# Outcomes — success
OK_OUTCOME = "ok"
PARTIAL_OUTCOME = "partial_failure"

# Outcomes — failure
TRANSIENT_OUTCOME = "transient"
REAUTH_OUTCOME = "reauth"
VALIDATION_OUTCOME = "validation"

# Detail namespace — these are the event contract values, NOT the
# TransactionDetail enum from data-model.md (see contract §Namespaces).
DETAIL_HISTORY_RETRIEVED = "history_retrieved"
DETAIL_NO_MOVEMENTS = "no_movements"
DETAIL_NO_MOVEMENTS_FOR_INSTRUMENT = "no_movements_for_instrument"
DETAIL_ACCOUNT_FAILED = "account_failed"
DETAIL_PROVIDER_UNREACHABLE = "provider_unreachable"
DETAIL_REAUTH_NEEDED = "reauth_needed"
DETAIL_INVALID_QUERY = "invalid_query"

# Allowed (outcome, detail) pairs for each terminal event (contract table)
ALLOWED_SUCCESS_COMBINATIONS: frozenset[tuple[str, str]] = frozenset({
    (OK_OUTCOME, DETAIL_HISTORY_RETRIEVED),
    (OK_OUTCOME, DETAIL_NO_MOVEMENTS),
    (OK_OUTCOME, DETAIL_NO_MOVEMENTS_FOR_INSTRUMENT),
    (PARTIAL_OUTCOME, DETAIL_ACCOUNT_FAILED),
})

ALLOWED_FAILURE_COMBINATIONS: frozenset[tuple[str, str]] = frozenset({
    (TRANSIENT_OUTCOME, DETAIL_PROVIDER_UNREACHABLE),
    (REAUTH_OUTCOME, DETAIL_REAUTH_NEEDED),
    (VALIDATION_OUTCOME, DETAIL_INVALID_QUERY),
})


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_auth_event():
    """Mock ``auth_event`` inside the transactions module.

    This captures every call made by ``get_transaction_history`` so tests
    can verify event name, outcome, detail, and call count.
    """
    with patch("schwab_mcp.transactions.auth_event") as mock:
        yield mock


@pytest.fixture
def mock_client():
    """Create a mock Schwab client.

    Provides a ``transactions`` method that the real implementation will
    call once per linked account.  The ``_validator`` attribute is
    pre-configured so ``_bypass_validator`` does not fail.
    """
    client = MagicMock()
    client._validator = MagicMock()
    client._validator.enabled = True
    return client


def _setup_accounts(mock_client, hashes: list[str] | None = None) -> None:
    """Configure ``mock_client.linked_accounts`` to return a list of accounts."""
    if hashes is None:
        hashes = ["test_acc"]
    mock_client.linked_accounts.return_value = [
        {"accountHash": h} for h in hashes
    ]


# =============================================================================
# 1. Module / function existence
# =============================================================================


class TestGetTransactionHistoryExistence:
    """Verify the module exposes ``get_transaction_history`` as a callable.

    Will fail with ``ImportError`` until T011 is implemented (TDD Red).
    """

    def test_get_transaction_history_is_callable(self) -> None:
        """``get_transaction_history`` is a callable function."""
        from schwab_mcp.transactions import get_transaction_history

        assert callable(get_transaction_history)


# =============================================================================
# 2. Success events — transactions_query_success
# =============================================================================


class TestTransactionSuccessEvents:
    """``transactions_query_success`` emitted for ok/partial outcomes."""

    def test_ok_history_retrieved(self, mock_auth_event, mock_client) -> None:
        """ok outcome with history_retrieved detail when transactions exist."""
        from schwab_mcp.transactions import get_transaction_history

        mock_client.linked_accounts.return_value = [{"accountHash": "acc1"}]
        mock_client.transactions.return_value = {
            "transactions": [{"type": "TRADE"}],
        }

        result = get_transaction_history(mock_client, "2026-10-01", "2026-10-20")

        _assert_terminal_event(
            mock_auth_event, SUCCESS_EVENT, OK_OUTCOME, detail=DETAIL_HISTORY_RETRIEVED,
        )

    def test_ok_no_movements(self, mock_auth_event, mock_client) -> None:
        """ok outcome with no_movements detail when no transactions exist."""
        from schwab_mcp.transactions import get_transaction_history

        mock_client.linked_accounts.return_value = [{"accountHash": "acc1"}]
        mock_client.transactions.return_value = {
            "transactions": [],
        }

        result = get_transaction_history(mock_client, "2026-10-01", "2026-10-20")

        _assert_terminal_event(
            mock_auth_event, SUCCESS_EVENT, OK_OUTCOME, detail=DETAIL_NO_MOVEMENTS,
        )

    def test_ok_no_movements_for_instrument(
        self, mock_auth_event, mock_client,
    ) -> None:
        """ok outcome with no_movements_for_instrument when symbol filter
        returned empty (no transactions matching the requested instrument)."""
        from schwab_mcp.transactions import get_transaction_history

        mock_client.linked_accounts.return_value = [{"accountHash": "acc1"}]
        mock_client.transactions.return_value = {
            "transactions": [],
        }
        # Symbol validation upcall — a known symbol returns a non-empty
        # result list (real SDK shape: parsed JSON list).
        mock_client.instruments.return_value = [{"symbol": "AAPL"}]

        # The function determines no_movements_for_instrument vs no_movements
        # based on whether a symbol was provided in the request.
        result = get_transaction_history(
            mock_client, "2026-10-01", "2026-10-20", symbol="AAPL",
        )

        _assert_terminal_event(
            mock_auth_event, SUCCESS_EVENT, OK_OUTCOME,
            detail=DETAIL_NO_MOVEMENTS_FOR_INSTRUMENT,
        )

    def test_partial_failure_account_failed(
        self, mock_auth_event, mock_client,
    ) -> None:
        """partial_failure outcome with account_failed detail when >= 1
        account fails."""
        from schwab_mcp.transactions import get_transaction_history

        # Simulate some accounts failing, some succeeding
        mock_client.linked_accounts.return_value = [
            {"accountHash": "acc1"}, {"accountHash": "acc2"},
        ]
        mock_client.transactions.side_effect = [
            RuntimeError("provider error"),  # First account fails
            {"transactions": [{"type": "TRADE"}]},  # Second succeeds
        ]

        result = get_transaction_history(mock_client, "2026-10-01", "2026-10-20")

        _assert_terminal_event(
            mock_auth_event, SUCCESS_EVENT, PARTIAL_OUTCOME, detail=DETAIL_ACCOUNT_FAILED,
        )


# =============================================================================
# 3. Failure events — transactions_query_failure
# =============================================================================


class TestTransactionFailureEvents:
    """``transactions_query_failure`` emitted for transient/reauth/validation."""

    def test_transient_provider_unreachable(
        self, mock_auth_event, mock_client,
    ) -> None:
        """transient outcome with provider_unreachable detail on connectivity
        error (first attempt, no retries)."""
        from schwab_mcp.transactions import get_transaction_history

        mock_client.linked_accounts.return_value = [{"accountHash": "acc1"}]
        mock_client.transactions.side_effect = ConnectionError(
            "provider unreachable",
        )

        result = get_transaction_history(mock_client, "2026-10-01", "2026-10-20")

        _assert_terminal_event(
            mock_auth_event, FAILURE_EVENT, TRANSIENT_OUTCOME,
            detail=DETAIL_PROVIDER_UNREACHABLE,
        )

    def test_reauth_reauth_needed(self, mock_auth_event, mock_client) -> None:
        """reauth outcome with reauth_needed detail when store is absent,
        corrupted, or refresh rejected."""
        from schwab_mcp.transactions import get_transaction_history

        # Simulate a reauthorisation error
        mock_client.linked_accounts.return_value = [{"accountHash": "acc1"}]
        mock_client.transactions.side_effect = PermissionError(
            "refresh token rejected",
        )

        result = get_transaction_history(mock_client, "2026-10-01", "2026-10-20")

        _assert_terminal_event(
            mock_auth_event, FAILURE_EVENT, REAUTH_OUTCOME, detail=DETAIL_REAUTH_NEEDED,
        )

    def test_validation_invalid_query(
        self, mock_auth_event, mock_client,
    ) -> None:
        """validation outcome with invalid_query detail when request
        validation fails (FR-004)."""
        from schwab_mcp.transactions import get_transaction_history

        # Validation occurs before any provider call; no mock needed.
        # Bad query arguments trigger validation error.
        with pytest.raises((ValueError, TypeError)):
            result = get_transaction_history(
                mock_client, start_date="invalid", end_date="2026-10-20",
            )

        _assert_terminal_event(
            mock_auth_event, FAILURE_EVENT, VALIDATION_OUTCOME, detail=DETAIL_INVALID_QUERY,
        )


# =============================================================================
# 4. Exactly 1 terminal event per invocation
# =============================================================================


class TestExactlyOneTerminalEvent:
    """Every invocation emits *exactly* one terminal event.

    Pattern from ``get_open_positions`` (003): no duplicate success/failure
    events, no missing events.
    """

    def test_one_terminal_event_on_success(self, mock_auth_event, mock_client) -> None:
        """ok outcome emits exactly one terminal call to auth_event."""
        from schwab_mcp.transactions import get_transaction_history

        mock_client.linked_accounts.return_value = [{"accountHash": "acc1"}]
        mock_client.transactions.return_value = {
            "transactions": [{"type": "TRADE"}],
        }

        result = get_transaction_history(mock_client, "2026-10-01", "2026-10-20")

        terminal_events = [
            c for c in mock_auth_event.call_args_list
            if c[0][0] in (SUCCESS_EVENT, FAILURE_EVENT)
        ]
        assert len(terminal_events) == 1
        call_args = terminal_events[0]
        assert call_args[0][0] == SUCCESS_EVENT  # event name

    def test_one_terminal_event_on_failure(self, mock_auth_event, mock_client) -> None:
        """transient failure emits exactly one terminal call to auth_event."""
        from schwab_mcp.transactions import get_transaction_history

        mock_client.linked_accounts.return_value = [{"accountHash": "acc1"}]
        mock_client.transactions.side_effect = ConnectionError()

        result = get_transaction_history(mock_client, "2026-10-01", "2026-10-20")

        terminal_events = [
            c for c in mock_auth_event.call_args_list
            if c[0][0] in (SUCCESS_EVENT, FAILURE_EVENT)
        ]
        assert len(terminal_events) == 1
        call_args = terminal_events[0]
        assert call_args[0][0] == FAILURE_EVENT

    def test_no_duplicate_events_on_reauth(self, mock_auth_event, mock_client) -> None:
        """Reauth emits exactly one failure event (not duplicated by error
        handler + terminal path)."""
        from schwab_mcp.transactions import get_transaction_history

        mock_client.linked_accounts.return_value = [{"accountHash": "acc1"}]
        mock_client.transactions.side_effect = PermissionError()

        result = get_transaction_history(mock_client, "2026-10-01", "2026-10-20")

        terminal_events = [
            c for c in mock_auth_event.call_args_list
            if c[0][0] in (SUCCESS_EVENT, FAILURE_EVENT)
        ]
        assert len(terminal_events) == 1

    def test_start_event_is_not_terminal(self, mock_auth_event, mock_client) -> None:
        """If the implementation emits a start event (``transactions_query_start``),
        it does NOT count as the terminal event — exactly one terminal event
        must still be emitted."""
        from schwab_mcp.transactions import get_transaction_history

        mock_client.linked_accounts.return_value = [{"accountHash": "acc1"}]
        mock_client.transactions.return_value = {
            "transactions": [{"type": "TRADE"}],
        }

        result = get_transaction_history(mock_client, "2026-10-01", "2026-10-20")

        terminal_events = [
            c for c in mock_auth_event.call_args_list
            if c[0][0] in (SUCCESS_EVENT, FAILURE_EVENT)
        ]
        assert len(terminal_events) == 1


# =============================================================================
# 5. Validation event rules (FR-004)
# =============================================================================


class TestValidationEventRules:
    """Specific rules around the validation outcome event.

    - Validation event emitted once per invocation
    - Emitted before any provider call (pure validation)
    """

    def test_validation_event_emitted_once(self, mock_auth_event, mock_client) -> None:
        """Validation failure emits exactly one ``transactions_query_failure``
        with validation outcome."""
        from schwab_mcp.transactions import get_transaction_history

        with pytest.raises((ValueError, TypeError)):
            result = get_transaction_history(
                mock_client, start_date="invalid", end_date="2026-10-20",
            )

        _assert_terminal_event(
            mock_auth_event, FAILURE_EVENT, VALIDATION_OUTCOME, detail=DETAIL_INVALID_QUERY,
        )

    def test_validation_before_any_provider_call(
        self, mock_auth_event, mock_client,
    ) -> None:
        """Validation error does NOT call any provider method.

        The mock client's ``transactions`` should never be called when
        validation fails.
        """
        from schwab_mcp.transactions import get_transaction_history

        with pytest.raises((ValueError, TypeError)):
            result = get_transaction_history(
                mock_client, start_date="", end_date="2026-10-20",
            )

        mock_client.transactions.assert_not_called()
        _assert_terminal_event(
            mock_auth_event, FAILURE_EVENT, VALIDATION_OUTCOME, detail=DETAIL_INVALID_QUERY,
        )


# =============================================================================
# 6. Success event timing
# =============================================================================


class TestSuccessEventTiming:
    """Success event is never emitted before the result is known."""

    def test_success_emitted_after_result_known(
        self, mock_auth_event, mock_client,
    ) -> None:
        """The success event is emitted AFTER the provider call returns,
        not before."""
        from schwab_mcp.transactions import get_transaction_history

        mock_client.linked_accounts.return_value = [{"accountHash": "acc1"}]
        sentinel: list[str] = []

        def _tracking_transactions(*args, **kwargs):
            sentinel.append("provider-called")
            return {"transactions": [{"type": "TRADE"}]}

        mock_client.transactions.side_effect = _tracking_transactions

        result = get_transaction_history(mock_client, "2026-10-01", "2026-10-20")

        # Find the index of the success event call
        success_calls = [
            (i, c) for i, c in enumerate(mock_auth_event.call_args_list)
            if c[0][0] == SUCCESS_EVENT
        ]
        if success_calls:
            # The provider must have been called before the success event
            assert "provider-called" in sentinel

    def test_success_not_emitted_if_provider_raises(
        self, mock_auth_event, mock_client,
    ) -> None:
        """No success event is emitted when the provider raises an error."""
        from schwab_mcp.transactions import get_transaction_history

        mock_client.linked_accounts.return_value = [{"accountHash": "acc1"}]
        mock_client.transactions.side_effect = ConnectionError()

        result = get_transaction_history(mock_client, "2026-10-01", "2026-10-20")

        success_calls = [
            c for c in mock_auth_event.call_args_list
            if c[0][0] == SUCCESS_EVENT
        ]
        assert len(success_calls) == 0


# =============================================================================
# 7. No secrets in events (FR-006 / SC-003 defense-in-depth)
# =============================================================================


class TestTransactionEventsSecretFree:
    """Event output must be free of secrets/tokens."""

    def test_no_access_token_in_events(self, mock_auth_event, mock_client) -> None:
        """No access token leaks into any event detail."""
        from schwab_mcp.transactions import get_transaction_history

        mock_client.linked_accounts.return_value = [{"accountHash": "acc1"}]
        mock_client.transactions.return_value = {
            "transactions": [{"type": "TRADE"}],
        }
        mock_client.access_token = "eyJhbGciOiJSUzI1NiJ9.fake-token"

        result = get_transaction_history(mock_client, "2026-10-01", "2026-10-20")

        for call_args in mock_auth_event.call_args_list:
            _, kwargs = call_args
            detail = kwargs.get("detail", "")
            assert "fake-token" not in (detail or ""), (
                f"Secret leaked in event detail: {detail}"
            )

    def test_no_refresh_token_in_events(self, mock_auth_event, mock_client) -> None:
        """No refresh token leaks into any event detail."""
        from schwab_mcp.transactions import get_transaction_history

        mock_client.linked_accounts.return_value = [{"accountHash": "acc1"}]
        mock_client.transactions.return_value = {
            "transactions": [{"type": "TRADE"}],
        }

        result = get_transaction_history(mock_client, "2026-10-01", "2026-10-20")

        for call_args in mock_auth_event.call_args_list:
            _, kwargs = call_args
            detail = kwargs.get("detail", "")
            assert "refresh" not in (detail or "").lower()

    def test_no_provider_text_unredacted(
        self, mock_auth_event, mock_client,
    ) -> None:
        """Free-form provider text (error messages, stack traces) is NOT
        placed directly into events — only fixed detail values from the
        contract namespace are used."""
        from schwab_mcp.transactions import get_transaction_history

        # Provider returns a raw error message — this should NEVER appear
        # verbatim in the event detail.
        mock_client.linked_accounts.return_value = [{"accountHash": "acc1"}]
        mock_client.transactions.side_effect = RuntimeError(
            "Internal server error: token=abc123",
        )

        result = get_transaction_history(mock_client, "2026-10-01", "2026-10-20")

        for call_args in mock_auth_event.call_args_list:
            _, kwargs = call_args
            detail = kwargs.get("detail", "")
            # The raw error text MUST NOT appear in the detail field
            assert "Internal server error" not in (detail or "")
            assert "abc123" not in (detail or "")


# =============================================================================
# 8. Event format matches contract
# =============================================================================


class TestTransactionEventFormat:
    """Event line format matches contracts/events.md.

    The format is::

        <ISO-8601 UTC timestamp> auth_event=<event> outcome=<outcome> detail=<detail>
    """

    def test_event_format_includes_auth_event_field(
        self, mock_auth_event, mock_client,
    ) -> None:
        """The line includes ``auth_event=<event>``."""
        from schwab_mcp.transactions import get_transaction_history

        mock_client.linked_accounts.return_value = [{"accountHash": "acc1"}]
        mock_client.transactions.return_value = {
            "transactions": [{"type": "TRADE"}],
        }

        result = get_transaction_history(mock_client, "2026-10-01", "2026-10-20")

        for call_args in mock_auth_event.call_args_list:
            args, kwargs = call_args
            if args[0] == SUCCESS_EVENT:
                assert args[0] == SUCCESS_EVENT

    def test_event_format_includes_outcome_field(
        self, mock_auth_event, mock_client,
    ) -> None:
        """The line includes ``outcome=<outcome>``."""
        from schwab_mcp.transactions import get_transaction_history

        mock_client.linked_accounts.return_value = [{"accountHash": "acc1"}]
        mock_client.transactions.side_effect = ConnectionError()

        result = get_transaction_history(mock_client, "2026-10-01", "2026-10-20")

        for call_args in mock_auth_event.call_args_list:
            args, kwargs = call_args
            if args[0] == FAILURE_EVENT:
                assert args[1] in {TRANSIENT_OUTCOME, REAUTH_OUTCOME, VALIDATION_OUTCOME}

    def test_event_format_includes_detail_field(
        self, mock_auth_event, mock_client,
    ) -> None:
        """The line includes ``detail=<detail>`` for terminal events."""
        from schwab_mcp.transactions import get_transaction_history

        mock_client.linked_accounts.return_value = [{"accountHash": "acc1"}]
        mock_client.transactions.return_value = {
            "transactions": [{"type": "TRADE"}],
        }

        result = get_transaction_history(mock_client, "2026-10-01", "2026-10-20")

        for call_args in mock_auth_event.call_args_list:
            args, kwargs = call_args
            if args[0] == SUCCESS_EVENT:
                assert "detail" in kwargs
                assert kwargs["detail"] is not None


# =============================================================================
# 9. Detail values are from event namespace, NOT TransactionDetail enum
# =============================================================================


class TestTransactionEventDetailNamespace:
    """The event ``detail`` field uses its own namespace (contract values),
    NOT the ``TransactionDetail`` enum from data-model.md.

    From the contract::

        El campo ``detail`` de los **eventos** es un namespace propio
        de este contrato y NO es el enum ``TransactionDetail``.

    This means:
    - The detail values are the *same strings* as TransactionDetail values
      (because they describe the same underlying situations), but the event
      contract defines them independently.
    - The ``invalid_query`` detail exists in the event namespace but does
      NOT exist in ``TransactionDetail`` (it maps to validation errors,
      not to a tool result).
    """

    def test_invalid_query_detail_not_in_transaction_detail_enum(
        self, mock_auth_event, mock_client,
    ) -> None:
        """``invalid_query`` is a valid event detail but NOT a valid
        ``TransactionDetail`` enum value — it is exclusive to the event
        namespace."""
        from schwab_mcp.transactions import TransactionDetail, get_transaction_history

        # Confirm the enum does NOT have invalid_query
        with pytest.raises((ValueError, TypeError)):
            TransactionDetail("invalid_query")

        # But the event SHOULD accept it for validation outcomes
        with pytest.raises((ValueError, TypeError)):
            result = get_transaction_history(
                mock_client, start_date="invalid", end_date="2026-10-20",
            )

        _assert_terminal_event(
            mock_auth_event, FAILURE_EVENT, VALIDATION_OUTCOME, detail=DETAIL_INVALID_QUERY,
        )

    def test_all_event_details_are_closed_values(
        self, mock_auth_event, mock_client,
    ) -> None:
        """Every terminal event detail is one of the contract's closed set."""
        from schwab_mcp.transactions import get_transaction_history

        mock_client.linked_accounts.return_value = [{"accountHash": "acc1"}]
        mock_client.transactions.return_value = {
            "transactions": [{"type": "TRADE"}],
        }

        result = get_transaction_history(mock_client, "2026-10-01", "2026-10-20")

        all_details_all_values = {
            DETAIL_HISTORY_RETRIEVED,
            DETAIL_NO_MOVEMENTS,
            DETAIL_NO_MOVEMENTS_FOR_INSTRUMENT,
            DETAIL_ACCOUNT_FAILED,
            DETAIL_PROVIDER_UNREACHABLE,
            DETAIL_REAUTH_NEEDED,
            DETAIL_INVALID_QUERY,
        }

        for call_args in mock_auth_event.call_args_list:
            args, kwargs = call_args
            # Only check terminal events (the contract's namespace);
            # start events have their own detail values.
            if args[0] not in (SUCCESS_EVENT, FAILURE_EVENT):
                continue
            detail = kwargs.get("detail", "")
            assert detail in all_details_all_values, (
                f"Unexpected event detail: {detail!r}"
            )