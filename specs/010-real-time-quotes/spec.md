# Feature Specification: Real-Time Quotes (`get_quotes`)

**Feature Branch**: `010-real-time-quotes`

**Created**: 2026-10-27

**Status**: Draft

**Input**: User description: "010 — Real-time quotes (`get_quotes`), from the
spec roadmap [status: planned]: MCP tool wrapping the provider's
multi-symbol and single-symbol quote capability — current price, bid/ask,
volume, and quote freshness for 1..N symbols in one invocation. Outcome: the
agent can obtain current prices without pulling an option chain or other
heavyweight payload. Scope in: single and multi-symbol queries; curated
compact output with `data_state` (realtime/delayed); `extended` passthrough.
Scope out: order book depth (not provided by the source); chart data
(that is 011). Expected payload must stay in the hundreds of tokens per
symbol."

## Clarifications

### Session 2026-10-27

- Q: Which kinds of instrument symbols must the quotes tool accept? → A: **all
  of the above** — underlying equity/ETF symbols, option-contract symbols,
  and index symbols; validation adapts to each kind and quotes return per
  requested symbol.
- Q: When the market for a requested symbol is closed, what `data_state`
  value should the quote carry? → A: **three states**: `realtime` (live
  quote while the market is open), `delayed` (delayed feed while open),
  and `closed` (last available quote while the market for that symbol is
  closed), with the last-trade timestamp carrying the exact staleness.
- Q: How should the multi-symbol response present the quotes? → A: **object
  keyed by symbol**; each entry carries that symbol's quote or its
  per-symbol error, so attribution is unambiguous regardless of order or
  de-duplication.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Current price of a single instrument without heavyweight payloads (Priority: P1)

An AI agent advising a trader needs the current price of one instrument —
for example, to check whether an underlying has moved before evaluating an
option position, or to mark a position to market. Today the only way to get
a price is to pull the full option chain (~75,000 tokens) or another
heavyweight payload. The agent invokes the quotes tool with the instrument
symbol and receives a compact quote: last price, bid, ask, volume, net
change, a freshness indicator (`realtime`, `delayed`, or `closed`), and the time of the
last trade. With one small response the agent has the price and can judge
how fresh it is, without any follow-up call.

**Why this priority**: this is the core reason the tool exists (roadmap
outcome): the cheapest possible path to a current price. It is independently
valuable and is the foundation the batch story reuses.

**Independent Test**: invoke the tool with one valid symbol and verify the
response contains the curated quote fields for that symbol, the freshness
indicator, and stays within the per-symbol token budget.

**Acceptance Scenarios**:

1. **Given** a valid listed symbol, **When** the agent invokes the tool with
   only that symbol, **Then** it receives a single curated quote with last
   price, bid, ask, volume, net change, `data_state` (`realtime`,
   `delayed`, or `closed`), and last-trade timestamp.
2. **Given** the market for that symbol is closed, **When** the agent
   requests a quote, **Then** it still receives the last available quote,
   with `data_state` = `closed` and the last-trade timestamp making the
   staleness explicit (no invented or refreshed prices).
3. **Given** an invalid or unknown symbol, **When** the agent invokes the
   tool, **Then** it receives a structured error naming the offending
   symbol, with no partial quote data.

---

### User Story 2 - Batch quotes for several instruments in one invocation (Priority: P2)

An AI agent reviewing a portfolio needs current prices for several
underlyings at once (for example, every symbol held in the account). Instead
of issuing one invocation per symbol — multiplying latency and tool-call
overhead — the agent passes the list of symbols in a single invocation and
receives one quote per symbol in the same compact format as the
single-symbol case. The response grows linearly and predictably with the
number of symbols, staying within the declared budget.

**Why this priority**: it removes a recurring N-call pattern in portfolio
analysis and is the roadmap's reason for preferring one tool for 1..N
symbols over a single-symbol-only tool. It builds directly on the
single-symbol behavior of Story 1.

