# Bug Assessment: corrupted store makes `auth` a dead-end loop ("Store treated as absent")

- **Slug**: auth-corrupt-store-blocked
- **Created**: 2026-11-03
- **Source**: pasted text (terminal transcript from remote host `openclaw@Server1`, after deploying v0.8.1)
- **Verdict**: valid
- **Severity**: high

## Report (verbatim or summarized)

Pasted transcript — two consecutive `schwab-mcp auth` runs on Server1
(post-v0.8.1) both exit immediately with no flow, no URL, no prompt:

```text
openclaw@Server1:~/projects/schwab-mcp$ set -a; source ~/.schwab-mcp/env; set +a
openclaw@Server1:~/projects/schwab-mcp$ uv run schwab-mcp auth
Store treated as absent; run schwab-mcp auth
openclaw@Server1:~/projects/schwab-mcp$ uv run schwab-mcp auth
Store treated as absent; run schwab-mcp auth
```

No URL supplied — no fetch performed, URL Trust Policy not applicable.

## Symptom

`schwab-mcp auth` aborts instantly with `Store treated as absent; run
schwab-mcp auth` (exit 5) and never reaches the authorization flow —
even though the message itself instructs the user to run `auth` again,
which reproduces the same failure forever. Expected: a corrupt token
store must not block re-authorization; `auth` should recover by moving
the unusable file aside and running a fresh flow.

## Reproduction

