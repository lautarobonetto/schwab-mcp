"""TDD Red-phase tests for underlying-aware symbol filter query (T004).

These tests are written BEFORE the implementation of the new filter
semantics (T005).  The orchestration function ``get_transaction_history``
already exists but currently:

- Sends ``symbol`` upstream to ``client.transactions()``
- Validates symbols immediately with ``InstrumentNotFoundError``
- Relies on upstream filtering for subset-consistency

T005 will change the behaviour so that the filter is applied LOCALLY after
fetching ALL movements, using the three-form matcher
(``movement_involves_filter``).  Therefore most tests here will fail (Red)
until T005 is implemented.  Some tests (e.g. basic pagination) may
partially pass — that is expected in the Red phase.

Covers (from specs/007-underlying-symbol-filter/tasks.md T004)
----------------------------------------------------------------
- **R1**: Filter query does NOT send ``symbol`` upstream to
  ``transactions()``
- **Filter by underlying symbol**: ``symbol="NOK"`` returns equity NOK
  trades + option movements with root NOK
- **Full OCC symbol**: ``symbol="NOK   261218P00011000"`` returns only
  that option's movements
- **Case insensitivity**: ``"nok"`` ≡ ``"NOK"``; full OCC in lowercase ≡
  exact OCC
- **Subset-consistency**: Filtering the unfiltered result locally with the
  matcher produces the same set as the filtered query
- **Pagination over filtered set**: ``total_count`` reflects the subset;
  walk with ``offset`` without duplicates or omissions
- **Dual validation — directory not resolve + matches → ok**: When
  ``instruments()`` returns empty but movements still match (e.g. OCC
  symbol), return ok
- **Dual validation — directory not resolve + 0 matches →
  InstrumentNotFoundError**: Via ``get_transaction_history_tool`` →
  ``ToolError``; ``detail=no_movements_for_instrument`` only when nothing
  matches
- **CURRENCY_USD**: Returns its movements (M1 match)
- **partial_failure with filter**: Some accounts succeed/fail; successful
  accounts contribute movements matching the filter; failed accounts go to
  ``accounts_failed``; never discard an entire account due to filter

References
----------
- specs/007-underlying-symbol-filter/tasks.md T004
- specs/007-underlying-symbol-filter/spec.md (FR-001, FR-003, FR-005, FR-006)
- specs/007-underlying-symbol-filter/data-model.md (§2, §3, §4)
- specs/007-underlying-symbol-filter/research.md (R1, R3, R4)
"""

from __future__ import annotations

from typing import Any

import pytest

from schwab_mcp.transactions import (
    InstrumentNotFoundError,
    MovementEntry,
    TransactionDetail,
    TransactionOutcome,
    TransactionsResult,
    get_transaction_history,
    movement_involves_filter,
)


# =============================================================================
# Fake client with call logging (LiveLikeClient-style)
# =============================================================================


class _Validator:
    """Mimics ``schwabdev.validation.Validator`` with a toggleable flag."""

    enabled = True


class FilterFakeClient:
    """Fake schwabdev Client for testing local filter semantics (T004).

    Unlike the fake in ``test_transactions_symbol.py``, this client's
    ``transactions()`` method does NOT filter by symbol — it returns the
    full pre-configured dataset regardless of the ``symbol`` parameter.
    This is essential for testing that the orchestration performs local
    filtering (T005) rather than relying on upstream filtering.

    ``instruments()`` recognises a configurable set of known symbols and
    returns an empty response for unknown ones (dual validation, FR-003).

    All invocations are recorded in ``call_log`` for assertions.
    """

    def __init__(self) -> None:
        self._validator = _Validator()
        self._accounts: list[dict[str, str]] = []
        # {account_hash: dict} — full (unfiltered) response for transactions()
        self._tx_responses: dict[str, Any] = {}
        # Set of symbols that instruments() considers valid (directory)
        self._known_symbols: set[str] = set()
        # {account_hash: Exception} — raise instead of returning
        self._tx_errors: dict[str, Exception] = {}

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
        """Set the response ``transactions()`` returns for *account_hash*.

        The response MUST contain ALL movements for the account (no upstream
        filtering) so the test can verify local filtering.
        """
        self._tx_responses[account_hash] = data

    def set_known_symbols(self, symbols: set[str]) -> None:
        """Set the set of symbols that ``instruments()`` considers valid."""
        self._known_symbols = set(symbols)

    def set_error(self, account_hash: str, exc: Exception) -> None:
        """Make ``transactions()`` raise *exc* for *account_hash*."""
        self._tx_errors[account_hash] = exc

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

        Returns a valid response for symbols in ``_known_symbols`` and an
        empty dict for unknown symbols.
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

        Returns the FULL pre-configured dataset — does NOT filter by symbol.
        The ``symbol`` parameter is recorded in the call log but has no
        effect on the returned data, so tests can verify whether the
        orchestration passes it upstream.
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
        if accountHash in self._tx_errors:
            raise self._tx_errors[accountHash]
        return self._tx_responses.get(accountHash, {"transactions": []})


# =============================================================================
# Fixture builders
# =============================================================================


