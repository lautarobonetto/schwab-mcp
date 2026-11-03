---
description: "Task list for feature 012-option-expiration-list"
---

# Tasks: Option Expiration List (`get_option_expiration_chain`)

**Input**: Design documents from `/specs/012-option-expiration-list/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅,
contracts/ ✅, quickstart.md ✅

**Tests**: INCLUDED — TDD is constitutionally mandatory (Principle I).
Every user-story phase writes FAILING tests first, then minimal
implementation to pass them (Red → Green → Refactor).

**Organization**: Tasks grouped by user story (US1 → US2 → US3 from
spec.md). US1 alone delivers the complete MVP tool; US2 and US3 extend it.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1/US2/US3)
- Exact file paths included in every description

## Path Conventions

Single project (per plan.md): code in `src/schwab_mcp/`, tests in
`tests/`, docs in `docs/`. The feature extends the existing option-domain
module `src/schwab_mcp/options_chain.py` — no new modules (research R3).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Fixture machinery shared by every user story's tests.

- [X] T001 [P] Add `build_expiration_chain_payload` fixture builder to
      tests/unit/helpers.py — builds a provider-shaped expiration-chain
      payload (`{"status": "success", "errorCode": null, "expirations":
      [...]}` per data-model.md §2) from (date, dte, settlement_type)
      tuples, plus a reusable `FakeExpirationClient` with an
      `option_expiration_chain(symbol)` method returning a
      `build_response(...)`-style object (mirror the FakeChainClient
      pattern in tests/integration/test_options_chain.py). Follow the
      existing helpers' style; no production code.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Pin the real provider payload shape before any mapping code
exists (research.md R2 — the field-name evidence is currently
community-documented, not live-confirmed).

**⚠️ CRITICAL**: No user-story mapping work can begin until T002 is done.

- [X] T002 Capture one live provider payload: run the documented probe
      (research.md R2 — the MCP's own token machinery, e.g. via a
      throwaway MCP server session or the credentials env sourced with
      `schwab_mcp.schwabdev_compat.install_trailing_slash_callback_support()`)
      for a liquid optionable symbol (AAPL), then (a) commit the captured
      payload as a fixture module at
      tests/unit/fixtures/expiration_chain_payloads.py (market data only —
      NEVER credentials or account identifiers, per constitution Credential
      Safety; follow the existing fixture-module style of
      tests/unit/fixtures/quotes_payloads.py), and (b) record the exact
      provider field names for expiration date / DTE / settlement type in
      the docstring of `build_expiration_chain_payload`
      (tests/unit/helpers.py) pointing at that fixture. If the live field
      names differ from the candidate set (`expirationDate`,
      `daysToExpiration`, `settlementType`), note the correction here and
      in specs/012-option-expiration-list/research.md R2. The curated
      schema (data-model.md §2) MUST NOT change — only the provider-key
      mapping does. If the live capture is temporarily impossible
      (invalid tokens), record that in research.md R2 and pin the fixture
      from the best available evidence, flagging it for re-capture before
      the final commit gate (T018).

**Checkpoint**: Provider field names pinned; fixture builder matches the
live shape. US1 can begin.

---

## Phase 3: User Story 1 — List available expirations for an underlying in one call (Priority: P1) 🎯 MVP

**Goal**: `get_option_expiration_chain` returns the ordered curated
expiration list (date, DTE, settlement type) with the shared outcome
envelope, registered as an MCP tool.

**Independent Test**: invoke the tool with one valid symbol and no other
parameters → `outcome: "ok"`, `filters.dte_max_effective == 60`, ascending
expirations with `dte` and `settlement_type`, zero strikes/quotes/greeks,
within one provider call.

> **TDD**: write T003–T004 first; they MUST fail (no production function
> exists yet). T005–T007 are the minimal implementation that turns them
> green.

### Tests for User Story 1 ⚠️ write FIRST, ensure they FAIL

- [X] T003 [P] [US1] Write FAILING unit tests for curated mapping in
      tests/unit/test_option_expirations.py: from a fixture payload (via
      `build_expiration_chain_payload`) assert — each entry carries
      `expiration_date` (provider value passed through unmodified), `dte`
      (calendar days computed locally from today, NOT the provider's
      `daysToExpiration` — research R4), `settlement_type` (provider value
      passed through; explicit `null` when the provider omits it — never
      inferred); list ascending by `expiration_date`; same-date entries
      kept as separate rows distinguished by `settlement_type` (never
      merged — data-model §2 identity rule); missing provider fields yield
      explicit `null`, never invented values.
- [X] T004 [P] [US1] Write FAILING integration tests in
      tests/integration/test_option_expirations.py using
      `FakeExpirationClient`: default invocation (symbol only) → exactly
      ONE `option_expiration_chain` upcall (SC-004); result carries the
      shared envelope (`symbol`, `generated_at`, `outcome: "ok"`,
      `filters: {dte_max_requested: null, dte_max_effective: 60}`,
      `expiration_count == len(expirations)`); curated-only assertion —
      no `strikes`, quotes, or greek keys anywhere (SC-003); provider 400
      response → `outcome: "no_options_listed"`, `retryable: false`,
      `expirations: []`.

### Implementation for User Story 1

- [X] T005 [US1] Implement `_fetch_expiration_chain(client, query)` in
      src/schwab_mcp/options_chain.py mirroring `fetch_option_chain`
      (lines 261–309): `query.validate()` before any upcall, then
      `retry_call(client.option_expiration_chain, 0, symbol)` +
      `retry_call(response_json, 0, response=response)`; HTTP 400 after
      validation → return `{}` (live "no options listed" shape, research
      R6). Provider failures surface as the shared taxonomy
      (`ConnectivityError`, `ReauthorizationRequiredError`, `ValueError`).
      (depends T003)
- [X] T006 [US1] Implement `build_expiration_result(payload, query,
      today)` and `get_option_expiration_chain(client, symbol, dte_max=None,
      extended=False)` in src/schwab_mcp/options_chain.py: build
      `OptionChainQuery(symbol=..., dte_max=...)` (reuse — defaults keep
      unused fields valid, research R3); validate before upcall with
      `auth_event` start/failure/success events mirroring
      `get_option_chain` (lines 699–784); map per T003 semantics; apply
      `dte ≤ dte_max_effective`; outcomes `ok` /
      `no_expirations_in_range` (retryable, detail names the cap) /
      `no_options_listed` (payload `{}`); `_result_meta` reuse for
      `symbol`/`generated_at`; `filters` echo
      `{dte_max_requested, dte_max_effective}` (data-model.md §2). Make
      T003 pass. (depends T005)
- [X] T007 [US1] Implement `get_option_expiration_chain_tool(...)` wrapper
      in src/schwab_mcp/options_chain.py converting
      `ValueError`/`TypeError` into `ToolError` with the actionable
      message (mirror `get_option_chain_tool`, lines 792–821), and
      register the tool in src/schwab_mcp/server.py with the exact
      `get_option_chain` pattern (lines 191–221: wrapper sets
      `__name__`/`__qualname__`, `mcp.add_tool` with a one-line
      description pointing at `extended`). Make T004 pass. (depends T006)

**Checkpoint**: MVP — `get_option_expiration_chain` fully functional and
independently testable (`uv run pytest tests/unit/test_option_expirations.py
tests/integration/test_option_expirations.py` green).

---

## Phase 4: User Story 2 — Narrow or widen the expiration window with an explicit DTE ceiling (Priority: P2)

**Goal**: `dte_max` behaves exactly like `get_option_chain` (≥ 1 replaces
the 60-day default, no hard upper limit) with the `dte_max_effective` echo
and the structured empty-range outcome.

**Independent Test**: `dte_max=30` → only entries with `dte ≤ 30` and echo
`30`; `dte_max=365` → accepted (`dte_max_effective == 365`); a ceiling
that excludes everything → `no_expirations_in_range`, `retryable: true`,
cap in `detail`; `dte_max=0` → validation error naming `>= 1` before any
upcall. This phase's tests also close spec.md US1 acceptance scenario 2
(the all-beyond-ceiling empty outcome), which belongs to US2's ceiling
semantics.

> **TDD**: T008–T009 FAILING first; T010 makes them pass.

### Tests for User Story 2 ⚠️ write FIRST, ensure they FAIL

- [X] T008 [P] [US2] Write FAILING unit tests in
      tests/unit/test_option_expirations.py: `dte_max=30` excludes entries
      with `dte > 30`; `dte_max=365` accepted — every entry inside the
      fixture and `dte_max_effective == 365` (no hard upper limit —
      clarification 2026-11-03 Q1 option A); `dte_max=0` and `dte_max=-1`
      → `ValueError` naming `dte_max` and `>= 1`; `dte_max="30"` and
      `dte_max=True` → `TypeError` (bool is not int — 008 validation
      semantics); an unknown extra parameter (e.g. `max_strikes`) →
      `TypeError` naming the parameter (contracts/mcp-tools.md §4);
      empty and whitespace-containing symbols → `ValueError`
      before any upcall.
- [X] T009 [P] [US2] Write FAILING integration tests in
      tests/integration/test_option_expirations.py: `dte_max=30` →
      `filters == {dte_max_requested: 30, dte_max_effective: 30}` and only
      `dte ≤ 30` entries (SC-005 semantics mirror); fixture where every
      expiration lies beyond the ceiling → `outcome:
      "no_expirations_in_range"`, `retryable: true`, `expirations: []`,
      `expiration_count: 0`, `detail` names the effective cap; exactly one
      upcall per scenario (SC-004).

### Implementation for User Story 2

- [X] T010 [US2] Complete the DTE-ceiling and empty-outcome paths of
      `get_option_expiration_chain` in src/schwab_mcp/options_chain.py so
      T008 and T009 pass (the ceiling application and `dte_max_effective`
      come from the reused `OptionChainQuery`; add the
      `no_expirations_in_range` branch and echo if T006 stubbed them).
      (depends T006, T008, T009)

**Checkpoint**: US1 + US2 both work independently — window control with
008-identical semantics.

---

## Phase 5: User Story 3 — Full raw expiration payload on request (Priority: P3)

**Goal**: `extended=true` adds the raw provider payload under `"provider"`
(C-09 pattern), curated path unchanged.

**Independent Test**: with `extended=true` the result includes the exact
provider payload; without it, no `"provider"` key exists.

> **TDD**: T011 FAILING first; T012 makes it pass.

### Tests for User Story 3 ⚠️ write FIRST, ensure they FAIL

- [X] T011 [P] [US3] Write FAILING integration tests in
      tests/integration/test_option_expirations.py: `extended=True` →
      `result["provider"]` equals the raw provider payload dict returned
      by the fake client (unchanged, research R6); default
      `extended=False` → no `"provider"` key; both outcomes still carry
      the curated fields (US3 acceptance scenarios 1–2 of spec.md).

### Implementation for User Story 3

- [X] T012 [US3] Add the `extended` passthrough branch to
      `get_option_expiration_chain` in src/schwab_mcp/options_chain.py
      (`result["provider"] = payload` — mirror `get_option_chain` lines
      776–777) so T011 passes. (depends T006, T011)

**Checkpoint**: All three user stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Budget gates, docs, security regression, and commit-gate
validation across all stories (constitution Principle V + Credential
Safety + Commit Discipline).

- [X] T013 [P] Write the FAILING budget tests first, then confirm green:
      tests/performance/test_option_expirations_budgets.py — token budget
      (SC-001): representative ~8-entry fixture (AAPL-style) ≤ 1,000
      tokens, dense 60-entry worst case ≤ 1,100 tokens (recorded ceiling)
      measured as `len(json.dumps(result, separators=(",", ":"))) / 4`;
      latency budget (SC-002): ≤ 5 s per invocation measured (008
      precedent), inside the 10 s spec ceiling; one-upcall invariant
      (SC-004) asserted per scenario. (Budget growth justification in
      plan.md Complexity Tracking.)
- [X] T014 [P] Add the `get_option_expiration_chain` section to
      docs/tools.md per contracts/mcp-tools.md: input table (symbol,
      dte_max ≥ 1 semantics, extended), output schema, outcomes table,
      validation errors, normative agent guidance (§5 of the contract),
      budgets (§6). English only (Principle VII).
- [X] T015 [P] Add the feature entry to docs/CHANGELOG.md (new tool,
      semantics summary, docs updated).
- [X] T016 [P] Add a per-tool zero-secrets regression section for
      `get_option_expiration_chain` to tests/unit/test_no_secrets_in_output.py,
      mirroring the existing "Positions tool — zero secrets in all outcome
      forms" section (line ~630): run the new tool through a fake client
      (ok, no_expirations_in_range, no_options_listed, and extended=true
      outcomes) and assert the tool output, its log events, and the
      raw provider payload contain no credentials, tokens, or account
      identifiers (constitution Credential Safety MUST).
- [X] T017 Refresh the codebase-memory-mcp index for this repository
      (graph currency gate — constitution Development Workflow gate 7) and
      verify the new functions appear in `get_file_outline` of
      src/schwab_mcp/options_chain.py.
- [X] T018 Run quickstart.md validation end to end: the three test suites
      green, then full `uv run pytest` green with 0 skipped (commit gate),
      then the live smoke scenarios if credentials are valid. Confirm the
      committed fixture (T002) reflects live data before this gate.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001 — no dependencies, start immediately.
- **Foundational (Phase 2)**: T002 depends on T001 (field names are
  recorded in the helper's docstring). BLOCKS all user stories.
- **US1 (Phase 3)**: T003, T004 after T002; T005 after T003; T006 after
  T005; T007 after T006.
- **US2 (Phase 4)**: T008, T009 after T006 (tests exercise the real
  function signature); T010 after T006/T008/T009.
- **US3 (Phase 5)**: T011 after T006; T012 after T006/T011.
- **Polish (Phase 6)**: T013 after T006 (needs the implementation to go
  green); T014–T016 after T007 (tool semantics final); T017 after all
  code; T018 last.

### User Story Dependencies

- **US1 (P1)**: no dependencies on other stories — complete MVP on its own.
- **US2 (P2)**: extends US1's function; independently testable via its own
  scenarios.
- **US3 (P3)**: extends US1's function; independently testable.

### Parallel Opportunities

- T001 alone in setup; T003 and T004 (different files: unit vs
  integration) run together; T008 and T009 together; T011 alone.
- T013, T014, T015, T016 are mutually parallel (different files) once US1
  is green.
- US2 and US3 phases can interleave after T006 (both are thin branches of
  the same function — prefer sequential edits to avoid same-file
  conflicts; their TEST tasks T008/T009 and T011 are parallelizable).

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. T001 → T002 → T003/T004 (red) → T005 → T006 → T007 (green)
2. **STOP and VALIDATE**: quickstart.md §1 suites green; the tool answers
   "which expirations exist?" in one cheap call.
3. Commit only after the FULL suite is green (commit gate).

### Incremental Delivery

1. MVP (US1) → validate → commit.
2. Add US2 (window control) → validate → commit.
3. Add US3 (extended passthrough) → validate → commit.
4. Polish phase → budgets + docs + index refresh → final commit gate.

### Notes

- Every commit: full suite green, 0 skipped, docs current
  (constitution Commit Discipline).
- Same-file warning: T005/T006/T007/T010/T012 all touch
  src/schwab_mcp/options_chain.py — execute sequentially in ID order.
- Provider field names: if T002's live capture contradicts the candidate
  key set, update ONLY the provider-key mapping in T005/T006 and the
  fixture builder — the curated schema and all tests' curated assertions
  are unchanged (research R2).

---

## Phase 7: Convergence

> Appended by `/speckit.converge` (2026-11-03) after `/speckit.implement`
> completed Phases 1–6. Assessment found the implementation satisfies all
> 13 FRs, 8 acceptance scenarios, 5 success criteria, 6 edge cases, and
> every plan decision and constitution principle; two partial gaps remain
> (1 MEDIUM, 1 LOW).

- [X] T019 Re-capture the live provider payload and run the live smoke
      validation once the token store is renewed (`schwab-mcp auth` — the
      stored refresh token is expired/revoked; research R2, T002 fallback,
      T018 live gate skipped): run the documented probe
      (tmp/ machinery of T002) for AAPL, confirm or correct the pinned
      field names in tests/unit/fixtures/expiration_chain_payloads.py and
      the `build_expiration_chain_payload` docstring (tests/unit/helpers.py)
      — if a name differs, update ONLY the provider-key mapping and the
      fixture, never the curated schema — clear the re-capture flag in
      research.md R2 and the fixture module docstring, then run the
      quickstart.md §3 live smoke scenarios (default, dte_max 30/365, SPX
      same-date rows, failure shapes). per research R2 / T018 (partial)
- [X] T020 Add a unit test pinning the tool boundary's ToolError
      conversion: `get_option_expiration_chain_tool` must convert domain
      validation errors (`ValueError`/`TypeError`, e.g. `dte_max=0`,
      empty symbol) into the MCP SDK's `ToolError` carrying the actionable
      message — the contract §4 "never a raw stack trace" promise at the
      MCP boundary (currently implemented but unasserted; 008's wrapper
      has the same gap — mirror the new test there only if the reviewer
      wants cross-feature symmetry). per contracts/mcp-tools.md §4 / US1
      AC3 (partial)