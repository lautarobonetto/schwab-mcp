# MCP Tool Contract: `get_quotes` (010)

Feature: 010-real-time-quotes | Date: 2026-10-27
Read-only tool. Does not move money or place orders. Transport: stdio
exclusively via `schwab-mcp serve`.

## 1. Input schema

| Parameter | Type | Default | Constraints |
|---|---|---|---|
| `symbols` | string \| list[string] | — (mandatory) | 1..20 distinct after normalization (strip + uppercase + de-duplicate); each entry matches one of the three kind grammars below |
| `extended` | bool | `false` | when `true`, adds the raw provider payload channel |

A single string is accepted as a one-symbol convenience and normalized to a
list (the tool surface remains one tool for 1..N — FR-001).

### Symbol-kind grammars (normative, normalized uppercase)

| Kind | Grammar | Examples |
|---|---|---|
| Index | `\$[A-Z0-9]{1,5}` | `$SPX`, `$VIX`, `$DJI` |
| Option contract | `[A-Z0-9.]{1,6}([ _])?(YYMMDD)(C\|P)([0-9]+(\.[0-9]+)?)` | `AAPL 261127C350`, `AAPL_261127P350.5` |
| Equity/ETF | `[A-Z0-9]{1,6}` with at most one embedded `.` | `AAPL`, `NOK`, `BRK.B` |

Validation errors (before any upcall, FR-005/FR-007/FR-013): empty symbol
list, a symbol matching none of the grammars (`errors[symbol] =
"malformed_symbol"`), distinct count > 20 (structured error stating the
limit). At exactly 20 distinct symbols the request proceeds (edge case).

## 2. Output schema (`ok`)

```json
{
  "outcome": "ok",
  "detail": "quotes_retrieved",
  "requested_count": 2,
  "extended": false,
  "quote_fields": [
    "symbol", "description", "last", "bid", "ask",
    "volume", "net_change", "net_change_pct",
    "data_state", "trade_time"
  ],
  "quotes": {
    "AAPL": {
      "symbol": "AAPL",
      "description": "Apple Inc. - Common Shs",
      "last": 251.31,
      "bid": 251.30,
      "ask": 251.32,
      "volume": 52100433,
      "net_change": 1.02,
      "net_change_pct": 0.41,
      "data_state": "realtime",
      "trade_time": "2026-10-27T15:04:05+00:00"
    },
    "$SPX": {
      "symbol": "$SPX",
      "description": "S&P 500 Index",
      "last": 6915.25,
      "bid": null,
      "ask": null,
      "volume": null,
      "net_change": 12.4,
      "net_change_pct": 0.18,
      "data_state": "closed",
      "trade_time": "2026-10-27T20:00:00+00:00"
    }
  }
}
```

Conventions:

- `quotes` is an **object keyed by symbol** (clarification Q3): exactly one
  entry per distinct requested symbol; on success every requested symbol is
  present.
- `null` = not reported by the source (FR-012); the tool never defaults,
  substitutes, or interpolates.
- Rounding: equity/ETF/index prices 2 decimals; option-contract prices 4
  decimals; `net_change_pct` 2 decimals.
- `data_state` is always present with `trade_time` (FR-003, SC-003):
  - `realtime` — live quote, market open for the symbol's session
  - `delayed` — delayed/indicative feed, market open
  - `closed` — last available quote, market closed for the symbol's session
- `requested_count` = distinct symbols after normalization and
  de-duplication (duplicates are de-duplicated, edge case).
- `extended=true`: success response additionally carries `provider` — the
  complete raw source payload (requested with `fields=all`, research D2)
  keyed by symbol, without curation (SC-006). The curated `quotes` object
  remains present in the same response.

## 3. Error responses

No partial data (FR-006): if any requested symbol cannot be quoted, or the
source fails, the invocation returns a structured error and the `quotes`
object is absent. Per-symbol attribution uses `errors` keyed by symbol.

| `outcome` | `detail` | Trigger | Retryable |
|---|---|---|---|
| `validation_error` | `empty_symbol_list` | `symbols` empty or missing | no |
| `validation_error` | `too_many_symbols` | distinct count > 20 | no |
| `validation_error` | `malformed_symbol` | a symbol matches no grammar; `errors` names it | no |
| `quote_unavailable` | `source_could_not_quote_all_symbols` | provider response omits requested symbols; `errors[symbol] = "not_found"` | no (re-request is valid) |
| `provider_unreachable` | transport/timeout description | source unreachable, 5xx/408/429, malformed body, or market-hours call failure | **yes** |
| `reauth_needed` | re-authorization required | provider 401/403 | no (user action) |

- Expired or not-quoted option contracts surface as `quote_unavailable` /
  `not_found` for that symbol (edge case) — never a fabricated quote.
- Market-hours call failure → `provider_unreachable` (retryable): freshness
  is deterministic or absent (research D4).
- The response envelope (outcome/detail/retryability semantics) is the one
  shared by `get_open_positions`, `get_transaction_history`, and
  `get_option_chain` (FR-008, C-02).

## 4. Provider interaction (normative summary)

1. Validate input (fail before any upcall).
2. One market-hours call per invocation (research D4) — determines the
   open/closed component of `data_state`.
3. One `quotes()` call via the shared retry wrapper:
   - curated mode: `fields="quote"`, `indicative=false`
   - extended mode: `fields="all"`, `indicative=false`
4. Unwrap with the shared `response_json` helper; classify errors with the
   shared taxonomy.

Unknown provider symbols are detected as requested-distinct minus response
keys (research D3) and reported per-symbol as `not_found`.

## 5. Budgets (Principle V)

- **Tokens**: ≤ 250 tokens for a single curated quote; ≤ 2,500 tokens for a
  10-symbol batch (≈ ≤ 5,000 worst case at 20 symbols). Enforced by
  `tests/performance/test_quotes_budgets.py`.
- **Latency**: ≤ 5 s p95 per invocation at 20 symbols (two provider calls).
  Enforced by the same module.
- Extended mode payloads are not budget-capped (raw channel, explicitly
  requested); the curated portion remains within budget.

## 6. Audit events

`quotes_query_start` (initiated) → on failure
`quotes_query_failure` classified `validation` / `error` / `reauth` /
`provider_unreachable` (pattern of `options_chain_query_*`). No credentials,
tokens, or account identifiers in events or outputs (FR-010).

## 7. Documentation obligations (implementing commit)

`docs/tools.md` gains a `get_quotes` section (fourth MCP tool) and
`docs/CHANGELOG.md` records the addition, in the same commit as the code.