# Research: Extracción de Cadena de Opciones con Filtros

Feature: 008-extract-option-chain | Date: 2026-10-23

## R1 — Endpoint del proveedor y mapeo de filtros

**Decision**: usar `schwabdev.Client.option_chains(symbol, ...)` (endpoint
`/marketdata/v1/chains` del Schwab Trader API) con:

- `contractType`/`optionType` ← filtro de tipo: `both→ALL`, `calls→CALL`,
  `puts→PUT`.
- `strikeCount` ← límite de strikes por lado: la API devuelve N strikes
  por encima **y** por debajo del dinero, lo que coincide con la semántica
  del filtro (50 por lado por defecto).
- `fromDate` ← fecha actual; `toDate` ← fecha actual + tope de DTE
  (60 por defecto o el valor pedido). La API no acepta `fromDate` anterior
  a la fecha actual, así que la ventana de DTE se expresa como rango de
  fechas de vencimiento.
- `includeUnderlyingQuote: true` para obtener el precio vigente del
  subyacente (referencia del strike al dinero y metadato de la respuesta).

**Rationale**: es el único endpoint de cadenas expuesto por el SDK ya
integrado; mapea 1:1 con los filtros de la spec y evita traer vencimientos
fuera del rango DTE (reducción de volumen en origen, no solo en destino).

**Alternatives considered**:
- `option_expiration_chain` (solo fechas de vencimiento): útil como
  enumeración previa, pero duplicaría upcalls para la misma información que
  ya trae el payload de `option_chains` (claves `callExpDateMap` /
  `putExpDateMap`). Rechazado por DRY/KISS.
- Param `daysToExpiration` de la API: opera como valor puntual, no como
  tope de rango. Rechazado.

## R2 — Selección de la ventana de 5 strikes por delta objetivo

**Decision**: la API no filtra por delta, así que la selección es un
**post-filtro local**:

1. Cuando hay delta objetivo, el fetch interno pide
   `strikeCount = max(límite pedido, 100)` (cota interna 100) para
   garantizar que la zona del delta objetivo esté dentro de la ventana
   devuelta por la API; cuando no hay delta objetivo, se pide el límite
   pedido (default 50).
2. Por cada vencimiento del payload y por cada tipo incluido (CALLs y
   PUTs por separado, delta en valor absoluto):
   - identificar el contrato con delta más cercana al objetivo;
   - devolver ese strike más los dos strikes contiguos de cada lado
     (hasta 5, o todos los disponibles alrededor).
3. Si el objetivo no queda acotado dentro de la ventana interna (delta
   objetivo más profunda que los strikes fetchados), se hace **una**
   segunda llamada ampliando la ventana (cota 200); si sigue sin acotarse,
   se devuelven los contratos disponibles más cercanos al objetivo.

**Rationale**: la delta es monótona en el strike dentro de cada tipo, así
que "5 alrededor del más cercano" es determinista y verificable; pedir
strikeCount interno mayor solo cuando hay filtro de delta evita inflar el
volumen del caso por defecto.

**Alternatives considered**:
- Pedir siempre `range="ALL"` (toda la curva): volumen en origen
  innecesario y riesgo documentado por el SDK de "Body buffer overflow"
  en respuestas grandes. Rechazado.
- Iterar vencimiento por vencimiento: multiplica upcalls; rechazado.

## R3 — DTE y ordenación de vencimientos

**Decision**: DTE = días de calendario entre la fecha actual (local del
servidor, fecha de la consulta) y la fecha de vencimiento; los
vencimientos se ordenan ascendente por fecha. El tope vigente (60 por
defecto o el valor pedido) filtra vencimientos con DTE > tope. Un DTE
pedido que excluye todos los vencimientos produce la respuesta explícita
de cadena vacía (FR-009), no un error.

**Rationale**: coincidir con la lectura operativa del trader (los DTE de
vencimientos semanales se cuentan en días de calendario) y con la ventana
`fromDate/toDate` de la API.

**Alternatives considered**: DTE en días de mercado; rechazado porque la
API filtra por fechas de calendario y el caso de uso (selección de
vencimiento) usa días corridos.

## R4 — Presupuesto de tokens y esquema compacto

**Decision**:

- Esquema de salida **columnar por strike**: cada vencimiento contiene
  una lista de filas de strike; cada fila tiene el strike y como máximo
  dos arrays de valores (`call` y `put`) en un **orden de columnas
  documentado** en el propio payload (`contract_fields`). Esto elimina la
  repetición de nombres de campo por contrato (mayor costo del formato
  clave-valor) y la repetición del valor de strike entre piernas.
