---
description: "Task list for Real-Time Quotes (`get_quotes`) (010)"
---

# Tasks: Real-Time Quotes (`get_quotes`)

**Input**: Design documents from `/specs/010-real-time-quotes/`

**Prerequisites**: plan.md, spec.md, research.md (D1–D7), data-model.md,
contracts/mcp-tools.md, quickstart.md — all complete.

**Tests**: REQUIRED — the project constitution (Principle I) mandates TDD:
every task group below writes tests first, verifies they FAIL, then
implements minimal code to pass. Bug-fix rule N/A (new feature).

**Organization**: Tasks grouped by user story (US1 single quote → US2 batch
→ US3 extended) so each story is an independently testable increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths included in every description

## Path Conventions

Single package: `src/schwab_mcp/`, `tests/` at repository root
(per plan.md Project Structure).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify the baseline and capture the provider payload evidence
the RED tests will pin.

- [X] T001 Run the full suite baseline gate: `uv sync && uv run pytest` —
  must be green with 0 skipped before any change (constitution test-suite
  gate)
- [X] T002 [P] Capture live provider quote payloads with a real authorized
  client into fixture JSON files for the RED tests: (a) single equity
  symbol, (b) 3-symbol batch mixing equity + index + option-contract, (c)
  one unknown symbol (response omits it), (d) `fields="all"` vs
  `fields="quote"` variants — save to
  `tests/unit/fixtures/quotes_payloads.py` (fixture constants only; no
  credentials, tokens, or account identifiers may appear in the fixtures —
  FR-010). **Fallback**: if no authorized live session is available at
  implement time, defer this task and derive the fixture payloads from the
  documented provider response shape
  (`specs/010-real-time-quotes/data-model.md`, `contracts/mcp-tools.md`)
  and the `schwabdev` client source, recording the deviation in the
  implementing commit message; replace with live-captured fixtures in a
  later commit when a session is available (S5 live validation)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The one artifact every user story depends on.

**⚠️ CRITICAL**: No user story work begins until this phase is complete.

- [X] T003 Create the quotes module skeleton in `src/schwab_mcp/quotes.py`:
  module docstring, `get_quotes(client, symbols, extended=False)` and
  `get_quotes_tool(client, symbols, extended=False)` signatures that raise
  `NotImplementedError`, importing the shared helpers it will reuse —
  `schwab_mcp.provider.response_json`, `schwab_mcp.errors`,
  `schwab_mcp.tokens.retry_call`, `schwab_mcp.log.auth_event`
  (skeleton only — NO behavior; RED tests of Phase 3 must fail against it)

**Checkpoint**: Baseline green; fixtures recorded; skeleton fails loudly.

---

## Phase 3: User Story 1 — Single-Symbol Curated Quote (Priority: P1) 🎯 MVP

**Goal**: The agent requests one symbol and receives a compact curated
quote (last, bid, ask, volume, net change, percent, `data_state`,
`trade_time`) within the token and latency budgets, with fail-fast
validation and no partial data.

**Independent Test**: invoke `get_quotes` with one valid symbol and a fake
or real client → response matches the `ok` envelope of
`contracts/mcp-tools.md`; invalid input fails before any upcall.

### Tests for User Story 1 (write FIRST — must FAIL, TDD ⚠️)

- [X] T004 [P] [US1] RED: validation tests in
  `tests/unit/test_quotes_validation.py` covering the normative grammars of
  research D5 — index `\$[A-Z0-9]{1,5}`, option contract
  `[A-Z0-9.]{1,6}[ _]?YYMMDD[CP][0-9]+(\.[0-9]+)?`, equity/ETF
  `[A-Z0-9]{1,6}` with at most one embedded `.`; empty list →
  `validation_error`/`empty_symbol_list`; malformed symbol →
  `errors[symbol] = "malformed_symbol"`; normalization (strip + uppercase)
  and de-duplication before the 20-distinct limit; over-limit →
  `validation_error`/`too_many_symbols` stating the limit; exactly 20 →
  proceeds; **assert the provider client received zero calls** for every
  validation failure (fail-before-upcall, FR-005/FR-007/FR-013)
