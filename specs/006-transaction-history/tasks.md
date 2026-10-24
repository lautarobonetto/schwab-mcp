---

description: "Task list for feature 006-transaction-history implementation"
---

# Tasks: Account Transaction History (`get_transaction_history`)

**Input**: Design documents from `/specs/006-transaction-history/`

**Prerequisites**: [plan.md](./plan.md) · [spec.md](./spec.md) · [research.md](./research.md) · [data-model.md](./data-model.md) · [contracts/](./contracts/) · [quickstart.md](./quickstart.md)

**Tests**: OBLIGATORIOS — la constitución (Principio I: Test-First) exige
tests escritos primero y fallando (Red) antes de cada implementación
(Green). Cada fase de user story incluye sus tests TDD.

**Organization**: Tasks agrupadas por user story (spec.md: US1 P1, US2
P2, US3 P3) para implementación y testing independientes.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Puede correr en paralelo (archivos distintos, sin dependencias pendientes)
- **[Story]**: User story propietaria (US1, US2, US3)
- Paths exactos en cada descripción

## Path Conventions

- Single project: `src/schwab_mcp/` + `tests/{unit,performance}/`
- Módulo nuevo: `src/schwab_mcp/transactions.py` (único archivo de código nuevo; registro en `server.py`)
- Los tests de un mismo archivo NO se marcan [P] entre sí

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Baseline del repo en la branch — no hay dependencias nuevas (plan: "Sin dependencias nuevas")

- [X] T001 Verificar baseline en `006-transaction-history`: correr `uv sync` y `uv run pytest` — suite completa verde, 0 skipped, sin cambios de código (gate de commit de la constitución)

**Checkpoint**: baseline verde; se puede empezar TDD.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Modelos, enums y validación de `HistoryQuery` — prerrequisito de TODAS las user stories

**⚠️ CRITICAL**: Ninguna user story empieza antes de completar esta fase.

- [X] T002 Escribir tests fallando (Red) de enums y modelos en `tests/unit/test_transactions_models.py`: sets cerrados de `TransactionOutcome`/`TransactionDetail`/`MovementCategory`/`ProviderTransactionType` según data-model.md; tabla de mapeo tipo-upstream→categoría (R5: `TRADE→trade`; 7 tipos de dinero/entrega→`transfer`; `DIVIDEND_OR_INTEREST→dividend_or_interest`; `JOURNAL`/`SMA_ADJUSTMENT→adjustment`; `MEMORANDUM`/`MARGIN_CALL`/`MONEY_MARKET→other`; tipo desconocido→`other`); reglas de validación cruzada 1–8 de data-model.md (`outcome=ok`+`movements=[]` ⇔ detail vacío; `has_more=true` ⇒ `next_offset` presente y `returned==50`; `accounts_failed` ⇔ `partial_failure`; `retryable=true` ⇔ `transient_failure`; `no_movements_for_instrument` ⇒ `symbol` presente)
- [X] T003 Implementar enums y modelos Pydantic en `src/schwab_mcp/transactions.py` (solo modelos: `MovementEntry`, `TransactionsResult`, enums; campos y constraints verbatim de data-model.md: `account_hash` str min_length=1 opaco, `occurred_at` ISO-8601, `description` truncada a 80 chars en default, `amount` float, `currency` default `"USD"`, `symbol`/`instrument_type`/`extended` ausentes cuando no aplican) — hace pasar T002 (Green)
- [X] T004 [P] Escribir tests fallando (Red) de validación de `HistoryQuery` en `tests/unit/test_transactions_validation.py` (FR-004): fechas ausentes/mal formadas (formato `YYYY-MM-DD`), `end_date < start_date` (error nombra ambas), rango > 366 días (error indica máximo 1 año), `end_date` futura, `symbol` vacío, `offset < 0`; y que la validación corre ANTES de cualquier upcall
- [X] T005 Implementar validación de `HistoryQuery` en `src/schwab_mcp/transactions.py` (parseo de fechas `YYYY-MM-DD`, ventana ≤ 1 año, bordes inclusivos en America/New_York vía `zoneinfo` — research R4) — hace pasar T004 (Green)

**Checkpoint**: modelos + validación listos; US1/US2/US3 pueden empezar (US2 y US3 en paralelo si hay capacidad).

---

## Phase 3: User Story 1 - Retrieve every movement over a date range (Priority: P1) 🎯 MVP