**Independent Test**: invoke the tool with a list of valid symbols and
verify exactly one quote per requested symbol is returned, keyed by
symbol, and that the total response stays within the declared token budget
for that count.

**Acceptance Scenarios**:

1. **Given** a list of valid symbols (1..N within the limit), **When** the
   agent invokes the tool once with the list, **Then** it receives an
   object keyed by symbol with one curated quote per requested symbol,
   from a single invocation.
2. **Given** a list that exceeds the declared symbol limit, **When** the
   agent invokes the tool, **Then** it receives a structured validation
   error stating the limit, before any data is fetched.
3. **Given** a request for N symbols, **When** the response is measured,
   **Then** its size is consistent with the per-symbol budget multiplied by
   N (linear growth, no hidden bulk).

---

### User Story 3 - Full raw quote payload on request (Priority: P3)

An AI agent occasionally needs a field that the curated quote does not
include (for example, a provider-specific detail such as high/low of the
session, open interest context, or exchange identifiers). The agent re-runs
the request in extended mode and receives the complete raw quote payload as
delivered by the data source, for the same symbols, without a second
tool existing for that purpose.

**Why this priority**: it preserves access to the full source data without
inflating the default response, following the established curated-first
pattern of the existing tools. It is only needed when the curated set is
insufficient, so it is not required for the core value.

**Independent Test**: invoke the tool with extended mode enabled and verify
the response contains the complete raw provider quote payload for each
requested symbol, in addition to or instead of the curated view.

**Acceptance Scenarios**:

1. **Given** a valid symbol and extended mode requested, **When** the agent
   invokes the tool, **Then** it receives the full raw quote payload for
   that symbol as delivered by the source.
2. **Given** extended mode is not requested, **When** the agent invokes the
   tool, **Then** the response contains only the curated fields (compact by
   default).

---

### Edge Cases

- What happens when a symbol exists but has no current quote data from the
  source? → The tool reports a structured error naming the symbol rather
  than returning an empty or fabricated quote; if the source fails
  entirely, the invocation returns a structured error with no partial
  data (consistent with the established chain-tool behavior).
- What happens when a well-formed option-contract symbol refers to a
  contract that is expired or not quoted? → Treated like any other symbol
  without current quote data: structured error naming the symbol, no
  fabricated quote.
- What happens when a field of a returned quote is unavailable (for
  example, no bid/ask for a thinly traded instrument)? → The field is
  explicitly flagged as not available; the tool never invents or
  substitutes a value.
- What happens when the agent requests a symbol list with duplicates? →
  Duplicates are de-duplicated (one quote per distinct symbol), and the
  count check applies to distinct symbols.
- What happens when the symbol list is empty? → A structured validation
  error: at least one symbol is required.
- What happens when the symbol list is at the exact limit? → It succeeds;
  only exceeding the limit is rejected.
- What happens when the data source is unreachable or slow? → The tool
  returns a structured error within its latency budget, distinguishing
  retryable transport failures from permanent validation errors.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The tool MUST accept 1..N instrument symbols in a single
  invocation, covering the single-symbol and multi-symbol cases with one
  tool (no separate single-quote tool). In multi-symbol requests the
  response MUST be an object keyed by symbol, with one entry per distinct
  requested symbol carrying either that symbol's quote or its per-symbol
  error.
- **FR-002**: The tool MUST return, per symbol, at minimum: last price,
  bid, ask, volume, net change (absolute and percent), quote freshness
  (`data_state`: `realtime`, `delayed`, or `closed`), and last-trade
  timestamp. The percent net change MUST be `null` (never invented) when
  the reference close price is missing or zero.
- **FR-003**: The tool MUST make quote freshness explicit in every quote —
  `realtime` (live, market open), `delayed` (delayed feed, market open),
  or `closed` (last available quote, market closed for that symbol) — so
  the agent can distinguish live prices from delayed or stale ones without
  a second call.
- **FR-004**: The tool MUST return only the curated field set by default;
  the complete raw source payload MUST be reachable by explicitly
  requesting extended output, following the established curated-first
  pattern.
