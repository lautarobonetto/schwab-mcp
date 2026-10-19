# Tasks: Automated Token Renewal

**Input**: Design documents from `/specs/002-automated-token-renewal/`

**Prerequisites**: plan.md ✅ · spec.md ✅ · research.md ✅ · data-model.md ✅ · contracts/ ✅ · quickstart.md ✅

**Tests**: INCLUDED — Constitution Principle I (Test-First Development) is
NON-NEGOTIABLE for this project: every task below writes its failing tests
FIRST, then the minimal implementation that passes them (Red → Green →
Refactor). Performance and token-usage tests are mandatory gates
(Principle V).

**Organization**: Tasks grouped by user story (US1 P1 → US2 P2 → US3 P3
from spec.md) so each story is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

Single project (per plan.md): `src/schwab_mcp/`, `tests/{unit,integration,performance}/` at repository root.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the feature-001 baseline before any change.

- [X] T001 Run the full existing test suite (`uv run pytest`) and confirm a green baseline (all `tests/` passing, no skipped tests) before modifying any file

**Checkpoint**: Baseline green — work may begin.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared building blocks every user story depends on. No user story work may begin until this phase is complete.

- [X] T002 [P] Add failing tests for the generalized bounded-retry helper — initial attempt + exactly 2 retries with short fixed waits, `ConnectivityError` after exhaustion, stored credentials never deleted/rewritten on failure (FR-006) — in tests/unit/test_tokens.py
- [X] T003 Generalize `retry_once` into `retry_call(fn, retries=2)` with short fixed waits in src/schwab_mcp/tokens.py — the single bounded-retry implementation of the project (DRY, research.md D4); keep behavior compatible with existing callers
- [X] T004 [P] Add failing tests for the `RenewalOutcome` and `AuthHealth` value types — closed enums `renewed|not_needed|transient_failure|reauth_required` and `valid|reauth_required|store_absent|store_corrupted`; `retryable` true ONLY for `transient_failure`; `detail` restricted to the fixed vocabulary `access_renewed|still_valid|provider_unreachable|refresh_rejected|reauth_needed|store_absent|store_corrupted` (data-model.md §1–§2) — in tests/unit/test_renewal.py
- [X] T005 Implement `RenewalOutcome` and `AuthHealth` (frozen value types, no secrets, serializable to one compact JSON line) in src/schwab_mcp/renewal.py
- [X] T006 Add failing tests for the token-store lifetime reader — read `expires_in` + `access_token_issued` + `refresh_token_issued` from the schwabdev SQLite row (same read pattern as `peek_store_status`, no schema duplication); compute access/refresh remaining seconds; provider-communicated lifetime only, no second margin (research.md D5) — in tests/unit/test_renewal.py
- [X] T007 Implement the store lifetime reader in src/schwab_mcp/renewal.py reusing the `peek_store_status` read pattern from src/schwab_mcp/tokens.py (depends on T005, T006)

**Checkpoint**: Foundation ready — retry, outcome types, and lifetime reader available for all stories.

---

## Phase 3: User Story 1 — Zero-touch renewal when the access credential expires (Priority: P1) 🎯 MVP

**Goal**: Any authenticated operation triggers a preventive (margin-based), fully automatic renewal using the stored refresh credential — no browser, no URL, no human — and completes transparently.

**Independent Test**: With a stored credential set whose access credential is stale/expired, a normal authenticated operation succeeds with exactly one renewal, no interactive step, unchanged result shape (spec US1 acceptance scenarios 1–4).

### Tests for User Story 1 (write FIRST, ensure they FAIL)

- [X] T008 [US1] Add failing tests for outcome classification in tests/unit/test_renewal.py: `renewed` (stub `update_tokens` → True), `not_needed` (remaining validity above margin → no network call), `transient_failure` (network error persisting after ≤ 2 retries), `reauth_required` (guard hook raises), `renewed` via tie-breaker probe (another process renewed — `linked_accounts()` succeeds), and single-flight sharing (concurrent callers → exactly one renewal, FR-005)
- [X] T009 [P] [US1] Add failing integration test in tests/integration/test_renewal_flow.py: operation through a stub client with a stale access credential succeeds transparently (FR-011) — exactly one renewal occurred, operation result shape unchanged, stderr carries `renew_start` → `renewal_success outcome=ok` (contracts/events.md), zero secret material in any output

### Implementation for User Story 1

