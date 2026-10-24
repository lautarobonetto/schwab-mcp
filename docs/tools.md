# Interfaz para agentes de AI

Referencia completa de la superficie consumible por un agente de AI
(por ejemplo, OpenClaw). Documenta **cada comando y cada campo** de la
salida, con semántica exacta para que el agente pueda decidir sin
intervención humana.

**Versión del documento**: 0.6.0 (ver [CHANGELOG](./CHANGELOG.md)).

## Cómo se consume este MCP

El proyecto expone **dos superficies**, con roles distintos:

| Superficie | Cómo se invoca | Estado en esta versión |
|------------|----------------|------------------------|
| Servidor MCP `serve` | Cliente MCP conecta por **stdio** | Transporte activo; **3 tools registradas** (`get_open_positions`, `get_transaction_history` y `get_option_chain`) |
| CLI one-shot | El agente corre `schwab-mcp <comando>` por shell | **Superficie principal del agente** hoy |

Las herramientas ``get_open_positions``, ``get_transaction_history`` y
``get_option_chain`` (primera, segunda y tercera tool MCP registradas)
están disponibles a través del servidor ``serve``, complementando los
comandos one-shot descritos abajo.

Garantías transversales de **todos** los comandos agent-facing:

- **No interactivos**: nunca abren browser, nunca leen stdin, nunca
  escuchan en sockets. Seguros para ejecución desatendida.
- **Salida parseable**: exactamente **una línea JSON** en stdout;
  nada más en stdout. Mensajes auxiliares y eventos van a stderr.
- **Sin secretos**: ningún campo contiene tokens, app keys/secretos ni
  URLs de autorización. Hay un filtro de redacción activo como defensa
  adicional (stderr incluido).
- **Tiempo acotado**: ningún comando se cuelga; presupuestos por comando.
- **Seguros ante concurrencia**: coordinación por lock; corrompen nada.

---

## `get_open_positions` (primera tool MCP)

Primera herramienta MCP registrada por el servidor ``serve`` (feature
``003-list-open-positions``). Recupera todas las tenencias efectivas de
todas las cuentas vinculadas en una sola llamada upstream, con resultados
estructurados auto-clasificantes.

### Invocación

```json
{"name": "get_open_positions", "arguments": {}}
```

### Argumentos (input schema)

| Campo | Tipo | Default | Semántica |
|-------|------|---------|-----------|
| ``extended`` | bool | ``false`` | ``false`` (default): solo el set curado (compacto). ``true``: cada posición agrega el objeto ``extended`` con el passthrough completo del proveedor. |

Sin otros parámetros en v1: la consulta cubre siempre **todas** las
cuentas vinculadas.

### Output schema

Exactamente un objeto ``PositionsResult`` por invocación. Campos:

| Campo | Tipo | Valores |
|-------|------|---------|
| ``outcome`` | enum cerrado | ``ok`` · ``partial_failure`` · ``transient_failure`` · ``reauth_required`` |
| ``positions`` | array | Entradas ``PositionEntry``; ``[]`` válido solo con ``outcome: "ok"`` |
| ``accounts_failed`` | array \| ausente | Solo ``partial_failure``: ``[{account_hash, detail}]``, ``detail ∈ {provider_error, transient}`` |
| ``retryable`` | bool | ``true`` solo cuando ``outcome == "transient_failure"`` |
| ``detail`` | enum cerrado | ``data_received`` · ``no_positions`` · ``account_failed`` · ``provider_unreachable`` · ``reauth_needed`` · ``store_absent`` · ``store_corrupted`` |
| ``retrieved_at`` | string ISO-8601 UTC | Momento de recuperación del payload del proveedor |

El ``account_hash`` es el ``hashValue`` opaco del proveedor (de
``linked_accounts()``, cruzado por ``accountNumber``) — el mismo
identificador que expone ``get_transaction_history``, consistente en toda
la superficie MCP.

El esquema completo de ``PositionEntry`` y las reglas de validación
cruzada están en el
[data model](../specs/003-list-open-positions/data-model.md).

### Error mapping

| Condición | ``outcome`` | ``retryable`` | Acción del agente |
|-----------|-------------|---------------|-------------------|
| Red/proveedor no disponible | ``transient_failure`` | ``true`` | Reintentar con backoff |
| Refresh rechazado / store corrupto | ``reauth_required`` | ``false`` | Notificar al dueño (``schwab-mcp auth``), monitorear con ``auth-status`` |
| Algunas cuentas fallaron, otras no | ``partial_failure`` | ``false`` | Evaluar si reintentar; datos parciales en ``positions`` |
| Todas las cuentas respondieron | ``ok`` | ``false`` | Continuar normalmente |

### Garantías

- **Read-only**: no coloca órdenes ni mueve dinero.
- **Sin secretos**: ningún token/credencial en la salida.
- **Presupuesto**: ≤ 5 s de latencia; ≤ 8 KB default (≈ 2 000 tokens),
  ≤ 16 KB extended.
- **Sin reintentos internos** ante fallo transitorio (FR-007): el agente
  decide.

### Referencia