**Goal**: Con fechas inicio/fin, obtener TODOS los movimientos de todas las cuentas vinculadas (trades, transferencias, dividendos/intereses, ajustes, etc.) con categoría normalizada, montos y cuenta.

**Independent Test**: Con fixtures de payload del proveedor que contengan un trade, un interés, una transferencia y un ajuste, una consulta del rango devuelve los 4 con su categoría/cuenta/monto; con un rango sin movimientos devuelve `ok/no_movements`; fallo transitorio se reporta al primer intento.

### Tests for User Story 1 (TDD — escribir primero, verificar que FALLAN)

- [X] T006 [P] [US1] Escribir tests fallando de mapeo provider→modelo en `tests/unit/test_transactions_mapping.py`: fixtures de los 15 tipos upstream (R5) verificando categoría, `occurred_at`, `amount`, `currency` (regla: usar el campo de moneda del proveedor si lo expone; si no, default `"USD"` — F2 del analyze), `account_hash`, `symbol`/`instrument_type` solo cuando hay instrumento, `description` truncada a 80 caracteres, `extended` solo con `extended=true` (passthrough: `type` original, descripción completa, `fees`, `commissions`, `netAmount`, `settlementDate`, `transferItems`, `activityId` — research R5/data-model.md)
- [X] T007 [P] [US1] Escribir tests fallando de orquestación y outcomes en `tests/unit/test_transactions_query.py` (client falso): itera `linked_accounts()`; 1 llamada `transactions()` por cuenta con `types` = lista completa separada por comas de los 15 tipos (research D2/R2); helper de bypass del validador del SDK acotado (toggle de `client._validator.enabled` con restauración en `finally` — research D2); outcomes `ok/history_retrieved`, `ok/no_movements`, `transient_failure/provider_unreachable` con `retryable=true` reportado al primer intento SIN reintentos internos (FR-010), `reauth_required/reauth_needed`, `partial_failure` con `accounts_failed` por cuenta (`provider_error`/`transient`) sin descartar silencio cuentas (FR-008); fusiona cuentas y deduplica por `(account_hash, activityId)`; `retrieved_at` ISO-8601 UTC; determinismo: la misma consulta ejecutada dos veces produce el mismo conjunto (spec US1 esc. 2); la orquestación SOLO invoca métodos de lectura del client — sin `place_order` ni escrituras (FR-012)
- [X] T008 [P] [US1] Escribir tests fallando de split por tope en `tests/unit/test_transactions_split.py`: respuesta de exactamente 3000 movimientos → bisección del rango (sub-rango mínimo 1 día, research D3), fusión sin duplicados ni omisiones (SC-004); 2999 y 3001-no-alcanzan-tope no disparan split
- [X] T009 [P] [US1] Escribir tests fallando de eventos de auditoría en `tests/unit/test_transactions_events.py` según `contracts/events.md`: exactamente 1 evento terminal por invocación (`transactions_query_success` ok/partial · `transactions_query_failure` transient/reauth/validation), detail del enum cerrado del contrato, sin secretos, sin texto libre del proveedor sin redactar

### Implementation for User Story 1

- [X] T010 [US1] Implementar `map_provider_transactions(payload, extended)` en `src/schwab_mcp/transactions.py` (mapeo R5 + truncado de descripción + passthrough extended) — hace pasar T006 (Green)
- [X] T011 [US1] Implementar orquestación `get_transaction_history(client, start_date, end_date, extended=False, offset=0)` en `src/schwab_mcp/transactions.py`: linked_accounts → 1 `transactions()` por cuenta con lista completa de tipos + helper `_bypass_validator()` con `finally` (research D2); clasificación de outcomes y `accounts_failed` siguiendo el patrón de `positions.py`; `retry_call` con 0 reintentos para la llamada de transacciones (FR-010) — hace pasar T007 (Green)
- [X] T012 [US1] Implementar split por bisección al tope de 3000 con dedup por `(account_hash, activityId)` en `src/schwab_mcp/transactions.py` — hace pasar T008 (Green)
- [X] T013 [US1] Emitir eventos de auditoría (start/terminal) vía `log.auth_event` en `src/schwab_mcp/transactions.py` según contracts/events.md — hace pasar T009 (Green)
- [X] T014 [US1] Registrar la tool `get_transaction_history` en `src/schwab_mcp/server.py`: wrapper closure con client (patrón de `get_open_positions`), input schema con `start_date`, `end_date`, `extended` (`symbol` llega en US2, `offset` llega en US3 — no registrar parámetros sin comportamiento), `MCPServer.add_tool` con `structured_output`
- [X] T015 [US1] Extender cobertura de no-secretos para la nueva tool en `tests/unit/test_no_secrets_in_output.py` (resultado y eventos: sin tokens, app keys, secretos, números de cuenta — solo `account_hash` opaco)