def _provider_tx(
    activity_id: str = "act-001",
    tx_type: str = "TRADE",
    description: str = "Test transaction",
    amount: float = 100.0,
    occurred_at: str = "2026-10-20T14:03:11+00:00",
    settlement_date: str = "2026-10-22",
    symbol: str | None = "SPY",
    instrument_type: str | None = "EQUITY",
) -> dict:
    """Build a minimal provider-format transaction dict (``instrument``-style)."""
    tx: dict = {
        "activityId": activity_id,
        "type": tx_type,
        "description": description,
        "amount": amount,
        "settlementDate": settlement_date,
        "transactionDate": occurred_at,
    }
    if symbol is not None or instrument_type is not None:
        instr: dict[str, str] = {}
        if symbol is not None:
            instr["symbol"] = symbol
        if instrument_type is not None:
            instr["instrumentType"] = instrument_type
        tx["instrument"] = instr
    return tx


def _provider_option_tx(
    activity_id: str = "opt-001",
    description: str = "Option trade",
    amount: float = -50.0,
    occurred_at: str = "2026-10-20T14:03:11+00:00",
    occ_symbol: str = "NOK   261218P00011000",
) -> dict:
    """Build a transaction dict for an option movement with OCC symbol."""
    return _provider_tx(
        activity_id=activity_id,
        tx_type="TRADE",
        description=description,
        amount=amount,
        occurred_at=occurred_at,
        symbol=occ_symbol,
        instrument_type="OPTION",
    )


def _provider_response(transactions: list[dict]) -> dict:
    """Wrap a list of transaction dicts into a fake provider response."""
    return {"transactions": transactions}


def _has_symbol_key(result: TransactionsResult, symbol: str) -> bool:
    """Check if any movement in *result* has the given *symbol*."""
    if not result.movements:
        return False
    return any(m.symbol == symbol for m in result.movements)


# =============================================================================
# R1 — Filter query does NOT send symbol upstream
# =============================================================================


class TestFilterDoesNotSendSymbolUpstream:
    """R1: With a filter present, the orchestration MUST NOT pass ``symbol``
    as a keyword argument to ``client.transactions()`` (research R1).

    The filter is applied locally after fetching ALL movements from every
    account.
    """

    def test_symbol_not_in_transactions_kwargs(self) -> None:
        """When ``symbol="NOK"`` is provided, the ``transactions()`` call
        kwargs MUST NOT contain a ``symbol`` key (or contain None)."""
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_known_symbols({"NOK"})
        client.set_response("acc1", _provider_response([]))

        get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="NOK",
        )

        tx_calls = [
            e for e in client.call_log if e["method"] == "transactions"
        ]
        assert len(tx_calls) >= 1, "Expected at least one transactions() call"
        for call in tx_calls:
            kwargs = call["kwargs"]
            # The symbol kwarg must NOT be present, or must be None
            assert "symbol" not in kwargs or kwargs["symbol"] is None, (
                f"symbol={kwargs.get('symbol')!r} found in transactions() "
                f"kwargs; expected it to be absent or None (R1)"
            )

    def test_symbol_absent_also_no_upstream_symbol(self) -> None:
        """Without a filter, ``symbol`` MUST also be absent from
        ``transactions()`` kwargs (no change from 006 behaviour)."""
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_response("acc1", _provider_response([]))

        get_transaction_history(client, "2026-10-01", "2026-10-20")

        tx_calls = [
            e for e in client.call_log if e["method"] == "transactions"
        ]
        assert len(tx_calls) == 1
        kwargs = tx_calls[0]["kwargs"]
        assert "symbol" not in kwargs or kwargs["symbol"] is None, (
            f"Unexpected symbol={kwargs.get('symbol')!r} in transactions() "
            f"when no filter was provided"
        )

    def test_instruments_still_called_when_filter_present(self) -> None:
        """Even though symbol is not sent upstream, the ``instruments()``
        validation upcall MUST still happen (dual validation, FR-003)."""
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_known_symbols({"NOK"})
        client.set_response("acc1", _provider_response([]))

        get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="NOK",
        )

        instr_calls = [
            e for e in client.call_log if e["method"] == "instruments"
        ]
        assert len(instr_calls) == 1, (
            f"Expected exactly 1 instruments() call, got {len(instr_calls)}"
        )
        assert instr_calls[0]["kwargs"].get("symbols") == ["NOK"], (
            f"Expected symbols=['NOK'], got "
            f"{instr_calls[0]['kwargs'].get('symbols')!r}"
        )


# =============================================================================
# Filter by underlying symbol (FR-001)
# =============================================================================


