---
description: "Task list for feature 008-extract-option-chain"
---

# Tasks: Option Chain Extraction with Filters (`get_option_chain`)

**Input**: Design documents from `/specs/008-extract-option-chain/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/mcp-tools.md, quickstart.md

**Tests**: MANDATORY — the project constitution (Principle I) requires TDD
(Red → Green → Refactor): every implementation task is preceded by its
test task, and tests MUST fail before writing the implementation.

**Organization**: Tasks grouped by user story (US1 → US3, priority P1 → P3).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- Single project: `src/schwab_mcp/`, `tests/{unit,integration,performance}/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify the project baseline before touching code.

- [X] T001 Run `uv sync` and `uv run pytest` to confirm the full suite is green (0 skipped) before any change; record baseline in commit message of the first feature commit

**Checkpoint**: Green baseline — TDD can start.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Validated query, provider fetch and partials policy —
used by ALL user stories. Without this, no story can start.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 [P] Write FAILING unit tests for input validation (FR-008) in tests/unit/test_options_chain_validation.py: `symbol` non-empty; `max_strikes ≥ 1` (default 50); `option_type` ∈ {both, calls, puts} (default both); `delta_target` with `0 < |delta| < 1` or null (default null); `dte_max ≥ 1` or null (default null → current cap 60); actionable error message per case; quote the constraints verbatim from data-model.md §1
- [X] T003 Implement `OptionChainQuery` dataclass + `validate()` in src/schwab_mcp/options_chain.py to make T002 pass (reuse `errors.py` taxonomy; no upcall before validation)
- [X] T004 [P] Write FAILING unit tests for provider request mapping in tests/unit/test_options_chain_filters.py: `option_type` → `contractType` (both→ALL, calls→CALL, puts→PUT); `strikeCount` = `max_strikes` (50 default); `fromDate` = today, `toDate` = today + effective DTE cap (60 default or requested `dte_max`); `includeUnderlyingQuote=true`; DTE in calendar days (research R1/R3)
- [X] T005 Implement `fetch_option_chain(client, query)` in src/schwab_mcp/options_chain.py using `client.option_chains(...)` with params from T004, wrapped in `tokens.retry_call` + `provider.response_json`; FR-013: if a whole expiration map is missing/empty or the response fails → structured error WITHOUT partial chain (research R5)

**Checkpoint**: Foundation ready — user story implementation can now begin.

---

## Phase 3: User Story 1 — Analyze a complex position with a single query (Priority: P1) 🎯 MVP

**Goal**: With only `symbol`, return the complete chain with defaults
(≤60 DTE, both types, 50 strikes/side, all the Greeks and technical
values) in one invocation.

**Independent Test**: invoke with only `symbol` on an instrument with
options and verify expirations ≤60 DTE, both legs, strike window around
the ATM and complete `contract_fields` per leg (quickstart S1).

### Tests for User Story 1 (TDD — write first, must FAIL) ⚠️

- [X] T006 [P] [US1] Write FAILING unit tests for payload mapping in tests/unit/test_options_chain_mapping.py: union of `callExpDateMap`/`putExpDateMap` keyed by expiration date; `dte` = calendar days; `atm_strike` = strike closest to `underlying_price`; `contract_fields` fixed order from data-model.md §1 (bid…deliverable_note); rounding prices 2 / greeks+iv 4 decimals; missing field → explicit `null` in its column (FR-007); `data_state` realtime|delayed
- [X] T007 [P] [US1] Write FAILING unit tests for default filters in tests/unit/test_options_chain_filters.py: per-expiration symmetric window of up to 50 strikes each side around `atm_strike` (fewer → all); `option_type="both"` keeps both legs; expirations with `dte > 60` excluded
- [X] T008 [P] [US1] Write FAILING performance tests in tests/performance/test_options_chain_budgets.py (marker `performance`): token budget **≤ 110,000 tokens with default filters and ≤ 8,000 tokens with `delta_target`** (budgets adjusted by user decision 2026-10-24 during implementation and re-baselined during convergence T023: honest measurement of the mandated 23-column both-leg rows is ~95–106k; live wide chains with 16 expirations measure ~7,2–7,3k with delta; growth justification registered in plan.md Complexity Tracking and docs/tools.md) for a representative liquid-underlying fixture (~12 expirations × 100 strike rows, serialization measured as chars/4, plus a 16-expiration wide-chain delta case) (SC-002); FR-012 bound: response never exceeds expirations × types × strikes; latency budget hook per plan (≤5 s p95)
- [X] T009 [P] [US1] Write FAILING integration test in tests/integration/test_options_chain.py: end-to-end with provider double — `ok` chain; `no_options_listed` structured result; `no_expirations_in_range` structured result; whole-expiration-missing → error without partial chain (FR-013); `extended=true` adds raw provider payload (contract §2); SC-004/FR-011 assertion: each quickstart scenario completes with exactly 1 invocation and the `ok` response carries the full chain with no cursor/offset field

