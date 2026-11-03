# Bug Assessment: `schwab-mcp auth` reports success with dead tokens in the store

- **Slug**: auth-false-success
- **Created**: 2026-11-03
- **Source**: pasted text (terminal transcript from remote host `openclaw@Server1`)
- **Verdict**: valid
- **Severity**: high

## Report (verbatim or summarized)

Pasted transcript of `schwab-mcp auth` on a remote host with an existing
token store holding a revoked refresh token:

```text
openclaw@Server1:~/projects/schwab-mcp$ set -a; source ~/.schwab-mcp/env; set +a
openclaw@Server1:~/projects/schwab-mcp$ uv run schwab-mcp auth
2026-11-03T03:12:05Z+00:00 auth_event=auth_start outcome=initiated detail=browser flow requested
Could not get new access token; refresh_token likely invalid. ({"error":"unsupported_token_type","error_description":"400 Bad Request: \"{\"error_description\":\"Refresh token is invalid, expired or revoked\",\"error\":\"invalid_grant\"}\""})
Could not get new access token; refresh_token likely invalid. ({"error":"unsupported_token_type", ... "invalid_grant" ...})
Authorization successful. Schwab API access is configured.
2026-11-03T03:12:06Z+00:00 auth_event=auth_success outcome=ok detail=token set stored
```

No URL supplied — no fetch performed, URL Trust Policy not applicable.

## Symptom

Running `schwab-mcp auth` against a token store whose refresh token was
revoked server-side (`invalid_grant`) does **not** start a fresh
browser authorization flow: schwabdev's silent HTTP refresh fails, the
client constructor completes with the stale tokens still in the store,
and the CLI prints **"Authorization successful"** and logs
`auth_success` — with credentials that are unusable. Expected: `auth`
performs a real authorization and only reports success when fresh,
usable tokens were stored during this run.

## Reproduction

1. Obtain a token store (`~/.schwab-mcp/tokens.db`) whose refresh token
   is revoked but whose recorded issuance timestamp is recent (e.g. the
   DB is copied from another host, restored from backup, or a later
   re-authorization elsewhere invalidated it — Schwab issues a new
   refresh token per authorization and old ones become invalid).
2. Run `set -a; source ~/.schwab-mcp/env; set +a` then
   `uv run schwab-mcp auth`.
3. Observe: two `Could not get new access token; refresh_token likely
   invalid. (... invalid_grant ...)` error lines (schwabdev logger), no
   authorization URL printed, no browser flow, then
   `Authorization successful. Schwab API access is configured.` and
   `auth_event=auth_success outcome=ok`.

Exact schwabdev version on the affected host `[NEEDS CLARIFICATION:
which schwab-mcp / schwabdev release runs on Server1 — the repo moved
to schwabdev 4.0.0; the analyzed code paths are unchanged in current
main]`. Why the refresh token was revoked `[NEEDS CLARIFICATION: copy
from another host, concurrent re-auth, or Schwab-side revocation —
irrelevant to the fix: `auth` must not trust a stale store]`.

## Suspected Code Paths

- `src/schwab_mcp/cli.py:104-111` — `run_auth` constructs
  `schwabdev.Client(..., call_on_auth=counted_hook)`. schwabdev invokes
  the hook only through its own token-update flow, which for a
  non-empty store may never reach the interactive path.
- `src/schwab_mcp/cli.py:116-118` — the manual hook invocation fires
  only when `not peek_store(...)` — i.e. only for an **empty** store.
  A stale store skips it entirely.
- `src/schwab_mcp/cli.py:120-134` — success gate:
  `if not peek_store(config.token_db): raise AuthorizationCancelledError()`.
  `peek_store` (`src/schwab_mcp/tokens.py:19-50`) only checks "SQLite
  file with ≥1 row in table `schwabdev`" — it cannot distinguish fresh
  usable tokens from dead ones. The in-code comment "Success is
  determined by the STORE" conflates *rows present* with *credentials
  usable*.
- `.venv/.../schwabdev/tokens.py:270-289` (`update_tokens`) — on client
  init (called twice: `client.py:51` and `client.py:101`, which explains
  the duplicated error line): if the recorded refresh-token age is NOT
  within the 60.5-minute rotation window, it takes the HTTP-only branch
  `_update_access_token`.
- `.venv/.../schwabdev/tokens.py:297-322` (`_update_access_token`) — the
  HTTP refresh; on a non-OK response it logs
  `"Could not get new access token; refresh_token likely invalid."`,
  **returns `False`** (no exception, no `call_on_auth`), and leaves the
  stale rows in the DB.
- Contrast — `src/schwab_mcp/renewal.py:286-298`: `renew` handles
  `update_tokens() → False` via `_tie_breaker_probe` and correctly maps
  the failure to `reauth_required` with detail "run: schwab-mcp auth".
  The designed recovery pointer leads straight into the lying command.

## Root Cause Hypothesis

