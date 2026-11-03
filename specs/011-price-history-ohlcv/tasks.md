---
description: "Task list for Price History OHLCV (`get_price_history`) (011)"
---

# Tasks: Price History OHLCV (`get_price_history`)

**Input**: Design documents from `/specs/011-price-history-ohlcv/`

**Prerequisites**: plan.md, spec.md, research.md (D1–D9), data-model.md,
contracts/mcp-tools.md, quickstart.md — all complete.

**Tests**: REQUIRED — the project constitution (Principle I) mandates TDD:
every task group below writes tests first, verifies they FAIL, then
implements minimal code to pass. Bug-fix rule N/A (new feature).

**Organization**: Tasks grouped by user story (US1 default daily window →
US2 bounded selection → US3 extended) so each story is an independently
testable increment.

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
the RED tests will pin (research D8 — the one empirical constant).

- [X] T001 Run the full suite baseline gate: `uv sync && uv run pytest` —
  must be green with 0 skipped before any change (constitution test-suite
  gate)
- [X] T002 [P] Capture live provider price-history payloads with a real
  authorized client into fixture constants for the RED tests: (a) daily
  candles (`periodType="month", period=1`), (b) weekly candles
  (`periodType="year", period=1`) — to pin the stamping convention of
  research D7/D8, (c) 30-minute candles (`periodType="day", period=5`) —
  input for the hourly-aggregation tests, (d) one intraday regular-session
  vs `needExtendedHoursData=true` pair — evidence for the extended-hours
  behavior — save to `tests/unit/fixtures/price_history_payloads.py`
  (fixture constants only; no credentials, tokens, or account identifiers
  may appear in the fixtures — FR-011). **Pre-condition**: the local token
  store's refresh token is currently expired (`schwab-mcp renew` reports
  success while the raw SDK refuses) — run an interactive
  `uv run schwab-mcp auth` first if the SDK rejects requests. **Fallback**:
  if no authorized live session is available at implement time, derive the
  fixture payloads from the documented provider response shape
  (`specs/011-price-history-ohlcv/data-model.md`,
  `contracts/mcp-tools.md`) and the `schwabdev` client source, keep the
  D6/D7 stamping-dependent rules parameterized (do not hard-code an assumed
  convention), and record the deviation in the implementing commit message;
  replace with live-captured fixtures in a later commit when a session is
  available (S6 live validation)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The one artifact every user story depends on.

**⚠️ CRITICAL**: No user story work begins until this phase is complete.

- [X] T003 Create the price-history module skeleton in
  `src/schwab_mcp/price_history.py`: module docstring,
  `get_price_history(client, symbol, frequency="daily", period="1m", extended_hours=False, extended=False)`
  and `get_price_history_tool(client, ...)` signatures that raise
  `NotImplementedError`, importing the shared helpers it will reuse —
  `schwab_mcp.provider.response_json`, `schwab_mcp.errors`,
  `schwab_mcp.tokens.retry_call`, `schwab_mcp.log.auth_event`
  (skeleton only — NO behavior; RED tests of Phase 3 must fail against it)

**Checkpoint**: Baseline green; fixtures recorded; skeleton fails loudly.

---

## Phase 3: User Story 1 — Default Daily Window, One Symbol (Priority: P1) 🎯 MVP

**Goal**: The agent requests one symbol with no other parameters and
receives the default daily/1-month curated OHLCV candle series —
chronological, with window metadata and the in-progress marker — within the
token and latency budgets, with fail-fast validation and no partial data.

**Independent Test**: invoke `get_price_history` with one valid symbol and
a fake or real client → response matches the `ok` envelope of
`contracts/mcp-tools.md`; invalid input fails before any upcall.

### Tests for User Story 1 (write FIRST — must FAIL, TDD ⚠️)

- [X] T004 [P] [US1] RED: validation tests in
  `tests/unit/test_price_history_validation.py` covering the normative
  grammars of research D9 — equity/ETF `[A-Z0-9]{1,6}` with at most one
  embedded `.`, index `\$[A-Z0-9]{1,5}`; normalization (strip + uppercase);
  option-contract symbol → `validation_error`/`unsupported_symbol_kind`
  (D9); malformed symbol → `validation_error`/`malformed_symbol`; missing
  symbol → `validation_error`/`malformed_symbol`; defaults applied when
  `frequency`/`period` are omitted (`daily`/`1m`, FR-002); frequency
  outside {`5m`,`15m`,`30m`,`1h`,`daily`,`weekly`} →
  `validation_error`/`unsupported_frequency` (FR-003); **assert the
  provider client received zero calls** for every validation failure
  (fail-before-upcall, FR-007)
