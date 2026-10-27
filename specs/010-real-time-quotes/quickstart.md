# Quickstart: `get_quotes` (010)

Feature: 010-real-time-quotes | Date: 2026-10-27
Validation scenarios proving the quotes tool end to end. Contracts:
[contracts/mcp-tools.md](contracts/mcp-tools.md) · data rules:
[data-model.md](data-model.md).

## Prerequisites

- Environment set up: `uv sync`
- Authenticated: `uv run schwab-mcp auth-status` reports authorized
  (first-time: `uv run schwab-mcp auth`)
- Server running: `uv run schwab-mcp serve` (stdio MCP)
- Automated suite green: `uv run pytest` (commit gate: green, 0 skipped)

## S1 — Single-symbol curated quote (spec US1)

Invoke the MCP tool:

```json
{"name": "get_quotes", "arguments": {"symbols": "AAPL"}}
```

Expected:

- `outcome` = `ok`, `requested_count` = 1
- `quotes.AAPL` carries every field declared in `quote_fields` (last, bid,
  ask, volume, net_change, net_change_pct, data_state, trade_time)
- `data_state` ∈ {`realtime`, `delayed`, `closed`} and is consistent with
  the market being open or closed for the request time
- The whole response stays within the ≤ 250-token budget (verified
  automatically by `tests/performance/test_quotes_budgets.py`)

## S2 — Batch portfolio price check (spec US2)

```json
{"name": "get_quotes",
 "arguments": {"symbols": ["AAPL", "NOK", "$SPX", "AAPL 251127C200"]}}
```

Expected:

- One invocation, `outcome` = `ok`, `requested_count` = 4
- `quotes` is keyed by symbol with exactly one entry per requested symbol —
  including the index symbol and the option-contract symbol
- Option-contract prices carry 4 decimals; equity prices 2 decimals
- Latency ≤ 5 s; payload grows linearly (≤ 2,500 tokens at 10 symbols)

## S3 — Extended raw payload (spec US3)

```json
{"name": "get_quotes",
 "arguments": {"symbols": "AAPL", "extended": true}}
```

Expected:

- Curated `quotes` object present **and** `provider` with the complete raw
  source payload for `AAPL` (keyed by symbol, uncensored fields such as
  day high/low and open price)
- The curated portion alone still respects the token budget

## S4 — Failure attribution (spec FR-005/FR-006/FR-007)

Each invocation below must return a structured error (no partial quotes):

| Invoke with | Expected outcome |
|---|---|
| `{"symbols": []}` | `validation_error` / `empty_symbol_list` |
| `{"symbols": ["AAPL", "ZOMB", "BAD SYMBOL"]}` | validation error naming `BAD SYMBOL` as `malformed_symbol` **before any fetch**; if `ZOMB` is not quoted by the source, `quote_unavailable` with `errors.ZOMB = "not_found"` and no partial `quotes` object |
| 21 distinct valid symbols | `validation_error` / `too_many_symbols` stating the 20-symbol limit |
| `{"symbols": ["ZOMB"]}` (unknown but well-formed) | `quote_unavailable`, `errors.ZOMB = "not_found"` |

With the server running, also verify the retryable path: stop network
access and invoke the tool — expect `provider_unreachable` (retryable),
never a hang beyond the 5 s budget.

## S5 — Automated validation (definition of done)

```sh
uv run pytest tests/unit/test_quotes_validation.py \
              tests/unit/test_quotes_mapping.py \
              tests/unit/test_quotes_data_state.py
uv run pytest tests/integration/test_quotes.py
uv run pytest tests/performance/test_quotes_budgets.py
```

Expected: all green (written test-first per the constitution). The
performance module pins the token budgets (SC-002) and the ≤ 5 s p95
latency budget (SC-001); the integration module covers the S1–S4 flows with
fake clients plus one live-validation pass against a real symbol (fixture +
live pattern of 008).

## Success mapping

| Scenario | Spec coverage |
|---|---|
| S1 | US1, SC-001, SC-002, SC-003 |
| S2 | US2, SC-004 (limit paths), SC-005 |
| S3 | US3, SC-006 |
| S4 | FR-005/FR-006/FR-007, SC-004 |
| S5 | All SCs (automated gate) |