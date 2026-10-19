# Feature Specification: Schwab OAuth Access

**Feature Branch**: `001-schwab-oauth-access`

**Created**: 2026-10-19

**Status**: Draft

**Input**: User description: "Usemos los detalles que se encuentran en .specify/assessments/api-engine/decision.md e implementemos inicialmente toda la parte de OAuth para poder usar las APIs."

## Clarifications

### Session 2026-10-19

- Q: ¿Cómo se dispara la autorización de primera vez: automática al iniciar el server sin token, o mediante un comando explícito? → A: Comando explícito de autorización, separado del arranque del server (server completamente headless).
- Q: ¿Cómo provee el dueño las credenciales de aplicación (API key y secret) al server? → A: Variables de entorno (opcionalmente vía archivo de entorno fuera del repo).
- Q: ¿El server valida el token proactivamente al arrancar o perezosamente al primer request? → A: Validación proactiva al arrancar: verifica el acceso con la API antes de quedar listo.
- Q: ¿Qué eventos de autenticación debe registrar el sistema en su bitácora local (sin secretos)? → A: Eventos clave: inicio/éxito/fallo de autorización y de renovación de token (timestamp + resultado, sin secretos).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - First-time authorization (Priority: P1)

The owner runs the dedicated authorization command for the first time.
The system initiates an OAuth authorization flow: the owner's browser
opens with the Schwab login page, the owner signs in and approves his own
registered application, and the system receives the authorization result
and stores the resulting credentials locally. From this point on, the
server holds valid access to the Schwab API on the owner's behalf. The
server itself stays headless at all times.

**Why this priority**: Without a first successful authorization, nothing
else in the project can work. This is the foundation of the decided
approach (Option B, assessment api-engine).

**Independent Test**: Can be fully tested by running the authorization
flow with valid configured credentials and verifying that a usable set of
tokens is stored locally and that subsequent authenticated API access
succeeds.

**Acceptance Scenarios**:

1. **Given** the server is configured with the owner's application
   credentials, **When** the owner runs the authorization command and
   completes the Schwab login in the browser, **Then** the system stores
   the resulting tokens locally and reports success.
2. **Given** the owner completes authorization, **When** the system
   requests a simple account read from the Schwab API, **Then** the read
   succeeds without any additional manual steps.

---

### User Story 2 - Silent reuse across sessions (Priority: P2)

On every later start, the server loads the stored tokens and establishes
authenticated access without any browser interaction. When the short-lived
access credential expires during or between sessions, the system renews it
automatically using the long-lived refresh credential.

**Why this priority**: The problem definition demands reads "without any
manual token fiddling between sessions" — reuse without friction is the
day-to-day value.

**Independent Test**: Can be fully tested by starting the server twice
with an already-stored token set and verifying no browser interaction is
required and authenticated reads succeed, including after simulating an
expired short-lived credential.

**Acceptance Scenarios**:

1. **Given** a valid stored token set exists, **When** the server starts,
   **Then** it proactively verifies access validity before signaling
   ready, and a subsequent account read succeeds with no browser
   interaction.
2. **Given** the short-lived access credential has expired but the
   refresh credential is still valid, **When** any Schwab request is
   made, **Then** the system renews access automatically and the request
   succeeds.

---

### User Story 3 - Recoverable failure states (Priority: P3)

When authentication cannot be established — expired refresh credential,
revoked access, wrong or missing application credentials, or a failed
login attempt — the server fails fast with a clear, actionable message
that tells the owner exactly how to recover (e.g., re-run authorization),
instead of surfacing a raw error or hanging.

**Why this priority**: Error paths are unavoidable but secondary; the
feature is valuable once stories 1–2 work. Clear recovery preserves trust
and avoids debugging rabbit holes.

**Independent Test**: Can be fully tested by forcing each failure
condition (missing credentials, invalid credentials, expired/invalid
token set) and verifying each produces a distinct, actionable error
message and a non-hanging failure.

**Acceptance Scenarios**:

1. **Given** no stored token set exists and the owner declines browser
   login, **When** the authorization flow is cancelled, **Then** the
   server exits with a clear message explaining how to retry.
2. **Given** the stored token set is expired beyond recovery, **When**
   the server starts and a request is attempted, **Then** the server
   reports that re-authorization is required, with the exact action to
   take, and does not hang.

---

### Edge Cases

- What happens when the callback URL/port is already in use during
  authorization? → The system reports the conflict clearly and aborts
  cleanly rather than hanging.
- What happens when the Schwab API is unreachable during a refresh
  attempt? → The system retries once, then fails with a clear
  connectivity message; the stored token set is not corrupted or deleted.
- What happens when authorization is attempted twice concurrently?
  → The second attempt is refused with a clear message; the first
  authorization is not corrupted.
