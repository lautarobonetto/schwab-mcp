# Feature Specification: Option Expiration List (`get_option_expiration_chain`)

**Feature Branch**: `012-option-expiration-list`

**Created**: 2026-11-03

**Status**: Draft

**Input**: User description: "012 — Option expiration list
(`get_option_expiration_chain`), from the spec roadmap [status: planned]:
MCP tool wrapping the provider's option-expiration-chain capability — the
list of expirations for an underlying, without strikes or greeks. Outcome:
'which expirations exist?' costs hundreds of tokens instead of the
5–110k of a full `get_option_chain` call. Scope in: expiration dates with
DTE; DTE ceiling consistent with 008's `dte_max_effective` semantics.
Scope out: strikes, greeks, quotes (that is `get_option_chain`). Depends
on: 008 (semantics alignment). Governed by: C-05 (token/performance
budgets), C-09 (curated-first output pattern)."

## Clarifications

### Session 2026-11-03

- Q: When the agent supplies an explicit DTE ceiling, should the tool accept
  any positive value or impose its own hard upper limit? → A: **any
  `dte_max` ≥ 1 is accepted and replaces the 60-day default, with no hard
  upper limit** — identical semantics to `get_option_chain` (spec 008
  FR-005); payload risk is negligible because each expiration costs roughly
  ten tokens.

- Q: What should each curated expiration entry contain, and how should
  same-date expirations (for example, SPX morning- and afternoon-settled)
  be handled? → A: **each entry carries expiration date, DTE, and
  settlement type, and every provider entry is listed separately** —
  same-date expirations stay distinguishable and are never merged
  (deduping by date would silently lose a materially different contract).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - List available expirations for an underlying in one call (Priority: P1)

An AI agent planning an option strategy on an underlying (for example,
"sell a put on SPX expiring in about three weeks") first needs to know
**which expirations exist** for that underlying. Today the only way to
answer this through the MCP is to pull the full option chain
(`get_option_chain`), which costs from a few thousand up to ~110k tokens
because it returns every strike, quote, and greek. The agent instead
invokes the expiration-list tool with just the underlying's symbol and
receives a compact, ordered list of upcoming expirations — each with its
days-to-expiration (DTE) and settlement type — small enough to read at a
glance and to pick a target date from. One invocation, no follow-up calls,
no strikes or greeks attached.

**Why this priority**: this is the core roadmap outcome and the
highest token-saving ratio of the passthrough group. Answering
"which expirations exist?" is the natural pre-step before any targeted
chain query; without it, the agent either wastes a heavyweight call or
guesses an expiration date that may not exist.

**Independent Test**: invoke the tool with one valid optionable symbol and
no other parameters; verify the response contains a bounded, ordered list
of expirations with date, DTE, and settlement type, no
strikes/quotes/greeks, and within the declared token budget.

**Acceptance Scenarios**:

1. **Given** a valid listed optionable symbol, **When** the agent invokes
   the tool with only that symbol, **Then** it receives the list of
   upcoming expirations for that underlying, each with its calendar DTE
   and settlement type, ordered from soonest to latest.
2. **Given** a valid symbol whose expirations all lie beyond the default
   DTE ceiling (60 days), **When** the agent invokes the tool, **Then** it
   receives an empty expiration list with a structured, retryable outcome
   stating that the applied DTE ceiling excluded all expirations (mirroring
   the `no_expirations_in_range` semantics of `get_option_chain`) — not a
   generic error and not fabricated data.
3. **Given** an invalid, unknown, or non-optionable symbol, **When** the
   agent invokes the tool, **Then** it receives a structured validation
   error outcome before any upstream call is made or as a clean provider
   error mapping — never a raw stack trace, never invented expirations.

---

### User Story 2 - Narrow or widen the expiration window with an explicit DTE ceiling (Priority: P2)

An agent often cares only about expirations within a planning horizon
(for example, the next 30 days for a short-dated spread) or needs to see
further out (for example, LEAPS-ish horizons when comparing calendars).
The agent passes an explicit DTE ceiling with the request and receives only
the expirations whose DTE is within that ceiling. The response echoes the
effective ceiling actually applied (`dte_max_effective`), so the agent can
always verify the applied window and distinguish "empty because of the
ceiling" from "empty because the underlying has no options".

