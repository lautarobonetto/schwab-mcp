# Quickstart: `get_transaction_history` (006)

Guía de validación end-to-end. Detalles normativos en
[contracts/mcp-tools.md](contracts/mcp-tools.md) y
[data-model.md](data-model.md).

## Prerequisitos

1. Entorno listo: `uv sync`
2. Configuración: `SCHWAB_APP_KEY` y `SCHWAB_APP_SECRET` en el entorno
3. Autorización vigente: `uv run schwab-mcp auth-status` → `state: valid`
   (si no, el dueño corre `uv run schwab-mcp auth`)
4. Permisos: la app registrada y las cuentas deben tener acceso de
   lectura de transacciones (ver Caveat en contracts/mcp-tools.md)

## Ejecutar

```sh
uv run schwab-mcp serve
```

El servidor registra 2 tools: `get_open_positions` y
**`get_transaction_history`**.

## Escenarios de validación (mapean a SC del spec)

### S1 — Historia completa de un rango (SC-001/SC-002/SC-004)

Con un cliente MCP conectado por stdio:

```json
{"name": "get_transaction_history",
 "arguments": {"start_date": "2026-09-01", "end_date": "2026-09-30"}}
```

Esperado: `outcome=ok`, `detail=history_retrieved` (o `no_movements` si
el mes no tuvo actividad), `movements` con trades **y también**
transferencias/intereses/dividendos/ajustes si los hubo, ordenados del
más viejo al más nuevo, `total_count` ≥ `returned`, `returned ≤ 50`.

### S2 — Filtro por instrumento (FR-003, SC-005)

```json
{"name": "get_transaction_history",
 "arguments": {"start_date": "2026-09-01", "end_date": "2026-09-30",
               "symbol": "AAPL"}}
```

Esperado: solo movimientos con `"symbol": "AAPL"`; sin transferencias ni
intereses. Con un símbolo inexistente (ej. `ZZZZZZ`) → error
`instrument_not_found` — **no** un `no_movements` ambiguo.

### S3 — Paginación sin duplicados ni gaps (SC-006)

Si `has_more=true`, repetir la misma consulta con `"offset": 50`,
después `100`… hasta `has_more=false`. Verificar:
`total_count` constante entre páginas, unión sin duplicados (por
`account_hash` + `occurred_at` + descripción) y sin omisiones, y que la
última página no trae `next_offset`.

### S4 — Validación de rango (FR-004, edge cases)

Cada uno debe fallar con error accionable, **sin** llamar al proveedor:

- `end_date < start_date` → error nombra ambas fechas.
- Rango de 2 años → error indica el máximo de 1 año.
- `end_date: "2099-01-01"` → error fecha futura.
- `start_date: "01-09-2026"` → error de formato.

### S5 — Presupuestos (SC-001/SC-003)

```sh
uv run pytest tests/performance/test_transactions_budgets.py -v
```

Esperado: latencia p95 ≤ 5 s en el set de pruebas; página default
(50 movimientos) ≤ 16 KB; extended ≤ 64 KB.

### S6 — Sin secretos

```sh
uv run pytest tests/unit/test_no_secrets_in_output.py -v
```

Esperado: verde — ningún campo del resultado ni evento contiene tokens,
app keys ni secretos.

## Diagnóstico de vacíos persistentes (Caveat)

Si `no_movements` aparece para rangos amplios en una cuenta con
actividad visible en schwab.com, la causa probable es permiso de lectura
de transacciones de la app/cuenta (no falta de datos). Ver la sección
"Caveat operacional" del contrato.
