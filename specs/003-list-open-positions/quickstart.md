# Quickstart: List Open Positions

**Feature**: `003-list-open-positions`

Guía de validación end-to-end. Los detalles de esquema viven en
[contracts/mcp-tools.md](contracts/mcp-tools.md) y
[data-model.md](data-model.md) — no se duplican acá.

## Prerrequisitos

1. Entorno instalado: `uv sync`
2. Credenciales en el entorno: `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`
3. Autorización vigente (feature 001): `uv run schwab-mcp auth-status`
   → `{"state": "valid", ...}`. Si no, correr `schwab-mcp auth` (solo humano).

## Validación por tests (gate principal)

```sh
uv run pytest tests/unit/test_positions.py -v        # mapeo/consolidación/signo/omisión
uv run pytest tests/unit/test_server_tool.py -v      # registro + outcomes clasificados
uv run pytest tests/unit/test_no_secrets_in_output.py -v  # FR-008
uv run pytest -m performance tests/performance/test_positions_budgets.py -v  # 5 s + 8 KB
uv run pytest                                        # suite completa: gate de commit (0 skipped)
```

Esperado: todo verde. Los tests unitarios usan fakes del client (sin red).

## Validación manual end-to-end (con red real)

1. Levantar el servidor:

   ```sh
   uv run schwab-mcp serve
   ```

2. Desde un cliente MCP conectado por stdio (opencode u otro), invocar:

   ```json
   {"name": "get_open_positions", "arguments": {}}
   ```

3. Resultado esperado con tenencias (ejemplo de forma):

   ```json
   {
     "outcome": "ok",
     "detail": "data_received",
     "retryable": false,
     "retrieved_at": "2026-10-20T14:03:11+00:00",
     "positions": [
       {
         "account_hash": "…hash opaco…",
         "symbol": "SPY",
         "instrument_type": "EQUITY",
         "description": "SPDR S&P 500 ETF Trust",
         "quantity": 10.0,
         "average_price": 580.25,
         "market_value": 5910.0,
         "unrealized_pl": 107.5,
         "price_timestamp": "2026-10-20T14:03:11+00:00"
       }
     ]
   }
   ```

   Verificaciones:
   - Una entrada por (cuenta, contract); patas de un strangle/condor separadas, cantidad con signo (cortas negativas).
   - `price_timestamp` presente en cada entrada (FR-012).
   - Ningún número de cuenta crudo, token o secreto en el resultado ni en stderr.

4. Sin posiciones → `outcome: "ok"`, `detail: "no_positions"`, `positions: []` (no es error).

5. Modo extendido:

   ```json
   {"name": "get_open_positions", "arguments": {"extended": true}}
   ```

   Cada entrada agrega `"extended": {...}` con el passthrough del proveedor.

6. Auditoría en stderr de `serve`: por invocación, exactamente un
   `positions_query_start` y un terminal (`positions_query_success` o
   `positions_query_failure`) — vocabulario en [contracts/events.md](contracts/events.md).

## Escenarios de fallo (verificación del playbook)

| Cómo provocarlo | Resultado esperado |
|-----------------|--------------------|
| Sin conectividad (desconectar red) | `outcome: "transient_failure"`, `retryable: true`, `detail: "provider_unreachable"`, inmediato (sin reintentos internos) |
| Refresh token rechazado (expirado/revocado) | `outcome: "reauth_required"` → agente notifica al dueño (`schwab-mcp auth`); NO reintentar |
| Una cuenta falla y otras no | `outcome: "partial_failure"`, `accounts_failed` con hash + detalle, `positions` con lo que sí respondió |

## Flujo del agente ante fallos

Idéntico al playbook de [docs/tools.md](../../../docs/tools.md):
`transient_failure` → reintentar luego; `reauth_required` → notificar al
dueño y monitorear con `auth-status`; `partial_failure` → decidir si el
subconjunto alcanza o reintentar.