**Checkpoint**: US1 completa y testeable en forma independiente: historia completa por rango vía MCP funciona (MVP).

---

## Phase 4: User Story 2 - Focus the history on one instrument (Priority: P2)

**Goal**: Con `symbol` opcional, devolver solo los movimientos de ese instrumento en el rango; distinguir "instrumento inexistente" de "sin movimientos".

**Independent Test**: Con fixtures del rango que mezclen movimientos de varios instrumentos y sin instrumento, la consulta filtrada por `AAPL` devuelve exactamente el subconjunto AAPL (consistencia con la sin filtro); un símbolo inexistente produce error `instrument_not_found` (no vacío ambiguo).

### Tests for User Story 2 (TDD — escribir primero, verificar que FALLAN)

- [X] T016 [P] [US2] Escribir tests fallando de validación de símbolo en `tests/unit/test_transactions_symbol.py` (client falso): `symbol` presente → 1 upcall `instruments(symbols=[symbol], projection="SYMBOL_SEARCH")` (research D6); símbolo inexistente/typo → error `instrument_not_found` nombrando el símbolo (FR-009c); sin `symbol` → **cero** upcalls de instruments; sin fuzzy matching (Assumptions del spec)
- [X] T017 [P] [US2] Escribir tests fallando de semántica del filtro en `tests/unit/test_transactions_symbol.py`: resultado filtrado = subconjunto exacto del resultado sin filtro (consistencia, spec US2 esc. 3); símbolo válido sin movimientos → `ok/no_movements_for_instrument` (y la regla cruzada 6 de data-model.md: ese detail implica `symbol` presente); filtro aplicado upstream (`symbol=` en la llamada transactions)

### Implementation for User Story 2

- [X] T018 [US2] Implementar validación de `symbol` (upcall `instruments` + error `instrument_not_found`) y filtro upstream en `src/schwab_mcp/transactions.py` — hace pasar T016 y T017 (Green)
- [X] T019 [US2] Agregar `symbol` al input schema de la tool en `src/schwab_mcp/server.py` (wrapper y schema de T014) y verificar el flujo end-to-end con tests existentes de registro de tool

**Checkpoint**: US1 y US2 funcionan de forma independiente.

---

## Phase 5: User Story 3 - Bounded, agent-friendly pagination (Priority: P3)

**Goal**: Respuesta paginada determinista: orden cronológico ascendente, páginas de 50, `total_count`, `has_more`/`next_offset`, recorrido completo sin duplicados ni gaps.

**Independent Test**: Con un historial de 137 movimientos de fixture, la primera página trae 50 movimientos ordenados + `total_count=137` + `next_offset=50`; el walk completo (offset 0→50→100→137) no duplica ni omite ninguno (SC-006).

### Tests for User Story 3 (TDD — escribir primero, verificar que FALLAN)

- [X] T020 [P] [US3] Escribir tests fallando de paginación en `tests/unit/test_transactions_pagination.py`: orden `occurred_at` ascendente con desempate `(account_hash, activityId)`; página de máximo 50 (clarify Q4); `total_count` = total del rango completo; `has_more=true` ⇔ `next_offset` presente y `returned==50`; `next_offset` ⇒ `has_more=true`; walk de 137 movimientos en 3 páginas con cero duplicados/cero omisiones (SC-006); página final sin `next_offset`; rango que entra en una página sin indicador de continuación; `offset_echo` refleja el offset aplicado; última página parcial (< 50, `has_more=false`)

### Implementation for User Story 3

- [X] T021 [US3] Implementar ordenamiento y recorte de páginas en `src/schwab_mcp/transactions.py` (slicing sobre el historial fusionado y ordenado; campos `total_count`/`returned`/`has_more`/`next_offset`/`offset_echo` del data-model.md) y registrar `offset` en el input schema de la tool en `src/schwab_mcp/server.py` (F1 del analyze: el parámetro entra junto a su comportamiento) — hace pasar T020 (Green)

**Checkpoint**: Las tres user stories funcionan de forma independiente.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Gates de constitución transversales (performance, token-usage, docs) y verificación end-to-end

