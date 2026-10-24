# Bug Assessment: get_open_positions falla en vivo — Response sin unwrap y forma de payload inventada

- **Slug**: positions-response-unwrap
- **Created**: 2026-10-24
- **Source**: pasted text (contexto de la sesión de validación en vivo de la feature 006)
- **Verdict**: valid
- **Severity**: critical

## Report (verbatim or summarized)

Reporte original (texto pegado):

> "El mismo fix de Response para get_open_positions (feature 003), que
> también requiere cruzar accountNumber↔hashValue — avisame cuando quieras
> atacarlo."

Contexto verificado en esta misma sesión (2026-10-23/24, prueba en vivo):

- Llamada a la tool por el canal MCP conectado:
  `tools.schwab.get_open_positions({})` →
  `Error: Error executing tool get_open_positions` (error genérico del SDK
  MCP, la excepción real queda solo en el log del servidor).
- Verificado con el SDK real (`schwabdev==4.0.0`):
  `Client.account_details_all(fields="positions")` devuelve
  `requests.Response` (`<Response [200]>`), no un dict.
- Payload real (`status 200`, inspeccionado por claves, sin valores):
  lista JSON en el nivel superior:
  `[{"aggregatedBalance": {...}, "securitiesAccount": {"accountNumber",
  "positions": [...], "currentBalances", ...}}]`.
- `positions.py` espera un dict con clave `accountDetails` — que no existe
  en el payload real.

## Symptom

`get_open_positions` falla con error genérico en **toda** invocación en
vivo contra la API real de Schwab (la suite de tests pasa porque los fakes
devuelven dicts ya parseados con la forma `{"accountDetails": [...]}` que
el código asume). Esperado: `PositionsResult` con `outcome=ok` y las
posiciones de todas las cuentas vinculadas.

## Reproduction

1. Con credenciales vigentes (`uv run schwab-mcp auth-status` → `state: valid`),
   levantar `uv run schwab-mcp serve` (con el `SCHWAB_CALLBACK_URL` ya
   normalizado — ver bug `config-callback` corregido).
2. Invocar la tool `get_open_positions` por cualquier cliente MCP stdio.
3. Observar: error genérico "Error executing tool get_open_positions";
   en stderr del servidor: `AttributeError: 'Response' object has no
   attribute 'get'` (y, de corregirse solo el unwrap, fallaría luego el
   mapeo por forma de payload: `payload.get("accountDetails")` sobre una
   lista).

Alternativa determinística sin red (en proceso):

```python
import schwabdev
from schwab_mcp.config import load_config
from schwab_mcp.positions import get_open_positions
cfg = load_config()
client = schwabdev.Client(cfg.app_key, cfg.app_secret, cfg.callback_url,
                          tokens_db=cfg.token_db, open_browser_for_auth=False)
get_open_positions(client)   # AttributeError: 'Response' object has no attribute 'get'
```

## Suspected Code Paths

- `src/schwab_mcp/positions.py:388` — `payload = client.account_details_all(fields="positions")`:
  usa la `Response` del SDK directamente como si fuera un dict (sin
  `.json()` ni clasificación de estados HTTP). Es el mismo defecto corregido
  para 006 en `transactions.py` vía `schwab_mcp.provider.response_json()`.
- `src/schwab_mcp/positions.py:430-459` — `_detect_account_failures(payload)`,
  `_extract_successful_accounts(payload)` y `_transform_provider_payload(payload)`
  leen `provider_payload.get("accountDetails", [])`: forma de payload que
  el endpoint real no devuelve (real: lista top-level con
  `securitiesAccount` por elemento).
- `src/schwab_mcp/positions.py:175-177` — `_hash_account(account_number)`:
  hash local SHA-256 truncado del número de cuenta. No es el identificador
  opaco del proveedor (`hashValue` de `linked_accounts()`), así que los
  `account_hash` de `get_open_positions` no son consistentes con los de
  `get_transaction_history` (FR-008 de 006 exige consistencia de cobertura
  de cuentas). Además, un SHA-256 truncado a 8 hex de un número de cuenta
  corto es fuerza-bruteable — el identificador correcto y seguro es el
  `hashValue` del proveedor.
- `tests/unit/test_positions.py:49-60` — `FakePositionsClient` devuelve
  dicts con la forma asumida: los tests pinnan el contrato equivocado y por
  eso la suite está verde pese al bug en vivo.

## Root Cause Hypothesis

Feature 003 se construyó (y testó) contra una forma de payload supuesta
(`{"accountDetails": [{"accountNumber", "positions"}]}` con respuestas ya
parseadas) que no coincide con el contrato real del SDK ni del endpoint
`GET /trader/v1/accounts?fields=positions` (que devuelve `requests.Response`
con lista de `{aggregatedBalance, securitiesAccount}` y no expone el hash
de cuenta — hay que cruzar `securitiesAccount.accountNumber` con el
`hashValue` de `linked_accounts()`). Confianza: **alta** — reproducido en
vivo y confirmado inspeccionando el SDK instalado y el payload real.

## Proposed Remediation

**Preferred**: alinear `positions.py` con el patrón ya probado de
`transactions.py` (feature 006):

