# Data Model: Automated Token Renewal

**Feature**: `002-automated-token-renewal` | **Date**: 2026-10-19

The persisted data model is unchanged from feature 001 (the schwabdev
SQLite `schwabdev` single-row token table — see
`specs/001-schwab-oauth-access/data-model.md` §2 TokenSet). This feature
adds **in-process/ephemeral** structures only; nothing new is persisted
except renewal audit-event lines (append-only stderr log, contract in
`contracts/events.md`).

## Entities

### 1. RenewalOutcome (ephemeral; returned by every renewal path)

The single structured result type for FR-003. One instance per renewal
attempt; serialized as one compact JSON line for the agent.

| Field | Type | Validation | Notes |
|-------|------|------------|-------|
| outcome | enum str | one of `renewed` \| `not_needed` \| `transient_failure` \| `reauth_required` | Exactly one class per result (SC-004); drives exit codes (contracts/cli.md) |
| expires_in_seconds | int \| null | ≥ 0 when present | Remaining validity of the access credential after the operation; null when the credential is unusable |
| retryable | bool | — | `true` only for `transient_failure` |
| detail | enum str | fixed vocabulary (no free text) | Short fixed reason, e.g. `access_renewed`, `still_valid`, `provider_unreachable`, `refresh_rejected`, `reauth_needed`, `store_absent` |

Rules:
- NEVER contains token/secret values or URLs (FR-004); redaction filter
  is defense-in-depth.
- Payload is exactly 3–4 fields, single line (token-usage budget,
  contracts/cli.md).
- `renewed` and `not_needed` imply `retryable: false`.
- `transient_failure` implies `retryable: true`; all others false.

### 2. AuthHealth (ephemeral; result of the health query, FR-008)

| Field | Type | Validation | Notes |
|-------|------|------------|-------|
| state | enum str | one of `valid` \| `reauth_required` \| `store_absent` \| `store_corrupted` | `renewing` is transient and never observable through the one-shot status command (a concurrent renewal either finished or did not) |
| access_expires_in_seconds | int \| null | ≥ 0 when present | Computed from stored `expires_in` and `access_token_issued` (provider-communicated lifetime, research D5) |
| refresh_expires_in_seconds | int \| null | ≥ 0 when present | Computed from the 7-day Schwab refresh lifetime and `refresh_token_issued` |

Rules:
- One request answers everything the agent needs (SC-003): state + both
  remaining lifetimes + `reauth_required` visibility.
- No network call is required to answer (local read); an optional
  liveness probe is NOT part of v1 (KISS).

### 3. RenewalRecord (audit event line; extends 001 event log)

Append-only, secret-free stderr lines (FR-010). Format and event
vocabulary in `contracts/events.md`. One line per lifecycle transition:
`renew_start` → (`renewal_success` | `renewal_failure`).

### 4. TokenSet (persisted; UNCHANGED from 001 — referenced, not duplicated)

Schema owned by schwabdev: `access_token`, `refresh_token`, `id_token`,
`access_token_issued`, `refresh_token_issued`, `expires_in`,
`token_type`, `scope`. This feature only **reads** timestamps/
`expires_in` for margin and health computation and lets schwabdev
**write** rotated tokens (FR-009, research D1). Refresh-token lifetime is
Schwab's 7 days; schwabdev conservatively routes to re-auth when
< ~60.5 min remain — that routing, surfaced through the guard hook, is
what produces the `reauth_required` state (US3).

## State transitions (authentication state)

```text
            ┌─────────────────────────────────────────────┐
            │                (any operation)              │
            v                                             │
   ┌──────────────┐  remaining < margin   ┌─────────────┐ │
   │    valid     │ ────────────────────> │  renewing   │ │
   │ (store ok)   │ <──────────────────── └─────────────┘ │
   └──────────────┘   refresh ok (single-      │         │
          ^            flight; rotation         │ refresh │
          │            persisted)               │ rejected│
          │ owner runs                          v         │
          │ `schwab-mcp auth`      ┌──────────────────────┐│
          └──────────────────────> │  reauth_required     ││
                                   │ (guard hook raises;  ││
                                   │  no auto attempts)   ││
                                   └──────────────────────┘│
```

Rules:
- At most one renewal in flight at any time, enforced by schwabdev's
  SQLite `BEGIN EXCLUSIVE` + lock for the automatic path (FR-005) and by
  `AuthLock` for the explicit `schwab-mcp renew` command.
- From `reauth_required`, no automatic refresh attempts are made; every
  operation and renewal result reports `reauth_required` (US3) until the
  owner re-authorizes via the 001 `schwab-mcp auth` flow.
- `store_absent`/`store_corrupted` are entry states handled exactly as in
  001 (treated as re-authorization-required with distinct detail).