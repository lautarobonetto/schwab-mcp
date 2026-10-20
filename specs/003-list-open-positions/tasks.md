# Tasks: List Open Positions

**Input**: Design documents from `/specs/003-list-open-positions/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/, quickstart.md

**Tests**: Incluidos y OBLIGATORIOS — la constitución (Principio I) exige TDD: cada test se escribe primero y DEBE fallar (Red) antes de su implementación (Green).

**Organization**: Tasks grouped by user story (US1 → US2 → US3) per spec.md priorities.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- Single project: `src/schwab_mcp/`, `tests/` at repository root (per plan.md Structure Decision).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Baseline verde antes de tocar nada (gate de commit de la constitución).

- [x] T001 Run full baseline suite `uv run pytest` and confirm 100% green with 0 skipped before any change (record result in commit notes later)

**Checkpoint**: Baseline verde — se puede empezar.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Modelo de datos compartido por las tres historias (data-model.md §1–§2). BLOCKS all user stories.

- [x] T002 [P] Write failing model tests in tests/unit/test_positions.py: validation rules verbatim from data-model.md §1–§2 — `outcome ∈ {ok, partial_failure, transient_failure, reauth_required}`; identidad única `(account_hash, symbol)`; `quantity ≠ 0` y con signo (largo +, corto −); `positions: []` válido solo con `outcome: "ok"`; campos de opción presentes ⇔ `instrument_type == "OPTION"` (nunca `null`: se omiten); `retryable: true` solo con `transient_failure`; `accounts_failed` solo con `partial_failure`; `price_timestamp`/`retrieved_at` ISO-8601 parseable — expect FAIL (módulo no existe)
- [x] T003 Implement typed models `PositionEntry` and `PositionsResult` (pydantic, `structured_output`-compatible) with enums and the exact validation rules of T002 in src/schwab_mcp/positions.py — expect GREEN

**Checkpoint**: Foundation ready — user story implementation can begin.

---

## Phase 3: User Story 1 — Single-query snapshot of all open positions (Priority: P1) 🎯 MVP

**Goal**: Una invocación de `get_open_positions` devuelve todas las tenencias efectivas de todas las cuentas vinculadas, identificadas (cuenta + instrumento), consolidadas por lote, con clasificación de fallos básica y auditoría.

**Independent Test**: Con un fake del client que devuelve un payload conocido, la tool devuelve exactamente las posiciones abiertas de ese payload (firmadas, consolidadas, sin qty=0); con payload vacío → `ok/no_positions/[]`; con `ConnectivityError` → `transient_failure/retryable:true` al primer intento (sin reintentos internos); con `ReauthorizationRequiredError` → `reauth_required`. (Spec US1 scenarios 1–3 + FR-005/006/007.)

### Tests for User Story 1 (TDD — escribir primero, verificar que FALLAN)

- [x] T004 [P] [US1] Write failing tests in tests/unit/test_positions.py for provider→model mapping: single account long position; short position (cantidad negativa); consolidación de lotes duplicados del mismo `(account_hash, symbol)` con `average_price` promedio; omisión total de entradas con cantidad 0 (FR-015); `retrieved_at` propagado a `price_timestamp` de cada entrada — expect FAIL
- [x] T005 [P] [US1] Write failing tests in tests/unit/test_server_tool.py: tool `get_open_positions` registrada y callable vía `MCPServer.add_tool` con salida estructurada (research D1); resultado `ok` con payload fake de `account_details_all(fields="positions")` (una sola llamada upstream — asertar call count == 1); `positions: []` con payload sin posiciones; `ConnectivityError` → `transient_failure` sin segundo intento (assert de llamadas == 1, FR-007/D6); `ReauthorizationRequiredError`/`TokenStoreCorruptedError` → `reauth_required` (D7); eventos de auditoría: exactamente un `positions_query_start` + un terminal por invocación vía `log.auth_event` (FR-014) — expect FAIL

### Implementation for User Story 1

- [x] T006 [US1] Implement provider mapping and query orchestration in src/schwab_mcp/positions.py: llamar `client.account_details_all(fields="positions")` una vez (research D2); mapear payload → `PositionEntry` (campos base: `account_hash`, `symbol`, `instrument_type`, `description`, `quantity = longQuantity − shortQuantity`, `average_price`, `market_value`); consolidar por `(account_hash, symbol)`; omitir cantidad 0; clasificar excepciones de `errors.py` → `PositionsResult` (D7); `retrieved_at` = UTC al recibir la respuesta (D4) — expect GREEN (T004, T005 de mapeo/registro)
- [x] T007 [US1] Register tool in src/schwab_mcp/server.py: `mcp.add_tool(...)` con name `get_open_positions`, description según contracts/mcp-tools.md, función sync, `structured_output` vía annotation de `PositionsResult` — expect GREEN (test de registro de T005)
- [x] T008 [US1] Emit audit events in src/schwab_mcp/positions.py: `positions_query_start` (detail `curated`) → exactamente un terminal (`positions_query_success` | `positions_query_failure`) con vocabulario de contracts/events.md, reusando `log.auth_event`; sin símbolos/cantidades en las líneas — expect GREEN (test de eventos de T005)

**Checkpoint**: US1 funcional e independiente — MVP: la tool devuelve el snapshot básico con fallos clasificados y auditoría.

---

## Phase 4: User Story 2 — Complete metadata for each position (Priority: P2)

**Goal**: Cada posición incluye el set curado completo (incluye P/L no realizado, timestamp de precio y campos de opción); campos extendidos del proveedor solo con `extended=true`.

**Independent Test**: Con posiciones de distintos `assetType` (equity + option) en el payload fake, cada entrada trae TODOS los campos curados del data-model §1 (incluidos `underlying_symbol`/`put_call`/`strike_price`/`expiration_date` solo en OPTION); con `extended=true` cada entrada agrega `extended` passthrough; con `extended=false` (default) NUNCA aparece la clave `extended`. (Spec US2 scenarios 1–3, FR-003/003a.)

### Tests for User Story 2 (TDD — escribir primero, verificar que FALLAN)

- [x] T009 [P] [US2] Write failing tests in tests/unit/test_positions.py for curated metadata: `unrealized_pl` derivado correcto (largo y corto — research D3) y consistente con `currentDayProfitLoss` cuando el proveedor lo trae; campos de opción completos para `assetType: OPTION` (subyacente, put/call, strike, expiración) y ausentes para EQUITY; `price_timestamp` = timestamp de recuperación (FR-012/D4); extended: payload con campos extra (`cusip`, `settledLongQuantity`, `currentDayProfitLoss`, `maintenanceRequirement`) → `extended=true` los incluye como passthrough y `extended=false` (default) los omite por completo — expect FAIL
- [x] T010 [P] [US2] Write failing test in tests/unit/test_server_tool.py: argumento `extended` aceptado por la tool (default `false`), payload default ≤ presupuesto (fixture de 50 posiciones, assert serialización ≤ 8 KB — research D9) — expect FAIL

### Implementation for User Story 2

- [x] T011 [US2] Implement curated metadata mapping in src/schwab_mcp/positions.py: `unrealized_pl` derivado con signo (D3), campos de opción condicionales, `price_timestamp` por entrada — expect GREEN (T009)
- [x] T012 [US2] Implement `extended` parameter in src/schwab_mcp/positions.py and src/schwab_mcp/server.py (input schema `{extended: bool = false}`): passthrough sin interpretación de los campos restantes del proveedor dentro de `extended` (D3/D9), default compacto garantizado — expect GREEN (T010)

**Checkpoint**: US1 + US2 funcionan independientemente; el payload default sigue compacto.

---

## Phase 5: User Story 3 — Predictable failure behavior consistent with the agent playbook (Priority: P3)

**Goal**: Fallos multi-cuenta (`partial_failure` con `accounts_failed`) y verificación transversal de que todo outcome — éxito, vacío, parcial, transient, reauth — es machine-readable, sin secretos y con eventos de auditoría correctos.

**Independent Test**: Con un fake que hace fallar una cuenta y responder otras, el resultado es `partial_failure` con `accounts_failed[{account_hash, detail}]` y `positions` solo de las cuentas exitosas (FR-010); todas las formas de outcome pasan el test de no-secretos; eventos de fallo usan el vocabulario de contracts/events.md. (Spec US3 scenarios 1–3, FR-008/010.)

### Tests for User Story 3 (TDD — escribir primero, verificar que FALLAN)

- [x] T013 [P] [US3] Write failing tests in tests/unit/test_positions.py and tests/unit/test_server_tool.py: multi-cuenta con una cuenta fallando → `outcome: "partial_failure"`, `detail: "account_failed"`, `accounts_failed` con hash + `detail ∈ {provider_error, transient}`, posiciones solo de cuentas exitosas; extend tests/unit/test_no_secrets_in_output.py para cubrir TODAS las formas de resultado de la tool (ok, vacío, partial, transient, reauth): cero secretos y ningún número de cuenta crudo (FR-008) — expect FAIL

### Implementation for User Story 3

- [x] T014 [US3] Implement per-account error isolation in src/schwab_mcp/positions.py: separar respuesta por cuenta del payload de `account_details_all`, capturar fallo por cuenta sin perder las demás (FR-010/D7); emitir el terminal de auditoría correcto según el outcome del resultado (contracts/events.md): `positions_query_success` con `outcome: ok | partial_failure` y `detail: account_failed` cuando hay éxito o fallo parcial, `positions_query_failure` con `outcome: transient | reauth` y details fijos (`provider_unreachable`, `reauth_needed`, `store_absent`, `store_corrupted`) solo para fallos totales — expect GREEN (T013)

**Checkpoint**: Las tres historias funcionan independientemente; playbook del agente completo.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Presupuestos medibles, documentación al día y gate de commit.

- [x] T015 [P] Write performance + token-usage tests in tests/performance/test_positions_budgets.py (marker `performance`): latencia de invocación ≤ 5 s con fake de red normal (SC-002); payload default ≤ 12 KB con 50 posiciones curadas y extended ≤ 20 KB (SC-003/D9 presupuestos ajustados); correr y validar presupuestos — expect GREEN con la implementación actual
- [x] T016 [P] Update documentation: register `get_open_positions` in docs/tools.md (tabla de superficies, contrato completo, playbook extendido) and add entry to docs/CHANGELOG.md — required in the SAME commit as the implementation (constitution: documentation currency)
- [x] T017 Run quickstart.md validation end-to-end (tests + escenarios manuales del quickstart con red real si hay credenciales; si no, documentar los que quedan pendientes de verificación manual)
- [ ] T018 Final commit gate: `uv run pytest` full suite 100% green, 0 skipped, sin secretos en outputs, docs al día (T016) — recién entonces commit (constitution: green-before-commit)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias — inmediato
- **Foundational (Phase 2)**: depende de Phase 1 — BLOCKS todas las historias
- **US1 (Phase 3)**: depende de Phase 2
- **US2 (Phase 4)**: depende de US1 (la tool debe existir y mapear lo básico)
- **US3 (Phase 5)**: depende de US2 (aislamiento por cuenta opera sobre el mapeo completo)
- **Polish (Phase 6)**: depende de todas las historias

### User Story Dependencies

- **US1**: sin dependencias de otras historias (solo Foundational)
- **US2**: integra sobre US1 (mismo módulo `positions.py`; completa el mapeo)
- **US3**: integra sobre US1/US2 (multi-cuenta + verificación transversal)

### Within Each User Story

- Tests PRIMERO, verificando que fallan antes de implementar (TDD, constitution gate I)
- Mapping antes de registro de tool antes de eventos
- Story completa antes de la siguiente prioridad

### Parallel Opportunities

- T002 y T004…: dentro de cada fase, los tests marcados [P] son archivos/funciones distintas → paralelizables
- T015 y T016 (Polish) son paralelizables entre sí
- Las historias son secuenciales por dependencia de módulo compartido (`positions.py`); NO paralelizar US1/US2/US3 entre sí (mismo archivo — evitar conflictos)

---

## Parallel Example: User Story 1

```bash
# Los dos archivos de test de US1 son independientes → lanzar juntos:
Task: "Write failing tests in tests/unit/test_positions.py (T004)"
Task: "Write failing tests in tests/unit/test_server_tool.py (T005)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: baseline verde
2. Phase 2: modelos (Red → Green)
3. Phase 3: US1 completa → **STOP and VALIDATE**: la tool devuelve el snapshot con fallos clasificados
4. Ya usable por el agente para el caso core

### Incremental Delivery

1. US1 → snapshot básico + fallos + auditoría (MVP)
2. US2 → metadatos completos + extended bajo demanda
3. US3 → partial_failure + verificación transversal de secretos/eventos
4. Polish → presupuestos medidos, docs, commit gate

---

## Notes

- [P] tasks = archivos distintos, sin dependencias
- [Story] label mapea a spec.md para trazabilidad
- Verificar Red antes de cada Green (constitution gate I — no negociable)
- Commit después de cada checkpoint, con suite verde, 0 skipped, y docs incluidas (constitution: commit discipline)
- Evitar: tareas vagas, conflictos de mismo archivo entre tareas paralelas, dependencias cross-story que rompan independencia
