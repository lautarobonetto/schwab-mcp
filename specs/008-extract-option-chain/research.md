# Research: Option Chain Extraction with Filters

Feature: 008-extract-option-chain | Date: 2026-10-23

## R1 — Provider endpoint and filter mapping

**Decision**: use `schwabdev.Client.option_chains(symbol, ...)` (endpoint
`/marketdata/v1/chains` of the Schwab Trader API) with:

- `contractType`/`optionType` ← type filter: `both→ALL`, `calls→CALL`,
  `puts→PUT`.
- `strikeCount` ← strike limit per side: the API returns N strikes above
  **and** below the money, which matches the filter semantics (50 per
  side by default).
- `fromDate` ← current date; `toDate` ← current date + DTE cap (60 by
  default or the requested value). The API does not accept a `fromDate`
  earlier than the current date, so the DTE window is expressed as a
  range of expiration dates.
- `includeUnderlyingQuote: true` to obtain the current price of the
  underlying (reference for the at-the-money strike and response
  metadata).

**Rationale**: it is the only chains endpoint exposed by the already
integrated SDK; it maps 1:1 with the spec filters and avoids fetching
expirations outside the DTE range (volume reduction at the origin, not
only at the destination).

**Alternatives considered**:
- `option_expiration_chain` (expiration dates only): useful as prior
  enumeration, but it would duplicate upcalls for the same information
  already carried by the `option_chains` payload (keys
  `callExpDateMap` / `putExpDateMap`). Rejected for DRY/KISS.
- API param `daysToExpiration`: operates as a point value, not a range
  cap. Rejected.

## R2 — Selection of the 5-strike window per target delta

**Decision**: the API does not filter by delta, so the selection is a
**local post-filter**:

1. When there is a target delta, the internal fetch requests
   `strikeCount = max(requested limit, 100)` (internal bound of 100) to
   guarantee that the zone of the target delta is inside the window
   returned by the API; when there is no target delta, the requested
   limit is requested (default 50).
2. For each expiration in the payload and each included type (CALLs and
   PUTs separately, delta in absolute value):
   - identify the contract with the delta closest to the target;
   - return that strike plus the two contiguous strikes on each side
     (up to 5, or all available around).
3. If the target is not bracketed within the internal window (target
   delta deeper than the fetched strikes), **one** second call widening
   the window (bound 200) is made; if it is still not bracketed, the
   available contracts closest to the target are returned.

**Rationale**: delta is monotonic in the strike within each type, so "5
around the closest one" is deterministic and verifiable; requesting a
higher internal strikeCount only when there is a delta filter avoids
inflating the volume of the default case.

**Alternatives considered**:
- Always requesting `range="ALL"` (the whole curve): unnecessary volume
  at the origin and a documented SDK risk of "Body buffer overflow" on
  large responses. Rejected.
- Iterating expiration by expiration: multiplies upcalls; rejected.

## R3 — DTE and expiration ordering

**Decision**: DTE = calendar days between the current date (server
local, date of the query) and the expiration date; expirations are
ordered ascending by date. The current cap (60 by default or the
requested value) filters out expirations with DTE > cap. A requested DTE
that excludes all expirations produces the explicit empty-chain response
(FR-009), not an error.

**Rationale**: match the trader's operative reading (DTEs of weekly
expirations are counted in calendar days) and the `fromDate/toDate`
window of the API.

**Alternatives considered**: DTE in market days; rejected because the
API filters by calendar dates and the use case (expiration selection)
uses elapsed days.

## R4 — Token budget and compact schema

**Decision**:

- **Columnar per-strike** output schema: each expiration contains a list
  of strike rows; each row has the strike and at most two arrays of
  values (`call` and `put`) in a **documented column order** declared in
  the payload itself (`contract_fields`). This removes the repetition of
  field names per contract (the largest cost of the key-value format)
  and the repetition of the strike value between legs.
- Deterministic rounding: prices/values to 2 decimals, Greeks and IV to
  4 decimals.
