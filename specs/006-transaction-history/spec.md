# Feature Specification: Account Transaction History

**Feature Branch**: `006-transaction-history`

**Created**: 2026-10-23

**Status**: Draft

**Input**: User description: "Quiero agregar una nueva tool que permita pedir la historia de todos los movimientos que se hicieron en un rango de dias. Que se pueda especificar desde una fecha de inicio y hasta una fecha de fin. Que se pueda pedir que la historia se filtre por un instrumento particular, o que traiga todo. Lo movimientos no debe contener solo venta a compra de instrumentos, sino que tambien deben incluir transferencias, intereses, etc (todo)."

## Clarifications

### Session 2026-10-23

- Q: ¿Cuál debe ser la ventana máxima de consulta por request (rango inicio–fin) antes de exigir dividir la consulta? → A: 1 año.
- Q: ¿Contra qué zona horaria se interpretan las fechas de inicio y fin del rango? → A: Zona horaria del mercado de la cuenta (America/New_York), ambos bordes inclusivos.
- Q: ¿Cómo se reporta la categoría de cada movimiento — enum cerrado curado o texto del proveedor? → A: Enum cerrado curado con fallback `other`; el texto original del proveedor va solo en el detalle extendido.
- Q: ¿Cuántos movimientos trae como máximo una página de respuesta? → A: 50 movimientos por página.
- Q: (refinamiento en plan) ¿Cómo se clasifica un movimiento que el proveedor reporta como dividendo *o* interés sin distinguirlos? → A: valor de enum adicional `dividend_or_interest`; `interest`/`dividend`/`fee`/`corporate_action` quedan reservados sin mapeo upstream en v1.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Retrieve every movement over a date range (Priority: P1)

The AI agent, acting on the owner's behalf, needs a complete picture of
everything that happened in the owner's linked accounts during a period —
for example "what happened this month?" to reconcile cash flow, review
activity, or answer the owner's question about where money went. With a
single non-interactive request the agent supplies a start date and an end
date, and receives the history of **all** movements recorded in that
window: instrument purchases and sales, transfers in and out, interest
credited, dividends, fees, wire and ACH movements, corporate actions,
adjustments, and every other movement type the source exposes — not only
trades. Each movement is reported with everything needed to interpret it:
when it happened, what it was, and its monetary effect.

**Why this priority**: This is the core capability the user asked for —
"la historia de todos los movimientos en un rango". Without an
unfiltered, all-movement-types history over a date range, nothing else in
this feature has value.

**Independent Test**: Can be fully tested by requesting a known date range
for accounts with known activity (a trade, an interest credit, a
transfer) and verifying that every movement of every type present in the
reference data appears in the response with its date and amounts.

**Acceptance Scenarios**:

1. **Given** accounts with recorded activity (trades, transfers, interest,
   dividends, fees) in a date range, **When** the agent requests the
   history for that range, **Then** the response contains one entry per
   recorded movement of every type, each with its date, description,
   movement type, and monetary effect.
2. **Given** the same date range requested twice, **When** both requests
   complete, **Then** both responses contain the same set of movements
   (the history is a faithful, complete view, not a sample).
3. **Given** a date range with no recorded activity, **When** the agent
   requests the history, **Then** the response is an explicit, valid
   "no movements in range" result — not an error and not a fabricated
   partial answer.

---

### User Story 2 - Focus the history on one instrument (Priority: P2)

The AI agent reviewing a specific holding — for example the owner asks
"what happened with my AAPL position last quarter?" — needs the same
history but restricted to a single instrument. The agent repeats the
date-range query adding the instrument identifier as an optional filter,
and receives only the movements that involve that instrument within the
range: buys, sells, dividend or distribution postings tied to it, and any
other movement referencing it. Non-instrument movements (transfers,
interest, fees) are excluded from the response when the filter is active.

**Why this priority**: It is a refinement of Story 1 that adds focus and
payload economy, but it is independently valuable only once the base
history exists; the unfiltered history covers the primary need.

**Independent Test**: Can be fully tested by requesting a date range with
an instrument filter over reference data known to contain both
instrument-related and non-instrument movements, and verifying that only
movements referencing the instrument are returned.

**Acceptance Scenarios**:

1. **Given** a date range containing trades of several instruments plus
   non-instrument movements, **When** the agent requests the history
   filtered by one instrument identifier, **Then** the response contains
   only movements involving that instrument, and none of the transfers,
   interest, or fee movements.
2. **Given** a valid date range where the filtered instrument had no
   activity but other movements exist, **When** the agent requests the
   filtered history, **Then** the response is an explicit "no movements
   for this instrument in range" result that makes the empty result
   unambiguous.
3. **Given** the same date range, **When** the agent requests the history
   once without and once with the instrument filter, **Then** the
   filtered result is exactly the subset of the unfiltered result
   referring to that instrument (filter consistency).

