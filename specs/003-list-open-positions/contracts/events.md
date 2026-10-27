# Contract: Positions Audit Events

**Feature**: `003-list-open-positions` | **Date**: 2026-10-20

Extends the audit channel established in
[`specs/002-automated-token-renewal/contracts/events.md`](../../002-automated-token-renewal/contracts/events.md)
(same `log.auth_event` mechanism, same line format, same redaction
filter). This feature adds **new vocabulary** — it does not modify
the auth events.

## Line format

```text
<timestamp ISO-8601> auth_event=<event> outcome=<outcome> detail=<detail>
```

(It is the same `auth_event=` emitter — deliberately reused for DRY with
a single parseable format; the `event` distinguishes the domain.)

## Events per `get_open_positions` invocation

Every invocation emits **exactly one** `positions_query_start`
followed by **exactly one** terminal event. Never two terminals,
never an orphan start.

| Event | outcome | detail | Meaning |
|-------|---------|--------|---------|
| `positions_query_start` | `initiated` | `extended` \| `curated` | Query initiated (indicates mode) |
| `positions_query_success` | `ok` \| `partial_failure` | `positions_found` \| `no_positions` \| `account_failed` | Structured result returned; the event's outcome is exactly the result's `outcome` (includes `partial_failure` — FR-010) |
| `positions_query_failure` | `transient` \| `reauth` | `provider_unreachable` \| `reauth_needed` \| `store_absent` \| `store_corrupted` | Structured failure result returned |

## Rules

- **No secrets**: never tokens, credentials, or URLs; the redaction filter
  from 001 covers these lines (defense in depth).
- **No financial PII in the event**: the event does NOT include symbols,
  quantities, or values (that data travels only in the result to the
  MCP client). Classification only.
- **One line per transition**: the `start` → terminal sequence is the
  only one allowed; an unclassifiable internal failure emits
  `positions_query_failure` with `outcome=error`, `detail=internal`.
- Events go to the auxiliary channel (stderr); the structured result
  is the only thing that travels through the tool's data channel.