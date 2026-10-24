"""Failing (Red) unit tests for deterministic offset-based pagination (US3).

These are TDD red-phase tests: ``get_transaction_history`` already exists
in ``schwab_mcp.transactions`` and currently returns ALL movements in a
single page (``has_more=False``, ``returned=len(movements)``). The
pagination slicing logic (page size 50, ``next_offset``, ``has_more``,
sort tiebreak) does NOT exist yet, so every pagination assertion will fail.

References
----------
- specs/006-transaction-history/tasks.md T020
- specs/006-transaction-history/spec.md US3 (FR-006, SC-006)
- specs/006-transaction-history/data-model.md (§TransactionsResult,
  invariants 2, 3, pagination fields)
- specs/006-transaction-history/plan.md (clarify Q4: page size 50)
"""

from __future__ import annotations

from typing import Any

import pytest

from schwab_mcp.transactions import (
    MovementEntry,
    TransactionDetail,
    TransactionOutcome,
    TransactionsResult,
)


# =============================================================================
# Fake client (reused pattern from test_transactions_query.py)
# =============================================================================


class _validator:
    """Mimics ``schwabdev.validation.Validator`` with a toggleable flag."""

    enabled = True


class FakeClient:
    """Fake schwabdev Client that returns pre-configured transaction payloads.

    ``linked_accounts()`` returns a list of ``{"accountHash": str}`` dicts.
    ``transactions()`` returns a pre-configured response per account hash.
    """

    def __init__(self) -> None:
        self._validator = _validator()
        self._accounts: list[dict[str, str]] = []
        self._tx_responses: dict[str, Any] = {}

        self.call_log: list[dict[str, Any]] = []

    def linked_accounts(self) -> list[dict[str, str]]:
        self.call_log.append({"method": "linked_accounts", "kwargs": {}})
        return list(self._accounts)

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
        return self._tx_responses.get(accountHash, {"transactions": []})

    def set_accounts(self, hashes: list[str]) -> None:
        self._accounts = [{"accountHash": h} for h in hashes]

    def set_response(self, account_hash: str, data: dict) -> None:
        self._tx_responses[account_hash] = data


# =============================================================================
# Helpers: build provider-format transaction dicts
# =============================================================================

# The 3 accounts used in the 137-movement fixture
ACCOUNTS = ["acc_a", "acc_b", "acc_c"]


def _provider_tx(
    activity_id: str = "act-000",
    tx_type: str = "TRADE",
    description: str = "Test transaction",
    net_amount: float = 100.0,
    transaction_date: str = "2026-10-01T09:00:00+00:00",
    account_hash: str = "acc_a",
    symbol: str | None = "SPY",
    instrument_type: str | None = "EQUITY",
) -> dict:
    """Build a single provider-format transaction dict.

    Uses the correct field names that ``map_provider_transactions`` reads
    (``transactionDate``, ``netAmount``, ``accountHash``).
    """
    tx: dict[str, Any] = {
        "activityId": activity_id,
        "type": tx_type,
        "transactionDate": transaction_date,
        "description": description,
        "netAmount": net_amount,
        "accountHash": account_hash,
    }
    if symbol is not None:
        tx["symbol"] = symbol
    if instrument_type is not None:
        tx["instrumentType"] = instrument_type
    return tx


def _provider_response(transactions: list[dict]) -> dict:
    """Wrap transaction dicts into a fake provider response."""
    return {"transactions": transactions}


# =============================================================================
# Fixture builders (regular functions, not pytest fixtures — called directly)
# =============================================================================


def _client_one_account() -> FakeClient:
    """A fake client with a single account (acc_a) and 10 movements."""
    client = FakeClient()
    client.set_accounts(["acc_a"])
    txs = [
        _provider_tx(
            activity_id=f"act-a{i:03d}",
            transaction_date=f"2026-10-01T09:{i:02d}:00+00:00",
            account_hash="acc_a",
        )
        for i in range(10)
    ]
    client.set_response("acc_a", _provider_response(txs))
    return client