- Contrato completo:
  [`specs/003-list-open-positions/contracts/mcp-tools.md`](../specs/003-list-open-positions/contracts/mcp-tools.md)
- Data model:
  [`specs/003-list-open-positions/data-model.md`](../specs/003-list-open-positions/data-model.md)
- Eventos de auditoría:
  [`specs/003-list-open-positions/contracts/events.md`](../specs/003-list-open-positions/contracts/events.md)

---

## `get_transaction_history` (segunda tool MCP)

Segunda herramienta MCP registrada por el servidor ``serve`` (feature
``006-transaction-history``). Recupera el historial de transacciones de
todas las cuentas vinculadas en un rango de fechas, con resultados
estructurados y paginación determinista.

### Invocación

```json
{
  "name": "get_transaction_history",
  "arguments": {
    "start_date": "2026-09-01",
    "end_date": "2026-09-30"
  }
}
```

Con filtro por instrumento y paginación:

```json
{
  "name": "get_transaction_history",
  "arguments": {
    "start_date": "2026-01-01",
    "end_date": "2026-09-30",
    "symbol": "AAPL",
    "offset": 50
  }
}
```

### Argumentos (input schema)

| Campo | Tipo | Default | Semántica |
|-------|------|---------|-----------|
| `start_date` | string | obligatorio | Fecha inicio del rango, `YYYY-MM-DD`. Borde **inclusivo**, interpretado en America/New_York. |
| `end_date` | string | obligatorio | Fecha fin del rango, `YYYY-MM-DD`. Borde **inclusivo**; no puede ser futura. |
| `symbol` | string \| ausente | sin filtro | Si está presente: solo movimientos que **involucran** a ese instrumento (data-model §2): el símbolo registrado coincide exactamente (M1), o es una opción cuyo subyacente (root OCC) coincide (M2), o es un símbolo OCC completo (M3). Comparación **insensible a mayúsculas**. Validación dual: si el directorio no resuelve el filtro, se consulta igual y solo se reporta `instrument_not_found` si ningún movimiento matchea (FR-003). **Ya no se envía upstream** (research R1) — el filtro se aplica localmente. |
| `extended` | bool | `false` | `false` (default): set curado compacto. `true`: cada movimiento agrega `extended` con el passthrough del proveedor (type original, descripción completa, fees, netAmount, transferItems…). |
| `offset` | int | `0` | Continuación de paginación: repetir la misma consulta con el `next_offset` recibido. |

Ventana máxima: **1 año** (366 días calendario) entre `start_date` y
`end_date`. Rangos mayores → error de validación que indica el máximo
y sugiere dividir la consulta.

### Output schema

Exactamente un objeto `TransactionsResult` por invocación:

| Campo | Tipo | Presencia | Semántica |
|-------|------|-----------|-----------|
| `outcome` | enum cerrado | siempre | `ok` · `partial_failure` · `transient_failure` · `reauth_required` |
| `detail` | enum cerrado | siempre | `history_retrieved` · `no_movements` · `no_movements_for_instrument` · `account_failed` · `provider_unreachable` · `reauth_needed` |
| `retryable` | bool | siempre | `true` solo cuando `outcome == "transient_failure"` |
| `retrieved_at` | string ISO-8601 UTC | siempre | Momento de recuperación del payload del proveedor |
| `total_count` | int | `outcome=ok` | Total de movimientos del rango completo (todas las páginas) |
| `movements` | array | `outcome=ok` | Lista de entradas `MovementEntry` (ver data-model); `[]` válido solo con `no_movements`/`no_movements_for_instrument` |
| `returned` | int | `outcome=ok` | Cantidad de movimientos en esta página (≤ 50) |
| `has_more` | bool | `outcome=ok` | `true` si quedan movimientos por entregar |
| `next_offset` | int \| ausente | solo `has_more=true` | Offset para la solicitar la siguiente página |
| `accounts_failed` | array \| ausente | solo `partial_failure` | `[{"account_hash": str, "detail": "provider_error"|"transient"}]` |
| `offset_echo` | int | `outcome=ok` | Offset efectivo aplicado a esta página |

Ejemplo de respuesta (`ok`, primera página):

```json
{
  "outcome": "ok",
  "detail": "history_retrieved",
  "retryable": false,
  "retrieved_at": "2026-10-23T14:00:00+00:00",
  "total_count": 137,
  "returned": 50,
  "has_more": true,
  "next_offset": 50,
  "offset_echo": 0,
  "movements": [
    {
      "account_hash": "AB12CD34EF56GH78",
      "occurred_at": "2026-09-03T15:45:00-04:00",
      "category": "trade",
      "description": "You SOLD 10 shares of AAPL",
      "amount": -2318.9,
      "currency": "USD",
      "symbol": "AAPL",
      "instrument_type": "EQUITY"
    },
    {
      "account_hash": "AB12CD34EF56GH78",
      "occurred_at": "2026-09-03T15:46:00-04:00",
      "category": "trade",
      "description": "Option trade",
      "amount": -50.0,
      "currency": "USD",
      "symbol": "NOK   261218P00011000",
      "instrument_type": "OPTION",
      "underlying_symbol": "NOK"
    }
  ]
}
```

