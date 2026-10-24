# Implementation Plan: Underlying-Aware Symbol Filter and Underlying Reference

**Branch**: `007-underlying-symbol-filter` | **Date**: 2026-10-24 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/007-underlying-symbol-filter/spec.md`

## Summary

Extender la tool MCP **`get_transaction_history`** (feature 006) para que
el filtro `symbol` sea **consciente del subyacente**: `symbol="NOK"`
devuelve los movimientos registrados bajo `NOK` **y** los movimientos de
opciones cuyo root del símbolo OCC es `NOK`, y — cuando el filtro es un
símbolo de opción completo registrado — los movimientos de esa opción
puntual. Además, cada movimiento de opción expone el **subyacente** como
campo de primera clase (`underlying_symbol`) en el output curado, derivado
del símbolo registrado (la fuente no lo expone por separado).

Technical approach (de research): con el filtro presente, la tool consulta
el rango **sin filtro upstream** (mismas upcalls que la consulta sin
filtro: 1 `linked_accounts` + 1 `transactions` por cuenta, con bisección
ante el tope de 3000) y aplica el matching de tres formas localmente —
el endpoint del proveedor no puede filtrar opciones por subyacente
(verificado en vivo: `symbol=NOK` → 0 resultados; símbolo OCC → HTTP 400).
Validación dual del filtro (clarificación C): lookup en el directorio de
instrumentos primero; si no resuelve, se consulta igual y
`instrument_not_found` solo si nada matchea. `underlying_symbol` se deriva
del root del OCC (porción previa a los últimos 15 caracteres fecha/C-P/
strike — mismo anclaje derecho verificado en vivo para posiciones).
Comparación insensible a mayúsculas. **Sin dependencias nuevas.**

## Technical Context

**Language/Version**: Python ≥ 3.11 (pyproject: `requires-python = ">=3.11"`)

**Primary Dependencies**: `schwabdev==4.0.0` (`Client.linked_accounts`,
`Client.transactions`, `Client.instruments`), `mcp>=1.0.0`
(`mcp.add_tool`), Pydantic (vía dependencia del SDK MCP). `zoneinfo`
(stdlib). **Sin dependencias nuevas.**

**Storage**: N/A — resultado efímero; sin caché entre requests (criterio
de 003/006).

**Testing**: pytest 9.x + pytest-asyncio (unit); marcador `performance`
para presupuestos.

**Target Platform**: proceso local `schwab-mcp serve`, transporte stdio
exclusivo (constitution: no sockets entrantes, no HTTP).

**Project Type**: local MCP server (stdio) — extensión de la segunda tool
registrada; no se registran tools nuevas.

**Performance Goals**: mismos presupuestos que 006 (≤ 5 s p95, SC-001 de
006): las upcalls no cambian (el filtro ya no viaja upstream, pero las
upcalls por cuenta son las mismas 1 + N); 1 `instruments` adicional solo
cuando hay filtro (como hoy).

**Constraints**: payload default acotado (≤ 16 KB por página de 50 —
debe mantenerse **incluyendo** el campo nuevo, FR-007); sin reintentos
internos; auditoría por invocación; read-only estricto; sin secretos.

**Scale/Scope**: todas las cuentas vinculadas; tope upstream de 3000 por
(cuenta, llamada) manejado con la bisección existente; páginas de 50.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Estado | Evidencia |
|------|--------|-----------|
| I. Test-First | PASS | tasks.md (Phase 2) ordenará tests primero: matching de las 3 formas, case-insensitivity, subset-consistency, validación dual, `underlying_symbol` por forma de payload, presupuestos |
| II. DRY | PASS | Reusa `response_json` (provider.py), la orquestación/bisección/paginación de `transactions.py`, el anclaje derecho de símbolos OCC ya verificado en `positions.py`; el matcher de filter es una única función pura con una sola definición |
| III. Reuse Before Creation | PASS | Sin libs nuevas; upcalls existentes del SDK; el parser OCC se apoya en el conocimiento ya codificado y probado en vivo |
| IV. KISS | PASS | Un solo barrido + filtro local (frente a doble consulta híbrida, descartada en research R1); sin estado de servidor; sin caché |
| V. Efficiency & Cost | PASS | Presupuestos declarados sin cambios (≤ 5 s p95, ≤ 16 KB página default) — el campo nuevo entra dentro del presupuesto actual (research R5 lo mide); tests de performance + token-usage existentes se extienden |
| Layout fijo | PASS | Código → `src/schwab_mcp/`; tests → `tests/`; docs afectadas (`docs/tools.md`, CHANGELOG) en el mismo commit |
| Credential safety | PASS | `underlying_symbol` es un identificador de instrumento público, no de cuenta; `account_hash` opaco se mantiene; sin tokens/secretos |
| Read/write discipline | PASS | Solo lectura; sin órdenes ni movimientos de dinero |

**Re-check post-Phase 1**: PASS — contratos y data model reusan el
vocabulario de outcomes de 006 y el canal de eventos sin cambios; ninguna
entrada en Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/007-underlying-symbol-filter/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   └── mcp-tools.md     # Cambios de contrato de get_transaction_history
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/schwab_mcp/
├── transactions.py      # MODIFICADO: matcher de filter (3 formas, case-
│                        # insensitive), derivación de root/underlying,
│                        # validación dual, field en MovementEntry; ya NO
│                        # envía symbol upstream
├── provider.py          # REUSADO sin cambios (response_json)
├── positions.py         # REUSADO sin cambios (referencia de patrón OCC)
├── log.py               # REUSADO sin cambios (events de 006)
└── server.py            # REUSADO sin cambios (la tool ya registrada)

tests/
├── unit/                # tests TDD: matching, subset-consistency, validación
│                        # dual, underlying_symbol, case-insensitivity
└── performance/         # presupuestos extendidos (16 KB con campo nuevo)
```

**Structure Decision**: sin módulos nuevos; la extensión vive en
`transactions.py` (matcher puro + derivación de root + wiring en la
orquestación existente). `server.py` no cambia (mismos parámetros de
input).

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

Sin entradas: no hay violaciones de constitución que justificar.
