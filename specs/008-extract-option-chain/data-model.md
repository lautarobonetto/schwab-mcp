# Data Model: Extracción de Cadena de Opciones con Filtros

Feature: 008-extract-option-chain | Date: 2026-10-23

## 1. Entidades

### OptionChainQuery (input validado)

Parámetros de la invocación, validados antes de cualquier upcall.

| Campo | Tipo | Default | Validación |
|---|---|---|---|
| `symbol` | string | — (obligatorio) | no vacío, sin espacios internos; se pasa tal cual al proveedor (el matching/normalización es del proveedor) |
| `max_strikes` | int | `50` | ≥ 1 |
| `option_type` | enum `both` \| `calls` \| `puts` | `both` | valor del enum |
| `delta_target` | float \| null | `null` | si presente: `0 < |delta_target| < 1` |
| `dte_max` | int \| null | `null` | si presente: ≥ 1; si ausente, tope vigente = 60 |

Semántica de defaults: `dte_max=null` NO significa "sin tope" — significa
"no elijo DTE" y aplica el tope por defecto de 60 días (FR-005).

### ChainMeta (metadatos de la respuesta)

| Campo | Tipo | Semántica |
|---|---|---|
| `symbol` | string | instrumento consultado (eco) |
| `generated_at` | string ISO-8601 UTC | momento de la consulta |
| `data_state` | `realtime` \| `delayed` | frescura reportada por la fuente |
| `underlying_price` | float \| null | precio vigente del subyacente (`includeUnderlyingQuote`) |
| `filters` | objeto | eco de la consulta efectiva (incluye `dte_max_effective`: 60 o el valor pedido) |
| `contract_fields` | lista de strings | orden de columnas de cada array de pierna (ver §2) |

### Expiration (vencimiento)

| Campo | Tipo | Semántica |
|---|---|---|
| `expiration_date` | string `YYYY-MM-DD` | fecha de vencimiento (clave de `*ExpDateMap`) |
| `dte` | int | días de calendario desde hoy hasta el vencimiento |
| `atm_strike` | float | strike más cercano a `underlying_price` (centro de la ventana de strikes; referencia de análisis) |
| `strikes` | lista de StrikeRow | filas ordenadas por strike ascendente |

### StrikeRow (fila por strike)

| Campo | Tipo | Semántica |
|---|---|---|
| `strike` | float | precio de ejercicio |
| `call` | array de números/null \| ausente | pierna CALL en orden `contract_fields`; ausente si el filtro excluye CALLs |
| `put` | array de números/null \| ausente | pierna PUT en orden `contract_fields`; ausente si el filtro excluye PUTs |

Reglas: la pierna existe solo si el tipo está incluido por
`option_type`; el strike aparece si al menos una pierna incluida existe
en el payload.

### ContractFields (columnas de cada pierna — orden fijo)

`bid`, `ask`, `last`, `mark`, `mark_change`, `mark_pct_change`,
`high`, `low`, `open`, `close`, `volume`, `open_interest`,
`iv`, `delta`, `gamma`, `theta`, `vega`, `rho`,
`theoretical_value`, `time_value`, `multiplier`, `trade_time`,
`deliverable_note`

- Griegas completas: delta, gamma, theta, vega, rho (FR-006).
- Redondeo determinista: precios/valores a 2 decimales; griegas e IV a 4
  decimales; sin redondeo para `volume`/`open_interest`/`multiplier`
  (enteros).
- Campo ausente en la fuente → `null` en su columna (FR-007).
- Campos estructurales excluidos del formato curado (disponibles vía
  `extended=true`): ver research R6.

## 2. Relaciones

```
OptionChainQuery --valida--> upcall proveedor
ChainMeta 1 --N Expiration
Expiration 1 --N StrikeRow
StrikeRow 0..1 pierna call + 0..1 pierna put
```

- Cada `Expiration` proviene de una clave de `callExpDateMap` /
  `putExpDateMap` del payload (unión de ambas claves por fecha).
- `atm_strike` se calcula por vencimiento contra `underlying_price`.
- La ventana de strikes (sin delta) es simétrica alrededor de
  `atm_strike`; la ventana por delta es por tipo (clarificación 2026-10-23).

## 3. Algoritmos de selección (deterministas)

- **Ventana por strikes (sin delta)**: por vencimiento, los
  `max_strikes` strikes más cercanos por debajo y por encima de
  `atm_strike` (incluido el ATM si existe); si hay menos, todos.
- **Ventana por delta**: por vencimiento y por tipo incluido: contrato
  con delta más cercana a `delta_target` (valor absoluto) + 2 contiguos
  de cada lado → hasta 5 (o los disponibles alrededor). No interactúa con
  `max_strikes` (clarificación 2026-10-23).
- **Filtro de DTE**: `dte ≤ dte_max_effective`; el filtrado también ocurre
  en origen (`fromDate`/`toDate`) y el post-filtro corrige bordes.

## 4. Validación y estados de resultado

Estados de resultado (no hay ciclo de vida: tool sin estado):

| Estado | Cuándo | Forma |
|---|---|---|
| `ok` | cadena devuelta | ChainMeta + expirations |
| `no_options_listed` | la fuente no reporta mapas de expiración para el símbolo | resultado estructurado con `detail` (FR-009) |
| `no_expirations_in_range` | tope de DTE excluye todos los vencimientos | resultado estructurado con `detail` y tope vigente (FR-009) |
| error de validación | filtros inválidos (§1) | error accionable antes de upcall (FR-008) |
| error de transporte | fallo de fuente / vencimiento entero sin datos | error estructurado sin cadena parcial (FR-013) |

## 5. Volumen esperado (para tests de presupuesto)

- Fila de strike con ambas piernas: ~55–75 tokens (columnas, redondeo).
- Subyacente típico con defaults (50/lado → 100 strikes × ~12
  vencimientos): ~600–1200 filas → **~45–75k tokens estimados**;
  presupuesto normativo fijado en **≤75.000 tokens** con defaults
  (clarificación 2026-10-24, SC-002, justificación en plan.md) y
  **<3.000** con `delta_target`. El test de presupuesto usa fixture
  representativo y mide la serialización real.
- Con `delta_target` activo: ~5 strikes × 2 tipos × N vencimientos →
  típicamente < 3k tokens.
