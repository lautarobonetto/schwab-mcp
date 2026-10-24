# Contrato de tool MCP: `get_transaction_history` (007 — filtro consciente del subyacente)

Feature: 007-underlying-symbol-filter | Date: 2026-10-24
Base: `specs/006-transaction-history/contracts/mcp-tools.md` (la tool
existe; este contrato documenta **solo los cambios** de la feature 007).
Todo lo no listado aquí (outcomes, detail, errores de validación de
fechas, paginación, garantías, caveat de permisos) queda vigente de 006.

## 1. Input schema — semántica extendida de `symbol`

Parámetros: mismos nombres y tipos que 006 (`start_date`, `end_date`,
`symbol` opcional, `extended`, `offset`). Cambia la **semántica** del
filtro:

| Filtro del agente | Comportamiento 006 | Comportamiento 007 |
|---|---|---|
| `symbol: "NOK"` (subyacente) | Solo movimientos registrados bajo `NOK` (las opciones de NOK **invisibles**; si la cuenta solo operó opciones de NOK, devolvía `no_movements_for_instrument` — engañoso) | Movimientos bajo `NOK` **+** movimientos de opciones con root `NOK` |
| `symbol: "NOK   261218P00011000"` (OCC completo) | Rechazo del proveedor (HTTP 400) expuesto como `partial_failure` opaco | Movimientos de **esa opción puntual** |
| `symbol: "nok"` (minúsculas) | Depende del matcheo upstream | Igual resultado que `"NOK"` (matching insensible a mayúsculas) |
| `symbol: "ZZZZZZ"` (inexistente) | `instrument_not_found` | `instrument_not_found` **solo** si además nada matchea (validación dual — ver §3) |
| `symbol: "CURRENCY_USD"` (interno) | `instrument_not_found` | Devuelve los movimientos de caja etiquetada con ese símbolo (si existen) |

Matching exacto, sin fuzzy (M1 símbolo registrado · M2 root de opción ·
M3 OCC completo — ver data-model §2). Comparación insensible a
mayúsculas/minúsculas. La salida reporta los símbolos tal como la fuente
los registra.

## 2. Output schema — campo nuevo en `MovementEntry`

| Campo | Tipo | Presencia | Semántica |
|-------|------|-----------|-----------|
| `underlying_symbol` | string \| ausente | solo movimientos de opción con OCC identificable | Subyacente de la opción (root del símbolo OCC, sin padding). Ausente para no-opciones y para opciones sin codificación OCC identificable |

Ejemplo (`ok`, movimiento de opción, curado):

```json
{
  "account_hash": "8016D21F…",
  "occurred_at": "2026-08-27T13:31:07+0000",
  "category": "trade",
  "description": "",
  "amount": -3220.0,
  "currency": "USD",
  "symbol": "NOK   261218P00011000",
  "underlying_symbol": "NOK",
  "instrument_type": "OPTION"
}
```

Los demás campos y su presencia quedan idénticos a 006. La presencia del
campo es aditiva: consumidores existentes no se rompen (nuevos campos
ausentes para no-opciones).

## 3. Validación dual del filtro (reemplaza la validación única de 006)

1. Lookup en el directorio (`instruments`, `symbol-search`) — 1 upcall,
   solo si hay filtro (idéntico a 006).
2. Directorio resuelve → consulta normal.
3. Directorio NO resuelve → **no falla**: se consulta igual.
4. Clasificación final: hay match (M1/M2/M3) → `ok`; no hay match →
   `instrument_not_found` nombrando el filtro (ToolError accionable).

Consecuencia documentada: `CURRENCY_USD` pasa de error a resultados si
hay movimientos con ese símbolo registrado.

## 4. Subset-consistency (invariante del contrato)

Para el mismo `start_date`/`end_date` y `extended`, el resultado filtrado
es exactamente el subconjunto del resultado sin filtro cuyos movimientos
matchean el filtro (M1∨M2∨M3) — mismo `total_count` del subconjunto,
misma ordenación, misma paginación. Verificable con el walk del
quickstart (S3).

## 5. Presupuestos

Sin cambios respecto de 006: ≤ 5 s p95; ≤ 16 KB página default de 50
movimientos **incluyendo** `underlying_symbol`; ≤ 64 KB extended.
`docs/tools.md` debe reflejar el tamaño esperado actualizado.

## 6. Eventos de auditoría

Sin cambios: `transactions_query_start` + terminal
(`transactions_query_success` / `transactions_query_failure`) por
invocación, vocabulario de 006 (ver
`specs/006-transaction-history/contracts/events.md`). La validación dual
no agrega eventos (la decisión queda capturada por el evento terminal
correspondiente).

## 7. Read-only y secretos

Sin cambios: solo lectura; `account_hash` opaco; ningún campo nuevo
contiene identificadores de cuenta ni credenciales (`underlying_symbol`
es un identificador público de instrumento).
