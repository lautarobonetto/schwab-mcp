# Contract: Eventos de auditoría de posiciones

**Feature**: `003-list-open-positions` | **Date**: 2026-10-20

Extiende el canal de auditoría establecido en
[`specs/002-automated-token-renewal/contracts/events.md`](../../002-automated-token-renewal/contracts/events.md)
(mismo mecanismo `log.auth_event`, mismo formato de línea, mismo filtro
de redacción). Esta feature agrega **nuevo vocabulario** — no modifica
los eventos de auth.

## Formato de línea

```text
<timestamp ISO-8601> auth_event=<event> outcome=<outcome> detail=<detail>
```

(Es el mismo emisor `auth_event=` — reutilizado a propósito por DRY para
un solo formato parseable; el `event` distingue el dominio.)

## Eventos por invocación de `get_open_positions`

Cada invocación emite **exactamente un** `positions_query_start`
seguido de **exactamente un** evento terminal. Nunca dos terminales,
nunca un start huérfano.

| Evento | outcome | detail | Significado |
|--------|---------|--------|-------------|
| `positions_query_start` | `initiated` | `extended` \| `curated` | Consulta iniciada (indica modo) |
| `positions_query_success` | `ok` \| `partial_failure` | `positions_found` \| `no_positions` \| `account_failed` | Resultado estructurado devuelto; el outcome del evento es exactamente el `outcome` del resultado (incluye `partial_failure` — FR-010) |
| `positions_query_failure` | `transient` \| `reauth` | `provider_unreachable` \| `reauth_needed` \| `store_absent` \| `store_corrupted` | Resultado estructurado de fallo devuelto |

## Reglas

- **Sin secretos**: nunca tokens, credenciales ni URLs; el filtro de
  redacción de 001 cubre estas líneas (defensa adicional).
- **Sin PII financiera en el evento**: el evento NO incluye símbolos,
  cantidades ni valores (esos datos viajan solo en el resultado al
  cliente MCP). Solo clasificación.
- **Una línea por transición**: la secuencia `start` → terminal es la
  única permitida; un fallo interno no clasificable emite
  `positions_query_failure` con `outcome=error`, `detail=internal`.
- Los eventos van al canal auxiliar (stderr); el resultado estructurado
  es lo único que viaja por el canal de datos de la tool.
