"""Performance and payload-size tests for the get_transaction_history tool.

Budgets (see specs/006-transaction-history/contracts/mcp-tools.md):
- Latency (SC-001): p95 ≤ 5 seconds for 20+ queries with a fast fake client
- Default payload (50 movements, no extended) serialized JSON ≤ 16 KB (SC-003)
- Extended payload (50 movements with extended fields) ≤ 64 KB (SC-003)
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from schwab_mcp.transactions import get_transaction_history


# =============================================================================
# Fake client for performance measurement — returns immediately, no delay
# =============================================================================


class _validator:
    """Mimics ``schwabdev.validation.Validator`` with a toggleable ``enabled`` flag."""

    enabled = True


class FastFakeClient:
    """Fake schwabdev Client that returns immediately (no delay).

    Pre-built with account list and per-account transaction responses.
    Does not record calls, simulate errors, or add artificial delays.
    """

    def __init__(
        self,
        accounts: list[dict[str, str]],
        tx_responses: dict[str, Any],
    ) -> None:
        self._validator = _validator()
        self._accounts = accounts
        self._tx_responses = tx_responses

    def linked_accounts(self) -> list[dict[str, str]]:
        return list(self._accounts)

    def instruments(
        self, symbols: list[str], projection: str
    ) -> Any:
        known = {"AAPL", "SPY", "MSFT", "GOOGL", "NVDA"}
        if not symbols or symbols[0].upper() not in {s.upper() for s in known}:
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
        return self._tx_responses.get(accountHash, {"transactions": []})


# =============================================================================
# Fixtures: build 50 realistic transaction entries across 3 accounts
# =============================================================================

TRANSACTION_TYPES = [
    "TRADE",
    "TRADE",
    "DIVIDEND_OR_INTEREST",
    "ACH_RECEIPT",
    "ACH_DISBURSEMENT",
    "CASH_RECEIPT",
    "CASH_DISBURSEMENT",
    "ELECTRONIC_FUND",
    "WIRE_IN",
    "WIRE_OUT",
    "JOURNAL",
    "MEMORANDUM",
    "MARGIN_CALL",
    "MONEY_MARKET",
    "SMA_ADJUSTMENT",
]

INSTRUMENTS: list[tuple[str, str]] = [
    ("AAPL", "EQUITY"),
    ("SPY", "ETF"),
    ("MSFT", "EQUITY"),
    ("GOOGL", "EQUITY"),
    ("NVDA", "EQUITY"),
]

ACCOUNT_HASHES = ["ACC001", "ACC002", "ACC003"]
ACCOUNT_COUNTS = [20, 15, 15]


def _build_tx(
    activity_id: str,
    acct_hash: str,
    tx_type: str,
    description: str,
    amount: float,
    occurred_at: str,
    settlement_date: str,
    symbol: str | None = None,
    instrument_type: str | None = None,
    with_extended: bool = False,
) -> dict:
    """Build a single provider-format transaction dict (see mapping tests for the schema)."""
    tx: dict = {
        "activityId": activity_id,
        "type": tx_type,
        "description": description,
        "netAmount": amount,
        "transactionDate": occurred_at,
        "settlementDate": settlement_date,
        "currency": "USD",
        "accountHash": acct_hash,
    }
    if symbol is not None and instrument_type is not None:
        tx["instrument"] = {
            "symbol": symbol,
            "instrumentType": instrument_type,
        }
    if with_extended:
        tx["fees"] = 0.0
        tx["commission"] = 0.35
        tx["transferItems"] = []
    return tx


def _build_fifty_tx_payload(with_extended: bool = False) -> dict[str, dict]:
    """Build per-account transaction responses for 50 entries across 3 accounts.

    Distribution:
      ACC001: 20 trades/misc
      ACC002: 15 trades/misc
      ACC003: 15 trades/misc
    """
    descriptions = [
        "Bought shares",
        "Sold shares",
        "Dividend payment",
        "ACH deposit",
        "Wire transfer",
        "Journal entry",
        "Interest payment",
        "Fee adjustment",
    ]
    tx_id = 0
    responses: dict[str, dict] = {}

    for acct_hash, count in zip(ACCOUNT_HASHES, ACCOUNT_COUNTS):
        txs: list[dict] = []
        for j in range(count):
            tx_id += 1
            tx_type = TRANSACTION_TYPES[j % len(TRANSACTION_TYPES)]
            day = 1 + (tx_id // 5)
            hour = 9 + (tx_id % 8)
            minute = (tx_id * 3) % 60
            occurred_at = f"2026-10-{day:02d}T{hour:02d}:{minute:02d}:00+00:00"
            settlement_date = f"2026-10-{min(day + 2, 31):02d}"
            sym, inst_type = INSTRUMENTS[j % len(INSTRUMENTS)]
            amount = round(100.0 + tx_id * 10.5, 2) * (-1 if j % 2 == 0 else 1)
            desc = descriptions[j % len(descriptions)]

            txs.append(
                _build_tx(
                    activity_id=f"act-{tx_id:04d}",
                    acct_hash=acct_hash,
                    tx_type=tx_type,
                    description=desc,
                    amount=amount,
                    occurred_at=occurred_at,
                    settlement_date=settlement_date,
                    symbol=sym,
                    instrument_type=inst_type,
                    with_extended=with_extended,
                )
            )
        responses[acct_hash] = {"transactions": txs}

    return responses


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def accounts() -> list[dict[str, str]]:
    """Three account hashes returned by ``linked_accounts()``."""
    return [{"accountHash": h} for h in ACCOUNT_HASHES]


@pytest.fixture
def fifty_tx_payload(accounts: list[dict[str, str]]) -> dict[str, dict]:  # noqa: ARG001
    """Per-account transaction responses with 50 entries, default fields."""
    return _build_fifty_tx_payload(with_extended=False)


# =============================================================================
# Latency budget (SC-001): p95 ≤ 5 seconds for 20+ queries
# =============================================================================


class TestTransactionsLatencyBudget:
    """Latency budget: p95 ≤ 5 seconds for 20+ queries with fast fake client (SC-001)."""

    @pytest.mark.performance
    def test_p95_completes_under_budget(self) -> None:
        """20+ queries with a fast fake client must have p95 < 5 seconds."""
        payload = _build_fifty_tx_payload(with_extended=False)
        durations: list[float] = []

        for _ in range(20):
            client = FastFakeClient(
                accounts=[{"accountHash": h} for h in ACCOUNT_HASHES],
                tx_responses=payload,
            )
            start = time.perf_counter()
            result = get_transaction_history(
                client,
                start_date="2026-10-01",
                end_date="2026-10-20",
                extended=False,
            )
            elapsed = time.perf_counter() - start
            durations.append(elapsed)
            assert result.outcome == "ok", (
                f"Expected ok outcome, got {result.outcome}"
            )

        durations.sort()
        p95_index = int(0.95 * len(durations))
        p95 = durations[p95_index]
        assert p95 < 5.0, (
            f"p95 latency {p95:.4f}s exceeds 5 s budget "
            f"(min={durations[0]:.4f}s, max={durations[-1]:.4f}s)"
        )


# =============================================================================
# Default payload budget (SC-003): ≤ 16 KB for 50 movements
# =============================================================================


class TestTransactionsDefaultPayloadBudget:
    """Default payload (extended=false) budget: ≤ 16 KB for 50 movements."""

    @pytest.mark.performance
    def test_default_payload_under_budget(self) -> None:
        """50 movements with default must serialize within 16 KB."""
        client = FastFakeClient(
            accounts=[{"accountHash": h} for h in ACCOUNT_HASHES],
            tx_responses=_build_fifty_tx_payload(with_extended=False),
        )
        result = get_transaction_history(
            client,
            start_date="2026-10-01",
            end_date="2026-10-20",
            extended=False,
        )
        serialized = result.model_dump_json(exclude_none=True)
        size = len(serialized.encode("utf-8"))
        # Budget: 16 KB (SC-003)
        assert size <= 16384, (
            f"Default payload size {size} bytes exceeds 16 KB budget"
        )


# =============================================================================
# Extended payload budget (SC-003): ≤ 64 KB for 50 movements
# =============================================================================


class TestTransactionsExtendedPayloadBudget:
    """Extended payload budget: ≤ 64 KB for 50 movements with extended=true."""

    @pytest.mark.performance
    def test_extended_payload_under_budget(self) -> None:
        """50 extended movements with extended=true must serialize within 64 KB."""
        client = FastFakeClient(
            accounts=[{"accountHash": h} for h in ACCOUNT_HASHES],
            tx_responses=_build_fifty_tx_payload(with_extended=True),
        )
        result = get_transaction_history(
            client,
            start_date="2026-10-01",
            end_date="2026-10-20",
            extended=True,
        )
        serialized = result.model_dump_json(exclude_none=True)
        size = len(serialized.encode("utf-8"))
        # Budget: 64 KB (SC-003)
        assert size <= 65536, (
            f"Extended payload size {size} bytes exceeds 64 KB budget"
        )