"""Failing unit tests for HistoryQuery validation (FR-004).

These are TDD red-phase tests: the ``validate_history_query`` function does
not exist yet in ``schwab_mcp.transactions``, so every test will fail with
``ImportError`` / ``ModuleNotFoundError``. Once implemented (T005), all tests
should pass.

Covers (from tasks.md T004)
---------------------------
- Missing or malformed dates (not parseable as ``YYYY-MM-DD``)
- ``end_date < start_date`` — error names BOTH dates
- Range > 366 days — error indicates max 1 year and suggests splitting
- ``end_date`` in the future — error indicates cannot be future
- Empty ``symbol`` — error for empty string when provided
- ``offset < 0`` — error indicating minimum value 0
- Valid inputs pass validation (happy path)

Design constraints (FR-004 / data-model.md)
-------------------------------------------
- Validation runs **before** any upcall — pure function, no I/O
- Date range is inclusive both ends, interpreted in America/New_York
- Maximum window is 1 year (366 calendar days)
- Errors are meaningful, actionable (standard MCP tool errors)

References
----------
- specs/006-transaction-history/spec.md (FR-004, Edge Cases)
- specs/006-transaction-history/data-model.md (§HistoryQuery)
- specs/006-transaction-history/research.md (R4)
"""

from __future__ import annotations

import pytest


# =============================================================================
# Malformed dates
# =============================================================================


class TestMalformedDates:
    """FR-004: ``start_date`` / ``end_date`` that cannot be parsed as
    ``YYYY-MM-DD`` must be rejected with a clear error message describing
    the expected format.

    The validation function must not silently coerce or interpret alternative
    date formats.
    """

    def test_start_date_not_a_string(self) -> None:
        """A non-string ``start_date`` raises a validation error."""
        from schwab_mcp.transactions import validate_history_query

        with pytest.raises((ValueError, TypeError)):
            validate_history_query(start_date=12345, end_date="2026-10-20")

    def test_end_date_not_a_string(self) -> None:
        """A non-string ``end_date`` raises a validation error."""
        from schwab_mcp.transactions import validate_history_query

        with pytest.raises((ValueError, TypeError)):
            validate_history_query(start_date="2026-10-01", end_date=None)

    def test_start_date_completely_invalid_format(self) -> None:
        """A completely unparseable ``start_date`` is rejected."""
        from schwab_mcp.transactions import validate_history_query

        with pytest.raises((ValueError, TypeError)) as exc:
            validate_history_query(start_date="not-a-date", end_date="2026-10-20")
        msg = str(exc.value)
        assert "YYYY-MM-DD" in msg or "format" in msg.lower()

    def test_end_date_completely_invalid_format(self) -> None:
        """A completely unparseable ``end_date`` is rejected."""
        from schwab_mcp.transactions import validate_history_query

        with pytest.raises((ValueError, TypeError)) as exc:
            validate_history_query(start_date="2026-10-01", end_date="bogus")
        msg = str(exc.value)
        assert "YYYY-MM-DD" in msg or "format" in msg.lower()

    def test_start_date_wrong_separator(self) -> None:
        """Date with '/' instead of '-' is rejected (strict ``YYYY-MM-DD``)."""
        from schwab_mcp.transactions import validate_history_query

        with pytest.raises((ValueError, TypeError)) as exc:
            validate_history_query(start_date="2026/10/01", end_date="2026-10-20")
        msg = str(exc.value)
        assert "YYYY-MM-DD" in msg or "format" in msg.lower()

    def test_start_date_month_out_of_range(self) -> None:
        """Month > 12 is rejected (not a real calendar date)."""
        from schwab_mcp.transactions import validate_history_query

        with pytest.raises((ValueError, TypeError)):
            validate_history_query(start_date="2026-13-01", end_date="2026-10-20")

    def test_start_date_day_out_of_range(self) -> None:
        """Day > 31 is rejected (not a real calendar date)."""
        from schwab_mcp.transactions import validate_history_query

        with pytest.raises((ValueError, TypeError)):
            validate_history_query(start_date="2026-10-32", end_date="2026-10-20")

    def test_start_date_empty_string(self) -> None:
        """An empty string ``start_date`` is rejected."""
        from schwab_mcp.transactions import validate_history_query

        with pytest.raises((ValueError, TypeError)):
            validate_history_query(start_date="", end_date="2026-10-20")

    def test_end_date_empty_string(self) -> None:
        """An empty string ``end_date`` is rejected."""
        from schwab_mcp.transactions import validate_history_query

        with pytest.raises((ValueError, TypeError)):
            validate_history_query(start_date="2026-10-01", end_date="")

    def test_start_date_whitespace_only(self) -> None:
        """A whitespace-only ``start_date`` is rejected."""
        from schwab_mcp.transactions import validate_history_query

        with pytest.raises((ValueError, TypeError)):
            validate_history_query(start_date="   ", end_date="2026-10-20")


