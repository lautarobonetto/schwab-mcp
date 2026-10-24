"""Failing unit tests for bisection split mechanism (TDD red-phase).

Tests cover the recursive bisection split that handles the upstream
3000-transaction limit (research D3), boundary conditions, deduplication
by ``(account_hash, activityId)``, and fusion integrity (SC-004).

Every test imports functions that **do not exist yet** in
``schwab_mcp.transactions``, so they will fail with ``ImportError`` /
``ModuleNotFoundError``. Once implemented (T012), all tests should pass.

References
----------
- specs/006-transaction-history/research.md (R3 — upstream 3000 limit)
- specs/006-transaction-history/tasks.md (T008)
- specs/006-transaction-history/contracts/mcp-tools.md (guarantees)
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest


# =============================================================================
# Trigger condition: _should_split
# =============================================================================


class TestShouldSplit:
    """_should_split(movements: list, range_days: int) -> bool

    Determines whether a date range needs bisection. Returns ``True``
    when the movement count is >= 3000 (the upstream cap) and the range
    spans more than 1 day. A 1-day sub-range at the cap still triggers
    the check, but the recursion stops because it cannot be split further.
    """

    def test_exactly_3000_triggers_split(self) -> None:
        """Exactly 3000 movements triggers bisection (the upstream cap)."""
        from schwab_mcp.transactions import _should_split

        movements = [object() for _ in range(3000)]
        assert _should_split(movements, range_days=30) is True

    def test_2999_does_not_trigger_split(self) -> None:
        """2999 movements does NOT trigger bisection (below cap)."""
        from schwab_mcp.transactions import _should_split

        movements = [object() for _ in range(2999)]
        assert _should_split(movements, range_days=30) is False

    def test_3001_triggers_split(self) -> None:
        """3001 movements triggers bisection (exceeds cap, edge case)."""
        from schwab_mcp.transactions import _should_split

        movements = [object() for _ in range(3001)]
        assert _should_split(movements, range_days=30) is True

    def test_empty_movements_does_not_trigger(self) -> None:
        """Empty movements list does NOT trigger bisection."""
        from schwab_mcp.transactions import _should_split

        assert _should_split([], range_days=30) is False

    def test_2999_long_range_does_not_trigger(self) -> None:
        """2999 movements even over a long range does NOT trigger."""
        from schwab_mcp.transactions import _should_split

        movements = [object() for _ in range(2999)]
        assert _should_split(movements, range_days=365) is False

    def test_one_movement_does_not_trigger(self) -> None:
        """A single movement never triggers bisection."""
        from schwab_mcp.transactions import _should_split

        assert _should_split([object()], range_days=30) is False

    def test_exactly_3000_with_single_day_range(self) -> None:
        """3000 on a 1-day range still triggers the check.

        The recursion stops naturally because a 1-day range cannot be
        split further — the function returns all 3000 movements.
        """
        from schwab_mcp.transactions import _should_split

        movements = [object() for _ in range(3000)]
        # Still True: the trigger fires; the recursion stop is handled
        # by the bisect function, not the trigger itself.
        assert _should_split(movements, range_days=1) is True


# =============================================================================
# Date-range splitting: _split_date_range
# =============================================================================


class TestSplitDateRange:
    """_split_date_range(start_date: str, end_date: str) -> tuple

    Splits an inclusive date range into two roughly equal halves.
    Returns four strings: ``(left_start, left_end, right_start, right_end)``.
    """

    def test_even_range_splits_in_half(self) -> None:
        """A 10-day range splits into two 5-day halves."""
        from schwab_mcp.transactions import _split_date_range

        left_start, left_end, right_start, right_end = _split_date_range(
            "2026-01-01", "2026-01-10"
        )

        assert left_start == "2026-01-01"
        assert left_end == "2026-01-05"
        assert right_start == "2026-01-06"
        assert right_end == "2026-01-10"

    def test_odd_range_leaves_tail_day(self) -> None:
        """An 11-day range splits into 5 + 6 days (right half gets the extra day)."""
        from schwab_mcp.transactions import _split_date_range

        left_start, left_end, right_start, right_end = _split_date_range(
            "2026-01-01", "2026-01-11"
        )

        # 11 days inclusive: mid at day 5 → left 1-5, right 6-11
        assert left_start == "2026-01-01"
        assert left_end == "2026-01-05"
        assert right_start == "2026-01-06"
        assert right_end == "2026-01-11"

    def test_single_day_cannot_split(self) -> None:
        """A 1-day range cannot be split — returns the same range for both halves
        or raises to signal recursion should stop."""
        from schwab_mcp.transactions import _split_date_range

        result = _split_date_range("2026-06-15", "2026-06-15")
        # Either the left and right halves are identical (single day),
        # or the function returns None/raises to signal stop.
        assert result is None or result == (
            "2026-06-15", "2026-06-15",
            "2026-06-15", "2026-06-15",
        )

    def test_two_day_range_splits_one_each(self) -> None:
        """A 2-day range splits into two 1-day ranges."""
        from schwab_mcp.transactions import _split_date_range

        left_start, left_end, right_start, right_end = _split_date_range(
            "2026-03-01", "2026-03-02"
        )

        assert left_start == "2026-03-01"
        assert left_end == "2026-03-01"
        assert right_start == "2026-03-02"
        assert right_end == "2026-03-02"

    def test_range_adjacent_months(self) -> None:
        """Split across a month boundary works correctly."""
        from schwab_mcp.transactions import _split_date_range

        # Jan 15 to Feb 14 = 31 days → mid at ~15 days
        left_start, left_end, right_start, right_end = _split_date_range(
            "2026-01-15", "2026-02-14"
        )

        # Verify the halves are contiguous and cover the full range
        left_cover = date.fromisoformat(left_end) - date.fromisoformat(left_start)
        right_cover = date.fromisoformat(right_end) - date.fromisoformat(right_start)
        total_days = (date.fromisoformat("2026-02-14") - date.fromisoformat("2026-01-15")).days + 1
        half_days = left_cover.days + 1 + right_cover.days + 1
        assert half_days == total_days
        assert right_start == (date.fromisoformat(left_end) + timedelta(days=1)).isoformat()

    def test_full_year_range_split(self) -> None:
        """A full 366-day range splits into two halves, each ≤ 366 days."""
        from schwab_mcp.transactions import _split_date_range

        left_start, left_end, right_start, right_end = _split_date_range(
            "2026-01-01", "2026-12-31"
        )

        left_days = (date.fromisoformat(left_end) - date.fromisoformat(left_start)).days + 1
        right_days = (date.fromisoformat(right_end) - date.fromisoformat(right_start)).days + 1
        total = (date.fromisoformat("2026-12-31") - date.fromisoformat("2026-01-01")).days + 1

        assert left_days + right_days == total
        assert right_start == (date.fromisoformat(left_end) + timedelta(days=1)).isoformat()


# =============================================================================
# Deduplication: _dedup_movements
# =============================================================================


class TestDedupMovements:
    """_dedup_movements(movements: list[MovementEntry]) -> list[MovementEntry]

    Removes duplicate movements by ``(account_hash, activityId)`` where
    ``activityId`` comes from each movement's ``extended`` dict. The first
    occurrence is kept; subsequent duplicates are discarded.
    """

    def test_dedup_removes_exact_duplicate(self) -> None:
        """Two movements with same (account_hash, activityId) → one kept."""
        from schwab_mcp.transactions import MovementEntry, _dedup_movements

        entry_a = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Bought SPY",
            amount=5802.50,
            extended={"activityId": "act_001"},
        )
        entry_b = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Bought SPY (duplicate)",
            amount=5802.50,
            extended={"activityId": "act_001"},
        )

        result = _dedup_movements([entry_a, entry_b])
        assert len(result) == 1
        assert result[0] is entry_a  # First occurrence kept

    def test_dedup_preserves_unique_entries(self) -> None:
        """Two movements with different activityId are both kept."""
        from schwab_mcp.transactions import MovementEntry, _dedup_movements

        entry_1 = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Bought SPY",
            amount=5802.50,
            extended={"activityId": "act_001"},
        )
        entry_2 = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:05:00+00:00",
            category="trade",
            description="Sold AAPL",
            amount=-3500.00,
            extended={"activityId": "act_002"},
        )

        result = _dedup_movements([entry_1, entry_2])
        assert len(result) == 2

    def test_dedup_same_activity_different_accounts(self) -> None:
        """Same activityId on different accounts are NOT duplicates."""
        from schwab_mcp.transactions import MovementEntry, _dedup_movements

        acc_a = MovementEntry(
            account_hash="accA",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Bought SPY",
            amount=5802.50,
            extended={"activityId": "act_001"},
        )
        acc_b = MovementEntry(
            account_hash="accB",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Bought SPY",
            amount=5802.50,
            extended={"activityId": "act_001"},
        )

        result = _dedup_movements([acc_a, acc_b])
        assert len(result) == 2

    def test_dedup_keeps_first_occurrence(self) -> None:
        """When duplicates exist, the FIRST occurrence is kept."""
        from schwab_mcp.transactions import MovementEntry, _dedup_movements

        original = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T10:00:00+00:00",
            category="transfer",
            description="Original entry",
            amount=1000.00,
            extended={"activityId": "act_001"},
        )
        duplicate = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T12:00:00+00:00",
            category="transfer",
            description="Duplicate entry",
            amount=2000.00,
            extended={"activityId": "act_001"},
        )

        result = _dedup_movements([original, duplicate])
        assert len(result) == 1
        assert result[0].description == "Original entry"

    def test_dedup_preserves_order(self) -> None:
        """Deduplication preserves the relative order of unique entries."""
        from schwab_mcp.transactions import MovementEntry, _dedup_movements

        entries = [
            MovementEntry(
                account_hash="acc123",
                occurred_at="2026-10-20T10:00:00+00:00",
                category="trade",
                description="First",
                amount=100.0,
                extended={"activityId": f"act_{i}"},
            )
            for i in range(5)
        ]
        # Add a duplicate of index 2
        entries.append(
            MovementEntry(
                account_hash="acc123",
                occurred_at="2026-10-20T12:00:00+00:00",
                category="trade",
                description="Duplicate of third",
                amount=999.0,
                extended={"activityId": "act_2"},
            )
        )

        result = _dedup_movements(entries)
        assert len(result) == 5
        descriptions = [e.description for e in result]
        assert descriptions == ["First", "First", "First", "First", "First"]

    def test_dedup_empty_list(self) -> None:
        """Empty list deduplicates to empty list."""
        from schwab_mcp.transactions import _dedup_movements

        assert _dedup_movements([]) == []

    def test_dedup_all_unique(self) -> None:
        """A list with all unique entries is returned unchanged (same count)."""
        from schwab_mcp.transactions import MovementEntry, _dedup_movements

        entries = [
            MovementEntry(
                account_hash="acc123",
                occurred_at=f"2026-10-{d:02d}T10:00:00+00:00",
                category="trade",
                description=f"Entry {d}",
                amount=100.0 * d,
                extended={"activityId": f"act_{d}"},
            )
            for d in range(1, 6)
        ]

        result = _dedup_movements(entries)
        assert len(result) == 5

    def test_dedup_entry_without_extended_gets_identity_by_hash_occurred(self) -> None:
        """A movement without ``extended`` (no activityId) is identified
        by its ``(account_hash, occurred_at)`` as fallback."""
        from schwab_mcp.transactions import MovementEntry, _dedup_movements

        entry = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="No extended data",
            amount=100.0,
        )
        duplicate_no_ext = MovementEntry(
            account_hash="acc123",
            occurred_at="2026-10-20T14:03:11+00:00",
            category="trade",
            description="Duplicate no extended",
            amount=100.0,
        )

        result = _dedup_movements([entry, duplicate_no_ext])
        assert len(result) == 1
        assert result[0].description == "No extended data"


# =============================================================================
# Recursive bisection: _bisect_range
# =============================================================================


class TestBisectRange:
    """_bisect_range(query_fn, account_hash, start_date, end_date, types_str)

    Recursively queries a date range, splitting in half whenever the
    query returns >= 3000 movements, until the sub-range reaches 1 day
    (the minimum). Merged results are deduplicated by
    ``(account_hash, activityId)``.
    """

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_movement(
        account_hash: str,
        activity_id: str,
        day: int,
        description: str = "",
    ) -> object:
        """Build a single MovementEntry for test fixtures."""
        from schwab_mcp.transactions import MovementEntry

        return MovementEntry(
            account_hash=account_hash,
            occurred_at=f"2026-10-{day:02d}T12:00:00+00:00",
            category="trade",
            description=description or f"Movement day {day}",
            amount=100.0,
            extended={"activityId": activity_id},
        )

    @staticmethod
    def _make_query_fn(
        results_map: dict[tuple[str, str], list[object]],
    ) -> object:
        """Build a query callable that returns pre-defined results per
        ``(start_date, end_date)`` key.

        The callable signature matches what ``_bisect_range`` expects:
        ``(account_hash, start_date, end_date, types_str) ->
        list[MovementEntry]``.
        """
        def _query(
            account_hash: str,
            start_date: str,
            end_date: str,
            types_str: str,
        ) -> list[object]:
            key = (start_date, end_date)
            if key not in results_map:
                return []
            return results_map[key]

        return _query

    def _range_days(self, start: str, end: str) -> int:
        """Compute inclusive range days between two ISO date strings."""
        return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1

    # ------------------------------------------------------------------
    # tests
    # ------------------------------------------------------------------

    def test_range_below_cap_returns_directly(self) -> None:
        """When query returns < 3000, _bisect_range returns movements directly."""
        from schwab_mcp.transactions import MovementEntry, _bisect_range

        movements = [self._make_movement("acc123", "act_001", 15)]
        query_fn = self._make_query_fn({("2026-10-01", "2026-10-30"): movements})

        result = _bisect_range(
            query_fn, "acc123", "2026-10-01", "2026-10-30",
            "TRADE,TRANSFER",
        )

        assert len(result) == 1
        assert result[0].extended["activityId"] == "act_001"

    def test_empty_range_returns_empty(self) -> None:
        """An empty result is returned as-is (no split attempt)."""
        from schwab_mcp.transactions import _bisect_range

        query_fn = self._make_query_fn({("2026-10-01", "2026-10-30"): []})

        result = _bisect_range(
            query_fn, "acc123", "2026-10-01", "2026-10-30",
            "TRADE,TRANSFER",
        )

        assert result == []

    def test_3000_movements_triggers_bisection(self) -> None:
        """Exactly 3000 movements triggers range split and re-query of both halves."""
        from schwab_mcp.transactions import MovementEntry, _bisect_range

        # The full range returns 3000 movements
        left_movements = [self._make_movement("acc123", f"act_{i}", 1) for i in range(1500)]
        right_movements = [self._make_movement("acc123", f"act_{1500 + i}", 16) for i in range(1500)]

        query_fn = self._make_query_fn({
            ("2026-10-01", "2026-10-30"): [object()] * 3000,  # Full range: 3000 triggers
            ("2026-10-01", "2026-10-15"): left_movements,       # Left half: < 3000
            ("2026-10-16", "2026-10-30"): right_movements,      # Right half: < 3000
        })

        result = _bisect_range(
            query_fn, "acc123", "2026-10-01", "2026-10-30",
            "TRADE,TRANSFER",
        )

        # Both halves should be queried and merged
        assert len(result) == 3000

    def test_recursive_bisection_multi_level(self) -> None:
        """When a half also returns 3000, the split recurses further."""
        from schwab_mcp.transactions import MovementEntry, _bisect_range

        # Left half also has 3000, so it splits again
        left_left = [self._make_movement("acc123", f"ll_{i}", 1) for i in range(1500)]
        left_right = [self._make_movement("acc123", f"lr_{i}", 9) for i in range(1500)]
        right_half = [self._make_movement("acc123", f"r_{i}", 16) for i in range(500)]

        query_fn = self._make_query_fn({
            ("2026-10-01", "2026-10-30"): [object()] * 3000,   # Triggers split
            ("2026-10-01", "2026-10-15"): [object()] * 3000,   # Left half: triggers again
            ("2026-10-01", "2026-10-07"): left_left,            # L-L: < 3000
            ("2026-10-08", "2026-10-15"): left_right,           # L-R: < 3000
            ("2026-10-16", "2026-10-30"): right_half,           # R: < 3000
        })

        result = _bisect_range(
            query_fn, "acc123", "2026-10-01", "2026-10-30",
            "TRADE,TRANSFER",
        )

        assert len(result) == 3500

    def test_single_day_range_at_cap_does_not_loop(self) -> None:
        """A 1-day range returning 3000 does NOT recurse (minimum sub-range).

        The function returns all 3000 movements without further splitting.
        """
        from schwab_mcp.transactions import MovementEntry, _bisect_range

        # The query returns 3000 on a 1-day range
        movements = [self._make_movement("acc123", f"act_{i}", 15) for i in range(3000)]

        def query_fn(account_hash, start_date, end_date, types_str):
            return movements

        result = _bisect_range(
            query_fn, "acc123", "2026-10-15", "2026-10-15",
            "TRADE,TRANSFER",
        )

        # Should return all 3000 without splitting (can't split 1 day)
        assert len(result) == 3000

    def test_only_one_account_splits(self) -> None:
        """Bisection only affects the account that hit 3000; other accounts
        are unaffected (ensured by orchestration, but the bisect function
        must preserve account_hash through the split)."""
        from schwab_mcp.transactions import MovementEntry, _bisect_range

        left = [self._make_movement("accA", f"a_{i}", 1) for i in range(2000)]
        right = [self._make_movement("accA", f"a_{2000 + i}", 16) for i in range(2000)]

        query_fn = self._make_query_fn({
            ("2026-10-01", "2026-10-30"): [object()] * 3000,
            ("2026-10-01", "2026-10-15"): left,
            ("2026-10-16", "2026-10-30"): right,
        })

        result = _bisect_range(
            query_fn, "accA", "2026-10-01", "2026-10-30",
            "TRADE,TRANSFER",
        )

        assert len(result) == 4000
        assert all(m.account_hash == "accA" for m in result)

    def test_bisection_preserves_all_types_str(self) -> None:
        """The ``types_str`` parameter is passed unchanged to every recursive query."""
        from schwab_mcp.transactions import _bisect_range

        types_seen = []

        def query_fn(account_hash, start_date, end_date, types_str):
            types_seen.append(types_str)
            return []

        _bisect_range(query_fn, "acc123", "2026-10-01", "2026-10-30", "ALL_TYPES")

        # All queries should receive the same types_str
        assert all(t == "ALL_TYPES" for t in types_seen)


# =============================================================================
# Fusion integrity — SC-004: no duplicates, no omissions
# =============================================================================


class TestFusionIntegrity:
    """SC-004: After bisection, the merged result must have no duplicates
    and no omissions.

    Tests verify that:
    - Merged result count = sum of parts minus legitimate duplicates
    - No transaction is counted twice
    - No transaction is lost
    - Deduplication by (account_hash, activityId) is applied during merge
    """

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_movement(
        account_hash: str,
        activity_id: str,
        day: int,
    ) -> object:
        """Build a single MovementEntry for fixtures."""
        from schwab_mcp.transactions import MovementEntry

        return MovementEntry(
            account_hash=account_hash,
            occurred_at=f"2026-10-{day:02d}T12:00:00+00:00",
            category="trade",
            description=f"Movement {activity_id}",
            amount=100.0,
            extended={"activityId": activity_id},
        )

    # ------------------------------------------------------------------
    # tests
    # ------------------------------------------------------------------

    def test_merge_no_overlap(self) -> None:
        """When halves have no overlapping transactions, merged count = sum."""
        from schwab_mcp.transactions import MovementEntry, _bisect_range

        left = [self._make_movement("acc123", f"act_{i}", 1) for i in range(1500)]
        right = [self._make_movement("acc123", f"act_{1500 + i}", 16) for i in range(1500)]

        query_fn = lambda acc, s, e, t: {
            ("2026-10-01", "2026-10-30"): [object()] * 3000,
            ("2026-10-01", "2026-10-15"): left,
            ("2026-10-16", "2026-10-30"): right,
        }.get((s, e), [])

        result = _bisect_range(
            query_fn, "acc123", "2026-10-01", "2026-10-30",
            "TRADE,TRANSFER",
        )

        # No overlap: sum of parts = 3000
        assert len(result) == 3000

    def test_merge_with_overlap_dedup(self) -> None:
        """When halves share some transactions, merged count = sum - duplicates."""
        from schwab_mcp.transactions import MovementEntry, _bisect_range

        # The boundary transaction appears in both halves (overlap)
        left = [self._make_movement("acc123", f"act_{i}", 1) for i in range(1500)]
        # One duplicate at the boundary
        boundary = self._make_movement("acc123", "act_500", 8)
        right = [boundary] + [self._make_movement("acc123", f"act_{1500 + i}", 16) for i in range(1499)]

        # Right has 1500 entries (1 duplicate + 1499 unique)
        query_fn = lambda acc, s, e, t: {
            ("2026-10-01", "2026-10-30"): [object()] * 3000,
            ("2026-10-01", "2026-10-15"): left,
            ("2026-10-16", "2026-10-30"): right,
        }.get((s, e), [])

        result = _bisect_range(
            query_fn, "acc123", "2026-10-01", "2026-10-30",
            "TRADE,TRANSFER",
        )

        # left(1500) + right(1500) - 1 duplicate = 2999
        assert len(result) == 2999

    def test_all_activity_ids_are_unique_after_merge(self) -> None:
        """After bisection, no two entries share the same
        (account_hash, activityId)."""
        from schwab_mcp.transactions import MovementEntry, _bisect_range

        # Create a scenario with overlapping activityIds
        left = [self._make_movement("acc123", f"act_{i}", 1) for i in range(1500)]
        # Right half has some overlapping activityIds
        right = [self._make_movement("acc123", f"act_{i}", 16) for i in range(500, 2000)]

        query_fn = lambda acc, s, e, t: {
            ("2026-10-01", "2026-10-30"): [object()] * 3000,
            ("2026-10-01", "2026-10-15"): left,
            ("2026-10-16", "2026-10-30"): right,
        }.get((s, e), [])

        result = _bisect_range(
            query_fn, "acc123", "2026-10-01", "2026-10-30",
            "TRADE,TRANSFER",
        )

        seen: set[tuple[str, str]] = set()
        for m in result:
            aid = m.extended["activityId"] if m.extended else None
            key = (m.account_hash, aid)
            assert key not in seen, f"Duplicate (account_hash, activityId): {key}"
            seen.add(key)

    def test_no_omissions_across_three_levels(self) -> None:
        """After multi-level bisection, every movement from the original
        range is present exactly once."""
        from schwab_mcp.transactions import MovementEntry, _bisect_range

        # Build a 3-level scenario:
        # Full range (30 days) → 3000, splits
        # Left (15 days) → 3000, splits
        # L-L (8 days) → < 3000, L-R (7 days) → < 3000
        # Right (15 days) → < 3000
        movements = {}
        movements[("2026-10-01", "2026-10-30")] = [object()] * 3000
        movements[("2026-10-01", "2026-10-15")] = [object()] * 3000

        lll = [self._make_movement("acc123", f"lll_{i}", 1) for i in range(1000)]
        ll_count = len(lll)
        lr = [self._make_movement("acc123", f"lr_{i}", 9) for i in range(2000)]
        lr_count = len(lr)
        r = [self._make_movement("acc123", f"r_{i}", 16) for i in range(500)]
        r_count = len(r)

        movements[("2026-10-01", "2026-10-07")] = lll
        movements[("2026-10-08", "2026-10-15")] = lr
        movements[("2026-10-16", "2026-10-30")] = r

        query_fn = lambda acc, s, e, t: movements.get((s, e), [])

        result = _bisect_range(
            query_fn, "acc123", "2026-10-01", "2026-10-30",
            "TRADE,TRANSFER",
        )

        expected_count = ll_count + lr_count + r_count
        assert len(result) == expected_count, (
            f"Expected {expected_count}, got {len(result)}"
        )

    def test_dedup_key_respects_account_hash(self) -> None:
        """Same activityId on different account hashes are NOT deduped."""
        from schwab_mcp.transactions import MovementEntry, _dedup_movements

        entry_a = MovementEntry(
            account_hash="accA",
            occurred_at="2026-10-20T10:00:00+00:00",
            category="trade",
            description="Account A",
            amount=100.0,
            extended={"activityId": "act_001"},
        )
        entry_b = MovementEntry(
            account_hash="accB",
            occurred_at="2026-10-20T10:00:00+00:00",
            category="trade",
            description="Account B",
            amount=200.0,
            extended={"activityId": "act_001"},
        )

        result = _dedup_movements([entry_a, entry_b])
        assert len(result) == 2, (
            "Same activityId on different accounts must NOT be deduped"
        )