class TestFilterByUnderlyingSymbol:
    """FR-001: ``symbol="NOK"`` returns equity movements registered under
    NOK AND option movements whose OCC root is NOK — nothing else."""

    def test_underlying_returns_equity_and_options(self) -> None:
        """``symbol="NOK"`` returns the NOK equity trade AND the NOK option
        movement, but NOT the AMD option."""
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_known_symbols({"NOK"})
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id="eq-nok", symbol="NOK", instrument_type="EQUITY"),
                _provider_option_tx(activity_id="opt-nok", occ_symbol="NOK   261218P00011000"),
                _provider_option_tx(activity_id="opt-amd", occ_symbol="AMD   261120P00630000"),
                _provider_tx(activity_id="eq-aapl", symbol="AAPL", instrument_type="EQUITY"),
                _provider_tx(activity_id="no-symbol", symbol=None, instrument_type=None),
            ]),
        )

        result = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="NOK", extended=True,
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.detail == TransactionDetail.history_retrieved
        assert result.movements is not None

        returned_ids = {
            m.extended.get("activityId", "") if m.extended else ""
            for m in result.movements
        }
        # Must include the NOK equity and NOK option
        assert "eq-nok" in returned_ids, (
            "NOK equity movement must be in the filtered result"
        )
        assert "opt-nok" in returned_ids, (
            "NOK option movement must be in the filtered result"
        )
        # Must NOT include AMD option or AAPL equity
        assert "opt-amd" not in returned_ids, (
            "AMD option movement must NOT be in the filtered result"
        )
        assert "eq-aapl" not in returned_ids, (
            "AAPL equity movement must NOT be in the filtered result"
        )
        # Movements without symbol are excluded
        assert "no-symbol" not in returned_ids

        # total_count must match the filtered set
        assert result.total_count == 2, (
            f"Expected total_count=2, got {result.total_count}"
        )

    def test_underlying_no_option_activity(self) -> None:
        """When the underlying has equity activity but no options, only
        the equity movements are returned."""
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_known_symbols({"NOK"})
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id="eq-nok", symbol="NOK", instrument_type="EQUITY"),
                _provider_tx(activity_id="eq-aapl", symbol="AAPL", instrument_type="EQUITY"),
            ]),
        )

        result = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="NOK",
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.movements is not None
        assert len(result.movements) == 1
        assert result.movements[0].symbol == "NOK"

    def test_underlying_only_option_activity(self) -> None:
        """When the underlying has only option activity, those options are
        returned — the absence of equity activity is not an error."""
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_known_symbols({"NOK"})
        client.set_response(
            "acc1",
            _provider_response([
                _provider_option_tx(activity_id="opt-nok-a", occ_symbol="NOK   261218P00011000"),
                _provider_option_tx(activity_id="opt-nok-b", occ_symbol="NOK   261220C00250000"),
                _provider_tx(activity_id="eq-aapl", symbol="AAPL", instrument_type="EQUITY"),
            ]),
        )

        result = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="NOK", extended=True,
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.movements is not None
        assert result.total_count == 2
        returned_ids = {
            m.extended.get("activityId", "") if m.extended else ""
            for m in result.movements
        }
        assert "opt-nok-a" in returned_ids
        assert "opt-nok-b" in returned_ids
        assert "eq-aapl" not in returned_ids


# =============================================================================
# Full OCC symbol filter
# =============================================================================


class TestFilterByFullOCCSymbol:
    """FR-001 (M3): When the filter is a complete OCC option symbol, the
    result MUST contain ONLY movements whose symbol matches that exact
    OCC — plus any other movements whose symbol/root matches."""

    def test_full_occ_returns_only_that_option(self) -> None:
        """``symbol="NOK   261218P00011000"`` returns only movements whose
        symbol is that exact OCC."""
        occ = "NOK   261218P00011000"
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        # The OCC symbol is NOT in the known symbols directory — dual
        # validation means we proceed anyway.
        client.set_known_symbols(set())
        client.set_response(
            "acc1",
            _provider_response([
                _provider_option_tx(activity_id="opt-target", occ_symbol=occ),
                _provider_option_tx(activity_id="opt-other", occ_symbol="NOK   261220C00250000"),
                _provider_tx(activity_id="eq-nok", symbol="NOK", instrument_type="EQUITY"),
            ]),
        )

        result = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol=occ, extended=True,
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.movements is not None
        returned_ids = {
            m.extended.get("activityId", "") if m.extended else ""
            for m in result.movements
        }
        assert "opt-target" in returned_ids, (
            "The exact OCC option must be in the filtered result"
        )
        # The other NOK option does NOT match because the filter is the full
        # OCC, not the root.  The equity NOK also does NOT match because the
        # filter is the OCC, not "NOK".
        assert "opt-other" not in returned_ids, (
            "Different OCC option must NOT match full OCC filter"
        )
        assert "eq-nok" not in returned_ids, (
            "Equity NOK must NOT match a full OCC filter"
        )
        assert result.total_count == 1

    def test_full_occ_with_known_directory_also_works(self) -> None:
        """When the full OCC IS in the directory, behaviour is identical
        (dual validation, resolved path)."""
        occ = "NOK   261218P00011000"
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        # Pretend the directory knows this OCC
        client.set_known_symbols({occ})
        client.set_response(
            "acc1",
            _provider_response([
                _provider_option_tx(activity_id="opt-target", occ_symbol=occ),
                _provider_option_tx(activity_id="opt-other", occ_symbol="NOK   261220C00250000"),
            ]),
        )

        result = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol=occ, extended=True,
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.movements is not None
        assert result.total_count == 1
        returned_ids = {
            m.extended.get("activityId", "") if m.extended else ""
            for m in result.movements
        }
        assert "opt-target" in returned_ids


