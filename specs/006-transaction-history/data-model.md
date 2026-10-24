# Data Model: Account Transaction History (006)

Fecha: 2026-10-23. Derivado de [spec.md](./spec.md) y [research.md](./research.md).
Convenciones heredadas de los data models de 002/003: enums cerrados,
campos opcionales explícitos, sin secretos jamás.

## Enums cerrados

### `TransactionOutcome` (reusado de 003 — única definición)

| Valor | Significado |
|-------|-------------|
| `ok` | Consulta completa: todas las cuentas respondieron |
| `partial_failure` | Algunas cuentas fallaron, otras respondieron (ver `accounts_failed`) |
| `transient_failure` | Red/proveedor no disponibles en el primer intento |
| `reauth_required` | Credenciales rechazadas/store ausente o corrupto: re-autorización humana |

### `TransactionDetail` (enum cerrado de esta tool)

| Valor | Significado |
|-------|-------------|
| `history_retrieved` | Historial recuperado (≥ 1 movimiento) |
| `no_movements` | Sin movimientos en el rango para ninguna cuenta (rango válido) |
| `no_movements_for_instrument` | Filtro por símbolo activo, símbolo válido, sin movimientos en el rango |
| `account_failed` | ≥ 1 cuenta falló (solo con `partial_failure`) |
| `provider_unreachable` | Fallo transitorio (solo con `transient_failure`) |
| `reauth_needed` | Re-autorización requerida (solo con `reauth_required`) |

### `MovementCategory` (clarify Q3 + research D5)

| Valor | Tipos upstream mapeados (v1) |
|-------|------------------------------|
| `trade` | `TRADE` |
| `transfer` | `RECEIVE_AND_DELIVER`, `ACH_RECEIPT`, `ACH_DISBURSEMENT`, `CASH_RECEIPT`, `CASH_DISBURSEMENT`, `ELECTRONIC_FUND`, `WIRE_IN`, `WIRE_OUT` |
| `dividend_or_interest` | `DIVIDEND_OR_INTEREST` |
| `adjustment` | `JOURNAL`, `SMA_ADJUSTMENT` |
| `other` | `MEMORANDUM`, `MARGIN_CALL`, `MONEY_MARKET` |
| `interest` | *(reservado, sin mapeo en v1)* |
| `dividend` | *(reservado, sin mapeo en v1)* |
| `fee` | *(reservado, sin mapeo en v1)* |
| `corporate_action` | *(reservado, sin mapeo en v1)* |

Todo tipo upstream **no listado** (tipo nuevo del proveedor) → `other`
(fallback del spec FR-002), con el texto original en `extended`.

### `ProviderTransactionType` (espejo del SDK, nevera de la app)

`TRADE`, `RECEIVE_AND_DELIVER`, `DIVIDEND_OR_INTEREST`, `ACH_RECEIPT`,
`ACH_DISBURSEMENT`, `CASH_RECEIPT`, `CASH_DISBURSEMENT`,
`ELECTRONIC_FUND`, `WIRE_OUT`, `WIRE_IN`, `JOURNAL`, `MEMORANDUM`,
`MARGIN_CALL`, `MONEY_MARKET`, `SMA_ADJUSTMENT`.

La tool **siempre consulta con la lista completa** separada por comas
(research D2) — no hay parámetro de filtrado por tipo en v1: el
default es "todo" (FR-002).

## Entidades

### `HistoryQuery` (request)

| Campo | Tipo | Default | Regla de validación |
|-------|------|---------|---------------------|
| `start_date` | string | obligatorio | `YYYY-MM-DD` parseable; fecha real |
| `end_date` | string | obligatorio | `YYYY-MM-DD` parseable; ≥ `start_date`; ≤ hoy (America/New_York) |
| `symbol` | string \| ausente | sin filtro | no vacío; validado contra `instruments` (research D6) |
| `extended` | bool | `false` | — |
| `offset` | int | `0` | ≥ 0 |

Errores de validación (FR-004) → error estándar de tool MCP con mensaje
accionable, **antes** de cualquier upcall (incluida `linked_accounts`):
fecha mal formada; `end_date < start_date`; rango > 1 año (366 días
calendario); `end_date` futura; `symbol` vacío.

