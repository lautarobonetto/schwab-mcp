"""Performance and token-budget tests for ``get_price_history`` (Principle V).

Covers the tasks' budget groups: T012 (default-window budgets) and T022
(worst-case scaling).  Budgets are MEASURED against the recorded fixture
payloads, per the constitution's rule that budget growth needs an
explicit recorded justification:

- **Tokens**: <= 650 for the default 22-candle window (measured 588);
  <= 6.500 for the 260-candle worst case (measured ~6.3k); <= 25 tokens
  per curated candle (measured 23.4-24.2).
- **Latency**: <= 5 s p95 per invocation (one provider call, SC-001).

Recorded deviation from ``research.md`` D5: the plan's arithmetic
(~75 chars = 19-22 tokens per candle, 550 / 5.200 totals) omitted the
``in_progress`` field that every curated candle carries (pinned by the
mapping tests and quickstart S1), which costs ~19 chars (~5 tokens) per
candle.  A curated candle measures 96 compact-JSON chars (~24 tokens).
The 260-candle ceiling is unchanged: it is structural (FR-004, SC-003 —
ceiling by construction), so the token budget is restated rather than
the ceiling lowered.

Token measurement (pattern of ``test_quotes_budgets.py``):
``len(json.dumps(x, separators=(",", ":"))) / 4``.
"""

from __future__ import annotations

import json
import time

import pytest

from tests.unit.fixtures import price_history_payloads as fx
from tests.unit.helpers import FakePriceHistoryClient

LATENCY_BUDGET_S = 5.0  # <= 5 s p95 per invocation (SC-001)

DEFAULT_TOKEN_BUDGET = 650  # 22 daily candles, measured 588 (SC-002)
WORST_CASE_TOKEN_BUDGET = 6_500  # 260 candles, measured ~6.3k (SC-002/SC-003)
PER_CANDLE_TOKEN_BUDGET = 25  # measured 23.4-24.2 (research D5 baseline)

MAX_CANDLES = 260  # global ceiling by construction (FR-004)


def _tokens(value) -> float:
    """Approximate token size of *value* as compact-serialized chars / 4."""
    return len(json.dumps(value, separators=(",", ":"))) / 4


def _per_candle_tokens(result: dict) -> float:
    """Marginal token cost of one curated candle (candles array only)."""
    return _tokens(result["candles"]) / result["candle_count"]


def _synthetic_minute_payload(count: int, step_minutes: int) -> dict:
    """Deterministic worst-case intraday payload (no clock reads)."""
    from datetime import datetime

    base = int(datetime(2026, 10, 5, 4, 0, tzinfo=fx.ET).timestamp() * 1000)
    candles = []
    for i in range(count):
        price = 100.0 + 0.01 * i
        candles.append(
            {
                "open": price,
                "high": price + 0.5,
                "low": price - 0.5,
                "close": price + 0.25,
                "volume": 10_000 + i,
                "datetime": base + i * step_minutes * fx.MS_PER_MINUTE,
            }
        )
    return {"candles": candles, "symbol": fx.SYMBOL, "empty": False}


# =============================================================================
# T012 — default-window token budget (SC-002)
# =============================================================================


class TestDefaultWindowTokenBudget:
    """The default daily 1-month window stays inside the declared budget."""

    @pytest.mark.performance
    def test_default_response_within_budget(self) -> None:
        """22 daily candles (the default window) <= 650 tokens."""
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD)
        result = get_price_history(client, fx.SYMBOL)

        assert result["outcome"] == "ok"
        # Anti-gaming: the full curated window must be present.
        assert result["candle_count"] == 22, "default window is ~22 sessions"
        assert len(result["candles"]) == 22
        for candle in result["candles"]:
            assert set(candle) == {"t", "o", "h", "l", "c", "v", "in_progress"}
        tokens = _tokens(result)
        assert tokens <= DEFAULT_TOKEN_BUDGET, (
            f"default-window response is {tokens:.0f} tokens, "
            f"budget is {DEFAULT_TOKEN_BUDGET}"
        )

    @pytest.mark.performance
    def test_per_candle_cost_within_baseline(self) -> None:
        """Per-curated-candle cost <= 25 tokens (research D5 restated)."""
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD)
        result = get_price_history(client, fx.SYMBOL)

        per_candle = _per_candle_tokens(result)
        assert per_candle <= PER_CANDLE_TOKEN_BUDGET, (
            f"each curated candle costs {per_candle:.1f} tokens, "
            f"budget is {PER_CANDLE_TOKEN_BUDGET}"
        )


