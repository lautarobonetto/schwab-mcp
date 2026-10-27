# Quickstart: List Open Positions

**Feature**: `003-list-open-positions`

End-to-end validation guide. Schema details live in
[contracts/mcp-tools.md](contracts/mcp-tools.md) and
[data-model.md](data-model.md) — not duplicated here.

## Prerequisites

1. Environment installed: `uv sync`
2. Credentials in the environment: `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`
3. Authorization in force (feature 001): `uv run schwab-mcp auth-status`
   → `{"state": "valid", ...}`. If not, run `schwab-mcp auth` (human only).

## Test-based validation (main gate)

```sh
uv run pytest tests/unit/test_positions.py -v        # mapping/consolidation/sign/omission
uv run pytest tests/unit/test_server_tool.py -v      # registration + classified outcomes
uv run pytest tests/unit/test_no_secrets_in_output.py -v  # FR-008
uv run pytest -m performance tests/performance/test_positions_budgets.py -v  # 5 s + 8 KB
uv run pytest                                        # full suite: commit gate (0 skipped)
```

Expected: all green. Unit tests use client fakes (no network).

## Manual end-to-end validation (with real network)

1. Start the server:

   ```sh
   uv run schwab-mcp serve
   ```

2. From an MCP client connected over stdio (opencode or another), invoke:

   ```json
   {"name": "get_open_positions", "arguments": {}}
   ```

3. Expected result with holdings (example shape):

   ```json
   {
     "outcome": "ok",
     "detail": "data_received",
     "retryable": false,
     "retrieved_at": "2026-10-20T14:03:11+00:00",
     "positions": [
       {
         "account_hash": "…opaque hash…",
         "symbol": "SPY",
         "instrument_type": "EQUITY",
         "description": "SPDR S&P 500 ETF Trust",
         "quantity": 10.0,
         "average_price": 580.25,
         "market_value": 5910.0,
         "unrealized_pl": 107.5,
         "price_timestamp": "2026-10-20T14:03:11+00:00"
       }
     ]
   }
   ```

   Checks:
   - One entry per (account, contract); legs of a strangle/condor separate, signed quantity (shorts negative).
   - `price_timestamp` present in every entry (FR-012).
   - No raw account number, token, or secret in the result or on stderr.

4. No positions → `outcome: "ok"`, `detail: "no_positions"`, `positions: []` (not an error).

5. Extended mode:

   ```json
   {"name": "get_open_positions", "arguments": {"extended": true}}
   ```

   Each entry adds `"extended": {...}` with the provider passthrough.

6. Audit on `serve`'s stderr: per invocation, exactly one
   `positions_query_start` and one terminal (`positions_query_success` or
   `positions_query_failure`) — vocabulary in [contracts/events.md](contracts/events.md).

## Failure scenarios (playbook verification)

| How to trigger it | Expected result |
|-------------------|-----------------|
| No connectivity (disconnect network) | `outcome: "transient_failure"`, `retryable: true`, `detail: "provider_unreachable"`, immediate (no internal retries) |
| Refresh token rejected (expired/revoked) | `outcome: "reauth_required"` → agent notifies the owner (`schwab-mcp auth`); DO NOT retry |
| One account fails and others don't | `outcome: "partial_failure"`, `accounts_failed` with hash + detail, `positions` with whatever did respond |

## Agent flow on failure

Identical to the [docs/tools.md](../../../docs/tools.md) playbook:
`transient_failure` → retry later; `reauth_required` → notify the
owner and monitor with `auth-status`; `partial_failure` → decide whether the
subset suffices or retry.