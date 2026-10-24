"""Failing unit tests for symbol validation and filter semantics (US2).

These are TDD red-phase tests for the symbol filtering feature.  The
``InstrumentNotFoundError`` class and the ``instruments()`` validation
upcall inside ``get_transaction_history`` do not exist yet, so the
top-level import of ``InstrumentNotFoundError`` will fail with
``ImportError``, marking every test as Red.  Once implemented (T018), all
tests should pass.

Covers (from tasks.md T016 and T017)
-------------------------------------
- ``symbol`` present → 1 upcall ``instruments(symbols=[symbol],
  projection="SYMBOL_SEARCH")`` (research D6)
- Symbol not found / typo → ``instrument_not_found`` error naming the
  symbol (FR-009c)
- No ``symbol`` → ZERO upcalls of ``instruments`` (no unnecessary API
  calls)
- No fuzzy matching — exact symbol required (Assumptions from spec)
- Filtered result = exact subset of unfiltered result (consistency,
  US2 esc. 3)
- Valid symbol with no movements → ``ok/no_movements_for_instrument``
- Filter applied upstream — ``symbol=`` parameter passed to
  ``transactions()`` call

References
----------
- specs/006-transaction-history/tasks.md T016, T017
- specs/006-transaction-history/spec.md (US2, FR-003, FR-009c)
- specs/006-transaction-history/research.md (D6)
- specs/006-transaction-history/data-model.md (§HistoryQuery,
  cross-validation rule 6)
- specs/006-transaction-history/contracts/mcp-tools.md
"""

from __future__ import annotations

from typing import Any

import pytest

from schwab_mcp.transactions import (
    MovementEntry,
    TransactionDetail,
    TransactionOutcome,
    TransactionsResult,
    get_transaction_history,
)

# ---------------------------------------------------------------------------
# This import will fail — InstrumentNotFoundError does not exist yet (T016.2,
# T018).  Its absence is the Red signal: every test in this file fails with
# ImportError until the symbol-validation logic is implemented.
# ---------------------------------------------------------------------------
from schwab_mcp.transactions import InstrumentNotFoundError  # noqa: F401


# =============================================================================
# Fake client with instruments() support
# =============================================================================


class _validator:
    """Mimics ``schwabdev.validation.Validator`` with a toggleable ``enabled`` flag."""

    enabled = True


class FakeClient:
    """Fake schwabdev Client for testing symbol validation and filter semantics.

    Extends the pattern from ``test_transactions_query.py`` with an
    ``instruments()`` method and symbol-aware ``transactions()``.

    Known valid symbols are held in ``_known_symbols``.  The
    ``instruments()`` method returns a valid response when the symbol is
    known, or an empty dict when it is not.

    All invocations are recorded in ``call_log`` for assertions.
    """

    def __init__(self) -> None:
        self._validator = _validator()
        self._accounts: list[dict[str, str]] = []
        # {account_hash: dict} — the response for transactions()
        self._tx_responses: dict[str, Any] = {}
        # Set of symbols that instruments() considers valid
        self._known_symbols: set[str] = {"AAPL", "SPY", "MSFT", "GOOGL", "NVDA"}

        # Call tracking
        self.call_log: list[dict[str, Any]] = []
        """Each entry: {"method": str, "kwargs": dict}"""

    # ------------------------------------------------------------------
    # Account helpers
    # ------------------------------------------------------------------

    def set_accounts(self, hashes: list[str]) -> None:
        """Set the list of account hashes returned by ``linked_accounts()``."""
        self._accounts = [{"accountHash": h} for h in hashes]

    def set_response(self, account_hash: str, data: dict) -> None:
        """Set the response ``transactions()`` returns for *account_hash*."""
        self._tx_responses[account_hash] = data

    def reset_tracking(self) -> None:
        """Clear the call log (useful for determinism / consistency tests)."""
        self.call_log.clear()

    # ------------------------------------------------------------------
    # SDK method fakes
    # ------------------------------------------------------------------

    def linked_accounts(self) -> list[dict[str, str]]:
        self.call_log.append({"method": "linked_accounts", "kwargs": {}})
        return list(self._accounts)

    def instruments(self, symbols: list[str], projection: str) -> Any:
        """Fake ``instruments()``.

        Returns a valid instrument response for symbols in
        ``_known_symbols`` and an empty dict for unknown symbols.
        """
        self.call_log.append({
            "method": "instruments",
            "kwargs": {"symbols": symbols, "projection": projection},
        })
        if not symbols or symbols[0].upper() not in {s.upper() for s in self._known_symbols}:
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
        """Fake ``transactions()``.

        Returns pre-configured responses per account hash.  When a
        ``symbol`` is provided, the response is filtered to only include
        transactions whose instrument matches that symbol, so that the
        subset consistency test (T017.1) can be verified.
        """
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
        raw = self._tx_responses.get(accountHash, {"transactions": []})

        if symbol is None:
            return raw

        filtered = [
            tx
            for tx in raw.get("transactions", [])
            if tx.get("instrument", {}).get("symbol") == symbol
        ]
        return {"transactions": filtered}


