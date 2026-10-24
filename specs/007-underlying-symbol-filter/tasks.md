---

description: "Task list for feature 007-underlying-symbol-filter implementation"
---

# Tasks: Underlying-aware symbol filter (`get_transaction_history` 007)

**Input**: Design documents from `/specs/007-underlying-symbol-filter/`

**Prerequisites**: [plan.md](./plan.md) · [spec.md](./spec.md) · [research.md](./research.md) · [data-model.md](./data-model.md) · [contracts/](./contracts/) · [quickstart.md](./quickstart.md)

**Tests**: OBLIGATORIOS — la constitución (Principio I: Test-First) exige
tests escritos primero y fallando (Red) antes de cada implementación
(Green). Cada fase de user story incluye sus tests TDD.

**Organization**: Tasks agrupadas por user story (spec.md: US1 P1 —
filtro por subyacente; US2 P2 — `underlying_symbol` por movimiento) para
implementación y testing independientes.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Puede correr en paralelo (archivos distintos, sin dependencias pendientes)
- **[Story]**: User story propietaria (US1, US2)
- Paths exactos en cada descripción

## Path Conventions

- Single project: `src/schwab_mcp/` + `tests/{unit,performance}/`
- Módulo modificado: `src/schwab_mcp/transactions.py` (matcher, derivación
  de root, orquestación y mapper); sin archivos nuevos de código
- Los tests de un mismo archivo NO se marcan [P] entre sí

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Baseline del repo — sin dependencias nuevas (plan: "Sin dependencias nuevas")

- [X] T001 Verificar baseline en `007-underlying-symbol-filter`: correr `uv sync` y `uv run pytest` — suite completa verde, 0 skipped, sin cambios de código (gate de commit de la constitución)

**Checkpoint**: baseline verde; se puede empezar TDD.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Funciones puras de matching y derivación de root — prerrequisito de AMBAS user stories

**⚠️ CRITICAL**: Ninguna user story empieza antes de completar esta fase.

- [X] T002 Escribir tests fallando (Red) de derivación de root y matching en `tests/unit/test_transactions_underlying.py`: `_option_root()` según data-model §1-R1 (root = `symbol[:-15].strip()` cuando los últimos 15 chars matchean patrón OCC — `YYMMDD` dígitos + `C`/`P` + 8 dígitos; anclaje derecho independiente del padding: `"AMD   261120P00630000"` → `"AMD"`, root sin padding; símbolo sin codificación OCC identificable → `None`); matcher de las 3 formas del data-model §2 (M1 símbolo registrado exacto · M2 root de opción · M3 OCC completo), insensible a mayúsculas (`"nok"` matchea `"NOK"` y el OCC de NOK), **sin fuzzy** (substring/parcial NO matchea: `"NO"` no matchea `"NOK"`), `CURRENCY_USD` matchea por M1
- [X] T003 Implementar `_option_root(symbol) -> str | None` y el matcher puro (`movement_involves_filter(symbol, instrument_type, filter) -> bool` o equivalente) en `src/schwab_mcp/transactions.py` (funciones puras, sin I/O; reusan el conocimiento de anclaje derecho de `_parse_occ_option_symbol` en positions.py sin duplicar su lógica de strike) — hace pasar T002 (Green)

**Checkpoint**: matcher + derivación listos; US1 y US2 pueden empezar.

---

## Phase 3: User Story 1 - Filter by underlying instrument (Priority: P1) 🎯 MVP

**Goal**: Con `symbol="NOK"`, obtener TODOS los movimientos que involucran a NOK en cualquier forma registrada (símbolo registrado, root de opción, OCC completo), con subset-consistency garantizada y validación dual.

**Independent Test**: Con fixtures que mezclen un trade de acción NOK, trades de opciones NOK y movimientos de otros instrumentos, la consulta filtrada devuelve exactamente los primeros dos grupos; la consulta en minúsculas devuelve lo mismo; el resultado filtrado es subconjunto exacto del sin filtro.

### Tests for User Story 1 (TDD — escribir primero, verificar que FALLAN)

