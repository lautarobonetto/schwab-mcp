"""Performance and token-budget tests for the get_quotes tool (Principle V).

TDD red-phase for the tasks' budget groups: T012 (single-quote budgets)
and T014 (batch scaling).  Budgets (spec SC-001/SC-002, plan.md,
contracts/mcp-tools.md §5):

- **Tokens**: <= 250 tokens for a single curated quote; <= 2.500 tokens
  for a 10-symbol batch (<= ~5.000 worst case at the 20-symbol limit).
- **Latency**: <= 5 s p95 per invocation (two provider calls).
- Response size grows linearly with symbol count — no hidden bulk
  (SC-005).

Token measurement (SC-002, pattern of test_options_chain_budgets.py):
``len(json.dumps(result, separators=(",", ":"))) / 4``.  Budget growth
requires recorded justification per constitution Principle V.
"""

from __future__ import annotations

import json
import time

import pytest

from tests.unit.fixtures.quotes_payloads import EQUITY_QUOTE_ENTRY
from tests.unit.helpers import (
    FakeQuotesClient,
    build_quote_entry,
    build_quotes_payload,
)

LATENCY_BUDGET_S = 5.0  # <= 5 s p95 per invocation (SC-001)
SINGLE_TOKEN_BUDGET = 250  # <= 250 tokens, single curated quote (SC-002)
BATCH_10_TOKEN_BUDGET = 2_500  # <= 2.500 tokens, 10-symbol batch (SC-002)
BATCH_20_TOKEN_BUDGET = 5_000  # declared worst case at the limit (plan.md)

SYMBOLS_20 = [f"T{i:04d}" for i in range(1, 21)]


def _tokens(result: dict) -> float:
    """Approximate token size of *result* as compact-serialized chars / 4."""
    return len(json.dumps(result, separators=(",", ":"))) / 4


def _batch_client(symbols: list[str]) -> FakeQuotesClient:
    payload = build_quotes_payload([build_quote_entry(s) for s in symbols])
    return FakeQuotesClient(quotes_payload=payload)


class TestSingleQuoteTokenBudget:
    """A single curated quote stays within 250 tokens (SC-002)."""

    @pytest.mark.performance
    def test_single_live_quote_within_budget(self) -> None:
        """The live AAPL fixture response serializes within 250 tokens."""
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY})
        result = get_quotes(client, "AAPL")

        assert result["outcome"] == "ok"
        # Anti-gaming: the response must be the full curated quote.
        quote = result["quotes"]["AAPL"]
        assert len(quote) == 10, "every curated field must be present"
        tokens = _tokens(result)
        assert tokens <= SINGLE_TOKEN_BUDGET, (
            f"single-quote response is {tokens:.0f} tokens, "
            f"budget is {SINGLE_TOKEN_BUDGET}"
        )

    @pytest.mark.performance
    def test_synthetic_quote_within_budget(self) -> None:
        from schwab_mcp.quotes import get_quotes

        payload = build_quotes_payload([build_quote_entry("T0001")])
        result = get_quotes(FakeQuotesClient(quotes_payload=payload), "T0001")

        assert _tokens(result) <= SINGLE_TOKEN_BUDGET


class TestBatchTokenBudget:
    """Batch budgets: 10 symbols <= 2.500 tokens; linear growth."""

    @pytest.mark.performance
    def test_ten_symbol_batch_within_budget(self) -> None:
        from schwab_mcp.quotes import get_quotes

        client = _batch_client(SYMBOLS_20[:10])
        result = get_quotes(client, SYMBOLS_20[:10])

        assert result["outcome"] == "ok"
        assert len(result["quotes"]) == 10, "fixture must stay representative"
        tokens = _tokens(result)
        assert tokens <= BATCH_10_TOKEN_BUDGET, (
            f"10-symbol batch is {tokens:.0f} tokens, "
            f"budget is {BATCH_10_TOKEN_BUDGET}"
        )

    @pytest.mark.performance
    def test_twenty_symbol_worst_case_within_budget(self) -> None:
        """The 20-symbol limit stays inside the declared ~5.000-token
        worst case (plan.md)."""
        from schwab_mcp.quotes import get_quotes

        client = _batch_client(SYMBOLS_20)
        result = get_quotes(client, SYMBOLS_20)

        assert result["outcome"] == "ok"
        assert len(result["quotes"]) == 20
        assert _tokens(result) <= BATCH_20_TOKEN_BUDGET

    @pytest.mark.performance
    def test_response_grows_linearly_no_hidden_bulk(self) -> None:
        """SC-005 path: the marginal cost of one more symbol stays within
        the per-symbol budget — size grows linearly, no hidden bulk."""
        from schwab_mcp.quotes import get_quotes

        one = get_quotes(
            FakeQuotesClient(
                quotes_payload=build_quotes_payload([build_quote_entry(SYMBOLS_20[0])])
            ),
            SYMBOLS_20[0],
        )
        ten_client = _batch_client(SYMBOLS_20[:10])
        ten = get_quotes(ten_client, SYMBOLS_20[:10])

        marginal = (_tokens(ten) - _tokens(one)) / 9
        assert marginal <= SINGLE_TOKEN_BUDGET, (
            f"marginal cost per symbol is {marginal:.0f} tokens, "
            f"must stay within the {SINGLE_TOKEN_BUDGET}-token per-symbol budget"
        )


class TestLatencyBudget:
    """Latency budget: <= 5 s p95 per invocation (SC-001)."""

    @pytest.mark.performance
    def test_single_invocation_under_budget(self) -> None:
        from schwab_mcp.quotes import get_quotes

        client = FakeQuotesClient(
            quotes_payload={"AAPL": EQUITY_QUOTE_ENTRY}, delay=0.1
        )
        start = time.monotonic()
        result = get_quotes(client, "AAPL")
        elapsed = time.monotonic() - start

        assert result["outcome"] == "ok"
        assert elapsed <= LATENCY_BUDGET_S, (
            f"invocation took {elapsed:.2f} s, budget is {LATENCY_BUDGET_S} s (p95)"
        )

    @pytest.mark.performance
    def test_max_symbols_under_budget(self) -> None:
        """20 symbols with a 0.1 s network delay complete within 5 s."""
        from schwab_mcp.quotes import get_quotes

        client = _batch_client(SYMBOLS_20)
        client._delay = 0.1
        start = time.monotonic()
        result = get_quotes(client, SYMBOLS_20)
        elapsed = time.monotonic() - start

        assert result["outcome"] == "ok"
        assert elapsed <= LATENCY_BUDGET_S
