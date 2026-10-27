---

description: "Task list for feature 007-underlying-symbol-filter implementation"
---

# Tasks: Underlying-aware symbol filter (`get_transaction_history` 007)

**Input**: Design documents from `/specs/007-underlying-symbol-filter/`

**Prerequisites**: [plan.md](./plan.md) · [spec.md](./spec.md) · [research.md](./research.md) · [data-model.md](./data-model.md) · [contracts/](./contracts/) · [quickstart.md](./quickstart.md)

**Tests**: MANDATORY — the constitution (Principle I: Test-First)
requires tests written first and failing (Red) before each
implementation (Green). Each user story phase includes its TDD tests.

**Organization**: Tasks grouped by user story (spec.md: US1 P1 — filter
by underlying; US2 P2 — `underlying_symbol` per movement) for
independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no pending dependencies)
- **[Story]**: Owning user story (US1, US2)
- Exact paths in each description

## Path Conventions

- Single project: `src/schwab_mcp/` + `tests/{unit,performance}/`
- Modified module: `src/schwab_mcp/transactions.py` (matcher, root
  derivation, orchestration and mapper); no new code files
- Tests in the same file are NOT marked [P] against each other

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Repo baseline — no new dependencies (plan: "No new dependencies")

- [X] T001 Verify baseline in `007-underlying-symbol-filter`: run `uv sync` and `uv run pytest` — full suite green, 0 skipped, no code changes (constitution commit gate)

**Checkpoint**: baseline green; TDD can start.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Pure matching and root-derivation functions — prerequisite for BOTH user stories

**⚠️ CRITICAL**: No user story starts before this phase is complete.

