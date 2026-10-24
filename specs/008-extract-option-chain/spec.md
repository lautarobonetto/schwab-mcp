# Feature Specification: Extracción de Cadena de Opciones con Filtros

**Feature Branch**: `008-extract-option-chain`

**Created**: 2026-10-23

**Status**: Draft

**Input**: User description: "quiero agregar una nueva tool al mcp, que permita extraer toda la cadena de opciones de un instrumento. Para que no sea muy voluminoso el resultado que debe devolver el MCP, quiero que la tool tenga todos los siguientes filtro opcionales: (1) cantidad máxima de strikes a traer, aplica para ambos lados del strike, valor predeterminado 50; (2) filtrar solo CALLs, solo PUTs, o ambos, valor predeterminado ambos; (3) filtrar por Delta buscado: si se busca delta 0.20, el filtro trae las opciones de los 5 strikes que estén alrededor del Delta 0.20, valor predeterminado nulo (no filtra por delta); (4) filtro de DTE, valor predeterminado nulo y significa que trae todos los vencimientos hasta los 60 días como máximo. Nota: la cadena debe traer todas las griegas y todos los valores técnicos disponibles para poder hacer buenos análisis de posiciones de opciones complejas (Iron Condors, Naked puts, Calendars, LEAPs, etc)."

## Clarifications

### Session 2026-10-23

- Q: Cuando el filtro de delta objetivo está activo y el tipo de opción es "ambos", la ventana de 5 strikes se calcula por separado para CALLs y PUTs? → A: ventana **por tipo**: por cada vencimiento, hasta 5 strikes de CALLs alrededor del contrato CALL más cercano al delta objetivo y hasta 5 strikes de PUTs alrededor del contrato PUT más cercano al delta objetivo (comparando delta en valor absoluto); ninguna ventana compartida entre tipos.
- Q: Cuál es el presupuesto máximo de tamaño de respuesta (en tokens aproximados) que debe respetar una invocación con todos los filtros por defecto? → A: **30.000 tokens** por invocación con filtros por defecto; si una cadena real lo excede, se compacta el formato de salida sin recortar griegas ni violar los límites de filtros.
- Q: Cuando el filtro de delta objetivo está activo, la ventana de 5 strikes se aplica a todos los vencimientos dentro del tope de DTE vigente, o solo al vencimiento más próximo? → A: a **todos los vencimientos** dentro del tope de DTE vigente (por defecto 60 días), uno por uno; el filtro de delta no restringe el conjunto de vencimientos.
- Q: Cuando la fuente de datos de mercado falla o devuelve una cadena incompleta, la tool debe abortar con un error estructurado sin datos parciales, o devolver lo que tenga marcando lo faltante? → A: **error estructurado sin datos parciales**: si la fuente falla o un vencimiento entero viene sin datos, la tool no devuelve cadena y reporta el motivo; los campos puntuales faltantes dentro de contratos presentes se marcan como no disponible (FR-007).

### Session 2026-10-24

- Q: Para que la respuesta con filtros por defecto sea predecible en tamaño, qué estrategia elegimos: subir el presupuesto de tokens a la medida real, o bajar el default de strikes por lado? → A: **default de 50 strikes por lado se mantiene**; el presupuesto de tokens con filtros por defecto sube a **≤75.000 tokens** (justificación registrada en plan.md, Principio V de la constitución); con `delta_target` activo el objetivo chico (<3.000 tokens) se mantiene. Esta decisión **reemplaza** el presupuesto de 30.000 tokens de la sesión 2026-10-23.
- Q: Cómo hacemos verificable el criterio de que el agente completa el análisis de una posición compleja sin necesidad de una segunda invocación? → A: **cada escenario de validación (quickstart S1–S3, cubriendo Iron Condor, Naked Put, Calendar y LEAP) se completa con exactamente 1 invocación a la tool**, verificado en los tests de integración.
- Q: Qué alcance exacto debe tener el set de campos técnicos por contrato: superset curado declarado en la respuesta (con acceso al resto vía modo extendido), o literalmente todos los campos de la fuente? → A: **superset curado declarado en `contract_fields`** (cotización, liquidez, IV, las 5 griegas, valores teóricos, time value, multiplicador, trade time, nota de entregables); los campos estructurales restantes de la fuente quedan accesibles vía modo extendido con el payload crudo completo.
- Q: Qué objetivo de latencia unificamos como criterio de éxito: el más exigente de plan y contrato (≤5 s p95) o el más laxo de la spec (<10 s)? → A: **≤5 segundos p95 por invocación**, unificado en spec, plan y contrato.
- Q: Cómo verificamos el cumplimiento de la ventana de 5 strikes por delta: fixtures en la suite automática, con validación live adicional, o solo cadenas reales? → A: **suite automática con fixtures representativos** (incluyendo bordes: delta en el límite de la curva, strikes faltantes) **+ validación contra cadena real como paso del quickstart S2**.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Analizar una posición de opciones compleja con una sola consulta (Priority: P1)