# =============================================================================
# Helper: build a minimal provider transaction dict with instrument sub-object
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
    """Build a minimal provider-format transaction dict for fake client responses.

    The instrument is placed inside an ``instrument`` sub-object (matching
    the real provider format), so that ``map_provider_transactions`` reads
    the symbol correctly.
    """
    tx: dict = {
        "activityId": activity_id,
        "type": tx_type,
        "description": description,
        "amount": amount,
        "settlementDate": settlement_date,
        "transactionDate": occurred_at,
    }
    if fees is not None:
        tx["fees"] = fees
    if commission is not None:
        tx["commission"] = commission
    if net_amount is not None:
        tx["netAmount"] = net_amount
    if symbol is not None or instrument_type is not None:
        instrument: dict[str, str] = {}
        if symbol is not None:
            instrument["symbol"] = symbol
        if instrument_type is not None:
            instrument["instrumentType"] = instrument_type
        tx["instrument"] = instrument
    return tx


def _provider_response(transactions: list[dict]) -> dict:
    """Wrap a list of transaction dicts into a fake provider response."""
    return {"transactions": transactions}


# =============================================================================
# T016 — Symbol validation tests
# =============================================================================


class TestSymbolValidationUpcall:
    """T016: Symbol validation via ``instruments()`` upcall.

    When ``symbol`` is present, the orchestration MUST make exactly one
    ``instruments()`` call with the correct parameters.  When no ``symbol``
    is provided, there MUST be zero ``instruments()`` calls.
    """

    def test_symbol_present_triggers_instruments_upcall(self) -> None:
        """``symbol="AAPL"`` produces exactly 1 ``instruments()`` upcall
        with ``symbols=["AAPL"]`` and ``projection="SYMBOL_SEARCH"``
        (research D6)."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response("acc1", _provider_response([]))

        get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="AAPL",
        )

        # Extract instruments calls from the log
        instr_calls = [
            e for e in client.call_log if e["method"] == "instruments"
        ]
        assert len(instr_calls) == 1, (
            f"Expected exactly 1 instruments() call, got {len(instr_calls)}"
        )
        kwargs = instr_calls[0]["kwargs"]
        assert kwargs.get("symbols") == ["AAPL"], (
            f"Expected symbols=['AAPL'], got {kwargs.get('symbols')!r}"
        )
        assert kwargs.get("projection") == "symbol-search", (
            f"Expected projection='symbol-search', got "
            f"{kwargs.get('projection')!r}"
        )

    def test_instruments_upcall_uses_exact_symbol_no_fuzzy(self) -> None:
        """The exact symbol is passed to ``instruments()`` — no
        lowercasing, trimming, or wildcards (Assumptions: no fuzzy
        matching)."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response("acc1", _provider_response([]))

        # Use a symbol that differs only in case from a known symbol
        get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="aapl",
        )

        instr_calls = [
            e for e in client.call_log if e["method"] == "instruments"
        ]
        assert len(instr_calls) >= 1
        kwargs = instr_calls[0]["kwargs"]
        symbol_passed = kwargs.get("symbols", [None])[0]
        assert symbol_passed == "aapl", (
            f"Expected exact symbol 'aapl', got {symbol_passed!r}"
        )

    def test_no_symbol_no_instruments_upcall(self) -> None:
        """When no ``symbol`` is provided, the orchestration MUST NOT
        call ``instruments()`` at all (no unnecessary API calls)."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response("acc1", _provider_response([]))

        get_transaction_history(client, "2026-10-01", "2026-10-20")

        instr_calls = [
            e for e in client.call_log if e["method"] == "instruments"
        ]
        assert len(instr_calls) == 0, (
            f"Expected 0 instruments() calls when symbol is absent, "
            f"got {len(instr_calls)}"
        )


class TestSymbolNotFound:
    """T016.2: A symbol that does not exist or is mistyped MUST produce
    an ``instrument_not_found`` error naming the symbol (FR-009c).

    The error MUST be distinguishable from an empty-result ``no_movements``
    response.
    """

    def test_unknown_symbol_raises_instrument_not_found(self) -> None:
        """An unknown symbol raises ``InstrumentNotFoundError`` with a
        message containing the symbol."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response("acc1", _provider_response([]))

        with pytest.raises(InstrumentNotFoundError) as exc:
            get_transaction_history(
                client, "2026-10-01", "2026-10-20", symbol="ZYXW_FAKE",
            )
        msg = str(exc.value)
        assert "ZYXW_FAKE" in msg, (
            f"Error must name the unknown symbol, got: {msg}"
        )

    def test_typo_symbol_raises_instrument_not_found(self) -> None:
        """A plausible but mistyped symbol raises
        ``InstrumentNotFoundError``."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response("acc1", _provider_response([]))

        # "AAPL" is valid; "APL" is a typo
        with pytest.raises(InstrumentNotFoundError) as exc:
            get_transaction_history(
                client, "2026-10-01", "2026-10-20", symbol="APL",
            )
        msg = str(exc.value)
        assert "APL" in msg, (
            f"Error must name the typo symbol, got: {msg}"
        )

    def test_instrument_not_found_is_not_no_movements(self) -> None:
        """``InstrumentNotFoundError`` is an error, not an ``ok``
        outcome — the agent can distinguish it from an empty result."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response("acc1", _provider_response([]))

        with pytest.raises(InstrumentNotFoundError):
            get_transaction_history(
                client, "2026-10-01", "2026-10-20", symbol="BOGUS",
            )


