# Implementation Plan: List Open Positions

**Branch**: `003-list-open-positions` | **Date**: 2026-10-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-list-open-positions/spec.md`

## Summary

Exponer la **primera tool MCP** del servidor: `get_open_positions`, que en
una sola invocación devuelve todas las tenencias efectivas (cantidad con
signo no cero) de todas las cuentas vinculadas, cada una con el conjunto
curado de metadatos (identificación del instrumento, cantidad con signo,
costo promedio, valor de mercado con timestamp del precio, P/L no
realizado, clasificación del instrumento) y los campos extendidos solo
bajo demanda explícita (`extended=true`). Sin reintentos internos; los
fallos se auto-clasifican (`transient_failure`, `reauth_required`,
`partial_failure`) con el mismo vocabulario del playbook existente, y
cada consulta emite eventos de auditoría sin secretos.

Technical approach (de research): una única llamada a
`schwabdev.Client.account_details_all(fields="positions")` alimenta la
tool; un módulo nuevo `src/schwab_mcp/positions.py` mapea el payload del
proveedor al modelo de datos y `server.py` registra la tool vía
`MCPServer.add_tool` (SDK `mcp` ≥ 1.0.0, API verificada en el repo).

## Technical Context

**Language/Version**: Python ≥ 3.11 (pyproject: `requires-python = ">=3.11"`)

**Primary Dependencies**: `schwabdev==4.0.0` (API Schwab), `mcp>=1.0.0`
(servidor MCP stdio; `MCPServer.add_tool` con `structured_output`). Sin
dependencias nuevas.

**Storage**: N/A — resultado efímero; el único storage es el token store
SQLite de schwabdev (solo lectura de credenciales, sin cambios).

**Testing**: pytest 9.x + pytest-asyncio (unit; marcador `performance`
ya configurado para presupuestos).

**Target Platform**: proceso local `schwab-mcp serve`, transporte stdio
exclusivo (constitution: no sockets entrantes, no HTTP).

**Project Type**: local MCP server (stdio) + CLI one-shot existente.

**Performance Goals**: query completa ≤ 5 s (SC-002); un solo upstream
call a la API de Schwab por consulta.

**Constraints**: payload default acotado por presupuesto de tokens
(SC-003: declarado abajo, ≤ 8 KB para 50 posiciones curadas; crecimiento
justificable solo para `extended=true`); sin secretos en ninguna salida;
sin reintentos internos (FR-007); auditoría en cada invocación (FR-014).

**Scale/Scope**: cartera representativa ≤ 50 posiciones abiertas; cuentas
vinculadas ya enumerables vía `linked_accounts()` (feature 001).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Estado | Evidencia |
|------|--------|-----------|
| I. Test-First | PASS | tasks.md (Phase 2) ordenará tests antes que implementación: test de mapeo, test de registro de tool, test de fallos, test de auditoría, performance, token-usage |
| II. DRY | PASS | Reusa `errors.py` (taxonomía AuthError/exit codes), `log.auth_event` + filtro de redacción, `config.load_config`; el mapeo provider→modelo vive en un único módulo (`positions.py`) |
| III. Reuse Before Creation | PASS | `account_details_all()` de schwabdev reemplaza N llamadas por-cuenta; `MCPServer.add_tool` del SDK en vez de protocolo a mano; sin libs nuevas |
| IV. KISS | PASS | Sin filtros por cuenta (spec FR-004: todas), sin caché (FR-006 prohíbe stale), sin lógica de estrategias (grouping es del agente); un solo upstream call |
| V. Efficiency & Cost | PASS | Presupuestos declarados: ≤ 5 s (SC-002), ≤ 8 KB default para 50 posiciones (~2k tokens) y presupuesto separado declarado para `extended` (contracts); tests de performance + token-usage exigidos en tasks |
| Layout fijo | PASS | Código → `src/schwab_mcp/`; tests → `tests/`; docs afectadas (`docs/tools.md`, CHANGELOG) se actualizan en el mismo commit de implementación |
| Credential safety | PASS | Ningún campo del resultado lleva tokens/secretos; redaction filter sigue activo; contract lo verifica con test |
| Read/write discipline | PASS | Tool estrictamente read-only: no órdenes, no movimientos de dinero |

**Re-check post-Phase 1**: PASS — los contratos y el modelo de datos no
introducen duplicación (reusan enums/vocabulario de 002), ni
complejidad sin justificar (ver research D1–D8; ninguna entrada en
Complexity Tracking).

## Project Structure

### Documentation (this feature)

```text
specs/003-list-open-positions/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── mcp-tools.md     # Contrato de la tool get_open_positions
│   └── events.md        # Eventos de auditoría de posiciones
└── tasks.md             # Phase 2 output (/speckit.tasks - NOT created here)
```

### Source Code (repository root)

```text
src/schwab_mcp/
├── positions.py         # NUEVO: mapeo provider→modelo + armado del resultado
├── server.py            # MODIFICADO: registra la tool via MCPServer.add_tool
├── errors.py            # REUSADO: taxonomía y exit codes (sin cambios)
├── log.py               # REUSADO: auth_event + redaction filter (sin cambios)
└── config.py            # REUSADO: load_config (sin cambios)

tests/
├── unit/
│   ├── test_positions.py            # NUEVO: mapeo, consolidación, signo, omisión de qty=0
│   ├── test_server_tool.py          # NUEVO: registro de tool, resultado estructurado, fallos clasificados
│   └── test_no_secrets_in_output.py # EXTENDIDO: cubrir salida de la tool
└── performance/
    └── test_positions_budgets.py    # NUEVO: presupuesto 5 s + presupuesto de tokens
```

**Structure Decision**: proyecto único existente; un módulo nuevo
(`positions.py`) + registro en `server.py`. No hay subdirectorios nuevos
en `src/` porque la base de código es flat por feature (consistente con
001/002).

## Complexity Tracking

> Sin violaciones de constitución que justificar — tabla vacía.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