Un agente de IA que asesora a un trader necesita construir un análisis de
una posición de opciones compleja (por ejemplo, un Iron Condor o un Naked
Put) sobre un instrumento. El agente invoca la tool con el identificador
del instrumento y los valores por defecto de los filtros, y recibe la
cadena de opciones completa del instrumento con todos sus vencimientos
hasta 60 días, ambos tipos de opción (CALLs y PUTs), hasta 50 strikes por
lado alrededor del strike al dinero, y **todas** las griegas y todos los
valores técnicos disponibles para cada contrato. Con esa única respuesta el
agente puede identificar spreads verticales, seleccionar alas para el
condor y estimar el riesgo de la posición sin necesidad de consultas
adicionales.

**Why this priority**: es el caso de uso central de la tool: obtener toda
la información necesaria para analizar posiciones de opciones en una sola
invocación, sin exceder el volumen de datos que el agente puede consumir.

**Independent Test**: invocar la tool con un instrumento que tenga cadena
de opciones y verificar que la respuesta contiene, para cada vencimiento
dentro del rango de DTE por defecto, los strikes de ambos lados del
dinero (hasta el límite por defecto), ambos tipos de opción, y el set
completo de griegas y valores técnicos de cada contrato.

**Acceptance Scenarios**:

1. **Given** un instrumento con opciones listadas y varios vencimientos,
   **When** el agente invoca la tool solo con el identificador del
   instrumento (sin filtros), **Then** recibe los vencimientos dentro de
   los 60 días, ambos tipos de opción, hasta 50 strikes por lado del
   dinero por vencimiento, y para cada contrato todas las griegas y
   valores técnicos disponibles.
2. **Given** la respuesta de una invocación por defecto, **When** el
   agente la examina, **Then** cada contrato incluye al menos las cinco
   griegas clásicas (delta, gamma, theta, vega, rho) y los valores de
   mercado disponibles (precio de compra/venta, último, volumen, interés
   abierto, volatilidad implícita, y demás valores técnicos que la fuente
   exponga para ese contrato).
3. **Given** una posición de opciones compleja a analizar (Iron Condor),
   **When** el agente planifica la posición con los datos de la respuesta,
   **Then** no necesita invocar nuevamente la tool para completar el
   análisis dentro del rango de vencimientos y strikes recibidos.

---

### User Story 2 - Focalizar la consulta por tipo de opción y delta objetivo (Priority: P2)

Un agente que diseña una estrategia direccional o de renta (por ejemplo,
venta de puts cubiertos al delta 0.20) necesita ver solo las opciones
relevantes alrededor de ese delta. El agente invoca la tool indicando el
tipo de opción deseado (solo PUTs, por ejemplo) y un delta objetivo de
0.20; la tool devuelve, para cada vencimiento dentro del rango de DTE
vigente, las opciones de los 5 strikes que rodean al delta 0.20 en lugar
de toda la curva de strikes. Esto reduce drásticamente el volumen de la
respuesta y presenta exactamente la zona delChain donde se ejecutaría la
estrategia.

**Why this priority**: es el refinamiento más usado en la práctica para
selección de strikes por probabilidad (delta como proxy), y depende de la
tool base de la Historia 1.

**Independent Test**: invocar la tool con tipo de opción y delta objetivo
sobre un instrumento con opciones y verificar que, por cada vencimiento
elegible, se devuelven exactamente 5 strikes (o todos los disponibles si
hay menos) centrados alrededor del contrato cuya delta está más cerca del
objetivo, y que el tipo de opción excluido no aparece.

