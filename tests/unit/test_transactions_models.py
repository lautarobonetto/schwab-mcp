"""Failing unit tests for transaction models and enums (TDD red-phase).

These are TDD red-phase tests: the source module (``schwab_mcp.transactions``)
does not exist yet, so every test will fail with ``ModuleNotFoundError`` /
``ImportError``. Once implemented, all tests should pass.

References
----------
- specs/006-transaction-history/data-model.md: enum, entity, and
  cross-validation specifications.
"""

from __future__ import annotations

from datetime import datetime

import pytest


# =============================================================================
# TransactionOutcome enum
# =============================================================================


class TestTransactionOutcome:
    """TransactionOutcome is a closed enum with 4 values reused from 003.

    Values: ok, partial_failure, transient_failure, reauth_required.
    """

    def test_ok_value(self) -> None:
        """TransactionOutcome.ok represents a complete successful query."""
        from schwab_mcp.transactions import TransactionOutcome

        assert TransactionOutcome.ok.value == "ok"

    def test_partial_failure_value(self) -> None:
        """TransactionOutcome.partial_failure when some accounts fail."""
        from schwab_mcp.transactions import TransactionOutcome

        assert TransactionOutcome.partial_failure.value == "partial_failure"

    def test_transient_failure_value(self) -> None:
        """TransactionOutcome.transient_failure when network/provider down."""
        from schwab_mcp.transactions import TransactionOutcome

        assert TransactionOutcome.transient_failure.value == "transient_failure"

    def test_reauth_required_value(self) -> None:
        """TransactionOutcome.reauth_required when credentials rejected."""
        from schwab_mcp.transactions import TransactionOutcome

        assert TransactionOutcome.reauth_required.value == "reauth_required"

    def test_invalid_value_raises(self) -> None:
        """Creating a TransactionOutcome from an invalid string raises."""
        from schwab_mcp.transactions import TransactionOutcome

        with pytest.raises((ValueError, TypeError)):
            TransactionOutcome("bogus_outcome")

    def test_member_count_is_exactly_four(self) -> None:
        """TransactionOutcome has exactly 4 members."""
        from schwab_mcp.transactions import TransactionOutcome

        assert len(TransactionOutcome) == 4


# =============================================================================
# TransactionDetail enum
# =============================================================================


class TestTransactionDetail:
    """TransactionDetail is a closed enum with 6 values.

    Values: history_retrieved, no_movements, no_movements_for_instrument,
    account_failed, provider_unreachable, reauth_needed.
    """

    def test_history_retrieved_value(self) -> None:
        """history_retrieved when >= 1 movement retrieved."""
        from schwab_mcp.transactions import TransactionDetail

        assert TransactionDetail.history_retrieved.value == "history_retrieved"

    def test_no_movements_value(self) -> None:
        """no_movements when no movements in range for any account."""
        from schwab_mcp.transactions import TransactionDetail

        assert TransactionDetail.no_movements.value == "no_movements"

    def test_no_movements_for_instrument_value(self) -> None:
        """no_movements_for_instrument when symbol filter yields no results."""
        from schwab_mcp.transactions import TransactionDetail

        assert (
            TransactionDetail.no_movements_for_instrument.value
            == "no_movements_for_instrument"
        )

    def test_account_failed_value(self) -> None:
        """account_failed when >= 1 account failed (partial_failure)."""
        from schwab_mcp.transactions import TransactionDetail

        assert TransactionDetail.account_failed.value == "account_failed"

    def test_provider_unreachable_value(self) -> None:
        """provider_unreachable when transient failure occurs."""
        from schwab_mcp.transactions import TransactionDetail

        assert TransactionDetail.provider_unreachable.value == "provider_unreachable"

    def test_reauth_needed_value(self) -> None:
        """reauth_needed when re-authorisation is required."""
        from schwab_mcp.transactions import TransactionDetail

        assert TransactionDetail.reauth_needed.value == "reauth_needed"

    def test_invalid_value_raises(self) -> None:
        """Creating a TransactionDetail from an invalid string raises."""
        from schwab_mcp.transactions import TransactionDetail

        with pytest.raises((ValueError, TypeError)):
            TransactionDetail("bogus_detail")

    def test_member_count_is_exactly_six(self) -> None:
        """TransactionDetail has exactly 6 members."""
        from schwab_mcp.transactions import TransactionDetail

        assert len(TransactionDetail) == 6


# =============================================================================
# MovementCategory enum
# =============================================================================


