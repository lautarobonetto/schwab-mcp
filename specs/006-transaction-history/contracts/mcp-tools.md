# MCP Tool Contract: `get_transaction_history` (006)

Normative reference of the server's fourth MCP tool. Complements
`docs/tools.md` (which documents it for the agent). Data model:
[data-model.md](../data-model.md). Events: [events.md](events.md).

## Invocation

```json
{
  "name": "get_transaction_history",
  "arguments": {
    "start_date": "2026-09-01",
    "end_date": "2026-09-30"
  }
}
```

With instrument filter and pagination:

```json
{
  "name": "get_transaction_history",
  "arguments": {
    "start_date": "2026-01-01",
    "end_date": "2026-09-30",
    "symbol": "AAPL",
    "offset": 50
  }
}
```

## Arguments (input schema)

| Field | Type | Default | Semantics |
|-------|------|---------|-----------|
| `start_date` | string | mandatory | Range start date, `YYYY-MM-DD`. **Inclusive** boundary, interpreted in America/New_York. |
| `end_date` | string | mandatory | Range end date, `YYYY-MM-DD`. **Inclusive** boundary; cannot be in the future. |
| `symbol` | string \| absent | no filter | If present: only movements of that instrument. Validated against the provider before querying the history. |
| `extended` | bool | `false` | `false` (default): compact curated set. `true`: each movement adds `extended` with the provider passthrough (original type, full description, fees, netAmount, transferItems…). |
| `offset` | int | `0` | Pagination continuation: repeat the same query with the received `next_offset`. |

Maximum window: **1 year** (366 calendar days) between `start_date` and
`end_date` (clarify Q1). Larger ranges → validation error stating the
maximum and suggesting splitting the query.

## Output schema

Exactly one `TransactionsResult` object per invocation (see
[data-model.md](../data-model.md) for the full schema of
`MovementEntry`):

```json
{
  "outcome": "ok",
  "detail": "history_retrieved",
  "retryable": false,
  "retrieved_at": "2026-10-23T14:00:00+00:00",
  "total_count": 137,
  "returned": 50,
  "has_more": true,
  "next_offset": 50,
  "offset_echo": 0,
  "movements": [
    {
      "account_hash": "AB12CD34EF56GH78",
      "occurred_at": "2026-09-03T15:45:00-04:00",
      "category": "trade",
      "description": "You SOLD 10 shares of AAPL",
      "amount": -2318.9,
      "currency": "USD",
      "symbol": "AAPL",
      "instrument_type": "EQUITY"
    }
  ]
}
```

## Outcome and `detail` semantics

| Outcome | `detail` | Meaning for the agent |
|---------|----------|---------------------------|
| `ok` | `history_retrieved` | History retrieved; paginate with `next_offset` if `has_more`. |
| `ok` | `no_movements` | Valid range, no movements in any account. |
| `ok` | `no_movements_for_instrument` | Valid symbol, no movements of that instrument in the range. |
| `partial_failure` | `account_failed` | Some accounts failed (see `accounts_failed`); the data from the rest is valid. Consider retrying the full query. |
| `transient_failure` | `provider_unreachable` | Transient failure on the first attempt; no internal retries. Retrying later is safe. |
| `reauth_required` | `reauth_needed` | Same playbook as the other tools: do not retry; notify the owner (`schwab-mcp auth`). |

## Validation errors (standard MCP tool error, no upcalls)

| Condition | Expected message |
|-----------|------------------|
| `start_date`/`end_date` missing or malformed | States the expected `YYYY-MM-DD` format |
| `end_date < start_date` | Names both dates |
| Range > 366 days | States the 1-year maximum and suggests splitting into consecutive queries |
| Future `end_date` | States that the end date cannot be in the future |
| `symbol` present but non-existent/typo | `instrument_not_found`, names the symbol |
| `offset < 0` | States the minimum value |

Per-account errors (`accounts_failed[].detail`): `provider_error` ·
`transient` (same vocabulary as `get_open_positions`).

## Pagination

- Deterministic order: `occurred_at` ascending; tie-break by
  `account_hash` and `activityId`.
- Page: at most **50** movements (clarify Q4). `has_more=true` always
  accompanies `next_offset`; the last page carries no `next_offset`.
- Complete walk (SC-006): zero duplicates, zero omissions over the
  query snapshot.
- Caveat: the tool is stateless; if new movements arrive between
  pages, the offset may shift. Paginate soon.

## Upcalls

| Step | Call | When |
|------|---------|--------|
| 1 | `linked_accounts()` | Always (1 call) |
| 2 | `instruments(..., symbol-search)` | Only if `symbol` present (1 call) |
| 3 | `transactions(accountHash, startDate, endDate, types=<all>, symbol?)` | 1 per account; +bisection only if a response arrives at the 3000 cap (research D3) |

## Guarantees

- **Read-only**: places no orders and moves no money.
- **No secrets**: no token/credential in outputs or events;
  opaque `account_hash`, never the account number.
- **Budget**: ≤ 5 s p95 latency (SC-001); ≤ 16 KB default page
  (50 movements, SC-003); ≤ 64 KB extended (declared).
- **No silent truncation**: upstream cap of 3000 handled with split
  by bisection and deduplication by `(account_hash, activityId)`.
- **No internal retries** on transient failure: the agent decides
  (FR-010).

## Operational caveat (documented, not a tool error)

The provider may return `200 OK + []` for `/transactions` when the
registered app or the account lacks transaction read permission
(e.g. account without thinkorswim enabled; evidence regress#125). From
the response it is indistinguishable from a genuine empty: the tool
reports `ok / no_movements`. Suggested diagnosis for the agent: if the
account shows activity on schwab.com and several wide ranges
persistently return `no_movements`, the likely cause is the app/account
permission — not data.