def _client_137_movements() -> FakeClient:
    """A fake client with 3 accounts yielding exactly 137 movements total.

    Distribution: acc_a = 50, acc_b = 50, acc_c = 37.

    Each movement gets a globally unique ISO-8601 timestamp.  Timestamps
    are constructed from ``global_idx``, spreading across multiple days
    so the sort is meaningful.  Within each account, timestamps are
    monotonically increasing and unique, so the dedup key
    ``(account_hash, occurred_at)`` is always unique.
    """
    client = FakeClient()
    client.set_accounts(ACCOUNTS)

    txs: list[dict] = []

    # acc_a: 50 movements, acc_b: 50 movements, acc_c: 37 movements
    counts: dict[str, int] = {"acc_a": 50, "acc_b": 50, "acc_c": 37}
    counter: dict[str, int] = {"acc_a": 0, "acc_b": 0, "acc_c": 0}

    for global_idx in range(137):
        acct = ACCOUNTS[global_idx % 3]
        seq = counter[acct]
        counter[acct] += 1

        # Build a deterministic, chronological timestamp.
        # global_idx 0..137 => day 1..3, hour 0..23, minute 0..59, sec 0..59
        h = (global_idx * 7) % 24
        m = (global_idx * 13) % 60
        s = (global_idx * 19) % 60
        day = 1 + global_idx // 60
        ts = f"2026-10-{day:02d}T{h:02d}:{m:02d}:{s:02d}+00:00"

        txs.append(
            _provider_tx(
                activity_id=f"act-{acct}-{seq:03d}",
                transaction_date=ts,
                account_hash=acct,
                symbol="SPY" if (seq % 2 == 0) else "AAPL",
            )
        )

    # Assign responses per account
    for acct in ACCOUNTS:
        account_txs = [tx for tx in txs if tx["accountHash"] == acct]
        client.set_response(acct, _provider_response(account_txs))

    return client


# =============================================================================
# Test classes — Chronological order & tiebreak
# =============================================================================


class TestPaginationChronologicalOrder:
    """US3: Movements must appear in ascending chronological order, with
    tiebreak by ``(account_hash, activityId)`` when timestamps are equal.

    The current orchestration sorts only by ``occurred_at`` (lexicographic
    string sort), so the tiebreak assertions below WILL fail (Red).
    """

    def test_movements_sorted_by_occurred_at_ascending(self) -> None:
        """All returned movements MUST be in ascending ``occurred_at`` order."""
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_137_movements(), "2026-10-01", "2026-10-05",
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.movements is not None
        assert len(result.movements) > 1

        timestamps = [m.occurred_at for m in result.movements]
        for i in range(len(timestamps) - 1):
            assert timestamps[i] <= timestamps[i + 1], (
                f"Movement {i} ({timestamps[i]}) is after movement "
                f"{i + 1} ({timestamps[i + 1]}); expected "
                f"chronological order"
            )

    def test_tiebreak_by_account_hash_then_activity_id(self) -> None:
        """When ``occurred_at`` is equal, sort by ``account_hash``
        (lexicographic), then by ``activityId`` (from ``extended`` dict).

        Current code does NOT implement this tiebreak, so this test FAILS.
        """
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_137_movements(), "2026-10-01", "2026-10-05",
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.movements is not None
        assert len(result.movements) > 1

        for i in range(len(result.movements) - 1):
            a = result.movements[i]
            b = result.movements[i + 1]
            if a.occurred_at == b.occurred_at:
                # Same timestamp → tiebreak by account_hash
                if a.account_hash == b.account_hash:
                    # Same account → tiebreak by activityId (from extended)
                    a_id = (a.extended or {}).get("activityId", "")
                    b_id = (b.extended or {}).get("activityId", "")
                    assert a_id <= b_id, (
                        f"Tiebreak within same account: activityId "
                        f"{a_id!r} after {b_id!r}"
                    )
                else:
                    assert a.account_hash < b.account_hash, (
                        f"Tiebreak on equal timestamp: account "
                        f"{a.account_hash!r} after {b.account_hash!r}"
                    )


# =============================================================================
# Test classes — Pagination fields & behaviour
# =============================================================================


class TestPaginationPageBoundary:
    """US3: Page size is 50 movements maximum (clarify Q4)."""

    def test_page_size_max_50_offset_0(self) -> None:
        """Calling with ``offset=0`` when 137 movements exist MUST return
        at most 50 movements."""
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_137_movements(), "2026-10-01", "2026-10-05", offset=0,
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.movements is not None
        # Current code returns ALL 137 — this assertion WILL fail
        assert len(result.movements) == 50, (
            f"Expected page of 50 movements at offset=0, "
            f"got {len(result.movements)}"
        )

    def test_page_size_max_50_offset_50(self) -> None:
        """Calling with ``offset=50`` returns page 2, at most 50 movements."""
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_137_movements(), "2026-10-01", "2026-10-05", offset=50,
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.movements is not None
        # Current code returns ALL 137 ignoring offset — this WILL fail
        assert len(result.movements) == 50, (
            f"Expected page of 50 movements at offset=50, "
            f"got {len(result.movements)}"
        )

    def test_page_size_max_50_offset_100(self) -> None:
        """Calling with ``offset=100`` returns page 3 with 37 items (< 50)."""
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_137_movements(), "2026-10-01", "2026-10-05", offset=100,
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.movements is not None
        # Current code returns ALL 137 — this WILL fail
        assert len(result.movements) == 37, (
            f"Expected 37 movements on last page (offset=100), "
            f"got {len(result.movements)}"
        )