class TestSymbolValidationOrdering:
    """T016 (implied): Symbol validation happens BEFORE the
    ``transactions()`` upcall — the ``instruments()`` call is made first,
    and a failed validation short-circuits before any transaction query."""

    def test_instruments_called_before_transactions(self) -> None:
        """When a symbol is present, the ``instruments()`` call MUST
        appear in the call log before any ``transactions()`` call."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response("acc1", _provider_response([]))

        get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="AAPL",
        )

        methods_in_order = [e["method"] for e in client.call_log]
        instr_idx = methods_in_order.index("instruments")
        tx_indices = [
            i for i, m in enumerate(methods_in_order) if m == "transactions"
        ]
        assert tx_indices, (
            "Expected at least one transactions() call"
        )
        assert instr_idx < min(tx_indices), (
            f"instruments() at position {instr_idx} must precede "
            f"transactions() at positions {tx_indices}"
        )

    def test_invalid_symbol_short_circuits_no_transactions(self) -> None:
        """When the symbol is invalid, NO ``transactions()`` calls are
        made — the validation short-circuits before any account query."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1", "acc2"])
        client.set_response("acc1", _provider_response([]))
        client.set_response("acc2", _provider_response([]))

        with pytest.raises(InstrumentNotFoundError):
            get_transaction_history(
                client, "2026-10-01", "2026-10-20", symbol="NONEXISTENT",
            )

        tx_calls = [
            e for e in client.call_log if e["method"] == "transactions"
        ]
        assert len(tx_calls) == 0, (
            f"Expected 0 transactions() calls after invalid symbol, "
            f"got {len(tx_calls)}"
        )