class TestMovementCategory:
    """MovementCategory is a closed enum with 9 values.

    Active v1: trade, transfer, dividend_or_interest, adjustment, other.
    Reserved (no upstream mapping in v1): interest, dividend, fee,
    corporate_action.
    """

    def test_trade_value(self) -> None:
        """trade is a buy/sell of an instrument."""
        from schwab_mcp.transactions import MovementCategory

        assert MovementCategory.trade.value == "trade"

    def test_transfer_value(self) -> None:
        """transfer covers cash movements (ACH, wire, etc.)."""
        from schwab_mcp.transactions import MovementCategory

        assert MovementCategory.transfer.value == "transfer"

    def test_dividend_or_interest_value(self) -> None:
        """dividend_or_interest for the upstream DIVIDEND_OR_INTEREST type."""
        from schwab_mcp.transactions import MovementCategory

        assert MovementCategory.dividend_or_interest.value == "dividend_or_interest"

    def test_adjustment_value(self) -> None:
        """adjustment covers journals and SMA adjustments."""
        from schwab_mcp.transactions import MovementCategory

        assert MovementCategory.adjustment.value == "adjustment"

    def test_other_value(self) -> None:
        """other is the fallback for unknown/uncategorised types."""
        from schwab_mcp.transactions import MovementCategory

        assert MovementCategory.other.value == "other"

    def test_interest_reserved(self) -> None:
        """interest is a reserved value with no upstream mapping in v1."""
        from schwab_mcp.transactions import MovementCategory

        assert MovementCategory.interest.value == "interest"

    def test_dividend_reserved(self) -> None:
        """dividend is a reserved value with no upstream mapping in v1."""
        from schwab_mcp.transactions import MovementCategory

        assert MovementCategory.dividend.value == "dividend"

    def test_fee_reserved(self) -> None:
        """fee is a reserved value with no upstream mapping in v1."""
        from schwab_mcp.transactions import MovementCategory

        assert MovementCategory.fee.value == "fee"

    def test_corporate_action_reserved(self) -> None:
        """corporate_action is a reserved value with no upstream mapping in v1."""
        from schwab_mcp.transactions import MovementCategory

        assert MovementCategory.corporate_action.value == "corporate_action"

    def test_invalid_value_raises(self) -> None:
        """Creating a MovementCategory from an invalid string raises."""
        from schwab_mcp.transactions import MovementCategory

        with pytest.raises((ValueError, TypeError)):
            MovementCategory("bogus_category")

    def test_member_count_is_exactly_nine(self) -> None:
        """MovementCategory has exactly 9 members."""
        from schwab_mcp.transactions import MovementCategory

        assert len(MovementCategory) == 9


# =============================================================================
# ProviderTransactionType enum
# =============================================================================


class TestProviderTransactionType:
    """ProviderTransactionType mirrors all 15 upstream transaction types.

    Values: TRADE, RECEIVE_AND_DELIVER, DIVIDEND_OR_INTEREST, ACH_RECEIPT,
    ACH_DISBURSEMENT, CASH_RECEIPT, CASH_DISBURSEMENT, ELECTRONIC_FUND,
    WIRE_OUT, WIRE_IN, JOURNAL, MEMORANDUM, MARGIN_CALL, MONEY_MARKET,
    SMA_ADJUSTMENT.
    """

    def test_trade(self) -> None:
        from schwab_mcp.transactions import ProviderTransactionType

        assert ProviderTransactionType.TRADE.value == "TRADE"

    def test_receive_and_deliver(self) -> None:
        from schwab_mcp.transactions import ProviderTransactionType

        assert ProviderTransactionType.RECEIVE_AND_DELIVER.value == "RECEIVE_AND_DELIVER"

    def test_dividend_or_interest(self) -> None:
        from schwab_mcp.transactions import ProviderTransactionType

        assert (
            ProviderTransactionType.DIVIDEND_OR_INTEREST.value == "DIVIDEND_OR_INTEREST"
        )

    def test_ach_receipt(self) -> None:
        from schwab_mcp.transactions import ProviderTransactionType

        assert ProviderTransactionType.ACH_RECEIPT.value == "ACH_RECEIPT"

    def test_ach_disbursement(self) -> None:
        from schwab_mcp.transactions import ProviderTransactionType

        assert ProviderTransactionType.ACH_DISBURSEMENT.value == "ACH_DISBURSEMENT"

    def test_cash_receipt(self) -> None:
        from schwab_mcp.transactions import ProviderTransactionType

        assert ProviderTransactionType.CASH_RECEIPT.value == "CASH_RECEIPT"

    def test_cash_disbursement(self) -> None:
        from schwab_mcp.transactions import ProviderTransactionType

        assert ProviderTransactionType.CASH_DISBURSEMENT.value == "CASH_DISBURSEMENT"

    def test_electronic_fund(self) -> None:
        from schwab_mcp.transactions import ProviderTransactionType

        assert ProviderTransactionType.ELECTRONIC_FUND.value == "ELECTRONIC_FUND"

    def test_wire_out(self) -> None:
        from schwab_mcp.transactions import ProviderTransactionType

        assert ProviderTransactionType.WIRE_OUT.value == "WIRE_OUT"

    def test_wire_in(self) -> None:
        from schwab_mcp.transactions import ProviderTransactionType

        assert ProviderTransactionType.WIRE_IN.value == "WIRE_IN"

    def test_journal(self) -> None:
        from schwab_mcp.transactions import ProviderTransactionType

        assert ProviderTransactionType.JOURNAL.value == "JOURNAL"

    def test_memorandum(self) -> None:
        from schwab_mcp.transactions import ProviderTransactionType

        assert ProviderTransactionType.MEMORANDUM.value == "MEMORANDUM"

    def test_margin_call(self) -> None:
        from schwab_mcp.transactions import ProviderTransactionType

        assert ProviderTransactionType.MARGIN_CALL.value == "MARGIN_CALL"

    def test_money_market(self) -> None:
        from schwab_mcp.transactions import ProviderTransactionType

        assert ProviderTransactionType.MONEY_MARKET.value == "MONEY_MARKET"

    def test_sma_adjustment(self) -> None:
        from schwab_mcp.transactions import ProviderTransactionType

        assert ProviderTransactionType.SMA_ADJUSTMENT.value == "SMA_ADJUSTMENT"

    def test_invalid_value_raises(self) -> None:
        """Creating a ProviderTransactionType from an invalid string raises."""
        from schwab_mcp.transactions import ProviderTransactionType

        with pytest.raises((ValueError, TypeError)):
            ProviderTransactionType("UNKNOWN_TYPE")

    def test_member_count_is_exactly_fifteen(self) -> None:
        """ProviderTransactionType has exactly 15 members."""
        from schwab_mcp.transactions import ProviderTransactionType

        assert len(ProviderTransactionType) == 15