- [X] T002 Write failing tests (Red) for root derivation and matching in `tests/unit/test_transactions_underlying.py`: `_option_root()` per data-model §1-R1 (root = `symbol[:-15].strip()` when the last 15 chars match the OCC pattern — `YYMMDD` digits + `C`/`P` + 8 digits; right-anchored, padding-independent: `"AMD   261120P00630000"` → `"AMD"`, unpadded root; symbol without identifiable OCC encoding → `None`); matcher of the 3 forms of data-model §2 (M1 exact registered symbol · M2 option root · M3 complete OCC), case-insensitive (`"nok"` matches `"NOK"` and NOK's OCC), **no fuzzy** (substring/partial does NOT match: `"NO"` does not match `"NOK"`), `CURRENCY_USD` matches via M1
- [X] T003 Implement `_option_root(symbol) -> str | None` and the pure matcher (`movement_involves_filter(symbol, instrument_type, filter) -> bool` or equivalent) in `src/schwab_mcp/transactions.py` (pure functions, no I/O; reuse the right-anchoring knowledge of `_parse_occ_option_symbol` in positions.py without duplicating its strike logic) — makes T002 pass (Green)

**Checkpoint**: matcher + derivation ready; US1 and US2 can start.

---

## Phase 3: User Story 1 - Filter by underlying instrument (Priority: P1) 🎯 MVP

**Goal**: With `symbol="NOK"`, obtain ALL movements involving NOK in any registered form (registered symbol, option root, complete OCC), with guaranteed subset-consistency and dual validation.

**Independent Test**: With fixtures mixing an NOK equity trade, NOK option trades and movements of other instruments, the filtered query returns exactly the first two groups; the lowercase query returns the same; the filtered result is an exact subset of the unfiltered one.

### Tests for User Story 1 (TDD — write first, verify they FAIL)

- [X] T004 [P] [US1] Write failing tests for the filtered query in `tests/unit/test_transactions_filter_query.py` (fake client like `LiveLikeClient` from `test_transactions_live_response.py`): the orchestration **no longer sends** `symbol` upstream (the `transactions()` calls do not carry the `symbol` kwarg); `symbol="NOK"` returns NOK equity trades + options with root NOK and nothing else; `symbol="NOK   261218P00011000"` (complete OCC) returns only that option; `"nok"` ≡ `"NOK"`; the lowercase complete OCC (`"nok   261218p00011000"`) ≡ the exact OCC; subset-consistency (data-model §4): locally filtering the unfiltered result with the matcher produces the same set as the filtered query; pagination over the filtered set (`total_count` of the subset; walk with `offset` without duplicates or omissions); dual validation (FR-003): directory does NOT resolve + matching movements → `ok` with results; directory does NOT resolve + zero matches → `InstrumentNotFoundError` naming the filter (via `get_transaction_history_tool` → `ToolError`); `detail=no_movements_for_instrument` only when nothing matches; `CURRENCY_USD` returns its movements (data-model §2-step 4); `partial_failure` with an active filter — successful accounts contribute movements that match the filter and failed ones go to `accounts_failed` (FR-008), an entire account is never discarded by the filter
- [X] T005 [US1] Implement the filter semantics in `src/schwab_mcp/transactions.py`: remove the `symbol` kwarg from the `client.transactions(...)` call (research R1); dual validation — wrap the `validate_symbol` lookup so `InstrumentNotFoundError` does NOT abort: proceed with the sweep and only raise the error if the merged and deduplicated set has no matcher match (FR-001/FR-003); after merge/dedup/sort, filter with the matcher when `symbol` is present BEFORE paginating; `total_count`/`returned`/`has_more`/`next_offset` computed over the subset; `detail` per data-model §3 — makes T004 pass (Green). **Commit note**: T005 leaves the legacy tests of `test_transactions_symbol.py` red until T006 updates them to the new contract — commit T005+T006 as a single commit (constitution *green-before-commit* gate)
- [X] T006 [US1] Update the legacy symbol tests in `tests/unit/test_transactions_symbol.py` to the new contract: tests that pin sending `symbol=` upstream are inverted (verify it is NOT sent); the immediate `instrument_not_found` tests are adapted to dual validation (error only with zero matches); keep the zero-`instruments`-upcall tests without `symbol` — entire file green

**Checkpoint**: US1 complete and independently testable: the underlying filter delivers all the instrument's activity (MVP).

---

## Phase 4: User Story 2 - Underlying reference on option movements (Priority: P2)

**Goal**: Every option movement exposes `underlying_symbol` (OCC root, unpadded) in the curated output; non-options unchanged.

**Independent Test**: With option-movement fixtures (real padded OCC) and a non-option, the mapper adds `underlying_symbol="NOK"` only to options; the unidentifiable OCC case omits the field.

### Tests for User Story 2 (TDD — write first, verify they FAIL)

- [X] T007 [P] [US2] Write failing tests for the field in `tests/unit/test_transactions_underlying.py` (`TestUnderlyingSymbol` section): `map_provider_transactions` with a real option trade (padded OCC, `instrument_type="OPTION"`, real provider shape) → `underlying_symbol` present with the unpadded root; non-option movements (equity TRADE, DIVIDEND_OR_INTEREST, transfer) → field **absent** (not `null`, excluded by `exclude_none`); option with a symbol without identifiable OCC encoding → field absent; extended passthrough unchanged (the field is not duplicated in `extended`); no secrets: `underlying_symbol` carries only public instrument identifiers
- [X] T008 [US2] Implement the derivation in `map_provider_transactions` in `src/schwab_mcp/transactions.py`: when `instrument_type == "OPTION"` and `_option_root(symbol)` is not `None`, add `kwargs["underlying_symbol"] = root` (existing optional-field pattern: only set when applicable) — makes T007 pass (Green)

**Checkpoint**: US1 and US2 work independently.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Cross-cutting constitution gates (performance, docs) and end-to-end verification

- [X] T009 Extend the budgets in `tests/performance/test_transactions_budgets.py`: worst-case default page = 50 movements **all options** with `underlying_symbol` ≤ 16 KB (SC-003/FR-007) and extended page ≤ 64 KB; p95 latency ≤ 5 s unchanged (upcalls do not increase)
- [X] T010 [P] Update `docs/tools.md`: filter semantics (contract §1 table: underlying includes options; complete OCC supported; lowercase; dual validation), `underlying_symbol` row in the `MovementEntry` schema, replacement of the caveat "filtering options by underlying does not work" with the new behavior; update `docs/CHANGELOG.md` with the feature entry (docs version 0.5.0)
- [X] T011 Final validation: `uv run pytest` full suite green and 0 skipped; walk through the S1–S6 scenarios of `quickstart.md` (live ones require the owner's valid credentials); verify updated docs without obsolete behaviors (constitution documentation-currency gate)

---

## Phase 6: Convergence

- [X] T012 Remove the dead function `validate_symbol()` from `src/schwab_mcp/transactions.py` (left without references in `src/` and `tests/` after T005's dual validation) and keep `_symbol_resolved_in_directory()` as the single source of truth for the "empty response = unknown symbol" logic — verification: suite green after the removal per plan: research R3 / Constitution II (unrequested)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — immediate
- **Foundational (Phase 2)**: T002→T003 (Red→Green); BLOCKS both user stories
- **US1 (Phase 3)**: depends on Phase 2; within the phase: T004 (Red) → T005 (Green) → T006 (legacy tests to the new contract)
- **US2 (Phase 4)**: depends on Phase 2; can run in parallel with US1 if capacity allows (tests in different files; T005 and T008 touch the same module — coordinate commits)
- **Polish (Phase 5)**: depends on both user stories complete

### User Story Dependencies

- **US1 (P1)**: MVP — starts after Foundational, no dependencies between stories
- **US2 (P2)**: additive field; independent in value once US1 exists (and also benefits unfiltered queries)

### Parallel Opportunities

- T004 (US1 tests) and T007 (US2 tests) are in different files: parallelizable
- T010 (docs) parallelizable after implementation
- T005 and T008 are NOT parallel with each other (same file `transactions.py`)
- **T002 (Phase 2) and T007 (Phase 4) edit the same file** `tests/unit/test_transactions_underlying.py` in different phases — run in order (T002 → T003 → … → T007); if more than one agent runs, coordinate to avoid conflict

---

## Parallel Example: User Story Tests

```bash
# Red tests of the two stories in parallel (different files):
Task: "Filtered-query tests in tests/unit/test_transactions_filter_query.py"
Task: "Underlying-field tests in tests/unit/test_transactions_underlying.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: Setup (green baseline)
2. Phase 2: Foundational (matcher + root) — CRITICAL
3. Phase 3: User Story 1 (filter by underlying)
4. **STOP and VALIDATE**: S1 of quickstart + green suite → the agent can already ask for "everything NOK" in a single query
5. US2 adds the `underlying_symbol` field on top

### Incremental Delivery

- +US2: the curated output becomes self-descriptive (grouping by underlying without parsing OCC)
- Each story is a commit (or logical group) with a green suite and up-to-date docs

### Notes

- No new dependencies in the whole feature (plan: research R1–R7)
- The filter no longer travels upstream: subset-consistency by construction (research R1)
- The `CURRENCY_USD` case changes from error to results — documented in contract §3 and in `docs/tools.md` (T010)
- No unredacted provider text in events (006's contracts/events.md, unchanged)
- Stop at each checkpoint to validate the story independently