# =============================================================================
# Case insensitivity (R4)
# =============================================================================


class TestFilterCaseInsensitivity:
    """R4: Matching must be case-insensitive. The same movements must be
    returned for ``"nok"`` and ``"NOK"``; the same for a lowercase full
    OCC and its uppercase equivalent."""

    def test_lowercase_underlying_equals_uppercase(self) -> None:
        """``symbol="nok"`` returns the same set as ``symbol="NOK"``."""
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_known_symbols({"NOK"})
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id="eq-nok", symbol="NOK", instrument_type="EQUITY"),
                _provider_option_tx(activity_id="opt-nok", occ_symbol="NOK   261218P00011000"),
                _provider_tx(activity_id="eq-aapl", symbol="AAPL", instrument_type="EQUITY"),
            ]),
        )

        result_lower = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="nok",
        )

        client.reset_tracking()
        result_upper = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="NOK",
        )

        assert result_lower.outcome == TransactionOutcome.ok
        assert result_upper.outcome == TransactionOutcome.ok
        assert result_lower.total_count == result_upper.total_count, (
            f"Lowercase total_count={result_lower.total_count} != "
            f"uppercase total_count={result_upper.total_count}"
        )
        lower_ids = {
            m.extended.get("activityId", "") if m.extended else ""
            for m in (result_lower.movements or [])
        }
        upper_ids = {
            m.extended.get("activityId", "") if m.extended else ""
            for m in (result_upper.movements or [])
        }
        assert lower_ids == upper_ids, (
            f"Lowercase IDs {lower_ids} != uppercase IDs {upper_ids}"
        )

    def test_lowercase_full_occ_matches_uppercase(self) -> None:
        """A full OCC in lowercase matches the same movements as the
        uppercase version of that OCC."""
        occ_upper = "NOK   261218P00011000"
        occ_lower = "nok   261218p00011000"
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_known_symbols(set())
        client.set_response(
            "acc1",
            _provider_response([
                _provider_option_tx(activity_id="opt-target", occ_symbol=occ_upper),
                _provider_option_tx(activity_id="opt-other", occ_symbol="NOK   261220C00250000"),
            ]),
        )

        result_lower = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol=occ_lower,
        )

        client.reset_tracking()
        result_upper = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol=occ_upper,
        )

        assert result_lower.total_count == result_upper.total_count, (
            f"Lowercase OCC count={result_lower.total_count} != "
            f"uppercase OCC count={result_upper.total_count}"
        )
        lower_ids = {
            m.extended.get("activityId", "") if m.extended else ""
            for m in (result_lower.movements or [])
        }
        upper_ids = {
            m.extended.get("activityId", "") if m.extended else ""
            for m in (result_upper.movements or [])
        }
        assert lower_ids == upper_ids

    def test_filter_is_case_insensitive_not_lowercasing_output(self) -> None:
        """Output symbols MUST retain their original case (upper in
        practice) — only the comparison is case-insensitive."""
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_known_symbols({"NOK"})
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id="eq-nok", symbol="NOK", instrument_type="EQUITY"),
            ]),
        )

        result = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="nok",
        )

        assert result.movements is not None
        assert len(result.movements) == 1
        # The symbol in the output must be "NOK" (as recorded by the source),
        # not lowercased to "nok"
        assert result.movements[0].symbol == "NOK", (
            f"Output symbol '{result.movements[0].symbol}' should retain "
            f"original casing 'NOK'"
        )


# =============================================================================
# Subset-consistency (FR-005 / §4)
# =============================================================================