### Implementation for User Story 1

- [X] T010 [US1] Implement payload mapping/curation (ChainMeta, Expiration, StrikeRow, `contract_fields` constant) in src/schwab_mcp/options_chain.py to make T006 pass (depends T002, T005)
- [X] T011 [US1] Implement default filters: strike window per expiration, option_type leg selection, DTE filter + `filters` echo with `dte_max_effective` in src/schwab_mcp/options_chain.py to make T007 pass (depends T010)
- [X] T012 [US1] Implement compact columnar serialization (strike rows with both legs as positional arrays, deterministic rounding) in src/schwab_mcp/options_chain.py to make T008 pass (depends T010)
- [X] T013 [US1] Implement `get_option_chain` orchestration (ok / no_options_listed / no_expirations_in_range / error states per FR-009, FR-013) in src/schwab_mcp/options_chain.py and register the tool with closure wrapper named `get_option_chain` in src/schwab_mcp/server.py following the existing `get_open_positions`/`get_transaction_history` pattern, exposing schema: symbol, max_strikes, option_type, delta_target, dte_max, extended (depends T003, T005, T010–T012, T009)

**Checkpoint**: US1 usable end-to-end (MVP): one query → complete analysis.

---

## Phase 4: User Story 2 — Focus by type and target delta (Priority: P2)

**Goal**: With `option_type` and `delta_target`, return the window of up
to 5 strikes per type around the target delta at each expiration.

**Independent Test**: invoke with `option_type="puts"`,
`delta_target=0.20` and verify only PUTs and ≤5 strikes around
|delta|≈0.20 per expiration; with "both", separate windows of CALLs and
PUTs (quickstart S2).

### Tests for User Story 2 (TDD — write first, must FAIL) ⚠️

- [X] T014 [P] [US2] Write FAILING unit tests for the delta window in tests/unit/test_options_chain_delta.py: per expiration AND per included type, contract with delta closest to target (absolute value) + 2 contiguous strikes each side → up to 5 (or all available around); per-type independent windows when option_type="both" (clarification 2026-10-23); no invented strikes; delta window NOT reduced by max_strikes
- [X] T015 [P] [US2] Write FAILING integration test extension in tests/integration/test_options_chain.py: delta scenario end-to-end (puts-only 0.20; both-types per-type windows; SC-004 assertion: exactly 1 invocation per scenario, no cursor/offset in the response); internal `strikeCount` expansion rule (max(limit, 100), single re-fetch up to 200 when target not bracketed) observable via provider double request assertions

### Implementation for User Story 2

- [X] T016 [US2] Implement delta window selection + internal strikeCount expansion in src/schwab_mcp/options_chain.py to make T014/T015 pass (depends T014, T015, T005)
- [X] T017 [US2] Wire `delta_target` validation errors (FR-008) and `filters` echo for delta into the orchestration in src/schwab_mcp/options_chain.py (depends T016, T013)

**Checkpoint**: US1 + US2 independent and functional.

---

## Phase 5: User Story 3 — Adjust the volume with explicit limits (Priority: P3)

**Goal**: Explicit `max_strikes` and `dte_max` govern the response volume
deterministically (SC-006).

**Independent Test**: invoke with `max_strikes=10`, `dte_max=7` and
`dte_max=120` and verify that the limits are respected 100% and that the
empty range produces the structured result (quickstart S3).

### Tests for User Story 3 (TDD — write first, must FAIL) ⚠️

- [X] T018 [P] [US3] Write FAILING tests for explicit limits: extend tests/unit/test_options_chain_filters.py with `max_strikes=10` (≤10 per side, ATM zone always included), `dte_max=120` (includes farther expirations, `dte_max_effective`=120), `dte_max=7` with nearest expiration beyond → `no_expirations_in_range` with effective cap in detail; add to tests/integration/test_options_chain.py the SC-006 assertion (zero out-of-bounds contracts) and the SC-004 assertion (exactly 1 invocation per scenario, no cursor/offset)

### Implementation for User Story 3

- [X] T019 [US3] Implement `dte_max` passthrough beyond the 60-day default (`toDate` = today + requested value) and empty-range result wiring in src/schwab_mcp/options_chain.py to make T018 pass (depends T018, T011)