# =============================================================================
# Type-to-category mapping (R5)
# =============================================================================


class TestClassifyMovementType:
    """classify_movement_type(provider_type: str) -> MovementCategory

    Maps every known upstream transaction type to its normalised category.
    Unknown types fall back to ``other``.
    """

    def test_trade_maps_to_trade(self) -> None:
        """TRADE → MovementCategory.trade."""
        from schwab_mcp.transactions import MovementCategory, classify_movement_type

        assert classify_movement_type("TRADE") == MovementCategory.trade

    def test_receive_and_deliver_maps_to_transfer(self) -> None:
        """RECEIVE_AND_DELIVER → MovementCategory.transfer."""
        from schwab_mcp.transactions import MovementCategory, classify_movement_type

        assert (
            classify_movement_type("RECEIVE_AND_DELIVER")
            == MovementCategory.transfer
        )

    def test_ach_receipt_maps_to_transfer(self) -> None:
        """ACH_RECEIPT → MovementCategory.transfer."""
        from schwab_mcp.transactions import MovementCategory, classify_movement_type

        assert classify_movement_type("ACH_RECEIPT") == MovementCategory.transfer

    def test_ach_disbursement_maps_to_transfer(self) -> None:
        """ACH_DISBURSEMENT → MovementCategory.transfer."""
        from schwab_mcp.transactions import MovementCategory, classify_movement_type

        assert (
            classify_movement_type("ACH_DISBURSEMENT") == MovementCategory.transfer
        )

    def test_cash_receipt_maps_to_transfer(self) -> None:
        """CASH_RECEIPT → MovementCategory.transfer."""
        from schwab_mcp.transactions import MovementCategory, classify_movement_type

        assert classify_movement_type("CASH_RECEIPT") == MovementCategory.transfer

    def test_cash_disbursement_maps_to_transfer(self) -> None:
        """CASH_DISBURSEMENT → MovementCategory.transfer."""
        from schwab_mcp.transactions import MovementCategory, classify_movement_type

        assert (
            classify_movement_type("CASH_DISBURSEMENT") == MovementCategory.transfer
        )

    def test_electronic_fund_maps_to_transfer(self) -> None:
        """ELECTRONIC_FUND → MovementCategory.transfer."""
        from schwab_mcp.transactions import MovementCategory, classify_movement_type

        assert classify_movement_type("ELECTRONIC_FUND") == MovementCategory.transfer

    def test_wire_in_maps_to_transfer(self) -> None:
        """WIRE_IN → MovementCategory.transfer."""
        from schwab_mcp.transactions import MovementCategory, classify_movement_type

        assert classify_movement_type("WIRE_IN") == MovementCategory.transfer

    def test_wire_out_maps_to_transfer(self) -> None:
        """WIRE_OUT → MovementCategory.transfer."""
        from schwab_mcp.transactions import MovementCategory, classify_movement_type

        assert classify_movement_type("WIRE_OUT") == MovementCategory.transfer

    def test_dividend_or_interest_maps_to_dividend_or_interest(self) -> None:
        """DIVIDEND_OR_INTEREST → MovementCategory.dividend_or_interest."""
        from schwab_mcp.transactions import MovementCategory, classify_movement_type

        assert (
            classify_movement_type("DIVIDEND_OR_INTEREST")
            == MovementCategory.dividend_or_interest
        )

    def test_journal_maps_to_adjustment(self) -> None:
        """JOURNAL → MovementCategory.adjustment."""
        from schwab_mcp.transactions import MovementCategory, classify_movement_type

        assert classify_movement_type("JOURNAL") == MovementCategory.adjustment

    def test_sma_adjustment_maps_to_adjustment(self) -> None:
        """SMA_ADJUSTMENT → MovementCategory.adjustment."""
        from schwab_mcp.transactions import MovementCategory, classify_movement_type

        assert (
            classify_movement_type("SMA_ADJUSTMENT") == MovementCategory.adjustment
        )

    def test_memorandum_maps_to_other(self) -> None:
        """MEMORANDUM → MovementCategory.other."""
        from schwab_mcp.transactions import MovementCategory, classify_movement_type

        assert classify_movement_type("MEMORANDUM") == MovementCategory.other

    def test_margin_call_maps_to_other(self) -> None:
        """MARGIN_CALL → MovementCategory.other."""
        from schwab_mcp.transactions import MovementCategory, classify_movement_type

        assert classify_movement_type("MARGIN_CALL") == MovementCategory.other

    def test_money_market_maps_to_other(self) -> None:
        """MONEY_MARKET → MovementCategory.other."""
        from schwab_mcp.transactions import MovementCategory, classify_movement_type

        assert classify_movement_type("MONEY_MARKET") == MovementCategory.other

    def test_unknown_type_maps_to_other(self) -> None:
        """Any unknown upstream type falls back to MovementCategory.other."""
        from schwab_mcp.transactions import MovementCategory, classify_movement_type

        assert classify_movement_type("NEW_FUTURE_TYPE") == MovementCategory.other

    def test_empty_string_maps_to_other(self) -> None:
        """An empty string is not a known type → falls back to other."""
        from schwab_mcp.transactions import MovementCategory, classify_movement_type

        assert classify_movement_type("") == MovementCategory.other


