# Data Model: Underlying-Aware Symbol Filter and Underlying Reference

Feature: 007-underlying-symbol-filter | Date: 2026-10-24
Base: data-model de `specs/006-transaction-history/data-model.md` (la
tool y sus modelos existen; este feature los **extiende** sin reemplazar
nada). Los enums de outcome/detail y todas las reglas cruzadas 1–8 de 006
siguen vigentes sin cambios.

## §1. MovementEntry (extendido)

Campos existentes de 006 sin cambios: `account_hash`, `occurred_at`,
`category`, `description` (truncada a 80 en curado), `amount`, `currency`,
`symbol` (solo con instrumento), `instrument_type` (solo con
instrumento), `extended` (solo con `extended=true`).

### Campo nuevo

| Campo | Tipo | Presencia | Semántica |
|-------|------|-----------|-----------|
| `underlying_symbol` | string | **solo** movimientos cuya categoría de instrumento es opción (`instrument_type == "OPTION"` y símbolo OCC identificable) | Identificador del subyacente: la porción previa a los últimos 15 caracteres del símbolo OCC registrado, sin padding (`"AMD   261120P00630000"` → `"AMD"`). Reportado tal como la fuente lo registra (tras strip). Ausente (no `null`) para no-opciones y para opciones cuyo símbolo no tiene codificación OCC identificable |

Reglas:

0. **Terminología**: `underlying_symbol` (el campo del output) materializa
   la "referencia al subyacente" definida en el spec (US2/FR-004); su
   valor se deriva del **root** del símbolo OCC — el identificador del
   subyacente al inicio del símbolo de opción estándar. Tres nombres, un
   solo concepto.

1. **R1 — Derivación**: `root = symbol[:-15].strip()` cuando los últimos
   15 caracteres matchean el patrón OCC (`YYMMDD` dígitos + `C`/`P` +
   8 dígitos). Anclaje derecho, independiente del padding del root
   (mismo conocimiento verificado en vivo en el fix de posiciones).
2. **R2 — Presencia**: `underlying_symbol` presente ⇔ el movimiento es
   de opción Y su root es identificable. Nunca `null` explícito en el
   JSON (mismo patrón `exclude_none` de `symbol`/`instrument_type`).
3. **R3 — No-opciones sin cambios**: transfers, intereses, ajustes y
   trades de acciones/efectivo NO llevan el campo (output idéntico a 006
   para esos movimientos).
4. **R4 — Case**: se reporta tal cual la fuente (mayúsculas en la
   práctica); la insensibilidad a mayúsculas aplica solo al matching del
   filtro, nunca a la salida.

## §2. HistoryQuery — semántica extendida del filtro `symbol`

Parámetros de entrada sin cambios: `start_date`, `end_date`, `symbol`
(opcional), `extended`, `offset`.

### Regla de matching (FR-001/FR-002 del spec)

Un movimiento **involucra** al instrumento filtrado `F` (comparación
insensible a mayúsculas, exacta, sin fuzzy) si se cumple **cualquiera**:

| # | Forma | Condición | Ejemplo con `F = "NOK"` |
|---|-------|-----------|--------------------------|
| M1 | Símbolo registrado exacto | `movement.symbol.upper() == F.upper()` | trade de la acción `NOK`, dividendo registrado bajo `NOK` |
| M2 | Root de opción | el movimiento es de opción con símbolo OCC identificable y `root.upper() == F.upper()` | `NOK   261218P00011000` (buy/sell de las 20 puts) |
| M3 | Símbolo de opción completo | `movement.symbol.upper() == F.upper()` cuando `F` es un símbolo de opción completo | `F = "NOK   261218P00011000"` → solo esa opción |

Nota: M3 es un caso particular de M1 (igualdad del símbolo registrado);
se lista por separado porque ese input hoy es rechazado por el proveedor
(HTTP 400) y el feature lo soporta explícitamente — la tool ya no envía
el filtro upstream (research R1).

### Validación dual (clarificación C, FR-003)

1. Lookup `instruments(symbols=[F], projection="symbol-search")` — un
   solo upcall, solo cuando hay filtro (igual que 006).
2. Directorio resuelve `F` → continuar con el barrido sin filtro
   upstream + matching local.
3. Directorio NO resuelve `F` → **no fallar**: ejecutar el barrido igual.
   Clasificación final:
   - ≥ 1 movimiento matchea (M1/M2/M3) → `ok` con esos movimientos.
   - 0 movimientos matchean → error `instrument_not_found` nombrando `F`
     (ToolError accionable, como hoy).
4. Comportamiento nuevo derivado: `F = "CURRENCY_USD"` (no resuelto en
   el directorio) ahora devuelve sus movimientos de caja etiquetada en
   lugar de `instrument_not_found`.

### Filtro sin movimiento y sin entrada en directorio

`instrument_not_found` preserva su semántica de honestidad: un símbolo
mistipeado (sin entrada en directorio, sin movimientos) produce el error
nombrando el símbolo — nunca un `no_movements` ambiguo.

## §3. TransactionsResult (sin cambios estructurales)

Todos los campos de 006 sin cambios: `outcome`, `detail`, `retryable`,
`retrieved_at`, `total_count`, `movements`, `returned`, `has_more`,
`next_offset`, `accounts_failed`, `offset_echo`.

Semántica refinada (sin renombrar nada):

- `total_count` = tamaño del conjunto **filtrado** completo del rango
  (todas las páginas del resultado filtrado).
- `detail = no_movements_for_instrument` ⇔ el rango era válido, no hubo
  fallos y **nada** matcheó el filtro en ninguna forma (M1/M2/M3).
- Reglas cruzadas 1–8 de 006 vigentes (incluida la regla 6:
  `no_movements_for_instrument` ⇒ … y regla 2/3 de paginación).
- Paginación calculada sobre el conjunto filtrado; `offset`/`offset_echo`
  idénticos a 006.

## §4. Subset-consistency (FR-005)

Propiedad estructural garantizada por el diseño (barrido sin filtro +
matcher local — research R1): para el mismo rango,

```
filtered(result) == matcher(unfiltered(result), F)
```

donde `matcher` aplica M1∨M2∨M3. Test unitario de regresión fija la
propiedad contra fixtures deterministas.

## §5. Presupuestos (Principio V)

| Presupuesto | Valor declarado | Impacto |
|-------------|-----------------|---------|
| Latencia p95 | ≤ 5 s (SC-001 de 006) | Sin cambios: mismas upcalls (1 linked_accounts + N transactions) + 1 instruments opcional |
| Página default (50 movs) | ≤ 16 KB (SC-003 de 006) | Se mantiene **incluyendo** `underlying_symbol` (~25 bytes × mov. de opción; caso peor 50 opciones ≈ +1.2 KB) |
| Página extended | ≤ 64 KB | Sin cambios (extended ya incluía el passthrough con el OCC) |
