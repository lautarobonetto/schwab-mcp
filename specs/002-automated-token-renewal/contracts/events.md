# Contract: Renewal Event Log (extends 001 Authentication Event Log)

**Feature**: `002-automated-token-renewal`

Extends `specs/001-schwab-oauth-access/contracts/events.md` — same line
format, same stderr channel, same redaction filter, same invariants. Only
the vocabulary changes are recorded here.

## Line format (unchanged)

```text
<ISO-8601 UTC timestamp> auth_event=<event> outcome=<outcome> [detail=<fixed detail>]
```

## Event vocabulary changes

| Event | Status | Emitted when | Outcomes |
|-------|--------|--------------|----------|
| `renew_start` | **NEW** | A renewal attempt begins (automatic margin trigger or `schwab-mcp renew`) | `initiated` |
| `renewal_success` | extended | Renewal completed: access credential refreshed, or renewal unnecessary | `ok` \| `not_needed` (new) |
| `renewal_failure` | extended | Renewal failed after bounded retries, or re-authorization is required | `connectivity` \| `reauth_required` (both existed in 001) |

Example lines:

```text
2026-10-19T14:00:00Z+00:00 auth_event=renew_start outcome=initiated detail=margin_trigger
2026-10-19T14:00:02Z+00:00 auth_event=renewal_success outcome=ok detail=access token renewed
2026-10-19T14:00:00Z+00:00 auth_event=renew_start outcome=initiated detail=explicit_command
2026-10-19T14:00:01Z+00:00 auth_event=renewal_success outcome=not_needed detail=still valid
2026-10-19T14:00:10Z+00:00 auth_event=renewal_failure outcome=connectivity detail=retries exhausted
2026-10-19T14:00:01Z+00:00 auth_event=renewal_failure outcome=reauth_required detail=run: schwab-mcp auth
```

## New invariants

- Exactly one `renew_start` per renewal attempt; it is always followed by
  exactly one terminal event (`renewal_success` or `renewal_failure`)
  for that attempt (FR-010 lifecycle completeness).
- `detail` distinguishes the trigger: `margin_trigger` (automatic path)
  or `explicit_command` (`schwab-mcp renew`).
- A `not_needed` outcome is a **success** event: no provider call was
  made and nothing was invalidated (FR-002 AC2).
- No secrets, no authorization URLs (unchanged 001 invariant, FR-004).