# =============================================================================
# MovementEntry model
# =============================================================================


class TestMovementEntry:
    """MovementEntry(account_hash, occurred_at, category, description, amount, ...)
    validated data model.

    Tests cover:
    - All curated fields pass validation
    - account_hash non-empty
    - occurred_at ISO-8601 parseable
    - description truncated to 80 chars
    - currency defaults to "USD"
    - Symbol and instrument_type optional
    - Extended optional, only when extended=true
    - Invalid category raises
    """

    def test_minimal_movement_entry(self) -> None:
        """A MovementEntry with all required fields passes validation."""
        from schwab_mcp.transactions import MovementEntry

        entry = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Bought 10 SPY at 580.25",
            amount=5802.50,
        )
        assert entry.account_hash == "acc123"
        assert entry.occurred_at == "2026-10-20T14:03:11+00:00"
        assert entry.category.value == "trade"
        assert entry.description == "Bought 10 SPY at 580.25"
        assert entry.amount == 5802.50
        assert entry.currency == "USD"  # default

    def test_full_movement_entry_with_symbol(self) -> None:
        """A MovementEntry with optional instrument fields."""
        from schwab_mcp.transactions import MovementEntry

        entry = MovementEntry(
            account_hash="acc456",
            occurred_at="2026-10-19T10:00:00+00:00",
            category="transfer",
            description="ACH transfer",
            amount=5000.00,
            currency="USD",
            symbol=None,
            instrument_type=None,
        )
        assert entry.account_hash == "acc456"
        assert entry.symbol is None
        assert entry.instrument_type is None

    def test_movement_entry_with_instrument(self) -> None:
        """A MovementEntry referencing a specific instrument."""
        from schwab_mcp.transactions import MovementEntry

        entry = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Sold 5 AAPL",
            amount=-7500.00,
            symbol="AAPL",
            instrument_type="EQUITY",
        )
        assert entry.symbol == "AAPL"
        assert entry.instrument_type == "EQUITY"

    def test_account_hash_non_empty(self) -> None:
        """account_hash must be a non-empty string."""
        from schwab_mcp.transactions import MovementEntry

        with pytest.raises((ValueError, TypeError)):
            MovementEntry(
                account_hash="",
                occurred_at="2026-10-20T14:03:11+00:00",
                category="trade",
                description="Test",
                amount=100.0,
            )

    def test_occurred_at_iso8601_parseable(self) -> None:
        """occurred_at must be an ISO-8601 string parseable by datetime."""
        from schwab_mcp.transactions import MovementEntry

        entry = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Test",
            amount=100.0,
        )
        dt = datetime.fromisoformat(entry.occurred_at)
        assert dt.tzinfo is not None  # Must be timezone-aware

    def test_description_truncated_to_80_chars(self) -> None:
        """description longer than 80 characters is truncated to 80."""
        from schwab_mcp.transactions import MovementEntry

        long_desc = "A" * 200
        entry = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description=long_desc,
            amount=100.0,
        )
        assert len(entry.description) == 80

    def test_description_short_not_truncated(self) -> None:
        """description <= 80 characters is not truncated."""
        from schwab_mcp.transactions import MovementEntry

        short_desc = "Short description"
        entry = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description=short_desc,
            amount=100.0,
        )
        assert entry.description == short_desc

    def test_currency_defaults_to_usd(self) -> None:
        """currency field defaults to 'USD' when not provided."""
        from schwab_mcp.transactions import MovementEntry

        entry = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Test",
            amount=100.0,
        )
        assert entry.currency == "USD"

    def test_currency_explicit_non_usd(self) -> None:
        """currency can be set to a non-USD value when the provider exposes it."""
        from schwab_mcp.transactions import MovementEntry

        entry = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Test",
            amount=100.0,
            currency="EUR",
        )
        assert entry.currency == "EUR"

    def test_invalid_category_raises(self) -> None:
        """A category string not in MovementCategory raises."""
        from schwab_mcp.transactions import MovementEntry

        with pytest.raises((ValueError, TypeError)):
            MovementEntry(
                account_hash="acc123",
                occurred_at="2026-10-20T14:03:11+00:00",
                category="invalid_category",
                description="Test",
                amount=100.0,
            )

    def test_extended_present_when_extended_true(self) -> None:
        """When extended is provided, it is included as a dict."""
        from schwab_mcp.transactions import MovementEntry

        entry = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Test",
            amount=100.0,
            extended={"type": "TRADE", "fees": 0.0, "commissions": 0.0},
        )
        assert entry.extended is not None
        assert entry.extended["type"] == "TRADE"

    def test_extended_absent_by_default(self) -> None:
        """Without extended, the field is absent from serialised output."""
        from schwab_mcp.transactions import MovementEntry

        entry = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Test",
            amount=100.0,
        )
        serialised = entry.model_dump(exclude_none=True)
        assert "extended" not in serialised

    def test_symbol_and_instrument_type_absent_when_no_instrument(self) -> None:
        """Without instrument, symbol and instrument_type are absent from
        serialised output."""
        from schwab_mcp.transactions import MovementEntry

        entry = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="transfer",
            description="Wire transfer",
            amount=1000.0,
        )
        serialised = entry.model_dump(exclude_none=True)
        assert "symbol" not in serialised
        assert "instrument_type" not in serialised

    def test_amount_float_preserved(self) -> None:
        """amount preserves the sign and value from the provider."""
        from schwab_mcp.transactions import MovementEntry

        entry = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Sold stock",
            amount=-1234.56,
        )
        assert entry.amount == -1234.56


