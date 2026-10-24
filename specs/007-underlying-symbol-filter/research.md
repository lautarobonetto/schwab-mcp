# Research: Underlying-Aware Symbol Filter and Underlying Reference

Feature: 007-underlying-symbol-filter | Date: 2026-10-24

## R1. Cómo armar el resultado filtrado dado que el proveedor no puede filtrar opciones por subyacente

**Decision**: cuando `symbol` está presente, la tool consulta el rango
**sin filtro upstream** (mismas upcalls que la consulta sin filtro) y
aplica el matching de las tres formas **localmente**, sobre el historial
fusionado y deduplicado que ya produce la orquestación de 006.

**Rationale**: verificado en vivo (2026-10-23/24, feature 006):
- `symbol=NOK` (subyacente) → el endpoint responde `200` con **0
  resultados** aunque hubo 14 transacciones de opciones de NOK en el
  período: el filtro upstream solo matchea el símbolo registrado de cada
  transacción, y las de opciones se registran bajo su símbolo OCC.
- `symbol="NOK   261218P00011000"` (OCC) → el endpoint rechaza la llamada
  con `HTTP 400 {"message":"symbol: Invalid Symbol"}`.

Por lo tanto ningún uso del parámetro `symbol` upstream entrega el
resultado que la spec exige. El barrido sin filtro + matcher local:
(1) garantiza la subset-consistency (FR-005) **por construcción** — el
resultado filtrado es literalmente un subconjunto del resultado sin
filtro del mismo rango; (2) no agrega upcalls (las upcalls son idénticas
a la consulta sin filtro); (3) reutiliza íntegra la orquestación,
bisección y deduplicación existentes.

**Alternatives considered**:
- *Filtro upstream como hoy + segundo barrido para opciones*: 2× upcalls
  por consulta, dos fusiones, y el primer conjunto ya es incompleto
  (misma limitación) — rechazado (KISS, V).
- *Consultar por cada símbolo OCC conocido del subyacente*: imposible
  saber de antemano qué OCC symbols registró la cuenta sin el barrido —
  rechazado.
- *Mantener el filtro upstream solo para match exacto y barrido
  adicional solo si hay opciones*: indistinguible en costo del barrido
  directo y agrega un camino condicional — rechazado (KISS).

Nota de comportamiento: al dejar de enviar `symbol` upstream, la consulta
filtrada también deja de sufrir el `HTTP 400` por símbolo OCC — el caso
OC/AC4 del spec (opción puntual) queda soportado sin llamadas extra.

## R2. Derivación del root (subyacente) desde el símbolo OCC registrado

**Decision**: el root de una opción es la porción previa a los últimos
15 caracteres del símbolo registrado (`root = symbol[:-15].strip()`),
anclaje derecho idéntico al ya verificado en vivo para posiciones
(`_parse_occ_option_symbol`, bug positions-response-unwrap: los últimos
15 caracteres son siempre `YYMMDD + C/P + strike×1000`).

**Rationale**: el estándar OCC rellena el root a 6 caracteres con
espacios (`AMD   261120P00630000` → root `AMD`); anclar por la derecha
hace el parseo independiente del padding. Validado en vivo: los
instrumentos OPTION reales traen `symbol`, `putCall`, `underlyingSymbol`
(pero no `strikePrice`/`expirationDate`) — el símbolo es la fuente
confiable.

**Reglas de fallback** (edge cases del spec):
- Si el tail de 15 caracteres no matchea el patrón OCC (no son dígitos
  en las posiciones esperadas, o el C/P no es `C`/`P`), el root no es
  identificable: el movimiento solo puede matchear por igualdad exacta
  del símbolo registrado (FR-001a) y **no** expone `underlying_symbol`
  en el output curado.
- El root se reporta tal como la fuente lo registra (tras quitar
  padding), sin reformatear.

**Alternatives considered**:
- *Parseo del root anclado a la izquierda (6 chars fijos)*: rompe con
  roots de longitud distinta o padding inconsistente — rechazado.
- *Usar `instrument.underlyingSymbol` del payload extendido*: no está
  disponible en el modo curado (solo `extended=true`) y el campo puede
  venir vacío; el símbolo OCC es la fuente completa — rechazado como
  fuente primaria (queda en extended como passthrough).