# =============================================================================
# Date ordering: end_date < start_date
# =============================================================================


class TestEndDateBeforeStartDate:
    """FR-004: ``end_date < start_date`` must produce an error that names
    BOTH dates so the agent can see what was wrong and how to fix it.

    The error must be raised before any provider call (pure validation).
    """

    def test_end_date_before_start_date_same_month(self) -> None:
        """``end_date`` earlier in the same month is rejected."""
        from schwab_mcp.transactions import validate_history_query

        with pytest.raises((ValueError, TypeError)) as exc:
            validate_history_query(start_date="2026-10-20", end_date="2026-10-01")
        msg = str(exc.value)
        assert "2026-10-20" in msg, (
            f"Error must name the start_date, got: {msg}"
        )
        assert "2026-10-01" in msg, (
            f"Error must name the end_date, got: {msg}"
        )

    def test_end_date_before_start_date_different_years(self) -> None:
        """``end_date`` in a previous year than ``start_date`` is rejected."""
        from schwab_mcp.transactions import validate_history_query

        with pytest.raises((ValueError, TypeError)) as exc:
            validate_history_query(start_date="2026-01-01", end_date="2025-12-31")
        msg = str(exc.value)
        assert "2026-01-01" in msg
        assert "2025-12-31" in msg

    def test_end_date_equals_start_date_is_valid(self) -> None:
        """A single-day range (end_date == start_date) is valid (inclusive bounds)."""
        from schwab_mcp.transactions import validate_history_query

        # Should not raise — no exception means pass
        validate_history_query(start_date="2026-10-20", end_date="2026-10-20")


# =============================================================================
# Range > 366 days (max 1 year)
# =============================================================================


class TestRangeExceedsOneYear:
    """FR-004: A date range exceeding 1 year (366 calendar days, inclusive)
    must be rejected with an error indicating the maximum allowed window
    and suggesting the agent splits the range into consecutive queries.

    The max window is 366 days (fully inclusive: e.g. Jan 1 2026 – Jan 1 2027
    = 366 calendar days). Any range wider than that is rejected.
    """

    def test_range_exactly_366_days_is_valid(self) -> None:
        """A range of exactly 366 days is at the boundary and MUST pass."""
        from schwab_mcp.transactions import validate_history_query

        # 2026-01-01 to 2027-01-01 inclusive = 366 days
        validate_history_query(start_date="2026-01-01", end_date="2027-01-01")

    def test_range_367_days_rejected(self) -> None:
        """A range of 367 days (one day over) is rejected."""
        from schwab_mcp.transactions import validate_history_query

        with pytest.raises((ValueError, TypeError)) as exc:
            validate_history_query(start_date="2026-01-01", end_date="2027-01-02")
        msg = str(exc.value)
        assert "366" in msg or "1 year" in msg.lower() or "año" in msg.lower(), (
            f"Error must mention the max window (366 days / 1 year), got: {msg}"
        )
        assert "split" in msg.lower() or "divide" in msg.lower(), (
            f"Error must suggest splitting the range, got: {msg}"
        )

    def test_range_full_year_across_leap(self) -> None:
        """A 366-day range spanning a leap year boundary is valid."""
        from schwab_mcp.transactions import validate_history_query

        # 2024-01-01 to 2024-12-31 inclusive in a leap year = 366 days
        validate_history_query(start_date="2024-01-01", end_date="2024-12-31")

    def test_range_two_full_years_rejected(self) -> None:
        """A range spanning 2+ full years is clearly rejected."""
        from schwab_mcp.transactions import validate_history_query

        with pytest.raises((ValueError, TypeError)):
            validate_history_query(start_date="2025-01-01", end_date="2027-01-01")


# =============================================================================
# end_date in the future
# =============================================================================


