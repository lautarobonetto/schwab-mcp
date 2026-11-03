# Bug Fix: `schwab-mcp auth` reports success with dead tokens in the store

- **Slug**: auth-false-success
- **Fixed**: 2026-11-03
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

`run_auth` now performs a full, fresh re-authorization on every run: an
existing store is moved to a timestamped sibling backup before the
schwabdev client is constructed (so the empty-store path always reaches
the `call_on_auth` hook), restored byte-identically on any failure or
cancellation, and discarded on success. The success gate additionally
requires fresh-write evidence (hook ran or store content changed), so
surviving stale rows can never be reported as "Authorization
successful" — which repairs the `renew` → `reauth_required` →
`auth` recovery loop.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/tokens.py` | modified | Added `backup_token_store` (present-only, `0o600`, collision-safe via `_backup_timestamp()` + counter), `restore_token_store` (atomic `os.replace`, no-op without backup), `discard_token_store_backup` |
| `src/schwab_mcp/cli.py` | modified | `run_auth`: backup before client construction; flow wrapped in `try/except BaseException` that restores on any failure; success gate = `peek_store` AND (`hook_calls > 0` OR store bytes differ from pre-run); backup discarded on success; `_read_store_bytes` helper |
| `tests/integration/test_auth.py` | modified | New `TestStaleStoreReauthorization` (4 regression tests); `TestReauthFlow.test_reauth_on_existing_store_succeeds` updated to drive the real flow (it pinned the buggy behavior) |
| `tests/unit/test_tokens_backup.py` | added | 12 unit tests for the backup/restore/discard helper contract |
| `specs/001-schwab-oauth-access/contracts/cli.md` | modified | `auth` Behavior 3–5: always-fresh flow, fresh-write success gate, backup/restore semantics |
| `docs/tools.md` | modified | `schwab-mcp auth — humans only` section: always re-authorizes, backup semantics |
| `docs/usage.md` | modified | Token lifecycle: `auth` always re-authorizes; `invalid_grant` scenario; backup preserved on failure, discarded on success |
| `docs/CHANGELOG.md` | modified | `[Unreleased]` → Fixed entry + compare link |

## Diff Highlights

Backup → fresh flow → restore/discard in `run_auth`:

```python
pre_bytes = _read_store_bytes(config.token_db)
backup_path = backup_token_store(config.token_db)
try:
    ...  # schwabdev.Client(..., call_on_auth=counted_hook) — empty store ⇒ hook runs
    fresh_write = (
        hook_calls > 0
        or _read_store_bytes(config.token_db) != pre_bytes
    )
    if not peek_store(config.token_db) or not fresh_write:
        ...  # auth_failure events
        raise AuthorizationCancelledError()
except BaseException:
    restore_token_store(backup_path, config.token_db)  # FR-010
    raise
discard_token_store_backup(backup_path)  # success ⇒ backup obsolete
```

## Tests Added or Updated

- `tests/unit/test_tokens_backup.py` (12 tests) — backup moves a
  present store to a `*.bak.<ts>` sibling with `0o600`; absent/empty/
  corrupted stores return `None` untouched; existing backups are never
  overwritten (frozen timestamp + counter); restore puts original bytes
  back with `0o600` and consumes the backup; no-backup paths are no-ops;
  discard removes the backup.
- `tests/integration/test_auth.py::TestStaleStoreReauthorization` (4
  tests) —
  - `test_stale_store_runs_fresh_flow_not_silent_success`: pre-existing
    store + successful paste ⇒ exit 0 AND hook invoked ≥1 (pre-fix: hook
    0 + false success).
  - `test_stale_store_with_inert_client_never_reports_success`: no fresh
    write ⇒ exit ≠ 0 and no "Authorization successful" on stdout.
  - `test_cancelled_reauth_restores_store_and_leaves_no_backup`: decline
    at the prompt ⇒ exit 3, store byte-identical (FR-010), zero `*.bak*`
    files.
  - `test_successful_reauth_leaves_no_backup`: success discards the
    backup.
- `tests/integration/test_auth.py::TestReauthFlow::test_reauth_on_existing_store_succeeds`
  — updated: re-auth now requires (and asserts) the real fresh flow.

## Local Verification

- Commands run:
  - `uv run pytest tests/unit/test_tokens_backup.py tests/integration/test_auth.py::TestStaleStoreReauthorization`
    (pre-implementation) → RED: ImportError (helpers missing) + 3 failed /
    1 passed, as designed.
  - `uv run pytest tests/integration/test_auth.py tests/unit/test_tokens_backup.py`
    → 44 passed.
  - `uv run pytest` (full suite) → **1598 passed, 0 skipped** (was 1582;
    +12 helper +4 regression, 1 test updated in place).
- Manual checks: not performed (no live Schwab credentials in this
  environment; the `invalid_grant` reproduction requires a server-side
  revoked refresh token — covered at the fake-client level).

## Deviations from Assessment

None of substance. Minor concretizations within the proposed shape:

- Backup file name uses `<UTC timestamp>` compact form
  (`tokens.db.bak.20261103T120000Z`) plus a `-<n>` counter for
  same-second collisions; the assessment left the exact format open.
- The helper set is three functions (`backup` / `restore` / `discard`)
  rather than two, so the success path does not misuse "restore" to
  delete.
- The assessment's second listed test ("backup file gets 0o600 … and a
  pre-existing `.bak` is never silently overwritten") is covered at the
  unit level (`test_tokens_backup.py`) rather than inside the
  integration flow.

## Follow-ups

- Validate on the affected host (`Server1`) once this fix ships: with a
  revoked refresh token, `schwab-mcp auth` must print the URL, run the
  browser flow, and finish with real credentials.
- Consider a docs note that `auth-status` stays `valid` for
  server-side-revoked tokens (local read by design) — the honest signal
  is a tool call failing with `reauth_needed`.
- Assess whether `serve` should take a shared lock during `auth` (the
  renamed store is invisible to a running server until restart; SQLite
  keeps serving the stale open file).
- Roll the `[Unreleased]` changelog section into the next release
  commit (PATCH bump suggested).