**Acceptance Scenarios**:

1. **Given** un instrumento con opciones, **When** el agente pide solo
   PUTs con delta objetivo 0.20, **Then** recibe únicamente contratos de
   tipo PUT y, por cada vencimiento dentro del rango de DTE, los
   contratos de los 5 strikes alrededor del delta 0.20.
2. **Given** un delta objetivo cuyo valor más cercano en la cadena queda
   en el borde de la curva de strikes listados, **When** la tool aplica el
   filtro de delta, **Then** devuelve hasta 5 strikes: los que existan
   alrededor de ese punto, sin inventar strikes inexistentes.
3. **Given** un tipo de opción pedido (CALL o PUT), **When** la tool arma
   la respuesta, **Then** ningún contrato del tipo no solicitado aparece
   en la respuesta.

---

### User Story 3 - Ajustar el volumen de la respuesta mediante límites explícitos (Priority: P3)

Un agente que necesita una vista amplia de la cadena (por ejemplo para
calendars o LEAPs con vencimientos lejanos) puede ajustar los límites: el
número máximo de strikes por lado del dinero y el horizonte máximo de
DTE. El agente invoca la tool aumentando el límite de strikes o el
horizonte de DTE según lo necesite, y la tool devuelve una respuesta
determinista acotada por esos límites. Por el contrario, un agente que
necesita una respuesta mínima reduce el límite de strikes y el horizonte
de DTE para minimizar el consumo de tokens.

**Why this priority**: es la palanca de control de volumen; complementa
pero no bloquea los casos de uso principales.

**Independent Test**: invocar la tool con distintos valores de límite de
strikes y horizonte de DTE y verificar que la cantidad de strikes por lado
y el conjunto de vencimientos devueltos respetan exactamente los límites
solicitados.

**Acceptance Scenarios**:

1. **Given** un instrumento con más de 50 strikes listados por lado,
   **When** el agente pide un límite de 10 strikes por lado, **Then** la
   respuesta contiene como máximo 10 strikes por lado del dinero para
   cada vencimiento, siempre incluyendo la zona del dinero.
2. **Given** un horizonte de DTE solicitado de 120 días, **When** la tool
   arma la respuesta, **Then** incluye todos los vencimientos del
   instrumento con DTE menor o igual a 120 días y ninguno más allá.
3. **Given** un horizonte de DTE solicitado de 7 días, **When** el
   vencimiento más próximo del instrumento vence en 10 días, **Then** la
   respuesta no contiene vencimientos y lo comunica de forma explícita en
   lugar de fallar.

---

### Edge Cases

- ¿Qué pasa cuando el instrumento no tiene opciones listadas? La tool lo
  comunica de forma explícita y estructurada (sin datos, sin error
  ambiguo), de modo que el agente pueda decidir el paso siguiente.
- ¿Qué pasa cuando el filtro de DTE excluye todos los vencimientos (por
  ejemplo, DTE máximo menor que el vencimiento más próximo)? La respuesta
  es una cadena vacía acompañada de una explicación explícita, no un
  error genérico.
- ¿Qué pasa cuando el delta objetivo no tiene un contrato cercano razonable
  (por ejemplo, delta objetivo 0.02 en una cadena corta)? La tool devuelve
  los strikes disponibles alrededor del punto más cercano al objetivo y
  hasta 5, sin fallar.
- ¿Qué pasa cuando el número de strikes disponibles es menor que el límite
  solicitado? Se devuelven todos los disponibles para ese lado.
- ¿Qué pasa con valores de filtro inválidos (delta fuera del rango
  esperado, límite de strikes cero o negativo, DTE negativo)? La tool
  rechaza la invocación con un mensaje de validación claro antes de
  consultar datos.
- ¿Qué pasa cuando la fuente de datos no informa alguna griega o valor
  técnico para un contrato puntual? El campo correspondiente se marca
  como no disponible de forma explícita, sin inventar valores.
- ¿Qué pasa cuando la fuente de datos falla o un vencimiento entero viene
  sin datos? La tool no devuelve cadena parcial: aborta con un error
  estructurado que describe el motivo, para que el agente pueda reintentar
  o informar al usuario (FR-013).