- [X] T022 Escribir tests de presupuestos en `tests/performance/test_transactions_budgets.py` (marker `performance`): latencia p95 ≤ 5 s en set ≥ 20 consultas variadas con client falso rápido (SC-001; mide overhead propio — la latencia contra el proveedor real se valida live en S5 del quickstart, F7 del analyze) y tamaño de payload: página default de 50 movimientos ≤ 16 KB (SC-003) y página extended ≤ 64 KB (contrato); correr hasta verde
- [X] T023 [P] Actualizar `docs/tools.md`: nueva sección `get_transaction_history` (cuarta tool MCP: invocación, argumentos, output schema, outcomes/detail, errores, paginación, garantías, upcalls, caveat operacional de `200 + []` por permisos — research R8) y actualizar el conteo de tools registradas en la tabla inicial
- [X] T024 [P] Actualizar `docs/CHANGELOG.md` con la entrada de la feature (versión de docs 0.4.0)
- [X] T025 Validación final: `uv run pytest` suite completa verde y 0 skipped; recorrer los escenarios S1–S6 de `quickstart.md` (los live requieren credenciales válidas del dueño); verificar docs actualizadas sin comportamientos obsoletos (gate de documentación currency de la constitución)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias — inmediato
- **Foundational (Phase 2)**: T002→T003 (Red→Green), T004→T005 (Red→Green); BLOQUEA todas las user stories
- **US1 (Phase 3)**: depende de Phase 2; dentro de la fase: tests T006–T009 (Red, paralelizables) → implementación T010–T015 en orden (T010 depende de T006; T011 de T007+T003+T005; T012 de T008+T011; T013 de T009; T014 de T011; T015 de T014)
- **US2 (Phase 4)**: depende de US1 (extiende la orquestación de T011 y el registro T014)
- **US3 (Phase 5)**: depende de US1 (pagina el resultado fusionado de T011); puede hacerse en paralelo con US2 si hay capacidad (archivos distintos… mismo módulo: coordinar commits)
- **Polish (Phase 6)**: depende de todas las user stories completas

### User Story Dependencies

- **US1 (P1)**: MVP — arranca tras Foundational, sin dependencias entre stories
- **US2 (P2)**: refine US1 (filtro); independiente en valor una vez US1 existe
- **US3 (P3)**: refine US1 (paginación); independiente en valor una vez US1 existe

### Parallel Opportunities

- T002/T004 (Red de Foundational) son de archivos distintos: paralelos
- Todos los tests Red de US1 (T006–T009) son archivos distintos: paralelizables
- US2 (T016–T017) y US3 (T020) pueden escribirse en paralelo (archivos de test distintos)
- T023/T024 (docs) paralelizables entre sí tras la implementación

---

## Parallel Example: User Story 1

