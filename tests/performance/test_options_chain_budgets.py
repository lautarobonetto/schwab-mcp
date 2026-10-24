"""Performance and token-budget tests for the get_option_chain tool (Principle V).

Budgets (tmp/008-api-brief.md "Token budgets (T008 / SC-002) — ADJUSTED
2026-10-24", plan.md Complexity Tracking, contracts/mcp-tools.md §6):

- Default filters (representative liquid-underlying fixture:
  ~12 expirations x ~100 strike rows, both legs): **<= 110.000 tokens**
  (adjusted from 75.000 by user decision 2026-10-24; growth justification
  registered in plan.md Complexity Tracking + docs/tools.md).
- With ``delta_target`` (12 expirations x <= 5 strikes x 2 types):
  **< 6.000 tokens** (adjusted from 3.000).
- FR-012 bound: response never exceeds expirations x types x strikes
  (rows <= 2 x max_strikes per expiration; <= 5 legs per type with
  ``delta_target``).
- Latency: <= 5 s per invocation (p95 hook per plan.md).

Token measurement (SC-002): ``len(json.dumps(result, separators=(",", ":"))) / 4``.
The fixture is deliberately representative — do NOT shrink it: the budget is
the constitution's measurable budget gate and only meaningful at full size.
"""

from __future__ import annotations

import json
import time

import pytest

from schwab_mcp.options_chain import build_chain_result, get_option_chain, OptionChainQuery
from tests.unit.helpers import (
    build_chain_payload,
    build_expiration_map,
    build_response,
    chain_expiry_date,
)

# --- Representative liquid-underlying fixture constants ----------------------
# 100-strike ladder with 0.5 step centered on the underlying (251.31): the ATM
# strike (251.5) sits mid-ladder so the default selection (up to 50 strikes per
# side of ATM) yields a full-size ~100-row expiration.
UNDERLYING_PRICE = 251.31
STRIKE_STEP = 0.5
STRIKES = [round(226.5 + STRIKE_STEP * i, 1) for i in range(100)]

# 12 expirations inside the default DTE window (dte_max_effective = 60) in
# ~12 steps, matching a real weekly/monthly chain of a liquid underlying.
EXPIRATION_DTES = (7, 12, 17, 22, 27, 32, 37, 42, 47, 52, 57, 60)

MAX_STRIKES = 50          # default max_strikes per side (FR-012 bound)
LATENCY_BUDGET_S = 5.0    # <= 5 s p95 per invocation (plan.md)


def _delta_ladder(kind: str) -> list[float]:
    """Per-strike delta spread for the ``delta_target`` fixture.

    Calls descend 0.95 -> -0.05 with the strike ladder and puts ascend
    -0.95 -> 0.05 (realistic monotone behavior).  ``abs(delta)`` brackets 0.20
    for both types and hits it exactly at one interior strike (index 75), so
    the delta window (center ± 2) is unique, full and interior — no internal
    re-fetch, deterministic size.
    """
    if kind == "CALL":
        return [round(0.95 - i * 0.01, 4) for i in range(len(STRIKES))]
    return [round(-0.95 + i * 0.01, 4) for i in range(len(STRIKES))]


def _build_representative_payload(with_delta_spread: bool = False) -> dict:
    """Build the representative liquid-underlying ``option_chains`` payload.

    12 expirations x 100 strikes x both legs (call + put maps), rows built via
    ``build_contract`` (realistic rounded values).  With *with_delta_spread*
    the contracts carry the delta ladder of :func:`_delta_ladder` instead of
    the builder defaults.
    """
    call_map: dict[str, dict] = {}
    put_map: dict[str, dict] = {}
    for dte in EXPIRATION_DTES:
        exp_date = chain_expiry_date(dte)
        call_deltas = _delta_ladder("CALL") if with_delta_spread else None
        put_deltas = _delta_ladder("PUT") if with_delta_spread else None
        call_map.update(
            build_expiration_map(exp_date, "CALL", STRIKES, deltas=call_deltas)
        )
        put_map.update(
            build_expiration_map(exp_date, "PUT", STRIKES, deltas=put_deltas)
        )
    return build_chain_payload(
        call_map,
        put_map,
        symbol="TEST",
        underlying_price=UNDERLYING_PRICE,
    )


class FakeChainClient:
    """Fake schwabdev client serving a fixed option-chains payload."""

    def __init__(self, payload: dict, delay: float = 0.0) -> None:
        self._payload = payload
        self._delay = delay
        self.calls: list[dict] = []

    def option_chains(self, symbol: str, **kwargs):
        """Fake upstream call: records kwargs and simulates network delay."""
        self.calls.append({"symbol": symbol, **kwargs})
        if self._delay:
            time.sleep(self._delay)
        return build_response(self._payload)


def _token_count(result: dict) -> float:
    """Approximate token size of *result* as compact-serialized chars / 4."""
    return len(json.dumps(result, separators=(",", ":"))) / 4


class TestOptionsChainDefaultTokenBudget:
    """Default-filters token budget: <= 110.000 tokens (SC-002, adjusted)."""

    @pytest.mark.performance
    def test_default_token_budget(self) -> None:
        """12 expirations x ~100 both-leg rows serialize within 110.000 tokens."""
        client = FakeChainClient(_build_representative_payload())
        result = get_option_chain(client, "TEST")
        assert result["outcome"] == "ok"
        expirations = result["expirations"]
        # Anti-gaming: the response must be full-size — all 12 fixture
        # expirations survive the default DTE filter and each keeps ~100 rows
        # (99 rows when the ATM strike is shared by both selection sides).
        assert len(expirations) == len(EXPIRATION_DTES)
        for exp in expirations:
            assert len(exp["strikes"]) >= 95, (
                f"expiration {exp['expiration_date']} has only "
                f"{len(exp['strikes'])} rows — fixture must stay representative"
            )
        tokens = _token_count(result)
        # Budget: 110.000 tokens (adjusted 2026-10-24 by user decision from
        # 75.000; honest measurement of the mandated 23-column both-leg rows
        # is ~95–106k — growth justified in plan.md Complexity Tracking).
        assert tokens <= 110_000, (
            f"default-filters response is {tokens:.0f} tokens, budget is 110.000"
        )


