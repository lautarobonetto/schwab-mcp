# Quickstart: underlying-aware filter in `get_transaction_history` (007)

End-to-end validation guide. Normative details in
[contracts/mcp-tools.md](contracts/mcp-tools.md) and
[data-model.md](data-model.md). Prerequisites identical to feature 006
(`uv sync` environment, valid credentials via `uv run schwab-mcp
auth-status`, transaction read permissions).

## Run

```sh
uv run schwab-mcp serve
```

With an MCP client connected over stdio (or the MCP Inspector).

## Validation scenarios (map to the spec's SCs)

### S1 — Underlying filter includes options (SC-001/SC-002)

```json
{"name": "get_transaction_history",
 "arguments": {"start_date": "2025-10-24", "end_date": "2026-10-23",
               "symbol": "NOK"}}
```

Expected: `outcome=ok`; movements include **both** those registered
under `NOK` (if any) **and** option trades with root `NOK` (e.g.
`NOK   261218P00011000`), each with `"underlying_symbol": "NOK"`.
Completeness check: the union of the returned movements matches the NOK
subset of the unfiltered query of the same range (S3).

### S2 — Filter by complete OCC symbol (FR-001c / US1-AC4)

```json
{"name": "get_transaction_history",
 "arguments": {"start_date": "2025-10-24", "end_date": "2026-10-23",
               "symbol": "NOK   261218P00011000"}}
```

Expected: `outcome=ok` with exactly the movements of that option
(without the opaque `partial_failure` that the provider rejection
produces today). With a range with no activity of that option: `ok /
no_movements_for_instrument`.

### S3 — Subset consistency and case-insensitivity (SC-002)

1. Unfiltered query of the range → set `U`.
2. Query with `symbol="NOK"` → set `F1`.
3. Query with `symbol="nok"` (lowercase) → set `F2`.

Expected: `F1 == F2` and `F1 == {m ∈ U : m involves NOK}` (registered
symbol `NOK` or option root `NOK`). Script: filter `U` client-side with
the same rule and compare by `(account_hash, occurred_at, symbol)`.

### S4 — Dual validation (FR-003 / US1-AC5)

- Filter with a nonexistent symbol and no activity (e.g. `ZZZZZZ`) →
  `instrument_not_found` error naming the symbol (same as 006).
- Filter with a root not resolved in the directory but with movements
  that match (if one is identified; the `CURRENCY_USD` case is the
  documented example) → the movements are returned (`ok`), **not**
  `instrument_not_found`.

### S5 — Budgets (SC-004)

```sh
uv run pytest tests/performance/test_transactions_budgets.py -v
```

Expected: p95 latency ≤ 5 s; default page of 50 movements ≤ 16 KB **with
the worst case of 50 options** (all with `underlying_symbol`); extended
≤ 64 KB.

### S6 — No secrets

```sh
uv run pytest tests/unit/test_no_secrets_in_output.py -v
```

Expected: green — `underlying_symbol` carries only public instrument
identifiers; opaque `account_hash`; no tokens/secrets.

## Diagnostics

- If a filtered query returns `no_movements_for_instrument` but
  schwab.com shows activity of the underlying: verify the activity
  belongs to this period/account; options are matched by the registered
  OCC root — non-standard roots without an identifiable OCC encoding do
  not match (they appear in the unfiltered query).
- The filter no longer travels upstream: filtered response times should
  be comparable to the unfiltered query of the same range (same number
  of upcalls).