class TestPaginationTotalCount:
    """``total_count`` MUST always reflect the FULL range, not the page."""

    def test_total_count_is_137_not_50(self) -> None:
        """``total_count`` MUST be 137 (the full range), not 50 (page size)."""
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_137_movements(), "2026-10-01", "2026-10-05", offset=0,
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.total_count == 137, (
            f"Expected total_count=137 for full range, "
            f"got {result.total_count}"
        )

    def test_total_count_same_regardless_of_offset(self) -> None:
        """``total_count`` MUST be identical for every page of the same query."""
        from schwab_mcp.transactions import get_transaction_history

        client = _client_137_movements()

        r0 = get_transaction_history(client, "2026-10-01", "2026-10-05", offset=0)
        r1 = get_transaction_history(client, "2026-10-01", "2026-10-05", offset=50)
        r100 = get_transaction_history(client, "2026-10-01", "2026-10-05", offset=100)

        assert r0.total_count == r1.total_count == r100.total_count == 137, (
            f"total_count differs across pages: "
            f"offset=0 -> {r0.total_count}, "
            f"offset=50 -> {r1.total_count}, "
            f"offset=100 -> {r100.total_count}"
        )


class TestPaginationContinuationIndicators:
    """US3 rules (invariants 2 and 3 from data-model.md):

    2. ``has_more=true`` <=> ``next_offset`` present AND ``returned == 50``
    3. ``next_offset`` present => ``has_more=true``
    """

    def test_has_more_true_when_next_offset_present(self) -> None:
        """``has_more`` MUST be ``true`` when ``next_offset`` is present."""
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_137_movements(), "2026-10-01", "2026-10-05", offset=0,
        )

        assert result.outcome == TransactionOutcome.ok
        # Current code: has_more=False always -- this WILL fail
        assert result.has_more is True, (
            "Expected has_more=True when more than 50 movements exist"
        )
        assert result.next_offset == 50, (
            f"Expected next_offset=50, got {result.next_offset}"
        )
        assert result.returned == 50, (
            f"Expected returned=50, got {result.returned}"
        )

    def test_has_more_false_on_last_page(self) -> None:
        """The final page MUST have ``has_more=False`` and no ``next_offset``."""
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_137_movements(), "2026-10-01", "2026-10-05", offset=100,
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.has_more is False
        assert result.next_offset is None, (
            f"Expected no next_offset on last page, "
            f"got {result.next_offset}"
        )

    def test_has_more_false_when_all_fit_in_one_page(self) -> None:
        """When all movements fit in one page (<= 50), there MUST be no
        continuation indicator."""
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_one_account(), "2026-10-01", "2026-10-05",
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.has_more is False
        assert result.next_offset is None
        assert result.returned == 10

    def test_next_offset_implies_has_more_true(self) -> None:
        """If ``next_offset`` is set, ``has_more`` MUST be ``true``."""
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_137_movements(), "2026-10-01", "2026-10-05", offset=0,
        )

        assert result.outcome == TransactionOutcome.ok
        if result.next_offset is not None:
            assert result.has_more is True, (
                "has_more must be true when next_offset is present"
            )

    def test_no_continuation_on_empty_result(self) -> None:
        """An empty result (no movements) MUST have ``has_more=False`` and
        ``next_offset=None``."""
        from schwab_mcp.transactions import get_transaction_history

        client = FakeClient()
        client.set_accounts(["acc_a"])
        client.set_response("acc_a", _provider_response([]))

        result = get_transaction_history(client, "2026-10-01", "2026-10-05")

        assert result.outcome == TransactionOutcome.ok
        assert result.movements == []
        assert result.total_count == 0
        assert result.returned == 0
        assert result.has_more is False
        assert result.next_offset is None


class TestPaginationOffsetEcho:
    """``offset_echo`` MUST reflect the ``offset`` applied to the request."""

    def test_offset_echo_0(self) -> None:
        """``offset_echo`` is 0 when ``offset=0``."""
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_137_movements(), "2026-10-01", "2026-10-05", offset=0,
        )
        assert result.offset_echo == 0

    def test_offset_echo_50(self) -> None:
        """``offset_echo`` is 50 when ``offset=50``."""
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_137_movements(), "2026-10-01", "2026-10-05", offset=50,
        )
        assert result.offset_echo == 50

    def test_offset_echo_100(self) -> None:
        """``offset_echo`` is 100 when ``offset=100``."""
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_137_movements(), "2026-10-01", "2026-10-05", offset=100,
        )
        assert result.offset_echo == 100

    def test_offset_echo_default(self) -> None:
        """``offset_echo`` is 0 when ``offset`` is not passed (default)."""
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_one_account(), "2026-10-01", "2026-10-05",
        )
        assert result.offset_echo == 0