- [X] T004 [P] [US1] Escribir tests fallando de la consulta filtrada en `tests/unit/test_transactions_filter_query.py` (client falso tipo `LiveLikeClient` de `test_transactions_live_response.py`): la orquestación **ya NO envía** `symbol` upstream (las llamadas `transactions()` no llevan el kwarg `symbol`); `symbol="NOK"` devuelve trades de acción NOK + opciones con root NOK y nada más; `symbol="NOK   261218P00011000"` (OCC completo) devuelve solo esa opción; `"nok"` ≡ `"NOK"`; el OCC completo en minúsculas (`"nok   261218p00011000"`) ≡ el OCC exacto; subset-consistency (data-model §4): filtrar localmente el resultado sin filtro con el matcher produce el mismo conjunto que la consulta filtrada; paginación sobre el conjunto filtrado (`total_count` del subconjunto; walk con `offset` sin duplicados ni omisiones); validación dual (FR-003): directorio NO resuelve + movimientos que matchean → `ok` con resultados; directorio NO resuelve + cero matches → `InstrumentNotFoundError` nombrando el filtro (vía `get_transaction_history_tool` → `ToolError`); `detail=no_movements_for_instrument` solo cuando nada matchea; `CURRENCY_USD` devuelve sus movimientos (data-model §2-paso 4); `partial_failure` con filtro activo — las cuentas exitosas aportan movimientos que matchean el filtro y las fallidas van a `accounts_failed` (FR-008), nunca se descarta una cuenta entera por el filtro
- [X] T005 [US1] Implementar la semántica del filtro en `src/schwab_mcp/transactions.py`: quitar el kwarg `symbol` de la llamada `client.transactions(...)` (research R1); validación dual — envolver el lookup de `validate_symbol` para que `InstrumentNotFoundError` NO aborte: se procede con el barrido y solo se levanta el error si el conjunto fusionado y deduplicado no tiene ningún match del matcher (FR-001/FR-003); tras fusionar/dedup/ordenar, filtrar con el matcher cuando `symbol` está presente ANTES de paginar; `total_count`/`returned`/`has_more`/`next_offset` calculados sobre el subconjunto; `detail` según §3 del data-model — hace pasar T004 (Green). **Nota de commit**: T005 deja rojos los tests legacy de `test_transactions_symbol.py` hasta que T006 los actualice al nuevo contrato — commitear T005+T006 como un solo commit (gate *green-before-commit* de la constitución)
- [X] T006 [US1] Actualizar los tests legacy de símbolo en `tests/unit/test_transactions_symbol.py` al nuevo contrato: los tests que pinnan el envío de `symbol=` upstream se invierten (verificar que NO se envía); los tests de `instrument_not_found` inmediato se adaptan a la validación dual (error solo con cero matches); mantener los tests de cero upcalls de `instruments` sin `symbol` — archivo completo verde

**Checkpoint**: US1 completa y testeable en forma independiente: el filtro por subyacente entrega toda la actividad del instrumento (MVP).

---

## Phase 4: User Story 2 - Underlying reference on option movements (Priority: P2)

**Goal**: Cada movimiento de opción expone `underlying_symbol` (root del OCC, sin padding) en el output curado; no-opciones sin cambios.

**Independent Test**: Con fixtures de movimiento de opción (OCC real con padding) y no-opción, el mapper agrega `underlying_symbol="NOK"` solo a las opciones; el caso OCC no identificable omite el campo.

### Tests for User Story 2 (TDD — escribir primero, verificar que FALLAN)

- [X] T007 [P] [US2] Escribir tests fallando del campo en `tests/unit/test_transactions_underlying.py` (sección `TestUnderlyingSymbol`): `map_provider_transactions` con un trade de opción real (OCC con padding, `instrument_type="OPTION"`, forma real del proveedor) → `underlying_symbol` presente con el root sin padding; movimientos no-opción (TRADE de equity, DIVIDEND_OR_INTEREST, transfer) → campo **ausente** (no `null`, excluido por `exclude_none`); opción con símbolo sin codificación OCC identificable → campo ausente; extended passthrough sin cambios (el campo no se duplica en `extended`); sin secretos: `underlying_symbol` solo transporta identificadores públicos de instrumento
- [X] T008 [US2] Implementar la derivación en `map_provider_transactions` en `src/schwab_mcp/transactions.py`: cuando `instrument_type == "OPTION"` y `_option_root(symbol)` no es `None`, agregar `kwargs["underlying_symbol"] = root` (patrón de campos opcionales existente: solo setear cuando aplica) — hace pasar T007 (Green)

