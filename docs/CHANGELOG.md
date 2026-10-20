# Changelog

Registro del progreso del código de `schwab-mcp`.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/)
y el versionado es [SemVer](https://semver.org/lang/es/): MAJOR para
cambios incompatibles, MINOR por feature nueva, PATCH por correcciones.

## [0.3.0] - 2026-10-20

Feature 003 — **Primera tool MCP: listar posiciones abiertas** (spec:
`specs/003-list-open-positions/`).

### Added

- **`get_open_positions` tool MCP**: primera herramienta registrada por
  el servidor `serve`. Recupera todas las tenencias efectivas de todas
  las cuentas vinculadas en una sola llamada upstream, con resultado
  estructurado auto-clasificante (`PositionsResult`).
- **Input schema**: argumento `extended: bool = false` — `false` (default)
  produce el set curado (compacto); `true` agrega passthrough completo
  del proveedor como objeto `extended` por entrada.
- **Output clasificado (`PositionsResult`)**: contiene `outcome` (`ok` ·
  `partial_failure` · `transient_failure` · `reauth_required`), `positions`
  (array de `PositionEntry`), `accounts_failed` (solo en fallo parcial),
  `retryable`, `detail` y `retrieved_at`.
- **Error mapping**: `ConnectivityError` → `transient_failure` (retryable,
  sin reintentos internos — FR-007); `ReauthorizationRequiredError` /
  `TokenStoreCorruptedError` → `reauth_required`; fallo por cuenta
  (`error` en `accountDetails`) → `partial_failure` con `accounts_failed`
  clasificando cada fallo como `provider_error` o `transient`.
- **Consolidación por lote**: posiciones del mismo `(account_hash, symbol)`
  se consolidan con `average_price` promedio (FR-013).
- **Auditoría de posiciones**: evento `positions_query_start` → terminal
  `positions_query_success` / `positions_query_failure` en stderr, sin
  secretos.
- **Presupuestos medibles**: ≤ 5 s latencia, ≤ 8 KB default, ≤ 16 KB
  extended. Crecimiento requiere justificación registrada.
- **Documentación**: contrato de tool MCP, data model, eventos de auditoría
  y checklist de requirements en `specs/003-list-open-positions/`. Tabla
  de superficie MCP actualizada en `docs/tools.md`.

### Changed

- `src/schwab_mcp/server.py`: registro de `get_open_positions` vía
  `mcp.add_tool(...)` con wrapper que oculta `client` del input schema
  MCP.
- `docs/tools.md`: documenta `get_open_positions` como primera tool MCP,
  actualiza versión del documento a 0.3.0.

### Validación

- Test de registro: la tool aparece en `list_tools()` con nombre exacto
  y función sincrónica.
- Test de resultado vacío: `positions: []` con `outcome: ok` y
  `detail: no_positions`.
- Test de consolidación: mismo `(account_hash, symbol)` se promedia.
- Test de fallo por cuenta: `partial_failure` incluye `accounts_failed`.
- Test de errores: cada clase de error upstream produce el `outcome`
  correcto (sin reintentos en transitorio).
- Test de eventos: exactamente un `positions_query_start` + un terminal
  por invocación.
- Test de presupuesto de payload: default ≤ 8 KB, extended ≤ 16 KB.
- Test de latencia: ≤ 5 s en entorno controlado.
- Tests de rendimiento: marcador `performance`.
- Suite completa verde.

## [0.3.0] - 2026-10-20

Feature 003 — **List Open Positions** como primera tool MCP real
(spec: `specs/003-list-open-positions/`).

### Added

- **`get_open_positions`** (MCP tool, US1 — MVP): primera herramienta
  registrada vía `MCPServer.add_tool`. Recupera todas las tenencias
  efectivas de todas las cuentas vinculadas en una sola llamada upstream
  (`account_details_all(fields="positions")`). Resultado estructurado
  auto-clasificante (`PositionsResult`) con campos curados por posición
  (`symbol`, `instrument_type`, `quantity` con signo, `average_price`,
  `market_value`, `unrealized_pl`, `price_timestamp`). Clasificación de
  fallos: `transient_failure` (red/proveedor), `reauth_required`
  (auth caducado/corrupto). Sin reintentos internos (FR-007). Auditoría
  `positions_query_start` → `positions_query_success`/`positions_query_failure`
  en cada invocación (FR-014).
- **Metadatos completos por posición (US2)**: `unrealized_pl` derivado
  con signo (research D3), campos de opción condicionales
  (`underlying_symbol`, `put_call`, `strike_price`, `expiration_date` para
  `assetType=OPTION`), y `extended=true` para passthrough de campos
  adicionales del proveedor (FR-003a). Presupuestos medibles: ≤ 5 s de
  latencia, ≤ 12 KB default (50 posiciones), ≤ 20 KB extended.
- **Aislamiento de fallos por cuenta (US3)**: detección de errores
  individuales en `accountDetails` → `partial_failure` con
  `accounts_failed` y posiciones de las cuentas exitosas (FR-010).
  Verificación transversal de secretos: todas las formas de resultado
  (`ok`, `vacío`, `partial`, `transient`, `reauth`) confirmadas sin
  datos de autenticación ni números de cuenta crudos (FR-008).

### Changed

- `src/schwab_mcp/positions.py` (nuevo): modelos Pydantic
  (`PositionEntry`, `PositionsResult`, `AccountFailed`) con validación
  cruzada; función de mapeo `map_provider_positions` y orquestación
  `get_open_positions`.
- `src/schwab_mcp/server.py`: registra la tool `get_open_positions` vía
  `MCPServer.add_tool`.
- `src/schwab_mcp/log.py`: agrega eventos de posiciones
  (`positions_query_start`, `positions_query_success`,
  `positions_query_failure`) al vocabulario de auditoría.
- `docs/tools.md`: documentación completa de la tool, su invocación,
  resultados, y error mapping.
- `docs/CHANGELOG.md`: este registro.

## [0.2.0] - 2026-10-19

Feature 002 — **Renovación automática de tokens** para agentes de AI
desatendidos (spec: `specs/002-automated-token-renewal/`).

### Added

- **`schwab-mcp renew`**: renovación explícita no interactiva con
  resultado clasificado en una línea JSON (≤ 300 bytes) y exit codes
  `0/2/3/6/7` — el agente distingue éxito, `not_needed`, fallo
  transitorio (reintentable) y `reauth_required` (acción humana) sin
  interpretar texto libre.
- **`schwab-mcp auth-status`**: consulta de salud de autenticación en
  una request — estado (`valid`/`reauth_required`), vida útil restante
  del access y del refresh token. Lectura estrictamente local, sin red,
  ≤ 2 s; nunca dispara renovaciones.
- **Clasificación de outcomes** (`renewal.py`): tipos `RenewalOutcome` /
  `AuthHealth` con enums cerrados (`renewed|not_needed|
  transient_failure|reauth_required`), serialización compacta y cero
  secretos.
- **Camino automático transparente (US1)**: toda operación autenticada
  con validez por debajo del margen preventivo (61 s, provisto por
  schwabdev) renueva solo, sin browser ni interacción; la forma del
  resultado de la operación no cambia.
- **Eventos de auditoría de renovación**: `renew_start` →
  `renewal_success`/`renewal_failure` en stderr, con trigger
  `margin_trigger` (automático) o `explicit_command` (CLI), sin secretos.
- **Estado "re-autorización requerida" detectable (US3)**: cuando el
  refresh token es rechazado, todas las rutas reportan la misma
  clasificación consistente y acotan los intentos contra el proveedor
  (sin retry storms).
- **Guía para agentes de AI**: `docs/tools.md` — referencia detallada de
  la interfaz consumible por agentes.

### Changed

- `retry_once` generalizado a `retry_call(fn, retries=2)` en
  `tokens.py`: implementación única de reintento acotado del proyecto
  (DRY), reutilizada por validación de arranque y renovación.
- `server.py`: validación de arranque usa el reintento generalizado y
  emite eventos de ciclo de vida de renovación.

### Fixed

- **Regresión ISO-8601** en el lector de vida útil: schwabdev guarda
  `*_token_issued` como texto ISO (`2026-10-19T22:00:27.004577+00:00`),
  no como epoch numérico; el lector hacía `float - str` y crasheaba con
  exit 1. Ahora parsea ISO (asumiendo UTC si falta zona), tolera epochs
  numéricos y degrada a `reauth_required` ante timestamps no parseables
  en lugar de crashear. Cubierto con pruebas de regresión sobre el
  esquema real de la DB.

### Validación

- 294 tests pasando, 0 skipped (gates de rendimiento ≤ 10 s y de
  token-usage ≤ 300 bytes incluidos).
- Smoke manual verificado: `renew` (`not_needed` exit 0),
  `auth-status` (`valid` exit 0), fail-fast de configuración (exit 2).

## [0.1.0] - 2026-10-19

Feature 001 — **Capa de acceso OAuth a Schwab** (spec:
`specs/001-schwab-oauth-access/`).

### Added

- **`schwab-mcp auth`**: autorización interactiva one-shot con flujo
  paste-the-redirect-URL (browser del dueño + paste de la URL de
  redirect). Sin sockets de entrada.
- **`schwab-mcp serve`**: servidor MCP stdio headless con validación
  proactiva de acceso al arrancar (< 5 s). Registra 0 tools en esta
  versión (reservado para features futuras).
- **Token store** local SQLite (vía schwabdev 4.0.0) en
  `~/.schwab-mcp/tokens.db` con permisos `0o600`.
- **Taxonomía de errores** con exit codes accionables por falla
  (configuración, autorización, store, conectividad) — sin tracebacks.
- **Filtro de redacción** en logs: app secret, tokens y códigos de
  autorización jamás aparecen en la salida.
- **Lock de autorización** para evitar corridas concurrentes.
- Documentación: `docs/instalacion.md`, `docs/uso.md`; artefactos de
  spec en `specs/001-schwab-oauth-access/`.
- Suite de tests (unit/integration/performance) con gates TDD.

[0.3.0]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lautarobonetto/schwab-mcp/releases/tag/v0.1.0