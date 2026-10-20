# Contract: MCP Tool `get_open_positions`

**Feature**: `003-list-open-positions` | **Date**: 2026-10-20
**Superficie**: primera tool registrada por `schwab-mcp serve`
(FR-001, decisión Q1 del clarify: tool MCP real, no comando CLI).

## Invocación

```json
{
  "name": "get_open_positions",
  "arguments": {}
}
```

### Argumentos (input schema)

| Campo | Tipo | Default | Semántica |
|-------|------|---------|-----------|
| `extended` | bool | `false` | `false` (default): solo el set curado (compacto). `true`: cada posición agrega el objeto `extended` con el passthrough completo del proveedor (FR-003a). El default NUNCA incluye campos extendidos. |

Sin otros parámetros en v1: la consulta cubre siempre **todas** las
cuentas vinculadas (FR-004); no hay filtro por cuenta (KISS).

## Resultado (structured output)

Exactamente un objeto JSON por invocación (FR-002), esquema en
[data-model.md §2](../data-model.md). Campos:

| Campo | Tipo | Valores |
|-------|------|---------|
| `outcome` | enum cerrado | `ok` · `partial_failure` · `transient_failure` · `reauth_required` |
| `positions` | array | Entradas `PositionEntry`; `[]` válido solo con `outcome: "ok"` |
| `accounts_failed` | array \| ausente | Solo `partial_failure`: `[{account_hash, detail}]`, `detail ∈ {provider_error, transient}` |
| `retryable` | bool | `true` solo cuando `outcome == "transient_failure"` |
| `detail` | enum cerrado | `data_received` · `no_positions` · `account_failed` · `provider_unreachable` · `reauth_needed` · `store_absent` · `store_corrupted` |
| `retrieved_at` | string ISO-8601 UTC | Momento de recuperación del payload del proveedor |

### `PositionEntry` (set curado, FR-003)

```json
{
  "account_hash": "hash-opaco-de-cuenta",
  "symbol": "SPY",
  "instrument_type": "EQUITY",
  "description": "SPDR S&P 500 ETF Trust",
  "quantity": 10.0,
  "average_price": 580.25,
  "market_value": 5910.0,
  "unrealized_pl": 107.5,
  "price_timestamp": "2026-10-20T14:03:11+00:00"
}
```

Para `OPTION` se agregan (obligatorios, nunca `null`):
`underlying_symbol`, `put_call` (`PUT`|`CALL`), `strike_price`,
`expiration_date`. Con `extended=true`, cada entrada agrega `"extended": {...}`
passthrough del proveedor (claves opacas pero estables; incluye
`price_timestamp` a nivel entrada igual).

### Semántica de cada outcome

- **`ok`** (`detail: data_received` | `no_positions`): consulta
  completa. `no_positions` con `positions: []` significa "no hay
  tenencias", no un error (FR-005/SC-006).
- **`partial_failure`** (`detail: account_failed`): algunas cuentas
  respondieron, otras no (FR-010). `positions` trae las tenencias de las
  cuentas exitosas; `accounts_failed` identifica las que fallaron y por
  qué. El agente puede decidir reintentar.
- **`transient_failure`** (`detail: provider_unreachable`, `retryable:
  true`): primer intento fallido por red/proveedor; **no hay reintentos
  internos** (FR-007). Reintentar después es seguro; nada se corrompe.
- **`reauth_required`** (`detail: reauth_needed` | `store_absent` |
  `store_corrupted`): mismas reglas que el playbook existente — el
  agente NO debe reintentar; notificar al dueño para `schwab-mcp auth`
  y monitorear con `auth-status` hasta `state: valid`.

### Freshness de precios (FR-012)

El precio usado por `market_value`/`unrealized_pl` es el calculado por
el proveedor al generar el payload: en vivo durante el horario de
mercado, último cierre fuera de horario. `price_timestamp` /
`retrieved_at` marcan cuándo se recuperó ese payload. El MCP no
recalcula ni interpola precios (research D4).

## Garantías transversales

- **Read-only**: la tool no coloca órdenes ni mueve dinero; sin estado
  persistido propio.
- **Sin secretos**: cero tokens/credenciales/URLs en el resultado ni en
  eventos (verificado por test).
- **Órdenes pendientes fuera de alcance** (FR-015): solo tenencias
  efectivas con cantidad con signo ≠ 0; cantidades cero se omiten.
- **Sin estrategias agregadas**: cada contract es una entrada separada
  (strangle/condor/roll = N entradas); agrupar es del consumidor.

## Presupuestos (Constitution V)

- **Latencia**: ≤ 5 s por invocación bajo red normal (SC-002); un solo
  upstream call (`account_details_all(fields=positions)`).
- **Payload default**: ≤ 8 KB para 50 posiciones curadas (~2 000 tokens).
- **Payload extended**: ≤ 16 KB para 50 posiciones. Crecimiento de
  cualquiera de los dos requiere justificación registrada en el change.
- **Excedencia** (más de 50 posiciones o payload por encima del
  presupuesto): la respuesta NUNCA se trunca ni se omite posiciones
  silenciosamente (un recorte silencioso violaría FR-001/FR-010: el
  agente creería tener el cuadro completo). Estrategia determinística:
  la respuesta crece y el test de presupuesto (T015) falla, lo que
  obliga a una justificación registrada (Constitution V) o a una
  decisión explícita de paginación en un feature futuro. En v1 no hay
  paginación (KISS): carteras por encima del presupuesto son un hecho
  visible y medible, no un comportamiento oculto.
- Test obligatorio: `tests/performance/test_positions_budgets.py`
  (marcador `performance`).

## Errores MCP

Fallos clasificados como arriba se devuelven como **resultado
estructurado** (no como error de protocolo MCP): el agente los lee y
decide. Solo un fallo interno no clasificable se propaga como error MCP
con mensaje sin secretos.