- [X] T010 [US1] Implement renewal orchestration + classification `renew(...)` in src/schwab_mcp/renewal.py per research.md D2 — margin short-circuit → `not_needed`; `update_tokens` True → `renewed`; False → disambiguate via captured Schwabdev logger records ("network error" → transient, "refresh_token likely invalid" → permanent) with bounded-timeout `linked_accounts()` probe as tie-breaker (3 s timeout); guard-hook raise → `reauth_required` (depends on T005, T007, T003)
- [X] T011 [US1] Wire startup validation in src/schwab_mcp/server.py to use `retry_call` (replacing `retry_once`) and emit `renew_start`/`renewal_success`/`renewal_failure` events with trigger detail `margin_trigger`; keep tests/performance/test_startup_budget.py green (5 s SC-004 budget still applies)

**Checkpoint**: User Story 1 fully functional and independently testable — the automatic path renews, classifies, logs, and stays invisible to the caller.

---

## Phase 4: User Story 2 — Agent-triggered renewal as a single simple action (Priority: P2)

**Goal**: The agent explicitly requests renewal with one non-interactive command and receives a compact machine-readable result (contracts/cli.md).

**Independent Test**: `uv run schwab-mcp renew` with a valid stored refresh credential prints one JSON line (`renewed` or `not_needed`) and exits 0; with an unusable credential it prints a structured failure distinguishing transient from permanent.

### Tests for User Story 2 (write FIRST, ensure they FAIL)

- [X] T012 [P] [US2] Add failing contract/integration tests for `schwab-mcp renew` in tests/integration/test_renew.py covering every outcome class and exit code (contracts/cli.md): `renewed` → exit 0 + exactly one JSON line on stdout; `not_needed` → exit 0 with NO provider call and valid credentials untouched; `transient_failure` → exit 7, `retryable: true`; concurrent invocation while lock busy → exit 6; missing config → exit 2 before any network activity; store absent/corrupted → exit 3 with detail `store_absent`/`store_corrupted`

### Implementation for User Story 2

