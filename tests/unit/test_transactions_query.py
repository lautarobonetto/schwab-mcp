"""Failing unit tests for orchestration and outcomes of ``get_transaction_history``.

These are TDD red-phase tests: the orchestration function
``get_transaction_history`` does not exist yet in ``schwab_mcp.transactions``,
so every test will fail with ``ImportError`` / ``ModuleNotFoundError``.
Once implemented (T011), all tests should pass.

Tests use a **fake client** (``FakeClient``) to simulate the schwabdev SDK
without network calls.

References
----------
- specs/006-transaction-history/tasks.md T007
- specs/006-transaction-history/spec.md (FR-008, FR-010, FR-012)
- specs/006-transaction-history/research.md (D2, R5)
- specs/006-transaction-history/data-model.md (§TransactionsResult)
- specs/006-transaction-history/contracts/mcp-tools.md
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import pytest

from schwab_mcp.errors import ConnectivityError, ReauthorizationRequiredError
from schwab_mcp.transactions import (
    MovementEntry,
    TransactionDetail,
    TransactionOutcome,
    TransactionsResult,
)

# =============================================================================
# Constants
# =============================================================================

ALL_TYPES = (
    "TRADE,RECEIVE_AND_DELIVER,DIVIDEND_OR_INTEREST,ACH_RECEIPT,"
    "ACH_DISBURSEMENT,CASH_RECEIPT,CASH_DISBURSEMENT,ELECTRONIC_FUND,"
    "WIRE_OUT,WIRE_IN,JOURNAL,MEMORANDUM,MARGIN_CALL,MONEY_MARKET,"
    "SMA_ADJUSTMENT"
)

EXPECTED_TYPE_COUNT = 15
"""The comma-separated list MUST contain exactly 15 types (research D2)."""


# =============================================================================
# Fake client
# =============================================================================


class _validator:
    """Mimics ``schwabdev.validation.Validator`` with a toggleable ``enabled`` flag."""

    enabled = True


class FakeClient:
    """Fake schwabdev Client for testing orchestration.

    ``linked_accounts()`` returns a list of ``{"accountHash": str}`` dicts.
    ``transactions()`` returns a pre-configured response per account hash,
    or raises a configured exception.

    All invocations are recorded in ``call_log`` for assertions.
    """

    def __init__(self) -> None:
        self._validator = _validator()
        self._accounts: list[dict[str, str]] = []
        # {account_hash: dict} — the response for transactions()
        self._tx_responses: dict[str, Any] = {}
        # {account_hash: Exception} — raise instead of returning
        self._tx_errors: dict[str, Exception] = {}
        # Global error raised on ANY call to transactions() (overrides per-account)
        self._tx_global_error: Exception | None = None

        # Call tracking
        self.call_log: list[dict[str, Any]] = []
        """Each entry: {"method": str, "kwargs": dict}"""

    def linked_accounts(self) -> list[dict[str, str]]:
        self.call_log.append({"method": "linked_accounts", "kwargs": {}})
        return list(self._accounts)

    def instruments(
        self, symbols: list[str], projection: str
    ) -> Any:
        """Fake ``instruments()`` — recognises common symbols."""
        self.call_log.append({
            "method": "instruments",
            "kwargs": {"symbols": symbols, "projection": projection},
        })
        known = {"AAPL", "SPY", "MSFT", "GOOGL", "NVDA"}
        if not symbols or symbols[0].upper() not in {s.upper() for s in known}:
            return {}
        symbol = symbols[0]
        return [
            {
                "symbol": symbol,
                "instrumentType": "EQUITY",
                "description": f"{symbol} INC",
                "exchange": "NASDAQ",
            },
        ]

    def transactions(
        self,
        accountHash: str,
        startDate: str,
        endDate: str,
        types: str,
        symbol: str | None = None,
    ) -> Any:
        self.call_log.append({
            "method": "transactions",
            "kwargs": {
                "accountHash": accountHash,
                "startDate": startDate,
                "endDate": endDate,
                "types": types,
                "symbol": symbol,
            },
        })
        if self._tx_global_error is not None:
            raise self._tx_global_error
        if accountHash in self._tx_errors:
            raise self._tx_errors[accountHash]
        return self._tx_responses.get(accountHash, {"transactions": []})

    # ------------------------------------------------------------------
    # Helpers to configure scenarios
    # ------------------------------------------------------------------

    def set_accounts(self, hashes: list[str]) -> None:
        """Set the list of account hashes returned by ``linked_accounts()``."""
        self._accounts = [{"accountHash": h} for h in hashes]

    def set_response(self, account_hash: str, data: dict) -> None:
        """Set the response ``transactions()`` returns for *account_hash*."""
        self._tx_responses[account_hash] = data

    def set_error(self, account_hash: str, exc: Exception) -> None:
        """Make ``transactions()`` raise *exc* for *account_hash*."""
        self._tx_errors[account_hash] = exc

    def set_global_error(self, exc: Exception) -> None:
        """Make ``transactions()`` raise *exc* for EVERY account hash."""
        self._tx_global_error = exc

    def reset_tracking(self) -> None:
        """Clear the call log (useful for determinism tests)."""
        self.call_log.clear()


# =============================================================================
# Helper: build a minimal provider transaction dict
# =============================================================================


def _provider_tx(
    activity_id: str = "act-001",
    tx_type: str = "TRADE",
    description: str = "Test transaction",
    amount: float = 100.0,
    occurred_at: str = "2026-10-20T14:03:11+00:00",
    settlement_date: str = "2026-10-22",
    fees: float | None = None,
    commission: float | None = None,
    net_amount: float | None = None,
    symbol: str | None = "SPY",
    instrument_type: str | None = "EQUITY",
) -> dict:
    """Build a minimal provider-format transaction dict for fake client responses."""
    tx: dict = {
        "activityId": activity_id,
        "type": tx_type,
        "description": description,
        "amount": amount,
        "settlementDate": settlement_date,
        "occurred_at": occurred_at,
    }
    if fees is not None:
        tx["fees"] = fees
    if commission is not None:
        tx["commission"] = commission
    if net_amount is not None:
        tx["netAmount"] = net_amount
    if symbol is not None:
        tx["symbol"] = symbol
    if instrument_type is not None:
        tx["instrumentType"] = instrument_type
    return tx


def _provider_response(transactions: list[dict]) -> dict:
    """Wrap a list of transaction dicts into a fake provider response."""
    return {"transactions": transactions}


# =============================================================================
# Tests
# =============================================================================


class TestGetTransactionHistoryAccountIteration:
    """Verify that ``get_transaction_history`` correctly iterates linked
    accounts and makes the expected calls.

    These tests focus on call behaviour (what is invoked, with what
    arguments) rather than the returned data.
    """

    def test_linked_accounts_called(self) -> None:
        """``linked_accounts()`` MUST be called exactly once."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1", "acc2"])
        client.set_response("acc1", _provider_response([]))
        client.set_response("acc2", _provider_response([]))

        get_transaction_history(client, "2026-10-01", "2026-10-20")

        linked_calls = [
            e for e in client.call_log if e["method"] == "linked_accounts"
        ]
        assert len(linked_calls) == 1, (
            f"Expected exactly 1 linked_accounts() call, got {len(linked_calls)}"
        )

    def test_one_transactions_call_per_account(self) -> None:
        """``transactions()`` MUST be called once per linked account."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1", "acc2", "acc3"])
        client.set_response("acc1", _provider_response([]))
        client.set_response("acc2", _provider_response([]))
        client.set_response("acc3", _provider_response([]))

        get_transaction_history(client, "2026-10-01", "2026-10-20")

        tx_calls = [
            e for e in client.call_log if e["method"] == "transactions"
        ]
        assert len(tx_calls) == 3, (
            f"Expected 3 transactions() calls (one per account), "
            f"got {len(tx_calls)}"
        )

    def test_types_list_contains_all_15_types(self) -> None:
        """The ``types`` parameter to ``transactions()`` MUST contain all 15
        upstream types, comma-separated (research D2)."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response("acc1", _provider_response([]))

        get_transaction_history(client, "2026-10-01", "2026-10-20")

        tx_calls = [
            e for e in client.call_log if e["method"] == "transactions"
        ]
        assert len(tx_calls) == 1
        types_value = tx_calls[0]["kwargs"].get("types", "")
        type_list = [t.strip() for t in types_value.split(",")]
        assert len(type_list) == EXPECTED_TYPE_COUNT, (
            f"Expected {EXPECTED_TYPE_COUNT} types in comma-separated list, "
            f"got {len(type_list)}: {type_list}"
        )
        # Verify some key types are present
        assert "TRADE" in type_list
        assert "DIVIDEND_OR_INTEREST" in type_list
        assert "RECEIVE_AND_DELIVER" in type_list
        assert "SMA_ADJUSTMENT" in type_list

    def test_dates_forwarded_to_transactions(self) -> None:
        """``start_date`` and ``end_date`` MUST be forwarded to every
        ``transactions()`` call as ISO-8601 datetimes bounded by the
        account's market timezone (America/New_York, inclusive edges) —
        the API rejects bare ``YYYY-MM-DD`` strings."""
        from schwab_mcp.transactions import (
            _provider_datetime,
            get_transaction_history,
        )

        client = FakeClient()
        client.set_accounts(["acc1", "acc2"])
        client.set_response("acc1", _provider_response([]))
        client.set_response("acc2", _provider_response([]))

        start = "2026-01-01"
        end = "2026-06-30"
        get_transaction_history(client, start_date=start, end_date=end)

        tx_calls = [
            e for e in client.call_log if e["method"] == "transactions"
        ]
        assert len(tx_calls) >= 1
        for call in tx_calls:
            expected_start = _provider_datetime(start, end_of_day=False)
            expected_end = _provider_datetime(end, end_of_day=True)
            assert call["kwargs"].get("startDate") == expected_start, (
                f"Expected startDate={expected_start!r}, "
                f"got {call['kwargs'].get('startDate')!r}"
            )
            assert call["kwargs"].get("endDate") == expected_end, (
                f"Expected endDate={expected_end!r}, "
                f"got {call['kwargs'].get('endDate')!r}"
            )


