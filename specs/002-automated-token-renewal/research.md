# Research: Automated Token Renewal

**Feature**: `002-automated-token-renewal` | **Date**: 2026-10-19

All Technical Context items were resolved from feature 001 (no unknowns
carried over). This document records the research performed on
`schwabdev` 4.0.0 (source inspected at
`.venv/lib/python3.11/site-packages/schwabdev/`) and the resulting
design decisions.

---

## D1 — Renewal mechanics: reuse schwabdev's built-in refresh

**Decision**: Delegate the actual access-token refresh entirely to
`schwabdev.tokens.Tokens.update_tokens()` via `Client.update_tokens()`;
do not hand-roll the `refresh_token` OAuth grant.

**Rationale** (verified against schwabdev 4.0.0 source):

- `Client._request()` calls `update_tokens()` on **every** API request
  (`client.py:169-172`) — renewal is already wired into the operation
  path, exactly matching FR-011 (transparent to the caller).
- The preventive margin already exists: `update_tokens()` refreshes when
  `at_delta < access_threshold` with `access_threshold = 61 s`
  (`tokens.py:278-285`) — FR-001's "preventive with safety margin" is
  satisfied by the library; no additional margin logic of our own (DRY).
- Single-flight coordination already exists (FR-005):
  `_update_access_token()` holds a `threading.RLock` **and** a SQLite
  `BEGIN EXCLUSIVE` transaction across DB+HTTP, re-loading tokens from
  the DB first so a second process/instance that refreshed in between
  wins and the loser reports success (`tokens.py:288-325`).
- Refresh-token rotation persistence already exists (FR-009):
  `_set_tokens()` stores a new `refresh_token` from the provider response
  when present (`tokens.py:216-217`), alongside the unchanged
  `refresh_token_issued`.

**Alternatives considered**:

- *Hand-rolled `grant_type=refresh_token` call*: duplicates OAuth token
  handling, must re-implement locking, rotation persistence, and
  concurrency coordination — violates Principles II and III. Rejected.
- *Background scheduler/daemon refreshing on a timer*: a second renewal
  trigger with no requirement behind it (YAGNI); the margin-triggered
  lazy path covers every operation. Rejected.

---

## D2 — Outcome classification across a boolean-returning library

**Decision**: A thin `renewal.py` orchestration layer classifies every
renewal into exactly one of the four spec outcome classes
(`renewed` / `not_needed` / `transient_failure` / `reauth_required`)
using three signals, in order:

1. **Store status + timestamps** (local SQLite read, same read pattern as
   the existing `peek_store`): remaining validity vs. margin decides
   `not_needed` before any network call, and feeds `auth-status`.
2. **schwabdev result**: `update_tokens()` returning `True` → `renewed`.
3. **Failure disambiguation**: schwabdev returns `False` for *both*
   network errors and an invalid refresh token, logging the reason.
   `renewal.py` captures the `Schwabdev` logger records emitted during
   the call and matches stable message substrings ("network error" →
   transient; "refresh_token likely invalid" → permanent). As a
   tie-breaker probe, a lightweight authenticated call
   (`linked_accounts()` with a bounded timeout) distinguishes the
   remaining cases: 401 → `reauth_required`; connection error →
   `transient_failure`; success → `renewed` (another process renewed —
   consistent with the library's own coordination semantics).
4. **Interactive-flow guard**: when the refresh token is inside
   schwabdev's conservative window (< ~60.5 min remaining),
   `update_tokens()` routes to the authorization-code flow and our
   `call_on_auth` guard hook raises
   `ReauthorizationRequiredError` — caught and mapped to
   `reauth_required` (US3: the state is detectable, never a browser).

**Rationale**: schwabdev collapses error detail into logs; rather than
bypassing it (D1) or parsing its log *format* ad hoc everywhere, the
capture is localized to one function, and the probe tie-breaker keeps the
classification correct even if log wording changes. Every classification
path is unit-testable with stub clients/loggers.

**Alternatives considered**:

- *Treat every `False` as `reauth_required`*: would misreport transient
  network blips as permanent and trigger needless owner re-auth.
  Rejected (breaks FR-003's distinction).
- *Fork/patch schwabdev to raise typed errors*: maintenance burden; the
  probe + log capture is smaller. Rejected.

---

## D3 — Agent-facing interface: one-shot CLI subcommands

**Decision**: Expose `schwab-mcp renew` (explicit renewal action,
FR-002) and `schwab-mcp auth-status` (authentication health, FR-008) as
CLI subcommands that print one compact single-line JSON result on stdout
and exit with a code mapped to the outcome class.

**Rationale**: The decisive scenario for an unattended agent is exactly
when the server *cannot* start (re-authorization required, corrupted
store): MCP tools are unreachable then, but shell execution is not.
One-shot commands are non-interactive by construction, need no running
server, and keep `serve` fully headless. `renew` reuses the existing
`AuthLock` so a concurrent renewal refuses cleanly (exit `6`,
ConcurrentAuthError) instead of racing.

**Alternatives considered**:

- *MCP tools for renew/status*: unavailable precisely when the server is
  down; would also require tools registration infrastructure that this
  project deliberately defers. Tool wrappers can be added later as thin
  shims over the same `renewal.py` functions (no rework). Rejected for
  this feature.
- *Long-running status daemon / HTTP endpoint*: violates the
  no-inbound-sockets constraint and adds a process to manage (KISS).
  Rejected.

---

## D4 — Bounded retry: generalize, don't duplicate

**Decision**: Generalize the existing `retry_once` in `tokens.py` into a
single bounded-retry helper `retry_call(fn, retries=2)` (initial attempt
+ 2 retries, short fixed waits between attempts), used by both startup
validation and renewal (FR-006). Worst case fits the SC-002 budget:
3 attempts × 3 s timeout + 2 × 0.5 s waits = 10 s.

**Rationale**: One retry implementation (DRY); the 1-retry startup helper
already exists, so the change is a generalization, not a new mechanism.

**Alternatives considered**: keeping `retry_once` and adding a separate
2-retry helper — two implementations of the same idea. Rejected.

---

## D5 — Safety margin & lifetime source

**Decision**: Use the provider-communicated lifetime from the stored
token row (`expires_in`, issue timestamps) to compute remaining validity;
use schwabdev's built-in 61 s margin as *the* margin. `auth-status`
reports raw remaining seconds for access and refresh credentials.

**Rationale**: FR assumption "lifetime from the provider's own responses"
— `expires_in` is stored by schwabdev from the token response
(`tokens.py:223`). Adding a second, project-defined margin would create
two sources of truth (DRY).

---

## D6 — Audit events: extend, don't fork, the 001 taxonomy

**Decision**: Reuse the 001 event-log contract (`auth_event=` lines on
stderr, redaction-filtered) and add: `renew_start` (`initiated`),
`renewal_success` with outcomes `ok` | `not_needed`,
`renewal_failure` with outcomes `connectivity` | `reauth_required`
(FR-010).

**Rationale**: `renewal_success`/`renewal_failure` already exist in the
001 events contract; the feature only widens their outcome vocabulary and
adds one start event. No new event format.

---

## Open questions

None — all spec clarifications were resolved in
`spec.md → ## Clarifications` (2026-10-19): preventive-with-margin
trigger (B), 10 s budget, 2 retries with short waits.