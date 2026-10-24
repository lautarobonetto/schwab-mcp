# Bug Fix: get_open_positions falla en vivo — Response sin unwrap y forma de payload inventada

- **Slug**: positions-response-unwrap
- **Fixed**: 2026-10-24
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

`get_open_positions` (feature 003) ahora funciona contra la API real:
unwrapping de `requests.Response` vía `schwab_mcp.provider.response_json`
(reuso del mecanismo de la feature 006), normalización de la forma real
del payload (lista top-level de `{aggregatedBalance, securitiesAccount}`),
identificador de cuenta = `hashValue` del proveedor cruzado por
`accountNumber` con `linked_accounts()` (retiro del hash local SHA-256
truncado), y derivación de `strike_price`/`expiration_date` de opciones
desde el símbolo OCC.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/positions.py` | modified | Unwrap de `linked_accounts()` + `account_details_all()` con `response_json`; nuevo `_normalize_positions_payload()` (acepta forma real y legacy); nuevo `_parse_occ_option_symbol()`; partición matched/unmatched → `partial_failure` explícito; baja de `_hash_account` y del import `hashlib`; `_transform_provider_payload`/`_detect_account_failures` usan el `accountHash` resuelto |
| `tests/unit/test_positions_live_response.py` | new | 7 tests de regresión con fakes que devuelven `requests.Response` reales (forma real del payload) |
| `tests/unit/helpers.py` | new | Helper compartido `build_response()` (single source of truth para construir `Response` en tests) |
| `tests/unit/test_server_tool.py` | modified | `FakePositionsClient` agrega `linked_accounts()` con hashes opacos derivados de su payload |
| `tests/performance/test_positions_budgets.py` | modified | El fake agrega `linked_accounts()` (nueva upcall de la orquestación) |
| `docs/tools.md` | modified | Nota: `account_hash` = `hashValue` del proveedor, consistente entre tools |
| `docs/CHANGELOG.md` | modified | Entrada `Fixed` con el detalle y el cambio breaking de `account_hash` |
| `specs/003-list-open-positions/research.md` | modified | Nota de corrección post-implementación (forma real del payload, `hashValue`, OCC) |

## Diff Highlights (optional)

Orquestación (antes → después):

```python
# antes: Response usada como dict, hash local del número de cuenta
payload = client.account_details_all(fields="positions")
account_hash = _hash_account(account_number)  # sha256[:8]

# después: unwrap + cruce accountNumber↔hashValue
listing = response_json(client.linked_accounts())
raw = response_json(client.account_details_all(fields="positions"))
hash_by_number = {a["accountNumber"]: a["hashValue"] for a in listing}
provider_payload = _normalize_positions_payload(raw, hash_by_number)
# cuentas sin hash resoluble → accounts_failed (nunca hash inventado)
```

Opciones con símbolo OCC (antes → después):

```python
# antes: instrument.get("strikePrice", 0.0) → 0.0 real → ValidationError (gt=0)
# después: derivación desde el OCC
strike, parsed_expiry = _parse_occ_option_symbol(instrument.get("symbol", ""))
# "AMD   261120P00090000" → strike 630.0, expiry 2026-11-20
```

## Tests Added or Updated

- `tests/unit/test_positions_live_response.py::TestLiveSdkResponses::test_ok_from_real_shape_responses` — la forma real del SDK produce `ok` con posiciones mapeadas
- `...::test_account_hash_is_provider_hash_value` — `account_hash` = `hashValue` del proveedor (cruce por `accountNumber`), no hash local
- `...::test_http_401_maps_to_reauth_required` — HTTP 401 → `reauth_required/reauth_needed`
- `...::test_http_500_maps_to_transient_failure` — HTTP 500 → `transient_failure` con `retryable=true`
- `...::test_unmatched_account_number_is_partial_failure` — cuenta sin hash resoluble → `partial_failure` con `accounts_failed` (sin drop silencioso, sin hash local)
- `...::test_raw_account_number_never_in_output` — el número de cuenta crudo jamás aparece en la salida (credential safety)
- `...::test_option_strike_and_expiry_parsed_from_occ_symbol` — strike/expiry derivados del símbolo OCC cuando el instrumento no los trae

## Local Verification

- Comandos: `uv run pytest -q` → **758 passed, 0 skipped** (suite completa)
- Manual (en vivo, SDK real `schwabdev==4.0.0` con credenciales vigentes):
  `get_open_positions(client)` → `outcome=ok`, `detail=data_received`,
  8 posiciones (opciones AMD/SPCX/MSFT/XSP + strikes 630/620/155/165/525
  parseados del OCC), `account_hash` = `hashValue` real del proveedor.

## Deviations from Assessment

1. **Cruce por `accountNumber`, no por orden**: el assessment contemplaba
   el cruce; la implementación matchea por `accountNumber` (no por índice)
   y reporta cuentas sin match como `partial_failure` con etiquetas
   sintéticas `unmatched-account-N` (el modelo exige `account_hash`
   no vacío y no se puede emitir el número crudo).
2. **`_detect_account_failures` conservado**: el mecanismo de errores
   per-account (`"error"` en la entrada) no existe en el payload real del
   endpoint bulk; se conserva operando sobre la forma normalizada para
   compatibilidad con el contrato de 003 y fakes existentes.
3. **Descubrimiento nuevo (fuera del assessment)**: los instrumentos
   OPTION reales no traen `strikePrice`/`expirationDate` — al fix de
   unwrap se sumó `_parse_occ_option_symbol()` (derivación desde el
   símbolo OCC). Sin esto, la tool crasheaba en vivo con
   `ValidationError: strike_price Input should be greater than 0`.
4. **`server.py` sin cambios**: confirmado — la tool ya registrada no
   requiere wrapper adicional (no hay inputs a validar).

## Follow-ups

- Recargar el servidor MCP conectado y re-verificar `get_open_positions`
  por el canal real (el proceso en vuelo aún corre el código anterior).
- `/speckit.bug.test slug=positions-response-unwrap` para la verificación
  formal post-fix.
- Considerar documentar en `docs/uso.md` que los `account_hash` de la
  salida de `get_open_positions` cambiaron de valor (breaking para
  consumidores que los hayan cacheado) — ya registrado en el CHANGELOG.