- [X] T005 [P] [US1] RED: mapping tests in
  `tests/unit/test_quotes_mapping.py` using the Phase 1 fixtures — pin the
  provider→curated field mapping of data-model.md: `symbol`,
  `description` (truncated to 80 chars), `lastPrice→last`, `bidPrice→bid`,
  `askPrice→ask`, `totalVolume→volume`, `netPriceChange→net_change`,
  `net_change_pct` computed as `net_change / closePrice × 100` with `null`
  when `closePrice` is missing or 0, `tradeTime→trade_time` as ISO 8601
  UTC; rounding 2 decimals for equity/ETF/index symbols and 4 decimals for
  option-contract symbols; missing provider fields → explicit `null`
  (FR-012); response declares `quote_fields` (pattern of 008)
- [X] T006 [P] [US1] RED: data-state derivation tests in
  `tests/unit/test_quotes_data_state.py` pinning the D4 ladder — market
  closed → `closed` (regardless of `quoteType`);
  `quoteType == "Realtime"` → `realtime`; missing/other `quoteType` →
  `delayed`; market-hours call failure → structured retryable
  `provider_unreachable` error (never a guessed state); market-hours check
  invoked exactly once per invocation (not per symbol)
- [X] T007 [P] [US1] RED: audit-event tests in
  `tests/unit/test_quotes_events.py` — `quotes_query_start` (initiated) and
  `quotes_query_failure` with classification `validation` / `error` /
  `reauth` / `provider_unreachable` (pattern of `options_chain_query_*`);
  no credentials/tokens/account identifiers in any event or output
- [X] T008 [P] [US1] RED: integration tests for the single-symbol flows in
  `tests/integration/test_quotes.py` using fake clients (pattern of
  `tests/integration/test_options_chain.py`) — S1 `ok` envelope end to end;
  unknown symbol → `quote_unavailable` with `errors[symbol] = "not_found"`
  and NO partial `quotes` object (FR-006); provider 5xx/408/429 →
  retryable `provider_unreachable`; 401/403 → `reauth_needed` (shared
  taxonomy via `provider.response_json`)

### Implementation for User Story 1

- [X] T009 [US1] GREEN: implement input validation and normalization in
  `src/schwab_mcp/quotes.py` (kind grammars, strip/uppercase/de-dup, 20
  distinct limit, empty-list and malformed-symbol structured errors) —
  minimal code to pass T004 (depends on T003, T004)
- [X] T010 [US1] GREEN: implement the provider orchestration and curation
  in `src/schwab_mcp/quotes.py` — one `market_hours` call per invocation
  (D4), one `quotes()` call via `tokens.retry_call` with
  `fields="quote"`/`indicative=false`, `provider.response_json` unwrap,
  curated envelope (`outcome: "ok"`, `detail: "quotes_retrieved"`,
  `requested_count`, `quote_fields`, `quotes` keyed by symbol),
  missing-symbol detection (requested minus response keys → `not_found`),
  audit events — minimal code to pass T005, T006, T007, T008 (depends on
  T009)
- [X] T011 [US1] Register the tool in `src/schwab_mcp/server.py` following
  the 003/006/008 `mcp.add_tool` wrapper pattern (name `get_quotes`,
  parameters `symbols` string|list + `extended` bool), and add the
  registration assertions to `tests/unit/test_server_tool.py` (depends on
  T010)
- [X] T012 [US1] RED→GREEN: token-usage and latency budget tests in
  `tests/performance/test_quotes_budgets.py` (pattern of
  `test_options_chain_budgets.py`) — ≤ 250 tokens for a single curated
  quote (SC-002), ≤ 5 s p95 per invocation (SC-001); write tests first,
  verify they fail or pass against the fixture payload sizes, then adjust
  curation only if a real payload breaches budget (any budget growth
  requires recorded justification per constitution Principle V) (depends
  on T010)