class TestSubsetConsistency:
    """FR-005: For the same date range, the filtered result MUST be exactly
    the subset of the unfiltered result formed by applying the matcher
    locally (data-model §4)."""

    def test_filtered_result_is_subset_of_unfiltered(self) -> None:
        """The filtered result (by NOK) is a strict subset of the unfiltered
        result, containing exactly the movements that match the filter."""
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_known_symbols({"NOK"})
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id="eq-nok", symbol="NOK", instrument_type="EQUITY"),
                _provider_option_tx(activity_id="opt-nok", occ_symbol="NOK   261218P00011000"),
                _provider_option_tx(activity_id="opt-amd", occ_symbol="AMD   261120P00630000"),
                _provider_tx(activity_id="eq-aapl", symbol="AAPL", instrument_type="EQUITY"),
                _provider_tx(activity_id="no-sym", symbol=None, instrument_type=None),
            ]),
        )

        # Unfiltered query
        client.reset_tracking()
        unfiltered = get_transaction_history(
            client, "2026-10-01", "2026-10-20",
        )
        assert unfiltered.outcome == TransactionOutcome.ok
        assert unfiltered.movements is not None

        # Filtered query
        client.reset_tracking()
        filtered = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="NOK",
        )
        assert filtered.outcome == TransactionOutcome.ok
        assert filtered.movements is not None

        # Apply the matcher locally to the unfiltered result
        matched_ids: set[str] = set()
        for m in unfiltered.movements:
            if movement_involves_filter(m.symbol, m.instrument_type, "NOK"):
                activity_id = m.extended.get("activityId", "") if m.extended else ""
                matched_ids.add(activity_id)

        filtered_ids = {
            m.extended.get("activityId", "") if m.extended else ""
            for m in filtered.movements
        }

        # The filtered set must be exactly the matched set
        assert filtered_ids == matched_ids, (
            f"Filtered IDs {filtered_ids} do not match matcher-applied "
            f"IDs {matched_ids}"
        )

        # Every movement in the filtered result must match the filter
        for m in filtered.movements:
            assert movement_involves_filter(m.symbol, m.instrument_type, "NOK"), (
                f"Movement {m.extended.get('activityId', '') if m.extended else '?'} "
                f"with symbol={m.symbol} does not match filter NOK"
            )

    def test_subset_consistency_multiple_accounts(self) -> None:
        """Subset-consistency holds across multiple accounts."""
        client = FilterFakeClient()
        client.set_accounts(["acc1", "acc2"])
        client.set_known_symbols({"NOK"})
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id="a1", symbol="NOK", instrument_type="EQUITY"),
                _provider_tx(activity_id="a2", symbol="AAPL", instrument_type="EQUITY"),
            ]),
        )
        client.set_response(
            "acc2",
            _provider_response([
                _provider_option_tx(activity_id="b1", occ_symbol="NOK   261218P00011000"),
                _provider_tx(activity_id="b2", symbol="MSFT", instrument_type="EQUITY"),
            ]),
        )

        # Unfiltered
        unfiltered = get_transaction_history(
            client, "2026-10-01", "2026-10-20",
        )
        assert unfiltered.movements is not None

        # Filtered
        client.reset_tracking()
        filtered = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="NOK",
        )
        assert filtered.movements is not None

        matched_ids = {
            m.extended.get("activityId", "") if m.extended else ""
            for m in unfiltered.movements
            if movement_involves_filter(m.symbol, m.instrument_type, "NOK")
        }
        filtered_ids = {
            m.extended.get("activityId", "") if m.extended else ""
            for m in filtered.movements
        }
        assert filtered_ids == matched_ids

    def test_subset_consistency_full_occ(self) -> None:
        """Subset-consistency holds for full OCC filters too."""
        occ = "NOK   261218P00011000"
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_known_symbols(set())
        client.set_response(
            "acc1",
            _provider_response([
                _provider_option_tx(activity_id="opt-target", occ_symbol=occ),
                _provider_option_tx(activity_id="opt-other", occ_symbol="NOK   261220C00250000"),
            ]),
        )

        unfiltered = get_transaction_history(
            client, "2026-10-01", "2026-10-20",
        )
        assert unfiltered.movements is not None

        client.reset_tracking()
        filtered = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol=occ,
        )

        assert filtered.movements is not None
        matched_ids = {
            m.extended.get("activityId", "") if m.extended else ""
            for m in unfiltered.movements
            if movement_involves_filter(m.symbol, m.instrument_type, occ)
        }
        filtered_ids = {
            m.extended.get("activityId", "") if m.extended else ""
            for m in filtered.movements
        }
        assert filtered_ids == matched_ids


# =============================================================================
# Pagination over filtered set (FR-006)
# =============================================================================