**Why this priority**: window control bounds the payload before fetch
(C-09) and keeps consistency with the established `get_option_chain`
filter semantics (spec 008); it is essential for targeted workflows but
the default window alone already delivers the core value.

**Independent Test**: invoke the tool with a valid symbol and an explicit
DTE ceiling within the allowed bounds; verify only expirations with
DTE ≤ ceiling are returned and `dte_max_effective` equals the requested
value; invoke with a ceiling that excludes everything and verify the
structured empty outcome.

**Acceptance Scenarios**:

1. **Given** a valid optionable symbol with expirations spread across
   months, **When** the agent requests a DTE ceiling of 30, **Then** it
   receives only expirations with DTE ≤ 30 and the response shows
   `dte_max_effective == 30`.
2. **Given** an explicit DTE ceiling request with a large positive value
   (for example, 365), **When** the agent invokes the tool, **Then** the
   value is accepted and replaces the default — it returns all expirations
   with DTE ≤ 365 and the response shows `dte_max_effective == 365`; a
   value below 1 (zero or negative) is rejected with a structured
   validation error naming the `≥ 1` constraint before any upstream call.
3. **Given** the default request (no ceiling), **When** the agent invokes
   the tool, **Then** the response shows `dte_max_effective == 60`,
   identical to `get_option_chain`'s default ceiling.

---

### User Story 3 - Full raw expiration payload on request (Priority: P3)

When debugging a surprising result (for example, an expiration the agent
expected but does not see, or provider metadata the curated schema omits),
the agent re-invokes the tool with the extended passthrough enabled and
receives the provider's complete expiration-chain payload for that
underlying. The curated path stays the default; the raw payload is
reachable on demand without a second tool.

**Why this priority**: established cross-cutting pattern (C-09); keeps the
curated schema token-minimal while preserving full transparency for
debugging and schema-evolution decisions.

**Independent Test**: invoke the tool with the extended flag set; verify
the response contains the provider's raw expiration-chain payload and that
the default (flag unset) response contains only the curated fields.

**Acceptance Scenarios**:

1. **Given** a valid optionable symbol, **When** the agent invokes the
   tool with the extended flag, **Then** it receives the provider's raw
   expiration payload in addition to (or wrapped with) the curated result.
2. **Given** the same symbol, **When** the agent invokes the tool without
   the extended flag, **Then** the response contains only curated
   expiration fields — no provider-specific metadata, no strikes, no
   greeks, no quotes.

---

### Edge Cases

- What happens when the symbol has no listed options at all?
  → A structured, non-retryable outcome stating the underlying has no
  option expirations (distinct from "the ceiling excluded them").
- What happens when the DTE ceiling excludes every expiration but options
  exist beyond it? → `no_expirations_in_range` outcome with the effective
  ceiling in the detail, consistent with `get_option_chain`'s behavior.
- What happens when the symbol is malformed (empty, whitespace, too long,
  invalid characters)? → Structured validation error before any upstream
  call, consistent with the shared validation-error pattern of 003/006/008.
- What happens when the provider is unreachable or errors?
  → A structured, retryable outcome with the mapped error reason; no
  partial or fabricated expiration list.
- What happens when the underlying lists more than one expiration on the
  same calendar date (for example, SPX morning- and afternoon-settled)?
  → Both are listed as separate entries distinguished by settlement type;
  they are never merged or deduplicated by date.
- What happens when the provider returns an expiration already today (or
  one whose DTE computes to 0)? → It is included with DTE 0 whenever the
  effective cap is ≥ 1 (which validation guarantees), never silently
  dropped; DTE is always calendar days from today per the shared 008
  definition.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The MCP MUST expose a single expiration-list tool that,
  given exactly one underlying symbol, returns the upcoming expiration
  dates for that underlying's options.
- **FR-002**: Each listed expiration MUST include at minimum its
  expiration date, its DTE expressed in calendar days (same DTE definition
  as `get_option_chain`, spec 008), and its settlement type — so that
  multiple expirations on the same calendar date remain distinguishable.
- **FR-003**: The expiration list MUST be ordered from soonest to latest
  expiration.
- **FR-004**: The tool MUST support an optional DTE-ceiling parameter that
  limits results to expirations with DTE ≤ ceiling: when absent it applies
  a default cap of 60 calendar days; when present, any value ≥ 1 replaces
  the default cap with no hard upper limit — semantics identical to
  `get_option_chain`'s `dte_max` handling (spec 008 FR-005).