- [X] T013 [US2] Implement the `renew` subcommand in src/schwab_mcp/cli.py per contracts/cli.md: load config (fail fast) → peek store → `not_needed` short-circuit (above margin, no network) → acquire `AuthLock` (busy → exit 6) → `renew(...)` classification → print exactly one ≤ 300-byte JSON line on stdout (nothing else on stdout) → map exit codes {0, 2, 3, 6, 7} → emit audit events with trigger detail `explicit_command` (depends on T010, T013's tests T012)

**Checkpoint**: User Stories 1 AND 2 both work independently — automatic path untouched, explicit action available even with the server down.

---

## Phase 5: User Story 3 — Detectable "needs re-authorization" state (Priority: P3)

**Goal**: When the refresh credential is permanently unusable, every path reports the same consistent `reauth_required` classification; the agent detects it with one query and never triggers a retry storm or a browser.

**Independent Test**: With an invalidated refresh credential, `renew` exits 3 with outcome `reauth_required`; a repeat run reports the same classification without hammering the provider; `auth-status` reveals the state in one request; after the 001 `schwab-mcp auth` flow, `auth-status` reports `valid` (spec US3 acceptance scenarios 1–3).

### Tests for User Story 3 (write FIRST, ensure they FAIL)

- [X] T014 [P] [US3] Add failing tests for re-authorization-required consistency in tests/integration/test_renew.py: rejected refresh credential → `renew` exit 3, outcome `reauth_required`, detail `refresh_rejected`; repeated invocation reports the same classification with bounded provider attempts (no unbounded retry loop, FR-007); after a stubbed successful re-authorization, `renew` reports `renewed`/`not_needed` again
- [X] T015 [P] [US3] Add failing tests for `schwab-mcp auth-status` in tests/integration/test_auth_status.py: `valid` state with both `access_expires_in_seconds` and `refresh_expires_in_seconds` ≥ 0 (FR-008, SC-003 — one request answers everything); store absent/corrupted → exit 3 with `store_absent`/`store_corrupted`; NO network call and completes ≤ 2 s (local read only); no renewal is ever triggered by the query

### Implementation for User Story 3

- [X] T016 [US3] Implement the `auth-status` subcommand in src/schwab_mcp/cli.py per contracts/cli.md: config (fail fast) → store peek + lifetime reader → one JSON health line → exit codes {0, 2, 3}; strictly read-only (depends on T007)
- [X] T017 [US3] Verify/complete end-to-end `reauth_required` mapping in src/schwab_mcp/renewal.py and src/schwab_mcp/cli.py: guard-hook raise and rejected-refresh classification produce identical outcome/detail across `renew`, the automatic path, and event log outcomes `connectivity`|`reauth_required` (depends on T010, T014)

**Checkpoint**: All three user stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Quality gates that span all stories (Principle V budgets, security, docs).

- [X] T018 [P] Add performance tests asserting the SC-002 renewal budget in tests/performance/test_renewal_budget.py: worst case (3 attempts × 3 s timeout + 2 × 0.5 s waits) completes ≤ 10 s; use the `performance` marker per pyproject.toml
- [X] T019 [P] Add token-usage tests asserting compact outputs in tests/performance/test_output_budget.py: `renew` and `auth-status` stdout is a single line ≤ 300 bytes with only the contracted 3–4 fields (Principle V; growth beyond budget requires recorded justification)
- [X] T020 [P] Extend no-secrets coverage in tests/unit/test_no_secrets_in_output.py: renewal JSON results, auth-status results, and `renew_*` event lines contain zero token/secret/authorization-URL material (FR-004, SC-005)
- [X] T021 [P] Update docs/uso.md (and docs/instalacion.md if affected) documenting `schwab-mcp renew` and `schwab-mcp auth-status` for agent usage, linking specs/002-automated-token-renewal/contracts/cli.md
- [X] T022 Run the quickstart.md validation scenarios end-to-end (Scenarios 1–5) and record results; verify full suite green with no skipped tests (commit gate)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — start immediately
- **Foundational (Phase 2)**: depends on T001 — BLOCKS all user stories
- **US1 (Phase 3)**: depends on Phase 2
- **US2 (Phase 4)**: depends on T010 (classification core); does not modify US1 behavior
- **US3 (Phase 5)**: depends on T007 (reader) and T010 (classification); T017 closes the loop across stories
- **Polish (Phase 6)**: after the desired stories are complete (T018–T020 may start as soon as their subject matter exists)

### User Story Dependencies

- **US1 (P1)**: Foundational only — no cross-story dependencies (MVP)
- **US2 (P2)**: Reuses `renew(...)` from T010; CLI-only surface; independently testable against stubs
- **US3 (P3)**: Reuses reader + classification; `auth-status` is independent; T017 verifies consistency across all paths

### Within Each User Story

- Failing tests FIRST (Red) → implementation (Green) → refactor
- Core orchestration before CLI wiring; CLI wiring before event/exit-code polish

### Parallel Opportunities

- T002 (tests/unit/test_tokens.py) ∥ T004 (tests/unit/test_renewal.py) — different files
- T009 ∥ T008 after T005–T007 exist — different files
- T012 (tests/integration/test_renew.py) ∥ any US3/US1 file work
- T014 ∥ T015 — different files
- T018 ∥ T019 ∥ T020 ∥ T021 — all different files

---

## Parallel Example: Foundational + US1

```bash
# Failing tests first (different files, parallel):
Task: "T002 bounded-retry tests in tests/unit/test_tokens.py"
Task: "T004 outcome/health type tests in tests/unit/test_renewal.py"

# After Green on Phase 2, US1 tests in parallel:
Task: "T008 classification tests in tests/unit/test_renewal.py"
Task: "T009 integration flow test in tests/integration/test_renewal_flow.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. T001 → T002–T007 (foundation)
2. T008–T011 (US1: automatic transparent renewal)
3. **STOP and VALIDATE**: US1 acceptance scenarios 1–4 via stubs
4. The agent's zero-touch guarantee is live

### Incremental Delivery

1. Foundation → US1 (MVP: automatic path + classification)
2. +US2 (`renew` command: agent's explicit lever)
3. +US3 (`auth-status` + consistent re-auth state)
4. Polish (budgets, security, docs, quickstart) → commit-ready

### Commit Discipline (Constitution)

- Every commit: full suite green, no skipped tests, descriptive message
  enumerating the changes included.

## Notes

- [P] tasks = different files, no dependencies
- All network-touching tests use stub clients and a temporary token DB under `tmp/` (never committed) — never the live API
- `detail` values and outcome enums are closed vocabularies (data-model.md) — do not invent new values at implementation time
- Stop at any checkpoint to validate the story independently