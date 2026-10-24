# Contrato de eventos de auditoría: `get_transaction_history` (006)

Canal: stderr vía `log.auth_event` (reusado de 002/003, con redaction
filter activo). Ningún evento contiene tokens, secretos, números de
cuenta ni URLs de autorización. Formato de línea idéntico al existente:

```text
2026-10-23T14:00:00Z+00:00 auth_event=<event> outcome=<outcome> detail=<detail>
```

## Eventos por invocación

Cada invocación emite **exactamente un evento terminal** (patrón de
`get_open_positions` en 003): `transactions_query_success` para
resultados ok/partial, `transactions_query_failure` para fallos.

| Evento | Outcome | Detail | Cuándo |
|--------|---------|--------|--------|
| `transactions_query_success` | `ok` | `history_retrieved` · `no_movements` · `no_movements_for_instrument` | Todas las cuentas respondieron |
| `transactions_query_success` | `partial_failure` | `account_failed` | ≥ 1 cuenta falló, el resto respondió |
| `transactions_query_failure` | `transient` | `provider_unreachable` | Fallo transitorio en el primer intento (sin reintentos internos) |
| `transactions_query_failure` | `reauth` | `reauth_needed` | Store ausente/corrupto o refresh rechazado (ya emitido por el handler de errores, sin duplicar) |
| `transactions_query_failure` | `validation` | `invalid_query` | Error de validación del request (FR-004) — emitido para auditabilidad aunque la tool responda con error estándar MCP |

## Reglas

- **Namespace del `detail`**: el campo `detail` de los **eventos** es un
  namespace propio de este contrato (`history_retrieved`,
  `no_movements`, `no_movements_for_instrument`, `account_failed`,
  `provider_unreachable`, `reauth_needed`, `invalid_query`) y NO es el
  enum `TransactionDetail` del data model: los valores de evento
  describen la causa de auditoría, no el resultado de la tool
  (p. ej. una validación fallida emite `outcome=validation,
  detail=invalid_query` en stderr, mientras la tool responde con error
  estándar MCP).
- Nunca se emite un evento de éxito antes de conocer el resultado.
- El evento de validación se emite una sola vez por invocación.
- Los `detail` son valores cerrados de este contrato; cualquier texto
  libre proveniente del proveedor se redacta por el filtro existente.