---

### User Story 3 - Consume the history within a bounded, agent-friendly payload (Priority: P3)

The AI agent querying a long period (or a very active account) receives a
response that remains within a predictable size: the history is delivered
in a bounded, deterministic, ordered form — chronological ordering,
explicit count of the total movements found, and an explicit mechanism to
continue beyond the returned page when the complete history exceeds the
page size. The agent never receives a silently truncated list, and never
needs to guess whether more data exists.

**Why this priority**: This protects the agent's context budget on large
queries but does not add data capability; the feature is usable without
it for typical short ranges, so it comes after Stories 1 and 2.

**Independent Test**: Can be fully tested by querying a date range known
to contain more movements than one page holds, verifying the response is
bounded, explicitly states the total count, and that successive requests
continue exactly where the previous one stopped with no duplication and
no gaps.

**Acceptance Scenarios**:

1. **Given** a date range with more movements than fit in one response
   page, **When** the agent requests the history, **Then** the response
   contains a bounded page of movements in chronological order, the total
   number of movements found, and an explicit continuation indicator.
2. **Given** a continuation indicator from a previous response, **When**
   the agent requests the next portion of the same history, **Then** the
   response continues exactly after the last delivered movement, with no
   duplicated and no omitted movements, until the end of the range.
3. **Given** a date range whose movements fit within one page, **When**
   the agent requests the history, **Then** the response contains all
   movements and no continuation indicator.

---

### Edge Cases

- What happens when the end date is earlier than the start date? The
  response must be a clear validation error naming both dates, before
  any provider call is made.
- What happens when a date is malformed, in an impossible form, or in
  the future? The response must be a clear validation error describing
  the expected date form.
- What happens when the requested range exceeds the maximum query window
  the source supports? The response must be an explicit error stating
  the maximum window and inviting the agent to split the range into
  consecutive queries — never a silently shortened range.
- How are the date boundaries interpreted? The range is inclusive on
  both ends, and the calendar dates supplied by the agent are
  interpreted against the account's market timezone (America/New_York);
  the same range requested twice must yield the same set of movements.
- What happens when the filtered instrument identifier does not exist or
  is mistyped? The response must distinguish this from an empty result:
  a clear "instrument not found" error naming the identifier, not a
  "no movements" answer that would mislead the agent into believing the
  instrument simply had no activity.
- What happens when movements exist in multiple linked accounts? The
  query covers all linked accounts; movements must be attributable to
  their account, and if some accounts fail while others succeed the
  response must report the per-account failures explicitly (partial
  result), never silently dropping an account's history.
- What happens when the data source fails or is temporarily unreachable?
  The response must report the failure on the first failed attempt (no
  silent internal retries), so the agent can apply its own retry
  playbook; when re-authorization is required, the response must say so
  explicitly instead of failing opaquely.
- What happens when a movement has an amount in a currency other than
  the account's main currency? The movement must report the currency it
  is denominated in; the system must not silently convert or hide it.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST expose a single query capability through
  which the agent obtains the history of account movements between an
  explicit start date and an explicit end date, both supplied by the
  agent and both mandatory.
- **FR-002**: The system MUST include movements of **every** type the
  source exposes in the response — not only instrument trades —
  including at minimum: instrument purchases and sales, transfers in and
  out of the accounts, interest and dividend postings, fees and
  commissions, wire/ACH and other cash movements, corporate actions, and
  corrections/adjustments. The default query MUST be "everything"; no
  movement category may be excluded silently. Each movement MUST report a
  normalized category from a closed enum (trade, transfer, interest,
  dividend, dividend_or_interest, fee, corporate_action, adjustment,
  other) with `other` as the fallback for any movement type the enum does
  not cover; the provider's original category text MUST be exposed only
  in the on-demand extended detail. (`dividend_or_interest` exists
  because the source reports dividends and interest as a single,
  indistinguishable type; `interest`, `dividend`, `fee`, and
  `corporate_action` are reserved values with no upstream mapping in
  v1.)
- **FR-003**: The system MUST accept an optional instrument filter: when
  supplied, the response contains only movements referencing that
  instrument within the range; when absent, the response contains all
  movements regardless of type.
- **FR-004**: The system MUST validate the query before contacting the
  data source: both dates present and well-formed, end date not earlier
  than start date, and the range not exceeding the maximum query window
  of one year. Every violation MUST produce a distinct, actionable
  error stating what was wrong and what to change.
- **FR-005**: Every returned movement MUST be accompanied by, at minimum:
  the date and time it occurred, a human-readable description, its
  movement type or category, its monetary effect (amounts with their
  currency), the account it belongs to, and a reference to the
  instrument involved when one exists.