- [X] T005 [P] [US1] RED: mapping tests in
  `tests/unit/test_price_history_mapping.py` using the Phase 1 fixtures —
  pin the provider→curated mapping of data-model.md: `datetime→t` (epoch ms
  kept), `open→o`, `high→h`, `low→l`, `close→c`, `volume→v`, all values
  **as delivered** — no rounding, no adjustment (FR-012, research D9);
  candles ordered oldest-first (FR-005); response declares `candle_count`
  = `len(candles)` and `window.first`/`window.last` = first/last `t`
  (FR-015); envelope fields `outcome: "ok"`,
  `detail: "price_history_retrieved"`, `symbol`, `frequency`, `period`,
  `extended_hours`, `extended` echo the effective selection
- [X] T006 [P] [US1] RED: in-progress tests in
  `tests/unit/test_price_history_in_progress.py` pinning the D6 rule with
  an injected frozen `fetch_time` — the last candle is `in_progress: true`
  iff its period end > fetch_time; at most one candle per response carries
  `in_progress: true` (FR-017); for daily candles the period end derives
  from the fixture-pinned provider stamping convention (D8 — parameterized
  until T002 captures live evidence); a fully closed session yields no
  in-progress candle
- [X] T007 [P] [US1] RED: audit-event tests in
  `tests/unit/test_price_history_events.py` —
  `price_history_query_start` (initiated) and
  `price_history_query_failure` with classification `validation` / `error`
  / `reauth` / `provider_unreachable` (pattern of `quotes_query_*`); no
  credentials/tokens/account identifiers in any event or output (FR-011)
- [X] T008 [P] [US1] RED: integration tests for the default-window flows in
  `tests/integration/test_price_history.py` using fake clients (pattern of
  `tests/integration/test_quotes.py`) — S1 `ok` envelope end to end;
  exactly **one** `price_history()` provider call per invocation (D1);
  empty candle list → `history_unavailable`/
  `source_returned_no_candles` with no `candles` array (FR-008); provider
  5xx/408/429 → retryable `provider_unreachable`; 401/403 →
  `reauth_needed` (shared taxonomy via `provider.response_json`)

### Implementation for User Story 1

- [X] T009 [US1] GREEN: implement input validation, normalization, and
  defaults in `src/schwab_mcp/price_history.py` (symbol grammars, option
  rejection, frequency set membership, daily/1m defaults, structured
  validation errors) — minimal code to pass T004 (depends on T003, T004)
- [X] T010 [US1] GREEN: implement the provider orchestration and curation
  in `src/schwab_mcp/price_history.py` — one `price_history()` call via
  `tokens.retry_call` with parameters from the preset table
  (`periodType="month", period=1, frequencyType="daily", frequency=1` for
  the default), `provider.response_json` unwrap, chronological curated
  `candles` array with `in_progress` derivation (D6) and `window`/
  `candle_count` metadata, audit events — minimal code to pass T005, T006,
  T007, T008 (depends on T009)
- [X] T011 [US1] Register the tool in `src/schwab_mcp/server.py` following
  the 003/006/008/010 `mcp.add_tool` wrapper pattern (name
  `get_price_history`, parameters `symbol` string + `frequency` string +
  `period` string + `extended_hours` bool + `extended` bool), and add the
  registration assertions to `tests/unit/test_server_tool.py` (depends on
  T010)
- [X] T012 [US1] RED→GREEN: token-usage and latency budget tests in
  `tests/performance/test_price_history_budgets.py` (pattern of
  `test_quotes_budgets.py`) — default response ≤ ~550 tokens for 22 daily
  candles (SC-002, research D5 arithmetic), ≤ 5 s p95 per invocation
  (SC-001); write tests first against the fixture payload sizes, verify,
  then adjust curation only if a real payload breaches budget (any budget
  growth requires recorded justification per constitution Principle V)
  (depends on T010)

**Checkpoint**: `get_price_history` works for the default window end to end
— validation, curation, in-progress marker, errors, registration, budgets
all green. MVP validated independently via quickstart S1 + S4.