- ¿Qué pasa si el instrumento existe pero cotiza en un mercado cerrado con
  datos demorados? La tool devuelve los datos disponibles e indica la
  demora o el estado de los datos, para que el agente sepa qué tan
  frescos son.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El sistema MUST expone una tool de extracción de cadena de
  opciones que recibe el identificador del instrumento subyacente como
  único dato obligatorio.
- **FR-002**: La tool MUST aceptar un filtro opcional de cantidad máxima
  de strikes por lado del dinero, con valor predeterminado 50; el límite
  aplica simétricamente a los strikes por debajo y por encima del dinero
  para cada vencimiento devuelto.
- **FR-003**: La tool MUST aceptar un filtro opcional de tipo de opción
  con tres valores posibles: solo CALLs, solo PUTs, o ambos; el valor
  predeterminado es ambos.
- **FR-004**: La tool MUST aceptar un filtro opcional de delta objetivo;
  cuando está presente, por cada vencimiento dentro del tope de DTE
  vigente y por cada tipo de opción
  incluido (con "ambos", CALLs y PUTs se procesan por separado, comparando
  delta en valor absoluto) devuelve los contratos de los 5 strikes que
  rodean al contrato de ese tipo cuya delta está más cerca del objetivo
  (el punto más cercano más los dos strikes contiguos de cada lado,
  limitados a los strikes existentes); cuando está ausente, no filtra por
  delta.
- **FR-005**: La tool MUST aceptar un filtro opcional de DTE máximo;
  cuando está ausente aplica un tope por defecto de 60 días; cuando está
  presente, el valor indicado reemplaza ese tope por defecto. En ambos
  casos solo se devuelven vencimientos con DTE menor o igual al tope
  vigente.
- **FR-006**: Para cada contrato devuelto, la tool MUST incluir todas las
  griegas disponibles en la fuente (al menos delta, gamma, theta, vega y
  rho) y el superset curado de valores técnicos declarado en
  `contract_fields` dentro de la propia respuesta (cotización, liquidez,
  volatilidad implícita, valores teóricos, time value, multiplicador,
  trade time, nota de entregables); los campos estructurales restantes
  que exponga la fuente quedan accesibles vía modo extendido con el
  payload crudo completo.
- **FR-007**: Cuando un campo de griega o valor técnico no está disponible
  para un contrato, la tool MUST indicarlo explícitamente como no
  disponible en lugar de omitirlo silenciosamente o inventar un valor.
- **FR-008**: La tool MUST validar los filtros antes de consultar datos y
  rechazar con un mensaje de validación claro cualquier invocación con
  valores inválidos (tipo de opción desconocido, delta fuera del rango
  esperado para opciones compradoras/vendedoras según el tipo pedido,
  límite de strikes no positivo, DTE no positivo).
- **FR-009**: La tool MUST comunicar de forma explícita y estructurada los
  casos sin datos: instrumento sin opciones listadas y filtro de DTE que
  excluye todos los vencimientos.
- **FR-010**: La tool MUST incluir en la respuesta metadatos que permitan
  al agente interpretar la cadena: identificador del instrumento, estado o
  demora de los datos, y para cada vencimiento su fecha y su DTE.
- **FR-011**: La tool MUST devolver la respuesta completa en una única
  invocación, sin paginación ni necesidad de consultas de seguimiento
  dentro de los límites solicitados.
- **FR-012**: El volumen de la respuesta MUST quedar acotado por los
  filtros: la respuesta nunca excede el producto de (vencimientos dentro
  del tope de DTE) × (tipos pedidos) × (strikes permitidos por lado).
- **FR-013**: Cuando la fuente de datos de mercado falla o un vencimiento
  entero viene sin datos, la tool MUST abortar con un error estructurado
  que describa el motivo, sin devolver una cadena parcial; los campos
  puntuales faltantes dentro de contratos presentes se rigen por FR-007
  (marca explícita de no disponible).

### Key Entities *(include if feature involves data)*

- **Cadena de opciones**: el conjunto de vencimientos y contratos de un
  instrumento subyacente, con metadatos del instrumento y del estado de
  los datos.
