# Research: List Open Positions

**Feature**: `003-list-open-positions` | **Date**: 2026-10-20

Todas las decisiones fueron verificadas contra las versiones instaladas
en el repo (`uv run python -c ...` contra `schwabdev==4.0.0` y el SDK
`mcp>=1.0.0`), no contra documentación genérica.

## D1 — Superficie: primera tool MCP real vía `MCPServer.add_tool`

**Decision**: Registrar la tool con la API del SDK `mcp` ya usada en
`server.py`: `mcp.add_tool(fn, name="get_open_positions", description=...)`
(o el decorador equivalente `@mcp.tool`). La función es **sync** y el
SDK la invoca correctamente (verificado: `add_tool` acepta funciones
síncronas; `structured_output` auto-detecta por type annotation del
retorno — se anota con el modelo pydantic del resultado para salida
estructurada garantizada).

**Rationale**: El spec (Q1) decidió tool MCP real. El server ya instancia
`MCPServer("schwab-mcp")`; registrar una tool es la extensión mínima y
establece el patrón para tools futuras (KISS, Reuse). No hay segundo
camino CLI (Q1 descartó "ambas").

**Alternatives considered**:
- Comando one-shot CLI: rechazado — contradice la decisión del usuario (Q1: A).
- Implementar el handler de `call_tool` a mano sobre `Server` (lowlevel):
  rechazado — duplicaría lo que el SDK ya resuelve (DRY).

## D2 — Fuente de datos: `account_details_all(fields="positions")`

**Decision**: Una única llamada upstream por consulta:
`client.account_details_all(fields="positions")` (schwabdev 4.0.0,
verificado: `GET /trader/v1/accounts?fields=positions`). Devuelve todas
las cuentas vinculadas con sus posiciones en una sola respuesta.

**Rationale**: Satisface FR-001 + FR-004 (todas las cuentas, todas las
posiciones, una query) con el mínimo de llamadas al proveedor (latency
budget SC-002 y cortesía de rate-limit). `linked_accounts()` ya se usa
en 001/002 para validar acceso; no se necesita llamarlo aparte aquí.

**Alternatives considered**:
- `account_details(account_hash)` por cuenta (N llamadas): rechazado —
  N× latencia y N× cuota para el mismo dato.
- Endpoint de quotes separado para refrescar precios: rechazado —
  duplica llamadas; el payload de positions ya trae `marketValue` y
  datos de cotización del proveedor (ver D4).

## D3 — Conjunto curado de metadatos (FR-003 / FR-003a)

**Decision** — campos del payload del proveedor → set curado por posición:

| Campo curado | Fuente en payload provider |
|--------------|---------------------------|
| `symbol` | `instrument.symbol` |
| `instrument_type` | `instrument.assetType` (enum del proveedor: `EQUITY`, `OPTION`, `MUTUAL_FUND`, `FIXED_INCOME`, `CASH_EQUIVALENT`) |
| `description` | `instrument.description` |
| `quantity` (con signo) | `longQuantity - shortQuantity` |
| `average_price` | `averagePrice` |
| `market_value` | `marketValue` |
| `unrealized_pl` | derivado: `marketValue - (averagePrice × |quantity|) × sign(quantity)`; verificado contra `currentDayProfitLoss` cuando el proveedor lo trae |
| `price_timestamp` | ver D4 |
| `account_hash` | hash de la cuenta que contiene la posición (opaco, seguro para mostrar; nunca el número de cuenta crudo) |
| Solo opciones: `underlying_symbol`, `put_call`, `strike_price`, `expiration_date` | `instrument.underlyingSymbol`, `instrument.putCall`, `instrument.strikePrice`, `instrument.expiration*` |

**Extended bajo demanda (`extended=true`, FR-003a)**: el resto de los
campos que el proveedor trae para esa posición (p. ej. `cusip`,
`settledLongQuantity`, `settledShortQuantity`, `dayQuanity` —sic, campo
del proveedor—, `currentDayProfitLoss`, `maintenanceRequirement`, y todo
`instrument` completo) se pasasthrough sin interpretación, con
`price_timestamp` incluido igual.

**Rationale**: cubre todo lo que el spec define como "entender y decidir"
(US2) manteniendo el payload compacto (Constitution V). Los campos de
opción son obligatorios para el caso de uso declarado por el dueño
(strangles / condors / rolls).

**Alternatives considered**:
- Passthrough crudo completo por defecto: rechazado (Q2 del specify).
- Filtrar también el set extendido: rechazado — el valor de `extended`
  es justamente la fidelidad total del proveedor.

## D4 — `price_timestamp` cuando el proveedor no trae quote time por posición

**Decision**: El payload de positions de la API no garantiza un campo de
timestamp de cotización por posición. La tool setea `price_timestamp` al
**momento de recuperación de la respuesta del proveedor** (UTC ISO-8601)
y agrega a nivel de resultado `market_state` (`open` | `closed`) por
cuenta según horario del mercado de cada instrumento… **revisión
(KISS)**: derivar mercado abierto/cerrado por instrumento agrega lógica
y supuestos de calendario fuera del control del sistema. Decisión final:
`price_timestamp` = UTC de la recuperación; el valor reportado es el que
el proveedor calculó al generar ese payload (en vivo en horario de
mercado, último cierre fuera de horario — comportamiento del proveedor,
no nuestro). Se documenta explícitamente en el contract para que el
agente no atribuya frescura que no existe.

