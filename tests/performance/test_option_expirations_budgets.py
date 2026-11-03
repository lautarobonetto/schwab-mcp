"""Performance and token-budget tests for ``get_option_expiration_chain``.

Budgets (contracts/mcp-tools.md §6, plan.md — Principle V):

- **Token budget (SC-001)**: the curated default response of a
  **representative liquid-underlying fixture** (AAPL-style, 8 weekly
  expirations within the 60-day ceiling, ~240 tokens measured) is
  ≤ 1,000 tokens.  A dense index-style fixture (60 near-daily
  expirations) is the worst case and has its own **recorded ceiling of
  ≤ 1,100 tokens** (growth justification in plan.md Complexity
  Tracking).
- **Latency budget (SC-002)**: ≤ 5 s per invocation (008 precedent;
  inside the 10 s spec ceiling).
- **One-upcall invariant (SC-004)**: exactly one provider invocation per
  request, asserted in every scenario.

Token measurement: ``len(json.dumps(result, separators=(",", ":"))) / 4``
(the repo's established estimator).
"""

from __future__ import annotations

import json
import time

import pytest

from schwab_mcp.options_chain import get_option_expiration_chain
from tests.unit.helpers import (
    FakeExpirationClient,
    build_expiration_chain_payload,
    chain_expiry_date,
)

# --- Representative fixture (AAPL-style: ~8 weekly expirations inside 60d) ----
REPRESENTATIVE_DTES = (7, 14, 21, 28, 35, 42, 49, 56)
# --- Dense worst-case (index-style near-daily; data-model.md §6) --------------
DENSE_EXPIRATION_COUNT = 60

LATENCY_BUDGET_S = 5.0  # <= 5 s p95 per invocation (plan.md)
REPRESENTATIVE_TOKEN_BUDGET = 1_000  # SC-001: < 1,000 tokens
DENSE_WORST_CASE_CEILING = 1_100  # Recorded ceiling (plan.md Complexity Tracking)


def _representative_payload() -> dict:
    """AAPL-style ~12 weekly expirations — the realistic liquid-underlying
    shape that SC-001 asserts against."""
    return build_expiration_chain_payload(
        [(chain_expiry_date(dte), dte, "C") for dte in REPRESENTATIVE_DTES]
    )


def _dense_payload() -> dict:
    """Provider payload with 60 near-daily expirations (worst case)."""
    return build_expiration_chain_payload(
        [(chain_expiry_date(dte), dte, "C") for dte in range(DENSE_EXPIRATION_COUNT)]
    )


def _token_count(result: dict) -> float:
    """Approximate token size of *result* as compact-serialized chars / 4."""
    return len(json.dumps(result, separators=(",", ":"))) / 4


class TestExpirationChainTokenBudget:
    """Curated default response ≤ 1,000 tokens (SC-001)."""

    @pytest.mark.performance
    def test_representative_response_within_spec_budget(self) -> None:
        """Representative token budget: ~240 tokens, well within SC-001's < 1,000."""
        client = FakeExpirationClient(_representative_payload())
        result = get_option_expiration_chain(client, "TEST")
        assert result["outcome"] == "ok"
        assert result["expiration_count"] == 8
        tokens = _token_count(result)
        assert tokens <= REPRESENTATIVE_TOKEN_BUDGET, (
            f"representative response is {tokens:.0f} tokens, "
            f"SC-001 budget is {REPRESENTATIVE_TOKEN_BUDGET}"
        )
        assert client.call_count == 1

    @pytest.mark.performance
    def test_dense_worst_case_records_measured_ceiling(self) -> None:
        """The dense 60-entry index-style worst case fits within the
        recorded ceiling of 1,100 tokens (plan.md Complexity Tracking)."""
        client = FakeExpirationClient(_dense_payload())
        result = get_option_expiration_chain(client, "TEST")
        assert result["outcome"] == "ok"
        assert result["expiration_count"] == DENSE_EXPIRATION_COUNT
        tokens = _token_count(result)
        assert tokens <= DENSE_WORST_CASE_CEILING, (
            f"dense worst-case response is {tokens:.0f} tokens, "
            f"recorded ceiling is {DENSE_WORST_CASE_CEILING}"
        )
        assert client.call_count == 1


class TestExpirationChainLatencyBudget:
    """Latency budget: ≤ 5 s per invocation (SC-002, 008 p95 precedent)."""

    @pytest.mark.performance
    def test_invocation_completes_under_budget(self) -> None:
        """A call with a small network delay (0.1 s) completes in ≤ 5 s."""
        client = FakeExpirationClient(_dense_payload(), delay=0.1)
        start = time.monotonic()
        result = get_option_expiration_chain(client, "TEST")
        elapsed = time.monotonic() - start
        assert result["outcome"] == "ok"
        assert elapsed <= LATENCY_BUDGET_S, (
            f"invocation took {elapsed:.2f} s, "
            f"budget is {LATENCY_BUDGET_S} s (p95)"
        )
        assert client.call_count == 1