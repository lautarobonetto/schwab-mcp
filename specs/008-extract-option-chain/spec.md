# Feature Specification: Option Chain Extraction with Filters

**Feature Branch**: `008-extract-option-chain`

**Created**: 2026-10-23

**Status**: Draft

**Input**: User description: "I want to add a new tool to the MCP that allows extracting the entire option chain of an instrument. To keep the result the MCP has to return from being too bulky, I want the tool to have all of the following optional filters: (1) maximum number of strikes to fetch, applies to both sides of the strike, default value 50; (2) filter to CALLs only, PUTs only, or both, default value both; (3) filter by target Delta: if delta 0.20 is sought, the filter brings the options of the 5 strikes around Delta 0.20, default value null (does not filter by delta); (4) DTE filter, default value null and it means it brings all expirations up to 60 days at most. Note: the chain must include all the Greeks and all the technical values available so that good analyses of complex option positions (Iron Condors, Naked puts, Calendars, LEAPs, etc.) can be made."

## Clarifications

### Session 2026-10-23

- Q: When the target delta filter is active and the option type is "both", is the 5-strike window computed separately for CALLs and PUTs? → A: window **per type**: for each expiration, up to 5 CALL strikes around the CALL contract closest to the target delta and up to 5 PUT strikes around the PUT contract closest to the target delta (comparing delta in absolute value); no window shared between types.
- Q: What is the maximum response size budget (in approximate tokens) that an invocation with all filters at their defaults must respect? → A: **30,000 tokens** per invocation with default filters; if a real chain exceeds it, the output format is compacted without trimming Greeks or violating the filter limits.
- Q: When the target delta filter is active, is the 5-strike window applied to all expirations within the current DTE cap, or only to the nearest expiration? → A: to **all expirations** within the current DTE cap (default 60 days), one by one; the delta filter does not restrict the set of expirations.
- Q: When the market data source fails or returns an incomplete chain, must the tool abort with a structured error and no partial data, or return what it has while flagging what is missing? → A: **structured error with no partial data**: if the source fails or an entire expiration comes with no data, the tool does not return a chain and reports the reason; individual missing fields within present contracts are flagged as not available (FR-007).

### Session 2026-10-24

- Q: To make the response with default filters predictable in size, which strategy do we choose: raise the token budget to the actual measured size, or lower the default strikes per side? → A: **the default of 50 strikes per side stays**; the token budget with default filters rises to **≤75,000 tokens** (justification recorded in plan.md, Principle V of the constitution); with `delta_target` active the small target (<3,000 tokens) stays. This decision **replaces** the 30,000-token budget from the 2026-10-23 session.
- Q: How do we make the criterion that the agent completes the analysis of a complex position without needing a second invocation verifiable? → A: **each validation scenario (quickstart S1–S3, covering Iron Condor, Naked Put, Calendar and LEAP) completes with exactly 1 tool invocation**, verified in the integration tests.
- Q: What exact scope must the set of technical fields per contract have: a curated superset declared in the response (with access to the rest via extended mode), or literally all fields from the source? → A: **curated superset declared in `contract_fields`** (quote, liquidity, IV, the 5 Greeks, theoretical values, time value, multiplier, trade time, deliverables note); the remaining structural fields from the source remain accessible via extended mode with the full raw payload.
- Q: Which latency target do we unify as the success criterion: the strictest one from plan and contract (≤5 s p95) or the laxer one from the spec (<10 s)? → A: **≤5 seconds p95 per invocation**, unified in spec, plan and contract.
- Q: How do we verify compliance with the 5-strike-per-delta window: fixtures in the automated suite, with additional live validation, or only real chains? → A: **automated suite with representative fixtures** (including edges: delta at the boundary of the curve, missing strikes) **+ validation against a real chain as a step of quickstart S2**.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Analyze a complex option position with a single query (Priority: P1)