class TestPaginationLastPagePartial:
    """The last page MUST contain fewer than 50 items and
    ``has_more=false``."""

    def test_last_page_returns_remaining_items(self) -> None:
        """With 137 total, offset=100 returns exactly 37 items."""
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_137_movements(), "2026-10-01", "2026-10-05", offset=100,
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.movements is not None
        # Current code returns 137 -- this will fail
        assert len(result.movements) == 37, (
            f"Expected 37 remaining movements at offset=100, "
            f"got {len(result.movements)}"
        )
        assert result.returned == 37, (
            f"Expected returned=37, got {result.returned}"
        )

    def test_last_page_has_more_false(self) -> None:
        """The last page MUST have ``has_more=false``."""
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_137_movements(), "2026-10-01", "2026-10-05", offset=100,
        )
        assert result.has_more is False

    def test_last_page_returned_less_than_50(self) -> None:
        """``returned`` MUST be < 50 on the last page."""
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_137_movements(), "2026-10-01", "2026-10-05", offset=100,
        )
        assert result.returned is not None
        # Current code returns 137 which is NOT < 50 -- this WILL fail
        assert result.returned < 50, (
            f"Expected returned < 50 on last page, got {result.returned}"
        )


class TestPaginationReturnedField:
    """``returned`` MUST always be the length of the ``movements`` list."""

    def test_returned_matches_movements_length_page_1(self) -> None:
        """``returned`` == len(movements) for the first page."""
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_137_movements(), "2026-10-01", "2026-10-05", offset=0,
        )
        assert result.movements is not None
        assert result.returned == len(result.movements), (
            f"returned ({result.returned}) != len(movements) "
            f"({len(result.movements)})"
        )

    def test_returned_matches_movements_length_last_page(self) -> None:
        """``returned`` == len(movements) for the last page."""
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_137_movements(), "2026-10-01", "2026-10-05", offset=100,
        )
        assert result.movements is not None
        assert result.returned == len(result.movements), (
            f"returned ({result.returned}) != len(movements) "
            f"({len(result.movements)})"
        )


# =============================================================================
# Test class -- Full walk of 137 movements (SC-006)
# =============================================================================