**Checkpoint**: `get_quotes` works for a single symbol end to end —
validation, curation, freshness, errors, registration, budgets all green.
MVP validated independently via quickstart S1 + S4.

---

## Phase 4: User Story 2 — Batch Quotes for Several Instruments (Priority: P2)

**Goal**: 1..20 distinct symbols quoted in one invocation; response is an
object keyed by symbol with linear, budgeted payload growth.

**Independent Test**: invoke with a list of valid symbols (mixing kinds) →
exactly one keyed entry per distinct symbol; duplicates de-duplicated;
count and payload budgets hold.

### Tests for User Story 2 (write FIRST — must FAIL ⚠️)

- [X] T013 [P] [US2] RED: batch integration tests in
  `tests/integration/test_quotes.py` — 4-symbol batch mixing equity + ETF
  + index + option contract returns one entry per symbol keyed by symbol
  (clarification Q3); duplicate symbols in the request are de-duplicated
  (`requested_count` counts distinct); a single `quotes()` provider call
  carries the whole list (D1 — no per-symbol calls); mixed batch where the
  source omits one symbol → whole invocation is `quote_unavailable` with
  per-symbol `errors` and no partial data
- [X] T014 [P] [US2] RED: batch token-budget scaling tests in
  `tests/performance/test_quotes_budgets.py` — 10-symbol batch ≤ 2,500
  tokens (SC-002); response size grows linearly with symbol count, no
  hidden bulk (SC-005 path)

### Implementation for User Story 2

- [X] T015 [US2] GREEN: implement the batch path in
  `src/schwab_mcp/quotes.py` — distinct normalized symbol list joined for
  the single `quotes()` call, per-kind validation applied per entry, keyed
  result object built from the provider response — minimal code to pass
  T013 and T014 (depends on T010; touches only `quotes.py` + test files)

**Checkpoint**: US1 + US2 both work independently — single and batch share
one code path (D1) and one envelope (FR-008).

---

## Phase 5: User Story 3 — Extended Raw Payload (Priority: P3)

**Goal**: `extended=true` returns the complete raw provider payload
alongside the curated view, without a second tool.

**Independent Test**: invoke with `extended=true` → response carries both
`quotes` (curated, still within budget) and `provider` (raw
`fields="all"` payload keyed by symbol).

### Tests for User Story 3 (write FIRST — must FAIL ⚠️)

- [X] T016 [P] [US3] RED: extended-mode integration tests in
  `tests/integration/test_quotes.py` — success response contains BOTH the
  curated `quotes` object and `provider` with the complete raw payload
  (SC-006: verified against the Phase 1 `fields="all"` fixture); the
  provider call used `fields="all"` (assert on the fake client); the
  curated portion alone still respects the token budget; errors in
  extended mode follow the same structured envelope (no partial data)

### Implementation for User Story 3

- [X] T017 [US3] GREEN: implement the extended passthrough in
  `src/schwab_mcp/quotes.py` — `extended=true` switches the provider call
  to `fields="all"` (D2) and adds the raw `provider` channel to the
  success response (C-09 pattern of 003/006/008) — minimal code to pass
  T016 (depends on T015)

**Checkpoint**: All three user stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation currency, graph currency, and final gates.

- [X] T018 [P] Add the `get_quotes` section to `docs/tools.md` (fourth MCP
  tool): input schema, symbol-kind grammars, `ok`/error envelopes,
  `data_state` semantics, budgets, audit events — mirroring
  `specs/010-real-time-quotes/contracts/mcp-tools.md`
- [X] T019 [P] Record the addition in `docs/CHANGELOG.md` (new `get_quotes`
  tool, budgets, freshness states)
