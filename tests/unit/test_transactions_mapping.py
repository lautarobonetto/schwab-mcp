"""Failing unit tests for provider→model mapping (TDD red-phase).

Tests for ``map_provider_transactions(payload, extended)`` that will map
Schwab API transaction payloads into ``MovementEntry`` models.

The function does NOT exist yet — every test that reaches for it will fail
with ``ImportError`` / ``AttributeError`` (Red). Once implemented (T010),
all tests should pass.

References
----------
- specs/006-transaction-history/tasks.md: T006
- specs/006-transaction-history/research.md: R5 (type-to-category mapping)
- specs/006-transaction-history/data-model.md: §MovementEntry
"""

from __future__ import annotations

import pytest


# =============================================================================
# Fixture helpers
# =============================================================================


def _transaction(
    type_name: str = "TRADE",
    description: str = "Sample transaction",
    net_amount: float = 100.0,
    transaction_date: str = "2026-10-20T14:03:11+00:00",
    settlement_date: str | None = "2026-10-22",
    fees: float | None = None,
    commissions: float | None = None,
    currency: str | None = None,
    account_hash: str = "acc123",
    activity_id: str = "act0001",
    instrument: dict | None = None,
    transfer_items: list[dict] | None = None,
) -> dict:
    """Build a single transaction dict as the provider would return it."""
    tx: dict = {
        "activityId": activity_id,
        "type": type_name,
        "transactionDate": transaction_date,
        "description": description,
        "netAmount": net_amount,
        "accountHash": account_hash,
    }
    if settlement_date is not None:
        tx["settlementDate"] = settlement_date
    if fees is not None:
        tx["fees"] = fees
    if commissions is not None:
        tx["commission"] = commissions
    if currency is not None:
        tx["currency"] = currency
    if instrument is not None:
        tx["instrument"] = instrument
    if transfer_items is not None:
        tx["transferItems"] = transfer_items
    return tx


def _instrument(symbol: str = "AAPL", instrument_type: str = "EQUITY") -> dict:
    """Build an instrument sub-dict."""
    return {
        "symbol": symbol,
        "instrumentType": instrument_type,
    }


def _payload(
    transactions: list[dict],
    retrieved_at: str = "2026-10-20T14:05:00+00:00",
) -> dict:
    """Wrap a list of transactions into a fake provider payload."""
    return {
        "transactions": transactions,
        "retrieved_at": retrieved_at,
    }


# =============================================================================
# Test class: Type-to-category mapping for all 15 upstream types
# =============================================================================


