---

description: "Task list for feature 006-transaction-history implementation"
---

# Tasks: Account Transaction History (`get_transaction_history`)

**Input**: Design documents from `/specs/006-transaction-history/`

**Prerequisites**: [plan.md](./plan.md) · [spec.md](./spec.md) · [research.md](./research.md) · [data-model.md](./data-model.md) · [contracts/](./contracts/) · [quickstart.md](./quickstart.md)

**Tests**: MANDATORY — the constitution (Principle I: Test-First) requires
tests written first and failing (Red) before each implementation
(Green). Each user-story phase includes its TDD tests.

**Organization**: Tasks grouped by user story (spec.md: US1 P1, US2
P2, US3 P3) for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no pending dependencies)
- **[Story]**: Owning user story (US1, US2, US3)
- Exact paths in each description

## Path Conventions

- Single project: `src/schwab_mcp/` + `tests/{unit,performance}/`
- New module: `src/schwab_mcp/transactions.py` (only new code file; registration in `server.py`)
- Tests in the same file are NOT marked [P] against each other

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Repo baseline on the branch — there are no new dependencies (plan: "No new dependencies")

- [X] T001 Verify baseline on `006-transaction-history`: run `uv sync` and `uv run pytest` — full suite green, 0 skipped, no code changes (constitution commit gate)

**Checkpoint**: green baseline; TDD can start.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Models, enums and validation of `HistoryQuery` — prerequisite of ALL user stories

**⚠️ CRITICAL**: No user story starts before this phase is complete.

- [X] T002 Write failing tests (Red) for enums and models in `tests/unit/test_transactions_models.py`: closed sets of `TransactionOutcome`/`TransactionDetail`/`MovementCategory`/`ProviderTransactionType` per data-model.md; upstream-type→category mapping table (R5: `TRADE→trade`; 7 cash/delivery types→`transfer`; `DIVIDEND_OR_INTEREST→dividend_or_interest`; `JOURNAL`/`SMA_ADJUSTMENT→adjustment`; `MEMORANDUM`/`MARGIN_CALL`/`MONEY_MARKET→other`; unknown type→`other`); cross-validation rules 1–8 of data-model.md (`outcome=ok`+`movements=[]` ⇔ empty detail; `has_more=true` ⇒ `next_offset` present and `returned==50`; `accounts_failed` ⇔ `partial_failure`; `retryable=true` ⇔ `transient_failure`; `no_movements_for_instrument` ⇒ `symbol` present)
- [X] T003 Implement enums and Pydantic models in `src/schwab_mcp/transactions.py` (models only: `MovementEntry`, `TransactionsResult`, enums; fields and constraints verbatim from data-model.md: opaque `account_hash` str min_length=1, ISO-8601 `occurred_at`, `description` truncated to 80 chars in default, float `amount`, `currency` default `"USD"`, `symbol`/`instrument_type`/`extended` absent when not applicable) — makes T002 pass (Green)
- [X] T004 [P] Write failing tests (Red) for `HistoryQuery` validation in `tests/unit/test_transactions_validation.py` (FR-004): missing/malformed dates (`YYYY-MM-DD` format), `end_date < start_date` (error names both), range > 366 days (error states the 1-year maximum), future `end_date`, empty `symbol`, `offset < 0`; and that validation runs BEFORE any upcall
- [X] T005 Implement `HistoryQuery` validation in `src/schwab_mcp/transactions.py` (parsing of `YYYY-MM-DD` dates, window ≤ 1 year, inclusive boundaries in America/New_York via `zoneinfo` — research R4) — makes T004 pass (Green)

**Checkpoint**: models + validation ready; US1/US2/US3 can start (US2 and US3 in parallel if capacity allows).

---

## Phase 3: User Story 1 - Retrieve every movement over a date range (Priority: P1) 🎯 MVP

**Goal**: With start/end dates, obtain ALL movements of all linked
accounts (trades, transfers, dividends/interest, adjustments, etc.)
with normalized category, amounts and account.