**Rationale**: FR-012 exige timestamp del precio usado; el precio usado
ES el del payload del proveedor, y su timestamp de recuperación es la
verdad observable sin reinventar calendarios de mercados (KISS, y evita
una fuente de bugs silenciosos).

**Alternatives considered**:
- Calcular open/closed con calendarios (lib tipo `exchange_calendars`):
  rechazado — dependencia nueva + supuestos de feriados/horarios
  injustificables para v1 (YAGNI).

## D5 — Omisión de cantidad cero (FR-015)

**Decision**: Una posición con `longQuantity == shortQuantity == 0` (o
`longQuantity - shortQuantity == 0` con ambos > 0, p. ej. cerrada y no
liquidada) se **omite** del resultado. El contract lo documenta.

**Rationale**: FR-015 resolvió el edge case: solo tenencias efectivas;
el agente nunca ve posiciones fantasma.

## D6 — Sin reintentos internos (FR-007)

**Decision**: Fallo de red/proveedor → `ConnectivityError` (taxonomía
existente, exit 7) mapea a resultado `transient_failure` **en el primer
intento**, sin retry. `retryable: true` solo en esa clase.

**Rationale**: Decisión Q4 del clarify. Reuso el patrón de clasificación
de 002 (mismo vocabulario `retryable`/outcome classes) sin duplicar su
mecánica de reintentos, que no aplica a una lectura barata.

## D7 — Clasificación de fallos: reuso de la taxonomía de `errors.py`

**Decision**: Mapeo directo de las excepciones existentes a outcomes de
la tool:

| Excepción (errors.py) | Outcome de la tool |
|---|---|
| `ConnectivityError` | `transient_failure` (`retryable: true`) |
| `ReauthorizationRequiredError`, `TokenStoreCorruptedError` | `reauth_required` |
| Un account falla y otros ok (FR-010) | `partial_failure` con `accounts_failed` + `detail` por cuenta |
| `MissingConfigError`/`InvalidConfigError` | no deberían ocurrir en serve (fail-fast al arranque); si ocurren, se reportan como `error` genérico con detail |

**Rationale**: DRY total con el playbook de `docs/tools.md`; el agente
usa exactamente las mismas reglas de decisión que ya conoce.

**Alternatives considered**: taxonomía nueva para la tool: rechazado (DRY).

## D8 — Eventos de auditoría (FR-014)

**Decision**: Reutilizar `log.auth_event(event, outcome, detail=)` con
vocabulario nuevo, análogo al de renew:
`positions_query_start` → (`positions_query_success` |
`positions_query_failure`). Un `start` seguido de exactamente un
terminal por invocación; salida por el canal auxiliar (stderr), sin
secretos; el filtro de redacción existente cubre estas líneas.

**Rationale**: Q3 decidió auditar siempre; reuso del mecanismo existente
(DRY) con eventos con nombres propios para no colisionar con el vocabulario
de auth (contrato separado en `contracts/events.md`).

## D9 — Presupuesto de tokens / tamaño de payload (SC-003)

**Decision**: Presupuesto declarado para la implementación:
- Default (50 posiciones curadas): **≤ 8 KB** de JSON serializado
  (~2 000 tokens), medido por test.
- `extended=true`: presupuesto separado declarado en el contract
  (≤ 16 KB para 50 posiciones); cualquier crecimiento requiere
  justificación registrada (Constitution V).
- Formato compacto: nombres de campo cortos y snake_case, sin campos
  nulos informativos (omisión > null cuando el campo no aplica).

**Rationale**: SC-003 exige presupuesto medible; la estimación por
posición (~150 bytes curado) sale del conteo de campos de D3.

## D10 — Concurrency con renovación automática

**Decision**: La tool no coordina la renovación (schwabdev la maneja
internamente con su SQLite `BEGIN EXCLUSIVE` — probado en 002). Si una
renovación está en vuelo, la llamada a schwabdev espera o refleja el
estado; la tool nunca inicia flujos de autorización (el guard hook de
`serve` lo garantiza).

**Rationale**: Reuse del mecanismo probado de 002; sin locks nuevos (KISS).

---

## Corrección post-implementación (2026-10-24)

La forma de payload asumida en esta investigación
(`{"accountDetails": [{"accountNumber", "positions"}]}` con respuestas ya
parseadas) **no coincide con el contrato real del SDK/endpoint**:

- `Client.account_details_all()` devuelve `requests.Response` (el body
  debe unwrapearse con `.json()` — ver `schwab_mcp.provider.response_json`,
  introducido por el fix de la feature 006).
- El payload real es una **lista top-level** de
  `{"aggregatedBalance", "securitiesAccount": {...}}`.
- El `securitiesAccount` real no trae el hash de cuenta: el identificador
  opaco es el `hashValue` de `linked_accounts()`, cruzado por
  `accountNumber`.
- Los instrumentos OPTION reales no traen `strikePrice` ni
  `expirationDate`: se derivan del símbolo OCC.

Detectado y corregido en el bug `positions-response-unwrap`
(`.specify/bugs/positions-response-unwrap/`).
