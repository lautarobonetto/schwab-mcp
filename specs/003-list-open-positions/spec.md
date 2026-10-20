# Feature Specification: List Open Positions

**Feature Branch**: `003-list-open-positions`

**Created**: 2026-10-20

**Status**: Draft

**Input**: User description: "Agregar una tool que permita conocer todas las posiciones que se encuentran abiertas en este momento, y que con cada una de ellas se provean todos los metadatos relacionados."

## Clarifications

### Session 2026-10-20

- Q: ¿En qué superficie se expone la capacidad: como tool del servidor MCP, como comando one-shot de la CLI, o ambas? → A: Tool MCP real, registrada por el servidor para consumo directo vía cliente MCP (sin pasar por shell).
- Q: ¿"Todos los metadatos relacionados" significa el conjunto completo de campos que provee la fuente de datos, o un conjunto curado optimizado para consumo por un LLM dentro de un presupuesto de tokens? → A: Conjunto curado completo para agentes (todos los campos que un agente necesita para entender y decidir sobre cada posición), con campos adicionales del proveedor disponibles bajo demanda mediante una petición explícita; el payload por defecto se mantiene compacto.
- Q: ¿Qué frescura deben tener el valor de mercado y el P/L no realizado que se reportan por cada posición? → A: En vivo cuando el mercado está abierto, último cierre cuando está cerrado; siempre incluyendo la marca de tiempo del precio usado.
- Q: ¿Qué identifica únicamente a cada entrada de posición en la respuesta? → A: Una entrada por (cuenta, instrumento): los lotes del mismo instrumento se consolidan con costo promedio, cada contract de una estrategia multi-pata (strangle, condor, roll) aparece como entrada separada, y la cantidad es con signo (largo positivo, corto negativo).
- Q: ¿La consulta de posiciones debe emitir eventos de auditoría (inicio/resultado) como ya lo hacen la renovación y autorización del sistema? → A: Sí: evento de inicio + evento terminal en cada consulta, igual que las renovaciones, sin secretos y por el canal auxiliar.
- Q: ¿Qué política de reintentos internos debe aplicar la consulta ante fallos transitorios del proveedor? → A: Sin reintentos internos: reporta el fallo transitorio en el primer intento fallido; el agente reintenta según su playbook.
- Q: ¿Qué debe incluir exactamente "posiciones abiertas"? → A: Solo tenencias efectivas con cantidad con signo no cero; las órdenes abiertas/pendientes quedan explícitamente fuera de alcance (feature futuro posible).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Single-query snapshot of all open positions (Priority: P1)

The AI agent, acting on the owner's behalf, needs to know what is
currently held in the account(s). With one simple, non-interactive
request, it obtains the complete set of positions that are open at this
moment, each with its related metadata. The agent does not need to
issue one request per position, per account, or per data type: a single
query returns the full current picture, in a compact, machine-readable
form it can reason over without human help.

**Why this priority**: This is the core capability the user asked for.
Without it, the agent has no way to ground any portfolio-related
decision in reality.

**Independent Test**: Can be fully tested by seeding a known set of
open positions and invoking the single query, verifying the response
contains exactly the open positions present at that moment, each with
its metadata, and nothing else.

**Acceptance Scenarios**:

1. **Given** the account(s) hold one or more open positions, **When**
   the agent performs the single positions query, **Then** the response
   contains every currently open position, each identified and
   accompanied by its related metadata.
2. **Given** the account(s) hold no open positions at all, **When** the
   agent performs the query, **Then** the response is a valid,
   structured empty result (not an error), so the agent can distinguish
   "no positions" from "the query failed".
3. **Given** positions were opened or closed between two consecutive
   queries, **When** the agent performs the query again, **Then** the
   response reflects the state at the moment of the new query (fresh
   data, not a stale cached copy).

---

### User Story 2 - Complete metadata for each position (Priority: P2)

For every position returned, the response includes all the related
metadata the agent needs to reason about it without further lookups:
what instrument it is, how much is held, at what average cost it was
acquired, what it is worth at the current moment, how it has performed
(unrealized gain/loss), and any classification the source provides
(instrument type, identifiers). The agent never has to fire a second
query just to understand a position it already received.

**Why this priority**: The user explicitly asked for "todos los
metadatos relacionados" with each position; metadata completeness is a
defining part of the feature, not an afterthought. It is ranked after
the core query because it refines what the query returns rather than
being a separate capability.

**Independent Test**: Can be fully tested by seeding positions of
different instrument types and verifying that each returned position
carries the complete metadata set defined for the feature, with no
missing fields and no secret-bearing content.

**Acceptance Scenarios**:

1. **Given** an open position in any supported instrument type, **When**
   the agent receives it in a positions query result, **Then** the
   position entry includes identification, quantity, average cost
   basis, current market value, unrealized gain/loss, and the
   instrument classification provided by the source.