- **Vencimiento**: una fecha de expiración dentro de la cadena, con su
  fecha exacta y su DTE calculado; es la unidad sobre la que aplican los
  límites de strikes y el filtro de delta.
- **Contrato de opción**: una opción puntual (tipo CALL o PUT, strike y
  vencimiento), con sus valores de mercado, sus griegas y sus valores
  técnicos; incluye la referencia del subyacente y del strike al dinero
  vigente para su vencimiento.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un agente puede obtener la cadena de opciones completa de un
  instrumento con opciones (filtros por defecto) en una sola invocación,
  en **≤5 segundos p95** desde la invocación hasta la respuesta.
- **SC-002**: Con los filtros por defecto (50 strikes por lado, ambos
  tipos, tope de DTE vigente), el volumen de la respuesta para un
  subyacente típico se mantiene dentro de un presupuesto declarado de
  **75.000 tokens** por invocación, verificable por test automático
  (justificación del crecimiento registrada en plan.md — Principio V);
  con `delta_target` activo el objetivo es **< 3.000 tokens**. El formato
  de salida se compacta sin recortar griegas ni violar los límites de
  filtros.
- **SC-003**: El 100% de los contratos devueltos incluye las cinco griegas
  clásicas o la marca explícita de no disponible; ningún campo se omite
  silenciosamente.
- **SC-004**: Cada escenario de validación del quickstart (S1–S3,
  cubriendo los análisis de Iron Condor, Naked Put, Calendar y LEAP
  dentro del rango de vencimientos y strikes recibidos) se completa con
  **exactamente 1 invocación** a la tool, verificado en los tests de
  integración.
- **SC-005**: Con el filtro de delta objetivo activo y tipo "ambos", cada
  vencimiento devuelto contiene hasta 5 strikes de CALLs y hasta 5
  strikes de PUTs alrededor del delta objetivo (o todos los disponibles
  si hay menos). Verificación: suite automática con fixtures
  representativos del proveedor (incluyendo casos de borde) más una
  validación contra cadena real como paso del quickstart S2.
- **SC-006**: Los límites solicitados (strikes por lado, tipos de opción,
  DTE) se respetan al 100% en la respuesta; cero contratos fuera de
  límite en los casos de prueba.

## Assumptions

- **Aplicación por vencimiento**: los límites de strikes y el filtro de
  delta se aplican por cada vencimiento devuelto (no sobre la respuesta
  completa); es la lectura natural de "ambos lados del strike" y de "los 5
  strikes alrededor del delta".
- **Interacción delta × límite de strikes**: cuando el filtro de delta
  está activo, los 5 strikes alrededor del delta gobiernan la selección y
  el límite de strikes por lado no la reduce adicionalmente; el límite de
  strikes solo aplica cuando no hay filtro de delta.
- **Centrado del filtro de delta**: "alrededor del delta 0.20" se
  interpreta como centrado: por tipo de opción incluido (ver
  Clarifications, sesión 2026-10-23), el contrato con delta más cercana
  al objetivo más dos strikes contiguos de cada lado (hasta 5, o los
  que existan).
- **Strike de referencia del límite de strikes**: el centro de la ventana
  de strikes es el strike al dinero del vencimiento (el contrato con
  precio de ejercicio más cercano al precio vigente del subyacente para
  ese vencimiento).
- **Tope por defecto de DTE**: "valor predeterminado nulo" para el filtro
  de DTE se interpreta como: no filtra por un DTE elegido por el usuario,
  pero aplica un tope de 60 días como máximo; un valor explícito
  reemplaza ese tope (mayor o menor).
- **Rango de delta objetivo**: el delta objetivo se expresa en valor
  absoluto (por ejemplo 0.20) y la tool lo mapea al signo correcto según
  el tipo de opción pedido (puts con delta negativa); un delta fuera del
  rango razonable se rechaza en la validación.
- **Frescura de datos**: la herramienta reutiliza la fuente de datos de
  mercado ya integrada en este proyecto; no se agrega una fuente nueva.
- **Alcance**: la tool es de solo lectura (no coloca órdenes ni mueve
  dinero) y está orientada a agentes de IA que consumen el MCP.
