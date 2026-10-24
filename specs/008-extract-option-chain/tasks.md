---
description: "Task list for feature 008-extract-option-chain"
---

# Tasks: Extracción de Cadena de Opciones con Filtros (`get_option_chain`)

**Input**: Design documents from `/specs/008-extract-option-chain/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/mcp-tools.md, quickstart.md

**Tests**: OBLIGATORIOS — la constitución del proyecto (Principio I) exige TDD
(Red → Green → Refactor): cada tarea de implementación va precedida por su
tarea de test, y los tests DEBEN fallar antes de escribir la implementación.

**Organization**: Tasks grouped by user story (US1 → US3, prioridad P1 → P3).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- Single project: `src/schwab_mcp/`, `tests/{unit,integration,performance}/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verificar base del proyecto antes de tocar código.

- [X] T001 Run `uv sync` and `uv run pytest` to confirm the full suite is green (0 skipped) before any change; record baseline in commit message of the first feature commit

**Checkpoint**: Baseline verde — se puede empezar con TDD.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Query validada, fetch del proveedor y política de parciales —
usados por TODAS las user stories. Sin esto no arranca ninguna story.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 [P] Write FAILING unit tests for input validation (FR-008) in tests/unit/test_options_chain_validation.py: `symbol` no vacío; `max_strikes ≥ 1` (default 50); `option_type` ∈ {both, calls, puts} (default both); `delta_target` con `0 < |delta| < 1` o null (default null); `dte_max ≥ 1` o null (default null → tope vigente 60); mensaje de error accionable por cada caso; quote the constraints verbatim from data-model.md §1
- [X] T003 Implement `OptionChainQuery` dataclass + `validate()` in src/schwab_mcp/options_chain.py to make T002 pass (reuse `errors.py` taxonomy; no upcall before validation)
- [X] T004 [P] Write FAILING unit tests for provider request mapping in tests/unit/test_options_chain_filters.py: `option_type` → `contractType` (both→ALL, calls→CALL, puts→PUT); `strikeCount` = `max_strikes` (50 default); `fromDate` = hoy, `toDate` = hoy + tope de DTE efectivo (60 default o `dte_max` pedido); `includeUnderlyingQuote=true`; DTE en días de calendario (research R1/R3)
- [X] T005 Implement `fetch_option_chain(client, query)` in src/schwab_mcp/options_chain.py using `client.option_chains(...)` with params from T004, wrapped in `tokens.retry_call` + `provider.response_json`; FR-013: if a whole expiration map is missing/empty or the response fails → structured error WITHOUT partial chain (research R5)

**Checkpoint**: Foundation ready — user story implementation can now begin.

---

## Phase 3: User Story 1 — Analizar posición compleja con una sola consulta (Priority: P1) 🎯 MVP

**Goal**: Con solo `symbol`, devolver la cadena completa con defaults
(≤60 DTE, ambos tipos, 50 strikes/lado, todas las griegas y valores
técnicos) en una invocación.

**Independent Test**: invocar con solo `symbol` sobre un instrumento con
opciones y verificar vencimientos ≤60 DTE, ambas piernas, ventana de
strikes alrededor del ATM y `contract_fields` completo por pierna
(quickstart S1).

### Tests for User Story 1 (TDD — escribir primero, deben FALLAR) ⚠️