Cada `MovementEntry` contiene:

| Campo | Tipo | Presencia | Semántica |
|-------|------|-----------|-----------|
| `account_hash` | string | siempre | Identificador opaco de la cuenta (nunca número de cuenta) |
| `occurred_at` | string ISO-8601 | siempre | Fecha/hora del movimiento (timezone del proveedor) |
| `category` | enum cerrado | siempre | Categoría normalizada: `trade` · `transfer` · `dividend_or_interest` · `adjustment` · `other` |
| `description` | string | siempre | Descripción legible, **truncada a 80 caracteres** en default (texto completo en `extended`) |
| `amount` | float | siempre | Efecto monetario principal (signo del proveedor, no reinterpretado) |
| `currency` | string | siempre | Moneda del movimiento (default `"USD"`) |
| `symbol` | string \| ausente | solo si hay instrumento | Símbolo del instrumento referenciado. En trades con patas de efectivo/comisiones (`transferItems`), se cura el **primer instrumento no-divisa** (las patas `CURRENCY_USD` van primero en el payload real); `CURRENCY_USD` solo si el movimiento es genuinamente de efectivo |
| `instrument_type` | string \| ausente | solo si hay instrumento | Tipo de activo (`EQUITY`, `ETF`, `OPTION`, …) |
| `underlying_symbol` | string \| ausente | solo movimientos de opción con OCC identificable | Subyacente de la opción: root del símbolo OCC sin padding (p. ej. `"NOK"` desde `"NOK   261218P00011000"`). Ausente para no-opciones. |
| `extended` | object \| ausente | solo `extended=true` | Passthrough del proveedor: type original, descripción completa, fees, netAmount, transferItems… |

### Semántica de outcomes y `detail`

| Outcome | `detail` | Significado para el agente |
|---------|----------|---------------------------|
| `ok` | `history_retrieved` | Historial recuperado; paginar con `next_offset` si `has_more` |
| `ok` | `no_movements` | Rango válido, sin movimientos en ninguna cuenta |
| `ok` | `no_movements_for_instrument` | Símbolo válido, sin movimientos de ese instrumento en el rango |
| `partial_failure` | `account_failed` | Algunas cuentas fallaron (ver `accounts_failed`); datos parciales en `movements` |
| `transient_failure` | `provider_unreachable` | Fallo transitorio en el primer intento; reintentar con backoff |
| `reauth_required` | `reauth_needed` | Mismo playbook: no reintentar, notificar al dueño |

### Errores de validación (error estándar de tool MCP, sin upcalls)

| Condición | Mensaje esperado |
|-----------|------------------|
| `start_date`/`end_date` ausente o mal formada | Indica el formato esperado `YYYY-MM-DD` |
| `end_date < start_date` | Nombra ambas fechas |
| Rango > 366 días | Indica el máximo de 1 año y sugiere dividir en consultas consecutivas |
| `end_date` futura | Indica que la fecha fin no puede ser futura |
| `symbol` presente, directorio no resuelve + 0 movimientos matchean | `instrument_not_found`, nombra el símbolo (validación dual) |
| `symbol` presente, directorio no resuelve + ≥1 movimiento matchea | `ok` con los movimientos que matchean (CURRENCY_USD, OCC no registrado) |
| `offset < 0` | Indica el valor mínimo |

Errores por cuenta (`accounts_failed[].detail`): `provider_error` ·
`transient` (mismo vocabulario de `get_open_positions`).

### Paginación

- **Límite**: máximo **50** movimientos por página.
- **Orden**: `occurred_at` ascendente; desempate por `account_hash` y `activityId`.
- **Continuación**: cuando `has_more=true`, repetir la misma consulta con `offset=<next_offset>`.
- **Invariante**: recorrer con `next_offset` entrega la unión completa sin duplicados ni omisiones, sobre el snapshot del historial al momento de la consulta.
- **Caveat de stateless**: la tool es stateless; si llegan movimientos nuevos entre páginas, el offset puede desplazarse. Paginar pronto.

### Garantías

- **Read-only**: no coloca órdenes ni mueve dinero.
- **Sin secretos**: ningún token/credencial en la salida; `account_hash` opaco.
- **Presupuesto**: ≤ 5 s p95 de latencia; ≤ 16 KB página default (50 movimientos, **incluyendo** `underlying_symbol` — caso peor verificado: 50 opciones); ≤ 64 KB extended.
- **Sin truncado silencioso**: tope upstream de 3000 manejado con bisección y deduplicación.
- **Sin reintentos internos** ante fallo transitorio (FR-010): el agente decide.
- **Determinista**: salida reproducible para la misma consulta sin cambios subyacentes.

### Caveat operacional

El proveedor puede devolver `200 OK + []` para `/transactions` cuando
la app registrada o la cuenta carecen de permiso de lectura de
transacciones (p. ej. cuenta sin thinkorswim habilitado). Desde la
respuesta es indistinguible de un vacío genuino: la tool reporta
`ok / no_movements`. Diagnóstico sugerido: si la cuenta muestra
actividad en schwab.com y varios rangos amplios devuelven
`no_movements` persistentemente, la causa probable es el permiso de
la app/cuenta — no datos.