**Checkpoint**: The three stories work independently.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, end-to-end validation and constitution gates.

- [X] T020 [P] Document the tool in docs/tools.md: invocation, input schema, output schema with `contract_fields`, expected payload size (incl. the documented budget risk from plan.md Complexity Tracking), error table, examples — include in the feature commit (constitution commit discipline)
- [X] T021 Run quickstart.md scenarios S1–S4 as final validation; run `uv run pytest` full suite (green, 0 skipped); refresh the codebase-memory-mcp index for the repository (constitution VI graph currency gate) before closing the feature

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: immediate.
- **Foundational (Phase 2)**: blocks ALL user stories (T002→T003, T004→T005; T002/T004 in parallel).
- **US1 (Phase 3)**: depends on Phase 2. Tests T006–T009 in parallel → implementation T010→T011→T012→T013.
- **US2 (Phase 4)**: depends on Phase 3 (T013 registered the tool; the delta window is built on top of the mapping and the fetch).
- **US3 (Phase 5)**: depends on Phase 3 (uses the base filters); independent of US2.
- **Polish (Phase 6)**: depends on all stories complete.

### User Story Dependencies

- **US1**: does not depend on other stories.
- **US2**: reuses fetch (T005) and mapping (T010); independent of US3.
- **US3**: reuses base filters (T011); independent of US2 (they only share the filter test file → sequence T007 → T018).

### Parallel Opportunities

- Foundational: T002 ∥ T004.
- US1: T006 ∥ T007 ∥ T008 ∥ T009 (all different files).
- US2: T014 ∥ T015.
- Polish: T020 can be done in parallel with the final validation of T021.

---

## Parallel Example: User Story 1

```bash
# US1 tests in parallel (different files, all RED first):
Task: "tests/unit/test_options_chain_mapping.py"      (T006)
Task: "tests/unit/test_options_chain_filters.py"      (T007)
Task: "tests/performance/test_options_chain_budgets.py" (T008)
Task: "tests/integration/test_options_chain.py"       (T009)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 → Phase 2 (Foundation).
2. Complete Phase 3 → **STOP and VALIDATE** with quickstart S1.
3. The tool is already useful on its own (core use case).

### Incremental Delivery

- +US2 → validate with S2 (delta). +US3 → validate with S3 (limits).
- Each story adds value without breaking the previous ones.

### Constitution Gates per task group

- Strict TDD: each task's test must fail before its implementation.
- Budgets: T008 (tokens/latency) is a US1 gate.
- Commits: green suite, 0 skipped, docs updated in the same commit.
- At closing: refresh of the codebase-memory-mcp index (T021).

---

## Notes

- [P] tasks = different files, no dependencies
- `[Story]` label maps task to user story for traceability
- Verify tests fail before implementing; commit after each task or logical group
- Avoid: vague tasks, same-file conflicts, cross-story dependencies that break independence

---

## Phase 7: Convergence

*Appended by /speckit.converge (2026-10-24). Findings from assessing the
implemented feature against spec.md, plan.md, tasks.md and the constitution.
No CRITICAL/HIGH findings; ordered MEDIUM first.*

- [X] T022 Add the quickstart S4 "source down" integration scenario to tests/integration/test_options_chain.py: provider double answering HTTP 500 (and parametrized 408/429) on `option_chains` → `ConnectivityError` with the actionable shared-taxonomy message reaches the caller, audit event `options_chain_query_failure` outcome=transient detail=provider_unreachable is emitted, exactly 1 upcall occurs and no partial chain is returned (FR-013, contracts/mcp-tools.md §4) per quickstart S4 (missing)
- [X] T023 Re-baseline the `delta_target` token budget (SC-002 as amended in plan.md Complexity Tracking): the fixture test asserts < 6,000 tokens for ~12 expirations, but a live wide chain (SPY, 16 expirations ≤60 DTE, both types) measured ~7.5k tokens (found live 2026-10-24). Re-measure across representative live underlyings, then either adjust the declared budget with registered justification in plan.md + docs/tools.md (Principle V procedure) or reduce response volume without violating FR-006/FR-011; keep tests/performance/test_options_chain_budgets.py aligned with the ratified numbers (partial)
- [X] T024 Normalize integral floats in serialize_leg: `multiplier` arrives as float from the live provider (`100.0`, found live 2026-10-24) and is serialized unrounded; data-model.md §1 declares volume/open_interest/multiplier as integers. Coerce integral values to int in the `volume`/`open_interest`/`multiplier` columns (add regression test in tests/unit/test_options_chain_mapping.py) per data-model.md §1 (partial)