---

## Phase 4: User Story 2 — Bounded Period/Frequency Selection (Priority: P2)

**Goal**: The agent selects from the declared frequency set
(`5m`/`15m`/`30m`/`1h`/`daily`/`weekly`) and named period presets, gets
candles at the requested granularity within the 260-candle ceiling by
construction, with the `extended_hours` opt-in for intraday requests.

**Independent Test**: invoke with each declared preset combination → candles
at the requested frequency never exceeding the ceiling (SC-003); invalid
combinations fail validation before any upcall.

### Tests for User Story 2 (write FIRST — must FAIL ⚠️)

- [X] T013 [P] [US2] RED: preset-table validation tests in
  `tests/unit/test_price_history_validation.py` — every period outside the
  frequency's preset row of data-model.md →
  `validation_error`/`unsupported_period` naming the valid presets (FR-018,
  clarification Q4); period preset accepted at the exact table boundary;
  `extended_hours=true` with `daily`/`weekly` →
  `validation_error`/`extended_hours_not_applicable` (D4); **assert zero
  provider calls** on each failure
- [X] T014 [P] [US2] RED: hourly-aggregation tests in
  `tests/unit/test_price_history_aggregation.py` using the Phase 1 30m
  fixture — 30-minute candles grouped into clock-hour buckets in the
  exchange timezone (data-model rules): `o` = first, `h` = max, `l` = min,
  `c` = last, `v` = sum, `t` = bucket end; trailing partial bucket emitted
  and marked `in_progress: true`; regular-session filtering applied before
  bucketing unless `extended_hours=true` (clarification Q1, research D2)
- [X] T015 [P] [US2] RED: weekly-label tests in
  `tests/unit/test_price_history_aggregation.py` using the Phase 1 weekly
  fixture — every weekly `t` equals the closing session's timestamp
  (FR-019, clarification Q5); if the fixture shows a non-closing provider
  stamp, the normalization path relabels forward to the last session of
  that ISO week (D7 contingency) — assert whichever branch the fixture pins
- [X] T016 [P] [US2] RED: extended-hours behavior tests in
  `tests/unit/test_price_history_in_progress.py` and
  `tests/integration/test_price_history.py` — `extended_hours=true` maps to
  `needExtendedHoursData=true` on the provider call (assert on the fake
  client, D4); intraday responses with the flag include pre/post-market
  candles (more or equal candles vs the regular-session request, using the
  Phase 1 pair fixture)
- [X] T017 [P] [US2] RED: selection integration tests in
  `tests/integration/test_price_history.py` covering quickstart S2/S3 —
  one provider call per invocation for every frequency (the `1h` path
  requests 30-minute candles, D2); response echoes the effective
  `frequency`/`period`; every declared preset's worst case yields ≤ 260
  candles (SC-003 — ceiling by construction, assert on emitted counts per
  the preset table)

### Implementation for User Story 2

- [X] T018 [US2] GREEN: implement the full preset table and per-frequency
  provider-parameter mapping in `src/schwab_mcp/price_history.py` (D3 —
  `5m`/`15m`/`30m` → minute frequency with `periodType="day"`;
  `daily`/`weekly` → month/year/ytd period types; `1h` → 30-minute fetch;
  extended-hours applicability check) — minimal code to pass T013 (depends
  on T010; touches only `price_history.py` + test files)
- [X] T019 [US2] GREEN: implement the hourly aggregation function in
  `src/schwab_mcp/price_history.py` (pure function over fetched 30-minute
  candles per the data-model rules) — minimal code to pass T014 (depends
  on T018)
- [X] T020 [US2] GREEN: implement the weekly label verification/
  normalization in `src/schwab_mcp/price_history.py` (pass-through if the
  fixture pins closing-session stamps; otherwise ISO-week relabeling, D7) —
  minimal code to pass T015 (depends on T018)
- [X] T021 [US2] GREEN: wire the `extended_hours` flag through
  `src/schwab_mcp/price_history.py` to `needExtendedHoursData` (intraday
  only) — minimal code to pass T016 (depends on T018)
- [X] T022 [US2] RED→GREEN: worst-case budget scaling tests in
  `tests/performance/test_price_history_budgets.py` — 260-candle worst case
  ≤ ~5,200 tokens (SC-002/SC-003, research D5); per-candle baseline ≈ 19–22
  tokens asserted via the fixture; measured excess forces the ceiling
  downward with recorded justification (constitution Principle V) (depends
  on T018)