**Independent Test**: With provider payload fixtures containing a
trade, an interest credit, a transfer and an adjustment, a query of
the range returns the 4 with their category/account/amount; with a
range without movements it returns `ok/no_movements`; a transient
failure is reported on the first attempt.

### Tests for User Story 1 (TDD — write first, verify they FAIL)

- [X] T006 [P] [US1] Write failing provider→model mapping tests in `tests/unit/test_transactions_mapping.py`: fixtures of the 15 upstream types (R5) verifying category, `occurred_at`, `amount`, `currency` (rule: use the provider's currency field if it exposes one; otherwise default `"USD"` — F2 from analyze), `account_hash`, `symbol`/`instrument_type` only when there is an instrument, `description` truncated to 80 characters, `extended` only with `extended=true` (passthrough: original `type`, full description, `fees`, `commissions`, `netAmount`, `settlementDate`, `transferItems`, `activityId` — research R5/data-model.md)
- [X] T007 [P] [US1] Write failing orchestration and outcome tests in `tests/unit/test_transactions_query.py` (fake client): iterates `linked_accounts()`; 1 `transactions()` call per account with `types` = full comma-separated list of the 15 types (research D2/R2); scoped SDK validator bypass helper (toggle of `client._validator.enabled` with restoration in `finally` — research D2); outcomes `ok/history_retrieved`, `ok/no_movements`, `transient_failure/provider_unreachable` with `retryable=true` reported on the first attempt WITHOUT internal retries (FR-010), `reauth_required/reauth_needed`, `partial_failure` with per-account `accounts_failed` (`provider_error`/`transient`) without silently dropping accounts (FR-008); merges accounts and deduplicates by `(account_hash, activityId)`; `retrieved_at` ISO-8601 UTC; determinism: the same query run twice produces the same set (spec US1 scenario 2); the orchestration ONLY invokes read methods of the client — no `place_order` or writes (FR-012)
- [X] T008 [P] [US1] Write failing split-at-cap tests in `tests/unit/test_transactions_split.py`: response of exactly 3000 movements → range bisection (minimum sub-range 1 day, research D3), merge without duplicates or omissions (SC-004); 2999 and 3001-below-cap do not trigger the split
- [X] T009 [P] [US1] Write failing audit event tests in `tests/unit/test_transactions_events.py` per `contracts/events.md`: exactly 1 terminal event per invocation (`transactions_query_success` ok/partial · `transactions_query_failure` transient/reauth/validation), detail from the contract's closed enum, no secrets, no unredacted provider free text

### Implementation for User Story 1

- [X] T010 [US1] Implement `map_provider_transactions(payload, extended)` in `src/schwab_mcp/transactions.py` (R5 mapping + description truncation + extended passthrough) — makes T006 pass (Green)
- [X] T011 [US1] Implement orchestration `get_transaction_history(client, start_date, end_date, extended=False, offset=0)` in `src/schwab_mcp/transactions.py`: linked_accounts → 1 `transactions()` per account with the full type list + `_bypass_validator()` helper with `finally` (research D2); outcome classification and `accounts_failed` following the `positions.py` pattern; `retry_call` with 0 retries for the transactions call (FR-010) — makes T007 pass (Green)
- [X] T012 [US1] Implement split by bisection at the 3000 cap with dedup by `(account_hash, activityId)` in `src/schwab_mcp/transactions.py` — makes T008 pass (Green)
- [X] T013 [US1] Emit audit events (start/terminal) via `log.auth_event` in `src/schwab_mcp/transactions.py` per contracts/events.md — makes T009 pass (Green)
- [X] T014 [US1] Register the `get_transaction_history` tool in `src/schwab_mcp/server.py`: wrapper closure with client (pattern of `get_open_positions`), input schema with `start_date`, `end_date`, `extended` (`symbol` arrives in US2, `offset` in US3 — do not register parameters without behavior), `MCPServer.add_tool` with `structured_output`
- [X] T015 [US1] Extend no-secrets coverage for the new tool in `tests/unit/test_no_secrets_in_output.py` (result and events: no tokens, app keys, secrets, account numbers — only opaque `account_hash`)

**Checkpoint**: US1 complete and independently testable: full history by range via MCP works (MVP).

---

## Phase 4: User Story 2 - Focus the history on one instrument (Priority: P2)

**Goal**: With an optional `symbol`, return only that instrument's movements in the range; distinguish "unknown instrument" from "no movements".

**Independent Test**: With fixtures of the range mixing movements of several instruments and non-instrument movements, the query filtered by `AAPL` returns exactly the AAPL subset (consistency with the unfiltered one); a non-existent symbol produces an `instrument_not_found` error (not an ambiguous empty).

### Tests for User Story 2 (TDD — write first, verify they FAIL)

- [X] T016 [P] [US2] Write failing symbol validation tests in `tests/unit/test_transactions_symbol.py` (fake client): `symbol` present → 1 upcall `instruments(symbols=[symbol], projection="SYMBOL_SEARCH")` (research D6); non-existent/typo symbol → `instrument_not_found` error naming the symbol (FR-009c); without `symbol` → **zero** instruments upcalls; no fuzzy matching (spec Assumptions)
- [X] T017 [P] [US2] Write failing filter semantics tests in `tests/unit/test_transactions_symbol.py`: filtered result = exact subset of the unfiltered result (consistency, spec US2 scenario 3); valid symbol without movements → `ok/no_movements_for_instrument` (and cross-rule 6 of data-model.md: that detail implies `symbol` present); filter applied upstream (`symbol=` in the transactions call)

### Implementation for User Story 2

- [X] T018 [US2] Implement `symbol` validation (`instruments` upcall + `instrument_not_found` error) and upstream filter in `src/schwab_mcp/transactions.py` — makes T016 and T017 pass (Green)
- [X] T019 [US2] Add `symbol` to the tool input schema in `src/schwab_mcp/server.py` (wrapper and schema from T014) and verify the end-to-end flow with existing tool registration tests

**Checkpoint**: US1 and US2 work independently.

---

## Phase 5: User Story 3 - Bounded, agent-friendly pagination (Priority: P3)

**Goal**: Deterministic paginated response: chronological ascending order, pages of 50, `total_count`, `has_more`/`next_offset`, complete walk without duplicates or gaps.

**Independent Test**: With a fixture history of 137 movements, the first page brings 50 ordered movements + `total_count=137` + `next_offset=50`; the full walk (offset 0→50→100→137) neither duplicates nor omits any (SC-006).

### Tests for User Story 3 (TDD — write first, verify they FAIL)

- [X] T020 [P] [US3] Write failing pagination tests in `tests/unit/test_transactions_pagination.py`: ascending `occurred_at` order with tie-break `(account_hash, activityId)`; page of at most 50 (clarify Q4); `total_count` = total of the full range; `has_more=true` ⇔ `next_offset` present and `returned==50`; `next_offset` ⇒ `has_more=true`; walk of 137 movements in 3 pages with zero duplicates/zero omissions (SC-006); final page without `next_offset`; range fitting one page without continuation indicator; `offset_echo` reflects the applied offset; last partial page (< 50, `has_more=false`)

### Implementation for User Story 3

- [X] T021 [US3] Implement sorting and page slicing in `src/schwab_mcp/transactions.py` (slicing over the merged and sorted history; `total_count`/`returned`/`has_more`/`next_offset`/`offset_echo` fields from data-model.md) and register `offset` in the tool input schema in `src/schwab_mcp/server.py` (F1 from analyze: the parameter lands together with its behavior) — makes T020 pass (Green)

**Checkpoint**: All three user stories work independently.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Cross-cutting constitution gates (performance, token-usage, docs) and end-to-end verification

- [X] T022 Write budget tests in `tests/performance/test_transactions_budgets.py` (`performance` marker): p95 latency ≤ 5 s over a set of ≥ 20 varied queries with a fast fake client (SC-001; measures own overhead — latency against the real provider is validated live in S5 of the quickstart, F7 from analyze) and payload size: default page of 50 movements ≤ 16 KB (SC-003) and extended page ≤ 64 KB (contract); run until green
- [X] T023 [P] Update `docs/tools.md`: new `get_transaction_history` section (fourth MCP tool: invocation, arguments, output schema, outcomes/detail, errors, pagination, guarantees, upcalls, operational caveat of `200 + []` from permissions — research R8) and update the registered-tool count in the initial table
- [X] T024 [P] Update `docs/CHANGELOG.md` with the feature entry (docs version 0.4.0)
- [X] T025 Final validation: `uv run pytest` full suite green and 0 skipped; walk through scenarios S1–S6 of `quickstart.md` (the live ones require the owner's valid credentials); verify updated docs without obsolete behaviors (constitution documentation-currency gate)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — immediate
- **Foundational (Phase 2)**: T002→T003 (Red→Green), T004→T005 (Red→Green); BLOCKS all user stories
- **US1 (Phase 3)**: depends on Phase 2; within the phase: tests T006–T009 (Red, parallelizable) → implementation T010–T015 in order (T010 depends on T006; T011 on T007+T003+T005; T012 on T008+T011; T013 on T009; T014 on T011; T015 on T014)
- **US2 (Phase 4)**: depends on US1 (extends the orchestration of T011 and the registration T014)
- **US3 (Phase 5)**: depends on US1 (paginates the merged result of T011); can be done in parallel with US2 if capacity allows (different files… same module: coordinate commits)
- **Polish (Phase 6)**: depends on all user stories complete

### User Story Dependencies

- **US1 (P1)**: MVP — starts after Foundational, no dependencies between stories
- **US2 (P2)**: refines US1 (filter); independently valuable once US1 exists
- **US3 (P3)**: refines US1 (pagination); independently valuable once US1 exists

### Parallel Opportunities

- T002/T004 (Foundational Red) are different files: parallel
- All US1 Red tests (T006–T009) are different files: parallelizable
- US2 (T016–T017) and US3 (T020) can be written in parallel (different test files)
- T023/T024 (docs) parallelizable with each other after implementation

---

## Parallel Example: User Story 1

```bash
# US1 Red tests in parallel (4 different files):
Task: "Write failing mapping tests in tests/unit/test_transactions_mapping.py"
Task: "Write failing orchestration tests in tests/unit/test_transactions_query.py"
Task: "Write failing split tests in tests/unit/test_transactions_split.py"
Task: "Write failing event tests in tests/unit/test_transactions_events.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: Setup (green baseline)
2. Phase 2: Foundational (models + validation) — CRITICAL
3. Phase 3: User Story 1 (full history by range)
4. **STOP and VALIDATE**: quickstart S1 + green suite → the tool already delivers the core value requested ("everything, not only trades")
5. US2 and US3 add focus and token economy on top

### Incremental Delivery

- +US2: instrument filter with honest disambiguation (`instrument_not_found` vs empty)
- +US3: deterministic pagination for large ranges
- Each story is a commit (or logical group) with a green suite and up-to-date docs

### Notes

- No new dependencies in the whole feature (plan: Research R1–R10)
- The SDK validator bypass lives ONLY in the helper of `transactions.py` with `finally` (research D2)
- No unredacted provider free text in events (contracts/events.md)
- Stop at each checkpoint to validate the story independently

---

## Phase 7: Convergence

- [X] T026 CRITICAL: rewrite the 0.4.0 entry of `docs/CHANGELOG.md` so it describes the actual implementation confirmed in the commit — models `MovementEntry`/`TransactionsResult` (not `TransactionEntry`/`TransactionHistoryResult`/`TransactionType`), field `movements` (not `transactions`), closed category enum `trade`/`transfer`/`dividend_or_interest`/`adjustment`/`other` (+ reserved, no `withholding`/`other_transaction`), explicit `offset` pagination with `has_more`/`next_offset` (not "automatic client-side pagination"), absence of the `bisection_applied` field (bisection is internal at the 3000 cap, research D3), real input fields (`occurred_at`, `amount`, `currency`, `symbol`, `instrument_type`, `extended`) and events `transactions_query_start`/`transactions_query_success`/`transactions_query_failure` from `log.py`; while at it, update the "Document version" line of `docs/tools.md` to 0.4.0 per Constitution (Commit Discipline — Documentation currency) and T024 (contradicts)
- [X] T027 Consolidate the 3000-cap trigger into a single source of truth: make `_bisect_range()` in `src/schwab_mcp/transactions.py` use `_should_split()` (or remove the dead helper and pin it in one place), keeping `tests/unit/test_transactions_split.py` green per Constitution II — DRY and plan: research D3 (partial)

---

## Phase 8: Live Validation Fixes

**Purpose**: defects found during manual live validation against the
real API (2026-10-23) that the suite with dict-based fakes did not
detect.

- [X] T028 CRITICAL: unwrapping of SDK responses — new module
  `src/schwab_mcp/provider.py` with `response_json()` (single source of
  truth): `.json()` of the body and HTTP status classification (401/403 →
  reauth, 5xx/408/429 → transient, remaining 4xx → `provider_error` per
  account, malformed JSON → transient); applied to `linked_accounts()`,
  `transactions()` and `instruments()` in `transactions.py`; the account
  hash is extracted from `hashValue` (real shape of the payload of
  `linked_accounts()`); regression tests in
  `tests/unit/test_transactions_live_response.py` — the tool failed
  live with `AttributeError: 'Response' object has no attribute 'get'`
  per SC-002 (contradicts)
- [X] T029 Send provider ISO-8601 datetimes bounded in
  America/New_York (midnight to 23:59:59 local, real DST offset) instead
  of raw `YYYY-MM-DD` — the API rejects the raw format with HTTP 400
  (`'2026-09-01' is not a valid value for startDate`); helper
  `_provider_datetime()` with updated contract test per FR-004 and the
  spec's Assumptions (missing)
- [X] T030 Adapt the mapper to the real payload shape: timestamp in
  `time` (not `transactionDate`), JSON list at the top level (not
  envelope `{"transactions": [...]}`), instrument inside
  `transferItems[].instrument` with `assetType`; tests Red→Green in
  `test_transactions_live_response.py::TestRealProviderShape` per FR-005
  (partial)
- [X] T031 Convert validation errors and `instrument_not_found` into
  `ToolError` at the tool boundary (`get_transaction_history_tool`,
  registration in `server.py`) so the actionable message reaches the agent
  instead of the generic MCP SDK text per FR-009d and SC-005 (partial)
- [X] T032 Fix the instruments upcall projection to
  `symbol-search` (the SDK validator rejects `SYMBOL_SEARCH`);
  update research.md D6, `contracts/mcp-tools.md`, `docs/tools.md`
  (caveat of internal identifiers like `CURRENCY_USD`) and the CHANGELOG
  per Constitution — Documentation currency (contradicts)
- [X] T033 Normalize `SCHWAB_CALLBACK_URL` in `load_config()` by removing
  trailing slashes: the Schwab developer portal may **require** the
  trailing slash in the registered callback (without it the app enters
  error state and cannot be submitted for approval), while `schwabdev`
  rejects callbacks ending in `/`; normalization in `config.py` (single
  source of truth) makes both forms work without touching the app
  registration; regression test in `test_config.py` + updated docs
  (`docs/installation.md`, `docs/usage.md`, CHANGELOG) per Constitution II and
  Documentation currency (contradicts)