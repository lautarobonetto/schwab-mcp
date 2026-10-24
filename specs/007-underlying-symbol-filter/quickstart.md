# Quickstart: filtro consciente del subyacente en `get_transaction_history` (007)

Guía de validación end-to-end. Detalles normativos en
[contracts/mcp-tools.md](contracts/mcp-tools.md) y
[data-model.md](data-model.md). Prerequisitos idénticos a la feature 006
(entorno `uv sync`, credenciales vigentes via `uv run schwab-mcp
auth-status`, permisos de lectura de transacciones).

## Ejecutar

```sh
uv run schwab-mcp serve
```

Con un cliente MCP conectado por stdio (o el MCP Inspector).

## Escenarios de validación (mapean a SC del spec)

### S1 — Filtro por subyacente incluye opciones (SC-001/SC-002)

```json
{"name": "get_transaction_history",
 "arguments": {"start_date": "2025-10-24", "end_date": "2026-10-23",
               "symbol": "NOK"}}
```

Esperado: `outcome=ok`; los movimientos incluyen **tanto** los
registrados bajo `NOK` (si los hay) **como** los trades de opciones con
root `NOK` (p. ej. `NOK   261218P00011000`), cada uno con
`"underlying_symbol": "NOK"`. Verificación de completitud: la unión de
los movimientos devueltos coincide con el subconjunto NOK de la consulta
sin filtro del mismo rango (S3).

### S2 — Filtro por símbolo OCC completo (FR-001c / US1-AC4)

```json
{"name": "get_transaction_history",
 "arguments": {"start_date": "2025-10-24", "end_date": "2026-10-23",
               "symbol": "NOK   261218P00011000"}}
```

Esperado: `outcome=ok` con exactamente los movimientos de esa opción
(sin el `partial_failure` opaco que produce hoy el rechazo del
proveedor). Con un rango sin actividad de esa opción: `ok /
no_movements_for_instrument`.

### S3 — Consistencia de subconjunto y case-insensitivity (SC-002)

1. Consulta sin filtro del rango → conjunto `U`.
2. Consulta con `symbol="NOK"` → conjunto `F1`.
3. Consulta con `symbol="nok"` (minúsculas) → conjunto `F2`.

Esperado: `F1 == F2` y `F1 == {m ∈ U : m involucra NOK}` (símbolo
registrado `NOK` o root de opción `NOK`). Script: filtrar `U` del lado
del cliente con la misma regla y comparar por
`(account_hash, occurred_at, symbol)`.

### S4 — Validación dual (FR-003 / US1-AC5)

- Filtro con símbolo inexistente y sin actividad (p. ej. `ZZZZZZ`) →
  error `instrument_not_found` nombrando el símbolo (igual que 006).
- Filtro con root no resuelto en el directorio pero con movimientos que
  matchean (si se identifica uno; caso `CURRENCY_USD` es el ejemplo
  documentado) → los movimientos se devuelven (`ok`), **no**
  `instrument_not_found`.

### S5 — Presupuestos (SC-004)

```sh
uv run pytest tests/performance/test_transactions_budgets.py -v
```

Esperado: latencia p95 ≤ 5 s; página default de 50 movimientos ≤ 16 KB
**con el caso peor de 50 opciones** (todas con `underlying_symbol`);
extended ≤ 64 KB.

### S6 — Sin secretos

```sh
uv run pytest tests/unit/test_no_secrets_in_output.py -v
```

Esperado: verde — `underlying_symbol` solo transporta identificadores
públicos de instrumento; `account_hash` opaco; sin tokens/secretos.

## Diagnóstico

- Si una consulta filtrada devuelve `no_movements_for_instrument` pero
  schwab.com muestra actividad del subyacente: verificar que la actividad
  sea de este período/cuenta; las opciones se matchean por root del OCC
  registrado — roots no estándar sin codificación OCC identificable no
  matchean (aparecen en la consulta sin filtro).
- El filtro ya no viaja upstream: los tiempos de respuesta filtrada
  deben ser comparables a la consulta sin filtro del mismo rango (misma
  cantidad de upcalls).