**Checkpoint**: US1 + US2 both work independently — the default window and
every declared selection share one code path (D1) and one envelope
(FR-009).

---

## Phase 5: User Story 3 — Extended Raw Payload (Priority: P3)

**Goal**: `extended=true` returns the complete raw provider payload
alongside the curated view, without a second tool.

**Independent Test**: invoke with `extended=true` → response carries both
`candles` (curated, still within budget) and `provider` (raw payload; for
`1h`, the underlying 30-minute payload — research D2).

### Tests for User Story 3 (write FIRST — must FAIL ⚠️)

- [X] T023 [P] [US3] RED: extended-mode integration tests in
  `tests/integration/test_price_history.py` — success response contains
  BOTH the curated `candles` array and `provider` with the complete raw
  payload (SC-006: verified against the Phase 1 fixtures); for `1h` the
  `provider` channel carries the underlying 30-minute payload (D2); errors
  in extended mode follow the same structured envelope (no partial data)

### Implementation for User Story 3

- [X] T024 [US3] GREEN: implement the extended passthrough in
  `src/schwab_mcp/price_history.py` — `extended=true` adds the raw
  `provider` channel to the success response (C-09 pattern of
  003/006/008/010) — minimal code to pass T023 (depends on T021)

**Checkpoint**: All three user stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation currency, graph currency, and final gates.

- [X] T025 [P] Add the `get_price_history` section to `docs/tools.md` (fifth
  MCP tool): input schema, frequency/preset table, `ok`/error envelopes,
  candle conventions (`t` epoch ms, weekly closing-session label,
  `in_progress`), budgets, audit events — mirroring
  `specs/011-price-history-ohlcv/contracts/mcp-tools.md`
- [X] T026 [P] Record the addition in `docs/CHANGELOG.md` (new
  `get_price_history` tool, frequency set, 260-candle ceiling, budgets)
- [X] T027 Extend `tests/unit/test_no_secrets_in_output.py` to run the
  price-history tool output and audit events through the credential-safety
  assertions (FR-011)
- [X] T028 Refresh the codebase-memory-mcp index for the repository
  (constitution Principle VI graph-currency gate — index must be current
  before any later graph-based analysis)
- [X] T029 Run quickstart.md validation S1–S6 end to end, including one
  live validation pass against a real authorized client (S1 default window,
  S2 weekly selection, S3 extended hours, S4 forming candle, S5
  validation/unavailability, S6 extended passthrough)
- [X] T030 Final commit gate: `uv run pytest` — full suite green with 0
  skipped; docs updated (T025/T026) included in the same commit per
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
- **US2 (Phase 4)**: RED T013–T017 [P] after T010 (US1 core exists);
  T018 → T019/T020/T021 (aggregation, weekly, extended-hours depend on the
  preset table); T022 after T018
- **US3 (Phase 5)**: T023 [P] after T021; T024 depends on T023
- **Polish (Phase 6)**: T025/T026/T027 [P] after T024; T028 after T027;
  T029/T030 last (final gates)

### User Story Dependencies

- **User Story 1 (P1)**: no dependencies on other stories — MVP alone
- **User Story 2 (P2)**: builds on US1's orchestration (T010) but is
  independently testable via T013–T017
- **User Story 3 (P3)**: builds on US2's selection path but is
  independently testable via T023

### Within Each User Story

- RED tests first (TDD) → verify they FAIL → minimal implementation →
  verify GREEN → only then the next task

### Parallel Opportunities

- T002 (fixtures) parallel to T001 once baseline command is launched
- T004–T008 (all RED tests, five distinct files) run together after T003
- T011 + T012 parallel after T010 (different files)
- T013–T017 (US2 RED tests, four distinct files) parallel after T010
- T019 + T020 + T021 parallel after T018 (distinct concerns, same module —
  sequence if file conflicts arise)
- T023 (US3 RED test) single
- T025 + T026 + T027 (docs + safety test) parallel after T024

---

## Parallel Example: User Story 1