A partir de la versión 0.5.0, la validación del filtro es **dual**
(FR-003): si el directorio de instrumentos no reconoce el símbolo
(p. ej. `CURRENCY_USD`, un símbolo OCC completo, un subyacente sin
entrada en el índice), la tool procede con el barrido igual y solo
reporta `instrument_not_found` si ningún movimiento matchea el filtro
en ninguna de las tres formas (M1 símbolo registrado, M2 root de opción,
M3 OCC completo). Esto reemplaza el comportamiento anterior donde
identificadores internos como `CURRENCY_USD` producían
`instrument_not_found` a pesar de tener movimientos.

### Referencia

- Contrato completo (base 006):
  [`specs/006-transaction-history/contracts/mcp-tools.md`](../specs/006-transaction-history/contracts/mcp-tools.md)
- Extensiones filtro/underlying_symbol (007):
  [`specs/007-underlying-symbol-filter/contracts/mcp-tools.md`](../specs/007-underlying-symbol-filter/contracts/mcp-tools.md)
- Data model:
  [`specs/006-transaction-history/data-model.md`](../specs/006-transaction-history/data-model.md) ·
  [`specs/007-underlying-symbol-filter/data-model.md`](../specs/007-underlying-symbol-filter/data-model.md)
- Eventos de auditoría:
  [`specs/006-transaction-history/contracts/events.md`](../specs/006-transaction-history/contracts/events.md)

---

## `get_option_chain` (tercera tool MCP)

Tercera herramienta MCP registrada por el servidor ``serve`` (feature
``008-extract-option-chain``). Recupera la cadena de opciones de un
subyacente en **una sola invocación**, con selección determinista de
strikes (ventana simétrica al dinero o ventana por delta) y filtro por
DTE. Solo lectura: no coloca órdenes ni mueve dinero.

### Invocación

```json
{"name": "get_option_chain", "arguments": {"symbol": "AAPL"}}
```

### Argumentos (input schema)

| Campo | Tipo | Default | Semántica |
|-------|------|---------|-----------|
| `symbol` | string | — (obligatorio) | Instrumento subyacente. No vacío, sin espacios internos; se pasa tal cual al proveedor. |
| `max_strikes` | int | `50` | ≥ 1. Strikes por lado del dinero (ATM incluido) por vencimiento: hasta `2 × max_strikes` filas. Con `delta_target` no reduce esa ventana. |
| `option_type` | enum `both` \| `calls` \| `puts` | `both` | Qué piernas incluye la respuesta. |
| `delta_target` | number \| null | `null` | Si presente: `0 < \|delta_target\| < 1`. Selecciona, por vencimiento y por tipo incluido, hasta 5 strikes alrededor del contrato con \|delta\| más cercana al objetivo. |
| `dte_max` | int \| null | `null` | Si presente: ≥ 1 (días de calendario). **`null` no significa "sin tope"**: aplica el tope vigente de 60 días (FR-005). |
| `extended` | bool | `false` | `false` (default): set curado compacto. `true`: agrega `provider` con el payload crudo del proveedor (patrón 003/006). |

### Output schema

Exactamente un objeto resultado por invocación. Estados de resultado
(`outcome` es el marcador explícito):

| `outcome` | `detail` | Significado para el agente |
|-----------|----------|---------------------------|
| `ok` | `chain_retrieved` | Cadena completa en `expirations` |
| `no_options_listed` | `no_options_listed` | El instrumento no tiene opciones listadas (resultado estructurado, **no** error) |
| `no_expirations_in_range` | `no_expirations_in_range: dte_max_effective=N excludes all expirations` | Hay vencimientos, pero el tope de DTE los excluye a todos; `expirations: []` |

Metadatos (`ok`):

| Campo | Tipo | Semántica |
|-------|------|-----------|
| `symbol` | string | Eco del instrumento consultado |
| `generated_at` | string ISO-8601 UTC | Momento de la consulta |
| `data_state` | enum cerrado | `realtime` · `delayed` (frescura reportada por la fuente) |
| `underlying_price` | float \| null | Precio vigente del subyacente |
| `filters` | objeto | Eco de la consulta efectiva: `{max_strikes, option_type, delta_target, dte_max_requested, dte_max_effective}`. `dte_max_effective` es 60 o el valor pedido — el agente siempre puede verificar el tope aplicado. |
| `contract_fields` | array de strings | Orden de columnas de cada array de pierna (23 columnas, ver abajo) |
| `expirations` | array | Vencimientos ordenados por `expiration_date` ascendente |

Cada vencimiento: `{expiration_date: "YYYY-MM-DD", dte: int,
atm_strike: float, strikes: [...]}` — `dte` en días de calendario;
`atm_strike` es el strike más cercano a `underlying_price` (empates: el
menor); `strikes` ordenados por strike ascendente.

#### Columnas de cada pierna (`contract_fields`, orden fijo)