- [X] T006 [P] [US1] Write FAILING unit tests for payload mapping in tests/unit/test_options_chain_mapping.py: union of `callExpDateMap`/`putExpDateMap` keyed by expiration date; `dte` = calendar days; `atm_strike` = strike closest to `underlying_price`; `contract_fields` fixed order from data-model.md §1 (bid…deliverable_note); rounding prices 2 / greeks+iv 4 decimals; missing field → explicit `null` in its column (FR-007); `data_state` realtime|delayed
- [X] T007 [P] [US1] Write FAILING unit tests for default filters in tests/unit/test_options_chain_filters.py: per-expiration symmetric window of up to 50 strikes each side around `atm_strike` (fewer → all); `option_type="both"` keeps both legs; expirations with `dte > 60` excluded
- [X] T008 [P] [US1] Write FAILING performance tests in tests/performance/test_options_chain_budgets.py (marker `performance`): token budget **≤ 110.000 tokens with default filters and < 6.000 tokens with `delta_target`** (budgets adjusted by user decision 2026-10-24 during implementation: honest measurement of the mandated 23-column both-leg rows is ~95–106k / ~4,5–5k for the representative fixture; growth justification registered in plan.md Complexity Tracking and docs/tools.md) for a representative liquid-underlying fixture (~12 expirations × 100 strike rows, serialization measured as chars/4) (SC-002); FR-012 bound: response never exceeds expirations × types × strikes; latency budget hook per plan (≤5 s p95)
- [X] T009 [P] [US1] Write FAILING integration test in tests/integration/test_options_chain.py: end-to-end with provider double — `ok` chain; `no_options_listed` structured result; `no_expirations_in_range` structured result; whole-expiration-missing → error without partial chain (FR-013); `extended=true` adds raw provider payload (contract §2); SC-004/FR-011 assertion: each quickstart scenario completes with exactly 1 invocation and the `ok` response carries the full chain with no cursor/offset field

### Implementation for User Story 1

- [X] T010 [US1] Implement payload mapping/curado (ChainMeta, Expiration, StrikeRow, `contract_fields` constant) in src/schwab_mcp/options_chain.py to make T006 pass (depends T002, T005)
- [X] T011 [US1] Implement default filters: strike window per expiration, option_type leg selection, DTE filter + `filters` echo with `dte_max_effective` in src/schwab_mcp/options_chain.py to make T007 pass (depends T010)
- [X] T012 [US1] Implement compact columnar serialization (strike rows with both legs as positional arrays, deterministic rounding) in src/schwab_mcp/options_chain.py to make T008 pass (depends T010)
- [X] T013 [US1] Implement `get_option_chain` orchestration (ok / no_options_listed / no_expirations_in_range / error states per FR-009, FR-013) in src/schwab_mcp/options_chain.py and register the tool with closure wrapper named `get_option_chain` in src/schwab_mcp/server.py following the existing `get_open_positions`/`get_transaction_history` pattern, exposing schema: symbol, max_strikes, option_type, delta_target, dte_max, extended (depends T003, T005, T010–T012, T009)

**Checkpoint**: US1 usable end-to-end (MVP): una consulta → análisis completo.

---

## Phase 4: User Story 2 — Focalizar por tipo y delta objetivo (Priority: P2)

**Goal**: Con `option_type` y `delta_target`, devolver la ventana de hasta
5 strikes por tipo alrededor del delta objetivo en cada vencimiento.

**Independent Test**: invocar con `option_type="puts"`, `delta_target=0.20`
y verificar solo PUTs y ≤5 strikes alrededor de |delta|≈0.20 por
vencimiento; con "both", ventanas separadas de CALLs y PUTs (quickstart S2).

### Tests for User Story 2 (TDD — escribir primero, deben FALLAR) ⚠️

- [X] T014 [P] [US2] Write FAILING unit tests for the delta window in tests/unit/test_options_chain_delta.py: per expiration AND per included type, contract with delta closest to target (absolute value) + 2 contiguous strikes each side → up to 5 (or all available around); per-type independent windows when option_type="both" (clarification 2026-10-23); no invented strikes; delta window NOT reduced by max_strikes
- [X] T015 [P] [US2] Write FAILING integration test extension in tests/integration/test_options_chain.py: delta scenario end-to-end (puts-only 0.20; both-types per-type windows; SC-004 assertion: exactly 1 invocation per scenario, no cursor/offset in the response); internal `strikeCount` expansion rule (max(limit, 100), single re-fetch up to 200 when target not bracketed) observable via provider double request assertions

### Implementation for User Story 2

- [X] T016 [US2] Implement delta window selection + internal strikeCount expansion in src/schwab_mcp/options_chain.py to make T014/T015 pass (depends T014, T015, T005)
- [X] T017 [US2] Wire `delta_target` validation errors (FR-008) and `filters` echo for delta into the orchestration in src/schwab_mcp/options_chain.py (depends T016, T013)

**Checkpoint**: US1 + US2 independientes y funcionales.

---

## Phase 5: User Story 3 — Ajustar el volumen con límites explícitos (Priority: P3)

**Goal**: `max_strikes` y `dte_max` explícitos gobiernan el volumen de la
respuesta de forma determinista (SC-006).