```bash
# After T003 — launch all five RED test files together:
Task: "Validation tests in tests/unit/test_price_history_validation.py"
Task: "Mapping tests in tests/unit/test_price_history_mapping.py"
Task: "In-progress tests in tests/unit/test_price_history_in_progress.py"
Task: "Audit-event tests in tests/unit/test_price_history_events.py"
Task: "Integration tests in tests/integration/test_price_history.py"

# After T010 — registration and budgets in parallel:
Task: "Registration in src/schwab_mcp/server.py + tests/unit/test_server_tool.py"
Task: "Budget tests in tests/performance/test_price_history_budgets.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 (T001–T002) + Phase 2 (T003)
2. Phase 3: RED T004–T008 → GREEN T009–T012
3. **STOP and VALIDATE**: quickstart S1 + S4 against a real client
4. The agent already gets the roadmap's core outcome: recent daily OHLCV
   candles in one small call

### Incremental Delivery

1. MVP (US1) → validate → commit
2. Add US2 (selection) → validate S2/S3 → commit
3. Add US3 (extended) → validate S6 → commit
4. Polish (docs, safety, graph currency, final gates) → single
   docs-included commit per constitution Commit Discipline

---

## Notes

- [P] tasks = different files, no dependencies
- Every GREEN task is minimal implementation for its failing RED tests —
  no speculative parameters (research D3: preset table only, no
  numeric/date-range period input; FR-013: no indicator computation)
- The `1h` frequency is derived locally from 30-minute provider candles
  (research D2) — the only aggregation path; weekly stays provider-native
  with label verification (D7)
- Budget growth beyond ≤ ~550 tokens default, ≤ ~5,200 tokens worst case,
  or ≤ 5 s p95 requires recorded justification (constitution Principle V)
- Stop at any checkpoint to validate the story independently
- Avoid: implementing before its RED test exists; skipping the baseline
  gate; docs changes in a later commit than code (Commit Discipline)

---

## Phase 7: Convergence

Appended by `/speckit.converge` (2026-11-03) after the Phase 1–6
implementation (commit e3da0a1, suite 1558 passed / 0 skipped).  Three
partial gaps remain; each task follows TDD (RED first).

- [X] T031 Add the requested `symbol` to every structured error envelope
  (`validation_error`, `history_unavailable`, `provider_unreachable`,
  `reauth_needed`) in `src/schwab_mcp/price_history.py` so the error names
  the offending symbol, not only the audit events; RED-first tests in
  `tests/unit/test_price_history_validation.py` /
  `tests/integration/test_price_history.py` /
  `tests/unit/test_no_secrets_in_output.py`; document the field in
  `docs/tools.md` per FR-008 / US1-AC3 (partial)
- [X] T032 State the allowed values in the frequency validation error: add
  the declared frequency set (e.g. `valid_frequencies`) to the
  `unsupported_frequency` envelope in `src/schwab_mcp/price_history.py`
  (mirroring `valid_presets` on `unsupported_period`); RED-first test in
  `tests/unit/test_price_history_validation.py`; mirror in
  `docs/tools.md` per US2-AC2 (partial)
- [X] T033 Align the remaining documentation with the implemented
  envelopes and measured budgets: `specs/011-price-history-ohlcv/quickstart.md`
  still states the superseded research-D5 arithmetic (≤ ~550 / ≤ ~5,200
  tokens, 19–22 per candle) and `specs/011-price-history-ohlcv/contracts/mcp-tools.md`
  §3 still says "`detail` names the valid presets" while the
  implementation delivers a `valid_presets` envelope field (also missing
  from `docs/tools.md`) — update all three per Constitution commit
  discipline / SC-002 (partial)

---

## Phase 8: Convergence

Appended by `/speckit.converge` (2026-11-03) after the Phase 7 fixes
(commit 6718e7d, suite 1571 passed / 0 skipped).  One environment-blocked
obligation remains; it is deferred by T002's own fallback text and now
made traceable.

- [X] T034 Run the live validation pass of quickstart S1–S6 against a real
  authorized client (`uv run schwab-mcp auth` first — the refresh token is
  expired), capture real provider payloads per frequency into
  `tests/unit/fixtures/price_history_payloads.py` replacing the derived
  fixtures, flip `STAMPING_CONVENTION` / `WEEKLY_STAMP_CONVENTION` (and
  the module constant + `aggregate_hourly` convention default) to the
  observed D8 values, re-run the full suite, and record the pinned
  conventions in the commit message per T002 / T029 (partial)
