# Implementation Plan: Account Transaction History

**Branch**: `006-transaction-history` | **Date**: 2026-10-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-transaction-history/spec.md`

## Summary

Exponer la tool MCP **`get_transaction_history`**: historia completa de
movimientos de todas las cuentas vinculadas entre una fecha de inicio y
una fecha de fin (obligatorias, ambos bordes inclusivos, ventana máxima
1 año — clarify Q1), con filtro opcional por instrumento. Trae **todos**
los tipos de movimiento del proveedor (trades, transferencias, dividendos
e intereses, movimientos de caja, ajustes, etc.), cada uno con categoría
normalizada de enum cerrado (clarify Q3), fecha/hora, descripción,
monto con moneda, cuenta e instrumento cuando aplica. Orden cronológico
ascendente, conteo total, paginación explícita de 50 movimientos por
página con mecanismo de continuación sin duplicados ni gaps (clarify Q4).
Errores accionables por categoría (validación, instrumento inexistente,
fallo por cuenta, transitorio, re-auth), sin reintentos internos,
auditoría por invocación, read-only estricto y presupuestos declarados
(≤ 5 s p95, SC-001; ≤ 16 KB por página default, SC-003).

Technical approach (de research): módulo nuevo
`src/schwab_mcp/transactions.py` (modelos Pydantic + mapeo provider→modelo
+ orquestación por cuenta + paginación) siguiendo el patrón probado de
`positions.py`; upcalls: 1 `linked_accounts` + 1 `transactions` por cuenta
(con la lista completa de tipos separada por comas — research D2), 1
`instruments` solo cuando hay filtro por símbolo (research D6); split por
bisección ante el tope upstream de 3000 transacciones (research D3).
Registro en `server.py` vía `MCPServer.add_tool` con `structured_output`.
**Sin dependencias nuevas.**

## Technical Context

**Language/Version**: Python ≥ 3.11 (pyproject: `requires-python = ">=3.11"`)

**Primary Dependencies**: `schwabdev==4.0.0` (`Client.linked_accounts`,
`Client.transactions`, `Client.instruments` — firma verificada contra el
SDK instalado), `mcp>=1.0.0` (`MCPServer.add_tool`). Pydantic vía
dependencia transitiva del SDK MCP (ya en uso en `positions.py`).
`zoneinfo` (stdlib) para America/New_York. **Sin dependencias nuevas.**

**Storage**: N/A — resultado efímero; el único storage es el token store
SQLite de schwabdev (solo lectura, sin cambios). Sin caché entre
requests (mismo criterio que features 003 y 005).

**Testing**: pytest 9.x + pytest-asyncio (unit; marcador `performance`
ya configurado para presupuestos).

**Target Platform**: proceso local `schwab-mcp serve`, transporte stdio
exclusivo (constitution: no sockets entrantes, no HTTP).

**Project Type**: local MCP server (stdio) — cuarta tool registrada junto
a `get_open_positions`, `get_asset_metrics` y `get_metric_catalog`.

**Performance Goals**: consulta ≤ 5 s p95 (SC-001); upcalls lineales en
cuentas vinculadas (1 por cuenta), agrupación de todos los tipos en 1
llamada por cuenta (nunca 1 por tipo).

**Constraints**: payload default acotado (SC-003: ≤ 16 KB página de 50
movimientos; extended ≤ 64 KB declarado); ventana ≤ 1 año (clarify Q1);
sin secretos en salidas; sin reintentos internos (FR-010); auditoría por
invocación (FR-011); read-only estricto (FR-012).

**Scale/Scope**: todas las cuentas vinculadas; hasta 3000 movimientos
por (cuenta, llamada) — el tope upstream se maneja con split por
bisección (research D3); páginas de 50 movimientos (clarify Q4).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Estado | Evidencia |
|------|--------|-----------|
| I. Test-First | PASS | tasks.md (Phase 2) ordenará tests primero: validación de fechas/ventana, mapeo provider→categoría con fixtures de los 15 tipos, paginación (sin duplicados/gaps), errores por categoría, cuentas parciales, auditoría, performance, token-usage |
| II. DRY | PASS | Reusa `errors.py` (taxonomía AuthError), `log.auth_event` + redaction filter, `tokens.retry_call`, patrón outcome/detail/accounts_failed de `positions.py`; el vocabulario de outcomes tiene una única definición reutilizada |
| III. Reuse Before Creation | PASS | Upcalls existentes del SDK (`linked_accounts`/`transactions`/`instruments`); `MCPServer.add_tool` del SDK; `zoneinfo` de stdlib; patrón de mapeo de `positions.py` — **sin libs nuevas** |
| IV. KISS | PASS | Paginación por offset sin estado de servidor; sin conversión de moneda (fuera de alcance); sin caché entre requests; el bypass del validador del SDK está acotado a una función helper documentada (research D2) — la alternativa (15 upcalls por cuenta) viola el presupuesto de latencia |
| V. Efficiency & Cost | PASS | Presupuestos declarados: ≤ 5 s p95 (SC-001), ≤ 16 KB página default (SC-003), ≤ 64 KB extended; descripción truncada a 80 caracteres en default (texto completo en extended); tests de performance + token-usage exigidos en tasks |
| Layout fijo | PASS | Código → `src/schwab_mcp/`; tests → `tests/`; docs afectadas (`docs/tools.md`, CHANGELOG) en el mismo commit de implementación |
| Credential safety | PASS | Ningún campo del resultado ni evento lleva tokens/secretos; account_hash opaco (nunca número de cuenta); redaction filter sigue activo; contract lo verifica con test |
| Read/write discipline | PASS | Tool estrictamente read-only: consulta de historial, sin órdenes ni movimientos de dinero |

**Re-check post-Phase 1**: PASS — contratos y modelo de datos reusan el
vocabulario de outcomes de 003 y el canal de eventos de 002; la única
divergencia del spec (valor de enum `dividend_or_interest`, research D5)
está documentada y aplicada al spec; ninguna entrada en Complexity
Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/006-transaction-history/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   ├── mcp-tools.md     # get_transaction_history
│   └── events.md        # Eventos de auditoría de la consulta
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/schwab_mcp/
├── transactions.py      # NUEVO: modelos Pydantic, mapeo provider→modelo,
│                        # normalización de categorías, orquestación por cuenta,
│                        # paginación, split por tope de 3000
├── server.py            # MODIFICADO: registra get_transaction_history
├── errors.py            # REUSADO sin cambios (taxonomía AuthError/exit codes)
├── log.py               # REUSADO sin cambios (auth_event + redaction filter)
├── tokens.py            # REUSADO sin cambios (retry_call)
├── positions.py         # REUSADO sin cambios (referencia de patrón: outcome/
│                        # detail/accounts_failed/_hash_account)
└── metrics.py           # REUSADO sin cambios (referencia de patrón de registro)

tests/
├── unit/                # tests TDD: validación, mapeo, categorías, paginación,
│                        # errores, cuentas parciales, sin secretos
└── performance/         # presupuestos de latencia y token-usage
```

**Structure Decision**: estructura existente del repo (src/ + tests/), sin
directorios nuevos; `transactions.py` es el único módulo nuevo y sigue el
patrón consolidado de `positions.py` (modelos + mapeo + orquestación en un
lugar).

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

Sin entradas: no hay violaciones de constitución que justificar.
