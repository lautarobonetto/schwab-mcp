"""Failing unit tests for PositionEntry and PositionsResult models.

These are TDD red-phase tests: the source module (schwab_mcp.positions) does
not exist yet, so every test will fail with ModuleNotFoundError / ImportError.
Once implemented, all tests should pass.

References
----------
- data-model.md §1–§2: entity definitions and validation rules.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest


# =============================================================================
# PositionEntry model
# =============================================================================


class TestPositionEntry:
    """PositionEntry(account_hash, symbol, instrument_type, description, ...)
    validated data model.

    Tests cover:
    - Enum validation for instrument_type and outcome
    - Unique identity (account_hash, symbol)
    - quantity ≠ 0 with sign (long positive, short negative)
    - Option fields present ⇔ instrument_type == "OPTION"
    - price_timestamp/retrieved_at ISO-8601 parseable
    """

    def test_position_entry_with_all_curated_fields(self) -> None:
        """A complete PositionEntry with all curated fields passes validation."""
        from schwab_mcp.positions import PositionEntry

        entry = PositionEntry(
            account_hash="acc123",
            symbol="SPY",
            instrument_type="EQUITY",
            description="SPDR S&P 500 ETF Trust",
            quantity=10.0,
            average_price=580.25,
            market_value=5910.0,
            unrealized_pl=107.5,
            price_timestamp="2026-10-20T14:03:11+00:00",
        )
        assert entry.account_hash == "acc123"
        assert entry.symbol == "SPY"
        assert entry.instrument_type == "EQUITY"
        assert entry.quantity == 10.0
        assert entry.average_price == 580.25

    def test_negative_quantity_short_position(self) -> None:
        """A short position has a negative quantity (longQuantity - shortQuantity < 0)."""
        from schwab_mcp.positions import PositionEntry

        entry = PositionEntry(
            account_hash="acc456",
            symbol="AAPL",
            instrument_type="EQUITY",
            description="Apple stock",
            quantity=-5.0,
            average_price=150.0,
            market_value=750.0,
            unrealized_pl=0.0,
            price_timestamp="2026-10-20T14:03:11+00:00",
        )
        assert entry.quantity < 0

    def test_zero_quantity_raises(self) -> None:
        """A quantity of exactly 0 must raise a validation error (FR-015)."""
        from schwab_mcp.positions import PositionEntry

        with pytest.raises((ValueError, TypeError)):
            PositionEntry(
                account_hash="acc789",
                symbol="TSLA",
                instrument_type="EQUITY",
                description="Tesla stock",
                quantity=0.0,
                average_price=200.0,
                market_value=0.0,
                unrealized_pl=0.0,
                price_timestamp="2026-10-20T14:03:11+00:00",
            )

    def test_option_fields_present_for_option_type(self) -> None:
        """For instrument_type="OPTION", option-specific fields are required."""
        from schwab_mcp.positions import PositionEntry

        entry = PositionEntry(
            account_hash="acc123",
            symbol="SPY",
            instrument_type="OPTION",
            description="SPY Call Option",
            quantity=10.0,
            average_price=5.0,
            market_value=50.0,
            unrealized_pl=0.0,
            price_timestamp="2026-10-20T14:03:11+00:00",
            underlying_symbol="SPY",
            put_call="CALL",
            strike_price=580.0,
            expiration_date="2026-12-20",
        )
        assert entry.underlying_symbol == "SPY"
        assert entry.put_call == "CALL"
        assert entry.strike_price == 580.0
        assert entry.expiration_date == "2026-12-20"

    def test_option_fields_absent_for_non_option(self) -> None:
        """For instrument_type != "OPTION", option-specific fields must be absent
        from the serialised dict (exclude_none)."""
        from schwab_mcp.positions import PositionEntry

        entry = PositionEntry(
            account_hash="acc123",
            symbol="SPY",
            instrument_type="EQUITY",
            description="SPDR S&P 500 ETF Trust",
            quantity=10.0,
            average_price=580.25,
            market_value=5910.0,
            unrealized_pl=107.5,
            price_timestamp="2026-10-20T14:03:11+00:00",
        )
        # These fields should be omitted from the serialised output
        serialised = entry.model_dump(exclude_none=True)
        assert "underlying_symbol" not in serialised
        assert "put_call" not in serialised
        assert "strike_price" not in serialised
        assert "expiration_date" not in serialised

    def test_price_timestamp_iso8601_parseable(self) -> None:
        """price_timestamp must be an ISO-8601 string parseable by datetime."""
        from schwab_mcp.positions import PositionEntry

        entry = PositionEntry(
            account_hash="acc123",
            symbol="SPY",
            instrument_type="EQUITY",
            description="Test",
            quantity=10.0,
            average_price=100.0,
            market_value=1000.0,
            unrealized_pl=0.0,
            price_timestamp="2026-10-20T14:03:11+00:00",
        )
        dt = datetime.fromisoformat(entry.price_timestamp)
        assert dt.tzinfo is not None  # Must be timezone-aware

    def test_invalid_instrument_type_raises(self) -> None:
        """An instrument_type not in the allowed enum raises a validation error."""
        from schwab_mcp.positions import PositionEntry

        with pytest.raises((ValueError, TypeError)):
            PositionEntry(
                account_hash="acc123",
                symbol="SPY",
                instrument_type="INVALID_TYPE",
                description="Invalid",
                quantity=10.0,
                average_price=100.0,
                market_value=1000.0,
                unrealized_pl=0.0,
                price_timestamp="2026-10-20T14:03:11+00:00",
            )

    def test_invalid_put_call_raises(self) -> None:
        """put_call must be 'PUT' or 'CALL'."""
        from schwab_mcp.positions import PositionEntry

        with pytest.raises((ValueError, TypeError)):
            PositionEntry(
                account_hash="acc123",
                symbol="SPY",
                instrument_type="OPTION",
                description="Test Option",
                quantity=10.0,
                average_price=5.0,
                market_value=50.0,
                unrealized_pl=0.0,
                price_timestamp="2026-10-20T14:03:11+00:00",
                underlying_symbol="SPY",
                put_call="INVALID",
                strike_price=580.0,
                expiration_date="2026-12-20",
            )

    def test_account_hash_non_empty(self) -> None:
        """account_hash must be a non-empty string."""
        from schwab_mcp.positions import PositionEntry

        with pytest.raises((ValueError, TypeError)):
            PositionEntry(
                account_hash="",
                symbol="SPY",
                instrument_type="EQUITY",
                description="Test",
                quantity=10.0,
                average_price=100.0,
                market_value=1000.0,
                unrealized_pl=0.0,
                price_timestamp="2026-10-20T14:03:11+00:00",
            )

    def test_negative_average_price_raises(self) -> None:
        """average_price must be >= 0."""
        from schwab_mcp.positions import PositionEntry

        with pytest.raises((ValueError, TypeError)):
            PositionEntry(
                account_hash="acc123",
                symbol="SPY",
                instrument_type="EQUITY",
                description="Test",
                quantity=10.0,
                average_price=-1.0,
                market_value=1000.0,
                unrealized_pl=0.0,
                price_timestamp="2026-10-20T14:03:11+00:00",
            )


# =============================================================================
# PositionsResult model
# =============================================================================


class TestPositionsResult:
    """PositionsResult(outcome, positions, ...) validated result model.

    Tests cover:
    - outcome ∈ {ok, partial_failure, transient_failure, reauth_required}
    - positions: [] válido solo con outcome: "ok"
    - retryable: true solo con transient_failure
    - accounts_failed solo con partial_failure
    - detail vocabulary closed
    - retrieved_at ISO-8601 parseable
    """

    def test_ok_outcome_with_positions(self) -> None:
        """ok outcome with non-empty positions is valid."""
        from schwab_mcp.positions import PositionEntry, PositionsResult

        entry = PositionEntry(
            account_hash="acc123",
            symbol="SPY",
            instrument_type="EQUITY",
            description="SPDR S&P 500 ETF Trust",
            quantity=10.0,
            average_price=580.25,
            market_value=5910.0,
            unrealized_pl=107.5,
            price_timestamp="2026-10-20T14:03:11+00:00",
        )
        result = PositionsResult(
            outcome="ok",
            positions=[entry],
            detail="data_received",
            retryable=False,
            retrieved_at="2026-10-20T14:03:11+00:00",
        )
        assert result.outcome == "ok"
        assert len(result.positions) == 1
        assert result.detail == "data_received"
        assert result.retryable is False

    def test_ok_outcome_with_empty_positions(self) -> None:
        """ok outcome with [] is valid (FR-005: no positions, not an error)."""
        from schwab_mcp.positions import PositionsResult

        result = PositionsResult(
            outcome="ok",
            positions=[],
            detail="no_positions",
            retryable=False,
            retrieved_at="2026-10-20T14:03:11+00:00",
        )
        assert result.outcome == "ok"
        assert result.positions == []

    def test_transient_failure_with_retryable_true(self) -> None:
        """transient_failure outcome must have retryable=True."""
        from schwab_mcp.positions import PositionsResult

        result = PositionsResult(
            outcome="transient_failure",
            positions=[],
            detail="provider_unreachable",
            retryable=True,
            retrieved_at="2026-10-20T14:03:11+00:00",
        )
        assert result.outcome == "transient_failure"
        assert result.retryable is True

    def test_transient_failure_retryable_false_raises(self) -> None:
        """transient_failure with retryable=False must raise."""
        from schwab_mcp.positions import PositionsResult

        with pytest.raises((ValueError, TypeError)):
            PositionsResult(
                outcome="transient_failure",
                positions=[],
                detail="provider_unreachable",
                retryable=False,
                retrieved_at="2026-10-20T14:03:11+00:00",
            )

    def test_reauth_required_outcome(self) -> None:
        """reauth_required outcome must have retryable=False."""
        from schwab_mcp.positions import PositionsResult

        result = PositionsResult(
            outcome="reauth_required",
            positions=[],
            detail="reauth_needed",
            retryable=False,
            retrieved_at="2026-10-20T14:03:11+00:00",
        )
        assert result.outcome == "reauth_required"
        assert result.retryable is False

    def test_partial_failure_with_accounts_failed(self) -> None:
        """partial_failure must include accounts_failed list."""
        from schwab_mcp.positions import PositionsResult

        result = PositionsResult(
            outcome="partial_failure",
            positions=[],
            detail="account_failed",
            retryable=False,
            retrieved_at="2026-10-20T14:03:11+00:00",
            accounts_failed=[
                {"account_hash": "acc456", "detail": "provider_error"},
            ],
        )
        assert result.outcome == "partial_failure"
        assert len(result.accounts_failed) == 1
        assert result.accounts_failed[0].account_hash == "acc456"

    def test_partial_failure_without_accounts_failed_raises(self) -> None:
        """partial_failure without accounts_failed must raise."""
        from schwab_mcp.positions import PositionsResult

        with pytest.raises((ValueError, TypeError)):
            PositionsResult(
                outcome="partial_failure",
                positions=[],
                detail="account_failed",
                retryable=False,
                retrieved_at="2026-10-20T14:03:11+00:00",
            )

    def test_invalid_outcome_raises(self) -> None:
        """An outcome string not in the enum raises a validation error."""
        from schwab_mcp.positions import PositionsResult

        with pytest.raises((ValueError, TypeError)):
            PositionsResult(
                outcome="bogus_outcome",
                positions=[],
                detail="data_received",
                retryable=False,
                retrieved_at="2026-10-20T14:03:11+00:00",
            )

    def test_positions_with_transient_failure_raises(self) -> None:
        """Non-empty positions with transient_failure must raise."""
        from schwab_mcp.positions import PositionEntry, PositionsResult

        entry = PositionEntry(
            account_hash="acc123",
            symbol="SPY",
            instrument_type="EQUITY",
            description="Test",
            quantity=10.0,
            average_price=100.0,
            market_value=1000.0,
            unrealized_pl=0.0,
            price_timestamp="2026-10-20T14:03:11+00:00",
        )
        with pytest.raises((ValueError, TypeError)):
            PositionsResult(
                outcome="transient_failure",
                positions=[entry],
                detail="provider_unreachable",
                retryable=True,
                retrieved_at="2026-10-20T14:03:11+00:00",
            )

    def test_retrieved_at_iso8601_parseable(self) -> None:
        """retrieved_at must be an ISO-8601 string parseable by datetime."""
        from schwab_mcp.positions import PositionsResult

        result = PositionsResult(
            outcome="ok",
            positions=[],
            detail="no_positions",
            retryable=False,
            retrieved_at="2026-10-20T14:03:11+00:00",
        )
        dt = datetime.fromisoformat(result.retrieved_at)
        assert dt.tzinfo is not None

    def test_detail_vocabulary_closed(self) -> None:
        """detail must be one of the closed vocabulary values."""
        from schwab_mcp.positions import PositionsResult

        with pytest.raises((ValueError, TypeError)):
            PositionsResult(
                outcome="ok",
                positions=[],
                detail="bogus_detail",
                retryable=False,
                retrieved_at="2026-10-20T14:03:11+00:00",
            )

    def test_accounts_failed_detail_vocabulary(self) -> None:
        """accounts_failed entries must have detail ∈ {provider_error, transient}."""
        from schwab_mcp.positions import PositionsResult

        with pytest.raises((ValueError, TypeError)):
            PositionsResult(
                outcome="partial_failure",
                positions=[],
                detail="account_failed",
                retryable=False,
                retrieved_at="2026-10-20T14:03:11+00:00",
                accounts_failed=[
                    {"account_hash": "acc456", "detail": "bogus_reason"},
                ],
            )

    def test_ok_outcome_with_retryable_true_raises(self) -> None:
        """ok outcome with retryable=True must raise."""
        from schwab_mcp.positions import PositionsResult

        with pytest.raises((ValueError, TypeError)):
            PositionsResult(
                outcome="ok",
                positions=[],
                detail="no_positions",
                retryable=True,
                retrieved_at="2026-10-20T14:03:11+00:00",
            )


# =============================================================================
# Provider → Model mapping (map_provider_positions)
# =============================================================================


class TestMapProviderPositions:
    """map_provider_positions(payload: dict) -> PositionsResult

    Tests cover:
    - Single account long position maps to correct PositionEntry
    - Short position (longQuantity < shortQuantity) → negative quantity
    - Consolidation: same (account_hash, symbol) lots merged with average_price
    - Zero-quantity positions omitted from result
    - retrieved_at propagated to each entry's price_timestamp

    The function does not exist yet; these are TDD red-phase tests.
    """

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_payload(
        accounts: list[dict],
        retrieved_at: str = "2026-10-20T14:03:11+00:00",
    ) -> dict:
        """Wrap a list of account dicts into a fake provider payload."""
        return {
            "accounts": accounts,
            "retrieved_at": retrieved_at,
        }

    @staticmethod
    def _account(
        account_hash: str,
        positions: list[dict],
    ) -> dict:
        """Build a single account dict."""
        return {
            "accountHash": account_hash,
            "positions": positions,
        }

    @staticmethod
    def _position(
        symbol: str,
        asset_type: str = "EQUITY",
        description: str = "",
        long_quantity: float = 0.0,
        short_quantity: float = 0.0,
        average_price: float = 0.0,
        market_value: float = 0.0,
        unrealized_pl: float = 0.0,
    ) -> dict:
        """Build a single position dict as the provider would return it."""
        return {
            "symbol": symbol,
            "assetType": asset_type,
            "description": description or f"{symbol} description",
            "longQuantity": long_quantity,
            "shortQuantity": short_quantity,
            "averagePrice": average_price,
            "marketValue": market_value,
            "unrealizedPL": unrealized_pl,
        }

    # ------------------------------------------------------------------
    # tests
    # ------------------------------------------------------------------

    def test_single_account_long_position(self) -> None:
        """Single account, single long position maps to a correct PositionEntry."""
        from schwab_mcp.positions import PositionEntry, PositionsResult
        from schwab_mcp.positions import map_provider_positions  # will fail

        payload = self._make_payload(
            accounts=[
                self._account(
                    account_hash="acc123",
                    positions=[
                        self._position(
                            symbol="SPY",
                            asset_type="EQUITY",
                            description="SPDR S&P 500 ETF Trust",
                            long_quantity=10.0,
                            short_quantity=0.0,
                            average_price=580.25,
                            market_value=5910.0,
                            unrealized_pl=107.5,
                        ),
                    ],
                ),
            ],
            retrieved_at="2026-10-20T14:03:11+00:00",
        )

        result = map_provider_positions(payload)

        assert isinstance(result, PositionsResult)
        assert result.outcome == "ok"
        assert len(result.positions) == 1

        entry = result.positions[0]
        assert isinstance(entry, PositionEntry)
        assert entry.account_hash == "acc123"
        assert entry.symbol == "SPY"
        assert entry.instrument_type == "EQUITY"
        assert entry.description == "SPDR S&P 500 ETF Trust"
        assert entry.quantity == 10.0
        assert entry.average_price == 580.25
        assert entry.market_value == 5910.0
        assert entry.unrealized_pl == 107.5

    def test_short_position_negative_quantity(self) -> None:
        """A short position (shortQuantity > longQuantity) yields negative quantity."""
        from schwab_mcp.positions import map_provider_positions  # will fail

        payload = self._make_payload(
            accounts=[
                self._account(
                    account_hash="acc456",
                    positions=[
                        self._position(
                            symbol="AAPL",
                            asset_type="EQUITY",
                            description="Apple stock",
                            long_quantity=0.0,
                            short_quantity=5.0,
                            average_price=150.0,
                            market_value=750.0,
                            unrealized_pl=0.0,
                        ),
                    ],
                ),
            ],
            retrieved_at="2026-10-20T14:03:11+00:00",
        )

        result = map_provider_positions(payload)

        assert len(result.positions) == 1
        entry = result.positions[0]
        assert entry.symbol == "AAPL"
        assert entry.quantity < 0
        assert entry.quantity == -5.0  # longQuantity - shortQuantity

    def test_consolidation_duplicate_lots(self) -> None:
        """Same (account_hash, symbol) lots are merged into one entry with averaged
        average_price."""
        from schwab_mcp.positions import map_provider_positions  # will fail

        payload = self._make_payload(
            accounts=[
                self._account(
                    account_hash="acc123",
                    positions=[
                        self._position(
                            symbol="SPY",
                            long_quantity=7.0,
                            short_quantity=0.0,
                            average_price=100.0,
                            market_value=700.0,
                        ),
                        self._position(
                            symbol="SPY",
                            long_quantity=3.0,
                            short_quantity=0.0,
                            average_price=110.0,
                            market_value=330.0,
                        ),
                    ],
                ),
            ],
            retrieved_at="2026-10-20T14:03:11+00:00",
        )

        result = map_provider_positions(payload)

        # Two lots with same (acc123, SPY) → single consolidated entry
        assert len(result.positions) == 1
        entry = result.positions[0]
        assert entry.account_hash == "acc123"
        assert entry.symbol == "SPY"
        assert entry.quantity == 10.0  # 7 + 3

        # average_price = mean(100, 110) = 105.0
        assert entry.average_price == 105.0

    def test_zero_quantity_positions_omitted(self) -> None:
        """Positions where longQuantity == shortQuantity (net zero) are omitted."""
        from schwab_mcp.positions import map_provider_positions  # will fail

        payload = self._make_payload(
            accounts=[
                self._account(
                    account_hash="acc123",
                    positions=[
                        self._position(
                            symbol="SPY",
                            long_quantity=10.0,
                            short_quantity=0.0,
                            average_price=100.0,
                            market_value=1000.0,
                        ),
                        self._position(
                            symbol="TSLA",
                            long_quantity=5.0,
                            short_quantity=5.0,  # net zero
                            average_price=200.0,
                            market_value=1000.0,
                        ),
                    ],
                ),
            ],
            retrieved_at="2026-10-20T14:03:11+00:00",
        )

        result = map_provider_positions(payload)

        # Only SPY should appear; TSLA has zero net quantity and is omitted
        symbols = {e.symbol for e in result.positions}
        assert "SPY" in symbols
        assert "TSLA" not in symbols
        assert len(result.positions) == 1

    def test_retrieved_at_propagates_to_price_timestamp(self) -> None:
        """retrieved_at from the payload is propagated to each entry's
        price_timestamp."""
        from schwab_mcp.positions import map_provider_positions  # will fail

        retrieved_at = "2026-10-20T14:03:11+00:00"

        payload = self._make_payload(
            accounts=[
                self._account(
                    account_hash="acc123",
                    positions=[
                        self._position(
                            symbol="SPY",
                            long_quantity=10.0,
                            short_quantity=0.0,
                            average_price=100.0,
                            market_value=1000.0,
                        ),
                    ],
                ),
                self._account(
                    account_hash="acc456",
                    positions=[
                        self._position(
                            symbol="AAPL",
                            long_quantity=5.0,
                            short_quantity=0.0,
                            average_price=200.0,
                            market_value=1000.0,
                        ),
                    ],
                ),
            ],
            retrieved_at=retrieved_at,
        )

        result = map_provider_positions(payload)

        assert len(result.positions) == 2
        for entry in result.positions:
            assert entry.price_timestamp == retrieved_at


# =============================================================================
# Provider → Model mapping: option types and extended passthrough (US2)
# =============================================================================


class TestMapProviderPositionsOptionExtended:
    """map_provider_positions(payload) for option types and extended passthrough.

    Tests cover:
    - unrealized_pl derivation for long and short positions
    - Option field mapping for OPTION instrument types
    - Option fields absent for non-OPTION types
    - price_timestamp = retrieved_at propagation
    - Extended passthrough with extended=True parameter
    - Extended absent by default

    Tests ``test_option_fields_mapped`` and ``test_extended_passthrough``
    will fail until option/extended mapping is implemented in
    ``map_provider_positions``.
    """

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_payload(
        accounts: list[dict],
        retrieved_at: str = "2026-10-20T14:03:11+00:00",
    ) -> dict:
        """Wrap a list of account dicts into a fake provider payload."""
        return {
            "accounts": accounts,
            "retrieved_at": retrieved_at,
        }

    @staticmethod
    def _account(
        account_hash: str,
        positions: list[dict],
    ) -> dict:
        """Build a single account dict."""
        return {
            "accountHash": account_hash,
            "positions": positions,
        }

    @staticmethod
    def _position(
        symbol: str,
        asset_type: str = "EQUITY",
        description: str = "",
        long_quantity: float = 0.0,
        short_quantity: float = 0.0,
        average_price: float = 0.0,
        market_value: float = 0.0,
    ) -> dict:
        """Flat position dict (unrealizedPL omitted; mapping computes it)."""
        return {
            "symbol": symbol,
            "assetType": asset_type,
            "description": description or f"{symbol} desc",
            "longQuantity": long_quantity,
            "shortQuantity": short_quantity,
            "averagePrice": average_price,
            "marketValue": market_value,
        }

    @staticmethod
    def _option_position(
        symbol: str,
        description: str = "",
        long_quantity: float = 0.0,
        short_quantity: float = 0.0,
        average_price: float = 0.0,
        market_value: float = 0.0,
        underlying_symbol: str = "",
        put_call: str = "CALL",
        strike_price: float = 0.0,
        expiration_date: str = "",
    ) -> dict:
        """Option position with option-specific flat fields."""
        return {
            "symbol": symbol,
            "assetType": "OPTION",
            "description": description or f"{symbol} option",
            "longQuantity": long_quantity,
            "shortQuantity": short_quantity,
            "averagePrice": average_price,
            "marketValue": market_value,
            "underlyingSymbol": underlying_symbol,
            "putCall": put_call,
            "strikePrice": strike_price,
            "expirationDate": expiration_date,
        }

    # ------------------------------------------------------------------
    # tests
    # ------------------------------------------------------------------

    def test_unrealized_pl_long(self) -> None:
        """unrealized_pl = marketValue - averagePrice * quantity for long pos."""
        from schwab_mcp.positions import map_provider_positions

        payload = self._make_payload(
            accounts=[
                self._account(
                    account_hash="acc123",
                    positions=[
                        self._position(
                            symbol="SPY",
                            asset_type="EQUITY",
                            description="SPDR S&P 500 ETF Trust",
                            long_quantity=10.0,
                            short_quantity=0.0,
                            average_price=580.25,
                            market_value=5910.0,
                        ),
                    ],
                ),
            ],
        )

        result = map_provider_positions(payload)
        assert len(result.positions) == 1
        entry = result.positions[0]
        # 5910 - 580.25 * 10 = 107.5
        assert entry.unrealized_pl == 107.5

    def test_unrealized_pl_short(self) -> None:
        """unrealized_pl for short position (negative quantity)."""
        from schwab_mcp.positions import map_provider_positions

        payload = self._make_payload(
            accounts=[
                self._account(
                    account_hash="acc456",
                    positions=[
                        self._position(
                            symbol="AAPL",
                            asset_type="EQUITY",
                            description="Apple stock",
                            long_quantity=0.0,
                            short_quantity=5.0,
                            average_price=150.0,
                            market_value=750.0,
                        ),
                    ],
                ),
            ],
        )

        result = map_provider_positions(payload)
        assert len(result.positions) == 1
        entry = result.positions[0]
        # 750 - 150 * (-5) = 750 + 750 = 1500
        assert entry.unrealized_pl == 1500.0

    def test_option_fields_mapped(self) -> None:
        """OPTION assetType produces entries with option fields.

        Fails until map_provider_positions extracts option-specific fields
        (underlying_symbol, put_call, strike_price, expiration_date) from
        the flat position dict.
        """
        from schwab_mcp.positions import map_provider_positions

        payload = self._make_payload(
            accounts=[
                self._account(
                    account_hash="acc123",
                    positions=[
                        self._option_position(
                            symbol="SPY",
                            description="SPY Call Option",
                            long_quantity=10.0,
                            short_quantity=0.0,
                            average_price=5.0,
                            market_value=50.0,
                            underlying_symbol="SPY",
                            put_call="CALL",
                            strike_price=580.0,
                            expiration_date="2026-12-20",
                        ),
                    ],
                ),
            ],
        )

        result = map_provider_positions(payload)
        assert len(result.positions) == 1
        entry = result.positions[0]
        assert entry.instrument_type == "OPTION"
        assert entry.underlying_symbol == "SPY"
        assert entry.put_call == "CALL"
        assert entry.strike_price == 580.0
        assert entry.expiration_date == "2026-12-20"

    def test_option_fields_absent_for_equity(self) -> None:
        """EQUITY type → serialized output has no option fields (exclude_none)."""
        from schwab_mcp.positions import map_provider_positions

        payload = self._make_payload(
            accounts=[
                self._account(
                    account_hash="acc123",
                    positions=[
                        self._position(
                            symbol="SPY",
                            asset_type="EQUITY",
                            description="SPDR S&P 500 ETF Trust",
                            long_quantity=10.0,
                            short_quantity=0.0,
                            average_price=580.25,
                            market_value=5910.0,
                        ),
                    ],
                ),
            ],
        )

        result = map_provider_positions(payload)
        assert len(result.positions) == 1
        entry = result.positions[0]
        serialised = entry.model_dump(exclude_none=True)
        assert "underlying_symbol" not in serialised
        assert "put_call" not in serialised
        assert "strike_price" not in serialised
        assert "expiration_date" not in serialised

    def test_price_timestamp_matches_retrieved_at(self) -> None:
        """Each entry's price_timestamp equals the result's retrieved_at."""
        from schwab_mcp.positions import map_provider_positions

        retrieved_at = "2026-10-20T14:03:11+00:00"
        payload = self._make_payload(
            accounts=[
                self._account(
                    account_hash="acc123",
                    positions=[
                        self._position(
                            symbol="SPY",
                            long_quantity=10.0,
                            short_quantity=0.0,
                            average_price=100.0,
                            market_value=1000.0,
                        ),
                    ],
                ),
                self._account(
                    account_hash="acc456",
                    positions=[
                        self._position(
                            symbol="AAPL",
                            long_quantity=5.0,
                            short_quantity=0.0,
                            average_price=200.0,
                            market_value=1000.0,
                        ),
                    ],
                ),
            ],
            retrieved_at=retrieved_at,
        )

        result = map_provider_positions(payload)
        assert result.retrieved_at == retrieved_at
        for entry in result.positions:
            assert entry.price_timestamp == retrieved_at

    def test_extended_passthrough(self) -> None:
        """extended=True includes extra fields as extended dict per entry.

        Fails until map_provider_positions accepts extended=True and bundles
        passthrough fields (cusip, settledLongQuantity, …) into the
        extended dict.
        """
        from schwab_mcp.positions import map_provider_positions

        payload = self._make_payload(
            accounts=[
                self._account(
                    account_hash="acc123",
                    positions=[
                        {
                            "symbol": "SPY",
                            "assetType": "EQUITY",
                            "description": "SPDR S&P 500 ETF Trust",
                            "longQuantity": 10.0,
                            "shortQuantity": 0.0,
                            "averagePrice": 580.25,
                            "marketValue": 5910.0,
                            "cusip": "12345ABC",
                            "settledLongQuantity": 10.0,
                            "currentDayProfitLoss": 0.0,
                            "maintenanceRequirement": 0.0,
                        },
                    ],
                ),
            ],
        )

        result = map_provider_positions(payload, extended=True)
        assert len(result.positions) == 1
        entry = result.positions[0]
        assert entry.extended is not None
        assert entry.extended["cusip"] == "12345ABC"
        assert entry.extended["settledLongQuantity"] == 10.0

    def test_extended_default_false(self) -> None:
        """Without extended=True, no extended key in serialized entries."""
        from schwab_mcp.positions import map_provider_positions

        payload = self._make_payload(
            accounts=[
                self._account(
                    account_hash="acc123",
                    positions=[
                        self._position(
                            symbol="SPY",
                            long_quantity=10.0,
                            short_quantity=0.0,
                            average_price=100.0,
                            market_value=1000.0,
                        ),
                    ],
                ),
            ],
        )

        result = map_provider_positions(payload)
        for entry in result.positions:
            serialised = entry.model_dump(exclude_none=True)
            assert "extended" not in serialised


# =============================================================================
# Multi-account handling at mapping level (US3)
# =============================================================================


class TestMapProviderPositionsMultiAccount:
    """map_provider_positions(payload) with multi-account payloads.

    Tests cover multi-account handling at the pure mapping level.
    Per-account failure handling (partial_failure) is NOT handled here
    — that is done by get_open_positions (FR-010). At this level, the
    payload already contains only successful accounts.
    """

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_payload(
        accounts: list[dict],
        retrieved_at: str = "2026-10-20T14:03:11+00:00",
    ) -> dict:
        """Wrap a list of account dicts into a fake provider payload."""
        return {
            "accounts": accounts,
            "retrieved_at": retrieved_at,
        }

    @staticmethod
    def _account(
        account_hash: str,
        positions: list[dict],
    ) -> dict:
        """Build a single account dict."""
        return {
            "accountHash": account_hash,
            "positions": positions,
        }

    @staticmethod
    def _position(
        symbol: str,
        asset_type: str = "EQUITY",
        description: str = "",
        long_quantity: float = 0.0,
        short_quantity: float = 0.0,
        average_price: float = 0.0,
        market_value: float = 0.0,
    ) -> dict:
        """Build a single position dict as the provider would return it."""
        return {
            "symbol": symbol,
            "assetType": asset_type,
            "description": description or f"{symbol} desc",
            "longQuantity": long_quantity,
            "shortQuantity": short_quantity,
            "averagePrice": average_price,
            "marketValue": market_value,
        }

    # ------------------------------------------------------------------
    # tests
    # ------------------------------------------------------------------

    def test_two_accounts_both_with_positions(self) -> None:
        """Both accounts have positions → all positions appear in result."""
        from schwab_mcp.positions import map_provider_positions

        payload = self._make_payload(
            accounts=[
                self._account(
                    "acc123",
                    [self._position(
                        symbol="SPY",
                        long_quantity=10.0,
                        average_price=580.25,
                        market_value=5910.0,
                    )],
                ),
                self._account(
                    "acc456",
                    [self._position(
                        symbol="AAPL",
                        long_quantity=5.0,
                        average_price=150.0,
                        market_value=750.0,
                    )],
                ),
            ],
        )

        result = map_provider_positions(payload)

        assert result.outcome == "ok"
        assert len(result.positions) == 2

        symbols = {e.symbol for e in result.positions}
        hashes = {e.account_hash for e in result.positions}
        assert "SPY" in symbols
        assert "AAPL" in symbols
        assert "acc123" in hashes
        assert "acc456" in hashes

    def test_two_accounts_one_empty(self) -> None:
        """One account has positions, the other has none → only positions
        from the non-empty account appear."""
        from schwab_mcp.positions import map_provider_positions

        payload = self._make_payload(
            accounts=[
                self._account(
                    "acc123",
                    [self._position(
                        symbol="SPY",
                        long_quantity=10.0,
                        average_price=580.25,
                        market_value=5910.0,
                    )],
                ),
                self._account("acc456", []),
            ],
        )

        result = map_provider_positions(payload)

        assert result.outcome == "ok"
        assert len(result.positions) == 1
        assert result.positions[0].account_hash == "acc123"
        assert result.positions[0].symbol == "SPY"

    def test_two_accounts_both_empty(self) -> None:
        """Both accounts have no positions → outcome ok, detail no_positions."""
        from schwab_mcp.positions import map_provider_positions

        payload = self._make_payload(
            accounts=[
                self._account("acc123", []),
                self._account("acc456", []),
            ],
        )

        result = map_provider_positions(payload)

        assert result.outcome == "ok"
        assert result.detail == "no_positions"
        assert result.positions == []

    def test_no_accounts(self) -> None:
        """No accounts at all → outcome ok, detail no_positions."""
        from schwab_mcp.positions import map_provider_positions

        payload = self._make_payload(accounts=[])

        result = map_provider_positions(payload)

        assert result.outcome == "ok"
        assert result.detail == "no_positions"
        assert result.positions == []

    def test_positions_retain_correct_account_hash(self) -> None:
        """Each position retains its owning account's hash; positions
        from different accounts are never merged."""
        from schwab_mcp.positions import map_provider_positions

        payload = self._make_payload(
            accounts=[
                self._account(
                    "accA",
                    [self._position(
                        symbol="SPY",
                        long_quantity=10.0,
                        average_price=100.0,
                        market_value=1000.0,
                    )],
                ),
                self._account(
                    "accB",
                    [self._position(
                        symbol="SPY",  # Same symbol, different account
                        long_quantity=5.0,
                        average_price=200.0,
                        market_value=1000.0,
                    )],
                ),
            ],
        )

        result = map_provider_positions(payload)

        # Same symbol in different accounts → TWO entries (never merged)
        assert len(result.positions) == 2

        acc_a = [e for e in result.positions if e.account_hash == "accA"]
        acc_b = [e for e in result.positions if e.account_hash == "accB"]
        assert len(acc_a) == 1
        assert len(acc_b) == 1
        assert acc_a[0].quantity == 10.0
        assert acc_b[0].quantity == 5.0