class TestPaginationOverFilteredSet:
    """FR-006: Pagination over the filtered set — ``total_count`` reflects
    the subset, not the full unfiltered set.  Walking with ``offset``
    produces no duplicates or omissions (SC-006)."""

    def test_total_count_reflects_filtered_subset(self) -> None:
        """``total_count`` MUST be the size of the filtered set, not the
        full unfiltered set."""
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_known_symbols({"NOK"})
        # 5 movements total, 3 match NOK
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id="a1", symbol="NOK", instrument_type="EQUITY",
                             occurred_at="2026-10-01T10:00:00+00:00"),
                _provider_tx(activity_id="a2", symbol="AAPL", instrument_type="EQUITY",
                             occurred_at="2026-10-02T10:00:00+00:00"),
                _provider_option_tx(activity_id="a3", occ_symbol="NOK   261218P00011000",
                                    occurred_at="2026-10-03T10:00:00+00:00"),
                _provider_tx(activity_id="a4", symbol="MSFT", instrument_type="EQUITY",
                             occurred_at="2026-10-04T10:00:00+00:00"),
                _provider_option_tx(activity_id="a5", occ_symbol="NOK   261220C00250000",
                                    occurred_at="2026-10-05T10:00:00+00:00"),
            ]),
        )

        # Unfiltered — total_count should be 5
        unfiltered = get_transaction_history(
            client, "2026-10-01", "2026-10-20",
        )
        assert unfiltered.total_count == 5, (
            f"Unfiltered total_count should be 5, got {unfiltered.total_count}"
        )

        # Filtered — total_count should be 3
        client.reset_tracking()
        filtered = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="NOK",
        )
        assert filtered.total_count == 3, (
            f"Filtered total_count should be 3, got {filtered.total_count}"
        )

    def test_pagination_walk_over_filtered_set(self) -> None:
        """Walking the filtered set with offset produces every filtered
        movement exactly once, with no duplicates or omissions."""
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_known_symbols({"NOK"})
        # Create 55 movements: 30 NOK-matching (15 equity + 15 options),
        # 25 non-matching (other symbols).  Page size = 50.
        # All dates must be in the past (≤ today 2026-10-23).
        movements: list[dict] = []
        for i in range(15):
            movements.append(
                _provider_tx(
                    activity_id=f"eq-nok-{i:04d}",
                    symbol="NOK", instrument_type="EQUITY",
                    occurred_at=f"2026-09-{i+1:02d}T10:00:00+00:00",
                )
            )
        for i in range(15):
            movements.append(
                _provider_option_tx(
                    activity_id=f"opt-nok-{i:04d}",
                    occ_symbol="NOK   261218P00011000",
                    occurred_at=f"2026-09-{i+16:02d}T10:00:00+00:00",
                )
            )
        for i in range(25):
            movements.append(
                _provider_tx(
                    activity_id=f"other-{i:04d}",
                    symbol="AAPL", instrument_type="EQUITY",
                    occurred_at=f"2026-09-{min(i+1, 30):02d}T10:00:00+00:00",
                )
            )
        client.set_response("acc1", _provider_response(movements))

        # Collect all filtered movements by walking pages
        all_filtered_ids: list[str] = []
        offset = 0
        for _ in range(5):  # safety limit
            client.reset_tracking()
            result = get_transaction_history(
                client, "2026-09-01", "2026-09-30", symbol="NOK",
                offset=offset, extended=True,
            )
            assert result.outcome == TransactionOutcome.ok
            assert result.movements is not None
            for m in result.movements:
                activity_id = m.extended.get("activityId", "") if m.extended else ""
                all_filtered_ids.append(activity_id)
            if not result.has_more:
                break
            assert result.next_offset is not None
            offset = result.next_offset

        # We should have collected 30 unique movements
        assert len(all_filtered_ids) == 30, (
            f"Expected 30 filtered movements across all pages, "
            f"got {len(all_filtered_ids)}"
        )
        # No duplicates
        assert len(set(all_filtered_ids)) == 30, (
            f"Duplicates found in filtered walk: "
            f"{len(all_filtered_ids)} entries, {len(set(all_filtered_ids))} unique"
        )

    def test_offset_echo_reflects_filtered_offset(self) -> None:
        """``offset_echo`` MUST echo the requested offset, calculated over
        the filtered set."""
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_known_symbols({"NOK"})
        # 10 movements, 4 match NOK
        movements = [
            _provider_tx(activity_id=f"nok-{i:04d}", symbol="NOK",
                         occurred_at=f"2026-10-{i+1:02d}T10:00:00+00:00")
            for i in range(4)
        ]
        for i in range(6):
            movements.append(
                _provider_tx(activity_id=f"other-{i:04d}", symbol="AAPL",
                             occurred_at=f"2026-10-{i+5:02d}T10:00:00+00:00")
            )
        client.set_response("acc1", _provider_response(movements))

        result = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="NOK", offset=2,
        )
        assert result.offset_echo == 2


# =============================================================================
# Dual validation — directory not resolve + matches → ok (FR-003)
# =============================================================================


class TestDualValidationDirectoryNotResolveMatchesOk:
    """FR-003: When the instrument directory does NOT resolve the filter,
    the tool MUST NOT fail immediately — it must proceed with the sweep.
    If at least one movement matches (M1/M2/M3), return ok with those
    movements."""

    def test_unknown_symbol_with_matching_movements_returns_ok(self) -> None:
        """When ``instruments()`` returns empty for an OCC filter but
        movements matching that OCC exist, the result is ``ok`` with the
        matching movements."""
        occ = "NOK   261218P00011000"
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        # NOT in known symbols — directory does NOT resolve
        client.set_known_symbols(set())
        client.set_response(
            "acc1",
            _provider_response([
                _provider_option_tx(activity_id="opt-target", occ_symbol=occ),
            ]),
        )

        result = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol=occ,
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.movements is not None
        assert len(result.movements) == 1
        assert result.total_count == 1

    def test_unknown_underlying_with_option_matches_returns_ok(self) -> None:
        """When the directory does not know ``"NOK"`` but option movements
        with root NOK exist, the result is ``ok`` with those options."""
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        # "NOK" is NOT a known symbol in the directory
        client.set_known_symbols({"AAPL", "MSFT"})
        client.set_response(
            "acc1",
            _provider_response([
                _provider_option_tx(activity_id="opt-nok", occ_symbol="NOK   261218P00011000"),
                _provider_tx(activity_id="eq-aapl", symbol="AAPL", instrument_type="EQUITY"),
            ]),
        )

        result = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="NOK", extended=True,
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.movements is not None
        assert result.total_count == 1
        activity_id = (
            result.movements[0].extended.get("activityId", "")
            if result.movements[0].extended else ""
        )
        assert activity_id == "opt-nok"

    def test_directory_resolve_also_returns_ok(self) -> None:
        """When the directory DOES resolve, the result is also ok —
        consistency with the resolved path."""
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_known_symbols({"NOK"})
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id="eq-nok", symbol="NOK", instrument_type="EQUITY"),
            ]),
        )

        result = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="NOK",
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.total_count == 1


