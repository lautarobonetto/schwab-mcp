# Feature Specification: Price History OHLCV (`get_price_history`)

**Feature Branch**: `011-price-history-ohlcv`

**Created**: 2026-11-02

**Status**: Draft

**Input**: User description: "011 — Price history OHLCV (`get_price_history`),
from the spec roadmap [status: planned]: MCP tool wrapping the provider's
price-history capability with bounded period/frequency selection — OHLCV
candles for technical analysis, historical volatility, trends, and
backtesting. Outcome: the agent can run technical and volatility analysis
from a single deterministic call. Scope in: period/frequency parameters with
hard defaults and ceilings that bound payload; volume included; `extended`
passthrough. Scope out: indicator computation (agent-side or a later derived
spec); intraday tick data beyond what the source exposes. Unbounded candle
windows are a context hazard — the default must be small and every ceiling
test-enforced."

## Clarifications

### Session 2026-11-02

- Q: When the tool returns intraday (minute-based) candles, should they cover
  only the regular trading session, or also include pre-market and
  after-hours activity? → A: **regular session by default, with an explicit
  opt-in flag for extended hours** — the declared candle ceilings apply
  regardless of the flag.
- Q: Should the candle series include the current, still-forming session's
  candle (for example, today's daily candle while the market is still
  open)? → A: **include it, explicitly marked as in-progress** — never
  indistinguishable from completed candles.
- Q: Which intraday (minute-based) candle granularities should the tool
  expose? → A: **the declared frequency set is exactly: 5-minute,
  15-minute, 30-minute, hourly, daily, and weekly** — no 1-minute and no
  monthly frequency.
- Q: How should the agent express the period (how far back the series
  reaches) for a request? → A: **named period presets only** (for example,
  day / week / month / year / year-to-date), with the allowed presets
  bounded per frequency — no free-form numeric or date-range period input.
- Q: For candles that summarize a multi-day span, which timestamp should
  label a weekly candle? → A: **the timestamp of the week's last (closing)
  session** — so candle spans align naturally with dated events such as
  earnings dates and option expirations.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Recent daily candles for one symbol in one call (Priority: P1)

An AI agent analyzing a position needs the recent price behavior of an
underlying — for example, to judge whether a stock is trending or range-bound
before proposing an option strategy, or to estimate recent volatility. Today
the agent has no way to obtain historical prices through this MCP at all. The
agent invokes the price-history tool with just the symbol and receives a
compact series of recent daily candles — timestamp, open, high, low, close,
and volume for each trading day — small enough to read at a glance and reason
over directly. One invocation, no follow-up calls, no external data source.

**Why this priority**: this is the core roadmap outcome — technical and
volatility analysis from a single deterministic call. The default window is
deliberately small because unbounded candle windows are a known context
hazard; a small default alone delivers the most common analysis need.

**Independent Test**: invoke the tool with one valid symbol and no other
parameters; verify the response contains a bounded series of daily OHLCV
candles covering the declared default window, within the declared token
budget.

**Acceptance Scenarios**:

1. **Given** a valid listed symbol, **When** the agent invokes the tool with
   only that symbol, **Then** it receives the default candle series (daily
   frequency over the declared default period) with timestamp, open, high,
   low, close, and volume per candle.
2. **Given** a valid symbol with trading history shorter than the default
   period, **When** the agent invokes the tool, **Then** it receives all
   available candles within the window (fewer than the maximum) — not an
   error and not padded with fabricated candles.
3. **Given** an invalid or unknown symbol, **When** the agent invokes the
   tool, **Then** it receives a structured error naming the offending symbol,
   with no partial candle data.
4. **Given** the market for the symbol is currently open mid-session, **When**
   the agent invokes the tool, **Then** the series includes the current
   session's candle explicitly marked as in-progress, clearly distinguishable
   from the completed candles.

---

### User Story 2 - Bounded period and frequency selection for different analysis horizons (Priority: P2)

An AI agent tailoring an analysis to a specific horizon needs candles at a
different granularity or reach: 5- to 30-minute bars for intraday behavior,
weekly candles for multi-year trends, or a longer daily window for
volatility estimation. The agent specifies the period and frequency from the
tool's declared, bounded set of options and receives candles at that
granularity. Every combination has a hard ceiling on the number of candles
returned, so no request — however chosen — can produce an oversized payload.

**Why this priority**: it extends the core capability to the analysis
horizons agents actually use, while keeping the context hazard (roadmap
note) under control: every ceiling is declared and test-enforced.

**Independent Test**: invoke the tool with each declared period/frequency
combination and verify the candle count never exceeds the declared ceiling
for that combination and that every candle carries the full OHLCV field set.