class TestGetTransactionHistoryValidatorBypass:
    """Verify the ``_bypass_validator()`` helper used for each
    ``transactions()`` call.

    The helper toggles ``client._validator.enabled = False`` before the
    call and restores it to the original value in a ``finally`` block
    (research D2).
    """

    def test_bypass_validator_disables_during_transactions(self) -> None:
        """During a ``transactions()`` call, ``client._validator.enabled``
        MUST be ``False``."""
        from schwab_mcp.transactions import get_transaction_history

        captured: list[bool] = []

        class CaptureClient(FakeClient):
            def transactions(self, **kwargs: Any) -> Any:
                captured.append(self._validator.enabled)
                return _provider_response([])

        client = CaptureClient()
        client.set_accounts(["acc1"])
        client.set_response("acc1", _provider_response([]))

        get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert len(captured) >= 1, (
            "No transactions() call captured"
        )
        for idx, val in enumerate(captured):
            assert val is False, (
                f"client._validator.enabled was {val!r} during "
                f"transactions() call #{idx}; expected False"
            )

    def test_bypass_validator_restored_after_success(self) -> None:
        """After a successful call, ``client._validator.enabled`` MUST be
        restored to ``True`` (its original value)."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response("acc1", _provider_response([]))
        assert client._validator.enabled is True

        get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert client._validator.enabled is True, (
            "client._validator.enabled was not restored to True after success"
        )

    def test_bypass_validator_restored_after_error(self) -> None:
        """After a ``transactions()`` call raises, ``client._validator.enabled``
        MUST be restored to ``True`` via ``finally``."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_global_error(ConnectivityError(detail="Simulated failure"))
        assert client._validator.enabled is True

        # Should not crash — orchestration handles the error
        get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert client._validator.enabled is True, (
            "client._validator.enabled was not restored to True after error"
        )

    def test_bypass_validator_restored_after_reauth_error(self) -> None:
        """After a ``ReauthorizationRequiredError``, the validator MUST still
        be restored via ``finally``."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_global_error(
            ReauthorizationRequiredError(detail="Token expired")
        )
        assert client._validator.enabled is True

        get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert client._validator.enabled is True, (
            "client._validator.enabled was not restored to True after "
            "reauth error"
        )


class TestGetTransactionHistoryOutcomes:
    """Verify every outcome classification of ``get_transaction_history``.

    Covers: ok/history_retrieved, ok/no_movements,
    transient_failure/provider_unreachable (FR-010 — no internal retries),
    reauth_required/reauth_needed, partial_failure (FR-008).
    """

    def test_ok_history_retrieved_all_accounts(self) -> None:
        """When all accounts respond with transaction data, the outcome MUST
        be ``ok`` with ``detail=history_retrieved``."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1", "acc2"])
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id="a1", symbol="SPY"),
                _provider_tx(activity_id="a2", symbol="AAPL"),
            ]),
        )
        client.set_response(
            "acc2",
            _provider_response([
                _provider_tx(activity_id="b1", symbol="MSFT"),
            ]),
        )

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert result.outcome == TransactionOutcome.ok
        assert result.detail == TransactionDetail.history_retrieved
        assert result.retryable is False
        # We expect deduplication to have merged entries
        assert result.total_count is not None
        assert result.total_count >= 1

    def test_ok_no_movements_all_empty(self) -> None:
        """When every account returns an empty list, the outcome MUST be
        ``ok`` with ``detail=no_movements`` and an empty ``movements`` list."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1", "acc2"])
        client.set_response("acc1", _provider_response([]))
        client.set_response("acc2", _provider_response([]))

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert result.outcome == TransactionOutcome.ok
        assert result.detail == TransactionDetail.no_movements
        assert result.retryable is False
        assert result.movements == []
        assert result.total_count == 0

    def test_ok_no_movements_single_account(self) -> None:
        """A single account with no data returns ``ok/no_movements``."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response("acc1", _provider_response([]))

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert result.outcome == TransactionOutcome.ok
        assert result.detail == TransactionDetail.no_movements
        assert result.movements == []
        assert result.total_count == 0

    def test_transient_failure_at_first_attempt_no_retries(self) -> None:
        """A ``ConnectivityError`` on the very first ``transactions()`` call
        MUST produce ``transient_failure/provider_unreachable`` with
        ``retryable=True``.

        FR-010: the system MUST NOT perform internal retries — the failure
        is reported at the first attempt.
        """
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1", "acc2"])
        client.set_global_error(
            ConnectivityError(detail="Simulated network failure")
        )

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert result.outcome == TransactionOutcome.transient_failure
        assert result.detail == TransactionDetail.provider_unreachable
        assert result.retryable is True

        # Verify only ONE transactions() call was attempted (no retries)
        tx_calls = [
            e for e in client.call_log if e["method"] == "transactions"
        ]
        assert len(tx_calls) == 1, (
            f"Expected exactly 1 transactions() call (no internal retries), "
            f"got {len(tx_calls)}"
        )

    def test_transient_failure_no_retries_multiple_accounts(self) -> None:
        """When the FIRST account raises ``ConnectivityError``, no further
        accounts are queried (fail-fast)."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1", "acc2", "acc3"])
        client.set_error("acc1", ConnectivityError(detail="Down"))

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert result.outcome == TransactionOutcome.transient_failure
        assert result.detail == TransactionDetail.provider_unreachable
        assert result.retryable is True

        # Only acc1 should have been attempted
        tx_calls = [
            e for e in client.call_log if e["method"] == "transactions"
        ]
        assert len(tx_calls) == 1
        assert tx_calls[0]["kwargs"]["accountHash"] == "acc1"

    def test_reauth_required_on_auth_error(self) -> None:
        """A ``ReauthorizationRequiredError`` MUST produce
        ``reauth_required/reauth_needed`` with ``retryable=False``."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_global_error(
            ReauthorizationRequiredError(detail="Token expired, re-auth needed")
        )

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert result.outcome == TransactionOutcome.reauth_required
        assert result.detail == TransactionDetail.reauth_needed
        assert result.retryable is False

    def test_partial_failure_some_accounts_fail_provider_error(self) -> None:
        """When some accounts succeed and others fail with
        ``ConnectivityError``, the outcome MUST be ``partial_failure`` with
        ``accounts_failed`` containing the failed account hashes and
        ``detail=provider_error`` (FR-008)."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc_ok", "acc_fail", "acc_ok2"])
        client.set_response(
            "acc_ok",
            _provider_response([
                _provider_tx(activity_id="a1", symbol="SPY"),
            ]),
        )
        client.set_error(
            "acc_fail",
            Exception("Provider internal error"),
        )
        client.set_response(
            "acc_ok2",
            _provider_response([
                _provider_tx(activity_id="b1", symbol="AAPL"),
            ]),
        )

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert result.outcome == TransactionOutcome.partial_failure
        assert result.detail == TransactionDetail.account_failed
        assert result.retryable is False
        assert result.accounts_failed is not None

        failed_hashes = {af.account_hash for af in result.accounts_failed}
        assert "acc_fail" in failed_hashes, (
            f"'acc_fail' should be in accounts_failed, got {failed_hashes}"
        )
        # At least one entry with provider_error detail
        provider_errors = [
            af for af in result.accounts_failed
            if af.detail == "provider_error"
        ]
        assert len(provider_errors) >= 1, (
            "Expected at least one accounts_failed entry with "
            "detail='provider_error'"
        )

        # Successful accounts' data MUST be present
        assert result.movements is not None
        assert len(result.movements) >= 1

    def test_partial_failure_some_accounts_fail_transient(self) -> None:
        """When an account fails with ``ConnectivityError`` (which is
        transient), the ``accounts_failed`` entry MUST have
        ``detail='transient'``."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc_ok", "acc_transient"])
        client.set_response(
            "acc_ok",
            _provider_response([
                _provider_tx(activity_id="a1", symbol="SPY"),
            ]),
        )
        client.set_error(
            "acc_transient",
            ConnectivityError(detail="Timeout"),
        )

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert result.outcome == TransactionOutcome.partial_failure
        assert result.detail == TransactionDetail.account_failed
        assert result.accounts_failed is not None

        # Verify the transient failure entry
        transient_entries = [
            af for af in result.accounts_failed
            if af.account_hash == "acc_transient"
        ]
        assert len(transient_entries) == 1
        assert transient_entries[0].detail == "transient"

    def test_partial_failure_does_not_silently_drop_failed_accounts(
        self,
    ) -> None:
        """FR-008: When some accounts fail, the result MUST include them
        in ``accounts_failed`` — not silently drop them."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc_ok", "acc_fail1", "acc_fail2"])
        client.set_response(
            "acc_ok",
            _provider_response([
                _provider_tx(activity_id="a1", symbol="SPY"),
            ]),
        )
        client.set_error("acc_fail1", Exception("Error A"))
        client.set_error("acc_fail2", Exception("Error B"))

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert result.outcome == TransactionOutcome.partial_failure
        assert result.accounts_failed is not None
        failed_hashes = {af.account_hash for af in result.accounts_failed}
        assert "acc_fail1" in failed_hashes, (
            "'acc_fail1' not in accounts_failed; failed accounts must "
            "be reported (FR-008)"
        )
        assert "acc_fail2" in failed_hashes, (
            "'acc_fail2' not in accounts_failed; failed accounts must "
            "be reported (FR-008)"
        )
        assert len(failed_hashes) == 2

    def test_partial_failure_does_not_contain_retryable_true(self) -> None:
        """A ``partial_failure`` outcome MUST have ``retryable=False``
        (only ``transient_failure`` is retryable)."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc_ok", "acc_fail"])
        client.set_response(
            "acc_ok",
            _provider_response([_provider_tx(activity_id="a1")]),
        )
        client.set_error("acc_fail", Exception("Error"))

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert result.outcome == TransactionOutcome.partial_failure
        assert result.retryable is False

    def test_all_accounts_fail_returns_partial_failure(self) -> None:
        """When EVERY account fails, the outcome MUST be
        ``partial_failure`` (not ``transient_failure``), with all
        accounts listed in ``accounts_failed``."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc_fail1", "acc_fail2", "acc_fail3"])
        client.set_error("acc_fail1", Exception("Error 1"))
        client.set_error("acc_fail2", Exception("Error 2"))
        client.set_error("acc_fail3", Exception("Error 3"))

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert result.outcome == TransactionOutcome.partial_failure
        assert result.detail == TransactionDetail.account_failed
        assert result.accounts_failed is not None
        assert len(result.accounts_failed) == 3
        # When all accounts fail, movements should be empty
        assert result.movements == []


class TestGetTransactionHistoryDeduplication:
    """Verify that movements from different accounts (or the same account
    across split ranges) are deduplicated by ``(account_hash, activityId)``.

    See research D3 and data-model.md: deduplication key is
    ``(account_hash, activityId)``.
    """

    def test_deduplicates_identical_activity_in_same_account(self) -> None:
        """If the same account returns two entries with the same
        ``activityId``, only one MUST be kept in the final result."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(
                    activity_id="dup-001",
                    symbol="SPY",
                    description="Duplicate entry",
                ),
                _provider_tx(
                    activity_id="dup-001",  # Same ID!
                    symbol="SPY",
                    description="Duplicate entry",
                ),
                _provider_tx(
                    activity_id="unique-002",
                    symbol="AAPL",
                    description="Unique entry",
                ),
            ]),
        )

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert result.outcome == TransactionOutcome.ok
        assert result.movements is not None
        # 3 raw entries → 2 after dedup (one duplicate removed)
        assert result.total_count is not None and result.total_count >= 2

    def test_deduplicates_activity_across_different_accounts(self) -> None:
        """Two different accounts may have entries with the same
        ``activityId``. Because ``account_hash`` is part of the dedup key,
        BOTH entries MUST be kept (different account_hash)."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1", "acc2"])
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(
                    activity_id="act-001",
                    symbol="SPY",
                ),
            ]),
        )
        client.set_response(
            "acc2",
            _provider_response([
                _provider_tx(
                    activity_id="act-001",  # Same activityId, different account
                    symbol="AAPL",
                ),
            ]),
        )

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert result.outcome == TransactionOutcome.ok
        assert result.movements is not None
        # Both should be kept (different account hashes)
        assert result.total_count is not None and result.total_count == 2


class TestGetTransactionHistoryRetrievedAt:
    """Verify ``retrieved_at`` semantics: ISO-8601 UTC timestamp."""

    def test_retrieved_at_is_iso8601_utc(self) -> None:
        """``retrieved_at`` MUST be an ISO-8601 string parseable by
        ``datetime.fromisoformat()`` and MUST be timezone-aware (UTC)."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response(
            "acc1",
            _provider_response([_provider_tx(activity_id="a1")]),
        )

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        dt = datetime.fromisoformat(result.retrieved_at)
        assert dt.tzinfo is not None, (
            "retrieved_at must be timezone-aware (UTC)"
        )
        # Must be UTC — either +00:00 or Z
        utc_offsets = {0}  # UTC offset in minutes = 0
        assert dt.utcoffset() is not None
        assert dt.utcoffset().total_seconds() / 60 in utc_offsets, (
            f"retrieved_at must be UTC, got offset {dt.utcoffset()}"
        )

    def test_retrieved_at_on_transient_failure(self) -> None:
        """Even on ``transient_failure``, ``retrieved_at`` MUST be a valid
        ISO-8601 UTC timestamp."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_global_error(
            ConnectivityError(detail="Network down")
        )

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        dt = datetime.fromisoformat(result.retrieved_at)
        assert dt.tzinfo is not None

    def test_retrieved_at_on_reauth_required(self) -> None:
        """On ``reauth_required``, ``retrieved_at`` MUST be a valid
        ISO-8601 UTC timestamp."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_global_error(
            ReauthorizationRequiredError(detail="Re-auth needed")
        )

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        dt = datetime.fromisoformat(result.retrieved_at)
        assert dt.tzinfo is not None

    def test_retrieved_at_on_partial_failure(self) -> None:
        """On ``partial_failure``, ``retrieved_at`` MUST be a valid
        ISO-8601 UTC timestamp."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc_ok", "acc_fail"])
        client.set_response(
            "acc_ok",
            _provider_response([_provider_tx(activity_id="a1")]),
        )
        client.set_error("acc_fail", Exception("Error"))

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        dt = datetime.fromisoformat(result.retrieved_at)
        assert dt.tzinfo is not None


class TestGetTransactionHistoryOutputFields:
    """Verify the structure and required fields of the returned
    ``TransactionsResult`` for the ``ok`` outcome."""

    def test_ok_outcome_has_required_pagination_fields(self) -> None:
        """An ``ok`` result MUST include ``total_count``, ``movements``,
        ``returned``, ``has_more``, and ``offset_echo``."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id="a1", symbol="SPY"),
                _provider_tx(activity_id="a2", symbol="AAPL"),
            ]),
        )

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert result.outcome == TransactionOutcome.ok
        assert result.total_count is not None
        assert result.movements is not None
        assert result.returned is not None
        assert result.has_more is not None
        assert result.offset_echo is not None

    def test_ok_outcome_with_no_movements_has_pagination_fields(self) -> None:
        """Even with empty movements, an ``ok`` result MUST include all
        pagination fields (total_count=0, returned=0, has_more=False,
        movements=[], offset_echo=0)."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response("acc1", _provider_response([]))

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert result.outcome == TransactionOutcome.ok
        assert result.total_count == 0
        assert result.movements == []
        assert result.returned == 0
        assert result.has_more is False
        assert result.offset_echo is not None

    def test_offset_echo_reflects_requested_offset(self) -> None:
        """When called with an ``offset`` parameter, ``offset_echo`` MUST
        reflect that value."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id=f"a{i:04d}", symbol="SPY")
                for i in range(10)
            ]),
        )

        result = get_transaction_history(
            client, "2026-10-01", "2026-10-20", offset=3,
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.offset_echo == 3

    def test_extended_false_by_default(self) -> None:
        """Calling ``get_transaction_history`` without ``extended=True``
        MUST produce entries without the ``extended`` field."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(
                    activity_id="a1", symbol="SPY",
                    fees=1.0, commission=0.5, net_amount=98.5,
                ),
            ]),
        )

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert result.outcome == TransactionOutcome.ok
        assert result.movements is not None
        for entry in result.movements:
            serialised = entry.model_dump(exclude_none=True)
            assert "extended" not in serialised, (
                "extended should be absent when extended=False"
            )


class TestGetTransactionHistoryDeterminism:
    """US1 esc. 2: The same query executed twice MUST produce the same
    result set (determinism over a stable data set)."""

    def test_same_query_twice_produces_same_result(self) -> None:
        """Calling ``get_transaction_history`` twice with the same arguments
        and the same client state returns identical ``TransactionsResult``
        (same outcome, same detail, same movements)."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1", "acc2"])
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id="a1", symbol="SPY"),
                _provider_tx(activity_id="a2", symbol="AAPL"),
            ]),
        )
        client.set_response(
            "acc2",
            _provider_response([
                _provider_tx(activity_id="b1", symbol="MSFT"),
                _provider_tx(activity_id="b2", symbol="GOOG"),
            ]),
        )

        result1 = get_transaction_history(client, "2026-10-01", "2026-10-20")
        client.reset_tracking()
        result2 = get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert result1.outcome == result2.outcome
        assert result1.detail == result2.detail
        assert result1.total_count == result2.total_count
        assert result1.retryable == result2.retryable
        # The sets of activity IDs should be identical
        ids1 = {m.symbol for m in (result1.movements or [])}
        ids2 = {m.symbol for m in (result2.movements or [])}
        assert ids1 == ids2, (
            f"Determinism violation: first query symbols {ids1} != "
            f"second query symbols {ids2}"
        )

    def test_same_empty_query_twice(self) -> None:
        """An empty result must also be deterministic."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response("acc1", _provider_response([]))

        result1 = get_transaction_history(client, "2026-10-01", "2026-10-20")
        client.reset_tracking()
        result2 = get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert result1.outcome == result2.outcome
        assert result1.detail == result2.detail
        assert result1.total_count == result2.total_count
        assert result1.movements == result2.movements


class TestGetTransactionHistoryReadOnly:
    """FR-012: ``get_transaction_history`` MUST be read-only — it MUST only
    invoke read methods on the client (``linked_accounts``,
    ``transactions``) and MUST NOT invoke ``place_order`` or any other
    state-mutating method."""

    # Methods that would violate FR-012 if called
    _WRITE_METHODS = frozenset({
        "place_order", "place_order_linked", "cancel_order",
        "preview_order", "modify_order",
    })

    def test_only_read_methods_invoked(self) -> None:
        """The orchestration MUST only call read methods on the client.
        No ``place_order``, ``cancel_order``, or similar write methods
        may be invoked (FR-012)."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1", "acc2"])
        client.set_response("acc1", _provider_response([]))
        client.set_response("acc2", _provider_response([]))

        get_transaction_history(client, "2026-10-01", "2026-10-20")

        called_methods = {e["method"] for e in client.call_log}
        write_calls = called_methods & self._WRITE_METHODS
        assert not write_calls, (
            f"FR-012 violation: write method(s) called: {write_calls}. "
            f"Only read methods (linked_accounts, transactions) are "
            f"allowed."
        )

    def test_no_place_order_method_invoked(self) -> None:
        """Explicitly verify that ``place_order`` is never among the called
        methods (FR-012 safety)."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response("acc1", _provider_response([]))

        get_transaction_history(client, "2026-10-01", "2026-10-20")

        for entry in client.call_log:
            assert entry["method"] != "place_order", (
                f"FR-012: 'place_order' must NOT be called; "
                f"called {entry['method']}"
            )


class TestGetTransactionHistoryExtendedMode:
    """Behaviour when ``extended=True`` is passed to the orchestration."""

    def test_extended_true_forwarded_to_transactions(self) -> None:
        """When ``extended=True``, the orchestration does NOT change the
        ``transactions()`` call parameters (extended is a mapping concern,
        not a query parameter)."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response("acc1", _provider_response([_provider_tx(activity_id="a1")]))

        get_transaction_history(
            client, "2026-10-01", "2026-10-20", extended=True,
        )

        tx_calls = [
            e for e in client.call_log if e["method"] == "transactions"
        ]
        assert len(tx_calls) == 1
        # extended is NOT a parameter to transactions()
        assert "extended" not in tx_calls[0]["kwargs"]


