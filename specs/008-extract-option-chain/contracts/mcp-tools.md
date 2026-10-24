# Contrato de tool MCP: `get_option_chain` (008)

Feature: 008-extract-option-chain | Date: 2026-10-23
Tool de solo lectura. No mueve dinero ni coloca órdenes. Transporte: stdio
exclusivo vía `schwab-mcp serve`.

## 1. Input schema

| Parámetro | Tipo | Default | Restricciones |
|---|---|---|---|
| `symbol` | string | — (obligatorio) | no vacío |
| `max_strikes` | int | `50` | ≥ 1; aplica por vencimiento, simétrico alrededor del strike al dinero |
| `option_type` | `"both"` \| `"calls"` \| `"puts"` | `"both"` | valor del enum |
| `delta_target` | number \| null | `null` | si presente: `0 < |delta| < 1` |
| `dte_max` | int \| null | `null` | si presente: ≥ 1; si `null`, tope vigente = 60 días |

Errores de validación (antes de cualquier upcall, FR-008): `symbol` vacío,
`max_strikes ≤ 0`, `option_type` fuera del enum, `|delta_target| ∉ (0,1)`,
`dte_max ≤ 0`.

## 2. Output schema (`ok`)

```json
{
  "symbol": "AAPL",
  "generated_at": "2026-10-23T15:04:05+00:00",
  "data_state": "realtime",
  "underlying_price": 251.31,
  "filters": {
    "max_strikes": 50,
    "option_type": "both",
    "delta_target": null,
    "dte_max_requested": null,
    "dte_max_effective": 60
  },
  "contract_fields": [
    "bid", "ask", "last", "mark", "mark_change", "mark_pct_change",
    "high", "low", "open", "close", "volume", "open_interest",
    "iv", "delta", "gamma", "theta", "vega", "rho",
    "theoretical_value", "time_value", "multiplier", "trade_time",
    "deliverable_note"
  ],
  "expirations": [
    {
      "expiration_date": "2026-10-30",
      "dte": 7,
      "atm_strike": 251.0,
      "strikes": [
        {
          "strike": 250.0,
          "call": [25.1, 25.3, 25.2, 25.2, 0.4, 0.5, 24.5, 23.0, 250, 310,
                   0.2105, 0.0312, -0.0842, 0.0621, -0.0118, 0.0,
                   25.2, 24.4, 100, "2026-10-23T15:00:00+00:00", null],
          "put":  [6.05, 6.15, 6.10, 6.10, -0.2, -1.1, 5.9, 5.5, 410, 920,
                   0.2101, -0.2894, 0.0310, -0.0841, 0.0620, -0.0118,
                   6.10, 0.4, 100, "2026-10-23T15:00:00+00:00", null]
        }
      ]
    }
  ]
}
```

Convenciones:

- Cada pierna es un **array posicional** cuyo orden es
  `contract_fields` (declarado en la propia respuesta); `null` = no
  informado por la fuente (FR-007). El array puede traer menos elementos
  que `contract_fields` cuando los campos finales no están informados.
- `call`/`put` ausentes: el tipo está excluido por `option_type`.
- Redondeo: precios 2 decimales; griegas e IV 4 decimales.
- `dte_max_effective`: 60 (default) o el valor pedido — el agente siempre
  puede verificar el tope aplicado.
- `extended=true` (parámetro adicional de la tool): agrega `provider`
  con el payload crudo de la fuente (patrón 003/006), sin curado. Los
  campos estructurales excluidos del formato curado (`skipBars`,
  `isPitRanged`, `executable`, `settlementType`, `deliverables`) son
  accesibles por esta vía.

## 3. Selección de strikes (resumen normativo)

- Sin `delta_target`: por vencimiento, hasta `max_strikes` strikes por
  lado del dinero (ATM incluido si existe).
- Con `delta_target`: por vencimiento y **por tipo incluido**, hasta 5
  strikes alrededor del contrato con delta más cercana al objetivo (valor
  absoluto); `max_strikes` no reduce esta ventana.
- DTE: solo vencimientos con `dte ≤ dte_max_effective`; DTE en días de
  calendario.

## 4. Resultados sin datos y errores

| Caso | Respuesta |
|---|---|
| Instrumento sin opciones listadas | resultado estructurado `no_options_listed` con `detail` (no error de transporte) |
| Tope de DTE excluye todos los vencimientos | resultado estructurado `no_expirations_in_range` con `detail` y tope vigente |
| Filtros inválidos | error de validación accionable antes de upcall |
| Fallo de fuente / vencimiento entero sin datos | error estructurado; **nunca** cadena parcial (FR-013) |
| 401/403, 5xx/408/429, 4xx | mapeo estándar de `provider.response_json` (taxonomía compartida con 003/006) |

## 5. Garantías

- Una sola invocación devuelve la cadena completa dentro de los límites
  pedidos; sin paginación (FR-011).
- Los límites (`max_strikes`, `option_type`, DTE) se respetan al 100%
  (FR-012, SC-006).
- Todas las griegas y valores técnicos de la lista `contract_fields`
  están presentes por contrato o con `null` explícito (FR-006/FR-007).
- Sin estado entre invocaciones; sin credenciales en outputs (credential
  safety de la constitución).

## 6. Presupuestos

- Latencia: ≤ 5 s p95 por invocación (alineado 006 y SC-001).
- Tokens (filtros por defecto): ≤ 75.000 para un subyacente típico
  (decisión de la clarificación 2026-10-24; justificación del crecimiento
  registrada en plan.md, Principio V); el esquema columnar compacta el
  formato. `docs/tools.md` refleja el tamaño esperado.
- Con `delta_target`: típicamente < 3k tokens.
- Test: `tests/performance/test_options_chain_budgets.py`.

## 7. Auditoría

- La tool no emite eventos de autenticación nuevos (no toca el ciclo de
  tokens); reutiliza el guard de serve existente.
- Los errores de validación y los resultados sin datos se reportan en el
  detalle estructurado de la respuesta, no en logs con contenido de
  mercado.