1. **Unwrap** (reuso, cero código nuevo): `payload = response_json(...)` de
   `src/schwab_mcp/provider.py` para `account_details_all()` y para el
   nuevo upcall `linked_accounts()`; errores 401/403 → `reauth_required`,
   5xx/408/429 → `transient_failure` (clasificación ya centralizada).
2. **Adaptación de forma**: nuevo normalizador (puro, testeable) que
   convierte la lista real
   `[{"aggregatedBalance", "securitiesAccount": {...}}]` en el formato
   interno `{"accounts": [{"accountHash", "positions": [...]}]}` que ya
   consume `map_provider_positions`. El sub-mapeo de campos de posición
   (`longQuantity`, `averagePrice`, `marketValue`, `instrument.symbol`,
   `assetType`, …) coincide con las claves reales observadas, así que el
   core de mapeo no cambia.
3. **Cruce accountNumber↔hashValue**: obtener
   `response_json(client.linked_accounts())` → mapa
   `{accountNumber: hashValue}`; el normalizador resuelve el hash real por
   `accountNumber` (los elementos de `account_details_all` no traen
   `hashValue`). Cuenta sin match en el cruce → `partial_failure` con
   `accounts_failed` (nunca hash inventado).
4. **Retiro del hash local**: eliminar `_hash_account` (o dejarlo solo si
   algún test lo exige — preferible eliminarlo) y usar el `hashValue` del
   proveedor en `accounts_failed` también.
5. `server.py` no requiere cambios (la tool ya está registrada; no hay
   inputs a validar).

**Alternatives** (optional):

- A cambio mínimo: solo unwrap con `.json()` y ver qué MappingError surge
  después. Rechazado: entrega una tool rota de otra forma (resultados
  vacíos/garbage) y repite el anti-patrón de testear contra fideos falsos.
- Usar `GET /accounts/{hash}?fields=positions` por cuenta (como hace 006
  con `transactions`): trae el hash por construcción y errores por cuenta
  reales, a costa de 1 upcall por cuenta (el bulk `account_details_all`
  es 1 llamada total). Rechazado por ahora: más upcalls y reescritura de
  la orquestación; el bulk + cruce cumple con 1 upcall extra fija.

**Files likely to change**:

- `src/schwab_mcp/positions.py` (unwrap, normalizador de forma, cruce de
  hashes, baja de `_hash_account`)
- `tests/unit/test_positions.py` (fakes que devuelven `requests.Response`
  con la forma real + casos de reauth/transitorio/parcial)
- `tests/unit/test_no_secrets_in_output.py` (asegurar que ningún campo
  lleve `accountNumber` real — solo `hashValue`)
- `docs/tools.md` + `docs/CHANGELOG.md` (documentación al día)
- `specs/003-list-open-positions/` — nota de corrección del data-model
  asumido (similar a lo hecho en research.md de 006)

**Tests to add or update**:

- Test de regresión (Rojo primero, constitución I): fake cuya
  `account_details_all()` devuelve `requests.Response` real con la lista
  real → `outcome=ok`, posiciones mapeadas, `account_hash == hashValue`.
- 401/403 → `reauth_required`; 500 → `transient_failure` con
  `retryable=true`; JSON malformado → `transient_failure`.
- `accountNumber` sin match en `linked_accounts()` → `partial_failure`
  con `accounts_failed` (sin hash local).
- Per-account `error` (si se conserva `_detect_account_failures`):
  definir qué dispara ese camino con la forma real o marcarlo obsoleto.
- No-secretos: `accountNumber` nunca aparece en la salida.

## Risks & Considerations

- **Cambios de identificador visible**: los `account_hash` de la tool
  cambian de "sha256[:8] del número" al `hashValue` real — breaking para
  cualquier agente que haya cacheado hashes de `get_open_positions`;
  a cambio, quedan consistentes con `get_transaction_history` (y con el
  resto del ecosistema). Registrar en el CHANGELOG.
- **Upcall adicional**: `linked_accounts()` suma 1 llamada por consulta
  (2 totales); impacto mínimo en el presupuesto p95 de 5 s, medir en
  test de performance existente.
- **Orden/duplicados del cruce**: si `linked_accounts()` y
  `account_details_all()` difieren en orden o contenido (cuenta nueva
  entre ambas llamadas), matchear por `accountNumber` y fallar explícito
  lo no matcheado — nunca asumir por índice.
- **Credencial safety**: eliminar el hash local reduce la superficie
  (SHA-256 truncado de números de cuenta cortos es reversible por
  fuerza bruta).
- **Observabilidad**: los eventos `positions_query_*` no cambian; el
  camino de partial_failure conserva vocabulario del contrato de 003.

## Open Questions

- [NEEDS CLARIFICATION: ¿el endpoint bulk devuelve las cuentas siempre en
  el mismo orden que `linked_accounts()`? El plan matchea por
  `accountNumber`, así que el orden no debería importar — validar con la
  app real de una sola cuenta (ya observado: orden consistente con 1
  cuenta).]
- [NEEDS CLARIFICATION: ¿hay cuentas multi-tipo (margen/efectivo) que
  aparezcan dos veces en `account_details_all`? Si sí, definir dedup por
  `accountNumber` para el cruce.]