2. **Given** several open positions across different accounts, **When**
   the agent receives the results, **Then** each position entry
   indicates which account it belongs to, and positions from different
   accounts are never merged or confused with each other.
3. **Given** a position whose metadata contains a field the agent
   cannot interpret, **When** the agent inspects the entry, **Then**
   the field is self-describing (named and typed in a documented,
   stable schema) rather than an opaque blob.

---

### User Story 3 - Predictable failure behavior consistent with the agent playbook (Priority: P3)

When the positions query cannot be completed — transient network or
provider failure, or credentials that require re-authorization — the
agent receives a small, structured, machine-readable failure that
classifies itself consistently with the existing authentication
playbook: transient failures tell the agent that retrying later is
safe; re-authorization-required failures tell the agent to stop and
notify the owner. The agent never has to guess what a failure means or
whether retrying is safe.

**Why this priority**: Failure handling already has an established,
agent-consumable pattern in this system (transient vs
re-authorization-required); this story only requires the new capability
to conform to it. It cannot be exercised until the core query exists.

**Independent Test**: Can be fully tested by forcing transient failures
and a rejected-credential state and verifying the query returns the
same structured failure classes the existing commands use, with
correct retryability semantics.

**Acceptance Scenarios**:

1. **Given** the provider is unreachable or returns a transient error,
   **When** the agent performs the query, **Then** the response is a
   compact structured failure that identifies the situation as
   transient (retry later is safe), with no partial or misleading
   position data.
2. **Given** the stored credentials are rejected by the provider, **When**
   the agent performs the query, **Then** the response is a compact
   structured failure consistent with the existing
   "re-authorization required" indication used by other commands.
3. **Given** any failure response, **When** the agent inspects it,
   **Then** it contains no secret values and no truncated or partial
   position list presented as if it were complete.

---

### Edge Cases

- What happens when an account has positions but the provider reports them with zero quantity (e.g., fully closed but not yet settled)? Zero-quantity entries are omitted entirely (per FR-015, only effective holdings are included); the agent never sees ghost positions.
- What happens when the provider returns more positions than a typical response can carry comfortably? The response size stays within the declared budget via a documented, deterministic strategy (documented payload expectation per position), rather than silently truncating.
- What happens when the query runs concurrently with a credential renewal triggered by another operation? The query either succeeds with valid credentials or returns the consistent authentication failure; it never corrupts state and never deadlocks.
- What happens when different accounts are involved and one of them cannot be queried? The response unambiguously indicates partial failure (which accounts succeeded, which failed and why) instead of silently omitting accounts.
- What happens when the agent queries immediately after server start? The query works like any other moment; there is no warm-up requirement.
- What happens when the agent requests extended metadata but the provider has no additional fields for a given position? The response indicates cleanly that no extended metadata exists for that position, rather than failing or returning empty noise.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST expose a single, simple, non-interactive
  capability, registered as a tool of the MCP server for direct
  consumption by MCP clients, that returns all positions currently open
  across the owner's linked account(s) at the moment of the query.
- **FR-002**: The response MUST be a compact, machine-readable,
  structured result — exactly one parseable result with no
  human-oriented free text the agent must interpret.
- **FR-003**: Every position entry MUST include the complete curated
  metadata set for agents — at minimum: instrument identification
  (symbol and instrument type as classified by the source), quantity
  held, average acquisition cost, current market value, unrealized
  gain/loss, and instrument classification — enough to understand and
  reason about the position with no follow-up query for required
  metadata.
- **FR-003a**: Additional provider-provided metadata fields beyond the
  curated set MUST be available under explicit on-demand request from
  the agent; the default response payload MUST stay compact (extended
  fields are never included unless requested), and an extended request
  MUST never be required to understand any position returned by the
  default response.
- **FR-004**: Every position entry MUST indicate the account it belongs
  to; positions from different linked accounts MUST NOT be merged.
- **FR-005**: When no positions are open, the system MUST return a
  valid, structured empty result (distinguishable from a failure), not
  an error.
- **FR-006**: The data returned MUST reflect the state at the moment of
  the query; the system MUST NOT serve stale cached position data in
  place of a live query.
- **FR-007**: Failure outcomes MUST be structured and self-classifying,
  consistent with the established outcome classes of the existing
  commands: transient failure (safe to retry later) and
  re-authorization required (stop retrying, notify the owner). The
  query MUST NOT retry internally: a transient failure is reported on
  the first failed attempt, and retrying is the agent's decision per
  its playbook.
- **FR-015**: The result MUST include only effective holdings (signed
  quantity not zero). Open or pending orders MUST NOT be included and
  MUST be declared out of scope in the documented contracts; if the
  agent needs order state, that is a separate future capability.
- **FR-008**: No response — success or failure — MUST contain secret
  values (tokens, credentials, authorization URLs).
- **FR-009**: The positions query MUST respect the declared time budget
  (performance) and the declared output-size budget (token usage), with
  both budgets documented before implementation and enforced by tests.
