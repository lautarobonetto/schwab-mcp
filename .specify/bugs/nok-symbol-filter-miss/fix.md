# Bug Fix: `get_transaction_history` curaba todo trade como `CURRENCY_USD`

- **Slug**: nok-symbol-filter-miss
- **Fixed**: 2026-10-24
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

El mapper `map_provider_transactions` tomaba el primer `transferItems[].instrument` con símbolo para curar `symbol`; en el payload real las patas de efectivo/comisiones (`CURRENCY_USD`) van primero, así que ~131 de 173 trades reales quedaban etiquetados como divisa y el filtro `symbol=NOK` jamás matcheaba. Ahora el mapper recolecta todos los candidatos (top-level `instrument` + `transferItems`) y cura el **primer instrumento no-divisa**, cayendo en el primer candidato solo para movimientos genuinamente de efectivo. TDD: regresión en Red con el shape real → fix → Green → suite completa 842 passed, 0 skipped.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/transactions.py` | modified | `map_provider_transactions`: curación por primer instrumento no-divisa; nuevo helper `_is_currency_instrument()` (única definición de "pata de divisa", DRY) |
| `tests/unit/test_transactions_live_response.py` | added tests | Sección `1c. Multi-leg trade shape` con el payload real (4 patas de fees `CURRENCY_USD` no-None primero + pata OPTION última, encontrado en vivo 2026-10-24) |
| `docs/tools.md` | modified | Fila `symbol` de `MovementEntry`: documenta la regla de curación no-divisa |
| `specs/006-transaction-history/data-model.md` | modified | Misma regla en la tabla de `MovementEntry` |
| `docs/CHANGELOG.md` | modified | Nueva sección `[0.5.1]` con el fix |
| `pyproject.toml` | modified | Versión `0.5.0` → `0.5.1` (PATCH, consistente con CHANGELOG) |

## Diff Highlights

```python
# Antes: primer instrumento con símbolo → las patas de fees lo tapaban
instrument = tx.get("instrument")
if not (isinstance(instrument, dict) and instrument.get("symbol")):
    instrument = None
    for item in tx.get("transferItems") or []:
        cand = item.get("instrument") if isinstance(item, dict) else None
        if isinstance(cand, dict) and cand.get("symbol"):
            instrument = cand
            break

# Ahora: candidatos en orden de encuentro, gana el primer no-divisa
candidates: list[dict] = []
top_instrument = tx.get("instrument")
if isinstance(top_instrument, dict) and top_instrument.get("symbol"):
    candidates.append(top_instrument)
for item in tx.get("transferItems") or []:
    cand = item.get("instrument") if isinstance(item, dict) else None
    if isinstance(cand, dict) and cand.get("symbol"):
        candidates.append(cand)

chosen = next(
    (cand for cand in candidates if not _is_currency_instrument(cand)),
    candidates[0] if candidates else None,
)
```

```python
def _is_currency_instrument(instrument: dict) -> bool:
    asset_type = instrument.get("assetType") or instrument.get("instrumentType")
    if asset_type:
        return str(asset_type).upper() == "CURRENCY"
    symbol = instrument.get("symbol") or ""
    return symbol.upper().startswith("CURRENCY_")
```

## Tests Added or Updated

- `tests/unit/test_transactions_live_response.py::TestMultiLegTradeShape::test_option_leg_curated_over_fee_legs` — pin: la pata OPTION gana sobre 4 patas de fees `CURRENCY_USD` no-None; `underlying_symbol = "NOK"` derivado del símbolo corregido
- `...::test_symbol_filter_matches_multileg_option` — pin e2e: `symbol="NOK"` retorna el movimiento cuya raíz OCC es NOK (M2), no `no_movements_for_instrument`
- `...::test_cash_only_trade_stays_currency` — pin: movimientos genuinamente de efectivo siguen curando `CURRENCY_USD/CURRENCY`
- `...::test_first_noncurrency_leg_wins_deterministically` — pin: regla determinista (primera pata no-divisa en orden de encuentro)
- `...::test_top_level_currency_instrument_not_preferred_over_legs` — pin: un `instrument` top-level de divisa no tapa el instrumento de `transferItems`

## Local Verification

- `uv run pytest tests/unit/test_transactions_live_response.py::TestMultiLegTradeShape -x -q` (antes del fix) → **1 failed** (Red: `CURRENCY_USD` tapaba el OCC — reproduce el defecto)
- `uv run pytest tests/unit/test_transactions_live_response.py -q` (después del fix) → 20 passed
- `uv run pytest -q` (suite completa, gate de commit) → **842 passed, 0 skipped, 0 failed**
- Verificación con datos en vivo: el shape de los fixtures replica byte-a-byte el observado en el payload real de 2026-10-24 (`extended.transferItems` de trades PLTR/INTC/NOK). Verificación end-to-end contra el servidor MCP en vivo requiere reinicio del proceso `schwab-mcp` para cargar el código corregido (ver Follow-ups).

## Deviations from Assessment

- **No se implementó el campo `instruments[]` ni la forma de match M4** (parte 2 del remedio preferido). Justificación con evidencia nueva: el análisis en vivo de los 173 movimientos del período mostró **0 transacciones con más de un instrumento no-divisa** (135 con exactamente 1, 38 solo-efectivo); el proveedor emite una transacción por pata. El filtro M1/M2/M3 existente sobre el símbolo curado corregido cubre el 100% de los casos observados; `instruments[]` + M4 era generalidad especulativa (constitución: KISS/YAGNI) y habría cambiado el contrato del payload y el presupuesto de 16 KB/página sin beneficio observado. Queda como follow-up si aparecen payloads multi-instrumento (p. ej. asignaciones RECEIVE_AND_DELIVER con acciones+opciones).
- **No se modificó `tests/unit/test_transactions_filter_query.py`** (listado en el assessment para los tests de M4): el filtro no cambió y el test e2e `symbol="NOK"` quedó en `test_transactions_live_response.py` junto a los fixtures del shape real.
- **Sin fallback de descripción**: los trades reales traen `description` vacía a nivel de transacción; derivarla de la descripción del instrumento sería una mejora útil pero fuera del alcance del assessment (follow-up).

## Follow-ups

- Reiniciar el servidor MCP (`uv run schwab-mcp serve`) y re-ejecutar `get_transaction_history(symbol="NOK", start_date="2026-04-23", end_date="2026-10-23")` en vivo para confirmar las 14 legs de NOK (verificación end-to-end del fix contra el proveedor real).
- Vigilar en futuros barridos si aparecen transacciones con múltiples instrumentos no-divisa (asignaciones/ejercicios); si ocurre, implementar `instruments[]` + match M4 según el assessment.
- Evaluar derivar `description` desde la descripción del instrumento cuando la transacción no la trae (reduce movimientos "anónimos" en trades curados).
- `/speckit.bug.test slug=nok-symbol-filter-miss` para la verificación formal.
