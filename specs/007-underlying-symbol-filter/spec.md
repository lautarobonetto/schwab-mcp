# Feature Specification: Underlying-Aware Symbol Filter and Underlying Reference for Transaction History

**Feature Branch**: `007-underlying-symbol-filter`

**Created**: 2026-10-24

**Status**: Draft

**Input**: User description: "Lo que busco es que los agentes puedan usar la tool de get_transaction_history con el filtro `symbol=\"NOK\"` y que la tool pueda mostrar tanto los subyacentes, como las opciones que tienen \"NOK\" como parte del OCC." (extends the improvement note: derive/document the underlying symbol in every movement so agent-side filtering is trivial)

## Clarifications

### Session 2026-10-24

- Q: ¿Cómo se matchea un filtro de símbolo contra opciones? → A: el filtro aplica al **subyacente**: un movimiento involucra al instrumento filtrado si su símbolo registrado es exactamente el filtro (acciones, efectivo etiquetado) **o** si es una opción cuyo **root** (el identificador del subyacente al inicio del símbolo de opción estándar) es el filtro. Comparación exacta, insensible a mayúsculas/minúsculas. Sin fuzzy matching.
- Q: ¿Qué pasa si el agente pasa como filtro un símbolo OCC completo de una opción? → A: **Soportado**: si el filtro matchea un símbolo de opción exacto registrado por la fuente, la tool devuelve los movimientos de esa opción puntual (además del matcheo por subyacente).
- Q: ¿Qué pasa si el filtro no se resuelve en el directorio de instrumentos pero hay movimientos con ese root/símbolo? → A: **Validación dual**: primero se consulta el directorio; si no resuelve el filtro, se intenta la consulta igual y solo se reporta `instrument_not_found` si además no hay movimientos que matcheen (ni por símbolo registrado, ni por root, ni por símbolo de opción completo).
- Q: ¿De dónde sale el subyacente de un movimiento de opción? → A: del **root** del símbolo de opción estándar registrado por el proveedor (la propia cadena codifica subyacente, vencimiento, tipo y strike); el proveedor no expone el subyacente como campo separado en ese payload.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Filter the history by underlying instrument (Priority: P1)

The AI agent reviewing "everything that happened with NOK" supplies the
instrument identifier it knows — the underlying ticker, `NOK` — and
receives **all** movements involving that instrument in the range, in
whatever form the source recorded them: transactions registered under the
underlying itself, and option transactions whose option symbol belongs to
that underlying (for example puts and calls with `NOK` as the option
root). Today a filtered query only returns movements registered under the
exact supplied symbol, so option activity is invisible to an underlying
filter and the agent is misled into believing there was no activity.

**Why this priority**: This is the core value of the feature — a filter
that tells the truth about an instrument's activity. Without it, the
agent must pull the entire unfiltered history and filter on its own,
wasting context budget and risking wrong "no movements" conclusions.

**Independent Test**: Can be fully tested with reference data containing
equity movements registered under an underlying and option movements
whose option root matches that underlying: a filtered query must return
both groups and nothing else.

**Acceptance Scenarios**:

1. **Given** a date range containing equity movements registered under
   `NOK` and option movements whose option root is `NOK`, **When** the
   agent queries the history with `symbol="NOK"`, **Then** the response
   contains every movement of both groups and none of the movements of
   unrelated instruments.
2. **Given** the same date range queried without a filter, **When** the
   agent queries with `symbol="NOK"`, **Then** the filtered result is
   exactly the subset of the unfiltered result whose movements involve
   `NOK` in either registered form (filter consistency).
3. **Given** a valid range where the underlying had no activity in any
   form, **When** the agent queries with the filter, **Then** the
   response is an explicit "no movements for this instrument" result —
   never a fabricated partial answer.
4. **Given** a date range containing movements of a specific option
   (registered under its complete option symbol), **When** the agent
   queries with that complete option symbol as the filter, **Then** the
   response contains exactly the movements of that option — without the
   provider-side rejection that occurs today.
5. **Given** a filter whose underlying is not resolvable in the
   instrument directory but movements matching that filter exist (for
   example options whose root matches), **When** the agent queries the
   history, **Then** those movements are returned — the "instrument
   not found" error appears only when nothing matches in any form.