**Acceptance Scenarios**:

1. **Given** a declared period/frequency combination (for example, one year
   of daily candles, or ten years of weekly candles), **When** the agent
   invokes the tool with that combination, **Then** it receives candles at
   the requested frequency covering the requested period, never exceeding
   the declared ceiling for that combination.
2. **Given** a request that would exceed the declared ceiling for its
   combination (or an unsupported period/frequency value), **When** the
   agent invokes the tool, **Then** it receives a structured validation
   error stating the limit and the allowed values, before any data is
   fetched.
3. **Given** any successful request, **When** the response is measured,
   **Then** its size is consistent with the per-candle budget multiplied by
   the candle count (predictable linear growth, no hidden bulk).

---

### User Story 3 - Full raw price-history payload on request (Priority: P3)

An AI agent occasionally needs a field the curated candle set does not
include (for example, a provider-specific detail attached to the raw
price-history response). The agent re-runs the request in extended mode and
receives the complete raw payload as delivered by the data source, for the
same symbol and window, without a second tool existing for that purpose.

**Why this priority**: it preserves access to the full source data without
inflating the default response, following the established curated-first
pattern. It is only needed when the curated set is insufficient, so it is
not required for the core value.

**Independent Test**: invoke the tool with extended mode enabled and verify
the response contains the complete raw provider price-history payload for
the requested window, in addition to or instead of the curated view.

**Acceptance Scenarios**:

1. **Given** a valid request and extended mode enabled, **When** the agent
   invokes the tool, **Then** it receives the full raw price-history payload
   for that request as delivered by the source.
2. **Given** extended mode is not requested, **When** the agent invokes the
   tool, **Then** the response contains only the curated candle fields
   (compact by default).

---

### Edge Cases

- What happens when a symbol exists but the source has no price history for
  it (for example, a newly listed or delisted instrument)? → The tool
  returns a structured error naming the symbol rather than an empty or
  fabricated series; if the source fails entirely, the invocation returns a
  structured error with no partial data (consistent with the established
  chain-tool behavior).
- What happens when the requested window contains non-trading days
  (weekends, holidays)? → Only candles for actual trading sessions are
  returned; gaps are not interpolated or padded.
- What happens when a candle field is unavailable (for example, zero volume
  on a low-liquidity session)? → The field is reported as delivered — zero
  volume is a real value, not a missing one — and any truly unavailable
  field is explicitly flagged as not available; the tool never invents or
  substitutes a value.
- What happens when the candle count for a valid combination sits exactly
  at the declared ceiling? → It succeeds; only exceeding the ceiling is
  rejected.
- What happens when the source returns fewer candles than the window
  implies (for example, a halted trading week)? → The response reports the
  candles actually delivered; the tool does not fabricate missing sessions.
- What happens when extended-hours coverage is requested for an intraday
  window in which the source has no pre-market or after-hours sessions? →
  Only the candles actually delivered are returned (regular-session candles
  when no extended-hours activity exists); the ceiling still applies and
  nothing is fabricated to fill the extended window.
- What happens when the data source is unreachable or slow? → The tool
  returns a structured error within its latency budget, distinguishing
  retryable transport failures from permanent validation errors.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The tool MUST accept exactly one instrument symbol per
  invocation and return its OHLCV candle series. Intraday tick data beyond
  what the source exposes is out of scope.
- **FR-002**: The tool MUST provide a default window — daily frequency over
  a small declared period — used when the agent specifies nothing, so the
  most common analysis need costs one parameterless invocation. The default
  MUST be small (the exact baseline is measured and recorded at planning
  time).
- **FR-003**: The tool MUST allow the agent to select the period and
  frequency from a declared, bounded set of supported values. The frequency
  set is exactly: 5-minute, 15-minute, 30-minute, hourly, daily, and weekly
  candles — no other frequency is exposed. Every supported combination MUST
  carry a hard ceiling on the number of candles returned.
- **FR-004**: Every period/frequency ceiling MUST be test-enforced: no
  request, however composed, can produce a response exceeding the declared
  ceiling for its combination.
- **FR-005**: The tool MUST return, per candle, at minimum: session
  timestamp, open, high, low, close, and volume, in chronological order.
- **FR-006**: The tool MUST return only the curated field set by default;
  the complete raw source payload MUST be reachable by explicitly requesting
  extended output, following the established curated-first pattern.
- **FR-007**: The tool MUST validate all input (symbol presence and format,
  period/frequency values, ceiling compliance) and fail with a structured
  validation error before any data is fetched.
- **FR-008**: The tool MUST NOT return partial data: if the source fails or
  cannot provide price history for the requested symbol, the invocation
  returns a structured error naming the symbol and the reason.
