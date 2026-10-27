# Tasks: List Open Positions

**Input**: Design documents from `/specs/003-list-open-positions/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included and MANDATORY — the constitution (Principle I) requires TDD: every test is written first and MUST fail (Red) before its implementation (Green).

**Organization**: Tasks grouped by user story (US1 → US2 → US3) per spec.md priorities.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- Single project: `src/schwab_mcp/`, `tests/` at repository root (per plan.md Structure Decision).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Green baseline before touching anything (constitution commit gate).

- [x] T001 Run full baseline suite `uv run pytest` and confirm 100% green with 0 skipped before any change (record result in commit notes later)

**Checkpoint**: Baseline green — ready to start.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Data model shared by the three stories (data-model.md §1–§2). BLOCKS all user stories.

- [x] T002 [P] Write failing model tests in tests/unit/test_positions.py: validation rules verbatim from data-model.md §1–§2 — `outcome ∈ {ok, partial_failure, transient_failure, reauth_required}`; unique identity `(account_hash, symbol)`; `quantity ≠ 0` and signed (long +, short −); `positions: []` valid only with `outcome: "ok"`; option fields present ⇔ `instrument_type == "OPTION"` (never `null`: they are omitted); `retryable: true` only with `transient_failure`; `accounts_failed` only with `partial_failure`; `price_timestamp`/`retrieved_at` parseable ISO-8601 — expect FAIL (module does not exist)
- [x] T003 Implement typed models `PositionEntry` and `PositionsResult` (pydantic, `structured_output`-compatible) with enums and the exact validation rules of T002 in src/schwab_mcp/positions.py — expect GREEN

**Checkpoint**: Foundation ready — user story implementation can begin.

---

## Phase 3: User Story 1 — Single-query snapshot of all open positions (Priority: P1) 🎯 MVP

**Goal**: One invocation of `get_open_positions` returns all effective holdings of all linked accounts, identified (account + instrument), consolidated by lot, with basic failure classification and auditing.

**Independent Test**: With a client fake that returns a known payload, the tool returns exactly the open positions of that payload (signed, consolidated, no qty=0); with an empty payload → `ok/no_positions/[]`; with `ConnectivityError` → `transient_failure/retryable:true` on the first attempt (no internal retries); with `ReauthorizationRequiredError` → `reauth_required`. (Spec US1 scenarios 1–3 + FR-005/006/007.)

### Tests for User Story 1 (TDD — write first, verify they FAIL)

- [x] T004 [P] [US1] Write failing tests in tests/unit/test_positions.py for provider→model mapping: single account long position; short position (negative quantity); consolidation of duplicate lots of the same `(account_hash, symbol)` with averaged `average_price`; full omission of entries with zero quantity (FR-015); `retrieved_at` propagated to each entry's `price_timestamp` — expect FAIL
- [x] T005 [P] [US1] Write failing tests in tests/unit/test_server_tool.py: tool `get_open_positions` registered and callable via `MCPServer.add_tool` with structured output (research D1); `ok` result with a fake payload from `account_details_all(fields="positions")` (single upstream call — assert call count == 1); `positions: []` with a payload without positions; `ConnectivityError` → `transient_failure` with no second attempt (assert calls == 1, FR-007/D6); `ReauthorizationRequiredError`/`TokenStoreCorruptedError` → `reauth_required` (D7); audit events: exactly one `positions_query_start` + one terminal per invocation via `log.auth_event` (FR-014) — expect FAIL

### Implementation for User Story 1

- [x] T006 [US1] Implement provider mapping and query orchestration in src/schwab_mcp/positions.py: call `client.account_details_all(fields="positions")` once (research D2); map payload → `PositionEntry` (base fields: `account_hash`, `symbol`, `instrument_type`, `description`, `quantity = longQuantity − shortQuantity`, `average_price`, `market_value`); consolidate by `(account_hash, symbol)`; omit zero quantity; classify `errors.py` exceptions → `PositionsResult` (D7); `retrieved_at` = UTC when receiving the response (D4) — expect GREEN (T004, T005 mapping/registration)
- [x] T007 [US1] Register tool in src/schwab_mcp/server.py: `mcp.add_tool(...)` with name `get_open_positions`, description per contracts/mcp-tools.md, sync function, `structured_output` via `PositionsResult` annotation — expect GREEN (registration test of T005)
- [x] T008 [US1] Emit audit events in src/schwab_mcp/positions.py: `positions_query_start` (detail `curated`) → exactly one terminal (`positions_query_success` | `positions_query_failure`) with vocabulary from contracts/events.md, reusing `log.auth_event`; no symbols/quantities in the lines — expect GREEN (events test of T005)

**Checkpoint**: US1 functional and independent — MVP: the tool returns the basic snapshot with classified failures and auditing.

---

## Phase 4: User Story 2 — Complete metadata for each position (Priority: P2)

**Goal**: Every position includes the full curated set (including unrealized P/L, price timestamp and option fields); extended provider fields only with `extended=true`.

**Independent Test**: With positions of different `assetType` (equity + option) in the fake payload, each entry carries ALL the curated fields from data-model §1 (including `underlying_symbol`/`put_call`/`strike_price`/`expiration_date` only in OPTION); with `extended=true` each entry adds the `extended` passthrough; with `extended=false` (default) the `extended` key NEVER appears. (Spec US2 scenarios 1–3, FR-003/003a.)

### Tests for User Story 2 (TDD — write first, verify they FAIL)

- [x] T009 [P] [US2] Write failing tests in tests/unit/test_positions.py for curated metadata: correct derived `unrealized_pl` (long and short — research D3) and consistent with `currentDayProfitLoss` when the provider carries it; complete option fields for `assetType: OPTION` (underlying, put/call, strike, expiration) and absent for EQUITY; `price_timestamp` = retrieval timestamp (FR-012/D4); extended: payload with extra fields (`cusip`, `settledLongQuantity`, `currentDayProfitLoss`, `maintenanceRequirement`) → `extended=true` includes them as passthrough and `extended=false` (default) omits them entirely — expect FAIL
- [x] T010 [P] [US2] Write failing test in tests/unit/test_server_tool.py: `extended` argument accepted by the tool (default `false`), default payload ≤ budget (fixture of 50 positions, assert serialization ≤ 8 KB — research D9) — expect FAIL

### Implementation for User Story 2

- [x] T011 [US2] Implement curated metadata mapping in src/schwab_mcp/positions.py: signed derived `unrealized_pl` (D3), conditional option fields, per-entry `price_timestamp` — expect GREEN (T009)
- [x] T012 [US2] Implement `extended` parameter in src/schwab_mcp/positions.py and src/schwab_mcp/server.py (input schema `{extended: bool = false}`): uninterpreted passthrough of the provider's remaining fields inside `extended` (D3/D9), compact default guaranteed — expect GREEN (T010)

**Checkpoint**: US1 + US2 work independently; the default payload remains compact.

---

## Phase 5: User Story 3 — Predictable failure behavior consistent with the agent playbook (Priority: P3)

**Goal**: Multi-account failures (`partial_failure` with `accounts_failed`) and cross-cutting verification that every outcome — success, empty, partial, transient, reauth — is machine-readable, secret-free, and accompanied by correct audit events.

**Independent Test**: With a fake that makes one account fail and others respond, the result is `partial_failure` with `accounts_failed[{account_hash, detail}]` and `positions` only from the successful accounts (FR-010); every outcome shape passes the no-secrets test; failure events use the vocabulary of contracts/events.md. (Spec US3 scenarios 1–3, FR-008/010.)

### Tests for User Story 3 (TDD — write first, verify they FAIL)

- [x] T013 [P] [US3] Write failing tests in tests/unit/test_positions.py and tests/unit/test_server_tool.py: multi-account with one account failing → `outcome: "partial_failure"`, `detail: "account_failed"`, `accounts_failed` with hash + `detail ∈ {provider_error, transient}`, positions only from successful accounts; extend tests/unit/test_no_secrets_in_output.py to cover ALL outcome shapes of the tool (ok, empty, partial, transient, reauth): zero secrets and no raw account number (FR-008) — expect FAIL

### Implementation for User Story 3

- [x] T014 [US3] Implement per-account error isolation in src/schwab_mcp/positions.py: split the response per account from the `account_details_all` payload, capture per-account failure without losing the others (FR-010/D7); emit the correct audit terminal according to the result's outcome (contracts/events.md): `positions_query_success` with `outcome: ok | partial_failure` and `detail: account_failed` when there is success or partial failure, `positions_query_failure` with `outcome: transient | reauth` and fixed details (`provider_unreachable`, `reauth_needed`, `store_absent`, `store_corrupted`) only for total failures — expect GREEN (T013)

**Checkpoint**: All three stories work independently; the agent playbook is complete.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Measurable budgets, up-to-date documentation, and commit gate.

- [x] T015 [P] Write performance + token-usage tests in tests/performance/test_positions_budgets.py (marker `performance`): invocation latency ≤ 5 s with a normal-network fake (SC-002); default payload ≤ 12 KB with 50 curated positions and extended ≤ 20 KB (SC-003/D9 adjusted budgets); run and validate budgets — expect GREEN with the current implementation
- [x] T016 [P] Update documentation: register `get_open_positions` in docs/tools.md (surfaces table, full contract, extended playbook) and add entry to docs/CHANGELOG.md — required in the SAME commit as the implementation (constitution: documentation currency)
- [x] T017 Run quickstart.md validation end-to-end (tests + manual quickstart scenarios with real network if credentials are available; otherwise, document the ones pending manual verification)
- [ ] T018 Final commit gate: `uv run pytest` full suite 100% green, 0 skipped, no secrets in outputs, docs up to date (T016) — only then commit (constitution: green-before-commit)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — immediate
- **Foundational (Phase 2)**: depends on Phase 1 — BLOCKS all stories
- **US1 (Phase 3)**: depends on Phase 2
- **US2 (Phase 4)**: depends on US1 (the tool must exist and map the basics)
- **US3 (Phase 5)**: depends on US2 (per-account isolation operates on the full mapping)
- **Polish (Phase 6)**: depends on all stories

### User Story Dependencies

- **US1**: no dependencies on other stories (Foundational only)
- **US2**: builds on US1 (same `positions.py` module; completes the mapping)
- **US3**: builds on US1/US2 (multi-account + cross-cutting verification)

### Within Each User Story

- Tests FIRST, verifying they fail before implementing (TDD, constitution gate I)
- Mapping before tool registration before events
- Story complete before the next priority

### Parallel Opportunities

- T002 and T004…: within each phase, tests marked [P] are different files/functions → parallelizable
- T015 and T016 (Polish) are parallelizable with each other
- Stories are sequential due to shared module dependency (`positions.py`); DO NOT parallelize US1/US2/US3 with each other (same file — avoid conflicts)

---

## Parallel Example: User Story 1

```bash
# The two US1 test files are independent → launch together:
Task: "Write failing tests in tests/unit/test_positions.py (T004)"
Task: "Write failing tests in tests/unit/test_server_tool.py (T005)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: green baseline
2. Phase 2: models (Red → Green)
3. Phase 3: full US1 → **STOP and VALIDATE**: the tool returns the snapshot with classified failures
4. Already usable by the agent for the core case

### Incremental Delivery

1. US1 → basic snapshot + failures + auditing (MVP)
2. US2 → complete metadata + extended on demand
3. US3 → partial_failure + cross-cutting secrets/events verification
4. Polish → measured budgets, docs, commit gate

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps to spec.md for traceability
- Verify Red before each Green (constitution gate I — non-negotiable)
- Commit after each checkpoint, with a green suite, 0 skipped, and docs included (constitution: commit discipline)
- Avoid: vague tasks, same-file conflicts between parallel tasks, cross-story dependencies that break independence