```bash
# Tests Red de US1 en paralelo (4 archivos distintos):
Task: "Escribir tests fallando de mapeo en tests/unit/test_transactions_mapping.py"
Task: "Escribir tests fallando de orquestación en tests/unit/test_transactions_query.py"
Task: "Escribir tests fallando de split en tests/unit/test_transactions_split.py"
Task: "Escribir tests fallando de eventos en tests/unit/test_transactions_events.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: Setup (baseline verde)
2. Phase 2: Foundational (modelos + validación) — CRITICAL
3. Phase 3: User Story 1 (historia completa por rango)
4. **STOP and VALIDATE**: S1 de quickstart + suite verde → la tool ya entrega el valor core pedido ("todo, no solo trades")
5. US2 y US3 agregan foco y economía de tokens encima

### Incremental Delivery

- +US2: filtro por instrumento con desambiguación honesta (`instrument_not_found` vs vacío)
- +US3: paginación determinista para rangos grandes
- Cada story es un commit (o grupo lógico) con suite verde y docs al día

### Notes

- Sin dependencias nuevas en todo el feature (plan: Research R1–R10)
- El bypass del validador del SDK vive SOLO en el helper de `transactions.py` con `finally` (research D2)
- Ningún texto del proveedor sin redactar en eventos (contracts/events.md)
- Stop en cada checkpoint para validar la story de forma independiente

---

## Phase 7: Convergence

- [X] T026 CRITICAL: reescribir la entrada 0.4.0 de `docs/CHANGELOG.md` para que describa la implementación real confirmada en el commit — modelos `MovementEntry`/`TransactionsResult` (no `TransactionEntry`/`TransactionHistoryResult`/`TransactionType`), campo `movements` (no `transactions`), enum cerrado de categorías `trade`/`transfer`/`dividend_or_interest`/`adjustment`/`other` (+ reservados, sin `withholding`/`other_transaction`), paginación explícita por `offset` con `has_more`/`next_offset` (no "paginación automática del cliente"), ausencia del campo `bisection_applied` (la bisección es interna ante el tope de 3000, research D3), campos de entrada reales (`occurred_at`, `amount`, `currency`, `symbol`, `instrument_type`, `extended`) y eventos `transactions_query_start`/`transactions_query_success`/`transactions_query_failure` de `log.py`; de paso, actualizar la línea "Versión del documento" de `docs/tools.md` a 0.4.0 per Constitution (Commit Discipline — Documentation currency) y T024 (contradicts)
- [X] T027 Consolidar el disparador del tope de 3000 en una única fuente de verdad: hacer que `_bisect_range()` en `src/schwab_mcp/transactions.py` use `_should_split()` (o eliminar el helper muerto y pinarlo en un solo lugar), manteniendo `tests/unit/test_transactions_split.py` verde per Constitution II — DRY y plan: research D3 (partial)

---

## Phase 8: Live Validation Fixes

**Purpose**: defectos hallados en la validación manual en vivo contra la
API real (2026-10-23) que la suite con fakes basados en dicts no detectaba.

- [X] T028 CRITICAL: unwrapping de respuestas del SDK — nuevo módulo
  `src/schwab_mcp/provider.py` con `response_json()` (única fuente de
  verdad): `.json()` del body y clasificación de estados HTTP (401/403 →
  reauth, 5xx/408/429 → transitorio, resto 4xx → `provider_error` por
  cuenta, JSON malformado → transitorio); aplicado a `linked_accounts()`,
  `transactions()` y `instruments()` en `transactions.py`; el hash de
  cuenta se extrae de `hashValue` (forma real del payload de
  `linked_accounts()`); tests de regresión en
  `tests/unit/test_transactions_live_response.py` — la herramienta fallaba
  en vivo con `AttributeError: 'Response' object has no attribute 'get'`
  per SC-002 (contradicts)
- [X] T029 Enviar al proveedor datetimes ISO-8601 acotados en
  America/New_York (medianoche a 23:59:59 locales, offset DST real) en vez
  de `YYYY-MM-DD` crudo — la API rechaza el formato crudo con HTTP 400
  (`'2026-09-01' is not a valid value for startDate`); helper
  `_provider_datetime()` con test de contrato actualizado per FR-004 y
  Assumptions del spec (missing)
- [X] T030 Adaptar el mapper a la forma real del payload: timestamp en
  `time` (no `transactionDate`), lista JSON en el nivel superior (no
  envelope `{"transactions": [...]}`), instrumento dentro de
  `transferItems[].instrument` con `assetType`; tests en Rojo→Verde en
  `test_transactions_live_response.py::TestRealProviderShape` per FR-005
  (partial)
- [X] T031 Convertir errores de validación e `instrument_not_found` en
  `ToolError` en el límite de la tool (`get_transaction_history_tool`,
  registro en `server.py`) para que el mensaje accionable llegue al agente
  en vez del texto genérico del SDK MCP per FR-009d y SC-005 (partial)
- [X] T032 Corregir la proyección del upcall de instrumentos a
  `symbol-search` (el validador del SDK rechaza `SYMBOL_SEARCH`);
  actualizar research.md D6, `contracts/mcp-tools.md`, `docs/tools.md`
  (caveat de identificadores internos como `CURRENCY_USD`) y el CHANGELOG
  per Constitution — Documentation currency (contradicts)
- [X] T033 Normalizar `SCHWAB_CALLBACK_URL` en `load_config()` quitando
  barras finales: el portal de desarrollo de Schwab puede **exigir** la
  barra final en el callback registrado (sin ella la app pasa a estado de
  error y no admite envío a aprobación), mientras `schwabdev` rechaza
  callbacks que terminan en `/`; la normalización en `config.py` (única
  fuente de verdad) hace que ambas formas funcionen sin tocar el registro
  de la app; test de regresión en `test_config.py` + docs actualizadas
  (`docs/instalacion.md`, `docs/uso.md`, CHANGELOG) per Constitution II y
  Documentation currency (contradicts)