An AI agent advising a trader needs to build an analysis of a complex
option position (for example, an Iron Condor or a Naked Put) on an
instrument. The agent invokes the tool with the instrument identifier and
the default filter values, and receives the complete option chain of the
instrument with all its expirations up to 60 days, both option types
(CALLs and PUTs), up to 50 strikes per side around the at-the-money
strike, and **all** the Greeks and all the technical values available for
each contract. With that single response the agent can identify vertical
spreads, select wings for the condor and estimate the risk of the
position without needing additional queries.

**Why this priority**: it is the core use case of the tool: obtaining all
the information needed to analyze option positions in a single
invocation, without exceeding the data volume the agent can consume.

**Independent Test**: invoke the tool with an instrument that has an
option chain and verify that the response contains, for each expiration
within the default DTE range, the strikes on both sides of the money (up
to the default limit), both option types, and the complete set of Greeks
and technical values of each contract.

**Acceptance Scenarios**:

1. **Given** an instrument with listed options and several expirations,
   **When** the agent invokes the tool with only the instrument
   identifier (no filters), **Then** it receives the expirations within
   60 days, both option types, up to 50 strikes per side of the money
   per expiration, and for each contract all the available Greeks and
   technical values.
2. **Given** the response of a default invocation, **When** the agent
   examines it, **Then** each contract includes at least the five
   classic Greeks (delta, gamma, theta, vega, rho) and the available
   market values (bid/ask price, last, volume, open interest, implied
   volatility, and the other technical values the source exposes for
   that contract).
3. **Given** a complex option position to analyze (Iron Condor),
   **When** the agent plans the position with the data from the
   response, **Then** it does not need to invoke the tool again to
   complete the analysis within the range of expirations and strikes
   received.

---

### User Story 2 - Focus the query by option type and target delta (Priority: P2)

An agent designing a directional or income strategy (for example, selling
puts covered at delta 0.20) needs to see only the relevant options around
that delta. The agent invokes the tool indicating the desired option type
(PUTs only, for example) and a target delta of 0.20; the tool returns,
for each expiration within the current DTE range, the options of the 5
strikes surrounding delta 0.20 instead of the entire strike curve. This
drastically reduces the response volume and presents exactly the zone of
the chain where the strategy would be executed.

**Why this priority**: it is the most commonly used refinement in
practice for strike selection by probability (delta as proxy), and it
depends on the base tool of Story 1.

**Independent Test**: invoke the tool with option type and target delta
on an instrument with options and verify that, for each eligible
expiration, exactly 5 strikes are returned (or all available if there are
fewer) centered around the contract whose delta is closest to the target,
and that the excluded option type does not appear.

**Acceptance Scenarios**:

1. **Given** an instrument with options, **When** the agent requests PUTs
   only with target delta 0.20, **Then** it receives only PUT-type
   contracts and, for each expiration within the DTE range, the
   contracts of the 5 strikes around delta 0.20.
2. **Given** a target delta whose closest value in the chain falls on the
   edge of the listed strike curve, **When** the tool applies the delta
   filter, **Then** it returns up to 5 strikes: those that exist around
   that point, without inventing non-existent strikes.
3. **Given** a requested option type (CALL or PUT), **When** the tool
   builds the response, **Then** no contract of the non-requested type
   appears in the response.

---

### User Story 3 - Adjust the response volume via explicit limits (Priority: P3)

An agent that needs a broad view of the chain (for example for calendars
or LEAPs with distant expirations) can adjust the limits: the maximum
number of strikes per side of the money and the maximum DTE horizon. The
agent invokes the tool increasing the strike limit or the DTE horizon as
needed, and the tool returns a deterministic response bounded by those
limits. Conversely, an agent that needs a minimal response lowers the
strike limit and the DTE horizon to minimize token consumption.

**Why this priority**: it is the volume control lever; it complements but
does not block the main use cases.

**Independent Test**: invoke the tool with different strike-limit and
DTE-horizon values and verify that the number of strikes per side and the
set of returned expirations respect exactly the requested limits.

**Acceptance Scenarios**:

1. **Given** an instrument with more than 50 listed strikes per side,
   **When** the agent requests a limit of 10 strikes per side, **Then**
   the response contains at most 10 strikes per side of the money for
   each expiration, always including the at-the-money zone.
2. **Given** a requested DTE horizon of 120 days, **When** the tool
   builds the response, **Then** it includes all the expirations of the
   instrument with DTE less than or equal to 120 days and none beyond.
3. **Given** a requested DTE horizon of 7 days, **When** the nearest
   expiration of the instrument expires in 10 days, **Then** the
   response contains no expirations and communicates this explicitly
   instead of failing.

---

### Edge Cases

- What happens when the instrument has no listed options? The tool
  communicates it explicitly and structurally (no data, no ambiguous
  error), so the agent can decide the next step.
- What happens when the DTE filter excludes all expirations (for
  example, a maximum DTE smaller than the nearest expiration)? The
  response is an empty chain accompanied by an explicit explanation, not
  a generic error.
- What happens when the target delta has no reasonable nearby contract
  (for example, target delta 0.02 in a short chain)? The tool returns
  the available strikes around the point closest to the target and up to
  5, without failing.
- What happens when the number of available strikes is smaller than the
  requested limit? All available ones are returned for that side.
- What happens with invalid filter values (delta outside the expected
  range, strike limit of zero or negative, negative DTE)? The tool
  rejects the invocation with a clear validation message before querying
  data.
- What happens when the data source does not report some Greek or
  technical value for a specific contract? The corresponding field is
  flagged as not available explicitly, without inventing values.
- What happens when the data source fails or an entire expiration comes
  with no data? The tool does not return a partial chain: it aborts with
  a structured error that describes the reason, so the agent can retry
  or inform the user (FR-013).
- What happens if the instrument exists but trades in a closed market
  with delayed data? The tool returns the available data and indicates
  the delay or the data state, so the agent knows how fresh it is.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST expose an option chain extraction tool
  that receives the underlying instrument identifier as the only
  mandatory input.
- **FR-002**: The tool MUST accept an optional filter of maximum number
  of strikes per side of the money, with default value 50; the limit
  applies symmetrically to the strikes below and above the money for
  each returned expiration.
- **FR-003**: The tool MUST accept an optional option-type filter with
  three possible values: CALLs only, PUTs only, or both; the default
  value is both.
- **FR-004**: The tool MUST accept an optional target delta filter;
  when present, for each expiration within the current DTE cap and for
  each option type included (with "both", CALLs and PUTs are processed
  separately, comparing delta in absolute value) it returns the
  contracts of the 5 strikes surrounding the contract of that type whose
  delta is closest to the target (the closest point plus the two
  contiguous strikes on each side, limited to existing strikes); when
  absent, it does not filter by delta.
- **FR-005**: The tool MUST accept an optional maximum DTE filter; when
  absent it applies a default cap of 60 days; when present, the provided
  value replaces that default cap. In both cases only expirations with
  DTE less than or equal to the current cap are returned.
- **FR-006**: For each returned contract, the tool MUST include all the
  Greeks available in the source (at least delta, gamma, theta, vega and
  rho) and the curated superset of technical values declared in
  `contract_fields` within the response itself (quote, liquidity,
  implied volatility, theoretical values, time value, multiplier, trade
  time, deliverables note); the remaining structural fields the source
  exposes remain accessible via extended mode with the full raw payload.
- **FR-007**: When a Greek or technical value field is not available for
  a contract, the tool MUST flag it explicitly as not available instead
  of silently omitting it or inventing a value.
- **FR-008**: The tool MUST validate the filters before querying data
  and reject with a clear validation message any invocation with invalid
  values (unknown option type, delta outside the expected range for
  buying/selling options depending on the requested type, non-positive
  strike limit, non-positive DTE).
- **FR-009**: The tool MUST explicitly and structurally communicate the
  no-data cases: instrument without listed options and a DTE filter that
  excludes all expirations.
- **FR-010**: The tool MUST include in the response metadata that allows
  the agent to interpret the chain: instrument identifier, data state or
  delay, and for each expiration its date and its DTE.