- What happens when the stored token set file is corrupted or
  tampered with? → The system treats it as absent and requests
  re-authorization; it never crashes with a raw traceback.
- What happens when the configured application credentials are wrong?
  → The system fails fast at startup or first use with a message
  pointing at the configuration, not at a network error.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST initiate an OAuth 2.0 authorization flow that
  opens the owner's browser for Schwab login, triggered only by an
  explicit, dedicated authorization command — never implicitly during
  server startup.
- **FR-002**: System MUST receive the authorization callback and exchange
  the authorization code for an access/refresh token set.
- **FR-003**: System MUST persist the token set to local storage outside
  the repository (it MUST never be committed to version control), as a
  plain file readable only by the owner.
- **FR-004**: System MUST automatically renew expired short-lived access
  credentials using the refresh credential, without user interaction.
- **FR-005**: System MUST request the least-privileged access scope
  consistent with the project's read-only scope.
- **FR-006**: System MUST NOT write application credentials (API key,
  secret) or tokens to logs, error messages, or any tool output — zero
  occurrences, verifiable by automated checks. Exception: the
  authorization URL displayed during `auth` MUST include the client_id
  (app key) in full — it is public by OAuth design and the URL must be
  usable as-is (copy/paste into any browser, including a private window).
  The app secret, tokens, and authorization codes remain redacted
  everywhere, and the app key is redacted in every sink other than the
  displayed authorization URL (in particular, never logged).
- **FR-007**: System MUST detect unrecoverable authentication states and
  present a distinct, actionable recovery message per failure mode
  (missing config, invalid config, expired beyond recovery, user
  cancelled).
- **FR-008**: System MUST read application credentials exclusively from
  environment variables (optionally sourced from an environment file
  outside the repository) and MUST fail fast at startup when they are
  absent or malformed.
- **FR-009**: System MUST treat a corrupted or unreadable stored token
  set as absent (requesting re-authorization) rather than crashing.
- **FR-010**: System MUST support running the authorization flow again
  (re-auth) without corrupting an existing valid token set until the new
  authorization completes.
- **FR-011**: System MUST refuse concurrent authorization attempts with
  a clear message.
- **FR-012**: System MUST make the token storage location and callback
  address configurable, with sensible local defaults.
- **FR-013**: When a stored token set exists, System MUST proactively
  verify that access is still valid at startup, before signaling ready;
  an invalid token set MUST trigger the recovery messaging of FR-007 at
  startup rather than at first request.
- **FR-014**: System MUST log key authentication events — authorization
  start, authorization success/failure, and token renewal success/failure
  — each with timestamp and outcome, and MUST NOT include any credential,
  token material, or secret in log entries.

### Key Entities *(include if feature involves data)*

- **Application Credentials**: the owner's Schwab developer app key and
  secret; supplied via environment variables only; identifies the
  registered application; must never be exposed or persisted in the
  repository.
- **Token Set**: the short-lived access credential, the long-lived
  refresh credential, and its expiry information; lives only in local
  storage outside the repository.
- **Authorization Grant**: the one-time code delivered via the browser
  callback during first-time authorization; consumed once and never
  persisted.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A first-time authorization completes in under 2 minutes of
  owner interaction (excluding Schwab's own account-approval lead time).
- **SC-002**: Across at least 10 consecutive sessions within the refresh
  credential's validity window, zero manual logins are required.
- **SC-003**: Automated checks find zero occurrences of credential or
  token material (app secret, tokens, authorization codes; app key
  outside the displayed authorization URL) in logs, error output, or
  tool responses.
- **SC-004**: When a valid token set exists, the server completes its
  proactive startup access validation and reaches ready state within 5
  seconds of start.
- **SC-005**: Every failure mode listed in User Story 3 produces a
  distinct, actionable message (verified one-by-one) with no hanging
  process and no raw internal error surfaced.

## Assumptions

- Single user (the project owner), single Schwab account, local stdio
  server — per the assessment (api-engine) handoff and constitution.
- The owner has a registered, approved Schwab developer application (if
  not, registration/approval is an owner action that may take days; this
  feature assumes credentials exist when first run).
- Token storage defaults to a private location in the user's home
  directory (configurable per FR-012), stored as a plain file with
  owner-only restrictive permissions (decided 2026-10-19: simplicity
  over encryption-at-rest; KISS).
- The decided access route (assessment Option B) reuses an established,
  actively maintained Schwab API client library for the OAuth/token
  mechanics; this spec describes the required behavior, and
  `/speckit.plan` selects the concrete library wiring.
- The OAuth flow requires a one-time interactive browser login; headless
  operation applies to everything after that first login (US2).