---

### User Story 2 - See the underlying of every option movement (Priority: P2)

The AI agent reading an unfiltered (or filtered) history needs to know,
for every option movement, **which underlying instrument** that option
belongs to, without needing to parse option symbols itself and without
requesting the extended detail. Each option movement carries the
underlying instrument identifier as a first-class, curated field; the
option symbol remains as the precise instrument reference. This makes
agent-side grouping ("all NOK activity"), scanning and follow-up
filtering trivial.

**Why this priority**: It completes the story: the filter (US1) answers
"give me NOK"; this field answers "what is this movement about" for
every row, including unfiltered queries. It is additive and valuable on
its own once the history exists.

**Independent Test**: Can be fully tested by querying a range known to
contain option movements and verifying every option movement exposes the
underlying identifier, while non-option movements are unchanged.

**Acceptance Scenarios**:

1. **Given** a date range containing option movements, **When** the
   agent queries the history (filtered or not), **Then** every option
   movement includes the underlying instrument identifier as an explicit
   field alongside the option symbol.
2. **Given** a date range containing only non-option movements (transfers,
   interest, cash), **When** the agent queries the history, **Then** the
   output is unchanged from the previous behavior (no new empty fields
   for movements that have no underlying).

---

### Edge Cases

- What happens when the agent supplies a complete option symbol as the
  filter? It must be treated as a valid, first-class filter for that
  exact option — the provider-side rejection that occurs today (the
  source rejects the padded option symbol outright) must be replaced by
  a correct filtered result or an honest empty result, never an opaque
  partial failure.
- What happens when the filtered instrument does not exist or is
  mistyped? The response must remain a distinct "instrument not found"
  error naming the identifier — not an ambiguous empty result. Under
  the dual-validation rule, the error is confirmed by the query
  outcome: no directory entry **and** no movements matching the filter
  in any registered form.
- What happens when the agent supplies the filter in lowercase (for
  example `nok`)? Matching must be case-insensitive so the same set of
  movements is returned; the result must equal the uppercase query's
  result.
- What happens when an option's root differs from its listed underlying
  identifier (flexible/expired conventions, special symbols)? Matching
  uses the root of the option symbol as recorded by the source; if the
  root is not identifiable, the movement simply does not match (it
  still appears in unfiltered queries) — never a failure of the whole
  query.
- What happens when the filtered instrument has equity activity but no
  option activity (or vice versa)? The response contains exactly the
  movements that exist in either form; absence in one form is not an
  error.
- What happens when the filter names an internal cash identifier (for
  example `CURRENCY_USD`) that the instrument directory does not
  resolve? Under the dual-validation rule the query decides: movements
  whose recorded symbol matches the filter are returned; only a
  matchless filter produces "instrument not found". The documented
  caveat of feature 006 is updated accordingly.
- What happens to pagination when the filtered set exceeds one page?
  Ordering, page size, total count and continuation must behave exactly
  as in the unfiltered case, computed over the filtered set.
- What happens when some accounts fail during the query? Per-account
  failures must be reported explicitly as a partial result, as today.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: When a symbol filter is supplied, the history response
  MUST include every movement in the range that involves the filtered
  instrument under **any** form the source registers it: movements whose
  recorded symbol matches the filter exactly, option movements whose
  option root matches the filter, and — when the filter itself is a
  complete option symbol registered by the source — the movements of
  that exact option. The response MUST NOT silently omit any of these
  groups.
- **FR-002**: Matching MUST be exact, not fuzzy: the comparison is
  between the filter and (a) the recorded symbol, (b) the root of the
  option symbol, or (c) the complete option symbol, using case-
  insensitive exact equality. No substring, prefix-inside-root, or
  similarity matching.
- **FR-003**: The filter MUST be validated against the source's
  instrument directory as a first step. When the directory does **not**
  resolve the filter, the tool MUST NOT fail immediately: it MUST
  attempt the query and report the distinct "instrument not found"
  error naming the identifier **only** if no movements match the filter
  under FR-001's matching rule. A mistyped symbol therefore still
  produces the honest error (no directory entry and no matching
  movements), while a valid-but-unlisted option root with actual
  activity returns its movements.
