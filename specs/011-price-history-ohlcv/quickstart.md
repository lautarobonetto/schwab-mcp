# Quickstart: `get_price_history` (011)

Feature: 011-price-history-ohlcv | Date: 2026-11-02
Validation scenarios proving the price-history tool end to end. Contracts:
[contracts/mcp-tools.md](contracts/mcp-tools.md) · data rules:
[data-model.md](data-model.md).

## Prerequisites

- Environment set up: `uv sync`
- Authenticated: `uv run schwab-mcp auth-status` reports authorized
  (first-time: `uv run schwab-mcp auth`)
- Server running: `uv run schwab-mcp serve` (stdio MCP)
- Automated suite green: `uv run pytest` (commit gate: green, 0 skipped)

## S1 — Default daily window, one symbol (spec US1)

Invoke the MCP tool:

```json
{"name": "get_price_history", "arguments": {"symbol": "SPY"}}
```

Expected:

- `outcome` = `ok`, `frequency` = `daily`, `period` = `1m`
- `candles` is chronological (oldest first) with ≈ 20–23 entries; each
  carries `t`, `o`, `h`, `l`, `c`, `v` (and `in_progress` on every candle,
  `true` at most on the last)
- `candle_count` matches `len(candles)`; `window.first`/`window.last` match
  the first/last `t`
- The whole response stays within the ≤ ~550-token budget (verified
  automatically by `tests/performance/test_price_history_budgets.py`)

## S2 — Bounded selection for a different horizon (spec US2)

```json
{"name": "get_price_history",
 "arguments": {"symbol": "AAPL", "frequency": "weekly", "period": "5y"}}
```

Expected:

- ≈ 260 or fewer weekly candles; each `t` is the closing session's
  timestamp (weekday Friday or the last trading session of that week)
- No response for any valid preset ever exceeds 260 candles

## S3 — Intraday with extended hours opt-in (clarification Q1)

```json
{"name": "get_price_history",
 "arguments": {"symbol": "AAPL", "frequency": "30m", "period": "5d",
               "extended_hours": true}}
```

Expected:

- 30-minute candles covering the requested days, including pre/post-market
  sessions (more candles per day than the regular-session default)
- Repeating the call with `"extended_hours": false` yields strictly fewer
  or equal candles, regular sessions only

## S4 — Forming candle marked in-progress (clarification Q2, FR-017)

While the market is open, request the daily default:

Expected:

- The last candle's `in_progress` is `true` and its `t`/values reflect the
  partial session; all earlier candles have `in_progress` = `false`
- After the session closes, the same request marks every candle
  `in_progress` = `false`

## S5 — Validation and unavailability (spec FR-007/FR-008)

```json
{"name": "get_price_history",
 "arguments": {"symbol": "AAPL 261127C350"}}
{"name": "get_price_history",
 "arguments": {"symbol": "AAPL", "frequency": "daily", "period": "10y"}}
{"name": "get_price_history",
 "arguments": {"symbol": "AAPL", "frequency": "daily", "period": "1m",
               "extended_hours": true}}
```

Expected (each, before any provider call):

1. `validation_error` / `unsupported_symbol_kind`
2. `validation_error` / `unsupported_period` (daily presets cap at `1y`)
3. `validation_error` / `extended_hours_not_applicable`

For a symbol with no price history (e.g., a recently delisted ticker):

- `history_unavailable` / `source_returned_no_candles`, no `candles` array

## S6 — Extended passthrough (spec US3, SC-006)

```json
{"name": "get_price_history",
 "arguments": {"symbol": "SPY", "extended": true}}
```

Expected:

- The response carries `provider` — the complete raw source payload for the
  request — alongside the curated `candles` array

## Budget assertions (automated)

`tests/performance/test_price_history_budgets.py` asserts, against the
recorded fixture payloads (`tests/unit/fixtures/price_history_payloads.py`):

- Default response ≤ ~550 tokens; worst-case preset (260 candles) ≤ ~5,200
  tokens; per-candle baseline ≈ 19–22 tokens (research D5)
- Latency ≤ 5 s p95 with a fake client
