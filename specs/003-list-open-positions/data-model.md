# Data Model: List Open Positions

**Feature**: `003-list-open-positions` | **Date**: 2026-10-20

No hay persistencia nueva: el modelo es **efímero** (resultado de una
consulta snapshot) más **eventos de auditoría** append-only en el canal
auxiliar (contrato en `contracts/events.md`). El token store SQLite de
schwabdev queda intacto (solo lectura implícita vía el client).

## Entities

### 1. PositionEntry (ephemeral; una entrada por (cuenta, instrumento))

Unidad de FR-003/FR-013. Serializada dentro del resultado de la tool.

| Field | Type | Validation | Notes |
|-------|------|------------|-------|
| account_hash | str | non-empty, opaco | Cuenta propietaria; nunca el número crudo (research D3) |
| symbol | str | non-empty | `instrument.symbol` del proveedor |
| instrument_type | enum str | `EQUITY` \| `OPTION` \| `MUTUAL_FUND` \| `FIXED_INCOME` \| `CASH_EQUIVALENT` | `instrument.assetType`; vocabulario cerrado del proveedor |
| description | str | non-empty | Descripción humana del instrumento |
| quantity | float | ≠ 0, con signo | `longQuantity − shortQuantity`; largo positivo, corto negativo (FR-013) |
| average_price | float | ≥ 0 | Costo promedio de adquisición (`averagePrice`) |
| market_value | float | signo consistente con quantity | Valor de mercado actual (`marketValue`) |
| unrealized_pl | float | — | Derivado (research D3); negativo = pérdida |
| price_timestamp | str (ISO-8601 UTC) | parseable | Momento de recuperación del payload; el valor es el calculado por el proveedor (FR-012, research D4) |
| underlying_symbol | str \| ausente | — | Solo `OPTION` (research D3) |
| put_call | enum str \| ausente | `PUT` \| `CALL` | Solo `OPTION` |
| strike_price | float \| ausente | > 0 | Solo `OPTION` |
| expiration_date | str \| ausente | — | Solo `OPTION` |

Rules:
- Identidad: `(account_hash, symbol)` única en el resultado (FR-013);
  lotes del mismo instrumento consolidados con `average_price` promedio.
- Cantidad cero ⇒ la entrada **no existe** en el resultado (FR-015, D5).
- Campos de opción presentes ⇔ `instrument_type == "OPTION"`; para otros
  tipos se omiten (nunca `null` — token budget, research D9).

### 2. PositionsResult (ephemeral; resultado único de la tool, FR-002)

Un solo objeto estructurado por invocación; auto-clasificante (FR-007).

| Field | Type | Validation | Notes |
|-------|------|------------|-------|
| outcome | enum str | `ok` \| `partial_failure` \| `transient_failure` \| `reauth_required` | Clase única (SC-004) |
| positions | list[PositionEntry] | vacía solo permitida si `outcome == "ok"` | Lista completa de tenencias efectivas (FR-001); `[]` = sin posiciones, válido (FR-005) |
| accounts_failed | list[{account_hash, detail}] \| ausente | — | Solo en `partial_failure` (FR-010): cuenta + motivo fijo (`provider_error` \| `transient`) |
| retryable | bool | — | `true` solo con `outcome == "transient_failure"` (D6) |
| detail | enum str | vocabulario cerrado | `data_received` · `no_positions` · `account_failed` · `provider_unreachable` · `reauth_needed` · `store_absent` · `store_corrupted` |
| retrieved_at | str (ISO-8601 UTC) | parseable | Timestamp de la recuperación; igual al `price_timestamp` de cada entrada |

Rules:
- Ningún campo contiene secretos (FR-008); el filtro de redacción de
  `log.py` es defensa adicional.
- `outcome: ok` + `positions: []` es éxito, no error (FR-005/SC-006).
- `partial_failure` es un éxito parcial: las posiciones de las cuentas
  que respondieron SÍ vienen en `positions` (FR-010).

### 3. ExtendedPositionFields (ephemeral; FR-003a, solo con `extended=true`)

Passthrough sin interpretación de los campos restantes del proveedor
(`cusip`, `settledLongQuantity`, `settledShortQuantity`,
`currentDayProfitLoss`, `maintenanceRequirement`, `instrument` completo,
etc.). Sin schema propio: claves tal como las nombra el proveedor,
documentadas como opacas pero estables por versión de API. Con
`extended=true`, cada `PositionEntry` agrega el objeto `extended` con
este contenido (y el presupuesto de payload declarado crece — research D9).

### 4. PositionsAuditRecord (audit event line; patrón de 002)

`positions_query_start` → exactamente un terminal
(`positions_query_success` | `positions_query_failure`), sin secretos,
canal auxiliar. Vocabulario y formato en `contracts/events.md`.

### 5. TokenSet (persisted; UNCHANGED — no duplicar)

Propiedad de schwabdev; esta feature solo lo consume a través del client
existentemente instanciado en `server.py`. Ver
`specs/002-automated-token-renewal/data-model.md` §4.

## State transitions

No hay estados propios de esta feature (snapshot sin persistencia). Las
transiciones relevantes son las del estado de autenticación (002), que
determinan el `outcome` observable:

```text
credentials válidas          → outcome ok | partial_failure | transient_failure
refresh rechazado / store    → outcome reauth_required
ausente/corrupto
red/proveedor caído          → outcome transient_failure (retryable: true)
```

Las mismas reglas de entrada (`store_absent`, `store_corrupted`,
re-auth) que rigen para `serve` aplican acá: la tool nunca dispara
autorización interactiva (guard hook de 001/002).
