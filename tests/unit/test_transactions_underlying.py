"""TDD Red-phase tests for underlying-aware matching (007).

Tests for ``_option_root()`` derivation and the three-form matcher
(``movement_involves_filter()``) — pure functions without I/O.

These tests are written BEFORE the implementation (TDD: Red → Green).
They import functions that do not exist yet, so the module will fail
to import — that is the expected Red signal.

References
----------
- specs/007-underlying-symbol-filter/data-model.md §1-R1, §2
- specs/007-underlying-symbol-filter/research.md R2, R4
"""

from __future__ import annotations

import pytest

# =============================================================================
# These imports will fail (Red) until T003 implements the functions.
# =============================================================================
from schwab_mcp.transactions import (
    _option_root,
    map_provider_transactions,
    movement_involves_filter,
)


# =============================================================================
# _option_root — root derivation (data-model §1-R1)
# =============================================================================


class TestOptionRoot:
    """R1: root = symbol[:-15].strip() when the last 15 chars match OCC pattern."""

    def test_standard_occ_with_padding(self) -> None:
        """``AMD   261120P00630000`` → ``AMD`` (root with padding stripped)."""
        root = _option_root("AMD   261120P00630000")
        assert root == "AMD"

    def test_root_without_padding(self) -> None:
        """``NOK261218P00011000`` (no padding) → ``NOK``."""
        root = _option_root("NOK261218P00011000")
        assert root == "NOK"

    def test_short_root(self) -> None:
        """``A     261120C00100000`` → ``A`` (single-char root)."""
        root = _option_root("A     261120C00100000")
        assert root == "A"

    def test_long_root(self) -> None:
        """``SPXW  261218C05000000`` → ``SPXW`` (4-char root)."""
        root = _option_root("SPXW  261218C05000000")
        assert root == "SPXW"

    def test_put_option(self) -> None:
        """``MSFT  261220P00250000`` → ``MSFT`` (put, not call)."""
        root = _option_root("MSFT  261220P00250000")
        assert root == "MSFT"

    def test_non_occ_symbol_returns_none(self) -> None:
        """An equity symbol like ``AAPL`` returns ``None``."""
        root = _option_root("AAPL")
        assert root is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string returns ``None``."""
        root = _option_root("")
        assert root is None

    def test_short_symbol_returns_none(self) -> None:
        """A symbol shorter than 15 chars returns ``None``."""
        root = _option_root("SHORT")
        assert root is None

    def test_invalid_tail_chars_returns_none(self) -> None:
        """Last 15 chars with non-digit where digit expected returns ``None``."""
        # The 6th char (0-based) must be C/P; here it's X
        root = _option_root("NOK   261120X00630000")
        assert root is None

    def test_invalid_digits_returns_none(self) -> None:
        """Last 15 chars with non-digit in strike portion returns ``None``."""
        root = _option_root("NOK   26112X000630000")
        assert root is None

    def test_case_sensitive_root_preserved(self) -> None:
        """Root is returned as-is (source is uppercase in practice)."""
        root = _option_root("NOK   261218P00011000")
        assert root == "NOK"

    def test_edge_none_input(self) -> None:
        """``None`` input returns ``None`` without crashing."""
        root = _option_root(None)
        assert root is None


# =============================================================================
# movement_involves_filter — three-form matcher (data-model §2)
# =============================================================================


class TestMovementInvolvesFilter:
    """M1/M2/M3 matching rules — exact, case-insensitive, no fuzzy."""

    # --- M1: Exact symbol match ---

    def test_m1_exact_symbol_match(self) -> None:
        """``symbol="NOK"`` with filter ``"NOK"`` → True (M1)."""
        assert movement_involves_filter("NOK", "EQUITY", "NOK") is True

    def test_m1_different_symbol_returns_false(self) -> None:
        """``symbol="AAPL"`` with filter ``"NOK"`` → False."""
        assert movement_involves_filter("AAPL", "EQUITY", "NOK") is False

    def test_m1_case_insensitive(self) -> None:
        """``symbol="nok"`` with filter ``"NOK"`` → True (M1, case-insensitive)."""
        assert movement_involves_filter("nok", "EQUITY", "NOK") is True

    def test_m1_reverse_case_insensitive(self) -> None:
        """``symbol="NOK"`` with filter ``"nok"`` → True (M1, case-insensitive)."""
        assert movement_involves_filter("NOK", "EQUITY", "nok") is True

    def test_m1_no_fuzzy_substring(self) -> None:
        """`symbol="NO"` with filter ``"NOK"`` → False (no substring match)."""
        assert movement_involves_filter("NO", "EQUITY", "NOK") is False

    def test_m1_no_fuzzy_partial(self) -> None:
        """`symbol="NOKIA"` with filter ``"NOK"`` → False (no partial match)."""
        assert movement_involves_filter("NOKIA", "EQUITY", "NOK") is False

    def test_m1_currency_usd(self) -> None:
        """``symbol="CURRENCY_USD"`` with filter ``"CURRENCY_USD"`` → True (M1)."""
        assert movement_involves_filter("CURRENCY_USD", "CURRENCY", "CURRENCY_USD") is True

    def test_m1_symbol_none_returns_false(self) -> None:
        """``symbol=None`` → False (no match possible)."""
        assert movement_involves_filter(None, "EQUITY", "NOK") is False

    # --- M2: Option root match ---

    def test_m2_option_root_match(self) -> None:
        """Option with root ``NOK`` and filter ``"NOK"`` → True (M2)."""
        assert movement_involves_filter("NOK   261218P00011000", "OPTION", "NOK") is True

    def test_m2_case_insensitive_root(self) -> None:
        """Option with root ``NOK`` and filter ``"nok"`` → True (M2, case-insensitive)."""
        assert movement_involves_filter("NOK   261218P00011000", "OPTION", "nok") is True

    def test_m2_not_option_does_not_match_root(self) -> None:
        """EQUITY symbol that happens to have OCC-like suffix → no M2 match (not OPTION)."""
        # Even if symbol looks like OCC, non-OPTION instrument_type skips M2.
        # M1 also doesn't match because the full OCC ≠ "NOK".
        assert movement_involves_filter("NOK   261218P00011000", "EQUITY", "NOK") is False

    def test_m2_different_root(self) -> None:
        """Option with root ``AMD`` and filter ``"NOK"`` → False."""
        assert movement_involves_filter("AMD   261120P00630000", "OPTION", "NOK") is False

    def test_m2_non_occ_option_no_root_match(self) -> None:
        """Option with non-OCC symbol → no M2 match (root is None)."""
        # A non-OCC symbol won't match via M2 since _option_root returns None.
        # It can still match via M1 if symbols are equal.
        assert movement_involves_filter("SOMETHING_ELSE", "OPTION", "NOK") is False

    def test_m2_equity_no_m2(self) -> None:
        """EQUITY instrument never matches via M2."""
        assert movement_involves_filter("NOK", "EQUITY", "NOK") is True  # via M1

    # --- M3: Full OCC symbol match ---

    def test_m3_full_occ_symbol_match(self) -> None:
        """Full OCC ``NOK   261218P00011000`` with same as filter → True (M1=M3)."""
        occ = "NOK   261218P00011000"
        assert movement_involves_filter(occ, "OPTION", occ) is True

    def test_m3_full_occ_case_insensitive(self) -> None:
        """Full OCC in lowercase matches uppercase filter."""
        occ_upper = "NOK   261218P00011000"
        occ_lower = "nok   261218p00011000"
        assert movement_involves_filter(occ_upper, "OPTION", occ_lower) is True

    def test_m3_different_full_occ(self) -> None:
        """Different OCC symbols don't match."""
        assert movement_involves_filter(
            "NOK   261218P00011000", "OPTION", "NOK   261220C00250000"
        ) is False

    # --- Edge cases ---

    def test_empty_filter_returns_false(self) -> None:
        """Empty string filter ``""`` → False."""
        assert movement_involves_filter("NOK", "EQUITY", "") is False

    def test_none_filter_returns_false(self) -> None:
        """``None`` filter → False."""
        assert movement_involves_filter("NOK", "EQUITY", None) is False

    def test_zero_length_root_after_strip(self) -> None:
        """Edge case: symbol where root is empty after strip (marginal)."""
        # An OCC with only spaces and no root ... improbable but handle gracefully
        occ = "       261218P00011000"
        assert movement_involves_filter(occ, "OPTION", "") is False

    def test_instrument_type_none_with_option_symbol(self) -> None:
        """``instrument_type=None`` with an OCC symbol — M2 is skipped, but M1/M3 still apply."""
        occ = "NOK   261218P00011000"
        assert movement_involves_filter(occ, None, occ) is True  # via M1