class TestEndDateInFuture:
    """FR-004: ``end_date`` in the future (beyond today in America/New_York)
    must be rejected with a clear error that ``end_date`` cannot be in the
    future.

    The validation should determine "today" using America/New_York timezone.
    """

    def test_end_date_tomorrow_rejected(self) -> None:
        """A date of tomorrow is rejected as future."""
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        from schwab_mcp.transactions import validate_history_query

        # Compute "tomorrow" with the same clock the validator uses
        # (America/New_York). Using the machine-local date makes this test
        # timezone-flaky: in the evening, the NY date can already equal
        # local "tomorrow", so the validator accepts it as today.
        today_ny = datetime.now(ZoneInfo("America/New_York")).date()
        tomorrow = (today_ny + timedelta(days=1)).isoformat()
        with pytest.raises((ValueError, TypeError)) as exc:
            validate_history_query(start_date="2026-01-01", end_date=tomorrow)
        msg = str(exc.value)
        assert "future" in msg.lower(), (
            f"Error must indicate end_date cannot be in the future, got: {msg}"
        )

    def test_end_date_far_future_rejected(self) -> None:
        """A date many years in the future is rejected."""
        from schwab_mcp.transactions import validate_history_query

        with pytest.raises((ValueError, TypeError)) as exc:
            validate_history_query(start_date="2026-01-01", end_date="2030-12-31")
        msg = str(exc.value)
        assert "future" in msg.lower(), (
            f"Error must indicate end_date cannot be in the future, got: {msg}"
        )

    def test_end_date_today_is_valid(self) -> None:
        """Today's date as ``end_date`` passes validation."""
        from datetime import date
        from schwab_mcp.transactions import validate_history_query

        today = date.today().isoformat()
        # Use a start_date that keeps the range ≤ 366 days
        validate_history_query(
            start_date=(date.today().replace(year=date.today().year - 1)).isoformat(),
            end_date=today,
        )


# =============================================================================
# Empty symbol
# =============================================================================


class TestEmptySymbol:
    """FR-004: When ``symbol`` is provided as a string, it must be non-empty.
    An empty string or whitespace-only string is rejected.

    A ``None`` symbol (no filter) should pass — the filter is optional.
    """

    def test_none_symbol_is_valid(self) -> None:
        """``symbol=None`` (no filter) passes validation."""
        from schwab_mcp.transactions import validate_history_query

        validate_history_query(
            start_date="2026-10-01", end_date="2026-10-20", symbol=None,
        )

    def test_empty_string_symbol_rejected(self) -> None:
        """An empty string ``symbol=""`` is rejected."""
        from schwab_mcp.transactions import validate_history_query

        with pytest.raises((ValueError, TypeError)) as exc:
            validate_history_query(
                start_date="2026-10-01", end_date="2026-10-20", symbol="",
            )
        msg = str(exc.value)
        assert "symbol" in msg.lower(), (
            f"Error must mention 'symbol', got: {msg}"
        )

    def test_whitespace_symbol_rejected(self) -> None:
        """A whitespace-only ``symbol="   "`` is rejected."""
        from schwab_mcp.transactions import validate_history_query

        with pytest.raises((ValueError, TypeError)):
            validate_history_query(
                start_date="2026-10-01", end_date="2026-10-20", symbol="   ",
            )


# =============================================================================
# offset < 0
# =============================================================================


class TestNegativeOffset:
    """FR-004 / data-model.md: ``offset`` must be >= 0. A negative offset
    is rejected before any upcall.
    """

    def test_offset_negative_one_rejected(self) -> None:
        """``offset=-1`` is rejected."""
        from schwab_mcp.transactions import validate_history_query

        with pytest.raises((ValueError, TypeError)) as exc:
            validate_history_query(
                start_date="2026-10-01", end_date="2026-10-20", offset=-1,
            )
        msg = str(exc.value)
        assert "0" in msg, (
            f"Error must mention minimum value 0 (or similar), got: {msg}"
        )

    def test_offset_large_negative_rejected(self) -> None:
        """A very negative ``offset`` is rejected."""
        from schwab_mcp.transactions import validate_history_query

        with pytest.raises((ValueError, TypeError)):
            validate_history_query(
                start_date="2026-10-01", end_date="2026-10-20", offset=-999,
            )

    def test_offset_zero_is_valid(self) -> None:
        """``offset=0`` (the default) passes validation."""
        from schwab_mcp.transactions import validate_history_query

        validate_history_query(
            start_date="2026-10-01", end_date="2026-10-20", offset=0,
        )

    def test_offset_positive_is_valid(self) -> None:
        """A positive ``offset`` passes validation."""
        from schwab_mcp.transactions import validate_history_query

        validate_history_query(
            start_date="2026-10-01", end_date="2026-10-20", offset=50,
        )