- **FR-004**: Every option movement in the **curated** output MUST
  include the underlying instrument identifier as an explicit,
  first-class field (for example `underlying_symbol`), derived from the
  option symbol registered by the source. Non-option movements MUST NOT
  carry the field. The extended detail remains available on demand and
  unchanged in content policy.
- **FR-005**: For the same date range, the filtered result MUST be
  exactly the subset of the unfiltered result formed by the movements
  that involve the filtered instrument under FR-001's matching rule
  (filter consistency, inherited and strengthened from feature 006).
- **FR-006**: Pagination semantics MUST be unchanged: deterministic
  chronological order, bounded pages, explicit total count and
  continuation for the **filtered** set, with no duplication or gaps.
- **FR-007**: The default payload MUST stay within the declared budget
  of feature 006 (16 KB per 50-movement page) **including** the new
  underlying field; the budget must not grow silently. The documented
  expected payload size must be updated in the tool's documentation.
- **FR-008**: Multi-account coverage and per-account partial-failure
  reporting MUST be unchanged from feature 006 (every movement
  attributable to its account; per-account failures explicit).
- **FR-009**: Audit events, the no-internal-retries policy and strict
  read-only behavior MUST be unchanged from feature 006's established
  policies.
- **FR-010**: The tool's documentation MUST describe the new matching
  semantics (underlying-aware filter, option-root rule, case
  insensitivity) and the new field, replacing the operational caveat
  that previously instructed agents to filter client-side.

### Key Entities *(include if feature involves data)*

- **MovementEntry** (existing, extended): one recorded financial event.
  New attribute: **underlying instrument reference** — the identifier of
  the underlying instrument for option movements (absent for non-option
  movements). Existing attributes unchanged: occurrence date/time,
  description, category, monetary effect, account, instrument symbol.
- **HistoryQuery** (existing, semantics extended): the `symbol` filter
  now identifies an instrument **by underlying**: it matches the
  instrument itself and every option whose root is that instrument. The
  outcome vocabulary (success, empty, partial, transient, re-auth) is
  unchanged.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Given reference data containing movements registered under
  an underlying and option movements whose root is that underlying, a
  filtered query returns 100% of those movements — verified by a
  scripted completeness check against the reference data (the scripted
  check is the fixture-based unit test of the filtered query; its
  end-to-end counterpart is scenario S1 of the quickstart, executed
  against the real provider).
- **SC-002**: For any date range, the filtered result is exactly the
  subset of the unfiltered result implied by the matching rule —
  verified by a scripted set-difference check (no extra, no missing
  movements).
- **SC-003**: 100% of option movements in any response expose the
  underlying instrument identifier in the curated output — verified by a
  scripted field-presence check.
- **SC-004**: The default 50-movement page remains within the declared
  16 KB budget with the new field included, and the p95 latency budget
  of the tool (≤ 5 s) is maintained — verified by the existing
  performance and token-usage test suites.
- **SC-005**: An agent can obtain the complete activity of one
  underlying (equity + options) in a **single** filtered query — no
  second unfiltered sweep required — as demonstrated by the scripted
  completeness check of SC-001 executed end-to-end through the tool
  interface.

## Assumptions

- The option root is defined by the standard option symbol convention
  the source records (root = leading instrument identifier, before the
  expiry/type/strike encoding). The tool derives the underlying from
  this registered symbol; the source does not expose the underlying as
  a separate field in this payload.
- Case insensitivity applies to the filter comparison only; output
  symbols are reported exactly as the source records them.
- The instrument-not-found validation continues to use the source's
  instrument directory for the supplied underlying (unchanged from
  feature 006); option-level validation is not added.
- How the tool assembles the composite filtered result (given that the
  source cannot filter option transactions by underlying) is a planning
  concern: this spec defines the outcome, not the method.
- Pagination, audit, retry policy, credential safety, payload curation
  and multi-account coverage follow the decisions already established in
  features 003 and 006; this feature reuses rather than redefines them.
- The 16 KB default-page budget from feature 006 remains the declared
  budget; if the underlying field makes it unattainable, the change
  requires an explicit, recorded justification (constitution, Principle
  V) rather than a silent budget increase.