class TestPaginationFullWalk:
    """SC-006: Walking offset 0->50->100->137 covers every movement exactly once,
    with zero duplicates and zero omissions.

    Current implementation returns all 137 on every call, so every assertion
    about page boundaries and cumulative coverage WILL fail.
    """

    def test_full_walk_no_duplicates_no_omissions(self) -> None:
        """The union of all pages MUST contain exactly 137 unique movements.
        No duplicate activityIds and no omitted ones."""
        from schwab_mcp.transactions import get_transaction_history

        client = _client_137_movements()
        all_seen: list[MovementEntry] = []

        # Walk pages
        offset = 0
        page_num = 0
        while True:
            result = get_transaction_history(
                client, "2026-10-01", "2026-10-05", offset=offset,
            )
            assert result.outcome == TransactionOutcome.ok
            assert result.movements is not None

            page_num += 1
            all_seen.extend(result.movements)

            if not result.has_more:
                break

            assert result.next_offset is not None, (
                f"Page {page_num} has has_more=true but next_offset is None"
            )
            offset = result.next_offset

        # Verify total count
        assert len(all_seen) == 137, (
            f"Full walk collected {len(all_seen)} movements, expected 137"
        )

        # Verify no duplicates by (account_hash, activityId)
        seen_keys: set[tuple[str, str | None]] = set()
        for m in all_seen:
            if m.extended and "activityId" in m.extended:
                key = (m.account_hash, m.extended["activityId"])
            else:
                key = (m.account_hash, m.occurred_at)
            assert key not in seen_keys, (
                f"Duplicate movement detected: account={m.account_hash}, "
                f"occurred_at={m.occurred_at}"
            )
            seen_keys.add(key)

        assert len(seen_keys) >= 137, (
            f"Expected at least 137 unique keys, got {len(seen_keys)}"
        )

        # Verify chronological order across page boundaries
        for i in range(len(all_seen) - 1):
            a = all_seen[i]
            b = all_seen[i + 1]
            assert a.occurred_at <= b.occurred_at, (
                f"Chronological order violation across pages at index {i}: "
                f"{a.occurred_at} after {b.occurred_at}"
            )

    def test_full_walk_exactly_3_pages(self) -> None:
        """137 movements at 50/page = exactly 3 pages (50 + 50 + 37)."""
        from schwab_mcp.transactions import get_transaction_history

        client = _client_137_movements()
        offsets_seen: list[int] = []
        pages = 0

        offset = 0
        while True:
            offsets_seen.append(offset)
            result = get_transaction_history(
                client, "2026-10-01", "2026-10-05", offset=offset,
            )
            assert result.outcome == TransactionOutcome.ok
            pages += 1

            if not result.has_more:
                break
            assert result.next_offset is not None
            offset = result.next_offset

        assert pages == 3, (
            f"Expected exactly 3 pages for 137 movements, got {pages}"
        )
        assert offsets_seen == [0, 50, 100], (
            f"Expected offsets [0, 50, 100], got {offsets_seen}"
        )

    def test_full_walk_page_sizes(self) -> None:
        """Page sizes must be [50, 50, 37] for the 3 pages."""
        from schwab_mcp.transactions import get_transaction_history

        client = _client_137_movements()
        page_sizes: list[int] = []

        offset = 0
        while True:
            result = get_transaction_history(
                client, "2026-10-01", "2026-10-05", offset=offset,
            )
            assert result.outcome == TransactionOutcome.ok
            assert result.movements is not None
            page_sizes.append(len(result.movements))

            if not result.has_more:
                break
            assert result.next_offset is not None
            offset = result.next_offset

        assert page_sizes == [50, 50, 37], (
            f"Expected page sizes [50, 50, 37], got {page_sizes}"
        )

    def test_full_walk_total_count_per_page(self) -> None:
        """``total_count`` MUST be 137 on every page throughout the walk."""
        from schwab_mcp.transactions import get_transaction_history

        client = _client_137_movements()
        offset = 0

        while True:
            result = get_transaction_history(
                client, "2026-10-01", "2026-10-05", offset=offset,
            )
            assert result.outcome == TransactionOutcome.ok
            assert result.total_count == 137, (
                f"total_count should be 137 on every page, "
                f"got {result.total_count} at offset={offset}"
            )

            if not result.has_more:
                break
            assert result.next_offset is not None
            offset = result.next_offset


# =============================================================================
# Test class -- Range that fits in one page
# =============================================================================


class TestPaginationSinglePage:
    """When the full result fits in one page (<= 50 movements), there MUST be
    no continuation indicator."""

    def test_no_continuation_on_10_movements(self) -> None:
        """10 movements fit in one page -> no continuation indicator."""
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_one_account(), "2026-10-01", "2026-10-05",
        )

        assert result.outcome == TransactionOutcome.ok
        assert result.has_more is False
        assert result.next_offset is None
        assert result.returned == 10
        assert result.total_count == 10

    def test_no_continuation_on_exactly_50_movements(self) -> None:
        """Exactly 50 movements fit in one page -> no continuation indicator
        because there is nothing beyond."""
        from schwab_mcp.transactions import get_transaction_history

        # Build a client with exactly 50 movements across accounts
        client = FakeClient()
        client.set_accounts(["acc_a"])
        txs = [
            _provider_tx(
                activity_id=f"act-{i:03d}",
                transaction_date="2026-10-01T09:00:00+00:00",
                account_hash="acc_a",
            )
            for i in range(50)
        ]
        client.set_response("acc_a", _provider_response(txs))

        result = get_transaction_history(client, "2026-10-01", "2026-10-05")

        assert result.outcome == TransactionOutcome.ok
        assert result.has_more is False
        assert result.next_offset is None
        assert result.returned == 50
        assert result.total_count == 50


# =============================================================================
# Test class -- offset_echo edge cases
# =============================================================================


class TestPaginationOffsetEchoEdgeCases:
    """``offset_echo`` edge cases."""

    def test_offset_echo_non_default(self) -> None:
        """``offset_echo`` reflects any positive offset value."""
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_137_movements(), "2026-10-01", "2026-10-05", offset=42,
        )
        # offset_echo works already -- this should PASS
        assert result.offset_echo == 42

    def test_offset_echo_large_offset(self) -> None:
        """``offset_echo`` reflects a large offset beyond the result set."""
        from schwab_mcp.transactions import get_transaction_history

        result = get_transaction_history(
            _client_137_movements(), "2026-10-01", "2026-10-05", offset=999,
        )
        # offset_echo works -- this should PASS
        assert result.offset_echo == 999