- Missing fields → explicit `null` in their column (meets FR-007 at
  minimal cost); no values are invented.
- Budget test (`tests/performance/test_options_chain_budgets.py`)
  measures the serialization of a representative fixture (liquid
  underlying, ~12 expirations, 100 strikes per expiration) against the
  normative budget of 75,000 tokens with defaults and < 3,000 with
  `delta_target` (SC-002; approximation: chars/4).

**Rationale**: the combination of spec defaults (50/side × 2 types × ~12
expirations × the curated superset) is inherently bulky; the columnar
schema is the only compaction lever that does not violate FR-006 (curated
superset) or FR-002/FR-005 (defaults). **Resolution of the 2026-10-24
clarification**: the default of 50 stays (user decision) and the
normative budget with defaults is set at **≤75,000 tokens** (SC-002),
with **<3,000** for calls with `delta_target`; justification recorded in
plan.md (Complexity Tracking, Principle V). The output declares the
expected size in `docs/tools.md`.

**Alternatives considered**:
- Key-value format per contract: ~2–3× more tokens. Rejected.
- Trimming low-utility fields (open/high/low/close of the leg): FR-006
  was bounded to the curated `contract_fields` superset + extended mode
  (clarification 2026-10-24), so this trimming is no longer necessary;
  the `extended` passthrough covers the rest.
- Pagination: violates FR-011 (a single invocation). Rejected.
- Reducing defaults (e.g. 25 strikes/side): rejected by user decision in
  the 2026-10-24 clarification (the default 50 stays and the budget
  rises to 75k with recorded justification).

## R5 — Errors, partials policy and reuse

**Decision**:

- Unwrapping and error classification: reuse `provider.response_json`
  (401/403 → re-auth; 5xx/408/429 → `ConnectivityError`; other 4xx →
  validation `ValueError`) and `tokens.retry_call` for transients.
- FR-013 policy: if the source fails or an entire expiration comes with
  no data (empty or missing expiration map), the tool aborts with a
  structured error without returning a partial chain.
- Filter validation **before** any upcall: unknown option type, delta
  with |delta| ∉ (0,1), strikes ≤ 0, dte ≤ 0, empty symbol → actionable
  validation error.
- New domain errors (minimal, same principles as 006):
  `no_options_listed` (the instrument has no options) and
  `no_expirations_in_range` (the DTE cap excludes all expirations) —
  communicated as structured results, not as transport errors (FR-009).

**Rationale**: reuses the single already-proven taxonomy (Principles II
and III) and separates "no data" from "failed" so the agent can decide
the next step.

**Alternatives considered**: a new taxonomy for this tool; rejected as
duplication.

## R6 — Field curation per contract

**Decision**: include per leg the fields the source exposes that
contribute to the analysis of option positions, excluding
structural/transport noise:

- **Quote**: `bid`, `ask`, `last`, `mark`, `markChange`,
  `markPercentChange`, `highPrice`, `lowPrice`, `openPrice`,
  `closePrice`.
- **Liquidity**: `totalVolume`, `openInterest`.
- **Risk/Greeks**: `volatility` (IV), `delta`, `gamma`, `theta`, `vega`,
  `rho`, `theoreticalOptionValue`, `timeValue`.
- **Reference**: `multiplier`, `daysToExpiration`, `tradeTime`,
  `deliverableNote` (relevant for assignment in LEAPs).
- **Excluded**: `skipBars`, `isPitRanged`, `executable`,
  `settlementType`, `deliverables` (structural, with no analysis value;
  available via `extended=true` with passthrough of the raw payload,
  pattern of 003/006).

**Rationale**: meets FR-006 ("all the Greeks and all the available
technical values") with a deterministic and declared curation; the
`extended` passthrough preserves access to 100% of the payload without
inflating the curated format.

**Alternatives considered**: raw passthrough as the only format;
rejected because the API payload is a verbose key-value format
(multiplies the token cost ~2–3×) and mixes structural metadata.