- **FR-010**: When multiple linked accounts exist and at least one fails
  while others succeed, the response MUST indicate partial failure
  unambiguously (which accounts succeeded, which failed and why) rather
  than silently omitting data.
- **FR-011**: The schema of position entries MUST be stable and
  documented (field names, types, and semantics) so agents can consume
  it without discovering it by trial and error; documented behavior and
  contracts MUST be updated in the same change that ships the feature.
- **FR-012**: Market value and unrealized gain/loss MUST reflect the
  price the provider used when generating the payload — live during
  market hours, last close outside them (provider behavior, not
  locally computed); every position entry MUST include the timestamp
  at which that priced payload was retrieved, so the agent can judge
  freshness without extra queries and never attributes more freshness
  than the data actually has.
- **FR-013**: Each position entry MUST be uniquely identified by
  (owning account, instrument): multiple lots of the same instrument
  MUST be consolidated into one entry with average acquisition cost,
  and each contract of a multi-leg strategy (strangle, condor, roll)
  appears as its own separate entry. Quantity MUST be signed (long
  positive, short negative) so short legs of sold strategies are
  unambiguous.
- **FR-014**: Every positions query MUST emit audit lifecycle events
  (one start event followed by exactly one terminal event with the
  outcome) in the auxiliary output channel, without secrets,
  consistent with the audit pattern established for renewal and
  authorization. Audit events MUST NOT inflate the query result
  payload.

### Key Entities *(include if feature involves data)*

- **Position**: A holding currently open in an account, uniquely
  identified by (owning account, instrument): instrument identifier and
  type, signed quantity (long positive, short negative; lots of the
  same instrument consolidated with average cost basis), current market
  value (with the timestamp of the price used, per the pricing
  freshness clarification), unrealized gain/loss, plus the additional
  metadata fields defined by the clarification on metadata scope.
  Snapshot data, not persisted by this feature. Each contract of a
  multi-leg strategy (strangle, condor, roll) is its own position
  entry; strategy-level grouping is the consumer's job.
- **Account**: A linked brokerage account identified by an opaque
  identifier safe to display; the scope boundary that groups positions.
- **Positions result**: The single structured response: either the
  complete list of open positions with metadata, a valid empty list,
  or a self-classifying failure. Contains no secrets.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The agent obtains the complete current picture of open
  positions (all linked accounts, all positions, the full curated
  metadata set) with exactly one default query — no follow-up query is
  ever needed for required metadata (target: 100% of positions fully
  described by the single default response). Extended, on-demand
  metadata (FR-003a) is supplementary and never blocks understanding a
  position.
- **SC-002**: A positions query completes within 5 seconds under normal
  network conditions (measured at the point where the agent invokes
  the capability), so it fits an interactive agent workflow.
- **SC-003**: The response size stays within a declared, documented
  budget for a representative portfolio (e.g., up to 50 open
  positions), measured consistently for every invocation; growth beyond
  the budget requires recorded justification.
- **SC-004**: 100% of responses (success, empty, partial failure,
  transient failure, re-authorization required) are machine-readable
  and self-classifying — the agent never needs to interpret free text
  or guess the meaning of an outcome.
- **SC-005**: Zero secret occurrences across all responses and
  associated audit events (verified by test on every invocation shape).
- **SC-006**: When no positions are open, the agent can distinguish
  "no positions" from "query failed" with certainty in a single
  response (100% of empty-state invocations unambiguous).

## Assumptions

- The consumer of this capability is the same unattended AI agent that
  uses the rest of the system's agent-facing surface; there is no
  human mid-session and no interactive step of any kind is acceptable.
- Out of scope (explicit): open or pending orders (including working
  legs of a strategy being rolled), watchlists, historical positions,
  and realized gain/loss. Only effective holdings with non-zero signed
  quantity are in scope (per the 2026-10-20 clarification).
- Positions are read-only data: this feature does not place orders,
  close positions, or move money. Read/write discipline of the
  constitution is respected by scope: no write operations are
  introduced.
- "Posiciones abiertas" means holdings with non-zero quantity at the
  moment of the query as reported by the provider; how the provider
  reports closed-but-unsettled lots is treated as an edge case with one
  documented, consistent behavior.
- Multi-account scope defaults to "all linked accounts in one query",
  with each position tagged by account, since the accounts are already
  linked and enumerable at authorization time; no per-account setup is
  required from the owner.
- Output size is expected to grow relative to the existing few-hundred-byte
  commands (it carries per-position metadata), so a per-feature token
  budget will be declared and enforced per constitution Principle V;
  the exact budget is fixed during planning. The default response uses
  the curated metadata set to stay compact; extended on-demand
  metadata increases payload only when explicitly requested, and that
  growth must also be declared and justified.
- Exposure as an MCP tool establishes the server's first registered
  tool; the pattern chosen here (registration, structured result
  schema, outcome classes) is expected to become the reference for
  future tools, per the user's decision in the 2026-10-20
  clarification session.