# =============================================================================
# T007 — underlying_symbol field on option movements (US2)
# =============================================================================


class TestUnderlyingSymbol:
    """T007: ``underlying_symbol`` derived from OCC option symbol (US2).

    When ``instrument_type == "OPTION"`` and ``_option_root(symbol)``
    returns a non-``None`` root, ``map_provider_transactions()`` must add
    ``underlying_symbol`` to the ``MovementEntry`` kwargs.

    These tests are in TDD Red phase: ``MovementEntry`` does not yet have an
    ``underlying_symbol`` field, so every test that reads this field will
    fail with ``AttributeError`` — that is the expected Red signal.

    References
    ----------
    - specs/007-underlying-symbol-filter/data-model.md §1-R1, §1-R2
    - specs/007-underlying-symbol-filter/tasks.md T007
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _option_tx(
        symbol: str,
        activity_id: str = "opt-001",
    ) -> dict:
        """Build a minimal provider transaction dict for an OPTION trade.

        Parameters
        ----------
        symbol:
            The instrument symbol (expected to be an OCC option symbol).
        activity_id:
            Unique identifier for the transaction.
        """
        return {
            "activityId": activity_id,
            "type": "TRADE",
            "transactionDate": "2026-10-20T14:03:11+00:00",
            "description": "Option trade",
            "netAmount": -3220.0,
            "currency": "USD",
            "accountHash": "acc1",
            "instrument": {
                "symbol": symbol,
                "instrumentType": "OPTION",
            },
        }

    # ------------------------------------------------------------------
    # 1. Option with real OCC symbol — underlying_symbol present
    # ------------------------------------------------------------------

    def test_option_with_occ_yields_underlying_symbol(self) -> None:
        """OPTION with OCC symbol → ``underlying_symbol`` set to root.

        ``NOK   261218P00011000`` (put, padding) → ``underlying_symbol == "NOK"``.
        Fails (Red): ``MovementEntry`` has no ``underlying_symbol`` field.
        """
        payload = {"transactions": [self._option_tx("NOK   261218P00011000")]}
        entries = map_provider_transactions(payload, extended=False)
        assert len(entries) == 1
        # AttributeError — Red signal
        assert entries[0].underlying_symbol == "NOK"

    def test_option_call_with_occ_yields_underlying_symbol(self) -> None:
        """OPTION call with OCC symbol → ``underlying_symbol`` set.

        ``AMD   261120C00630000`` (call, padding) → ``underlying_symbol == "AMD"``.
        Fails (Red).
        """
        payload = {"transactions": [self._option_tx("AMD   261120C00630000")]}
        entries = map_provider_transactions(payload, extended=False)
        assert len(entries) == 1
        assert entries[0].underlying_symbol == "AMD"  # Red

    def test_option_unpadded_occ_yields_underlying_symbol(self) -> None:
        """OPTION with unpadded OCC symbol → ``underlying_symbol`` stripped.

        ``NOK261218P00011000`` (no padding between root and expiry) →
        ``underlying_symbol == "NOK"``.
        Fails (Red).
        """
        payload = {"transactions": [self._option_tx("NOK261218P00011000")]}
        entries = map_provider_transactions(payload, extended=False)
        assert len(entries) == 1
        assert entries[0].underlying_symbol == "NOK"  # Red

    def test_option_short_root_yields_underlying_symbol(self) -> None:
        """OPTION with single-char root → ``underlying_symbol`` correct.

        ``A     261120C00100000`` → ``underlying_symbol == "A"``.
        Fails (Red).
        """
        payload = {"transactions": [self._option_tx("A     261120C00100000")]}
        entries = map_provider_transactions(payload, extended=False)
        assert len(entries) == 1
        assert entries[0].underlying_symbol == "A"  # Red

    def test_option_long_root_yields_underlying_symbol(self) -> None:
        """OPTION with 4-char root → ``underlying_symbol`` correct.

        ``SPXW  261218C05000000`` → ``underlying_symbol == "SPXW"``.
        Fails (Red).
        """
        payload = {"transactions": [self._option_tx("SPXW  261218C05000000")]}
        entries = map_provider_transactions(payload, extended=False)
        assert len(entries) == 1
        assert entries[0].underlying_symbol == "SPXW"  # Red

    # ------------------------------------------------------------------
    # 2. Non-option movements — underlying_symbol absent
    # ------------------------------------------------------------------

    def test_equity_trade_no_underlying_symbol(self) -> None:
        """EQUITY TRADE → ``underlying_symbol`` absent (``exclude_none``)."""
        payload = {
            "transactions": [
                {
                    "activityId": "eq-001",
                    "type": "TRADE",
                    "transactionDate": "2026-10-20T14:03:11+00:00",
                    "description": "Equity trade",
                    "netAmount": 1500.0,
                    "currency": "USD",
                    "accountHash": "acc1",
                    "instrument": {
                        "symbol": "AAPL",
                        "instrumentType": "EQUITY",
                    },
                },
            ],
        }
        entries = map_provider_transactions(payload, extended=False)
        assert len(entries) == 1
        dumped = entries[0].model_dump(exclude_none=True)
        assert "underlying_symbol" not in dumped

    def test_dividend_or_interest_no_underlying_symbol(self) -> None:
        """DIVIDEND_OR_INTEREST (no instrument) → no ``underlying_symbol``."""
        payload = {
            "transactions": [
                {
                    "activityId": "div-001",
                    "type": "DIVIDEND_OR_INTEREST",
                    "transactionDate": "2026-10-20T14:03:11+00:00",
                    "description": "Dividend payment",
                    "netAmount": 25.0,
                    "currency": "USD",
                    "accountHash": "acc1",
                },
            ],
        }
        entries = map_provider_transactions(payload, extended=False)
        assert len(entries) == 1
        dumped = entries[0].model_dump(exclude_none=True)
        assert "underlying_symbol" not in dumped

    def test_transfer_no_underlying_symbol(self) -> None:
        """Transfer (RECEIVE_AND_DELIVER, no instrument) → no ``underlying_symbol``."""
        payload = {
            "transactions": [
                {
                    "activityId": "trf-001",
                    "type": "RECEIVE_AND_DELIVER",
                    "transactionDate": "2026-10-20T14:03:11+00:00",
                    "description": "Transfer of shares",
                    "netAmount": 0.0,
                    "currency": "USD",
                    "accountHash": "acc1",
                },
            ],
        }
        entries = map_provider_transactions(payload, extended=False)
        assert len(entries) == 1
        dumped = entries[0].model_dump(exclude_none=True)
        assert "underlying_symbol" not in dumped

    # ------------------------------------------------------------------
    # 3. Option with non-identifiable OCC — field absent
    # ------------------------------------------------------------------

    def test_option_non_occ_returns_no_underlying_symbol(self) -> None:
        """OPTION with a non-OCC symbol → ``underlying_symbol`` absent.

        A symbol that does not match the OCC tail pattern should not
        produce the field, even when ``instrument_type == "OPTION"``.
        """
        payload = {"transactions": [self._option_tx("SOMETHING_ELSE")]}
        entries = map_provider_transactions(payload, extended=False)
        assert len(entries) == 1
        dumped = entries[0].model_dump(exclude_none=True)
        assert "underlying_symbol" not in dumped

    def test_option_empty_symbol_no_underlying_symbol(self) -> None:
        """OPTION with empty symbol → ``underlying_symbol`` absent.

        An empty symbol can never be a valid OCC, so the field must
        remain absent.
        """
        payload = {"transactions": [self._option_tx("")]}
        entries = map_provider_transactions(payload, extended=False)
        assert len(entries) == 1
        dumped = entries[0].model_dump(exclude_none=True)
        assert "underlying_symbol" not in dumped

    def test_option_short_symbol_no_underlying_symbol(self) -> None:
        """OPTION with symbol shorter than 15 chars → field absent.

        OCC symbols are at least 15 characters long; anything shorter
        cannot be a valid OCC.  The field must remain absent.
        """
        payload = {"transactions": [self._option_tx("SHORT")]}
        entries = map_provider_transactions(payload, extended=False)
        assert len(entries) == 1
        dumped = entries[0].model_dump(exclude_none=True)
        assert "underlying_symbol" not in dumped

    # ------------------------------------------------------------------
    # 4. Extended passthrough — no duplication
    # ------------------------------------------------------------------

    def test_extended_passthrough_no_underlying_duplication(self) -> None:
        """``underlying_symbol`` is NOT duplicated inside the ``extended`` dict.

        The field is a top-level curated field, not a blind pass-through
        from raw provider data.
        Fails (Red): ``underlying_symbol`` field does not exist yet.
        """
        payload = {"transactions": [self._option_tx("NOK   261218P00011000")]}
        entries = map_provider_transactions(payload, extended=True)
        assert len(entries) == 1
        entry = entries[0]
        # Red signal — AttributeError until field is added to MovementEntry
        assert entry.underlying_symbol == "NOK"
        assert entry.extended is not None
        assert "underlying_symbol" not in entry.extended

    # ------------------------------------------------------------------
    # 5. No secrets — only public instrument identifiers
    # ------------------------------------------------------------------

    def test_underlying_symbol_is_public_ticker(self) -> None:
        """``underlying_symbol`` carries only a public ticker, not sensitive data.

        The value is the OCC option root (a public market identifier),
        not account numbers, hashes, or personal data.
        Fails (Red): field not present yet.
        """
        payload = {"transactions": [self._option_tx("MSFT  261220P00250000")]}
        entries = map_provider_transactions(payload, extended=False)
        assert len(entries) == 1
        # Red signal — AttributeError
        ticker = entries[0].underlying_symbol
        assert ticker == "MSFT"
        # The ticker should be alphabetic — no hashes, no account data
        assert ticker.isalpha(), (
            f"underlying_symbol '{ticker}' contains non-alpha characters"
        )