- **FR-005**: Every response MUST echo the effective ceiling applied
  (`dte_max_effective`: 60 or the requested value) so the agent can verify
  the applied window.
- **FR-006**: The default (curated) response MUST NOT contain strikes,
  option quotes, greeks, or any per-strike data — expiration metadata only.
- **FR-007**: The tool MUST validate the symbol and the DTE parameter
  before any upstream call and return structured validation errors
  (naming the constraint violated) consistent with the shared
  validation-error pattern of the existing tools.
- **FR-008**: The tool MUST return structured outcomes for the empty
  cases: "ceiling excluded all expirations" (retryable with a larger
  ceiling) and "underlying has no options" (non-retryable), reusing the
  established outcome envelope — never a second envelope (C-02).
- **FR-009**: The tool MUST return at most one upstream invocation per
  request (no pagination, no cursor, no hidden retry storms).
- **FR-010**: The tool MUST support an explicit extended passthrough flag
  that returns the provider's raw expiration-chain payload (C-09); the
  curated result remains the default.
- **FR-011**: The tool output MUST stay within its declared token budget
  for the default request, and the budget MUST be enforced by a
  token-usage test (C-05).
- **FR-012**: Tool responses MUST follow the shared
  `outcome`/`detail`/`retryable` envelope and curated-schema conventions
  established by specs 003/006/008/010/011 (C-02).
- **FR-013**: The tool MUST be read-only: it retrieves market metadata
  only, initiates no orders, and exposes no credentials.

### Key Entities *(include if feature involves data)*

- **Expiration**: one expiration available for an underlying's options.
  Attributes: expiration date, DTE in calendar days, and settlement type.
  Multiple entries may share a calendar date (for example, morning- and
  afternoon-settled) and are listed as separate entries, distinguished by
  settlement type. Provider-only flags beyond these three fields are
  surfaced via the extended passthrough.
- **Expiration window**: the effective DTE ceiling applied to the request
  (`dte_max_effective`), echoed back in every response.
- **Underlying symbol**: the single equity/ETF/index symbol whose option
  expirations are listed; one symbol per request.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Answering "which expirations exist for this underlying?"
  costs fewer than 1,000 tokens in the default request — versus the
  5,000–110,000 tokens a full `get_option_chain` call can consume for the
  same question (measured by the token-usage test).
- **SC-002**: The tool completes a single-symbol expiration-list request
  within 10 seconds under normal operating conditions (performance test).
- **SC-003**: 100% of curated responses contain expiration date, DTE, and
  settlement type only — zero strikes, quotes, greeks, or other per-strike
  data in the default output (verified by schema/content tests).
- **SC-004**: Exactly one upstream invocation occurs per tool request in
  every scenario, including errors and empty results (verified by
  integration tests with a fake provider).
- **SC-005**: The DTE-ceiling semantics are indistinguishable from
  `get_option_chain`'s: same default (60), same echo field
  (`dte_max_effective`), same empty-range outcome — verified by
  consistency tests against the 008 behavior.

## Assumptions

- The provider exposes an option-expiration-chain capability analogous to
  the full option-chain capability already wrapped by `get_option_chain`;
  the new tool wraps it rather than deriving the expiration list from the
  full chain payload (reuse before creation, C-03).
- The DTE-ceiling semantics mirror `get_option_chain` exactly (spec 008
  FR-005): default cap of 60 calendar days; any provided value ≥ 1
  replaces it; no hard upper limit. Confirmed in clarification session
  2026-11-03; no provider-side maximum divergence is assumed.
- DTE is computed in calendar days from the current date, exactly as
  spec 008 defines it; no trading-day DTE variant is introduced (KISS,
  C-04).
- One symbol per request suffices: expiration lists are cheap and
  agents rarely need multi-underlying comparisons in a single call; a
  multi-symbol variant would be speculative (YAGNI, C-04).
- The token budget for the default request is set at fewer than 1,000
  tokens (a typical underlying lists tens of expirations; at roughly ten
  tokens per expiration plus envelope overhead this fits comfortably);
  the exact budget is confirmed with a measured baseline during planning
  per constitution Principle V.
- Docs obligations apply as for every tool: `docs/tools.md` and
  `docs/CHANGELOG.md` are updated in the same commit that delivers the
  tool.