# =============================================================================
# Happy path — valid inputs pass validation
# =============================================================================


class TestValidInputs:
    """A range of valid inputs should all pass validation without raising.

    Covers: typical ranges, edge boundary, full year, symbol present,
    offset present, all optional combinations.
    """

    def test_valid_short_range(self) -> None:
        """A typical 1-day range passes."""
        from schwab_mcp.transactions import validate_history_query

        validate_history_query(start_date="2026-10-20", end_date="2026-10-20")

    def test_valid_week_range(self) -> None:
        """A typical 1-week range passes."""
        from schwab_mcp.transactions import validate_history_query

        validate_history_query(start_date="2026-10-01", end_date="2026-10-08")

    def test_valid_full_year_range(self) -> None:
        """A range of exactly 366 days passes (boundary)."""
        from schwab_mcp.transactions import validate_history_query

        validate_history_query(start_date="2026-01-01", end_date="2027-01-01")

    def test_valid_with_symbol(self) -> None:
        """A valid query with a symbol filter passes."""
        from schwab_mcp.transactions import validate_history_query

        validate_history_query(
            start_date="2026-10-01", end_date="2026-10-20", symbol="AAPL",
        )

    def test_valid_with_offset(self) -> None:
        """A valid query with an offset passes."""
        from schwab_mcp.transactions import validate_history_query

        validate_history_query(
            start_date="2026-10-01", end_date="2026-10-20", offset=100,
        )

    def test_valid_with_symbol_and_offset(self) -> None:
        """A valid query with both symbol and offset passes."""
        from schwab_mcp.transactions import validate_history_query

        validate_history_query(
            start_date="2026-10-01",
            end_date="2026-10-20",
            symbol="SPY",
            offset=50,
        )

    def test_valid_default_offset_omitted(self) -> None:
        """Calling without ``offset`` uses the default (0) and passes."""
        from schwab_mcp.transactions import validate_history_query

        validate_history_query(
            start_date="2026-10-01", end_date="2026-10-20",
        )

    def test_valid_symbol_none(self) -> None:
        """Explicit ``symbol=None`` passes (optional filter)."""
        from schwab_mcp.transactions import validate_history_query

        validate_history_query(
            start_date="2026-10-01",
            end_date="2026-10-20",
            symbol=None,
        )


# =============================================================================
# Validation is pure — no upcalls (FR-004)
# =============================================================================


class TestValidationIsPure:
    """FR-004: Validation MUST run **before** any upcall. The
    ``validate_history_query`` function is a pure function: it performs no
    I/O, makes no network calls, and needs no client/context to run.

    These tests verify that the function can be called without a client or
    any dependency — only string and numeric arguments.
    """

    def test_validation_requires_no_client(self) -> None:
        """``validate_history_query`` can be called without a client argument
        (pure function — no I/O)."""
        from schwab_mcp.transactions import validate_history_query

        # No client needed — just strings and an int
        validate_history_query(start_date="2026-10-01", end_date="2026-10-20")

    def test_validation_returns_none_on_success(self) -> None:
        """On success, ``validate_history_query`` returns ``None``
        (no error → input is valid)."""
        from schwab_mcp.transactions import validate_history_query

        result = validate_history_query(
            start_date="2026-10-01", end_date="2026-10-20",
        )
        assert result is None, (
            f"Expected None on valid input, got {result!r}"
        )

    def test_validation_rejects_before_network_call(self) -> None:
        """Invalid inputs are rejected immediately, before any network/upcall
        would be made — the function is synchronous and has no async or
        network operations."""
        from schwab_mcp.transactions import validate_history_query

        # These should raise synchronously before any I/O
        for start, end in [
            ("invalid", "2026-10-20"),
            ("2026-10-20", "2026-10-01"),  # reversed
            ("2026-01-01", "2027-01-10"),  # > 366 days
        ]:
            with pytest.raises((ValueError, TypeError)):
                validate_history_query(start_date=start, end_date=end)