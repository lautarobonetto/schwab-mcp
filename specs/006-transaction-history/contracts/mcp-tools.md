# Contrato MCP Tool: `get_transaction_history` (006)

Referencia normativa de la cuarta tool MCP del servidor. Complementa
`docs/tools.md` (que la documentará para el agente). Modelo de datos:
[data-model.md](../data-model.md). Eventos: [events.md](events.md).

## Invocación

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

## Argumentos (input schema)

| Campo | Tipo | Default | Semántica |
|-------|------|---------|-----------|
| `start_date` | string | obligatorio | Fecha inicio del rango, `YYYY-MM-DD`. Borde **inclusivo**, interpretado en America/New_York. |
| `end_date` | string | obligatorio | Fecha fin del rango, `YYYY-MM-DD`. Borde **inclusivo**; no puede ser futura. |
| `symbol` | string \| ausente | sin filtro | Si está presente: solo movimientos de ese instrumento. Se valida contra el proveedor antes de consultar el historial. |
| `extended` | bool | `false` | `false` (default): set curado compacto. `true`: cada movimiento agrega `extended` con el passthrough del proveedor (type original, descripción completa, fees, netAmount, transferItems…). |
| `offset` | int | `0` | Continuación de paginación: repetir la misma consulta con el `next_offset` recibido. |

Ventana máxima: **1 año** (366 días calendario) entre `start_date` y
`end_date` (clarify Q1). Rangos mayores → error de validación que indica
el máximo y sugiere dividir la consulta.

## Output schema

Exactamente un objeto `TransactionsResult` por invocación (ver
[data-model.md](../data-model.md) para el esquema completo de
`MovementEntry`):

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
    }
  ]
}
```

## Semántica de outcomes y `detail`

| Outcome | `detail` | Significado para el agente |
|---------|----------|---------------------------|
| `ok` | `history_retrieved` | Historial recuperado; paginar con `next_offset` si `has_more`. |
| `ok` | `no_movements` | Rango válido, sin movimientos en ninguna cuenta. |
| `ok` | `no_movements_for_instrument` | Símbolo válido, sin movimientos de ese instrumento en el rango. |
| `partial_failure` | `account_failed` | Algunas cuentas fallaron (ver `accounts_failed`); los datos del resto son válidos. Evaluar reintento de la consulta completa. |
| `transient_failure` | `provider_unreachable` | Fallo transitorio en el primer intento; sin reintentos internos. Reintentar después es seguro. |
| `reauth_required` | `reauth_needed` | Mismo playbook de las demás tools: no reintentar; notificar al dueño (`schwab-mcp auth`). |

## Errores de validación (error estándar de tool MCP, sin upcalls)

| Condición | Mensaje esperado |
|-----------|------------------|
| `start_date`/`end_date` ausente o mal formada | Indica el formato esperado `YYYY-MM-DD` |
| `end_date < start_date` | Nombra ambas fechas |
| Rango > 366 días | Indica el máximo de 1 año y sugiere dividir en consultas consecutivas |
| `end_date` futura | Indica que la fecha fin no puede ser futura |
| `symbol` presente pero inexistente/typo | `instrument_not_found`, nombra el símbolo |
| `offset < 0` | Indica el valor mínimo |

Errores por cuenta (`accounts_failed[].detail`): `provider_error` ·
`transient` (mismo vocabulario de `get_open_positions`).

## Paginación

- Orden determinista: `occurred_at` ascendente; desempate por
  `account_hash` y `activityId`.
- Página: máx **50** movimientos (clarify Q4). `has_more=true` siempre
  acompaña `next_offset`; la última página no trae `next_offset`.
- Recorrido completo (SC-006): cero duplicados, cero omisiones sobre el
  snapshot de la consulta.
- Caveat: la tool es stateless; si llegan movimientos nuevos entre
  página y página, el offset puede desplazarse. Paginar pronto.

## Upcalls

| Paso | Llamada | Cuándo |
|------|---------|--------|
| 1 | `linked_accounts()` | Siempre (1 call) |
| 2 | `instruments(..., symbol-search)` | Solo si `symbol` presente (1 call) |
| 3 | `transactions(accountHash, startDate, endDate, types=<todos>, symbol?)` | 1 por cuenta; +bisección solo si una respuesta llega con el tope de 3000 (research D3) |

## Garantías

- **Read-only**: no coloca órdenes ni mueve dinero.
- **Sin secretos**: ningún token/credencial en la salida ni eventos;
  `account_hash` opaco, nunca número de cuenta.
- **Presupuesto**: ≤ 5 s p95 de latencia (SC-001); ≤ 16 KB página
  default (50 movimientos, SC-003); ≤ 64 KB extended (declarado).
- **Sin truncado silencioso**: tope upstream de 3000 manejado con split
  por bisección y deduplicación por `(account_hash, activityId)`.
- **Sin reintentos internos** ante fallo transitorio: el agente decide
  (FR-010).

## Caveat operacional (documentado, no es error de la tool)

El proveedor puede devolver `200 OK + []` para `/transactions` cuando la
app registrada o la cuenta carecen de permiso de lectura de
transacciones (p. ej. cuenta sin thinkorswim habilitado; evidencia
regress#125). Desde la respuesta es indistinguible de un vacío genuino:
la tool reporta `ok / no_movements`. Diagnóstico sugerido para el
agente: si la cuenta muestra actividad en schwab.com y varios rangos
amplios devuelven `no_movements` persistentemente, la causa probable es
el permiso de la app/cuenta — no datos.
