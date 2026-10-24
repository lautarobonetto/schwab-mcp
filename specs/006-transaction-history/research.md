# Research: Account Transaction History (006)

Fecha: 2026-10-23. Fuente primaria: código fuente del SDK instalado
(`schwabdev==4.0.0`, leído en `.venv/.../schwabdev/{client,validation}.py`),
docs de schwab-py (SDK de referencia independiente) y evidencia
operacional de terceros (regress#125). Cada decisión cita su evidencia.

## R1. Endpoint upstream y límites

**Decision**: usar `GET /trader/v1/accounts/{accountHash}/transactions`
vía `schwabdev.Client.transactions(accountHash, startDate, endDate,
types, symbol)`.

**Rationale**: firma verificada contra el SDK instalado. Límites
documentados en el docstring del SDK: **máx 3000 transacciones por
llamada; rango de fechas máx 1 año** — consistente con la ventana de 1
año decidida en clarify Q1 (FR-004). `startDate`/`endDate` van en
ISO-8601 (el SDK las convierte con `TimeFormat.ISO_8601`). `symbol` es
opcional y filtra upstream. Nota: la doc de schwab-py menciona "60 days"
para `start_date`, pero es su documentación de `get_orders` arrastrada;
el docstring del SDK instalado (fuente de verdad de este repo) dice 1
año. El quickstart incluye una verificación live de la ventana.

**Alternatives considered**: endpoint `account_orders_all`-style para
todas las cuentas — **no existe** para transactions (el SDK solo tiene
`transactions` por cuenta); por lo tanto la orquestación itera
`linked_accounts()` (igual que hace `positions.py` con
`account_details_all`, que aquí no aplica).

## R2. Formato de `types` y bypass del validador del SDK

**Decision**: 1 upcall por cuenta con `types` = lista completa de los 15
tipos documentados, **separada por comas**:
`"TRADE,RECEIVE_AND_DELIVER,DIVIDEND_OR_INTEREST,ACH_RECEIPT,ACH_DISBURSEMENT,CASH_RECEIPT,CASH_DISBURSEMENT,ELECTRONIC_FUND,WIRE_OUT,WIRE_IN,JOURNAL,MEMORANDUM,MARGIN_CALL,MONEY_MARKET,SMA_ADJUSTMENT"`.
Para esta única llamada se desactiva el validador de parámetros del SDK
de forma **acotada y reversible** (toggle de `client._validator.enabled`
dentro de un helper de `transactions.py`, restaurado en `finally`).

**Rationale**: (a) el validador del SDK (`validation.py:_v_transactions`)
usa `_vin`, que exige que `types` sea **un solo valor** del set —
rechazaría la lista separada por comas; (b) el formato upstream
**sí** acepta tipos separados por comas: es el formato documentado que
envían las dos librerías de referencia (schwab-py envía
`','.join(transaction_types)`) y la investigación de regress#125 lo
verificó contra ambas ("Comma-separated is the documented working
format"); (c) la alternativa de 1 upcall por tipo serían 15 llamadas
secuenciales por cuenta (~3–7 s por cuenta) — viola el presupuesto
SC-001 de ≤ 5 s p95 y multiplica la superficie de rate limiting; (d) el
SDK está pineado (`schwabdev==4.0.0`), así que el atributo privado
tocado está bajo control de versión; el helper centraliza el bypass con
comentario y test propio.

**Alternatives considered**:
- *1 upcall por tipo por cuenta*: determinista con el validador activo,
  pero latencia inaceptable (ver (c)) y más carga al proveedor.
- *`params` repetidos* (`types=TRADE&types=...`): requeriría llamar a
  `client._request` (más privado aún que el toggle) y regress#125
  descartó que cambie el resultado.
- *`validate_params=False` al construir el cliente*: desactiva la
  validación de **todas** las calls (positions, quotes, etc.) — pérdida
  injustificada de seguridad en el resto de la app.

## R3. Tope upstream de 3000 transacciones (completitud)

**Decision**: si una respuesta por cuenta devuelve exactamente 3000
movimientos (tope upstream), la tool **divide el rango por bisección** y
re-consulta cada mitad recursivamente (mismo tipo-lista), fusionando y
deduplicando por `(account_hash, activityId)`; profundidad acotada (el
mínimo sub-rango es 1 día). No hay paginación upstream, así que el split
es el único camino a completitud garantizada (SC-004).

**Rationale**: FR-006/SC-004 prohíben truncado silencioso; el tope de
3000 es real (docstring del SDK). La bisección converge: un rango de 1
año con >3000 movimientos requiere pocas iteraciones para cuentas
personales; el costo extra solo se paga cuando realmente hay >3000
movimientos en el sub-rango.

**Alternatives considered**:
- *Reportar truncado y que el agente subdivida*: cumple el "no silencio"
  pero degrada SC-005 (el agente tendría que adivinar cómo partir).
- *Split fijo mensual siempre*: multiplicaría upcalls ×12 por cuenta en
  cada consulta — viola latencia/presupuesto sin necesidad.

## R4. Semántica de fechas y zona horaria

**Decision**: las fechas (`YYYY-MM-DD`) se interpretan en la zona
horaria del mercado de la cuenta (**America/New_York**, clarify Q2),
bordes inclusivos: `startDate` = `T00:00:00-05:00/-04:00` (offset real
del día vía `zoneinfo`), `endDate` = `T23:59:59` del día fin (enviado
como el instante final inclusivo en ISO-8601). `end_date` en el futuro
se rechaza en validación (edge case del spec).

**Rationale**: coincide con el calendario operativo del mercado y con
cómo el dueño lee sus estados de cuenta; `zoneinfo` es stdlib (Principio
III). El mismo rango pedido dos veces produce el mismo conjunto
(determinismo exigido por el spec).

## R5. Normalización de categorías (enum cerrado) y ajuste al spec

**Decision**: mapeo provider→categoría normalizada:

| Tipo upstream | Categoría |
|---------------|-----------|
| `TRADE` | `trade` |
| `RECEIVE_AND_DELIVER` | `transfer` |
| `ACH_RECEIPT` / `ACH_DISBURSEMENT` / `CASH_RECEIPT` / `CASH_DISBURSEMENT` / `ELECTRONIC_FUND` / `WIRE_IN` / `WIRE_OUT` | `transfer` |
| `DIVIDEND_OR_INTEREST` | `dividend_or_interest` |
| `JOURNAL` | `adjustment` |
| `SMA_ADJUSTMENT` | `adjustment` |
| `MEMORANDUM` / `MARGIN_CALL` / `MONEY_MARKET` | `other` |

El enum de categorías se **amplía con `dividend_or_interest`** respecto
del decidido en clarify Q3 (que listaba `interest` y `dividend` como
valores separados): el proveedor reporta dividendos e intereses como un
único tipo `DIVIDEND_OR_INTEREST` y no existe campo discriminatorio en
el payload, así que la proyección fiel (spec: "faithful projection") es
una categoría combinada. Los valores `interest`, `dividend`, `fee` y
`corporate_action` quedan **reservados** en el enum (sin mapeo en v1).
El texto original del proveedor (`type` + `description` completos) va
solo en el detalle extendido (FR-007, clarify Q3). El spec (FR-002) se
actualiza con el valor añadido.

**Rationale**: clasificar dividendos vs. intereses por heurística de
description sería fuzzy matching, explícitamente rechazado en las
Assumptions del spec; inventar una categoría no es posible sin
inventar datos.

**Alternatives considered**: mapear `DIVIDEND_OR_INTEREST → other`
(fiel pero degrada el valor para el agente); heurística sobre
`description` (viola "no fuzzy matching").

## R6. Validación del filtro por instrumento

**Decision**: cuando `symbol` está presente, la tool hace **1 upcall**
`instruments(symbols=[symbol], projection="symbol-search")`. (Corrección
2026-10-23, hallada en prueba en vivo: el validador del SDK rechaza
`SYMBOL_SEARCH`; las proyecciones válidas son minúsculas.) Si el símbolo
no existe → error explícito
`instrument_not_found` (FR-009c, edge case del spec: distinguir
"instrumento inexistente" de "sin movimientos"). Si existe, el filtro
viaja upstream (`symbol=`) y un resultado vacío significa genuinamente
"sin movimientos para ese instrumento en el rango" (`detail:
no_movements_for_instrument`).

**Rationale**: el endpoint upstream no distingue "símbolo malo" de
"sin resultados"; sin la validación, SC-005 (decisión sin ambigüedad)
es imposible de cumplir. El costo es 1 upcall adicional solo cuando hay
filtro.

## R7. Paginación MCP-side

**Decision**: paginación sin estado de servidor: la tool ordena el
historial fusionado por `occurred_at` ascendente (desempate:
`account_hash`, `activityId`), entrega páginas de **50 movimientos**
(clarify Q4) desde `offset` (default 0), y reporta `total_count`,
`returned`, `has_more` y `next_offset` cuando `has_more=true`. El agente
repite la misma consulta con el `next_offset` para continuar.

**Rationale**: el upstream no tiene paginación (entrega todo ≤ tope
manejado en D3), así que la paginación es un recorte MCP-side
determinista; offset sobre una lista ordenada es trivial de testear
(SC-006: cero duplicados, cero gaps). Caveat documentada en el
contrato: si el agente tarda entre páginas y llegan movimientos nuevos,
el offset puede desplazarse — paginar pronto; la herramienta es
stateless y no promete consistencia entre páginas.

**Alternatives considered**: token de continuación con firma/estado →
complejidad injustificada (KISS); cursor por fecha del último movimiento
→ ambiguo ante fechas idénticas.

## R8. Riesgo operacional: `200 OK + []` sin permiso de lectura

**Decision**: la herramienta **no inventa errores** ante un resultado
vacío: devuelve `outcome: ok, detail: no_movements, total_count: 0`
(proyección fiel del upstream). El riesgo conocido — el endpoint puede
devolver `200 + []` cuando la app/cuenta no tiene permiso de lectura de
transacciones (app tier sin Trading Production, o cuenta sin
thinkorswim habilitado; evidencia regress#125) — se mitiga con
**documentación** en `docs/tools.md` y `quickstart.md`: si el rango es
amplio y la cuenta tiene actividad visible en schwab.com pero la tool
devuelve vacío persistentemente, la causa probable es permiso de la
app/cuenta, no datos.

**Rationale**: desde la respuesta no es distinguible un vacío genuino de
un vacío por permiso (regress#125 documentó que todas las formas de
filtro devuelven `200 + []`); fabricar un error sería un falso positivo
para cuentas genuinamente vacías (KISS + fidelidad). La doc le da al
agente la señal de diagnóstico.

## R9. Reuso del vocabulario y canales existentes

**Decision**: `TransactionsResult` replica el patrón de `PositionsResult`
(feature 003): `outcome ∈ {ok, partial_failure, transient_failure,
reauth_required}`, `retryable` (true solo en transient), `detail` enum
cerrado, `accounts_failed` solo en partial, `retrieved_at` ISO-8601 UTC.
Errores de autenticación vía taxonomía de `errors.py`; upcalls bajo
`tokens.retry_call` (1 intento: sin reintentos internos, FR-010);
auditoría vía `log.auth_event` + redaction filter (FR-011). Registro de
la tool en `server.py` con `MCPServer.add_tool` + `structured_output`
(patrón de 003/005).

**Rationale**: un solo vocabulario de outcomes en todo el MCP (DRY);
los agentes ya conocen el playbook de decisión de `docs/tools.md`.

## R10. Moneda

**Decision**: `currency` por movimiento; el upstream no expone campo de
moneda por transacción y las cuentas brokerage del proyecto son
USD-denominated → default `"USD"` documentado en el data model. Sin
conversión (spec Assumptions).

**Alternatives considered**: omitir currency (viola FR-005); inferir por
instrumento (fuzzy, rechazado).
