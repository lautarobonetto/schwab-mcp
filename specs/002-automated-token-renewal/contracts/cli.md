# Contract: CLI Renewal & Auth-Status Commands

**Feature**: `002-automated-token-renewal`

Extends the `schwab-mcp` console script (001 contract
`specs/001-schwab-oauth-access/contracts/cli.md`) with two one-shot,
**non-interactive** subcommands for the unattended AI agent. Neither
command ever opens a browser, reads stdin, or listens on a socket.
`serve` remains headless; these commands are the agent's recovery levers
precisely when the server cannot start.

## Result envelope (both commands)

Exactly **one** JSON line on stdout, UTF-8, no other stdout output:

```json
{"outcome": "renewed", "expires_in_seconds": 1800, "retryable": false, "detail": "access_renewed"}
```

`auth-status` substitutes the health fields:

```json
{"state": "valid", "access_expires_in_seconds": 1520, "refresh_expires_in_seconds": 412000}
```

Output guarantees (FR-004, SC-005):
- **No secrets**: no token, app key/secret, or authorization URL in any
  field; redaction filter active as defense-in-depth.
- **Compact**: 3–4 fields, single line, ≤ 300 bytes per result
  (token-usage test budget, Principle V).
- Field vocabularies are closed enums (data-model.md §1–§2); `detail`
  uses only the fixed reasons listed below. Human-oriented narrative, if
  any, goes to stderr only.

| `outcome` / `state` | `detail` values |
|---------------------|-----------------|
| `renewed` | `access_renewed` |
| `not_needed` | `still_valid` |
| `transient_failure` | `provider_unreachable` |
| `reauth_required` | `refresh_rejected`, `store_absent`, `store_corrupted` |
| `valid` (status only) | — |

## `schwab-mcp renew`

Explicit renewal action (FR-002). One attempt to renew the access
credential from the stored refresh credential, with at most 2 retries on
transient failure (FR-006), then a classified result.

```
usage: schwab-mcp renew [-h]
```

### Behavior

1. Loads and validates configuration (fail fast; no network before it).
2. Peeks the token store: `absent`/`corrupted` → `reauth_required`
   result (details `store_absent`/`store_corrupted`); no renewal attempt.
3. Reads remaining validity from the store; if above the renewal margin,
   returns `not_needed` (`still_valid`) **without any network call** and
   without invalidating valid credentials (FR-002 AC2).
4. Acquires the advisory auth lock (non-blocking); busy → exits `6`
   (another renewal/authorization in progress — FR-005 at the command
   level).
5. Runs the schwabdev refresh under outcome classification
   (research D2): `renewed`, `transient_failure` (after ≤ 2 retries with
   short waits; existing valid credentials preserved), or
   `reauth_required` (refresh rejected / interactive-flow guard raised).
6. Emits `renew_start`, then `renewal_success`/`renewal_failure` audit
   events (contracts/events.md).

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | `renewed` or `not_needed` |
| 2 | Missing or malformed configuration |
| 3 | `reauth_required` (owner must run `schwab-mcp auth`) |
| 6 | Another renewal/authorization already in progress |
| 7 | `transient_failure` (retryable — safe for the agent to retry later) |

## `schwab-mcp auth-status`

Authentication-health query (FR-008). Local read only; answers in one
request (SC-003), no network call, ≤ 2 s.

```
usage: schwab-mcp auth-status [-h]
```

### Behavior

1. Loads and validates configuration (fail fast).
2. Peeks the token store and reads remaining lifetimes
   (data-model.md §2).
3. Prints the health JSON line; never triggers a renewal.

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | `valid` (even if close to expiry — the fields carry that information) |
| 2 | Missing or malformed configuration |
| 3 | `reauth_required` (`refresh_rejected` is not detectable locally; this code is emitted for `store_absent`/`store_corrupted`) |

## Invariants

- Both commands are safe to run any number of times, concurrently-safe
  (`renew` refuses via lock; `auth-status` is read-only).
- stdout carries exactly one JSON line per run — agents parse it, never
  free text (SC-004).
- Re-authorization itself remains the 001 interactive `schwab-mcp auth`
  flow; these commands never attempt it.