# =============================================================================
# Dual validation — directory not resolve + 0 matches → InstrumentNotFoundError
# =============================================================================


class TestDualValidationDirectoryNotResolveZeroMatches:
    """FR-003: When the directory does NOT resolve the filter AND zero
    movements match after the sweep, the tool MUST raise
    ``InstrumentNotFoundError`` (naming the filter) — never an ambiguous
    ``no_movements``."""

    def test_unknown_symbol_no_matches_raises_instrument_not_found(self) -> None:
        """A mistyped symbol (not in directory, no matching movements)
        raises ``InstrumentNotFoundError`` naming the symbol."""
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_known_symbols(set())
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id="a1", symbol="AAPL", instrument_type="EQUITY"),
                _provider_tx(activity_id="a2", symbol="MSFT", instrument_type="EQUITY"),
            ]),
        )

        with pytest.raises(InstrumentNotFoundError) as exc:
            get_transaction_history(
                client, "2026-10-01", "2026-10-20", symbol="ZZYYY_FAKE",
            )
        msg = str(exc.value)
        assert "ZZYYY_FAKE" in msg, (
            f"Error must name the unknown symbol, got: {msg}"
        )

    def test_unknown_underlying_no_option_matches_raises_instrument_not_found(
        self,
    ) -> None:
        """An unknown underlying with no matching movements in any form
        raises ``InstrumentNotFoundError``."""
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_known_symbols(set())
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id="a1", symbol="AAPL", instrument_type="EQUITY"),
            ]),
        )

        with pytest.raises(InstrumentNotFoundError) as exc:
            get_transaction_history(
                client, "2026-10-01", "2026-10-20", symbol="BOGUS",
            )
        assert "BOGUS" in str(exc.value)

    def test_known_symbol_no_movements_yields_no_movements_for_instrument(
        self,
    ) -> None:
        """When the directory DOES resolve but no movements match, the
        result is ``ok/no_movements_for_instrument`` — NOT
        ``InstrumentNotFoundError``."""
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_known_symbols({"NOK"})
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id="a1", symbol="AAPL", instrument_type="EQUITY"),
            ]),
        )

        result = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="NOK",
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.detail == TransactionDetail.no_movements_for_instrument
        assert result.movements == []
        assert result.total_count == 0


# =============================================================================
# ToolError conversion for InstrumentNotFoundError (FR-009d)
# =============================================================================


class TestToolErrorConversion:
    """Via ``get_transaction_history_tool``, ``InstrumentNotFoundError``
    MUST be converted to an MCP ``ToolError`` so the actionable message
    reaches the agent."""

    def test_instrument_not_found_becomes_tool_error(self) -> None:
        """When dual validation fails (no directory, no matches), the
        tool wrapper converts to ``ToolError`` naming the symbol."""
        from mcp.server.mcpserver.exceptions import ToolError

        from schwab_mcp.transactions import get_transaction_history_tool

        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_known_symbols(set())
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id="a1", symbol="AAPL"),
            ]),
        )

        with pytest.raises(ToolError) as exc:
            get_transaction_history_tool(
                client, "2026-10-01", "2026-10-20", symbol="ZYXW_NONE",
            )
        assert "ZYXW_NONE" in str(exc.value), (
            f"ToolError must name the symbol, got: {exc.value}"
        )

    def test_ok_result_no_tool_error(self) -> None:
        """When dual validation succeeds (directory resolves or matches
        found), the tool wrapper returns a normal ``TransactionsResult``."""
        from schwab_mcp.transactions import get_transaction_history_tool

        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_known_symbols({"NOK"})
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id="a1", symbol="NOK"),
            ]),
        )

        # Should not raise
        result = get_transaction_history_tool(
            client, "2026-10-01", "2026-10-20", symbol="NOK",
        )
        assert result.outcome == TransactionOutcome.ok


# =============================================================================
# CURRENCY_USD (data-model §2-paso 4)
# =============================================================================


class TestCurrencyUSDFilter:
    """CURRENCY_USD is an internal cash identifier not in the instrument
    directory.  Under dual validation, movements whose symbol is
    ``CURRENCY_USD`` MUST be returned (M1 match)."""

    def test_currency_usd_returns_its_movements(self) -> None:
        """``symbol="CURRENCY_USD"`` returns movements whose symbol is
        ``CURRENCY_USD``, even though the directory does not resolve it."""
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        # NOT in the directory
        client.set_known_symbols({"AAPL", "MSFT"})
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(
                    activity_id="cash-1", symbol="CURRENCY_USD",
                    instrument_type="CURRENCY",
                    description="Cash movement",
                ),
                _provider_tx(activity_id="a1", symbol="AAPL", instrument_type="EQUITY"),
            ]),
        )

        result = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="CURRENCY_USD",
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.movements is not None
        assert result.total_count == 1
        assert result.movements[0].symbol == "CURRENCY_USD", (
            f"Expected CURRENCY_USD movement, got {result.movements[0].symbol}"
        )

    def test_currency_usd_no_movements_raises_instrument_not_found(self) -> None:
        """When no movement has symbol ``CURRENCY_USD``, and the directory
        does not resolve it, the result is ``InstrumentNotFoundError``."""
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_known_symbols({"AAPL"})
        client.set_response(
            "acc1",
            _provider_response([
                _provider_tx(activity_id="a1", symbol="AAPL", instrument_type="EQUITY"),
            ]),
        )

        with pytest.raises(InstrumentNotFoundError) as exc:
            get_transaction_history(
                client, "2026-10-01", "2026-10-20", symbol="CURRENCY_USD",
            )
        assert "CURRENCY_USD" in str(exc.value)