- **FR-009**: The tool MUST follow the same structured response envelope
  (success/error outcomes with detail and retryability) as the existing
  tools; no second response format may be introduced.
- **FR-010**: The tool MUST be read-only: it retrieves market data only and
  MUST NOT place, modify, or cancel orders.
- **FR-011**: The tool MUST never emit credentials, tokens, or account
  identifiers in any output.
- **FR-012**: The tool MUST complete within its declared latency budget and
  return a structured error (not a timeout hang) when the source exceeds it.
- **FR-013**: The tool MUST NOT compute indicators, averages, volatility
  statistics, or any other derived value: it returns the candles as
  delivered, and analysis is performed by the agent (or a later derived
  spec).
- **FR-014**: The tool MUST NOT perform arbitrary date-range queries in its
  default surface: period/frequency presets bound the payload; a stated need
  is required before any start/end-date capability is added.
- **FR-015**: Every response MUST state the window it covers (first and last
  candle timestamps) and the candle count, so the agent can judge coverage
  without counting candles or making a second call.
- **FR-016**: For intraday (minute-based) requests, candles MUST cover the
  regular trading session by default; an explicit opt-in flag MUST extend
  coverage to pre-market and after-hours sessions. The declared candle
  ceilings apply regardless of the flag — enabling it never raises them.
- **FR-017**: The response MUST include the current still-forming session's
  candle when one exists, explicitly identified as in-progress (a per-candle
  marker); it MUST never be indistinguishable from completed candles, and
  the tool MUST NOT withhold or fabricate it.
- **FR-018**: The period MUST be selected from a declared set of named
  presets (for example: day, week, month, year, year-to-date), with the
  allowed presets bounded per frequency. Free-form numeric look-backs and
  date-range inputs are not accepted as period values (consistent with
  FR-014).
- **FR-019**: Each weekly candle MUST be labeled with the timestamp of its
  last (closing) session, so candle spans align naturally with dated events
  the agent tracks (earnings dates, option expirations, transaction dates).

### Key Entities *(include if feature involves data)*

- **Candle**: the summarized market activity of one session at the requested
  frequency. Attributes: session timestamp (for weekly candles: the closing
  session's timestamp, FR-019), open, high, low, close, volume, and an
  in-progress marker (true only for the current still-forming candle). A
  candle never contains computed indicators or derived statistics (out of
  scope).
- **Price history request**: one invocation: one instrument symbol, an
  optional period/frequency selection — the frequency from the declared set
  (5-minute, 15-minute, 30-minute, hourly, daily, weekly) and the period
  from the declared named presets bounded per frequency (a small daily
  default applies when omitted), an optional extended-hours flag for
  intraday requests (regular session when omitted), and the extended-output
  flag. Every combination is capped by a declared candle ceiling.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The agent obtains the default candle series with a single tool
  invocation completing in **≤ 5 seconds p95**, without any external data
  source or manual stitching.
- **SC-002**: The default curated response stays within its declared token
  budget — on the order of **a few hundred tokens for the default window** —
  with the exact baseline measured and recorded at planning time and
  verified by token-usage tests thereafter.
- **SC-003**: For any supported period/frequency combination, the response
  never exceeds the declared candle ceiling, verified by tests covering
  100% of declared combinations.
- **SC-004**: 100% of invalid requests (malformed symbol, unsupported
  period/frequency, ceiling-exceeding request) fail with a structured
  validation error before any data fetch occurs.
- **SC-005**: From any successful response alone, the agent can determine
  the covered window (first/last candle timestamps) and candle count with
  100% of responses carrying them.
- **SC-006**: Extended mode returns the complete raw source payload for the
  requested window, verified against a known source response in the
  automated suite.

## Assumptions

- The exact default window and per-combination ceilings (and their measured
  token baselines) are finalized at planning time, per the roadmap's open
  question on the payload budget baseline for candles; this spec fixes only
  that the default must be small and every ceiling test-enforced.
- Period/frequency presets only in this version: arbitrary start/end date
  ranges are out of scope until a stated analysis need requires them
  (simplicity-first; FR-014).
- Candles are returned in chronological order (oldest first), matching how
  trend analysis consumes them.
- The price history data comes from the existing Schwab market-data
  integration (reuse before creation); no new data source is introduced.
- Prices are as delivered by the source (no additional adjustment or
  back-adjustment is computed here); any provider-specific adjustment
  metadata remains reachable via extended mode.
- This spec follows the roadmap decisions C-04 (simplicity), C-05 (payload
  and latency budgets), and C-09 (curated-first with `extended`
  passthrough), and the read-only surface decision C-06.