`run_auth`'s success criterion is "the store is non-empty after client
construction" (`cli.py:123`). With a stale store, schwabdev's init-time
`update_tokens()` tries a silent HTTP refresh; when the refresh token
was revoked server-side, that returns `False` without raising and
without invoking `call_on_auth`, the stale rows survive, and the CLI
declares success on credentials that are already dead. The interactive
hook is unreachable for non-empty stores unless schwabdev itself decides
the refresh token is within its rotation window, so `auth` cannot
recover from `invalid_grant` by design. Confidence: **high** — every
step is grounded in the quoted transcript plus the cited schwabdev
source lines and CLI code.

## Proposed Remediation

**Preferred**: make `auth` a deliberate, always-fresh re-authorization
with a real success gate.

1. In `run_auth`, when `peek_store_status(config.token_db) == "present"`,
   move the existing store aside first (e.g. rename to
   `tokens.db.bak.<ISO timestamp>` in the same directory, `0o600`).
   With an empty store, schwabdev's v4 auto-start invokes `call_on_auth`
   → URL printed → browser flow → fresh code exchange → fresh tokens.
   This makes `auth` deterministic: it performs an authorization instead
   of opportunistically trusting whatever is in the DB.
2. On failure paths (`AuthorizationCancelledError`, `AuthError`, empty
   store after the flow), restore the backup — a cancelled auth must not
   destroy possibly-valid credentials (same spirit as the T020
   invariant "the store is not deleted on failure").
3. Strengthen the success gate: success requires evidence of a fresh
   write during **this run** (e.g. hook ran AND store rows were written
   after process start), not merely "store non-empty". Keep the
   stale-store-skips-hook guard impossible: after step 1 the store is
   always empty at client construction, so the hook always runs.

This also fixes the poisoned recovery loop: `renew`'s
`reauth_required → run: schwab-mcp auth` advice now actually re-authorizes.

**Alternatives** (optional):

- Call `client.tokens.update_tokens(force_refresh_token=True)` after
  client construction when the store is present — routes to
  `_update_refresh_token` → `_prompt_for_auth` → our hook. Trade-off:
  couples `auth` to schwabdev's public-but-behavioral API and its
  internal transaction/lock state; does not fix the success gate
  (needs a separate freshness check), so two changes instead of one.
- Detect the failure only (probe access-token issuance before/after,
  or capture schwabdev log records) and report
  `reauth_required`-style failure. Trade-off: leaves the user without a
  working `auth` path on a stale store — they must delete `tokens.db`
  by hand; strictly worse UX for the same effort.

**Files likely to change**:

- `src/schwab_mcp/cli.py` (`run_auth` — backup/restore + success gate)
- `src/schwab_mcp/tokens.py` (small helper for backup/restore, or keep
  inline in `cli.py` if it stays trivial)
- `docs/tools.md` / `docs/usage.md` (document that `auth` always
  re-authorizes and preserves a `.bak` copy on failure)
- `docs/CHANGELOG.md` (bugfix entry)
- `specs/*/contracts/cli.md` — the `auth` behavior contract likely
  states the store-based success rule; amend it

**Tests to add or update**:

- Regression (integration, `tests/integration/test_auth.py`): store
  present + fake client that models "non-empty store, refresh fails,
  `call_on_auth` never invoked" → `auth` must NOT print
  "Authorization successful"; with the fix, the hook runs and fresh
  tokens land in the store.
- Backup restore: cancelled auth (`AuthorizationCancelledError` path)
  restores the backed-up store byte-identically and removes the backup
  on success.
- Backup hygiene: backup file gets `0o600`/parent `0o700` (credential
  safety), and a pre-existing `.bak` is never silently overwritten.
- Existing `test_auth.py` suites that assume `auth` succeeds with a
  pre-populated store and no hook call will need updating — that
  assumption is precisely the bug.

## Risks & Considerations

- Renaming the store under a **running `serve`** process: SQLite keeps
  working on the renamed file via its open descriptor; the server would
  keep serving stale tokens until restart. `AuthLock` only guards
  concurrent `auth`/`renew`, not `serve`. Mitigation: document "restart
  the MCP server after re-auth" (already implied by token reload
  behavior); assess whether `serve` should hold a shared lock.
- Credential safety: the `.bak` file holds live tokens — enforce
  `0o600` and parent `0o700` immediately; never log its contents.
- `auth-status` is local-only by design and will still report
  `valid` with remaining lifetimes for server-side-dead tokens; out of
  scope here, but worth a docs note (the honest signal for dead tokens
  is a failed tool call with `reauth_needed`).
- The affected host runs an unknown version; fix should be validated
  against schwabdev 4.0.0 (repo-pinned) only.

## Open Questions

- [NEEDS CLARIFICATION: schwab-mcp/schwabdev version on `Server1` —
  transcript timestamps suggest post-v0.7.1; behavior is identical on
  current main either way]
- [NEEDS CLARIFICATION: should `auth` with a **healthy** store still
  force a full re-authorization (simple, deterministic), or only when a
  freshness probe fails? The preferred fix forces always — confirm that
  matches the intended UX of the `auth` command]