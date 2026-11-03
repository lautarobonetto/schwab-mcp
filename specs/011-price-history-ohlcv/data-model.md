# Data Model: Price History OHLCV (`get_price_history`) (011)

Feature: 011-price-history-ohlcv | Date: 2026-11-02
Entities, field mappings, and derivation rules for the price-history tool.
Normative contract details live in [contracts/mcp-tools.md](contracts/mcp-tools.md).

## Entities

### PriceHistoryRequest

One tool invocation.

| Attribute | Type | Rules |
|---|---|---|
| `symbol` | string | exactly one; normalized (strip whitespace, uppercase); must pass the equity/ETF or index grammar (D9) — option-contract symbols are rejected |
| `frequency` | enum | one of `5m`, `15m`, `30m`, `1h`, `daily`, `weekly` (clarification Q3); default `daily` |
| `period` | string | one named preset from the per-frequency table below (clarification Q4); default `1m`; no numeric or date-range values (FR-014, FR-018) |
| `extended_hours` | bool | default `false`; valid only for intraday frequencies (`5m`/`15m`/`30m`/`1h`), otherwise validation error (clarification Q1, D4) |
| `extended` | bool | default `false`; when `true`, adds the raw provider payload channel |

Lifecycle: pure value object — validated (fail before any upcall, FR-007),
used for one provider round trip, never persisted.

### Candle

The summarized market activity of one period at the requested frequency.

| Attribute | Type | Source | Rules |
|---|---|---|---|
| `t` | integer | provider `datetime` (normalized per D6/D7/D8) | epoch milliseconds; weekly labels = closing session (FR-019) |
| `o` | number | provider `open` | as delivered, no rounding (FR-012) |
| `h` | number | provider `high` | as delivered |
| `l` | number | provider `low` | as delivered |
| `c` | number | provider `close` | as delivered |
| `v` | integer \| null | provider `volume` | as delivered; `null` only if the source omits it |
| `in_progress` | bool | derived (D6) | `true` only for the current still-forming candle (FR-017) |

Out of scope (never present): computed indicators, averages, volatility
statistics, any derived value (FR-013); tick data (spec scope-out).

## Period presets × frequency matrix (D3, normative)

| Frequency | Provider call | Presets | Provider parameters per preset | Max candles |
|---|---|---|---|---|
| `5m` | minute × 5 | `1d`, `2d`, `3d` | `periodType="day"`, period 1/2/3 | 234 |
| `15m` | minute × 15 | `1d`, `2d`, `5d`, `10d` | `periodType="day"`, period 1/2/5/10 | 260 |
| `30m` | minute × 30 | `1d`, `2d`, `5d`, `10d` | `periodType="day"`, period 1/2/5/10 | 130 |
| `1h` | minute × 30, aggregated 2:1 | `1d`, `2d`, `5d`, `10d` | `periodType="day"`, period 1/2/5/10 | 65 (130 fetched) |
| `daily` | daily × 1 | `1m`, `3m`, `6m`, `1y`, `ytd` | `periodType="month"/"year"/"ytd"`, period 1/3/6/1/1 | 252 |
| `weekly` | weekly × 1 | `1m`, `3m`, `6m`, `1y`, `2y`, `3y`, `5y`, `ytd` | `periodType="month"/"year"/"ytd"`, period 1/3/6/1/2/3/5/1 | ≈ 260 |

Global ceiling: **260 candles** per invocation, enforced by construction —
every preset's worst case is at or below it, so no request can exceed the
ceiling (FR-004). Presets outside the table are validation errors, never
truncations.

## Aggregation rules (D2, normative)

### Hourly (`1h`) — derived from provider 30-minute candles

1. Fetch 30-minute candles for the requested day preset
   (`needExtendedHoursData` per the `extended_hours` flag).
2. Discard candles outside the regular session unless `extended_hours=true`.
3. Group consecutive 30-minute candles into hour buckets aligned to clock
   hours in the exchange timezone: a candle stamped at minute m belongs to
   the bucket `floor(m / 60)`.
4. Each bucket aggregates to one candle: `o` = first candle's `o`, `h` =
   max of `h`, `l` = min of `l`, `c` = last candle's `c`, `v` = sum of `v`,
   `t` = bucket end timestamp (end-labeling, consistent with weekly — D7).
5. A trailing bucket that has not reached a full hour at fetch time is still
   emitted (with its partial data) and marked `in_progress: true` (D6).

### Weekly — provider-native, label verified/normalized (D7)

Provider weekly candles are passed through; the fixture test pins the
provider's stamping convention. If the provider stamps at any point other
than the closing session, the mapping normalizes each label forward to the
last session of that ISO week (weekday arithmetic, no extra provider call)
so FR-019 holds deterministically.

## in_progress derivation (D6, normative)

- Injected `fetch_time` (epoch ms) — frozen in tests.
- A candle is `in_progress: true` iff `period_end(candle) > fetch_time`,
  where period end is: timestamp + frequency span for native intraday
  candles; hour-bucket end for `1h`; fixture-pinned session/week end for
  `daily`/`weekly` (D8).
- At most one candle per response can be `in_progress: true` (the last).

## State transitions

None — stateless passthrough. The only "state" is the forming candle's
in-progress marker, recomputed per invocation.

## Volume expectations

- Default invocation: ≈ 22 candles ≈ ≤ 650 tokens (measured 588).
- Worst-case preset: 260 candles ≈ ≤ 6,500 tokens (measured ~6.3k; asserted
  against the recorded fixture by token-usage tests).
- Per-candle cost ≈ 23–24 tokens measured. Research D5's 19–22 assumed no
  `in_progress` field; the field is required on every candle, so the
  measured value is authoritative (recorded in the implementing commit).
- The 260-candle ceiling is structural (ceiling by construction) and is
  not lowered to fit the original arithmetic.
- Provider fetch is bounded by the same preset table (worst fetch = 260
  native candles, or 130 for `1h`).
