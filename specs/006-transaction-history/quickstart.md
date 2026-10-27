# Quickstart: `get_transaction_history` (006)

End-to-end validation guide. Normative details in
[contracts/mcp-tools.md](contracts/mcp-tools.md) and
[data-model.md](data-model.md).

## Prerequisites

1. Environment ready: `uv sync`
2. Configuration: `SCHWAB_APP_KEY` and `SCHWAB_APP_SECRET` in the environment
3. Valid authorization: `uv run schwab-mcp auth-status` → `state: valid`
   (if not, the owner runs `uv run schwab-mcp auth`)
4. Permissions: the registered app and the accounts must have
   transaction read access (see the Caveat in contracts/mcp-tools.md)

## Run

```sh
uv run schwab-mcp serve
```

The server registers 2 tools: `get_open_positions` and
**`get_transaction_history`**.

## Validation scenarios (map to the spec's SCs)

### S1 — Full history of a range (SC-001/SC-002/SC-004)

With an MCP client connected over stdio:

```json
{"name": "get_transaction_history",
 "arguments": {"start_date": "2026-09-01", "end_date": "2026-09-30"}}
```

Expected: `outcome=ok`, `detail=history_retrieved` (or `no_movements`
if the month had no activity), `movements` with trades **and also**
transfers/interest/dividends/adjustments if there were any, ordered
from oldest to newest, `total_count` ≥ `returned`, `returned ≤ 50`.

### S2 — Instrument filter (FR-003, SC-005)

```json
{"name": "get_transaction_history",
 "arguments": {"start_date": "2026-09-01", "end_date": "2026-09-30",
               "symbol": "AAPL"}}
```

Expected: only movements with `"symbol": "AAPL"`; no transfers or
interest. With a non-existent symbol (e.g. `ZZZZZZ`) →
`instrument_not_found` error — **not** an ambiguous `no_movements`.

### S3 — Pagination without duplicates or gaps (SC-006)

If `has_more=true`, repeat the same query with `"offset": 50`, then
`100`… until `has_more=false`. Verify: constant `total_count` across
pages, a union without duplicates (by `account_hash` + `occurred_at` +
description) and without omissions, and that the last page carries no
`next_offset`.

### S4 — Range validation (FR-004, edge cases)

Each must fail with an actionable error, **without** calling the
provider:

- `end_date < start_date` → error names both dates.
- 2-year range → error states the 1-year maximum.
- `end_date: "2099-01-01"` → future-date error.
- `start_date: "01-09-2026"` → format error.

### S5 — Budgets (SC-001/SC-003)

```sh
uv run pytest tests/performance/test_transactions_budgets.py -v
```

Expected: p95 latency ≤ 5 s on the test set; default page (50
movements) ≤ 16 KB; extended ≤ 64 KB.

### S6 — No secrets

```sh
uv run pytest tests/unit/test_no_secrets_in_output.py -v
```

Expected: green — no result field or event contains tokens, app keys
or secrets.

## Diagnosing persistent empties (Caveat)

If `no_movements` appears for wide ranges in an account with activity
visible on schwab.com, the likely cause is the app/account's
transaction read permission (not missing data). See the "Operational
caveat" section of the contract.