**Independent Test**: invocar con `max_strikes=10`, `dte_max=7` y
`dte_max=120` y verificar que los límites se respetan al 100% y que el
rango vacío produce el resultado estructurado (quickstart S3).

### Tests for User Story 3 (TDD — escribir primero, deben FALLAR) ⚠️

- [X] T018 [P] [US3] Write FAILING tests for explicit limits: extend tests/unit/test_options_chain_filters.py with `max_strikes=10` (≤10 per side, ATM zone always included), `dte_max=120` (includes farther expirations, `dte_max_effective`=120), `dte_max=7` with nearest expiration beyond → `no_expirations_in_range` with effective cap in detail; add to tests/integration/test_options_chain.py the SC-006 assertion (zero out-of-bounds contracts) and the SC-004 assertion (exactly 1 invocation per scenario, no cursor/offset)

### Implementation for User Story 3

- [X] T019 [US3] Implement `dte_max` passthrough beyond the 60-day default (`toDate` = today + requested value) and empty-range result wiring in src/schwab_mcp/options_chain.py to make T018 pass (depends T018, T011)

**Checkpoint**: Las tres stories funcionan de forma independiente.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentación, validación end-to-end y gates de la constitución.

- [X] T020 [P] Document the tool in docs/tools.md: invocation, input schema, output schema with `contract_fields`, expected payload size (incl. the documented budget risk from plan.md Complexity Tracking), error table, examples — include in the feature commit (constitution commit discipline)
- [X] T021 Run quickstart.md scenarios S1–S4 as final validation; run `uv run pytest` full suite (green, 0 skipped); refresh the codebase-memory-mcp index for the repository (constitution VI graph currency gate) before closing the feature

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: immediate.
- **Foundational (Phase 2)**: blocks ALL user stories (T002→T003, T004→T005; T002/T004 en paralelo).
- **US1 (Phase 3)**: depends on Phase 2. Tests T006–T009 en paralelo → implementación T010→T011→T012→T013.
- **US2 (Phase 4)**: depends on Phase 3 (T013 registró la tool; la ventana de delta se monta sobre el mapeo y el fetch).
- **US3 (Phase 5)**: depends on Phase 3 (usa los filtros base); independiente de US2.
- **Polish (Phase 6)**: depends on all stories complete.

### User Story Dependencies

- **US1**: no depende de otras stories.
- **US2**: reutiliza fetch (T005) y mapeo (T010); independiente de US3.
- **US3**: reutiliza filtros base (T011); independiente de US2 (solo comparten el archivo de test de filtros → secuencia T007 → T018).

### Parallel Opportunities

- Foundational: T002 ∥ T004.
- US1: T006 ∥ T007 ∥ T008 ∥ T009 (todos archivos distintos).
- US2: T014 ∥ T015.
- Polish: T020 puede hacerse en paralelo con la validación final de T021.

---

## Parallel Example: User Story 1

```bash
# Tests de US1 en paralelo (archivos distintos, todos RED primero):
Task: "tests/unit/test_options_chain_mapping.py"      (T006)
Task: "tests/unit/test_options_chain_filters.py"      (T007)
Task: "tests/performance/test_options_chain_budgets.py" (T008)
Task: "tests/integration/test_options_chain.py"       (T009)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 → Phase 2 (Foundation).
2. Phase 3 completo → **STOP and VALIDATE** con quickstart S1.
3. La tool ya es útil por sí sola (caso de uso central).

### Incremental Delivery

- +US2 → validar con S2 (delta). +US3 → validar con S3 (límites).
- Cada story agrega valor sin romper las anteriores.

### Constitution Gates per task group

- TDD estricto: el test de cada tarea debe fallar antes de su implementación.
- Presupuestos: T008 (tokens/latencia) es gate de US1.
- Commits: suite verde, 0 skipped, docs actualizadas en el mismo commit.
- Al cerrar: refresco del índice codebase-memory-mcp (T021).

---

## Notes

- [P] tasks = different files, no dependencies
- `[Story]` label maps task to user story for traceability
- Verify tests fail before implementing; commit after each task or logical group
- Avoid: vague tasks, same-file conflicts, cross-story dependencies that break independence
