# MCP Tool Contract: `get_price_history` (011)

Feature: 011-price-history-ohlcv | Date: 2026-11-02
Read-only tool. Does not move money or place orders. Transport: stdio
exclusively via `schwab-mcp serve`.

## 1. Input schema

| Parameter | Type | Default | Constraints |
|---|---|---|---|
| `symbol` | string | — (mandatory) | exactly one; normalized (strip + uppercase); must match the equity/ETF or index grammar below |
| `frequency` | string | `"daily"` | one of `5m`, `15m`, `30m`, `1h`, `daily`, `weekly` |
| `period` | string | `"1m"` | one named preset valid for the chosen frequency (table below) |
| `extended_hours` | bool | `false` | only valid for intraday frequencies (`5m`/`15m`/`30m`/`1h`) |
| `extended` | bool | `false` | when `true`, adds the raw provider payload channel |

### Symbol grammar (normative, normalized uppercase)

| Kind | Grammar | Examples |
|---|---|---|
| Equity/ETF | `[A-Z0-9]{1,6}` with at most one embedded `.` | `AAPL`, `NOK`, `BRK.B` |
| Index | `\$[A-Z0-9]{1,5}` | `$SPX`, `$VIX` |

Class-share equities (embedded `.`) are rewritten to the provider's
**slash form** at the upcall (`BRK.B` → `BRK/B`; live probe
2026-11-02: the dotted form returns `not_found` / empty candles).  The
request/echo/error envelopes keep the dotted agent-facing form.

Option-contract symbols are rejected at validation
(`unsupported_symbol_kind`): the provider price-history endpoint serves
underlyings, not option contracts (research D9).

### Period presets × frequency (normative; clarification Q4, research D3)

| Frequency | Valid presets | Provider mapping |
|---|---|---|
| `5m` | `1d`, `2d`, `3d` | `periodType="day"`, period 1/2/3, frequency 5 |
| `15m` | `1d`, `2d`, `5d`, `10d` | `periodType="day"`, period 1/2/5/10, frequency 15 |
| `30m` | `1d`, `2d`, `5d`, `10d` | `periodType="day"`, period 1/2/5/10, frequency 30 |
| `1h` | `1d`, `2d`, `5d`, `10d` | 30-minute fetch aggregated 2:1 (research D2) |
| `daily` | `1m`, `3m`, `6m`, `1y`, `ytd` | `frequencyType="daily"`; month 1/3/6, year 1, ytd 1 |
| `weekly` | `1m`, `3m`, `6m`, `1y`, `2y`, `3y`, `5y`, `ytd` | `frequencyType="weekly"`; month 1/3/6, year 1/2/3/5, ytd 1 |

