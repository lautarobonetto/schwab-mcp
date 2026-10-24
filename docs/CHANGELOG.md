# Changelog

Registro del progreso del código de `schwab-mcp`.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/)
y el versionado es [SemVer](https://semver.org/lang/es/): MAJOR para
cambios incompatibles, MINOR por feature nueva, PATCH por correcciones.

## [0.6.2] - 2026-10-24

Documentación — guía anti-errores para agentes que consumen
`get_option_chain` (hallazgos de uso real).

### Added

- **`docs/tools.md` (`get_option_chain`)**: nueva sección
  *Errores comunes de invocación* con las 6 trampas reales observadas
  (enum `option_type` en plural — `put`/`call` singulares se rechazan;
  `dte_max` es tope y no existe `dte_min` — filtrar DTE ≥ N es
  post-proceso cliente; `dte_max: null` aplica tope 60; ventana de
  `delta_target` ≤ 5 strikes por tipo exige múltiples llamadas
  escalonadas para barrer la cadena; `delta_target` es \|delta\|
  absoluta; costo de payload de `extended`). Nueva sección *Recetas*
  con invocaciones correctas para estrategias comunes (piernas de
  strangle por delta, barrido de puts para credit spreads).

## [0.6.1] - 2026-10-24

Bug fix — **`trade_time` epoch cero se reportaba como operación del
1970** (hallazgo live en la primera consulta real de la tool, NOK).

### Fixed

- **`trade_time` de contratos sin operación**: el proveedor manda
  `tradeTimeInLong=0` (y `tradeTime=null`) para contratos que nunca
  operaron; la conversión epoch→ISO los mostraba como
  `1970-01-01T00:00:00+00:00`, inventando una marca temporal inexistente.
  Ahora epoch `0` (en cualquiera de las dos formas del campo) se reporta
  como `null` en su columna (FR-007: no inventar datos). En la consulta
  live de NOK afectaba 96 de 10.074 piernas.

### Validación

- 2 tests de regresión (`tests/unit/test_options_chain_mapping.py`,
  `TestSerializeLeg`) reproducen el defecto (epoch `0` directo y vía
  fallback `tradeTimeInLong=0`) y fallan sin el fix.
- Suite completa: **989 tests**, 0 skipped, 0 failed.

## [0.6.0] - 2026-10-24

Feature 008 — **Extracción de cadena de opciones con filtros**
(spec: `specs/008-extract-option-chain/`).

### Added

- **Tool `get_option_chain`** (tercera tool MCP, solo lectura): extrae la
  cadena de opciones de un subyacente en **una sola invocación** (sin
  paginación, FR-011), con filtros acotadores opcionales: `max_strikes`
  (default 50, por lado del dinero y por vencimiento), `option_type`
  (`both|calls|puts`, default `both`), `delta_target` (ventana de hasta 5
  strikes por tipo alrededor del contrato con |delta| más cercana;
  independiente por tipo y no reducida por `max_strikes`), `dte_max`
  (default: tope vigente 60 días) y `extended` (payload crudo del
  proveedor bajo `provider`).
- **Esquema columnar compacto**: por fila de strike, cada pierna como array
  posicional con orden fijo de 23 columnas declarado en `contract_fields`
  (todas las griegas + valores técnicos); campo ausente → `null` explícito
  (FR-006/FR-007); redondeo determinista 2 decimales (precios) / 4
  (griegas e IV); `trade_time` ISO-8601 UTC.
- **Estados estructurados** (FR-009): `ok`/`chain_retrieved`,
  `no_options_listed`, `no_expirations_in_range` (tope vigente en `detail`
  y eco `filters` con `dte_max_effective`); validación de filtros **antes**
  de cualquier upcall con mensajes accionables (FR-008); `ChainDataError`
  ante un vencimiento entero sin datos — error sin cadena parcial (FR-013).
- **Selección determinista** (data-model §3): ventana simétrica de strikes
  alrededor del ATM (≤ 2×`max_strikes` filas por vencimiento, ATM incluido,
  empate al strike más bajo); ventana por delta = anchor ± 2 contiguos por
  tipo (≤ 5); DTE en días de calendario con post-filtro de bordes;
  expansión interna de `strikeCount` (`max(límite, 100)` con
  `delta_target`, un solo re-fetch a 200 cuando el objetivo no queda
  acotado).
- **Presupuestos medibles** (Principio V): ≤ **110.000 tokens** con
  defaults y < **6.000** con `delta_target` para el fixture
  representativo (~12 vencimientos × 100 filas); latencia ≤ 5 s p95.
  **Ajuste registrado**: la medición real del formato (23 columnas por
  pierna, ~80–88 tokens por fila con ambas piernas) da ~95–106k / ~4,5–5k
  — por encima de los 75k/3k de SC-002 — y el contenido de la respuesta
  está fijado por FR-002/FR-006; los presupuestos se ajustaron por
  decisión del usuario con justificación en
  `specs/008-extract-option-chain/plan.md` (Complexity Tracking) y
  `docs/tools.md`.
- Auditoría: eventos `options_chain_query_{start,success,failure}` en la
  taxonomía de `log.py`.

### Fixed (hallazgos live 2026-10-24, con tests de regresión)

- Claves de `*ExpDateMap` con sufijo (`2026-10-23:-1`) normalizadas a
  `YYYY-MM-DD` (el parseo anterior fallaba en vivo).
- Entradas de vencimiento como listas indexadas por strike
  (`{"737.0": [contract]}`) parseadas además de la forma dict.
- HTTP 400 del proveedor para símbolos sin opciones (`ZZZZZZ`) mapeado al
  estado estructurado `no_options_listed` en vez de error de transporte.

### Validación

- Suite completa: **975 tests**, 0 skipped, 0 failed (baseline pre-feature:
  842).
- Gates del quickstart: unit 93, integración 30, performance 5.
- Validación live S1–S4 contra el proveedor real (token vigente): **24/24
  checks**, incl. SC-005 (ventanas por tipo con delta, una invocación por
  escenario). S1 SPY defaults: 1,4 s / ~67k tokens. Nota live: SPY con 16
  vencimientos ≤60 DTE produce ~7,5k tokens con `delta_target` + ambos
  tipos (el presupuesto <6.000 aplica al fixture de 12 vencimientos).

### Changed (convergencia, misma fecha)

- **Re-baseline del presupuesto `delta_target` a ≤ 8.000 tokens** (T023,
  decisión del usuario): la medición live de la convergencia (SPY ~7.334,
  QQQ ~7.214, AAPL ~4.640, TSLA ~5.074 tokens) mostró que cadenas anchas
  de 16 vencimientos superan el tope de <6.000; la ventana de 5 strikes
  por tipo aplica por vencimiento (FR-004) y el volumen escala con los
  vencimientos dentro del tope de DTE. Justificación registrada en
  `specs/008-extract-option-chain/plan.md` (Complexity Tracking) y
  `docs/tools.md`; el test de presupuestos agrega un caso de cadena ancha
  (16 vencimientos) que fija el nuevo tope.
- **Normalización de enteros en `serialize_leg`** (T024): `multiplier`
  llega como float del proveedor live (`100.0`) y ahora se serializa como
  entero (`volume`/`open_interest`/`multiplier`), sin truncar valores no
  integrales (regresión con test).
- **Test del escenario "fuente caída"** (T022): la suite de integración
  fija el camino 5xx/408/429 (quickstart S4): `ConnectivityError`
  accionable, evento de auditoría `provider_unreachable`, 1 upcall, sin
  cadena parcial. Suite completa tras la convergencia: **987 tests**.

## [0.5.1] - 2026-10-24

Bug fix — **`get_transaction_history` curaba todo trade como `CURRENCY_USD`**
(bug: `.specify/bugs/nok-symbol-filter-miss/`).

### Fixed

- **`symbol` del movimiento en trades multi-leg**: en el payload real de
  `/transactions`, cada TRADE trae en `transferItems` primero las patas de
  efectivo/comisiones (todas con `instrument.symbol = "CURRENCY_USD"`,
  `assetType = CURRENCY`, no-None) y al final la pata del instrumento
  negociado. El mapper tomaba el primer item con símbolo → ~131 de 173
  movimientos `trade` reales quedaban etiquetados `CURRENCY_USD/CURRENCY`
  con descripción vacía, ocultando el instrumento. Consecuencia: el filtro
  `symbol=X` (M1/M2/M3) nunca matcheaba y la tool afirmaba falsamente
  `no_movements_for_instrument` (p. ej. 14 legs de opciones NOK en el
  período eran invisibles). Ahora el mapper cura el **primer instrumento
  no-divisa** y solo cae en `CURRENCY_USD` para movimientos genuinamente
  de efectivo. `underlying_symbol` se deriva del símbolo corregido.

### Validación

- 5 tests de regresión (`tests/unit/test_transactions_live_response.py`,
  sección multi-leg) reproducen el shape real del payload y fallan sin el
  fix. Verificación end-to-end en vivo contra el proveedor real: la
  consulta original del bug retorna 14 legs NOK (pre-fix: 0) y el barrido
  sin filtro se mantiene en 173 movimientos. Detalle:
  `.specify/bugs/nok-symbol-filter-miss/`.
- Suite completa: **842 tests**, 0 skipped, 0 failed.

## [0.5.0] - 2026-10-24

Feature 007 — **Filtro consciente del subyacente y referencia de
subyacente en opciones** (spec: `specs/007-underlying-symbol-filter/`).

### Added

- **Filtro `symbol` consciente del subyacente**: `symbol="NOK"` devuelve
  **tanto** los movimientos registrados bajo `NOK` **como** las opciones
  cuyo root OCC es `NOK` (tres formas de matching: M1 símbolo registrado,
  M2 root de opción, M3 OCC completo — data-model §2). Comparación
  **insensible a mayúsculas**; sin fuzzy (substring no matchea). El filtro
  **ya no viaja upstream** (research R1): se aplica localmente tras el
  barrido, garantizando subset-consistency por construcción.
- **Validación dual del filtro (FR-003)**: si el directorio de instrumentos
  no resuelve el símbolo, la tool **no falla** — procede con el barrido
  y solo reporta `instrument_not_found` si ningún movimiento matchea en
  ninguna forma. Esto habilita el filtro por símbolo OCC completo (antes
  rechazado por el proveedor con HTTP 400) y el filtro `CURRENCY_USD`
  (antes `instrument_not_found`).
- **`underlying_symbol` en `MovementEntry`**: cada movimiento de opción
  con OCC identificable expone el subyacente (root sin padding, p. ej.
  `"NOK"` desde `"NOK   261218P00011000"`). Campo ausente (excluido por
  `exclude_none`) para no-opciones y opciones sin OCC identificable.

### Changed

- `src/schwab_mcp/transactions.py`: agrega `_option_root()` y
  `movement_involves_filter()` (matching puro); `get_transaction_history`
  ya no envía `symbol` upstream (research R1), aplica validación dual
  (FR-003) y filtra localmente antes de paginar; `map_provider_transactions`
  deriva `underlying_symbol` para opciones. Se elimina `validate_symbol()`,
  muerto tras la validación dual (su lógica de lookup vive ahora en
  `_symbol_resolved_in_directory()`, única fuente de verdad).
- `pyproject.toml`: versión del paquete alineada a 0.5.0.
- `docs/tools.md`: semántica del filtro actualizada (subyacente + opciones,
  OCC completo, case-insensitive, validación dual); `underlying_symbol`
  documentado en el schema de `MovementEntry`; caveat de opciones
  reemplazado por la nueva conducta.
- `docs/CHANGELOG.md`: este registro.

### Validación

- Test de matching: `_option_root()` con 12 casos (padding, sin padding,
  root corto/largo, put/call, no-OCC, None, inválidos) — todos pasan.
- Test del matcher: `movement_involves_filter()` con 21 casos (M1/M2/M3,
  case-insensitive, sin fuzzy, CURRENCY_USD, None filter) — todos pasan.
- Tests de filtro US1 (31 tests): no envía symbol upstream, filtro por
  subyacente incluye opciones, OCC completo, case-insensitivity,
  subset-consistency, paginación sobre filtrado, validación dual
  (directory no resuelve + matches → ok; directory no resuelve + 0 matches
  → error), CURRENCY_USD, partial_failure con filtro.
- Tests de `underlying_symbol` US2 (13 tests): presente en opciones,
  ausente en no-opciones, ausente en OCC no identificable, extended sin
  cambios, sin secretos.
- Tests de presupuesto: worst-case 50 opciones con `underlying_symbol`
  ≤ 16 KB default y ≤ 64 KB extended.
- Legacy tests actualizados: 3 tests adaptados a la nueva semántica
  (symbol no se envía upstream, validación dual).
- Suite completa: **837 tests**, 0 skipped, 0 failed.

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

[0.5.1]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lautarobonetto/schwab-mcp/releases/tag/v0.1.0