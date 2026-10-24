# Bug Assessment: `get_transaction_history` pierde la pata del instrumento en trades multi-leg (`symbol=NOK` nunca matchea)

- **Slug**: nok-symbol-filter-miss
- **Created**: 2026-10-23 (actualizado 2026-10-24 con evidencia en vivo)
- **Source**: pasted text
- **Verdict**: valid (reproducido y root cause confirmado con payload en vivo)
- **Severity**: high

## Report (verbatim or summarized)

> "Porque la tool schwab.get_transaction_history [start_date=2026-04-23, end_date=2026-10-23, symbol=NOK] no trajo registros, si hubo transaccion de opciones sobre NOK y el OCC de esas transacciones debio tener NOK como raiz."

Segunda pasada del usuario: "si eliminas el filtro por instrumento de la tool vas a ver que las transacciones de opciones si existen en ese periodo."

## Symptom

`get_transaction_history(symbol="NOK")` sobre la ventana 2026-04-23..2026-10-23 devuelve `ok / no_movements_for_instrument` con 0 registros, aunque existen 14 legs de opciones sobre NOK en el período. En realidad el bug es más amplio: **casi todo movimiento `trade` queda etiquetado `CURRENCY_USD | CURRENCY` con descripción vacía** — la pata del instrumento real (opción/acción) se pierde en el mapeo, por lo que el filtro por símbolo nunca puede matchear.

## Reproduction (confirmada en vivo, 2026-10-24)

1. Invocar `get_transaction_history(start_date="2026-09-24", end_date="2026-10-23")` (sin filtro): 23 movimientos, **18 con `category=trade` pero todos `symbol=CURRENCY_USD`**, pares de montos en el mismo timestamp (patas de spreads).
2. Re-invocar la misma ventana con `extended=true`: los `extended.transferItems` crudos **sí contienen la pata de la opción** (p. ej. `PLTR  261120P00180000`, `INTC  261120P00085000`) después de 4 items de efectivo/comisiones (`CURRENCY_USD` con `feeType` COMMISSION/SEC_FEE/OPT_REG_FEE/TAF_FEE).
3. Invocar con `symbol="NOK"` → 0 registros; con `symbol="AMD"` → 0 registros (también operó AMD en el período).
4. Barrido de 6 meses con `extended=true`: **131 de los movimientos `trade` están etiquetados `CURRENCY_USD` ocultando un instrumento real**; se identificaron 14 legs de NOK en `transferItems`.

## Suspected Code Paths

- `src/schwab_mcp/transactions.py:824-860` (`map_provider_transactions`) — **ROOT CAUSE CONFIRMADO**. Extrae el símbolo del top-level `instrument` o del **primer** `transferItems[].instrument` con `symbol` (líneas 829-833). En los payloads reales, los primeros items de `transferItems` son las patas de efectivo/comisiones con `instrument: {symbol: "CURRENCY_USD", assetType: "CURRENCY"}` (no-None), por lo que `symbol` queda en `CURRENCY_USD` y `instrument_type` en `CURRENCY`. El `underlying_symbol` (líneas 857-860) depende del mismo `symbol`, así que también se pierde. Nota: el test `test_transactions_live_response.py:_real_trade_tx` modela la pata de efectivo con `instrument: None` — el payload real de 2026-10-24 la trae **no-None** (`CURRENCY_USD`), y va primero.
- `src/schwab_mcp/transactions.py:75-120` (`movement_involves_filter`) — **correcto** (M1/M2/M3 verificados en vivo y por `tests/unit/test_transactions_underlying.py`); el filtro no matchea porque el movimiento curado ya no contiene el instrumento.
- `docs/tools.md` (garantías de la tool) — la contratse afirma descripción/símbolo curados; el caso multi-leg con patas de fees no está modelado.

## Root Cause Hypothesis