1. On a host where `~/.schwab-mcp/tokens.db` exists, is >0 bytes, but
   is not a readable SQLite DB with a `schwabdev` table (see Root Cause
   for how v0.8.1's backup flow can produce this state).
2. `uv run schwab-mcp auth` → exit 5, message above, no `auth_start`
   event, no flow. Repeatable forever.

The exact on-disk trigger on Server1 `[NEEDS CLARIFICATION: whether
`tokens.db.bak.*` files exist there, whether stray `tokens.db-journal`
/ `-wal` / `-shm` sidecars exist, and what happened during the first
post-upgrade auth run — was the URL/paste prompt shown, cancelled, or
the process killed?]`.

## Suspected Code Paths

- `src/schwab_mcp/cli.py:92-97` — `run_auth`'s guard:
  `peek_store_status(...) == "corrupted"` → `raise TokenStoreCorruptedError`
  BEFORE the `AuthLock` and before any flow. Exit 5; the message
  (`errors.py:54` "Store treated as absent; run schwab-mcp auth")
  circularly points back at `auth` itself.
- `src/schwab_mcp/tokens.py:53-89` (`peek_store_status`) — "corrupted"
  fires for: file exists + >0 bytes but (a) not SQLite, (b) SQLite
  without the `schwabdev` table, (c) `sqlite3.connect(mode=ro)` or the
  SELECT raises — **including a database with a hot `-journal`/`-wal`
  sidecar, which cannot be recovered in read-only mode**, and (d)
  `os.stat` raises OSError (e.g. unreadable file / non-searchable
  directory).
- `src/schwab_mcp/tokens.py:96-140` (v0.8.1 backup/restore) — the new
  flow renames the store aside and lets schwabdev create a **fresh**
  SQLite DB at the same path; `restore_token_store` uses `os.replace`
  over the main file only — it never cleans stray
  `tokens.db-journal` / `tokens.db-wal` / `tokens.db-shm` sidecars left
  by the aborted fresh DB, nor does an interrupted run (SIGKILL /
  closed terminal — `except BaseException` never runs) restore anything.
- `src/schwab_mcp/errors.py:50-54` — `TokenStoreCorruptedError`, exit 5.
- Existing tests pin the fail-fast behavior:
  `tests/integration/test_failures.py:522-614` (`test_auth_corrupted_store_exits_5`,
  `..._not_deleted`, `..._no_browser_no_prompt`, `..._bounded`) — these
  encode the dead-end as specified behavior (FR-009 "treated as absent"
  implemented as "fail fast").
- Non-affected paths: `renew` and `serve` map corrupted →
  `reauth_required`/exit with "run: schwab-mcp auth" (renewal.py:264,
  server.py:76) — that advice becomes actionable only once `auth`
  recovers.

## Root Cause Hypothesis

Two defects compound. (1) **Trigger** (medium confidence on the exact
mechanism): the v0.8.1 backup flow moves the store aside and has
schwabdev create a fresh SQLite DB at the same path; when that run is
interrupted (killed terminal / SIGKILL — bypassing the
`except BaseException` restore) the fresh DB is left partially written
with hot journal sidecars; even on a clean cancel, `restore_token_store`
replaces only the main file, leaving stray `tokens.db-journal`/`-wal`
sidecars that make the **restored** DB unreadable read-only. In both
cases the store lands in the "corrupted" state, while the previous
(dead-but-valid) tokens survive in `tokens.db.bak.<ts>`. (2) **The
actual bug** (high confidence): `run_auth` treats "corrupted" as fatal
exit 5 with a self-referential recovery message, so no CLI path can
ever clear the state — `auth` is permanently blocked until the user
deletes files by hand. This was latent pre-v0.8.1, but v0.8.1 both
created new ways to reach the state and (correctly) made recovery flow
through `auth`, exposing the dead end.

## Proposed Remediation

**Preferred**: make `auth` self-healing — quarantine, don't refuse.

1. `run_auth`: replace the hard `TokenStoreCorruptedError` raise with a
   quarantine step: a corrupted store (and any `tokens.db-journal` /
   `-wal` / `-shm` sidecars) is renamed aside to
   `tokens.db.corrupt.<UTC timestamp>` (chmod 0600 — it may contain
   token fragments), an `auth_event` records the quarantine, and the
   fresh authorization flow proceeds. The error message's own contract
   ("treated as absent") is finally honored. A killed-flow scenario
   then also self-heals on the next `auth` run.
2. `backup_token_store` / `restore_token_store` / `discard` hygiene:
   move stray SQLite sidecars along with the store (or delete them
   after `os.replace`) so a restored DB is never shadowed by a foreign
   hot journal; quarantine path handles sidecars too.
3. Keep `TokenStoreCorruptedError` for `serve` (fail-fast there is
   correct and its playbook says "run auth") — only the `auth` guard
   changes. Contract `specs/001-.../contracts/cli.md` and FR-009
   wording updated: corrupted store → quarantined, not exit 5.

**Alternatives** (optional):

- Keep exit 5 but fix the message to give concrete manual steps
  (`mv ~/.schwab-mcp/tokens.db …`). Trade-off: still a dead end for
  agents following `renew`'s advice; violates the error's own text.
- Delete the corrupted file outright. Trade-off: violates FR-009's
  "not deleted or modified" test intent and destroys forensics;
  quarantine preserves both.

**Files likely to change**:

- `src/schwab_mcp/cli.py` (guard → quarantine)
- `src/schwab_mcp/tokens.py` (quarantine helper + sidecar hygiene in
  backup/restore/discard)
- `tests/integration/test_failures.py` (corrupted-store auth tests: now
  quarantine + flow, not exit 5; the `serve` exit-5 tests stay)
- `tests/unit/test_tokens_backup.py` (sidecar handling, quarantine)
- `specs/001-schwab-oauth-access/contracts/cli.md` + `docs/usage.md` +
  `docs/tools.md` + `docs/CHANGELOG.md`

**Tests to add or update**:

- Corrupted store + `auth` → store quarantined to `*.corrupt.<ts>`
  (0600), flow runs, fresh tokens stored, exit 0.
- Corrupted store + cancelled flow → quarantined file remains, no
  restore of garbage (nothing valid to restore), exit 3.
- Stray `tokens.db-journal` next to a valid store → backup/restore
  leaves no sidecar behind; a restored store reads as "present".
- Interrupted-flow simulation: fresh DB with hot journal + no restore →
  next `auth` quarantines and proceeds.
- Existing `test_failures.py` auth corrupted tests updated; `serve`
  corrupted tests unchanged.

## Risks & Considerations

- The quarantined `.corrupt` file may contain token fragments — must be
  `0o600` and never logged (credential safety).
- Quarantine renames accumulate (`tokens.db.corrupt.<ts>`); acceptable
  (same as `.bak`), but document cleanup.
- Changing FR-009-adjacent behavior requires contract + docs updates in
  the same commit (constitution).
- Immediate **workaround for Server1 right now** (no code change):
  `mv ~/.schwab-mcp/tokens.db*` (including any `-journal`/`-wal`) to
  quarantine names, then run `auth` — the old tokens are dead anyway
  and live in `tokens.db.bak.<ts>`.

## Open Questions

- [NEEDS CLARIFICATION: on-disk state on Server1 — list
  `~/.schwab-mcp/` (`.bak`, `.corrupt`, `-journal`/`-wal` files) and
  confirm whether the first post-upgrade run showed the URL/paste
  prompt or was killed]
- [NEEDS CLARIFICATION: should the quarantine event be a new
  `auth_event` outcome or reuse `auth_start` detail? Contracts/events.md
  has a closed enum — decide during fix]