class TestOptionsChainDeltaTokenBudget:
    """delta_target token budget: < 6.000 tokens (SC-002, adjusted)."""

    @pytest.mark.performance
    def test_delta_token_budget(self) -> None:
        """delta_target=0.20 serializes within 6.000 tokens (SC-005 shape)."""
        client = FakeChainClient(_build_representative_payload(with_delta_spread=True))
        result = get_option_chain(client, "TEST", option_type="both", delta_target=0.20)
        assert result["outcome"] == "ok"
        # The fixture brackets the target for both types: no internal re-fetch.
        assert len(client.calls) == 1, (
            "delta_target=0.20 must be bracketed by the fixture (single upcall)"
        )
        for exp in result["expirations"]:
            call_rows = [row for row in exp["strikes"] if "call" in row]
            put_rows = [row for row in exp["strikes"] if "put" in row]
            # SC-005 shape bound (<= 5 legs per type per expiration) and
            # anti-gaming floor: the delta window (center ± 2) is interior to
            # the strike ladder, so a compliant selection yields exactly 5.
            assert len(call_rows) == 5
            assert len(put_rows) == 5
        tokens = _token_count(result)
        # Budget: 6.000 tokens (adjusted 2026-10-24 by user decision from
        # 3.000; honest measurement is ~4,5–5k).
        assert tokens < 6_000, (
            f"delta_target response is {tokens:.0f} tokens, budget is 6.000"
        )


class TestOptionsChainFr012Bounds:
    """FR-012/SC-006: response never exceeds expirations × types × strikes."""

    @pytest.mark.performance
    def test_default_response_respects_fr012_bounds(self) -> None:
        """Rows ≤ 2 × max_strikes; legs ≤ expirations × 2 × (2 × 50); zero
        out-of-bounds contracts."""
        client = FakeChainClient(_build_representative_payload())
        result = get_option_chain(client, "TEST")
        assert result["outcome"] == "ok"
        expirations = result["expirations"]
        fixture_strikes = set(STRIKES)
        total_legs = 0
        for exp in expirations:
            rows = exp["strikes"]
            # Row bound: up to max_strikes nearest strikes below ATM UNION up
            # to max_strikes nearest strikes above ATM.
            assert len(rows) <= 2 * MAX_STRIKES
            atm = exp["atm_strike"]
            for row in rows:
                strike = row["strike"]
                # SC-006: zero out-of-bounds contracts — every strike exists in
                # the fixture ladder (never invented) and lies inside the
                # permitted window: atm ± (max_strikes - 1) strike steps.
                assert strike in fixture_strikes, f"strike {strike} not in fixture"
                assert abs(strike - atm) <= (MAX_STRIKES - 1) * STRIKE_STEP + 1e-9, (
                    f"strike {strike} outside the permitted window around ATM {atm}"
                )
                total_legs += sum(1 for key in ("call", "put") if key in row)
        # FR-012: total legs never exceed expirations × types × strikes.
        assert total_legs <= len(expirations) * 2 * (2 * MAX_STRIKES)

    @pytest.mark.performance
    def test_delta_response_respects_fr012_bounds(self) -> None:
        """With delta_target: ≤ 5 legs per type per expiration, contiguous and
        in-ladder (never invented)."""
        client = FakeChainClient(_build_representative_payload(with_delta_spread=True))
        result = get_option_chain(client, "TEST", option_type="both", delta_target=0.20)
        assert result["outcome"] == "ok"
        fixture_strikes = set(STRIKES)
        for exp in result["expirations"]:
            for leg in ("call", "put"):
                selected = sorted(
                    row["strike"] for row in exp["strikes"] if leg in row
                )
                # FR-012 with delta: ≤ 5 legs per type (center ± 2 window).
                assert len(selected) <= 5
                assert all(s in fixture_strikes for s in selected), (
                    f"expiration {exp['expiration_date']} {leg}: strike outside fixture"
                )
                # SC-006: the selected strikes form one contiguous run inside
                # the ladder — the permitted delta window, nothing out of it.
                idx = [STRIKES.index(s) for s in selected]
                assert idx == list(range(idx[0], idx[0] + len(idx))), (
                    f"expiration {exp['expiration_date']} {leg}: non-contiguous window"
                )


class TestOptionsChainLatencyBudget:
    """Latency budget: ≤ 5 s per invocation (plan.md, p95 hook)."""

    @pytest.mark.performance
    def test_invocation_completes_under_budget(self) -> None:
        """A call with a small network delay (0.1 s) completes in ≤ 5 s."""
        client = FakeChainClient(_build_representative_payload(), delay=0.1)
        start = time.monotonic()
        result = get_option_chain(client, "TEST")
        elapsed = time.monotonic() - start
        assert result["outcome"] == "ok"
        assert elapsed <= LATENCY_BUDGET_S, (
            f"invocation took {elapsed:.2f} s, budget is {LATENCY_BUDGET_S} s (p95)"
        )