# =============================================================================
# T017 — Filter semantics tests
# =============================================================================


class TestFilterConsistency:
    """T017.1: The filtered result MUST be an exact subset of the
    unfiltered result (US2 esc. 3).

    Given the same date range queried without and with a symbol filter,
    every movement in the filtered result must reference the requested
    symbol and be present in the unfiltered result.
    """

    def test_filtered_result_is_subset_of_unfiltered(self) -> None:
        """Movements from a symbol-filtered query are exactly those
        referencing the symbol from the full unfiltered result."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id="a1", symbol="AAPL"),
                _provider_tx(activity_id="a2", symbol="SPY"),
                _provider_tx(activity_id="a3", symbol="MSFT"),
                _provider_tx(activity_id="a4", symbol=None),  # non-instrument
            ]),
        )

        # Query without filter
        client.reset_tracking()
        unfiltered = get_transaction_history(
            client, "2026-10-01", "2026-10-20",
        )
        assert unfiltered.outcome == TransactionOutcome.ok
        assert unfiltered.movements is not None
        unfiltered_symbols = {
            m.symbol
            for m in unfiltered.movements
            if m.symbol is not None
        }
        assert "AAPL" in unfiltered_symbols, (
            "Sanity check: unfiltered result must include AAPL movements"
        )

        # Query with symbol filter
        client.reset_tracking()
        filtered = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="AAPL",
        )
        assert filtered.outcome == TransactionOutcome.ok
        assert filtered.movements is not None

        # EVERY movement in the filtered result must reference AAPL
        for m in filtered.movements:
            assert m.symbol == "AAPL", (
                f"Filtered movement {m.symbol!r} does not match "
                f"requested symbol 'AAPL'"
            )

        # The filtered set must be a subset of the unfiltered set
        # (by activityId, since the same movement shouldn't change)
        unfiltered_ids = {
            m.extended.get("activityId", "")
            for m in unfiltered.movements
            if m.extended
        }
        for m in filtered.movements:
            activity_id = (
                m.extended.get("activityId", "") if m.extended else ""
            )
            # If extended is not available, check by symbol presence
            if activity_id and unfiltered_ids:
                assert activity_id in unfiltered_ids, (
                    f"Movement {activity_id} in filtered result is not "
                    f"present in unfiltered result"
                )
            else:
                # Fallback: verify the symbol exists in unfiltered results
                assert any(
                    um.symbol == m.symbol for um in unfiltered.movements
                ), (
                    f"Movement with symbol {m.symbol} in filtered result "
                    f"not found in unfiltered result"
                )

    def test_filtered_result_empty_when_symbol_not_in_range(self) -> None:
        """When the symbol is valid but has no movements in the range,
        the result is ``ok/no_movements_for_instrument``, not a non-empty
        set of unrelated movements."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id="a1", symbol="SPY"),
                _provider_tx(activity_id="a2", symbol="MSFT"),
            ]),
        )

        # NVDA is valid (in _known_symbols) but has no transactions
        client.reset_tracking()
        result = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="NVDA",
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.detail == TransactionDetail.no_movements_for_instrument
        assert result.movements == []
        assert result.total_count == 0

    def test_filters_are_consistent_across_multiple_accounts(self) -> None:
        """Filter consistency holds even across multiple linked accounts."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1", "acc2"])
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id="a1", symbol="AAPL"),
                _provider_tx(activity_id="a2", symbol="SPY"),
            ]),
        )
        client.set_response(
            "acc2",
            _provider_response([
                _provider_tx(activity_id="b1", symbol="MSFT"),
                _provider_tx(activity_id="b2", symbol="AAPL"),
            ]),
        )

        # Unfiltered
        client.reset_tracking()
        unfiltered = get_transaction_history(
            client, "2026-10-01", "2026-10-20",
        )
        assert unfiltered.outcome == TransactionOutcome.ok
        unfiltered_aapl = {
            (
                m.extended.get("activityId", "") if m.extended else ""
            )
            for m in (unfiltered.movements or [])
            if m.symbol == "AAPL"
        }

        # Filtered by AAPL
        client.reset_tracking()
        filtered = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="AAPL",
        )
        assert filtered.outcome == TransactionOutcome.ok
        assert filtered.movements is not None
        filtered_ids = {
            m.extended.get("activityId", "") if m.extended else ""
            for m in filtered.movements
        }

        # Every filtered activity ID must be in the unfiltered AAPL set
        for fid in filtered_ids:
            assert fid in unfiltered_aapl, (
                f"Filtered activity {fid} not found in unfiltered "
                f"set {unfiltered_aapl}"
            )


class TestFilterNoMovementsForInstrument:
    """T017.2: A valid symbol with no movements in the range produces
    ``ok/no_movements_for_instrument`` with ``symbol`` present in the
    request (cross-validation rule 6 from data-model.md)."""

    def test_valid_symbol_no_movements_yields_no_movements_for_instrument(
        self,
    ) -> None:
        """When the symbol is found by ``instruments()`` but no
        movements exist, the outcome is ``ok`` with
        ``detail=no_movements_for_instrument``."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        # Valid symbol (in _known_symbols) but empty transactions
        client.set_response("acc1", _provider_response([]))

        result = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="AAPL",
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.detail == TransactionDetail.no_movements_for_instrument
        assert result.movements == []
        assert result.total_count == 0

    def test_no_movements_for_instrument_detail_implies_symbol_in_request(
        self,
    ) -> None:
        """The ``no_movements_for_instrument`` detail can only appear
        when ``symbol`` was present in the request (cross-validation
        rule 6)."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1"])
        client.set_response("acc1", _provider_response([]))

        # Without symbol, empty results MUST use detail=no_movements
        result_no_symbol = get_transaction_history(
            client, "2026-10-01", "2026-10-20",
        )
        assert result_no_symbol.detail == TransactionDetail.no_movements

        # With a valid symbol, empty results use no_movements_for_instrument
        result_with_symbol = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="AAPL",
        )
        assert (
            result_with_symbol.detail
            == TransactionDetail.no_movements_for_instrument
        )


class TestFilterForwardedUpstream:
    """T017.3: The ``symbol`` parameter MUST be forwarded as the
    ``symbol`` argument to ``transactions()`` (upstream filter)."""

    def test_symbol_forwarded_to_transactions(self) -> None:
        """When ``symbol="MSFT"`` is provided, every
        ``transactions()`` call receives ``symbol="MSFT"``."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc1", "acc2"])
        client.set_response("acc1", _provider_response([]))
        client.set_response("acc2", _provider_response([]))

        get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="MSFT",
        )

        tx_calls = [
            e for e in client.call_log if e["method"] == "transactions"
        ]
        assert len(tx_calls) >= 1
        for call in tx_calls:
            assert call["kwargs"].get("symbol") == "MSFT", (
                f"Expected symbol='MSFT' in transactions() call, "
                f"got {call['kwargs'].get('symbol')!r}"
            )

    def test_symbol_is_none_when_not_provided(self) -> None:
        """When no ``symbol`` is provided, every ``transactions()``
        call receives ``symbol=None``."""
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
            "Expected symbol=None in transactions() when no filter "
            "is provided"
        )