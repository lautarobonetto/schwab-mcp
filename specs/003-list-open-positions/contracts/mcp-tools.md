# Contract: MCP Tool `get_open_positions`

**Feature**: `003-list-open-positions` | **Date**: 2026-10-20
**Surface**: first tool registered by `schwab-mcp serve`
(FR-001, Q1 decision of the clarify: real MCP tool, not a CLI command).

## Invocation

```json
{
  "name": "get_open_positions",
  "arguments": {}
}
```

### Arguments (input schema)

| Field | Type | Default | Semantics |
|-------|------|---------|-----------|
| `extended` | bool | `false` | `false` (default): curated set only (compact). `true`: each position adds the `extended` object with the provider's full passthrough (FR-003a). The default NEVER includes extended fields. |

No other parameters in v1: the query always covers **all** linked
accounts (FR-004); there is no per-account filter (KISS).

## Result (structured output)

Exactly one JSON object per invocation (FR-002), schema in
[data-model.md §2](../data-model.md). Fields:

| Field | Type | Values |
|-------|------|--------|
| `outcome` | closed enum | `ok` · `partial_failure` · `transient_failure` · `reauth_required` |
| `positions` | array | `PositionEntry` entries; `[]` valid only with `outcome: "ok"` |
| `accounts_failed` | array \| absent | Only `partial_failure`: `[{account_hash, detail}]`, `detail ∈ {provider_error, transient}` |
| `retryable` | bool | `true` only when `outcome == "transient_failure"` |
| `detail` | closed enum | `data_received` · `no_positions` · `account_failed` · `provider_unreachable` · `reauth_needed` · `store_absent` · `store_corrupted` |
| `retrieved_at` | string ISO-8601 UTC | Moment the provider payload was retrieved |

### `PositionEntry` (curated set, FR-003)

```json
{
  "account_hash": "opaque-account-hash",
  "symbol": "SPY",
  "instrument_type": "EQUITY",
  "description": "SPDR S&P 500 ETF Trust",
  "quantity": 10.0,
  "average_price": 580.25,
  "market_value": 5910.0,
  "unrealized_pl": 107.5,
  "price_timestamp": "2026-10-20T14:03:11+00:00"
}
```

For `OPTION` the following are added (mandatory, never `null`):
`underlying_symbol`, `put_call` (`PUT`|`CALL`), `strike_price`,
`expiration_date`. With `extended=true`, each entry adds `"extended": {...}`
passthrough from the provider (opaque but stable keys; includes
`price_timestamp` at entry level all the same).

### Semantics of each outcome

- **`ok`** (`detail: data_received` | `no_positions`): complete query.
  `no_positions` with `positions: []` means "there are no
  holdings", not an error (FR-005/SC-006).
- **`partial_failure`** (`detail: account_failed`): some accounts
  responded, others did not (FR-010). `positions` carries the holdings of the
  successful accounts; `accounts_failed` identifies those that failed and why.
  The agent may decide to retry.
- **`transient_failure`** (`detail: provider_unreachable`, `retryable:
  true`): first attempt failed due to network/provider; **there are no
  internal retries** (FR-007). Retrying later is safe; nothing gets corrupted.
- **`reauth_required`** (`detail: reauth_needed` | `store_absent` |
  `store_corrupted`): same rules as the existing playbook — the
  agent must NOT retry; notify the owner for `schwab-mcp auth`
  and monitor with `auth-status` until `state: valid`.

### Price freshness (FR-012)

The price used by `market_value`/`unrealized_pl` is the one computed by
the provider when generating the payload: live during market
hours, last close outside them. `price_timestamp` /
`retrieved_at` mark when that payload was retrieved. The MCP does not
recompute or interpolate prices (research D4).

## Cross-cutting guarantees

- **Read-only**: the tool places no orders and moves no money; no persistent state of its own.
- **No secrets**: zero tokens/credentials/URLs in the result or in
  events (verified by test).
- **Pending orders out of scope** (FR-015): only effective holdings
  with signed quantity ≠ 0; zero quantities are omitted.
- **No aggregated strategies**: each contract is a separate entry
  (strangle/condor/roll = N entries); grouping is the consumer's job.

## Budgets (Constitution V)

- **Latency**: ≤ 5 s per invocation under normal network (SC-002); a single
  upstream call (`account_details_all(fields=positions)`).
- **Default payload**: ≤ 8 KB for 50 curated positions (~2 000 tokens).
- **Extended payload**: ≤ 16 KB for 50 positions. Growth of
  either requires recorded justification in the change.
- **Overage** (more than 50 positions or payload above the
  budget): the response is NEVER truncated nor are positions silently
  omitted (silent clipping would violate FR-001/FR-010: the
  agent would believe it has the complete picture). Deterministic strategy:
  the response grows and the budget test (T015) fails, which
  forces recorded justification (Constitution V) or an
  explicit pagination decision in a future feature. In v1 there is no
  pagination (KISS): portfolios above budget are a visible, measurable fact,
  not hidden behavior.
- Mandatory test: `tests/performance/test_positions_budgets.py`
  (marker `performance`).

## MCP Errors

Failures classified as above are returned as a **structured
result** (not as an MCP protocol error): the agent reads them and
decides. Only an unclassifiable internal failure propagates as an MCP error
with a message without secrets.