```json
["bid", "ask", "last", "mark", "mark_change", "mark_pct_change",
 "high", "low", "open", "close", "volume", "open_interest",
 "iv", "delta", "gamma", "theta", "vega", "rho",
 "theoretical_value", "time_value", "multiplier", "trade_time",
 "deliverable_note"]
```

Forma **columnar** de cada fila de strike
(`{strike: float, call: [...], put: [...]}`):

- Cada pierna es un **array posicional** en el orden de `contract_fields`
  (declarado en la propia respuesta). El array puede traer menos
  elementos cuando los campos finales no están informados.
- Campo ausente en la fuente → `null` explícito en su columna
  (FR-007); nunca se inventan valores.
- `call`/`put` **ausente** (no `null`) cuando el tipo está excluido por
  `option_type` o el strike quedó fuera de la ventana de delta de ese
  tipo. La fila existe si al menos una pierna incluida la seleccionó.
- Las 5 griegas (`delta`, `gamma`, `theta`, `vega`, `rho`) están
  presentes por contrato o con `null` explícito (FR-006/FR-007).
- Redondeo determinista: precios/valores 2 decimales; griegas e IV 4
  decimales; `volume`/`open_interest`/`multiplier` sin redondeo;
  `trade_time` en ISO-8601 UTC.

#### Selección de strikes (resumen normativo)

- **Sin `delta_target`**: por vencimiento, hasta `max_strikes` strikes
  más cercanos por debajo y por encima de `atm_strike` (ATM incluido si
  existe) → ≤ `2 × max_strikes` filas por vencimiento.
- **Con `delta_target`**: por vencimiento y **por tipo incluido**,
  contrato con \|delta\| más cercana al objetivo + 2 contiguos por lado
  → hasta 5 strikes por tipo. `max_strikes` no interviene.
- **DTE**: solo vencimientos con `dte ≤ dte_max_effective`.

#### `extended=true`

Agrega `provider` con el payload crudo de la fuente (sin curado). Los
campos estructurales excluidos del formato curado (`skipBars`,
`isPitRanged`, `executable`, `settlementType`, `deliverables`) son
accesibles por esta vía.

### Tamaño esperado del payload (Presupuesto, Principio V)

**Esta tool es la de mayor payload de la superficie MCP** — presupuestala
antes de invocarla:

| Filtros | Tamaño esperado | Presupuesto normativo |
|---------|-----------------|-----------------------|
| Por defecto (cadena ancha: ~12 vencimientos × ≤ 100 filas de strike) | ~95–106k tokens | **≤ 110.000 tokens** |
| Con `delta_target` (subyacente típico: 10–12 vencimientos) | ~4,5–5k tokens | **≤ 8.000 tokens** |
| Con `delta_target` (cadena ancha live: 16 vencimientos, SPY/QQQ) | ~7,2–7,3k tokens | **≤ 8.000 tokens** |

> **Justificación registrada del crecimiento** (Principio V): los
> presupuestos se ajustaron el 2026-10-24 por decisión del usuario
> porque la medición honesta de las filas de ambas piernas con las 23
> columnas exigidas da ~80–88 tokens por fila, y el contenido de la
> respuesta está fijado por FR-002/FR-006 (no admite recorte sin violar
> la spec). **Re-baseline posterior (misma fecha, convergencia T023)**:
> el presupuesto de `delta_target` pasó de <6.000 a ≤8.000 porque la
> ventana de 5 strikes por tipo aplica **por vencimiento** (FR-004) y el
> volumen escala con los vencimientos que el tope de DTE deja pasar —
> cadenas live de 16 vencimientos (SPY/QQQ) miden ~7,2–7,3k tokens.
> La justificación completa del crecimiento está registrada en
> [`specs/008-extract-option-chain/plan.md`](../specs/008-extract-option-chain/plan.md)
> (Complexity Tracking).

**Consejo para el agente**: si solo necesitás un slice de la cadena,
preferí `delta_target`, `max_strikes` chico o `dte_max` bajo — reducen el
payload sin paginar (la tool no pagina). El límite FR-012 garantiza que
la respuesta nunca excede `expirations × types × strikes`.

### Errores de validación (error estándar de tool MCP, sin upcalls)

Todos ocurren **antes de cualquier upcall** (FR-008) con mensaje
accionable que nombra el parámetro y la restricción:

| Condición | Mensaje esperado |
|-----------|------------------|
| `symbol` vacío o solo espacios | Nombra `symbol` y la restricción de no vacío |
| `symbol` con espacios internos | Nombra `symbol` y la restricción |
| `max_strikes ≤ 0` | Nombra `max_strikes` y `>= 1` |
| `option_type` fuera del enum | Nombra `option_type` y los valores `both, calls, puts` |
| `\|delta_target\| ∉ (0,1)` | Nombra `delta_target` y `0 < \|delta_target\| < 1` |
| `dte_max ≤ 0` | Nombra `dte_max` y `>= 1` |

### Errores de fuente (mapeo estándar compartido)

