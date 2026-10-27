# MCP tool contract: `get_transaction_history` (007 — underlying-aware filter)

Feature: 007-underlying-symbol-filter | Date: 2026-10-24
Base: `specs/006-transaction-history/contracts/mcp-tools.md` (the tool
exists; this contract documents **only the changes** of feature 007).
Everything not listed here (outcomes, detail, date validation errors,
pagination, guarantees, permissions caveat) remains in force from 006.

## 1. Input schema — extended semantics of `symbol`

Parameters: same names and types as 006 (`start_date`, `end_date`,
optional `symbol`, `extended`, `offset`). The **semantics** of the
filter change:

| Agent filter | 006 behavior | 007 behavior |
|---|---|---|
| `symbol: "NOK"` (underlying) | Only movements registered under `NOK` (NOK options **invisible**; if the account only traded NOK options, it returned `no_movements_for_instrument` — misleading) | Movements under `NOK` **+** movements of options with root `NOK` |
| `symbol: "NOK   261218P00011000"` (complete OCC) | Provider rejection (HTTP 400) exposed as an opaque `partial_failure` | Movements of **that specific option** |
| `symbol: "nok"` (lowercase) | Depends on upstream matching | Same result as `"NOK"` (case-insensitive matching) |
| `symbol: "ZZZZZZ"` (nonexistent) | `instrument_not_found` | `instrument_not_found` **only** if nothing matches either (dual validation — see §3) |
| `symbol: "CURRENCY_USD"` (internal) | `instrument_not_found` | Returns the tagged-cash movements with that symbol (if any) |

Exact matching, no fuzzy (M1 registered symbol · M2 option root ·
M3 complete OCC — see data-model §2). Case-insensitive comparison. The
output reports symbols as the source registers them.

## 2. Output schema — new field in `MovementEntry`

| Field | Type | Presence | Semantics |
|-------|------|----------|-----------|
| `underlying_symbol` | string \| absent | only option movements with identifiable OCC | Underlying of the option (root of the OCC symbol, unpadded). Absent for non-options and for options without an identifiable OCC encoding |

Example (`ok`, option movement, curated):

```json
{
  "account_hash": "8016D21F…",
  "occurred_at": "2026-08-27T13:31:07+0000",
  "category": "trade",
  "description": "",
  "amount": -3220.0,
  "currency": "USD",
  "symbol": "NOK   261218P00011000",
  "underlying_symbol": "NOK",
  "instrument_type": "OPTION"
}
```

The remaining fields and their presence stay identical to 006. The
field's presence is additive: existing consumers do not break (new
fields absent for non-options).

## 3. Dual filter validation (replaces 006's single validation)

1. Directory lookup (`instruments`, `symbol-search`) — 1 upcall,
   only if there is a filter (identical to 006).
2. Directory resolves → normal query.
3. Directory does NOT resolve → **does not fail**: the query proceeds
   anyway.
4. Final classification: there is a match (M1/M2/M3) → `ok`; no match →
   `instrument_not_found` naming the filter (actionable ToolError).

Documented consequence: `CURRENCY_USD` goes from error to results if
there are movements with that registered symbol.

## 4. Subset-consistency (contract invariant)

For the same `start_date`/`end_date` and `extended`, the filtered result
is exactly the subset of the unfiltered result whose movements match the
filter (M1∨M2∨M3) — same `total_count` of the subset, same ordering,
same pagination. Verifiable with the quickstart walk (S3).

## 5. Budgets

Unchanged from 006: ≤ 5 s p95; ≤ 16 KB default page of 50 movements
**including** `underlying_symbol`; ≤ 64 KB extended.
`docs/tools.md` must reflect the updated expected size.

## 6. Audit events

Unchanged: `transactions_query_start` + terminal
(`transactions_query_success` / `transactions_query_failure`) per
invocation, 006 vocabulary (see
`specs/006-transaction-history/contracts/events.md`). Dual validation
adds no events (the decision is captured by the corresponding terminal
event).

## 7. Read-only and secrets

Unchanged: read-only; opaque `account_hash`; no new field contains
account identifiers or credentials (`underlying_symbol` is a public
instrument identifier).