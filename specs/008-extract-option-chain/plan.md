# Implementation Plan: Extracción de Cadena de Opciones con Filtros

**Branch**: `008-extract-option-chain` | **Date**: 2026-10-23 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/008-extract-option-chain/spec.md`

## Summary

Nueva tool MCP `get_option_chain` de solo lectura que extrae la cadena de
opciones de un instrumento con filtros opcionales acotadores: límite de
strikes por lado (default 50), tipo de opción (ambos/calls/puts), delta
objetivo (ventana de 5 strikes por tipo alrededor del contrato con delta
más cercana, sobre todos los vencimientos dentro del tope de DTE) y DTE
máximo (default 60 días). Devuelve todas las griegas y todos los valores
técnicos relevantes que expone la fuente, en un formato compacto por
strike (ambas piernas por fila) para respetar el presupuesto de tokens.
La fuente de datos es el endpoint de cadenas del SDK ya integrado
(`schwabdev.Client.option_chains` → `/marketdata/v1/chains`), reutilizando
el unwrapping compartido (`provider.response_json`), la taxonomía de
errores existente y el patrón de registro de tools de `server.py`.

## Technical Context

**Language/Version**: Python ≥ 3.11 (pyproject `requires-python = ">=3.11"`)

**Primary Dependencies**: schwabdev 4.0.0 (Schwab Trader API), mcp ≥ 1.0.0 (MCPServer stdio)

**Storage**: N/A — tool de solo lectura sin estado propio; reutiliza el token store existente (`tokens.py`)

**Testing**: pytest ≥ 9.1.1 (unit / integration / performance, marker `performance`)

**Target Platform**: servidor MCP local por stdio (`schwab-mcp serve`); sin superficie HTTP

**Project Type**: library/cli (MCP stdio server local)

**Performance Goals**: latencia p95 ≤ 5 s por invocación (alineado con 006 y SC-001); presupuesto de tokens con filtros por defecto ≤ 75.000 tokens para un subyacente típico y < 3.000 tokens con `delta_target` activo (SC-002, decisión de la sesión de clarificación 2026-10-24, con justificación registrada abajo — Principio V)

**Constraints**: transporte stdio exclusivo; credenciales nunca en logs/outputs; respuesta en una sola invocación sin paginación (FR-011); sin datos parciales ante fallo de vencimiento entero (FR-013)

**Scale/Scope**: 1 módulo nuevo (`src/schwab_mcp/options_chain.py`), 1 tool nueva registrada en `server.py`, suites de tests unit/integration/performance

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Estado | Notas |
|---|---|---|
| I. TDD | ✅ Pasa | El feature se implementará Red → Green → Refactor; tests de filtros, delta-window y validación primero |
| II. DRY | ✅ Pasa | Reutiliza `provider.response_json`, `tokens.retry_call`, taxonomía de `errors.py`; sin duplicar unwrapping ni error mapping |
| III. Reuse Before Creation | ✅ Pasa | Un módulo nuevo solo porque el dominio (cadena de opciones) es nuevo; el SDK ya expone `option_chains()` |
| IV. KISS | ✅ Pasa | Una llamada aguas arriba + post-filtro local para delta; sin abstracciones especulativas |
| V. Efficiency & Budgets | ✅ Pasa (resuelto) | Presupuesto fijado por clarificación 2026-10-24: ≤75.000 tokens con defaults (justificación registrada en Complexity Tracking + R4) y <3.000 con `delta_target`; mitigación: esquema compacto columnar por strike, redondeo, `null` explícito solo para campos ausentes |
| VI. Graph-First | ✅ Pasa | Descubrimiento hecho vía codebase-memory-mcp (`get_architecture`, `search_graph`, `get_code_snippet`, `get_file_outline`); fallback a filesystem anotado por formato crudo de resultados de `search_graph` |
| Layout | ✅ Pasa | Código en `src/`, tests en `tests/`, docs en `docs/`, scratch en `tmp/` |
| Commit discipline | ✅ Pasa | `docs/tools.md` se actualiza en la misma feature |

## Project Structure

### Documentation (this feature)

```text
specs/008-extract-option-chain/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── mcp-tools.md     # Contrato de la tool get_option_chain
└── tasks.md             # Phase 2 output (/speckit.tasks — no creado aquí)
```

### Source Code (repository root)

```text
src/
└── schwab_mcp/
    ├── options_chain.py   # NUEVO: validación, mapeo, filtros, delta-window, curado
    └── server.py          # Registro de la tool get_option_chain (patrón wrapper existente)