# =============================================================================
# T022 — worst-case scaling (SC-002/SC-003)
# =============================================================================


class TestWorstCaseTokenBudget:
    """The 260-candle worst case stays inside the declared budget and the
    per-candle baseline holds at scale (no hidden bulk)."""

    @pytest.mark.performance
    @pytest.mark.parametrize(
        ("frequency", "period", "payload_factory"),
        [
            pytest.param(
                "15m", "10d", lambda: _synthetic_minute_payload(260, 15),
                id="15m-10d-260",
            ),
            pytest.param(
                "weekly", "5y", lambda: fx.build_weekly_payload(weeks=260),
                id="weekly-5y-260",
            ),
            pytest.param(
                "daily", "1y", lambda: fx.build_daily_payload(sessions=252),
                id="daily-1y-252",
            ),
        ],
    )
    def test_worst_case_within_budget(
        self, frequency, period, payload_factory
    ) -> None:
        from schwab_mcp.price_history import get_price_history

        payload = payload_factory()
        client = FakePriceHistoryClient(payload=payload)
        result = get_price_history(
            client,
            payload["symbol"],
            frequency,
            period,
            extended_hours=frequency in ("5m", "15m", "30m", "1h"),
        )

        assert result["outcome"] == "ok"
        assert result["candle_count"] <= MAX_CANDLES, "SC-003 ceiling"
        tokens = _tokens(result)
        assert tokens <= WORST_CASE_TOKEN_BUDGET, (
            f"{frequency}/{period} worst case is {tokens:.0f} tokens, "
            f"budget is {WORST_CASE_TOKEN_BUDGET}"
        )
        per_candle = _per_candle_tokens(result)
        assert per_candle <= PER_CANDLE_TOKEN_BUDGET, (
            f"{frequency}/{period} costs {per_candle:.1f} tokens per candle, "
            f"budget is {PER_CANDLE_TOKEN_BUDGET}"
        )

    @pytest.mark.performance
    def test_size_grows_linearly_no_hidden_bulk(self) -> None:
        """The marginal cost of one more candle stays inside the per-candle
        budget — linear growth, no hidden bulk (SC-005 path)."""
        from schwab_mcp.price_history import get_price_history

        small = _synthetic_minute_payload(130, 15)
        large = _synthetic_minute_payload(260, 15)

        result_small = get_price_history(
            FakePriceHistoryClient(payload=small), fx.SYMBOL, "15m", "10d",
            extended_hours=True,
        )
        result_large = get_price_history(
            FakePriceHistoryClient(payload=large), fx.SYMBOL, "15m", "10d",
            extended_hours=True,
        )

        assert result_small["candle_count"] == 130
        assert result_large["candle_count"] == 260
        marginal = (
            _tokens(result_large["candles"]) - _tokens(result_small["candles"])
        ) / 130
        assert marginal <= PER_CANDLE_TOKEN_BUDGET, (
            f"marginal cost per candle is {marginal:.1f} tokens, "
            f"budget is {PER_CANDLE_TOKEN_BUDGET}"
        )


# =============================================================================
# T012 — latency budget (SC-001)
# =============================================================================


class TestLatencyBudget:
    """Latency budget: <= 5 s p95 per invocation with one provider call."""

    @pytest.mark.performance
    def test_single_invocation_under_budget(self) -> None:
        from schwab_mcp.price_history import get_price_history

        client = FakePriceHistoryClient(payload=fx.DAILY_PAYLOAD, delay=0.1)
        start = time.monotonic()
        result = get_price_history(client, fx.SYMBOL)
        elapsed = time.monotonic() - start

        assert result["outcome"] == "ok"
        assert client.call_count == 1, "exactly one provider call (research D1)"
        assert elapsed <= LATENCY_BUDGET_S, (
            f"invocation took {elapsed:.2f} s, budget is {LATENCY_BUDGET_S} s (p95)"
        )

    @pytest.mark.performance
    def test_worst_case_and_extended_mode_under_budget(self) -> None:
        """The 260-candle path plus the raw passthrough stays within 5 s."""
        from schwab_mcp.price_history import get_price_history

        payload = _synthetic_minute_payload(260, 15)
        client = FakePriceHistoryClient(payload=payload, delay=0.1)
        start = time.monotonic()
        result = get_price_history(
            client, fx.SYMBOL, "15m", "10d", extended_hours=True, extended=True
        )
        elapsed = time.monotonic() - start

        assert result["outcome"] == "ok"
        assert result["provider"] == payload
        assert elapsed <= LATENCY_BUDGET_S