class TestMapProviderTransactionsCategory:
    """``map_provider_transactions(payload)`` maps each upstream type to the
    correct ``MovementCategory`` per research R5 / data-model.md.

    Each test verifies:
    - category is correctly mapped
    - occurred_at is extracted from the payload
    - amount is preserved (sign from provider, not reinterpreted)
    - currency defaults to "USD" (or uses provider's currency field)
    - account_hash is passed through
    """

    # ------------------------------------------------------------------
    # TRADE (with instrument: symbol, instrument_type)
    # ------------------------------------------------------------------

    def test_trade_maps_to_trade_category(self) -> None:
        """A TRADE transaction maps to category='trade' with instrument fields."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="TRADE",
                    description="Bought 10 AAPL at 231.89",
                    net_amount=-2318.90,
                    transaction_date="2026-10-20T14:03:11+00:00",
                    account_hash="acc123",
                    activity_id="act001",
                    instrument=_instrument(symbol="AAPL", instrument_type="EQUITY"),
                    fees=0.0,
                    commissions=0.0,
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        entry = result[0]
        assert entry.category.value == "trade"
        assert entry.occurred_at == "2026-10-20T14:03:11+00:00"
        assert entry.amount == -2318.90
        assert entry.currency == "USD"
        assert entry.account_hash == "acc123"
        assert entry.symbol == "AAPL"
        assert entry.instrument_type == "EQUITY"

    # ------------------------------------------------------------------
    # RECEIVE_AND_DELIVER → transfer
    # ------------------------------------------------------------------

    def test_receive_and_deliver_maps_to_transfer(self) -> None:
        """RECEIVE_AND_DELIVER maps to category='transfer'."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="RECEIVE_AND_DELIVER",
                    description="Free delivery of shares",
                    net_amount=5000.0,
                    transaction_date="2026-10-19T10:00:00+00:00",
                    account_hash="acc123",
                    activity_id="act002",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        entry = result[0]
        assert entry.category.value == "transfer"
        assert entry.occurred_at == "2026-10-19T10:00:00+00:00"
        assert entry.amount == 5000.0
        assert entry.account_hash == "acc123"

    # ------------------------------------------------------------------
    # ACH_RECEIPT → transfer
    # ------------------------------------------------------------------

    def test_ach_receipt_maps_to_transfer(self) -> None:
        """ACH_RECEIPT maps to category='transfer'."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="ACH_RECEIPT",
                    description="ACH deposit",
                    net_amount=1000.0,
                    transaction_date="2026-10-18T09:00:00+00:00",
                    account_hash="acc456",
                    activity_id="act003",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        assert result[0].category.value == "transfer"
        assert result[0].amount == 1000.0

    # ------------------------------------------------------------------
    # ACH_DISBURSEMENT → transfer
    # ------------------------------------------------------------------

    def test_ach_disbursement_maps_to_transfer(self) -> None:
        """ACH_DISBURSEMENT maps to category='transfer'."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="ACH_DISBURSEMENT",
                    description="ACH withdrawal",
                    net_amount=-500.0,
                    transaction_date="2026-10-17T14:00:00+00:00",
                    account_hash="acc123",
                    activity_id="act004",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        assert result[0].category.value == "transfer"
        assert result[0].amount == -500.0

    # ------------------------------------------------------------------
    # CASH_RECEIPT → transfer
    # ------------------------------------------------------------------

    def test_cash_receipt_maps_to_transfer(self) -> None:
        """CASH_RECEIPT maps to category='transfer'."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="CASH_RECEIPT",
                    description="Cash deposit",
                    net_amount=2000.0,
                    transaction_date="2026-10-16T12:00:00+00:00",
                    account_hash="acc123",
                    activity_id="act005",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        assert result[0].category.value == "transfer"
        assert result[0].amount == 2000.0

    # ------------------------------------------------------------------
    # CASH_DISBURSEMENT → transfer
    # ------------------------------------------------------------------

    def test_cash_disbursement_maps_to_transfer(self) -> None:
        """CASH_DISBURSEMENT maps to category='transfer'."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="CASH_DISBURSEMENT",
                    description="Cash withdrawal",
                    net_amount=-300.0,
                    transaction_date="2026-10-15T08:00:00+00:00",
                    account_hash="acc123",
                    activity_id="act006",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        assert result[0].category.value == "transfer"
        assert result[0].amount == -300.0

    # ------------------------------------------------------------------
    # ELECTRONIC_FUND → transfer
    # ------------------------------------------------------------------

    def test_electronic_fund_maps_to_transfer(self) -> None:
        """ELECTRONIC_FUND maps to category='transfer'."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="ELECTRONIC_FUND",
                    description="EFT transfer",
                    net_amount=1500.0,
                    transaction_date="2026-10-14T11:00:00+00:00",
                    account_hash="acc123",
                    activity_id="act007",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        assert result[0].category.value == "transfer"
        assert result[0].amount == 1500.0

    # ------------------------------------------------------------------
    # WIRE_IN → transfer
    # ------------------------------------------------------------------

    def test_wire_in_maps_to_transfer(self) -> None:
        """WIRE_IN maps to category='transfer'."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="WIRE_IN",
                    description="Wire transfer received",
                    net_amount=10000.0,
                    transaction_date="2026-10-13T15:30:00+00:00",
                    account_hash="acc456",
                    activity_id="act008",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        assert result[0].category.value == "transfer"
        assert result[0].amount == 10000.0

    # ------------------------------------------------------------------
    # WIRE_OUT → transfer
    # ------------------------------------------------------------------

    def test_wire_out_maps_to_transfer(self) -> None:
        """WIRE_OUT maps to category='transfer'."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="WIRE_OUT",
                    description="Wire transfer sent",
                    net_amount=-2500.0,
                    transaction_date="2026-10-12T09:45:00+00:00",
                    account_hash="acc123",
                    activity_id="act009",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        assert result[0].category.value == "transfer"
        assert result[0].amount == -2500.0

    # ------------------------------------------------------------------
    # DIVIDEND_OR_INTEREST → dividend_or_interest
    # ------------------------------------------------------------------

    def test_dividend_or_interest_maps_to_dividend_or_interest(self) -> None:
        """DIVIDEND_OR_INTEREST maps to category='dividend_or_interest'."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="DIVIDEND_OR_INTEREST",
                    description="AAPL dividend payment",
                    net_amount=45.00,
                    transaction_date="2026-10-11T00:00:00+00:00",
                    account_hash="acc123",
                    activity_id="act010",
                    instrument=_instrument(symbol="AAPL", instrument_type="EQUITY"),
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        assert result[0].category.value == "dividend_or_interest"
        assert result[0].amount == 45.00
        assert result[0].symbol == "AAPL"

    # ------------------------------------------------------------------
    # JOURNAL → adjustment
    # ------------------------------------------------------------------

    def test_journal_maps_to_adjustment(self) -> None:
        """JOURNAL maps to category='adjustment'."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="JOURNAL",
                    description="Journal entry",
                    net_amount=0.0,
                    transaction_date="2026-10-10T08:00:00+00:00",
                    account_hash="acc123",
                    activity_id="act011",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        assert result[0].category.value == "adjustment"
        assert result[0].amount == 0.0

    # ------------------------------------------------------------------
    # SMA_ADJUSTMENT → adjustment
    # ------------------------------------------------------------------

    def test_sma_adjustment_maps_to_adjustment(self) -> None:
        """SMA_ADJUSTMENT maps to category='adjustment'."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="SMA_ADJUSTMENT",
                    description="SMA adjustment",
                    net_amount=500.0,
                    transaction_date="2026-10-09T10:00:00+00:00",
                    account_hash="acc123",
                    activity_id="act012",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        assert result[0].category.value == "adjustment"
        assert result[0].amount == 500.0

    # ------------------------------------------------------------------
    # MEMORANDUM → other
    # ------------------------------------------------------------------

    def test_memorandum_maps_to_other(self) -> None:
        """MEMORANDUM maps to category='other'."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="MEMORANDUM",
                    description="Memo entry",
                    net_amount=0.0,
                    transaction_date="2026-10-08T12:00:00+00:00",
                    account_hash="acc123",
                    activity_id="act013",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        assert result[0].category.value == "other"
        assert result[0].amount == 0.0

    # ------------------------------------------------------------------
    # MARGIN_CALL → other
    # ------------------------------------------------------------------

    def test_margin_call_maps_to_other(self) -> None:
        """MARGIN_CALL maps to category='other'."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="MARGIN_CALL",
                    description="Margin call",
                    net_amount=-1000.0,
                    transaction_date="2026-10-07T09:00:00+00:00",
                    account_hash="acc123",
                    activity_id="act014",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        assert result[0].category.value == "other"
        assert result[0].amount == -1000.0

    # ------------------------------------------------------------------
    # MONEY_MARKET → other
    # ------------------------------------------------------------------

    def test_money_market_maps_to_other(self) -> None:
        """MONEY_MARKET maps to category='other'."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="MONEY_MARKET",
                    description="Money market interest",
                    net_amount=12.50,
                    transaction_date="2026-10-06T00:00:00+00:00",
                    account_hash="acc123",
                    activity_id="act015",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        assert result[0].category.value == "other"
        assert result[0].amount == 12.50


# =============================================================================
# Currency behavior
# =============================================================================


class TestMapProviderTransactionsCurrency:
    """Currency is extracted from the provider payload when exposed,
    otherwise defaults to ``"USD"`` (research R10 / data-model.md).

    Tests cover:
    - Currency defaults to "USD" when provider does not expose it
    - Currency uses provider's value when exposed
    """

    def test_currency_defaults_to_usd(self) -> None:
        """Without a currency field in the provider payload, ``currency``
        defaults to ``"USD"``."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="TRADE",
                    net_amount=100.0,
                    account_hash="acc123",
                    activity_id="act020",
                    instrument=_instrument(symbol="SPY", instrument_type="ETF"),
                    # no 'currency' key
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        assert result[0].currency == "USD"

    def test_currency_uses_provider_value_when_exposed(self) -> None:
        """When the provider payload includes a ``currency`` field, it is
        used as the entry's currency."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="TRADE",
                    net_amount=100.0,
                    currency="EUR",
                    account_hash="acc123",
                    activity_id="act021",
                    instrument=_instrument(symbol="AAPL", instrument_type="EQUITY"),
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        assert result[0].currency == "EUR"


# =============================================================================
# Instrument fields (symbol / instrument_type)
# =============================================================================


class TestMapProviderTransactionsInstrument:
    """``symbol`` and ``instrument_type`` are present ONLY when the provider
    payload contains an ``instrument`` sub-object.

    Tests cover:
    - With instrument: both fields present
    - Without instrument: both fields absent from serialised output
    - Null instrument: treated as no instrument
    """

    def test_symbol_and_instrument_type_present_with_instrument(self) -> None:
        """When the payload has an ``instrument``, ``symbol`` and
        ``instrument_type`` are populated."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="TRADE",
                    description="Sold 5 TSLA",
                    net_amount=7500.0,
                    account_hash="acc123",
                    activity_id="act030",
                    instrument=_instrument(symbol="TSLA", instrument_type="EQUITY"),
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        entry = result[0]
        assert entry.symbol == "TSLA"
        assert entry.instrument_type == "EQUITY"

    def test_symbol_and_instrument_type_absent_without_instrument(self) -> None:
        """Without an instrument in the payload, ``symbol`` and
        ``instrument_type`` are omitted from serialised output."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="ACH_RECEIPT",
                    description="ACH deposit",
                    net_amount=1000.0,
                    account_hash="acc123",
                    activity_id="act031",
                    # no instrument key
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        entry = result[0]
        serialised = entry.model_dump(exclude_none=True)
        assert "symbol" not in serialised
        assert "instrument_type" not in serialised

    def test_null_instrument_no_symbol(self) -> None:
        """When instrument is null/None, no symbol or instrument_type."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="TRADE",
                    description="Trade without instrument",
                    net_amount=100.0,
                    account_hash="acc123",
                    activity_id="act032",
                    instrument=None,
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        entry = result[0]
        serialised = entry.model_dump(exclude_none=True)
        assert "symbol" not in serialised
        assert "instrument_type" not in serialised