| Condición | Comportamiento | Acción del agente |
|-----------|----------------|-------------------|
| Vencimiento entero sin datos (FR-013, `ChainDataError`) | **Error** estructurado que nombra la fecha y el tipo; **nunca** cadena parcial | Reintentar más tarde o reducir el alcance; no confiar en datos parciales |
| 401/403 | Re-autenticación requerida | Playbook de `renew` (`reauth_required`) |
| 5xx/408/429 | Fallo transitorio | Reintentar con backoff |
| Otro 4xx | El proveedor revisó y rechazó el pedido | Corregir parámetros; no reintentar idéntico |

La taxonomía de errores de proveedor es la **compartida** con
`get_open_positions` y `get_transaction_history`
(`provider.response_json`): ver sus secciones de error para el detalle
del manejo de `reauth_required` y fallos transitorios. FR-013: una
asimetría a nivel de **fecha** entre los mapas incluidos (un vencimiento
con datos en un tipo y sin datos en el otro) es cadena parcial → error;
la asimetría a nivel de **strike** es normal: ese strike conserva solo
la pierna existente y la fila omite la otra clave.

### Ejemplos

**Cadena por defecto** (todos los vencimientos ≤ 60 DTE, ambos tipos):

```json
{"name": "get_option_chain", "arguments": {"symbol": "AAPL"}}
```

Respuesta (truncada; el payload real es enorme):

```json
{
  "outcome": "ok",
  "detail": "chain_retrieved",
  "symbol": "AAPL",
  "generated_at": "2026-10-24T15:04:05+00:00",
  "data_state": "realtime",
  "underlying_price": 251.31,
  "filters": {"max_strikes": 50, "option_type": "both", "delta_target": null,
              "dte_max_requested": null, "dte_max_effective": 60},
  "contract_fields": ["bid", "ask", "...", "trade_time", "deliverable_note"],
  "expirations": [
    {"expiration_date": "2026-10-30", "dte": 6, "atm_strike": 251.0,
     "strikes": [
       {"strike": 250.0,
        "call": [25.10, 25.30, "...", 100, "2026-10-24T15:00:00+00:00", null],
        "put":  [6.05, 6.15, "...", 100, "2026-10-24T15:00:00+00:00", null]},
       "... (hasta 100 filas de strike, ordenadas por strike)"
     ]},
    "... (hasta ~12 vencimientos, ordenados por fecha)"
  ]
}
```

**Puts con delta objetivo** (ventana por tipo, ≤ 5 strikes/vencimiento):

```json
{"name": "get_option_chain", "arguments": {"symbol": "AAPL", "option_type": "puts", "delta_target": 0.20}}
```

Solo claves `put` por fila (sin `call`); por vencimiento, ≤ 5 strikes
alrededor del contrato con \|delta\| ≈ 0.20. Payload típico ~5k tokens.

**Límites explícitos** (slice corto):

```json
{"name": "get_option_chain", "arguments": {"symbol": "AAPL", "max_strikes": 10, "dte_max": 7}}
```

≤ 20 filas de strike por vencimiento (2 × 10, centradas en `atm_strike`),
solo vencimientos con `dte ≤ 7` (`filters.dte_max_effective == 7`). Si el
vencimiento más próximo vence más lejos → `no_expirations_in_range`
estructurado, no error genérico.

**Edge: instrumento sin opciones**:

```json
{"name": "get_option_chain", "arguments": {"symbol": "ZZZZZZ"}}
```

```json
{"outcome": "no_options_listed", "detail": "no_options_listed",
 "symbol": "ZZZZZZ", "generated_at": "2026-10-24T15:04:05+00:00"}
```

### Garantías

- **Una sola invocación devuelve la cadena completa** dentro de los
  límites pedidos (FR-011): sin paginación, sin `cursor`/`offset`/
  `has_more` en la respuesta.
- **Límites respetados al 100%** (`max_strikes`, `option_type`, DTE)
  (FR-012, SC-006); la respuesta nunca excede
  `expirations × types × strikes`.
- **Griegas completas**: las 5 griegas y el resto de `contract_fields`
  presentes por contrato o con `null` explícito (FR-006/FR-007).
- **Determinista**: selección de strikes reproducible para los mismos
  datos de entrada.
- **Read-only**, **sin estado entre invocaciones** y **sin credenciales**
  en la salida (credential safety de la constitución).
- **Presupuesto**: ≤ 5 s p95 de latencia por invocación.

### Referencia

- Contrato completo:
  [`specs/008-extract-option-chain/contracts/mcp-tools.md`](../specs/008-extract-option-chain/contracts/mcp-tools.md)
- Data model (orden de `contract_fields`, algoritmos de selección):
  [`specs/008-extract-option-chain/data-model.md`](../specs/008-extract-option-chain/data-model.md)
- Escenarios de uso (S1–S4):
  [`specs/008-extract-option-chain/quickstart.md`](../specs/008-extract-option-chain/quickstart.md)

---

## `schwab-mcp renew`

Renovación explícita del access credential usando el refresh credential
almacenado. Es la palanca de recuperación del agente cuando detecta
problemas de autenticación, independiente del camino automático.

```sh
uv run schwab-mcp renew
```

