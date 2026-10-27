# Data Model: Real-Time Quotes (`get_quotes`) (010)

Feature: 010-real-time-quotes | Date: 2026-10-27
Entities, field mappings, and derivation rules for the quotes tool.
Normative contract details live in [contracts/mcp-tools.md](contracts/mcp-tools.md).

## Entities

### QuoteRequest

One tool invocation.

| Attribute | Type | Rules |
|---|---|---|
| `symbols` | list[string] | 1..20 distinct after normalization (strip whitespace, uppercase, de-duplicate); each entry must pass the symbol-kind grammar (D5) |
| `extended` | bool | default `false`; when `true`, adds the raw provider payload channel |

Lifecycle: pure value object — validated (fail before any upcall, FR-005),
used for one provider round trip, never persisted.

### Quote

The current market state of one instrument (all three accepted kinds).

| Attribute | Type | Source (D6 mapping) | Rules |
|---|---|---|---|
| `symbol` | string | `symbol` | normalized as requested |
| `description` | string | `description` | truncated to 80 chars |
| `last` | number | `lastPrice` | 2 decimals (4 for option symbols) |
| `bid` | number \| null | `bidPrice` | `null` = not reported (FR-012) |
| `ask` | number \| null | `askPrice` | `null` = not reported (FR-012) |
| `volume` | integer \| null | `totalVolume` | as reported |
| `net_change` | number \| null | `netPriceChange` | same rounding as `last` |
| `net_change_pct` | number \| null | computed `net_change / closePrice × 100` | `null` when `closePrice` missing or 0; 2 decimals |
| `data_state` | enum | `quoteType` + market-hours check (D4) | `realtime` \| `delayed` \| `closed` |
| `trade_time` | ISO 8601 UTC string \| null | `tradeTime` | exact last-trade time |

Out of scope (never present): order-book depth, historical price series,
fundamentals (C-08 — `fmp` territory).

### Symbol kinds (FR-013)

| Kind | Grammar (normalized uppercase) | Curated-field differences |
|---|---|---|
| Equity/ETF | `[A-Z0-9]{1,6}` with at most one embedded `.` | base mapping |
| Index | `$` + `[A-Z0-9]{1,5}` | base mapping |
| Option contract | root + optional separator (` ` or `_`) + OCC tail `YYMMDD [CP] strike` (strike ≥ 1 digit, optional decimal point) | price rounding 4 decimals |

## data_state derivation (D4, normative)

```text
market_hours(regular session) == closed        → "closed"
quoteType == "Realtime"                        → "realtime"
quoteType missing/other (e.g., "Indicated")    → "delayed"
```

- The market-hours check runs once per invocation (not per symbol): all
  three kinds trade on the same regular session.
- Failure of the market-hours call → structured retryable error
  (freshness is never guessed).
- Every returned quote carries `data_state` and `trade_time` (SC-003).

## Response envelopes (FR-008)

### Success (`outcome: "ok"`)

```json
{
  "outcome": "ok",
  "detail": "quotes_retrieved",
  "requested_count": 2,
  "extended": false,
  "quote_fields": ["symbol", "description", "last", "bid", "ask",
                    "volume", "net_change", "net_change_pct",
                    "data_state", "trade_time"],
  "quotes": {
    "AAPL": { "symbol": "AAPL", "description": "Apple Inc. - Common Shs",
              "last": 251.31, "bid": 251.30, "ask": 251.32, "volume": 52100433,
              "net_change": 1.02, "net_change_pct": 0.41,
              "data_state": "realtime",
              "trade_time": "2026-10-27T15:04:05+00:00" },
    "AAPL 251127C200": { "...": "quote with 4-decimal prices" }
  }
}
```

- `quotes` is an object keyed by symbol (clarification Q3): one entry per
  distinct requested symbol, every requested symbol present on success.
- `quote_fields` declares the curated schema (pattern of 008).

### Error (any symbol missing, source failure, or validation failure)

```json
{
  "outcome": "quote_unavailable",
  "detail": "source_could_not_quote_all_symbols",
  "requested_count": 3,
  "errors": {
    "BAD SYMBOL": "malformed_symbol",
    "ZOMB": "not_found",
    "$BAD$": "malformed_symbol"
  }
}
```

- No partial data: the `quotes` object is absent when any requested symbol
  lacks a quote (FR-006); per-symbol attribution is carried by `errors`
  keyed by symbol (clarification Q3).
- Per-symbol reasons include: `not_found` (provider omitted the symbol),
  `malformed_symbol` (validation, names the symbol), provider transport
  failures surface as invocation-level retryable errors (`provider_unreachable`,
  `reauth_needed`), consistent with the shared error taxonomy.
- Validation failures (empty list, > 20 distinct symbols, malformed symbol)
  occur before any upcall (FR-005/FR-007).

### Extended mode (`extended: true`)

Success response additionally carries `"provider"`: the complete raw
`/marketdata/v1/quotes` payload (requested with `fields="all"`, D2) keyed by
symbol, without curation (SC-006). The curated `quotes` object remains
present; both channels are reachable in one invocation.

## Validation rules summary (FR-005/FR-007/FR-013)

1. `symbols` present, non-empty list → else `validation_error` (empty list).
2. Each symbol matches one of the three kind grammars → else
   `errors[symbol] = "malformed_symbol"`.
3. Distinct count ≤ 20 (after normalization + de-duplication) → else
   `validation_error` stating the limit (FR-007).
4. At the exact limit → succeeds (edge case).

## State transitions

None — the feature is a stateless read-only passthrough. The only
state-bearing value is `data_state`, derived (not stored) per invocation.