**Confirmada (confianza alta)**: en el payload real de `/transactions`, cada TRADE lleva en `transferItems` primero las patas de efectivo y comisiones (todas con `instrument.symbol = "CURRENCY_USD"`, `assetType = "CURRENCY"`) y al final la pata del instrumento negociado. El mapper toma el primer item con símbolo no-None → todo trade queda curado como `CURRENCY_USD/CURRENCY`. Consecuencia: el filtro local `symbol=X` jamás matchea salvo que el movimiento sea de efectivo puro; `no_movements_for_instrument` se emite como afirmación de ausencia siendo falsa. Evidencia: los 14 legs de NOK (05-05, 05-06, 06-02, 06-05 ×8, 06-24 ×2, 08-27) están presentes en `transferItems` con `assetType: OPTION` y `rootSymbol: NOK`, pero sus movimientos curados dicen `CURRENCY_USD`.

## Proposed Remediation

**Preferred**:
1. **Mapeo** (`map_provider_transactions`): al escanear `transferItems`, elegir como símbolo del movimiento el primer instrumento **no-divisa** (preferir `assetType != CURRENCY`; caer en `CURRENCY_USD` solo si no hay otro). Como mínimo, la decisión debe ser determinista y testeada contra el shape real (fees primero). Conservar además la lista de símbolos involucrados (p. ej. `instruments: [...]`) para no descartar legs.
2. **Filtro** (`movement_involves_filter` + orquestador): matchear `filter_symbol` contra **todos** los instrumentos del movimiento (M1/M2 sobre el símbolo curado + M4 sobre `instruments[]`/`transferItems`), para que un trade multi-leg con NOK en cualquier pata matchee. Documentar la nueva forma en data-model §2 y `docs/tools.md`.

**Alternatives**:
- Solo (1): arregla el símbolo curado del trade simple, pero los spreads multi-instrumento (p. ej. roll NOK 260717→260821 en la misma marca de tiempo en transacciones separadas) seguirían mostrando un solo instrumento por movimiento. Menor cambio de contrato, solución parcial.
- Exponer solo `extended` y que el agente filtre client-side: ya posible hoy, pero contradice el contrato del parámetro `symbol` y es frágil (el agente debe saber del bug).

**Files likely to change**:
- `src/schwab_mcp/transactions.py` (mapeo de `transferItems`; filtro y su llamada en el orquestador)
- `tests/unit/test_transactions_live_response.py` (regresión con el shape real: 4 patas de fees `CURRENCY_USD` no-None primero + pata OPTION última)
- `tests/unit/test_transactions_filter_query.py` (M4 / match multi-instrumento)
- `docs/tools.md`, `specs/006-transaction-history/contracts/` (data-model §2: nueva forma de match y/o campo `instruments`)

**Tests to add or update**:
- Regresión de mapeo: transacción real (fees `CURRENCY_USD` no-None primero, opción al final) → `symbol` = OCC de la opción, `instrument_type = OPTION`, `underlying_symbol` = raíz.
- Regresión de extremo a extremo: `get_transaction_history(symbol="NOK")` con ese payload debe retornar el movimiento (M2).
- Multi-leg: movimiento con dos instrumentos no-divisa → el filtro matchea si cualquiera coincide.
- No romper: movimiento genuino de efectivo (solo `CURRENCY_USD`) sigue curándose igual.

## Risks & Considerations

- Cambio de contracto del data-model (§2 y esquema de `MovementEntry`) → actualizar spec/contracts y tests de presupuesto (`tests/performance/test_transactions_budgets.py`).
- Los trades ya curados en outputs previos cambian de forma: breaking change semántico para consumidores del MCP (documentar en CHANGELOG).
- `no_movements_for_instrument` pasará a ser confiable; hoy los agentes pueden haber sacado conclusiones falsas (ocurrió en esta sesión: "no operaste NOK").

## Open Questions

- Ninguno bloqueante; el root cause está confirmado con evidencia en vivo.
