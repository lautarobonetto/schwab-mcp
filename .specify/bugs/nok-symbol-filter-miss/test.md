# Bug Verification: `get_transaction_history` curaba todo trade como `CURRENCY_USD`

- **Slug**: nok-symbol-filter-miss
- **Tested**: 2026-10-24
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

El síntoma original ya no reproduce: la consulta exacta del reporte (`start_date=2026-04-23, end_date=2026-10-23, symbol="NOK"`) ejecutada en vivo contra la API real con el código corregido retorna las **14 legs de opciones NOK** del período (pre-fix: `ok / no_movements_for_instrument` con 0 registros). Todas las patas curan con el OCC correcto y `underlying_symbol=NOK`; el control sin filtro se mantiene en 173 movimientos (sin regresión en el volumen de datos).

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | `uv run python tmp/live_check_nok.py` (script one-off read-only con cliente real + tokens almacenados; ejecuta la consulta exacta del assessment con paginación) | **pass** | 14 movimientos NOK retornados (pre-fix: 0); el consentimiento del usuario fue otorgado para esta verificación de red |
| Reproduction (pre-fix baseline) | Misma consulta vía MCP en la sesión (código viejo cargado en el proceso del servidor) | pass (baseline) | Confirmó el síntoma original (`ok / no_movements_for_instrument`, total=0) — baseline obtenido antes del fix |
| New / updated tests | `uv run pytest tests/unit/test_transactions_live_response.py -q` | pass | 20 passed — incluye la sección `1c. Multi-leg trade shape` (5 tests de regresión) |
| Regression suite | `uv run pytest -q` | pass | **842 passed, 0 skipped, 0 failed** (gate de commit de la constitución) |
| Lint / type-check | — | not-run | No hay tooling de lint/type-check configurado en `pyproject.toml` |
| Control sin filtro (misma ventana) | `get_transaction_history(client, "2026-04-23", "2026-10-23")` en el script en vivo | pass | total=173, idéntico al barrido pre-fix — el fix no alteró el volumen de movimientos fetchados |

## Output Excerpts

Reproducción en vivo post-fix (`symbol=NOK`, ventana de 6 meses):

```
page offset=0: outcome=TransactionOutcome.ok detail=TransactionDetail.history_retrieved total=14 returned=14

NOK movements retrieved: 14
  2026-05-05T15:43:38+0000  trade  NOK   260618P00012000  type=OPTION  underlying=NOK
  2026-05-06T14:19:44+0000  trade  NOK   260618P00012000  type=OPTION  underlying=NOK
  2026-06-02T13:48:48+0000  trade  NOK   260717P00014000  type=OPTION  underlying=NOK
  2026-06-05T18:59:46+0000  trade  NOK   260821P00013000  type=OPTION  underlying=NOK   (×3)
  2026-06-05T18:59:46+0000  trade  NOK   260717P00014000  type=OPTION  underlying=NOK   (×3)
  2026-06-24T19:08:58+0000  trade  NOK   260821P00013000  type=OPTION  underlying=NOK
  2026-06-24T19:08:58+0000  trade  NOK   261218P00011000  type=OPTION  underlying=NOK
  2026-08-27T13:31:07+0000  trade  NOK   261218P00011000  type=OPTION  underlying=NOK

control unfiltered: outcome=TransactionOutcome.ok total=173
```

Las 14 legs coinciden 1:1 con las identificadas en el assessment vía `extended.transferItems` (fechas, contratos, cantidades), confirmando que el fix recupera exactamente los movimientos que el bug ocultaba.

## Residual Risks

- **Proceso del servidor MCP desactualizado**: el servidor `schwab-mcp` en ejecución sigue cargando el código pre-fix; las herramientas MCP de esta sesión seguirán mostrando el bug hasta reiniciarlo (`uv run schwab-mcp serve`). La verificación en vivo se ejecutó in-process con el código corregido, por lo que el resultado es válido.
- **Transacciones con múltiples instrumentos no-divisa**: fuera de alcance por decisión documentada (fix.md, Deviations) — 0 casos en 173 movimientos en vivo; si aparecen (p. ej. asignaciones RECEIVE_AND_DELIVER), solo se curará la primera pata no-divisa.
- **Descripción vacía en trades**: los trades reales no traen `description` a nivel de transacción; el fix no la deriva del instrumento (follow-up registrado).
- **Script de verificación**: `tmp/live_check_nok.py` queda en `tmp/` (git-ignored) como artefacto de la verificación; es re-ejecutable y solo-lectura.

## Recommendation

Cerrar el bug — verificado end-to-end: la reproducción original del assessment se ejercitó en vivo contra el proveedor real con el código corregido y el síntoma desapareció (14/14 legs NOK recuperadas), la suite completa está verde y el volumen de datos del barrido sin filtro no cambió. Pendiente operativo único: reiniciar el proceso del servidor MCP para que las tools servidas usen el código corregido.