Global ceiling: **260 candles** per invocation — enforced by construction
(every preset's worst case is at or below it); there is no truncation path
(FR-004). Defaults: `frequency="daily"`, `period="1m"` (FR-002).

Validation errors (before any upcall, FR-007): symbol missing or matching no
grammar (`malformed_symbol`), option-contract symbol
(`unsupported_symbol_kind`), frequency outside the set
(`unsupported_frequency`), period outside the frequency's preset table
(`unsupported_period`), `extended_hours=true` on a non-intraday frequency
(`extended_hours_not_applicable`).

## 2. Output schema (`ok`)

```json
{
  "outcome": "ok",
  "detail": "price_history_retrieved",
  "symbol": "SPY",
  "frequency": "daily",
  "period": "1m",
  "extended_hours": false,
  "extended": false,
  "candle_count": 22,
  "window": {
    "first": 1730419200000,
    "last": 1732742400000
  },
  "candles": [
    {"t": 1730419200000, "o": 566.02, "h": 568.51, "l": 565.11, "c": 568.18, "v": 41234567, "in_progress": false},
    {"t": 1732742400000, "o": 584.10, "h": 585.67, "l": 584.02, "c": 585.45, "v": 35412300, "in_progress": true}
  ]
}
```

Conventions:

- `candles` is a **chronological array** (oldest first), one entry per
  trading session/bucket actually delivered by the source; gaps
  (holidays, halts) are not interpolated (FR-005, edge cases).
- `t` is epoch milliseconds. For weekly candles it is the **closing
  session's** timestamp (clarification Q5, FR-019). For aggregated `1h`
  candles it is the hour-bucket end (end-labeling, research D2/D7).
- OHLC values are **as delivered by the source** — no rounding, no
  adjustment (FR-012, research D9). `v` is `null` only when the source
  omits it.
- `in_progress` is `true` only on the current still-forming candle
  (clarification Q2, FR-017); at most one candle per response carries it.
- `window.first` / `window.last` and `candle_count` state the covered span
  so the agent can judge coverage without counting (FR-015, SC-005).
- `frequency`/`period` echo the effective selection (defaults included).
- `extended=true`: the success response additionally carries `provider` —
  the complete raw source payload for the request, without curation
  (SC-006). The curated `candles` array remains present in the same
  response. For `1h`, the raw channel carries the underlying 30-minute
  provider payload (research D2).

## 3. Error responses

No partial data (FR-008): if the source fails or returns no candles, the
invocation returns a structured error and the `candles` array is absent.

| `outcome` | `detail` | Trigger | Retryable |
|---|---|---|---|
| `validation_error` | `malformed_symbol` | symbol missing or matches no grammar | no |
| `validation_error` | `unsupported_symbol_kind` | option-contract symbol | no |
| `validation_error` | `unsupported_frequency` | frequency outside the declared set; carries `valid_frequencies` | no |
| `validation_error` | `unsupported_period` | period not in the frequency's preset table; carries `valid_presets` | no |
| `validation_error` | `extended_hours_not_applicable` | `extended_hours=true` with `daily`/`weekly` | no |
| `history_unavailable` | `source_returned_no_candles` | source returned an empty candle list for a valid request (e.g., unlisted or delisted instrument) | no (re-request is valid) |
| `provider_unreachable` | transport/timeout description | source unreachable, 5xx/408/429, malformed body | **yes** |
| `reauth_needed` | re-authorization required | provider 401/403 | no (user action) |

- Every error envelope carries the requested (normalized) `symbol`
  (FR-008, US1-AC3); `unsupported_frequency` states the declared set in
  `valid_frequencies`, and `unsupported_period` states the frequency's
  presets in `valid_presets` — the limit and the allowed values before
  any fetch (US2-AC2).
- The response envelope (outcome/detail/retryability semantics) is the one
  shared by `get_open_positions`, `get_transaction_history`,
  `get_option_chain`, and `get_quotes` (FR-009, C-02).
- Fewer candles than the preset implies (halts, short history) is **not** an
  error: the response reports what the source delivered (edge cases).

## 4. Provider interaction (normative summary)

1. Validate input (fail before any upcall; preset table lookup, no
   arithmetic).
2. One `price_history()` call via the shared retry wrapper, with parameters
   from the preset table; `needExtendedHoursData` = the `extended_hours`
   flag (research D1/D4). For `1h`, the call requests 30-minute candles.
3. Unwrap with the shared `response_json` helper; classify errors with the
   shared taxonomy.
4. Curate: chronological array, `in_progress` derivation (research D6),
   weekly label verification/normalization (research D7), `window` and
   `candle_count` metadata.
5. Hourly aggregation (only for `1h`): pure function over the fetched
   30-minute candles per the data-model rules.

## 5. Budgets (Principle V)

| Budget | Target | Verified by |
|---|---|---|
| Latency | ≤ 5 s p95 per invocation (one provider call) | `tests/performance/test_price_history_budgets.py` |
| Default response | ≤ ~650 tokens (22 daily candles; measured 588) | token-usage tests against the recorded fixture |
| Worst-case response | ≤ ~6,500 tokens (260 candles; ceiling-by-construction; measured ~6.3k) | token-usage tests against the recorded fixture |
| Per-candle baseline | ≈ 23–24 tokens measured (research D5's 19–22 assumed no `in_progress` field on every candle) | asserted via the fixture; the 260-candle ceiling is structural and unchanged |

## 6. Audit events

`price_history_query_start` / `price_history_query_failure` /
`price_history_query_success`, mirroring the quotes tool's event pattern
(symbol and selection are logged; no credentials, FR-011).