- **Argumentos**: ninguno. **stdin**: nunca se lee.
- **Requiere**: `SCHWAB_APP_KEY` y `SCHWAB_APP_SECRET` en el entorno.
- **Puede llamar a la API de Schwab** (solo si el token está dentro del
  margen preventivo de 61 s de expirar).
- **Presupuesto**: ≤ 10 s en el peor caso (3 intentos × 3 s de timeout
  HTTP + 2 esperas de 0.5 s entre reintentos).

### Comportamiento interno (en orden)

1. Carga y valida la configuración — falla **antes** de cualquier red.
2. Inspecciona el token store: ausente o corrupto → resultado
   `reauth_required` sin intentar renovar.
3. Lee la validez restante del store; si está por encima del margen →
   `not_needed` **sin llamar a la API** y sin invalidar nada.
4. Adquiere el lock de autorización (no bloqueante): ocupado → exit 6.
5. Ejecuta el refresh vía schwabdev con hasta **2 reintentos** ante
   fallos transitorios (red/proveedor). Los tokens válidos existentes
   **jamás se descartan** por un fallo transitorio.
6. Clasifica el resultado y emite **una línea JSON** en stdout.
7. Emite eventos de auditoría en stderr (`renew_start` → terminal).

### Salida (stdout, una línea JSON, ≤ 300 bytes)

```json
{"outcome": "renewed", "expires_in_seconds": 1800, "retryable": false, "detail": "access_renewed"}
```

| Campo | Tipo | Valores |
|-------|------|---------|
| `outcome` | enum cerrado | `renewed` · `not_needed` · `transient_failure` · `reauth_required` |
| `expires_in_seconds` | int ≥ 0 o `null` | Nueva vida útil del access token; `null` salvo en `renewed` |
| `retryable` | bool | `true` **solo** cuando `outcome == "transient_failure"` |
| `detail` | enum cerrado | `access_renewed` · `still_valid` · `provider_unreachable` · `refresh_rejected` · `reauth_needed` · `store_absent` · `store_corrupted` |

### Códigos de salida

| Código | `outcome` | Significado para el agente |
|--------|-----------|---------------------------|
| 0 | `renewed` o `not_needed` | Éxito: el token está renovado o seguía vigente |
| 2 | — | Configuración faltante o mal formada (acción del dueño) |
| 3 | `reauth_required` | Refresh credential rechazado o store ausente/corrupto: **re-autorización humana requerida** |
| 6 | — | Otra renovación o autorización ya está en curso |
| 7 | `transient_failure` | Fallo transitorio de red/proveedor: reintentar más tarde es seguro |

### Semántica de cada resultado

- **`renewed`** (`detail: access_renewed`): el access token se renovó;
  `expires_in_seconds` trae la nueva vida útil (~1800 s). Si el
  proveedor rotó el refresh token, ya fue persistido en el store.
- **`not_needed`** (`detail: still_valid`): el token sigue vigente por
  encima del margen; **no hubo llamada de red** y no se invalidó nada.
  Tratar como éxito, no como error.
- **`transient_failure`** (`detail: provider_unreachable`, `retryable:
  true`): red o proveedor no disponibles tras agotar los 2 reintentos.
  Los tokens vigentes siguen intactos. Reintentar más tarde.
- **`reauth_required`** (`detail: refresh_rejected` / `reauth_needed` /
  `store_absent` / `store_corrupted`): la renovación automática es
  **imposible**. El agente NO debe seguir reintentando: debe notificar
  al dueño para que corra `schwab-mcp auth` (único paso que requiere
  humano, por constraint del proveedor). El estado persiste hasta la
  re-autorización.

### Eventos en stderr (auditoría)

```text
2026-10-19T14:00:00Z+00:00 auth_event=renew_start outcome=initiated detail=explicit_command
2026-10-19T14:00:02Z+00:00 auth_event=renewal_success outcome=ok detail=access token renewed
```

Cada intento emite exactamente un `renew_start` seguido de exactamente
un evento terminal (`renewal_success` | `renewal_failure`). Nunca
contienen secretos.

---

## `schwab-mcp auth-status`

Consulta de salud de autenticación en **una sola request**: estado,
vida útil del access token y del refresh token, y si hace falta
re-autorización. **Lectura estrictamente local**: no llama a la API,
nunca dispara una renovación.

```sh
uv run schwab-mcp auth-status
```

- **Argumentos**: ninguno. **stdin**: nunca se lee.
- **Presupuesto**: ≤ 2 s (lectura local de SQLite).

### Salida (stdout, una línea JSON)

```json
{"state": "valid", "access_expires_in_seconds": 1520, "refresh_expires_in_seconds": 412000}
```

| Campo | Tipo | Valores |
|-------|------|---------|
| `state` | enum cerrado | `valid` · `reauth_required` |
| `access_expires_in_seconds` | int ≥ 0 o `null` | Segundos restantes del access token; `null` si desconocido |
| `refresh_expires_in_seconds` | int ≥ 0 o `null` | Segundos restantes del refresh token (~7 días de vida); `null` si desconocido |