- **FR-006**: The response MUST present movements in a deterministic
  chronological order (oldest first), MUST state the total number of
  movements found for the query, and MUST NOT truncate silently: when
  the result exceeds one page, the response MUST deliver at most 50
  movements per page and provide an explicit continuation mechanism so
  the agent can retrieve the remainder without duplication or gaps.
- **FR-007**: The default response payload MUST be curated for agent
  consumption and kept compact; the complete set of fields available
  from the source for a movement MUST be obtainable on demand via an
  explicit request option. [Conforms to the payload policy established
  in features 003 and 005.]
- **FR-008**: The query MUST cover all linked accounts, consistent with
  the existing account-coverage policy; each movement MUST identify its
  account, and per-account failures MUST be reported explicitly as a
  partial result rather than omitted.
- **FR-009**: The system MUST return distinct, actionable errors for:
  (a) transient source unavailability, (b) expired or rejected
  credentials requiring human re-authorization, (c) an unknown or
  mistyped instrument filter, and (d) each validation failure of FR-004.
  The agent must be able to decide its next action from the error alone.
- **FR-010**: The system MUST NOT perform internal retries on transient
  source failures; it MUST report the failure on the first failed
  attempt so the agent can apply its own retry playbook. [Conforms to
  features 003 and 005 policy.]
- **FR-011**: Each query MUST emit audit events (start and terminal)
  through the auxiliary channel, containing no credentials, consistent
  with the audit policy of the existing tools.
- **FR-012**: The system MUST be read-only: retrieving the history MUST
  NOT place orders, move money, or otherwise alter account state.

### Key Entities *(include if feature involves data)*

- **Movement** (reported as `MovementEntry` in the data model): one
  recorded financial event in an account within the queried range. Attributes: occurrence date and time, human-readable
  description, movement type/category (a normalized category from the
  closed enum of FR-002 with `other` as fallback), monetary effect
  (amount(s) with currency), owning account, and instrument reference
  when one exists.
- **Instrument**: the tradable asset referenced by trade-like movements.
  Attributes: identifier (ticker symbol), asset type, human-readable
  name. Used both to annotate movements and as the optional filter key.
- **Account**: the linked account a movement belongs to. Attributes:
  account identifier (as exposed by the existing account-coverage
  machinery). Movement history is per-account, aggregated in one query.
- **HistoryQuery**: one request: start date, end date, optional
  instrument filter. Carries its own outcome in the response: success,
  empty, partial (per-account failures), transient failure, or
  re-authorization required.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An agent can obtain the movement history for a typical
  date range (up to one month of activity) in under 5 seconds from
  issuing the request, measured at the 95th percentile across a test set
  of at least 20 varied queries.
- **SC-002**: At least 95% of valid queries (well-formed dates within
  the maximum window) return a usable, complete-for-the-query result on
  the first attempt, with no agent-side retry needed.
- **SC-003**: The default response stays within a declared budget of
  16 KB for a one-page result (50 movements, as asserted by the
  project's token-usage tests); the documented expected payload size is
  published in the tool's documentation before release, including the
  worst case for a full page of movements.
- **SC-004**: Given reference data containing every movement type the
  source exposes, a query over a range covering that data returns 100%
  of the recorded movements — no type is silently dropped — as verified
  by a scripted completeness check against the reference data.
- **SC-005**: Every response, successful or not, lets the agent decide
  its next action without human help: success responses state the total
  count and whether more pages exist; empty responses distinguish "no
  movements in range" from "no movements for this instrument"; error
  responses state what was wrong and what to change, in every error
  category defined by FR-009.
- **SC-006**: The agent can reconstruct the complete history of a range
  exceeding one page using only the continuation mechanism, with zero
  duplicated and zero omitted movements, verified by a scripted
  pagination walk against reference data.

## Assumptions

- The capability is exposed as a real MCP tool registered by the server
  for direct consumption by an MCP client, following the precedent of
  `get_open_positions` (feature 003) and the metrics tools (feature
  005); no CLI one-shot command is required.
- The agent consuming the tool already holds a valid, authenticated
  session with the server; authentication is out of scope for this
  feature.
- The data source for the history is the same provider the project
  already integrates with; no external provider or new credentials are
  introduced. The set of movement types returned is exactly what that
  source exposes, and the response is a faithful projection of it.
- The maximum query window per request is one year; longer periods are
  covered by the agent issuing consecutive queries.
- Date semantics: calendar dates supplied by the agent are interpreted
  against the account's market timezone (America/New_York); both range
  boundaries are inclusive.
- When the instrument filter is supplied, movements are matched by the
  instrument identifier the source records; no fuzzy matching is
  performed.
- Audit events, retry policy, credential handling, and payload curation
  follow the decisions already established in features 003 and 005
  (listed in FR-007, FR-010, FR-011); this spec reuses rather than
  redefines them.
- Currency conversion is out of scope for v1: movements are reported in
  the currency the source records.