# =============================================================================
# TransactionsResult model
# =============================================================================


class TestTransactionsResult:
    """TransactionsResult(outcome, detail, retryable, retrieved_at, ...)
    validated result model.

    Tests cover:
    - All outcome forms are constructable
    - movements list with MovementEntry items
    - Pagination fields (returned, has_more, next_offset, offset_echo)
    - Cross-validation rules 1–8
    """

    # ------------------------------------------------------------------
    # Basic outcome forms
    # ------------------------------------------------------------------

    def test_ok_with_movements(self) -> None:
        """ok outcome with non-empty movements is valid."""
        from schwab_mcp.transactions import MovementEntry, TransactionsResult

        entry = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Bought SPY",
            amount=5802.50,
        )
        result = TransactionsResult(
            outcome="ok",
            detail="history_retrieved",
            retryable=False,
            retrieved_at="2026-10-20T14:05:00+00:00",
            total_count=1,
            movements=[entry],
            returned=1,
            has_more=False,
            offset_echo=0,
        )
        assert result.outcome.value == "ok"
        assert len(result.movements) == 1
        assert result.movements[0].account_hash == "acc123"
        assert result.total_count == 1
        assert result.returned == 1
        assert result.has_more is False
        assert result.offset_echo == 0

    def test_ok_with_empty_movements_and_no_movements_detail(self) -> None:
        """ok outcome with empty movements and detail=no_movements is valid
        (cross-validation rule 1)."""
        from schwab_mcp.transactions import TransactionsResult

        result = TransactionsResult(
            outcome="ok",
            detail="no_movements",
            retryable=False,
            retrieved_at="2026-10-20T14:05:00+00:00",
            total_count=0,
            movements=[],
            returned=0,
            has_more=False,
            offset_echo=0,
        )
        assert result.outcome.value == "ok"
        assert result.movements == []
        assert result.detail.value == "no_movements"

    def test_ok_with_empty_movements_and_no_movements_for_instrument_detail(
        self,
    ) -> None:
        """ok outcome with empty movements and detail=no_movements_for_instrument
        is valid (cross-validation rule 1)."""
        from schwab_mcp.transactions import TransactionsResult

        result = TransactionsResult(
            outcome="ok",
            detail="no_movements_for_instrument",
            retryable=False,
            retrieved_at="2026-10-20T14:05:00+00:00",
            total_count=0,
            movements=[],
            returned=0,
            has_more=False,
            offset_echo=0,
        )
        assert result.outcome.value == "ok"
        assert result.movements == []
        assert result.detail.value == "no_movements_for_instrument"

    def test_transient_failure(self) -> None:
        """transient_failure outcome with retryable=True."""
        from schwab_mcp.transactions import TransactionsResult

        result = TransactionsResult(
            outcome="transient_failure",
            detail="provider_unreachable",
            retryable=True,
            retrieved_at="2026-10-20T14:05:00+00:00",
        )
        assert result.outcome.value == "transient_failure"
        assert result.retryable is True
        assert result.detail.value == "provider_unreachable"

    def test_reauth_required(self) -> None:
        """reauth_required outcome with retryable=False."""
        from schwab_mcp.transactions import TransactionsResult

        result = TransactionsResult(
            outcome="reauth_required",
            detail="reauth_needed",
            retryable=False,
            retrieved_at="2026-10-20T14:05:00+00:00",
        )
        assert result.outcome.value == "reauth_required"
        assert result.retryable is False
        assert result.detail.value == "reauth_needed"

    def test_partial_failure(self) -> None:
        """partial_failure outcome includes accounts_failed."""
        from schwab_mcp.transactions import TransactionsResult

        result = TransactionsResult(
            outcome="partial_failure",
            detail="account_failed",
            retryable=False,
            retrieved_at="2026-10-20T14:05:00+00:00",
            accounts_failed=[
                {"account_hash": "acc456", "detail": "provider_error"},
            ],
        )
        assert result.outcome.value == "partial_failure"
        assert len(result.accounts_failed) == 1
        assert result.accounts_failed[0].account_hash == "acc456"

    # ------------------------------------------------------------------
    # Cross-validation rule 1: outcome=ok + movements=[] ⇔ detail ∈ {no_movements, ...}
    # ------------------------------------------------------------------

    def test_ok_with_empty_movements_and_wrong_detail_raises(self) -> None:
        """outcome=ok + movements=[] with detail=history_retrieved raises."""
        from schwab_mcp.transactions import TransactionsResult

        with pytest.raises((ValueError, TypeError)):
            TransactionsResult(
                outcome="ok",
                detail="history_retrieved",
                retryable=False,
                retrieved_at="2026-10-20T14:05:00+00:00",
                total_count=0,
                movements=[],
                returned=0,
                has_more=False,
                offset_echo=0,
            )

    def test_ok_with_non_empty_movements_and_no_movements_detail_raises(self) -> None:
        """outcome=ok + movements non-empty with detail=no_movements raises."""
        from schwab_mcp.transactions import MovementEntry, TransactionsResult

        entry = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Bought SPY",
            amount=100.0,
        )
        with pytest.raises((ValueError, TypeError)):
            TransactionsResult(
                outcome="ok",
                detail="no_movements",
                retryable=False,
                retrieved_at="2026-10-20T14:05:00+00:00",
                total_count=1,
                movements=[entry],
                returned=1,
                has_more=False,
                offset_echo=0,
            )

    # ------------------------------------------------------------------
    # Cross-validation rule 2: has_more=true ⇒ next_offset present and returned==50
    # ------------------------------------------------------------------

    def test_has_more_true_with_next_offset_and_returned_50(self) -> None:
        """has_more=true with next_offset present and returned=50 is valid."""
        from schwab_mcp.transactions import MovementEntry, TransactionsResult

        entries = [
            MovementEntry(
                account_hash="acc123",
                occurred_at=f"2026-10-{d:02d}T12:00:00+00:00",
                category="trade",
                description=f"Entry {d}",
                amount=100.0,
            )
            for d in range(1, 51)
        ]
        result = TransactionsResult(
            outcome="ok",
            detail="history_retrieved",
            retryable=False,
            retrieved_at="2026-10-20T14:05:00+00:00",
            total_count=100,
            movements=entries,
            returned=50,
            has_more=True,
            next_offset=50,
            offset_echo=0,
        )
        assert result.has_more is True
        assert result.next_offset == 50
        assert result.returned == 50

    def test_has_more_true_without_next_offset_raises(self) -> None:
        """has_more=true without next_offset must raise (rule 2)."""
        from schwab_mcp.transactions import MovementEntry, TransactionsResult

        entries = [
            MovementEntry(
                account_hash="acc123",
                occurred_at=f"2026-10-{d:02d}T12:00:00+00:00",
                category="trade",
                description=f"Entry {d}",
                amount=100.0,
            )
            for d in range(1, 51)
        ]
        with pytest.raises((ValueError, TypeError)):
            TransactionsResult(
                outcome="ok",
                detail="history_retrieved",
                retryable=False,
                retrieved_at="2026-10-20T14:05:00+00:00",
                total_count=100,
                movements=entries,
                returned=50,
                has_more=True,
                offset_echo=0,
            )

    def test_has_more_true_with_returned_not_50_raises(self) -> None:
        """has_more=true with returned != 50 must raise (rule 2)."""
        from schwab_mcp.transactions import MovementEntry, TransactionsResult

        entries = [
            MovementEntry(
                account_hash="acc123",
                occurred_at=f"2026-10-{d:02d}T12:00:00+00:00",
                category="trade",
                description=f"Entry {d}",
                amount=100.0,
            )
            for d in range(1, 26)
        ]
        with pytest.raises((ValueError, TypeError)):
            TransactionsResult(
                outcome="ok",
                detail="history_retrieved",
                retryable=False,
                retrieved_at="2026-10-20T14:05:00+00:00",
                total_count=100,
                movements=entries,
                returned=25,
                has_more=True,
                next_offset=50,
                offset_echo=0,
            )

    # ------------------------------------------------------------------
    # Cross-validation rule 3: next_offset present ⇒ has_more=true
    # ------------------------------------------------------------------

    def test_next_offset_present_with_has_more_false_raises(self) -> None:
        """next_offset present with has_more=false must raise (rule 3)."""
        from schwab_mcp.transactions import MovementEntry, TransactionsResult

        entry = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Test",
            amount=100.0,
        )
        with pytest.raises((ValueError, TypeError)):
            TransactionsResult(
                outcome="ok",
                detail="history_retrieved",
                retryable=False,
                retrieved_at="2026-10-20T14:05:00+00:00",
                total_count=1,
                movements=[entry],
                returned=1,
                has_more=False,
                next_offset=1,
                offset_echo=0,
            )

    # ------------------------------------------------------------------
    # Cross-validation rule 4: accounts_failed present ⇔ outcome=partial_failure
    # ------------------------------------------------------------------

    def test_partial_failure_without_accounts_failed_raises(self) -> None:
        """partial_failure without accounts_failed must raise (rule 4)."""
        from schwab_mcp.transactions import TransactionsResult

        with pytest.raises((ValueError, TypeError)):
            TransactionsResult(
                outcome="partial_failure",
                detail="account_failed",
                retryable=False,
                retrieved_at="2026-10-20T14:05:00+00:00",
            )

    def test_ok_outcome_with_accounts_failed_raises(self) -> None:
        """ok outcome with accounts_failed present must raise (rule 4)."""
        from schwab_mcp.transactions import TransactionsResult

        with pytest.raises((ValueError, TypeError)):
            TransactionsResult(
                outcome="ok",
                detail="history_retrieved",
                retryable=False,
                retrieved_at="2026-10-20T14:05:00+00:00",
                total_count=1,
                movements=[],
                returned=0,
                has_more=False,
                offset_echo=0,
                accounts_failed=[
                    {"account_hash": "acc456", "detail": "provider_error"},
                ],
            )

    # ------------------------------------------------------------------
    # Cross-validation rule 5: retryable=true ⇔ outcome=transient_failure
    # ------------------------------------------------------------------

    def test_transient_failure_with_retryable_false_raises(self) -> None:
        """transient_failure with retryable=false must raise (rule 5)."""
        from schwab_mcp.transactions import TransactionsResult

        with pytest.raises((ValueError, TypeError)):
            TransactionsResult(
                outcome="transient_failure",
                detail="provider_unreachable",
                retryable=False,
                retrieved_at="2026-10-20T14:05:00+00:00",
            )

    def test_ok_outcome_with_retryable_true_raises(self) -> None:
        """ok outcome with retryable=true must raise (rule 5)."""
        from schwab_mcp.transactions import TransactionsResult

        with pytest.raises((ValueError, TypeError)):
            TransactionsResult(
                outcome="ok",
                detail="history_retrieved",
                retryable=True,
                retrieved_at="2026-10-20T14:05:00+00:00",
                total_count=1,
                movements=[],
                returned=0,
                has_more=False,
                offset_echo=0,
            )

    def test_reauth_required_with_retryable_true_raises(self) -> None:
        """reauth_required with retryable=true must raise (rule 5)."""
        from schwab_mcp.transactions import TransactionsResult

        with pytest.raises((ValueError, TypeError)):
            TransactionsResult(
                outcome="reauth_required",
                detail="reauth_needed",
                retryable=True,
                retrieved_at="2026-10-20T14:05:00+00:00",
            )

    def test_partial_failure_with_retryable_true_raises(self) -> None:
        """partial_failure with retryable=true must raise (rule 5)."""
        from schwab_mcp.transactions import TransactionsResult

        with pytest.raises((ValueError, TypeError)):
            TransactionsResult(
                outcome="partial_failure",
                detail="account_failed",
                retryable=True,
                retrieved_at="2026-10-20T14:05:00+00:00",
                accounts_failed=[
                    {"account_hash": "acc456", "detail": "provider_error"},
                ],
            )

    # ------------------------------------------------------------------
    # Cross-validation rule 6: no_movements_for_instrument ⇒ symbol in request
    # (representation: the model itself doesn't hold the request symbol,
    #  but the detail value is validated against the closed enum)
    # ------------------------------------------------------------------

    def test_no_movements_for_instrument_detail_requires_closed_enum(self) -> None:
        """The detail value is validated against the TransactionDetail
        closed enum; no_movements_for_instrument is a valid member."""
        from schwab_mcp.transactions import TransactionsResult

        result = TransactionsResult(
            outcome="ok",
            detail="no_movements_for_instrument",
            retryable=False,
            retrieved_at="2026-10-20T14:05:00+00:00",
            total_count=0,
            movements=[],
            returned=0,
            has_more=False,
            offset_echo=0,
        )
        assert result.detail.value == "no_movements_for_instrument"

    # ------------------------------------------------------------------
    # Cross-validation rule 7: retrieved_at ≥ occurred_at of all movements
    # ------------------------------------------------------------------

    def test_retrieved_at_later_than_occurred_at(self) -> None:
        """retrieved_at >= occurred_at of all movements is valid."""
        from schwab_mcp.transactions import MovementEntry, TransactionsResult

        entry = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Test",
            amount=100.0,
        )
        result = TransactionsResult(
            outcome="ok",
            detail="history_retrieved",
            retryable=False,
            retrieved_at="2026-10-20T14:05:00+00:00",
            total_count=1,
            movements=[entry],
            returned=1,
            has_more=False,
            offset_echo=0,
        )
        retrieved = datetime.fromisoformat(result.retrieved_at)
        occurred = datetime.fromisoformat(entry.occurred_at)
        assert retrieved >= occurred

    def test_retrieved_at_earlier_than_occurred_at_raises(self) -> None:
        """retrieved_at < occurred_at of a movement must raise (rule 7)."""
        from schwab_mcp.transactions import MovementEntry, TransactionsResult

        entry = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:05:00+00:00",
            category="trade",
            description="Test",
            amount=100.0,
        )
        with pytest.raises((ValueError, TypeError)):
            TransactionsResult(
                outcome="ok",
                detail="history_retrieved",
                retryable=False,
                retrieved_at="2026-10-20T14:03:11+00:00",
                total_count=1,
                movements=[entry],
                returned=1,
                has_more=False,
                offset_echo=0,
            )

    # ------------------------------------------------------------------
    # Cross-validation rule 8: No secrets in any field
    # ------------------------------------------------------------------

    def test_ok_json_has_no_secrets(self) -> None:
        """Serialised JSON for ok outcome contains no registered secrets."""
        from schwab_mcp.transactions import MovementEntry, TransactionsResult

        entry = MovementEntry(
            account_hash="hash123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Test",
            amount=100.0,
        )
        result = TransactionsResult(
            outcome="ok",
            detail="history_retrieved",
            retryable=False,
            retrieved_at="2026-10-20T14:05:00+00:00",
            total_count=1,
            movements=[entry],
            returned=1,
            has_more=False,
            offset_echo=0,
        )
        json_text = result.model_dump_json(exclude_none=True)
        # These are placeholder secrets that should never appear in output
        assert "TEST_APP_SECRET" not in json_text
        assert "fake-access-token" not in json_text
        assert "fake-refresh-token" not in json_text

    def test_partial_failure_json_has_no_secrets(self) -> None:
        """Serialised JSON for partial_failure contains no secrets."""
        from schwab_mcp.transactions import MovementEntry, TransactionsResult

        entry = MovementEntry(
            account_hash="hash123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Test",
            amount=100.0,
        )
        result = TransactionsResult(
            outcome="partial_failure",
            detail="account_failed",
            retryable=False,
            retrieved_at="2026-10-20T14:05:00+00:00",
            total_count=1,
            movements=[entry],
            returned=1,
            has_more=False,
            offset_echo=0,
            accounts_failed=[
                {"account_hash": "hash789", "detail": "provider_error"},
            ],
        )
        json_text = result.model_dump_json(exclude_none=True)
        assert "TEST_APP_SECRET" not in json_text
        assert "fake-access-token" not in json_text

    def test_transient_failure_json_has_no_secrets(self) -> None:
        """Serialised JSON for transient_failure contains no secrets."""
        from schwab_mcp.transactions import TransactionsResult

        result = TransactionsResult(
            outcome="transient_failure",
            detail="provider_unreachable",
            retryable=True,
            retrieved_at="2026-10-20T14:05:00+00:00",
        )
        json_text = result.model_dump_json(exclude_none=True)
        assert "TEST_APP_SECRET" not in json_text
        assert "fake-access-token" not in json_text

    def test_reauth_required_json_has_no_secrets(self) -> None:
        """Serialised JSON for reauth_required contains no secrets."""
        from schwab_mcp.transactions import TransactionsResult

        result = TransactionsResult(
            outcome="reauth_required",
            detail="reauth_needed",
            retryable=False,
            retrieved_at="2026-10-20T14:05:00+00:00",
        )
        json_text = result.model_dump_json(exclude_none=True)
        assert "TEST_APP_SECRET" not in json_text
        assert "fake-access-token" not in json_text

    # ------------------------------------------------------------------
    # General validation
    # ------------------------------------------------------------------

    def test_invalid_outcome_raises(self) -> None:
        """An outcome string not in TransactionOutcome raises."""
        from schwab_mcp.transactions import TransactionsResult

        with pytest.raises((ValueError, TypeError)):
            TransactionsResult(
                outcome="bogus_outcome",
                detail="history_retrieved",
                retryable=False,
                retrieved_at="2026-10-20T14:05:00+00:00",
                total_count=0,
                movements=[],
                returned=0,
                has_more=False,
                offset_echo=0,
            )

    def test_invalid_detail_raises(self) -> None:
        """A detail string not in TransactionDetail raises."""
        from schwab_mcp.transactions import TransactionsResult

        with pytest.raises((ValueError, TypeError)):
            TransactionsResult(
                outcome="ok",
                detail="bogus_detail",
                retryable=False,
                retrieved_at="2026-10-20T14:05:00+00:00",
                total_count=0,
                movements=[],
                returned=0,
                has_more=False,
                offset_echo=0,
            )

    def test_retrieved_at_iso8601_parseable(self) -> None:
        """retrieved_at must be an ISO-8601 string parseable by datetime."""
        from schwab_mcp.transactions import TransactionsResult

        result = TransactionsResult(
            outcome="ok",
            detail="no_movements",
            retryable=False,
            retrieved_at="2026-10-20T14:05:00+00:00",
            total_count=0,
            movements=[],
            returned=0,
            has_more=False,
            offset_echo=0,
        )
        dt = datetime.fromisoformat(result.retrieved_at)
        assert dt.tzinfo is not None  # Must be timezone-aware

    def test_ok_outcome_requires_pagination_fields(self) -> None:
        """ok outcome requires total_count, movements, returned, has_more,
        and offset_echo — omitting them raises."""
        from schwab_mcp.transactions import TransactionsResult

        with pytest.raises((ValueError, TypeError)):
            TransactionsResult(
                outcome="ok",
                detail="history_retrieved",
                retryable=False,
                retrieved_at="2026-10-20T14:05:00+00:00",
            )

    def test_partial_failure_detail_requires_account_failed(self) -> None:
        """partial_failure outcome must have detail=account_failed or it
        makes no sense — invalid pairings raise."""
        from schwab_mcp.transactions import TransactionsResult

        with pytest.raises((ValueError, TypeError)):
            TransactionsResult(
                outcome="partial_failure",
                detail="history_retrieved",
                retryable=False,
                retrieved_at="2026-10-20T14:05:00+00:00",
                accounts_failed=[
                    {"account_hash": "acc456", "detail": "provider_error"},
                ],
            )

    def test_ok_with_multiple_movements_chronological_order(self) -> None:
        """Movements are provided in chronological order (ascending)."""
        from schwab_mcp.transactions import MovementEntry, TransactionsResult

        entries = [
            MovementEntry(
                account_hash="acc123",
                occurred_at="2026-10-19T10:00:00+00:00",
                category="transfer",
                description="Transfer in",
                amount=1000.0,
            ),
            MovementEntry(
                account_hash="acc123",
                occurred_at="2026-10-20T14:03:11+00:00",
                category="trade",
                description="Bought SPY",
                amount=5802.50,
            ),
        ]
        result = TransactionsResult(
            outcome="ok",
            detail="history_retrieved",
            retryable=False,
            retrieved_at="2026-10-20T14:05:00+00:00",
            total_count=2,
            movements=entries,
            returned=2,
            has_more=False,
            offset_echo=0,
        )
        times = [datetime.fromisoformat(m.occurred_at) for m in result.movements]
        assert times == sorted(times)