## R3. Validación dual del filtro (clarificación C del spec)

**Decision**: mantener el upcall `instruments(symbols=[filtro],
projection="symbol-search")` como primer paso (un solo lookup, como hoy).
Si el directorio **resuelve** el filtro → continuar (comportamiento
actual). Si **no resuelve** → NO fallar: proceder con el barrido y
clasificar al final — si hay movimientos que matcheen (símbolo
registrado, root u OCC completo), devolverlos con `ok`; si no hay
ninguno, devolver el error `instrument_not_found` nombrando el filtro
(como hoy).

**Rationale**: implementación directa de la clarificación C. El caso
`CURRENCY_USD` (no resuelto en el directorio pero presente como símbolo
registrado en movimientos) pasa de `instrument_not_found` a devolver sus
movimientos — cambio de comportamiento documentado en el contrato y en
`docs/tools.md` (el caveat de 006 se actualiza).

**Alternatives considered**:
- *Validación sin cambios (A del clarify)*: mentiría con
  `instrument_not_found` cuando hay actividad con ese root — rechazado
  por el usuario.
- *Validar el root derivado en vez del filtro crudo*: el filtro puede
  ser un OCC completo o un subyacente; el lookup del filtro crudo es el
  contrato vigente — rechazado.

## R4. Case-insensitivity del matching

**Decision**: normalizar el filtro y los candidatos a mayúsculas para
comparar (`filter.upper() == symbol.upper()` / `root.upper()`); el
output reporta los símbolos tal como la fuente los registra, sin
reformatear.

**Rationale**: los roots OCC son mayúsculas por estándar; los agentes
pueden enviar `nok`. Comparar en mayúsculas es determinista y evita
dependencia del caso de entrada. Los símbolos de la fuente ya son
mayúsculas en la práctica — la normalización es idempotente.

**Alternatives considered**: matching case-sensitive + error
instructivo — fricción innecesaria para el caso dominante.

## R5. Impacto del campo `underlying_symbol` en el presupuesto de 16 KB

**Decision**: `underlying_symbol` se agrega al output curado solo para
movimientos de opción (`Optional`, excluido con `exclude_none` como los
campos opcionales existentes). Impacto estimado: ~25 bytes JSON por
movimiento de opción (`"underlying_symbol":"AMD"` + overhead); una
página de 50 movimientos todos-opción agrega ~1.2 KB sobre el máximo
actual.

**Rationale**: la página default de 006 midió ≤ 16 KB con 50 movimientos
extended=false; el margen del presupuesto se verifica con el test de
token-usage existente extendido al caso peor (50 movimientos de opción,
cada uno con root). Si el caso peor excediera 16 KB, la constitución
exige justificación registrada — research preliminar indica margen
suficiente (página de 50 curada ≈ 8-9 KB hoy).

**Alternatives considered**: un campo siempre-presente (incluye
`null`) — desperdicio de tokens; solo-OPTION + `exclude_none` es lo ya
establecido por el patrón de `symbol`/`instrument_type`.

## R6. Semántica del `detail` con el nuevo matching

**Decision**: vocabulario de `detail` sin cambios: `history_retrieved`,
`no_movements`, `no_movements_for_instrument` (este último ahora significa
"nada matchea el filtro en ninguna forma"). Con la validación dual,
`instrument_not_found` solo aparece cuando no hay match y el directorio
no resolvió el filtro.

**Rationale**: no ampliar el enum cerrado (data-model de 006) evita
cambios de contrato en los outcomes; la semántica del detail existente
se refine sin renombrar nada.

**Alternatives considered**: un detail nuevo
`no_movements_for_underlying` — duplicaría significado (DRY, II).

## R7. Subset-consistency: cómo se prueba

**Decision**: la propiedad se testea a nivel unitario comparando, para
el mismo rango y fixtures, el resultado filtrado contra el filtrado
local del resultado sin filtro (misma función matcher); la prueba live
de quickstart la verifica contra la API real con un subyacente con
actividad de ambos tipos.

**Rationale**: con R1 (barrido + matcher local) la propiedad es
estructural; el test la fija para evitar regresiones si el plan de
implementación introduce atajos upstream.

**Alternatives considered**: comparar contra el proveedor en el test —
no determinista.