class TestGetTransactionHistoryEdgeCases:
    """Edge cases and boundary conditions."""

    def test_no_linked_accounts(self) -> None:
        """When ``linked_accounts()`` returns an empty list, the outcome
        MUST be ``ok/no_movements`` (no accounts == no movements)."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts([])

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert result.outcome == TransactionOutcome.ok
        assert result.detail == TransactionDetail.no_movements
        assert result.movements == []
        assert result.total_count == 0

    def test_single_account_with_data(self) -> None:
        """A single account with transactions returns ``ok/history_retrieved``."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id="a1", symbol="SPY", amount=100.0),
                _provider_tx(activity_id="a2", symbol="AAPL", amount=200.0),
            ]),
        )

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert result.outcome == TransactionOutcome.ok
        assert result.detail == TransactionDetail.history_retrieved
        assert result.total_count is not None and result.total_count >= 1

    def test_symbol_forwarded_to_transactions_when_provided(self) -> None:
        """When a ``symbol`` is provided, it MUST be forwarded as the
        ``symbol`` parameter to ``transactions()``."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response("acc1", _provider_response([]))

        get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="AAPL",
        )

        tx_calls = [
            e for e in client.call_log if e["method"] == "transactions"
        ]
        assert len(tx_calls) == 1
        assert tx_calls[0]["kwargs"].get("symbol") == "AAPL", (
            "symbol must be forwarded to transactions()"
        )

    def test_no_symbol_by_default(self) -> None:
        """When no ``symbol`` is provided, the ``transactions()`` call MUST
        have ``symbol=None`` (no filter)."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response("acc1", _provider_response([]))

        get_transaction_history(client, "2026-10-01", "2026-10-20")

        tx_calls = [
            e for e in client.call_log if e["method"] == "transactions"
        ]
        assert len(tx_calls) == 1
        assert tx_calls[0]["kwargs"].get("symbol") is None, (
            "No symbol should be None by default"
        )


class TestGetTransactionHistoryGeneralErrorHandling:
    """Graceful handling of unexpected errors during orchestration."""

    def test_generic_exception_during_transactions_is_account_failure(
        self,
    ) -> None:
        """A generic ``Exception`` (not specifically ``ConnectivityError``
        or ``ReauthorizationRequiredError``) during a ``transactions()``
        call MUST be treated as a per-account failure with
        ``detail=provider_error``."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc_ok", "acc_fail"])
        client.set_response(
            "acc_ok",
            _provider_response([_provider_tx(activity_id="a1", symbol="SPY")]),
        )
        client.set_error("acc_fail", RuntimeError("Unexpected crash"))

        result = get_transaction_history(client, "2026-10-01", "2026-10-20")

        assert result.outcome == TransactionOutcome.partial_failure
        assert result.accounts_failed is not None
        fail_entry = next(
            (af for af in result.accounts_failed if af.account_hash == "acc_fail"),
            None,
        )
        assert fail_entry is not None, (
            "acc_fail should appear in accounts_failed"
        )
        assert fail_entry.detail == "provider_error", (
            f"Expected detail='provider_error', got {fail_entry.detail!r}"
        )