- Redondeo determinista: precios/valores a 2 decimales, griegas e IV a 4
  decimales.
- Campos ausentes → `null` explícito en su columna (cumple FR-007 con
  costo mínimo); no se inventan valores.
- Test de presupuesto (`tests/performance/test_options_chain_budgets.py`)
  mide la serialización de un fixture representativo (subyacente líquido,
  ~12 vencimientos, 100 strikes por vencimiento) contra el presupuesto
  normativo de 75.000 tokens con defaults y < 3.000 con `delta_target`
  (SC-002; aproximación: caracteres/4).

**Rationale**: la combinación de defaults de la spec (50/lado × 2 tipos ×
~12 vencimientos × el superset curado) es inherentemente voluminosa; el
esquema columnar es la única palanca de compactación que no viola FR-006
(superset curado) ni FR-002/FR-005 (defaults). **Resolución de la
clarificación 2026-10-24**: se mantiene el default de 50 (decisión del
usuario) y el presupuesto normativo con defaults se fija en **≤75.000
tokens** (SC-002), con **<3.000** para llamadas con `delta_target`;
justificación registrada en plan.md (Complexity Tracking, Principio V).
La salida declara el tamaño esperado en `docs/tools.md`.

**Alternatives considered**:
- Formato clave-valor por contrato: ~2–3× más tokens. Rechazado.
- Recortar campos de baja utilidad (open/high/low/close de la pierna):
  FR-006 quedó acotado al superset curado `contract_fields` + modo
  extendido (clarificación 2026-10-24), por lo que este recorte ya no es
  necesario; el passthrough `extended` cubre el resto.
- Paginación: viola FR-011 (una sola invocación). Rechazado.
- Reducir defaults (p. ej. 25 strikes/lado): rechazado por decisión del
  usuario en la clarificación 2026-10-24 (el default 50 se mantiene y el
  presupuesto sube a 75k con justificación registrada).

## R5 — Errores, política de parciales y reutilización

**Decision**:

- Unwrapping y clasificación de errores: reutilizar
  `provider.response_json` (401/403 → re-auth; 5xx/408/429 →
  `ConnectivityError`; otros 4xx → `ValueError` de validación) y
  `tokens.retry_call` para transitorios.
- Política FR-013: si la fuente falla o un vencimiento entero viene sin
  datos (mapa de vencimiento vacío o ausente), la tool aborta con error
  estructurado sin devolver cadena parcial.
- Validación de filtros **antes** de cualquier upcall: tipo de opción
  desconocido, delta con |delta| ∉ (0,1), strikes ≤ 0, dte ≤ 0, símbolo
  vacío → error de validación accionable.
- Errores de dominio nuevos (mínimos, mismos principios que 006):
  `no_options_listed` (el instrumento no tiene opciones) y
  `no_expirations_in_range` (el tope de DTE excluye todos los
  vencimientos) — comunicados como resultado estructurado, no como error
  de transporte (FR-009).

**Rationale**: reutiliza la taxonomía única ya probada (Principios II y
III) y separa "sin datos" de "falló" para que el agente pueda decidir el
paso siguiente.

**Alternatives considered**: taxonomía nueva para esta tool; rechazada
por duplicación.

## R6 — Curado de campos por contrato

**Decision**: incluir por pierna los campos que la fuente expone y que
aportan al análisis de posiciones de opciones, excluyendo ruido
estructural/de transporte:

- **Cotización**: `bid`, `ask`, `last`, `mark`, `markChange`,
  `markPercentChange`, `highPrice`, `lowPrice`, `openPrice`, `closePrice`.
- **Liquidez**: `totalVolume`, `openInterest`.
- **Riesgo/griegas**: `volatility` (IV), `delta`, `gamma`, `theta`,
  `vega`, `rho`, `theoreticalOptionValue`, `timeValue`.
- **Referencia**: `multiplier`, `daysToExpiration`, `tradeTime`,
  `deliverableNote` (relevante para asignación en LEAPs).
- **Excluidos**: `skipBars`, `isPitRanged`, `executable`,
  `settlementType`, `deliverables` (estructurales, sin valor de análisis;
  disponibles vía `extended=true` con passthrough del payload crudo,
  patrón de 003/006).

**Rationale**: cumple FR-006 ("todas las griegas y todos los valores
técnicos disponibles") con una curación determinista y declarada; el
passthrough `extended` preserva acceso al 100% del payload sin inflar el
formato curado.

**Alternatives considered**: passthrough crudo como formato único;
rechazado porque el payload de la API es de formato clave-valor verbose
(multiplica el costo de tokens ~2–3×) y mezcla metadatos estructurales.