Semántica de rango: ambos bordes **inclusivos**, interpretados en
America/New_York (clarify Q2): `startDate` = 00:00:00 NY del día inicio,
`endDate` = final del día fin (23:59:59.999 NY), offset real del día
(DST) vía `zoneinfo`.

### `MovementEntry` (movimiento individual)

| Campo | Tipo | Presencia | Semántica |
|-------|------|-----------|-----------|
| `account_hash` | string | siempre | Identificador opaco de la cuenta (nunca número de cuenta) |
| `occurred_at` | string ISO-8601 | siempre | Fecha/hora del movimiento (del payload; si el proveedor solo da fecha, mediodía NY documentado) |
| `category` | `MovementCategory` | siempre | Categoría normalizada (enum cerrado) |
| `description` | string | siempre | Descripción legible, **truncada a 80 caracteres** en default (texto completo en `extended`) |
| `amount` | float | siempre | Efecto monetario principal tal como lo reporta el proveedor (signo del proveedor, no reinterpretado) |
| `currency` | string | siempre | Moneda del movimiento: usar el campo de moneda del proveedor **si lo expone**; si no, `"USD"` (accounts USD-denominated, research R10). Nunca convertir. |
| `symbol` | string \| ausente | solo si hay instrumento | Símbolo del instrumento referenciado; en trades multi-leg se cura el primer instrumento no-divisa de `transferItems` (las patas de fees `CURRENCY_USD` van primero en el payload real) |
| `instrument_type` | string \| ausente | solo si hay instrumento | Tipo de activo (`EQUITY`, `ETF`, `OPTION`, …) |
| `extended` | object \| ausente | solo `extended=true` | Passthrough del ítem del proveedor: `type` original, `description` completa, `fees`, `commissions`, `netAmount`, `settlementDate`, `transferItems` (subset relevante), `activityId` |

Curaduría default (FR-007): solo los campos de la tabla sin `extended`.
Sin secretos; `account_hash` opaco.

### `TransactionsResult` (response)

| Campo | Tipo | Presencia | Semántica |
|-------|------|-----------|-----------|
| `outcome` | `TransactionOutcome` | siempre | Ver enum |
| `detail` | `TransactionDetail` | siempre | Ver enum |
| `retryable` | bool | siempre | `true` solo cuando `outcome == "transient_failure"` |
| `retrieved_at` | string ISO-8601 UTC | siempre | Momento de recuperación del payload |
| `total_count` | int | `outcome=ok` | Total de movimientos del rango completo (todas las páginas) |
| `movements` | array de `MovementEntry` | `outcome=ok` | Página actual, orden cronológico ascendente (desempate `account_hash`, `activityId`); `[]` válido solo con `no_movements`/`no_movements_for_instrument` |
| `returned` | int | `outcome=ok` | Cantidad de movimientos en esta página (≤ 50) |
| `has_more` | bool | `outcome=ok` | `true` si quedan movimientos por entregar |
| `next_offset` | int \| ausente | solo `has_more=true` | Offset para la siguiente página |
| `accounts_failed` | array \| ausente | solo `partial_failure` | `[{"account_hash": str, "detail": "provider_error"|"transient"}]` |
| `offset_echo` | int | `outcome=ok` | Offset efectivo aplicado a esta página |

Invariante de paginación (SC-006): recorrer con `next_offset` entrega la
unión completa sin duplicados y sin omisiones, sobre el snapshot del
historial al momento de la consulta.

## Reglas de validación cruzada (validadas por el modelo)

1. `outcome=ok` + `movements=[]` ⇔ `detail ∈ {no_movements,
   no_movements_for_instrument}`.
2. `has_more=true` ⇒ `next_offset` presente y `returned == 50`.
3. `next_offset` presente ⇒ `has_more=true`.
4. `accounts_failed` presente ⇔ `outcome=partial_failure`.
5. `retryable=true` ⇔ `outcome=transient_failure`.
6. `detail ∈ {no_movements_for_instrument}` ⇒ `symbol` estaba presente
   en el request.
7. `retrieved_at` ≥ `occurred_at` de todo movimiento entregado.
8. Ningún campo contiene tokens, app keys, secretos ni URLs de
   autorización (test de no-secretos lo assertion).

## Ciclo de vida / estado

Sin estado persistente: la tool es stateless y sin caché entre requests
(mismo criterio que 003/005). El único "estado" es el `offset` que el
agente reenvía.