- **FR-011**: The tool MUST return the complete response in a single
  invocation, with no pagination or need for follow-up queries within
  the requested limits.
- **FR-012**: The response volume MUST be bounded by the filters: the
  response never exceeds the product of (expirations within the DTE cap)
  × (requested types) × (allowed strikes per side).
- **FR-013**: When the market data source fails or an entire expiration
  comes with no data, the tool MUST abort with a structured error that
  describes the reason, without returning a partial chain; individual
  missing fields within present contracts are governed by FR-007
  (explicit not-available flag).

### Key Entities *(include if feature involves data)*

- **Option chain**: the set of expirations and contracts of an underlying
  instrument, with metadata about the instrument and the data state.
- **Expiration**: an expiration date within the chain, with its exact
  date and its calculated DTE; it is the unit on which the strike limits
  and the delta filter apply.
- **Option contract**: a specific option (CALL or PUT type, strike and
  expiration), with its market values, its Greeks and its technical
  values; it includes the reference of the underlying and of the current
  at-the-money strike for its expiration.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An agent can obtain the complete option chain of an
  instrument with options (default filters) in a single invocation, in
  **≤5 seconds p95** from invocation to response.
- **SC-002**: With the default filters (50 strikes per side, both types,
  current DTE cap), the response volume for a typical underlying stays
  within a declared budget of **75,000 tokens** per invocation,
  verifiable by automated test (growth justification recorded in plan.md
  — Principle V); with `delta_target` active the target is
  **< 3,000 tokens**. The output format is compacted without trimming
  Greeks or violating the filter limits.
- **SC-003**: 100% of the returned contracts include the five classic
  Greeks or the explicit not-available flag; no field is silently
  omitted.
- **SC-004**: Each validation scenario of the quickstart (S1–S3,
  covering the Iron Condor, Naked Put, Calendar and LEAP analyses within
  the range of expirations and strikes received) completes with
  **exactly 1 invocation** to the tool, verified in the integration
  tests.
- **SC-005**: With the target delta filter active and type "both", each
  returned expiration contains up to 5 CALL strikes and up to 5 PUT
  strikes around the target delta (or all available if there are fewer).
  Verification: automated suite with representative fixtures from the
  provider (including edge cases) plus a validation against a real chain
  as a step of quickstart S2.
- **SC-006**: The requested limits (strikes per side, option types, DTE)
  are respected 100% in the response; zero out-of-bounds contracts in
  the test cases.

## Assumptions

- **Per-expiration application**: the strike limits and the delta filter
  apply to each returned expiration (not to the complete response); it
  is the natural reading of "both sides of the strike" and of "the 5
  strikes around the delta".
- **Delta × strike-limit interaction**: when the delta filter is active,
  the 5 strikes around the delta govern the selection and the strike
  limit per side does not reduce it further; the strike limit only
  applies when there is no delta filter.
- **Centering of the delta filter**: "around delta 0.20" is interpreted
  as centered: per option type included (see Clarifications, session
  2026-10-23), the contract with the delta closest to the target plus
  two contiguous strikes on each side (up to 5, or those that exist).
- **Reference strike of the strike limit**: the center of the strike
  window is the at-the-money strike of the expiration (the contract with
  exercise price closest to the current price of the underlying for that
  expiration).
- **Default DTE cap**: "default value null" for the DTE filter is
  interpreted as: it does not filter by a user-chosen DTE, but it
  applies a cap of 60 days at most; an explicit value replaces that cap
  (higher or lower).
- **Target delta range**: the target delta is expressed in absolute
  value (for example 0.20) and the tool maps it to the correct sign
  according to the requested option type (puts have negative delta); a
  delta outside the reasonable range is rejected in validation.
- **Data freshness**: the tool reuses the market data source already
  integrated in this project; no new source is added.
- **Scope**: the tool is read-only (it does not place orders or move
  money) and is aimed at AI agents that consume the MCP.