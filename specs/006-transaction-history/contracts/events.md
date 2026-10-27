# Audit Events Contract: `get_transaction_history` (006)

Channel: stderr via `log.auth_event` (reused from 002/003, with the
redaction filter active). No event contains tokens, secrets, account
numbers or authorization URLs. Line format identical to the existing
one:

```text
2026-10-23T14:00:00Z+00:00 auth_event=<event> outcome=<outcome> detail=<detail>
```

## Events per invocation

Each invocation emits **exactly one terminal event** (pattern of
`get_open_positions` in 003): `transactions_query_success` for
ok/partial results, `transactions_query_failure` for failures.

| Event | Outcome | Detail | When |
|--------|---------|--------|--------|
| `transactions_query_success` | `ok` | `history_retrieved` · `no_movements` · `no_movements_for_instrument` | All accounts responded |
| `transactions_query_success` | `partial_failure` | `account_failed` | ≥ 1 account failed, the rest responded |
| `transactions_query_failure` | `transient` | `provider_unreachable` | Transient failure on the first attempt (no internal retries) |
| `transactions_query_failure` | `reauth` | `reauth_needed` | Missing/corrupt store or rejected refresh (already emitted by the error handler, not duplicated) |
| `transactions_query_failure` | `validation` | `invalid_query` | Request validation error (FR-004) — emitted for auditability even though the tool responds with a standard MCP error |

## Rules

- **`detail` namespace**: the `detail` field of the **events** is a
  namespace of its own for this contract (`history_retrieved`,
  `no_movements`, `no_movements_for_instrument`, `account_failed`,
  `provider_unreachable`, `reauth_needed`, `invalid_query`) and is NOT
  the `TransactionDetail` enum of the data model: event values describe
  the audit cause, not the tool result (e.g. a failed validation emits
  `outcome=validation, detail=invalid_query` on stderr, while the tool
  responds with a standard MCP error).
- A success event is never emitted before the result is known.
- The validation event is emitted only once per invocation.
- The `detail` values are closed values of this contract; any free
  text coming from the provider is redacted by the existing filter.