**Checkpoint**: US1 y US2 funcionan de forma independiente.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Gates de constitución transversales (performance, docs) y verificación end-to-end

- [X] T009 Extender los presupuestos en `tests/performance/test_transactions_budgets.py`: caso peor de página default = 50 movimientos **todos de opción** con `underlying_symbol` ≤ 16 KB (SC-003/FR-007) y página extended ≤ 64 KB; latencia p95 ≤ 5 s sin cambios (las upcalls no aumentan)
- [X] T010 [P] Actualizar `docs/tools.md`: semántica del filtro (tabla del contrato §1: subyacente incluye opciones; OCC completo soportado; minúsculas; validación dual), fila `underlying_symbol` en el schema de `MovementEntry`, reemplazo del caveat "filtrar opciones por subyacente no funciona" por la nueva conducta; actualizar `docs/CHANGELOG.md` con la entrada del feature (versión de docs 0.5.0)
- [X] T011 Validación final: `uv run pytest` suite completa verde y 0 skipped; recorrer los escenarios S1–S6 de `quickstart.md` (los live requieren credenciales válidas del dueño); verificar docs actualizadas sin comportamientos obsoletos (gate de documentación currency de la constitución)

---

## Phase 6: Convergence

- [X] T012 Eliminar la función muerta `validate_symbol()` de `src/schwab_mcp/transactions.py` (quedó sin referencias en `src/` y `tests/` tras la validación dual de T005) y mantener `_symbol_resolved_in_directory()` como única fuente de verdad de la lógica "respuesta vacía = símbolo desconocido" — verificación: suite verde tras la eliminación per plan: research R3 / Constitution II (unrequested)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias — inmediato
- **Foundational (Phase 2)**: T002→T003 (Red→Green); BLOQUEA ambas user stories
- **US1 (Phase 3)**: depende de Phase 2; dentro de la fase: T004 (Red) → T005 (Green) → T006 (legacy tests al nuevo contrato)
- **US2 (Phase 4)**: depende de Phase 2; puede hacerse en paralelo con US1 si hay capacidad (tests en archivos distintos; T005 y T008 tocan el mismo módulo — coordinar commits)
- **Polish (Phase 5)**: depende de ambas user stories completas

### User Story Dependencies

- **US1 (P1)**: MVP — arranca tras Foundational, sin dependencias entre stories
- **US2 (P2)**: campo aditivo; independiente en valor una vez US1 existe (y también aporta a consultas sin filtro)

### Parallel Opportunities

- T004 (US1 tests) y T007 (US2 tests) son de archivos distintos: paralelizables
- T010 (docs) paralelizable tras la implementación
- T005 y T008 NO son paralelos entre sí (mismo archivo `transactions.py`)
- **T002 (Phase 2) y T007 (Phase 4) editan el mismo archivo** `tests/unit/test_transactions_underlying.py` en fases distintas — ejecutar en orden (T002 → T003 → … → T007); si corre más de un agente, coordinar para evitar conflicto

---

## Parallel Example: User Story Tests

```bash
# Tests Red de las dos stories en paralelo (archivos distintos):
Task: "Tests de consulta filtrada en tests/unit/test_transactions_filter_query.py"
Task: "Tests del campo underlying en tests/unit/test_transactions_underlying.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: Setup (baseline verde)
2. Phase 2: Foundational (matcher + root) — CRITICAL
3. Phase 3: User Story 1 (filtro por subyacente)
4. **STOP and VALIDATE**: S1 de quickstart + suite verde → el agente ya puede pedir "todo lo de NOK" en una sola consulta
5. US2 agrega el campo `underlying_symbol` encima

### Incremental Delivery

- +US2: el output curado se vuelve auto-descriptivo (agrupación por subyacente sin parsear OCC)
- Cada story es un commit (o grupo lógico) con suite verde y docs al día

### Notes

- Sin dependencias nuevas en todo el feature (plan: research R1–R7)
- El filtro ya no viaja upstream: subset-consistency por construcción (research R1)
- El caso `CURRENCY_USD` cambia de error a resultados — documentado en el contrato §3 y en `docs/tools.md` (T010)
- Ningún texto del proveedor sin redactar en eventos (contracts/events.md de 006, sin cambios)
- Stop en cada checkpoint para validar la story de forma independiente
