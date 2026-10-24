# Changelog

Registro del progreso del código de `schwab-mcp`.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/)
y el versionado es [SemVer](https://semver.org/lang/es/): MAJOR para
cambios incompatibles, MINOR por feature nueva, PATCH por correcciones.

## [0.4.0] - 2026-10-23

Feature 006 — **Historial completo de movimientos** (spec:
`specs/006-transaction-history/`).

### Added

- **`get_transaction_history` tool MCP**: recupera el historial completo de
  movimientos de todas las cuentas vinculadas en un rango de fechas (1
  `linked_accounts` + 1 `transactions` por cuenta, con la lista completa de
  los 15 tipos upstream separados por comas). Cada movimiento se reporta con
  una categoría normalizada de un **enum cerrado**: `trade`, `transfer`,
  `dividend_or_interest`, `adjustment`, `other` (fallback para tipos
  desconocidos); `interest`, `dividend`, `fee` y `corporate_action` quedan
  reservados sin mapeo upstream en v1 (el proveedor reporta dividendos e
  intereses como un único tipo indistinguible).
- **Input schema y filtros**: `start_date` / `end_date` obligatorios
  (`YYYY-MM-DD`, bordes inclusivos, interpretados en America/New_York) con
  validación previa a toda upcall: rango ≤ 1 año (366 días), `end_date` ≥
  `start_date`, `end_date` no futura, `offset` ≥ 0; `symbol` opcional para
  filtrar por instrumento (validado contra el proveedor vía
  `instruments(..., "symbol-search")` — símbolo inexistente → error
  `instrument_not_found`, no vacío ambiguo); `extended: bool = false` para el
  detalle extendido on-demand.
- **Tope upstream de 3000 movimientos**: split por bisección del rango con
  deduplicación por `(account_hash, activityId)` — sin truncado silencioso
  ni duplicados.
- **Output estructurado (`TransactionsResult`)**: contiene `outcome`
  (`ok` · `partial_failure` · `transient_failure` · `reauth_required`),
  `detail` (`history_retrieved` · `no_movements` ·
  `no_movements_for_instrument` · `account_failed` · `provider_unreachable`
  · `reauth_needed`), `retryable`, `retrieved_at`, `total_count`,
  `movements` (array de `MovementEntry`), `returned`, `has_more`,
  `next_offset`/`offset_echo` (paginación explícita de 50 movimientos por
  página, orden cronológico ascendente con desempate por `account_hash` y
  `activityId`), y `accounts_failed` (solo en `partial_failure`, con
  `provider_error`/`transient` por cuenta — resultado parcial explícito,
  nunca cuentas descartadas en silencio).
- **Cada movimiento (`MovementEntry`)**: `account_hash` (opaco, nunca número
  de cuenta), `occurred_at` (ISO-8601), `category` (enum cerrado),
  `description` (truncada a 80 caracteres en el modo default), `amount`,
  `currency` (default `"USD"`, sin conversión), y opcionalmente `symbol`,
  `instrument_type` y `extended` (solo con `extended=true`: type original
  del proveedor, descripción completa, `fees`, `commissions`, `netAmount`,
  `settlementDate`, `transferItems`, `activityId`).
- **Sin reintentos internos** ante fallo transitorio: se reporta
  `transient_failure/provider_unreachable` con `retryable=true` al primer
  intento, para que el agente aplique su propio playbook.
- **Error mapping**: consistente con el resto del servidor
  (`ConnectivityError`→`transient_failure`,
  `ReauthorizationRequiredError`→`reauth_required`, errores por
  cuenta→`partial_failure`).
- **Auditoría**: evento `transactions_query_start` → terminal
  `transactions_query_success` (ok/partial) o
  `transactions_query_failure` (transient/reauth/validation) en stderr,
  sin secretos y sin texto del proveedor sin redactar.
- **Documentación**: contrato de tool MCP, data model, eventos de auditoría
  y checklist en `specs/006-transaction-history/`. Sección completa de la
  tool en `docs/tools.md`.

### Fixed

- **Manejo de respuestas del SDK en vivo** (hallado en prueba manual contra
  la API real 2026-10-23): el cliente `schwabdev` devuelve
  `requests.Response` — la orquestación unwrapea el body JSON vía
  `schwab_mcp.provider.response_json` (única fuente de verdad, reutilizable
  por otras tools) y clasifica estados HTTP (401/403 → reauth, 5xx/408/429 →
  transitorio, resto de 4xx → `provider_error` por cuenta). Sin esto, toda
  invocación en vivo fallaba con `AttributeError` pese a la suite verde
  (los fakes devolvían dicts).
- **Forma real del payload**: `linked_accounts()` usa `hashValue` (no
  `accountHash`); `transactions` responde una lista JSON en el nivel
  superior (no `{"transactions": [...]}`); el timestamp vive en `time` (no
  `transactionDate`); el instrumento viaja dentro de `transferItems[].instrument`
  con `assetType`. El mapper acepta ambas formas.
- **Fechas para el proveedor**: la API rechaza `YYYY-MM-DD` crudo
  (`'2026-09-01' is not a valid value for startDate`); se envían datetimes
  ISO-8601 acotados en America/New_York (medianoche a 23:59:59 locales,
  offset DST real) — bordes inclusivos según spec.
- **Proyección de búsqueda de instrumentos**: el validador del SDK exige
  `symbol-search` (minúsculas); `SYMBOL_SEARCH` era rechazado.
- **Errores accionables en el canal MCP**: los errores de validación y
  `instrument_not_found` se convierten en `ToolError` en el límite de la
  tool (`get_transaction_history_tool`), de modo que el mensaje accionable
  llega al agente en lugar del texto genérico del SDK (FR-009d, SC-005).
- **`SCHWAB_CALLBACK_URL` con barra final** (hallado en vivo 2026-10-24):
  el portal de desarrollo de Schwab puede **exigir** la barra final en el
  callback registrado (sin ella la app pasa a estado de error y no se
  puede enviar a aprobar), mientras que `schwabdev` rechaza callbacks que
  terminan en `/`. `load_config()` ahora normaliza el valor (quita barras
  finales), así que ambas formas funcionan sin tocar el registro de la
  app.
- **`get_open_positions` en vivo** (bug `positions-response-unwrap`,
  2026-10-24): la tool fallaba en toda invocación real por tres razones
  encadenadas — el SDK devuelve `requests.Response` sin parsear (ahora
  unwrapeado con `schwab_mcp.provider.response_json`, la misma fuente de
  verdad que 006), el payload real es una lista top-level de
  `{aggregatedBalance, securitiesAccount}` (no el dict `accountDetails`
  asumido), y el identificador de cuenta ahora es el `hashValue` opaco del
  proveedor cruzado por `accountNumber` con `linked_accounts()` (se retiró
  el hash local SHA-256 truncado del número de cuenta). **Breaking**: los
  valores de `account_hash` cambian — ahora son consistentes con
  `get_transaction_history`. Además, los instrumentos OPTION reales no
  traen `strikePrice`/`expirationDate`: se derivan del símbolo OCC.

### Changed

- `src/schwab_mcp/server.py`: registro de `get_transaction_history` vía
  `mcp.add_tool(...)` con wrapper que oculta `client` del input schema MCP.
- `src/schwab_mcp/transactions.py` (nuevo): modelos Pydantic
  (`MovementEntry`, `TransactionsResult` con reglas de validación cruzada
  del data model), enums (`MovementCategory`, `ProviderTransactionType`),
  mapeo `map_provider_transactions`, orquestación por cuenta, validación de
  la consulta, validación de símbolo, bisección ante el tope de 3000 y
  paginación por offset.
- `src/schwab_mcp/log.py`: agrega los eventos de transacciones
  (`transactions_query_start`, `transactions_query_success`,
  `transactions_query_failure`) al vocabulario de auditoría.
- `docs/tools.md`: documenta `get_transaction_history`, filtros,
  categorías, paginación, garantías y error mapping.
- `docs/CHANGELOG.md`: este registro.

### Validación

- Test de registro: la tool aparece en `list_tools()` con nombre exacto.
- Test de resultado vacío: `movements: []` con `outcome: ok` y
  `detail: no_movements`.
- Test de categorías: cada uno de los 15 tipos upstream mapea a la
  categoría del enum cerrado correcta; tipos no reconocidos→`other`.
- Test de paginación: orden cronológico, páginas de 50, walk completo
  (offset 0→50→100) sin duplicados ni omisiones; `total_count` estable.
- Test de bisección: respuestas en el tope de 3000 disparan split del
  rango; fusión sin duplicados ni omisiones.
- Test de validación de fechas: rango > 366 días, `end < start`, fechas
  mal formadas o futuras, `offset < 0` rechazados antes de toda upcall.
- Test de filtro por símbolo: solo movimientos del símbolo solicitado;
  símbolo inexistente→`instrument_not_found`; sin `symbol`, cero upcalls
  de `instruments`.
- Test de errores: cada clase de error upstream produce el `outcome`
  correcto (transitorio al primer intento, re-auth, fallo parcial por
  cuenta).
- Test de eventos: exactamente un `transactions_query_start` + un terminal
  por invocación.
- Test de no-secretos: ni el resultado ni los eventos contienen tokens,
  app keys ni números de cuenta.
- Presupuestos: latencia p95 ≤ 5 s y página default ≤ 16 KB (extended
  ≤ 64 KB) en `tests/performance/test_transactions_budgets.py`.
- Suite completa verde (735 tests, 0 skipped).

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

[0.4.0]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lautarobonetto/schwab-mcp/releases/tag/v0.1.0