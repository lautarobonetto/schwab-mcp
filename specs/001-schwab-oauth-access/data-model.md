# Data Model: Schwab OAuth Access

**Feature**: `001-schwab-oauth-access` | **Date**: 2026-10-19

## Entities

### 1. ApplicationCredentials (in-process only — never persisted)

Identifies the owner's registered Schwab developer application.

| Field | Source | Type | Validation | Notes |
|-------|--------|------|------------|-------|
| app_key | env `SCHWAB_APP_KEY` | str | required, non-empty | Format validated by schwabdev (even length, combined ≥ 32 chars) — not duplicated here (DRY) |
| app_secret | env `SCHWAB_APP_SECRET` | str | required, non-empty | Format validated by schwabdev — not duplicated here |
| callback_url | env `SCHWAB_CALLBACK_URL` (optional) | str | must match app registration in the developer portal | Default `https://127.0.0.1`. Never actually connected to: the flow is paste-the-redirect-URL; the browser redirect to this URL is expected to fail to connect, and the owner copies the address-bar URL |

Constraints: loaded once at process start (`config.py`); missing/empty →
`MissingConfigError` (fail fast, FR-008). Values are held in memory only,
marked for redaction by the log filter. NEVER written to disk, logs, or
error messages (FR-006).

### 2. TokenSet (persisted; schema owned by schwabdev)

Lives in the schwabdev SQLite token DB — a single-row table `schwabdev` in
a plain SQLite file (default `~/.schwab-mcp/tokens.db`, configurable via
env `SCHWAB_TOKEN_DB`), outside the repository, chmod 600 (file) / 0700
(directory), no encryption at rest (owner decision 2026-10-19, KISS).

| Field | Type | Notes |
|-------|------|-------|
| access_token | str | Short-lived bearer token; Schwab validity 30 min; renewed automatically by schwabdev when < 61 s remain; **secret** — redacted everywhere |
| refresh_token | str | Long-lived credential; Schwab validity 7 days; exchanged for a new token set via re-auth when < ~60.5 min remain; **secret** — redacted everywhere |
| id_token | str | OIDC identity token issued alongside; **secret** — redacted everywhere |
| access_token_issued | ISO-8601 datetime (UTC) | Set at each access-token issue/refresh |
| refresh_token_issued | ISO-8601 datetime (UTC) | Set only at authorization-code exchange |
| expires_in | int (seconds) | Access-token lifetime (Schab default 1800) |
| token_type | str | `Bearer` |
| scope | str | Least-privilege API scope per FR-005 |

Rules:
- FR-003: file permissions enforced after every write (`0o600` file, `0o700`
  directory); path outside the repo; never committed.
- FR-009: if the store is unreadable, unparseable, or undecryptable →
  treated as ABSENT (corrupted store is not repaired, not deleted by
  default beyond schwabdev's own rewrite-on-reauth) →
  `TokenStoreCorruptedError` / re-auth messaging, never a crash.
- FR-010: a re-auth (`schwab-mcp auth`) only replaces the store row after
  the new authorization completes; an existing valid set is untouched
  until then (schwabdev writes the row only after a successful code
  exchange).
- FR-012: location configurable via `SCHWAB_TOKEN_DB`.

### 3. AuthorizationGrant (transient — never persisted)

The one-time authorization code delivered via the browser redirect during
`schwab-mcp auth`.

| Field | Type | Lifecycle |
|-------|------|-----------|
| auth_url | str | Constructed by schwabdev (`https://api.schwabapi.com/v1/oauth/authorize?client_id=…&redirect_uri=…`); displayed to the owner in FULL — client_id is public by OAuth design and the URL must be usable as-is (amended FR-006); never logged to any persistent sink; the app key stays redacted in every other sink |
| redirect_url (or raw code) | str | Pasted by the owner into the terminal; parsed by schwabdev; consumed exactly once by the token exchange; never logged, never written to disk |

Rules: the grant exists only inside one `auth` process run; a paste that
yields no code → `AuthorizationCancelledError` (US3). Codes expire in
~30 seconds after redirect (Schwab-side), which schwabdev surfaces as a
token-endpoint error → mapped to `InvalidConfigError`-distinct
`AuthorizationCancelledError` retry messaging.

### 4. AuthEvent (append-only log stream; no file schema beyond the entry format)

Emitted by `log.py` to **stderr** (never stdout — the MCP stdio channel),
secret-free, per FR-014.

| Field | Type | Values |
|-------|------|--------|
| timestamp | ISO-8601 UTC | emission time |
| event | str | `auth_start` \| `auth_success` \| `auth_failure` \| `renewal_success` \| `renewal_failure` |
| outcome/detail | str | fixed, secret-free description (failure detail names the recovery action, e.g. `run: schwab-mcp auth`) |

Rules: every entry passes the redaction filter; events are the audit
record required by FR-014 — no additional storage in this feature.

## Failure-mode → error mapping (FR-007 / US3 / SC-005)

Each failure mode has a distinct, actionable message and exit code; none
hangs; none surfaces a raw traceback.

| Failure mode | Detected by | Error type (exit code) | Recovery message points to |
|--------------|-------------|------------------------|----------------------------|
| Missing config | env vars absent/empty at start | `MissingConfigError` (2) | Set `SCHWAB_APP_KEY` / `SCHWAB_APP_SECRET` (see docs/quickstart) |
| Malformed config | schwabdev `ValueError` on client init | `InvalidConfigError` (2) | Fix the values in your environment |
| No token set + owner declines/cancels browser login | empty/short paste, or owner abort | `AuthorizationCancelledError` (3) | Re-run `schwab-mcp auth` to retry |
| Token set expired beyond recovery / refresh rejected | schwabdev refresh failure, refresh-token window exhausted, or `call_on_auth` raised in `serve` context | `ReauthorizationRequiredError` (4) | Run `schwab-mcp auth` |
| Corrupted / unreadable token set | store peek fails to parse/decrypt | `TokenStoreCorruptedError` (5) | Store treated as absent; run `schwab-mcp auth` |
| Concurrent authorization attempt | advisory lock busy | `ConcurrentAuthError` (6) | Another authorization is already running; wait for it to finish |
| Schwab API unreachable during refresh | network exception on refresh (1 retry, then fail) | `ConnectivityError` (7) | Check connectivity; stored tokens were not modified — retry or run `schwab-mcp auth` |

## State transitions (TokenSet lifecycle)

```text
            ┌──────────────────────────────────────────────────────┐
            │                                                      │
  ABSENT ──auth success──► AUTHORIZED (access valid)                │
    ▲                          │   │                                │
    │                          │   │ access expires (<61 s left or  │
    │                          │   │ on-demand)                     │
    │                          │   ▼                                │
    │                          │ REFRESHING (silent, refresh token)─┤
    │                          │   │ success → AUTHORIZED           │
    │                          │   │ network fail → ConnectivityError
    │                          │   │ refresh rejected → REAUTH_REQUIRED
    │                          │ refresh token < ~60.5 min left      │
    │                          ▼                                     │
    │                     REAUTH_REQUIRED ──(serve: fail fast with  │
    │                          │          re-auth message)           │
    └──────── (auth) ──────────┘                                     │
                                                                     │
  CORRUPTED (store unreadable) ──treated as ABSENT (FR-009)──────────┘
```

Notes:
- `serve` never enters the browser-flow state: when re-auth is required it
  exits with `ReauthorizationRequiredError` before the MCP handshake.
- Concurrent `auth` attempts: second attempt refused with
  `ConcurrentAuthError`; first attempt's store writes are serialized by
  schwabdev's SQLite coordination plus our advisory lock.