tests/
├── unit/
│   ├── test_options_chain_validation.py   # NUEVO: validación de filtros (Red primero)
│   ├── test_options_chain_mapping.py      # NUEVO: mapeo y curado del payload
│   ├── test_options_chain_filters.py      # NUEVO: strikes/dte/tipo
│   └── test_options_chain_delta.py        # NUEVO: ventana de 5 strikes por tipo
├── integration/
│   └── test_options_chain.py              # NUEVO: flujo end-to-end con double del proveedor
└── performance/
    └── test_options_chain_budgets.py      # NUEVO: presupuesto de tokens y latencia
```

**Structure Decision**: estructura de proyecto único existente; se agrega un
módulo por feature (patrón de `positions.py` y `transactions.py`) y el
registro de la tool se hace en `server.py` con el mismo wrapper-closure que
las dos tools existentes. Contratos y docs se actualizan en la misma feature.

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Crecimiento potencial del presupuesto de tokens (Principio V) | Los defaults exigidos por la spec (50 strikes/lado, ambos tipos, 60 DTE, superset curado de campos, FR-011 sin paginación) producen respuestas de ~45–75k tokens estimados en cadenas anchas. **Resuelto en la clarificación 2026-10-24**: el default de 50 se mantiene (decisión del usuario) y el presupuesto con defaults se fija en ≤75.000 tokens (SC-002), con <3.000 para llamadas con `delta_target` | Recortar griegas o paginar viola FR-006/FR-011; reducir defaults altera el comportamiento exigido por el usuario. Se mitiga con esquema columnar compacto (ambas piernas por fila de strike, redondeo a 4 decimales, `null` explícito solo para campos ausentes). El test T008 debe apuntar al presupuesto de 75k; la justificación también se documenta en `docs/tools.md` |
| **Segundo ajuste del presupuesto de tokens (Principio V) — decisión del usuario 2026-10-24 (implementación 008)** | La medición real de la serialización del formato del contrato (23 columnas por pierna, redondeo 2/4 decimales, ~80–88 tokens por fila con ambas piernas) muestra que el fixture representativo exigido por T008 (12 vencimientos × 100 filas ≈ 1.200 filas) serializa a **~95.000–106.000 tokens**, y el caso con `delta_target` (12 vencimientos × ≤5 strikes × 2 tipos ≈ 120 filas de una pierna) a **~4.500–5.000 tokens** — por encima de los 75.000 / 3.000 de SC-002. El contenido de la respuesta está fijado por FR-002/FR-006 (no admite recorte sin violar la spec). Presupuestos ajustados por decisión del usuario: **≤110.000 tokens** con defaults y **<6.000** con `delta_target` (T008 apunta a estos valores; se documenta en `docs/tools.md`) | Reducir `max_strikes` o recortar `contract_fields` viola FR-002/FR-006; paginar viola FR-011; usar un fixture no representativo (pocos vencimientos) haría que el test no verifique SC-002. Se mantiene el esquema columnar compacto como única mitigación de formato |
| **Tercer ajuste: re-baseline del presupuesto `delta_target` (Principio V) — decisión del usuario 2026-10-24 (convergencia 008, T023)** | Medición live (convergencia T023): cadenas anchas de **16 vencimientos ≤60 DTE** (SPY ~7.334, QQQ ~7.214 tokens) superan el presupuesto `<6.000` fijado en el segundo ajuste, mientras que subyacentes típicos (AAPL ~4.640, TSLA ~5.074) cumplen con holgura. La ventana por delta es ≤5 strikes por tipo **por vencimiento** (FR-004) — el volumen escala con la cantidad de vencimientos que el tope de DTE deja pasar, no es recortable sin violar la spec. Presupuesto re-basado por decisión del usuario: **≤8.000 tokens** con `delta_target`; el test T008 agrega un caso de cadena ancha (16 vencimientos) que fija el nuevo tope; documentado en `docs/tools.md` | La ventana de 5 por tipo está fijada por FR-004 (clarificación 2026-10-23); recortarla viola la spec. Limitar vencimientos adicionales violaría FR-005. El único margen válido es el formato, ya compactado (R4); el re-baseline es el procedimiento de Principio V |