- **FR-005**: The tool MUST validate all input (symbol list presence,
  format, and count limit) and fail with a structured validation error
  naming every offending symbol before any data is fetched.
- **FR-006**: The tool MUST NOT return partial data: if the source fails or
  cannot provide a requested symbol's quote, the invocation returns a
  structured error naming the affected symbol(s) and the reason.
- **FR-007**: The tool MUST reject requests exceeding the declared symbol
  limit with a structured validation error stating the limit.
- **FR-008**: The tool MUST follow the same structured response envelope
  (success/error outcomes with detail and retryability) as the existing
  tools; no second response format may be introduced.
- **FR-009**: The tool MUST be read-only: it retrieves market data only and
  MUST NOT place, modify, or cancel orders.
- **FR-010**: The tool MUST never emit credentials, tokens, or account
  identifiers in any output.
- **FR-011**: The tool MUST complete within its declared latency budget for
  the maximum symbol count, and return a structured error (not a timeout
  hang) when the source exceeds it.
- **FR-012**: Unavailable fields within a returned quote MUST be flagged as
  not available, never defaulted, substituted, or interpolated.
- **FR-013**: The tool MUST accept three kinds of instrument symbols:
  underlying equity/ETF symbols, option-contract symbols, and index
  symbols. Validation MUST adapt to each kind (format rules differ), and
  an unsupported or malformed symbol of any kind MUST fail validation
  naming the symbol.

### Key Entities *(include if feature involves data)*

- **Quote**: the current market state of one instrument. Attributes:
  instrument symbol, last price, bid, ask, volume, net change (absolute
  and percent), freshness state (`realtime`, `delayed`, or `closed`),
  last-trade timestamp. A quote never contains order-book depth or historical price
  series (out of scope).
- **Quote request**: one invocation: a list of 1..N distinct symbols plus
  the extended-output flag. Accepted symbol kinds: underlying
  equity/ETF symbols, option-contract symbols, and index symbols. The
  symbol count is capped by a declared limit.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The agent obtains a current price with a single tool
  invocation completing in **≤ 5 seconds p95**, without pulling an option
  chain or any other heavyweight payload.
- **SC-002**: The default curated response stays within the declared token
  budget: **hundreds of tokens per symbol** (target ≤ 250 tokens for a
  single symbol; ≤ 2,500 tokens for a 10-symbol batch), verified by
  token-usage tests.
- **SC-003**: For any quote returned, the agent can determine its freshness
  (`realtime`, `delayed`, or `closed`, with last-known timestamp) from the
  response alone, with 100% of quotes carrying `data_state` and a
  last-trade timestamp.
- **SC-004**: 100% of invalid requests (empty list, malformed symbol,
  over-limit list) fail with a structured validation error before any data
  fetch occurs.
- **SC-005**: A 10-symbol portfolio price check that today requires N
  heavyweight chain pulls (~750,000 tokens) completes with exactly 1
  invocation under 2,500 tokens — a payload reduction greater than 99%.
- **SC-006**: Extended mode returns the complete raw source payload for the
  requested symbols, verified against a known source response in the
  automated suite.

## Assumptions

- One tool serves 1..N symbols (roadmap Q1 resolved by DRY: the single and
  multi-symbol capabilities share one implementation and one response
  shape).
- The symbol count limit defaults to **20 symbols per invocation** — well
  above any single-portfolio price check while keeping the worst-case
  response within ~5,000 tokens; exceeding it returns a validation error.
- The quote data comes from the existing Schwab market-data integration
  (reuse before creation); no new data source is introduced.
- The curated field set above matches what agents repeatedly need for
  price checks; any additional provider field remains reachable via
  extended mode rather than growing the default payload.
- Order-book depth is not provided by the source and is out of scope;
  chart/historical data is spec 011 and out of scope here.
- This spec follows the roadmap decision C-09 (curated-first with
  `extended` passthrough) and the read-only surface decision C-06.