### Códigos de salida

| Código | `state` | Significado |
|--------|---------|-------------|
| 0 | `valid` | Credenciales utilizables; los campos indican cuánto resta (aunque sea poco) |
| 2 | — | Configuración faltante o mal formada |
| 3 | `reauth_required` | Store ausente o corrupto → re-autorización humana requerida |

> Nota: el rechazo del refresh token por el proveedor (`refresh_rejected`)
> **no es detectable localmente** — se manifiesta al usar `renew` o el
> servidor. Si `auth-status` dice `valid` pero una operación falla con
> `reauth_required`, creéle a la operación.

### Uso recomendado

Es la verificación **barata y previa**: consultala antes de operaciones
largas, después de una pausa larga del agente, o ante el primer síntoma
de fallo de autenticación. No consume cuota del proveedor.

---

## `schwab-mcp serve` (servidor MCP)

Servidor MCP de tipo **stdio**, headless. Registra 3 tools
(``get_open_positions``, ``get_transaction_history`` y
``get_option_chain``) y es el proceso
que un cliente MCP (opencode, Claude Desktop, etc.) lanza y con el que
habla por stdio.

Al arrancar:

1. Valida la configuración (fail fast).
2. Verifica el token store: ausente/corrupto → sale con código
   específico **antes** del handshake MCP.
3. Renueva el access token si está vencido o dentro del margen
   (eventos `renew_start` → `renewal_success`/`renewal_failure` en
   stderr, trigger `margin_trigger`).
4. Valida el acceso real con `linked_accounts()` (< 5 s).
5. Conecta el transporte stdio y queda a la espera del cliente.

Si el refresh credential está rechazado, `serve` **no arranca**: sale
con mensaje claro pidiendo `schwab-mcp auth`. En ese estado, la
recuperación del agente es: notificar al dueño, y monitorear con
`auth-status` hasta que el estado vuelva a `valid` — a partir de ahí
todo funciona sin más acciones del agente.

En operación, la renovación automática es **transparente**: las
operaciones del agente no cambian de forma ni requieren pasos extra.

---

## `schwab-mcp auth` — solo para humanos

Flujo interactivo de autorización (browser + paste de URL). **Un agente
no debe intentar ejecutarlo**: requiere login humano en Schwab por
constraint del proveedor. Cuando un comando devuelve
`reauth_required`, la acción correcta del agente es notificar al dueño.

---

## Playbook de decisión para el agente

```text
Ante un fallo de autenticación en una operación:
1. uv run schwab-mcp auth-status        # diagnóstico barato, local
2. uv run schwab-mcp renew              # palanca de recuperación

Interpretación:
- exit 0 + renewed/not_needed  → continuar normalmente
- exit 7 + transient_failure   → reintentar luego (backoff); nada se perdió
- exit 6 (lock busy)           → esperar y reintentar
- exit 3 + reauth_required     → DETENER reintentos; notificar al dueño:
                                 "corré schwab-mcp auth"; monitorear con
                                 auth-status hasta state=valid
- exit 2 (configuración)       → acción del dueño (env del proceso)
```

## Referencias normativas

- Contrato de la tool MCP ``get_open_positions``:
  [specs/003-list-open-positions/contracts/mcp-tools.md](../specs/003-list-open-positions/contracts/mcp-tools.md)
- Data model de posiciones:
  [specs/003-list-open-positions/data-model.md](../specs/003-list-open-positions/data-model.md)
- Eventos de auditoría de posiciones:
  [specs/003-list-open-positions/contracts/events.md](../specs/003-list-open-positions/contracts/events.md)
- Contrato CLI completo:
  [specs/002-automated-token-renewal/contracts/cli.md](../specs/002-automated-token-renewal/contracts/cli.md)
- Contrato de eventos de renovación:
  [specs/002-automated-token-renewal/contracts/events.md](../specs/002-automated-token-renewal/contracts/events.md)
- Modelo de datos (enums cerrados):
  [specs/002-automated-token-renewal/data-model.md](../specs/002-automated-token-renewal/data-model.md)
- Contrato de la tool MCP ``get_transaction_history``:
  [specs/006-transaction-history/contracts/mcp-tools.md](../specs/006-transaction-history/contracts/mcp-tools.md)
- Data model de transacciones:
  [specs/006-transaction-history/data-model.md](../specs/006-transaction-history/data-model.md)
- Eventos de auditoría de transacciones:
  [specs/006-transaction-history/contracts/events.md](../specs/006-transaction-history/contracts/events.md)
- Contrato de la tool MCP ``get_option_chain``:
  [specs/008-extract-option-chain/contracts/mcp-tools.md](../specs/008-extract-option-chain/contracts/mcp-tools.md)
- Data model de la cadena de opciones:
  [specs/008-extract-option-chain/data-model.md](../specs/008-extract-option-chain/data-model.md)
- Guía de validación de la cadena de opciones:
  [specs/008-extract-option-chain/quickstart.md](../specs/008-extract-option-chain/quickstart.md)
- [Guía de uso](./uso.md) · [Guía de instalación](./instalacion.md)