# =============================================================================
# Description truncation
# =============================================================================


class TestMapProviderTransactionsDescription:
    """``description`` is truncated to 80 characters (FR-007 / data-model.md).

    Tests cover:
    - Description exactly 80 chars: not truncated
    - Description > 80 chars: truncated to 80
    - Description < 80 chars: unchanged
    """

    def test_description_exactly_80_chars_not_truncated(self) -> None:
        """A description of exactly 80 characters is NOT truncated."""
        from schwab_mcp.transactions import map_provider_transactions

        desc = "A" * 80
        payload = _payload(
            transactions=[
                _transaction(
                    type_name="TRADE",
                    description=desc,
                    net_amount=100.0,
                    account_hash="acc123",
                    activity_id="act040",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        assert len(result[0].description) == 80
        assert result[0].description == desc

    def test_description_over_80_chars_truncated(self) -> None:
        """A description longer than 80 characters is truncated to 80."""
        from schwab_mcp.transactions import map_provider_transactions

        long_desc = "B" * 200
        payload = _payload(
            transactions=[
                _transaction(
                    type_name="TRADE",
                    description=long_desc,
                    net_amount=100.0,
                    account_hash="acc123",
                    activity_id="act041",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        assert len(result[0].description) == 80

    def test_description_short_not_truncated(self) -> None:
        """A description <= 80 characters is unchanged."""
        from schwab_mcp.transactions import map_provider_transactions

        short_desc = "Short description"
        payload = _payload(
            transactions=[
                _transaction(
                    type_name="TRADE",
                    description=short_desc,
                    net_amount=100.0,
                    account_hash="acc123",
                    activity_id="act042",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        assert result[0].description == short_desc


# =============================================================================
# Extended passthrough
# =============================================================================


class TestMapProviderTransactionsExtended:
    """When ``extended=True``, each entry includes an ``extended`` dict with
    provider passthrough fields: type, full description, fees, commissions,
    netAmount, settlementDate, transferItems, activityId.

    When ``extended`` is not set (or False), no extended field.
    """

    def test_extended_passthrough_with_trade(self) -> None:
        """extended=True includes passthrough fields for a TRADE entry."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="TRADE",
                    description="Bought 10 AAPL at 231.89",
                    net_amount=-2318.90,
                    transaction_date="2026-10-20T14:03:11+00:00",
                    settlement_date="2026-10-22",
                    fees=1.50,
                    commissions=0.75,
                    account_hash="acc123",
                    activity_id="act050",
                    instrument=_instrument(symbol="AAPL", instrument_type="EQUITY"),
                ),
            ],
        )

        result = map_provider_transactions(payload, extended=True)
        assert len(result) == 1
        entry = result[0]
        assert entry.extended is not None
        assert entry.extended["type"] == "TRADE"
        assert entry.extended["description"] == "Bought 10 AAPL at 231.89"
        assert entry.extended["fees"] == 1.50
        assert entry.extended["commission"] == 0.75
        assert entry.extended["netAmount"] == -2318.90
        assert entry.extended["settlementDate"] == "2026-10-22"
        assert entry.extended["activityId"] == "act050"

    def test_extended_passthrough_with_transfer(self) -> None:
        """extended=True includes transferItems for transfer types."""
        from schwab_mcp.transactions import map_provider_transactions

        transfer_items = [
            {
                "action": "RECEIVE",
                "amount": 5000.0,
                "description": "ACH deposit",
            },
        ]

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="ACH_RECEIPT",
                    description="ACH deposit",
                    net_amount=5000.0,
                    transaction_date="2026-10-19T10:00:00+00:00",
                    account_hash="acc123",
                    activity_id="act051",
                    transfer_items=transfer_items,
                ),
            ],
        )

        result = map_provider_transactions(payload, extended=True)
        assert len(result) == 1
        entry = result[0]
        assert entry.extended is not None
        assert entry.extended["type"] == "ACH_RECEIPT"
        assert entry.extended["transferItems"] == transfer_items

    def test_extended_default_false(self) -> None:
        """Without extended=True, no extended key in serialised entries."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="TRADE",
                    description="Bought SPY",
                    net_amount=5802.50,
                    account_hash="acc123",
                    activity_id="act052",
                    instrument=_instrument(symbol="SPY", instrument_type="ETF"),
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        serialised = result[0].model_dump(exclude_none=True)
        assert "extended" not in serialised


# =============================================================================
# Edge cases
# =============================================================================


class TestMapProviderTransactionsEdgeCases:
    """Edge case coverage for ``map_provider_transactions``.

    Tests cover:
    - Empty payload → empty list
    - Null fields in payload (null description, null netAmount, etc.)
    - Missing instrument (no symbol/instrument_type)
    - Unknown type → category 'other'
    - Amount sign preserved as reported by provider
    - Multiple transactions of different types
    """

    def test_empty_payload_returns_empty_list(self) -> None:
        """An empty payload (no transactions) returns an empty list."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(transactions=[])
        result = map_provider_transactions(payload)
        assert result == []

    def test_payload_with_no_transactions_key_returns_empty_list(self) -> None:
        """A payload without a ``transactions`` key returns an empty list."""
        from schwab_mcp.transactions import map_provider_transactions

        result = map_provider_transactions({})
        assert result == []

    def test_null_description(self) -> None:
        """A null/None description is handled gracefully (converted to empty
        string or similar)."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="MEMORANDUM",
                    description=None,  # type: ignore[arg-type]
                    net_amount=0.0,
                    account_hash="acc123",
                    activity_id="act060",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        # description should be a usable string (empty or "None")
        assert isinstance(result[0].description, str)

    def test_null_net_amount(self) -> None:
        """A null/None netAmount defaults to 0.0 or is handled gracefully."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="MEMORANDUM",
                    description="Memo with no amount",
                    net_amount=None,  # type: ignore[arg-type]
                    account_hash="acc123",
                    activity_id="act061",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        assert isinstance(result[0].amount, float)

    def test_null_transaction_date(self) -> None:
        """A null/None transactionDate is handled gracefully."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="MEMORANDUM",
                    description="Memo with no date",
                    net_amount=0.0,
                    transaction_date=None,  # type: ignore[arg-type]
                    account_hash="acc123",
                    activity_id="act062",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        # Should produce some string (empty or a fallback)
        assert isinstance(result[0].occurred_at, str)

    def test_missing_instrument_no_symbol(self) -> None:
        """A transaction without an instrument key has no symbol or
        instrument_type in the output, even if the type is TRADE."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="TRADE",
                    description="Trade without instrument detail",
                    net_amount=100.0,
                    account_hash="acc123",
                    activity_id="act063",
                    # no instrument
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        entry = result[0]
        serialised = entry.model_dump(exclude_none=True)
        assert "symbol" not in serialised
        assert "instrument_type" not in serialised

    def test_unknown_type_maps_to_other(self) -> None:
        """An unknown/unsupported transaction type maps to category 'other'."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="UNKNOWN_FUTURE_TYPE",
                    description="Some new type from the provider",
                    net_amount=100.0,
                    transaction_date="2026-10-05T12:00:00+00:00",
                    account_hash="acc123",
                    activity_id="act064",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 1
        assert result[0].category.value == "other"
        assert result[0].amount == 100.0

    def test_amount_sign_preserved_positive(self) -> None:
        """A positive netAmount results in a positive amount."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="ACH_RECEIPT",
                    description="Deposit",
                    net_amount=500.0,
                    account_hash="acc123",
                    activity_id="act065",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert result[0].amount > 0
        assert result[0].amount == 500.0

    def test_amount_sign_preserved_negative(self) -> None:
        """A negative netAmount (outflow) remains negative — not reinterpreted."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="WIRE_OUT",
                    description="Wire out",
                    net_amount=-2500.0,
                    account_hash="acc123",
                    activity_id="act066",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert result[0].amount < 0
        assert result[0].amount == -2500.0

    def test_multiple_transactions_mixed_types(self) -> None:
        """Multiple transactions of various types are all mapped correctly."""
        from schwab_mcp.transactions import map_provider_transactions

        payload = _payload(
            transactions=[
                _transaction(
                    type_name="TRADE",
                    description="Bought AAPL",
                    net_amount=-2318.90,
                    transaction_date="2026-10-20T14:03:11+00:00",
                    account_hash="acc123",
                    activity_id="act070",
                    instrument=_instrument(symbol="AAPL", instrument_type="EQUITY"),
                ),
                _transaction(
                    type_name="DIVIDEND_OR_INTEREST",
                    description="AAPL dividend",
                    net_amount=45.00,
                    transaction_date="2026-10-15T00:00:00+00:00",
                    account_hash="acc123",
                    activity_id="act071",
                ),
                _transaction(
                    type_name="ACH_RECEIPT",
                    description="Deposit",
                    net_amount=1000.00,
                    transaction_date="2026-10-10T09:00:00+00:00",
                    account_hash="acc456",
                    activity_id="act072",
                ),
            ],
        )

        result = map_provider_transactions(payload)
        assert len(result) == 3

        categories = {e.category.value for e in result}
        assert "trade" in categories
        assert "dividend_or_interest" in categories
        assert "transfer" in categories

        account_hashes = {e.account_hash for e in result}
        assert "acc123" in account_hashes
        assert "acc456" in account_hashes

        # All amounts preserved
        amounts = {e.amount for e in result}
        assert -2318.90 in amounts
        assert 45.00 in amounts
        assert 1000.00 in amounts