- [X] T020 Extend `tests/unit/test_no_secrets_in_output.py` to run the
  quotes tool output and audit events through the credential-safety
  assertions (FR-010)
- [X] T021 Refresh the codebase-memory-mcp index for the repository
  (constitution Principle VI graph-currency gate — index must be current
  before any later graph-based analysis)
- [X] T022 Run quickstart.md validation S1–S5 end to end, including one
  live validation pass against a real authorized client (S1 single quote,
  S2 batch, S3 extended, S4 failure attribution)
- [X] T023 Final commit gate: `uv run pytest` — full suite green with 0
  skipped; docs updated (T018/T019) included in the same commit per
  constitution Commit Discipline

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001 first (baseline), T002 [P] independent
- **Foundational (Phase 2)**: T003 depends on T001 (baseline green before
  code) — BLOCKS all user stories
- **US1 (Phase 3)**: RED tests T004–T008 [P] after T003; implementation
  T009 → T010 → T011/T012 sequential; all GREEN tasks require their RED
  tests failing first
- **US2 (Phase 4)**: RED T013/T014 [P] after T010 (US1 core exists);
  T015 depends on both
- **US3 (Phase 5)**: T016 [P] after T015; T017 depends on T016
- **Polish (Phase 6)**: T018/T019/T020 [P] after T017; T021 after T020;
  T022/T023 last (final gates)

### User Story Dependencies

- **User Story 1 (P1)**: no dependencies on other stories — MVP alone
- **User Story 2 (P2)**: builds on US1's orchestration (T010) but is
  independently testable via T013/T014
- **User Story 3 (P3)**: builds on US2's batch path but is independently
  testable via T016

### Within Each User Story

- RED tests first (TDD) → verify they FAIL → minimal implementation →
  verify GREEN → only then the next task

### Parallel Opportunities

- T002 (fixtures) parallel to T001 once baseline command is launched
- T004–T008 (all RED tests, five distinct files) run together after T003
- T011 + T012 parallel after T010 (different files)
- T013 + T014 (US2 RED tests) parallel
- T016 (US3 RED test) single
- T018 + T019 + T020 (docs + safety test) parallel after T017

---

## Parallel Example: User Story 1

```bash
# After T003 — launch all five RED test files together:
Task: "Validation tests in tests/unit/test_quotes_validation.py"
Task: "Mapping tests in tests/unit/test_quotes_mapping.py"
Task: "Data-state tests in tests/unit/test_quotes_data_state.py"
Task: "Audit-event tests in tests/unit/test_quotes_events.py"
Task: "Integration tests in tests/integration/test_quotes.py"

# After T010 — registration and budgets in parallel:
Task: "Registration in src/schwab_mcp/server.py + tests/unit/test_server_tool.py"
Task: "Budget tests in tests/performance/test_quotes_budgets.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 (T001–T002) + Phase 2 (T003)
2. Phase 3: RED T004–T008 → GREEN T009–T012
3. **STOP and VALIDATE**: quickstart S1 + S4 against a real client
4. The agent already gets the roadmap's core outcome: a current price in
   one small call

### Incremental Delivery

1. MVP (US1) → validate → commit
2. Add US2 (batch) → validate S2 → commit
3. Add US3 (extended) → validate S3 → commit
4. Polish (docs, safety, graph currency, final gates) → single
   docs-included commit per constitution Commit Discipline

---

## Notes

- [P] tasks = different files, no dependencies
- Every GREEN task is minimal implementation for its failing RED tests —
  no speculative parameters (research D2: no `fields`/`indicative` tool
  surface)
- Budget growth beyond ≤250 tokens/symbol, ≤2,500 tokens/10-symbol batch,
  or ≤5 s p95 requires recorded justification (constitution Principle V)
- Stop at any checkpoint to validate the story independently
- Avoid: implementing before its RED test exists; skipping the baseline
  gate; docs changes in a later commit than code (Commit Discipline)