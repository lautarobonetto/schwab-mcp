# Contract: Authentication Event Log

**Feature**: `001-schwab-oauth-access` (FR-014)

Authentication events are emitted to **stderr** (stdout is reserved for the
MCP stdio channel). Each event is a single line, secret-free, and passes
through the redaction filter before output.

## Line format

```text
<ISO-8601 UTC timestamp> auth_event=<event> outcome=<outcome> [detail=<fixed detail>]
```

Example lines:

```text
2026-10-19T12:00:00Z+00:00 auth_event=auth_start outcome=initiated detail=browser flow requested
2026-10-19T12:01:24Z+00:00 auth_event=auth_success outcome=ok detail=tokens stored at ~/.schwab-mcp/tokens.db
2026-10-19T12:05:00Z+00:00 auth_event=auth_failure outcome=cancelled detail=run: schwab-mcp auth to retry
2026-10-19T13:00:00Z+00:00 auth_event=renewal_success outcome=ok detail=access token renewed
2026-10-19T13:00:30Z+00:00 auth_event=renewal_failure outcome=reauth_required detail=run: schwab-mcp auth
```

## Event types

| Event | Emitted when | Outcomes |
|-------|--------------|----------|
| `auth_start` | `schwab-mcp auth` begins after config validation and lock acquisition | `initiated` |
| `auth_success` | Authorization-code exchange succeeded and the token set was stored | `ok` |
| `auth_failure` | Authorization cancelled, failed, or refused (concurrent) | `cancelled` \| `failed` \| `refused_concurrent` |
| `renewal_success` | Access-token refresh succeeded (startup validation or on-demand) | `ok` |
| `renewal_failure` | Access-token refresh failed (connectivity or refresh token rejected) | `connectivity` \| `reauth_required` |

## Invariants

- **No secrets ever**: app key, app secret, access/refresh/id tokens, and
  authorization codes must never appear in any event line (FR-006, SC-003).
  The redaction filter scrubs known secret values as defense-in-depth.
- Every event includes a timestamp and an outcome (FR-014).
- Failure details name the recovery action (e.g. `run: schwab-mcp auth`)
  per FR-007 — distinct per failure mode (see
  [../data-model.md](../data-model.md) mapping table).
- Events are emitted for every key lifecycle transition listed above; no
  event is emitted for routine authenticated API reads.