# =============================================================================
# partial_failure with filter (FR-008)
# =============================================================================


class TestPartialFailureWithFilter:
    """FR-008: With filter active, per-account failures MUST be reported
    explicitly — successful accounts contribute only movements that match
    the filter, and the tool never discards an entire account due to the
    filter."""

    def test_partial_failure_filters_successful_accounts(self) -> None:
        """When one account fails and another succeeds, the result is
        ``partial_failure`` with the failed account in ``accounts_failed``
        and the successful account's movements filtered by the symbol."""
        from schwab_mcp.errors import ConnectivityError

        client = FilterFakeClient()
        client.set_accounts(["acc_ok", "acc_fail"])
        client.set_known_symbols({"NOK"})
        client.set_response(
            "acc_ok",
            _provider_response([
                _provider_tx(activity_id="ok-nok", symbol="NOK", instrument_type="EQUITY"),
                _provider_tx(activity_id="ok-aapl", symbol="AAPL", instrument_type="EQUITY"),
            ]),
        )
        client.set_error("acc_fail", ConnectivityError(detail="Timeout"))

        result = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="NOK", extended=True,
        )

        assert result.outcome == TransactionOutcome.partial_failure
        assert result.detail == TransactionDetail.account_failed
        assert result.accounts_failed is not None
        assert [af.account_hash for af in result.accounts_failed] == ["acc_fail"]

        # Successful account's movements should be FILTERED by NOK
        assert result.movements is not None
        assert result.total_count == 1, (
            f"Expected 1 NOK movement from successful account, "
            f"got {result.total_count}"
        )
        activity_id = (
            result.movements[0].extended.get("activityId", "")
            if result.movements[0].extended else ""
        )
        assert activity_id == "ok-nok", (
            f"Expected 'ok-nok' movement, got {activity_id}"
        )

    def test_partial_failure_all_accounts_fail_with_filter(self) -> None:
        """When ALL accounts fail with the filter active, the result is
        ``partial_failure`` (all accounts in ``accounts_failed``), not
        ``transient_failure`` — matching the existing pattern from
        ``test_transactions_query.py``."""
        client = FilterFakeClient()
        client.set_accounts(["acc_fail1", "acc_fail2"])
        client.set_known_symbols({"NOK"})
        # Use generic Exceptions (not ConnectivityError) to match the
        # existing fail-fast behaviour: ConnectivityError on the first
        # account with no prior success would short-circuit to transient.
        client.set_error("acc_fail1", Exception("Provider error"))
        client.set_error("acc_fail2", Exception("Another error"))

        result = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="NOK",
        )

        assert result.outcome == TransactionOutcome.partial_failure
        assert result.accounts_failed is not None
        assert len(result.accounts_failed) == 2
        assert result.movements == []
        assert result.total_count == 0

    def test_partial_failure_with_filter_resolved_directory(self) -> None:
        """Partial failure behaviour is the same regardless of whether
        the directory resolved the filter."""
        from schwab_mcp.errors import ConnectivityError

        client = FilterFakeClient()
        client.set_accounts(["acc_ok", "acc_fail"])
        # Directory does NOT resolve "NOK"
        client.set_known_symbols({"AAPL"})
        client.set_response(
            "acc_ok",
            _provider_response([
                _provider_option_tx(
                    activity_id="ok-opt", occ_symbol="NOK   261218P00011000",
                ),
            ]),
        )
        client.set_error("acc_fail", ConnectivityError(detail="Down"))

        result = get_transaction_history(
            client, "2026-10-01", "2026-10-20", symbol="NOK",
        )

        assert result.outcome == TransactionOutcome.partial_failure
        assert result.accounts_failed is not None
        assert "acc_fail" in {af.account_hash for af in result.accounts_failed}
        # The successful account's option movement should match the filter
        assert result.movements is not None
        assert result.total_count == 1


# =============================================================================
# No-regression: instruments() not called when no symbol
# =============================================================================


class TestNoInstrumentsUpcallWithoutFilter:
    """When no ``symbol`` is provided, the orchestration MUST NOT call
    ``instruments()`` at all (no change from 006 behaviour)."""

    def test_no_symbol_no_instruments_call(self) -> None:
        """Without a symbol filter, zero ``instruments()`` upcalls."""
        client = FilterFakeClient()
        client.set_accounts(["acc1"])
        client.set_response("acc1", _provider_response([]))

        get_transaction_history(client, "2026-10-01", "2026-10-20")

        instr_calls = [
            e for e in client.call_log if e["method"] == "instruments"
        ]
        assert len(instr_calls) == 0, (
            f"Expected 0 instruments() calls without symbol, "
            f"got {len(instr_calls)}"
        )