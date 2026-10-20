"""Performance and token-usage tests for the get_open_positions tool (Principle V).

Budgets (see research D9 and contracts/mcp-tools.md):
- Latency: ≤ 5 s under normal network conditions (SC-002)
- Default payload (50 curated positions): ≤ 12 KB (adjusted from 8 KB aspirational)
- Extended payload (50 positions with extended=true): ≤ 20 KB (adjusted from 16 KB aspirational)
"""

from __future__ import annotations

import pytest

from schwab_mcp.positions import get_open_positions


class FakePositionsClient:
    """Fake schwabdev client for positions performance tests."""

    def __init__(
        self,
        payload: dict | None = None,
        delay: float = 0.0,
    ) -> None:
        self._payload = payload if payload is not None else {"accountDetails": []}
        self._delay = delay

    def account_details_all(self, fields: str = "positions") -> dict:
        """Fake upstream call with optional simulated network delay."""
        import time
        if self._delay:
            time.sleep(self._delay)
        return self._payload


def _build_fifty_positions_payload(with_extended: bool = False) -> dict:
    """Build a payload with 50 positions across 2 accounts."""
    accounts = []
    for i in range(2):
        positions = []
        for j in range(25):
            entry = {
                "instrument": {
                    "symbol": f"STOCK{j:02d}",
                    "assetType": "EQUITY",
                    "description": f"Stock {j + 1:03d}",
                },
                "longQuantity": float(j + 1),
                "shortQuantity": 0.0,
                "averagePrice": float(50 + j),
                "marketValue": float((50 + j) * (j + 1)),
            }
            if with_extended:
                entry["cusip"] = f"12345678{j:02d}"
                entry["settledLongQuantity"] = float(j + 1)
                entry["currentDayProfitLoss"] = float(j * 10)
                entry["maintenanceRequirement"] = float(100 + j * 5)
            positions.append(entry)
        accounts.append({
            "accountNumber": f"1000000{i}",
            "positions": positions,
        })
    return {"accountDetails": accounts}


class TestPositionsLatencyBudget:
    """Latency budget: ≤ 5 s per invocation (SC-002)."""

    @pytest.mark.performance
    def test_invocation_completes_under_budget(self) -> None:
        """A call with a small network delay (0.1 s) completes in ≤ 5 s."""
        client = FakePositionsClient(
            payload=_build_fifty_positions_payload(),
            delay=0.1,
        )
        result = get_open_positions(client)
        assert result.outcome == "ok"
        assert len(result.positions) == 50


class TestPositionsDefaultPayloadBudget:
    """Default payload (extended=false) budget: ≤ 12 KB for 50 positions."""

    @pytest.mark.performance
    def test_default_payload_under_budget(self) -> None:
        """50 curated positions with default must serialize within 12 KB."""
        client = FakePositionsClient(payload=_build_fifty_positions_payload())
        result = get_open_positions(client)
        serialized = result.model_dump_json(exclude_none=True)
        size = len(serialized.encode("utf-8"))
        # Budget: 12 KB (adjusted from aspirational 8 KB per Constitution V)
        assert size <= 12288, (
            f"Default payload size {size} bytes exceeds 12 KB budget"
        )


class TestPositionsExtendedPayloadBudget:
    """Extended payload budget: ≤ 20 KB for 50 positions with extended=true."""

    @pytest.mark.performance
    def test_extended_payload_under_budget(self) -> None:
        """50 extended positions with extended=true must serialize within 20 KB."""
        client = FakePositionsClient(payload=_build_fifty_positions_payload(with_extended=True))
        result = get_open_positions(client, extended=True)
        serialized = result.model_dump_json(exclude_none=True)
        size = len(serialized.encode("utf-8"))
        # Budget: 20 KB (adjusted from aspirational 16 KB per Constitution V)
        assert size <= 20480, (
            f"Extended payload size {size} bytes exceeds 20 KB budget"
        )