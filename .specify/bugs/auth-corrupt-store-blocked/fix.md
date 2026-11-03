# Bug Fix: corrupted store made `auth` a dead-end loop ("Store treated as absent")

- **Slug**: auth-corrupt-store-blocked
- **Fixed**: 2026-11-03
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

`run_auth` no longer refuses to run on a corrupted store: the unusable
file is quarantined (renamed to `tokens.db.corrupt.<UTC timestamp>`,
owner-only, content preserved, stray SQLite sidecars removed) and the
fresh authorization flow proceeds — honoring the error message's own
"treated as absent" promise. Backup/restore now also drops stray
`-journal`/`-wal`/`-shm` sidecars so a restored store is never shadowed
by a foreign hot journal (the likely Server1 poisoning mechanism).

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/tokens.py` | modified | Added `quarantine_corrupt_store` (corrupted-only, `*.corrupt.<ts>`, `0o600`, collision-safe, drops sidecars) + `_sidecar_paths`/`_drop_sidecars`; `backup_token_store` drops sidecars after the rename; `restore_token_store` drops sidecars after `os.replace` |
| `src/schwab_mcp/cli.py` | modified | `run_auth`: corrupted guard → quarantine inside the `AuthLock` + `auth_start` event with detail `corrupt store quarantined: <file>`; `TokenStoreCorruptedError` (exit 5) only when the rename itself fails with `OSError` |
| `tests/unit/test_tokens_quarantine.py` | added | 6 unit tests: quarantine contract + sidecar hygiene, incl. the Server1 mechanism (valid DB shadowed by a hot journal reads as corrupted → quarantined with content preserved) |
| `tests/integration/test_failures.py` | modified | `TestAuthCorruptedStore` rewritten: exit 5 dead-end → quarantine + flow reached (exit 3 with the inert client); content-preservation test kept (now at the quarantine path); bounded test kept |
| `tests/integration/test_auth.py` | added | `TestCorruptStoreRecovery` (2 tests): corrupted → fresh flow → exit 0 with fresh tokens; corrupted → cancelled flow → quarantine survives, no garbage restored |
| `specs/001-schwab-oauth-access/contracts/cli.md` | modified | `auth` Behavior point 6: quarantine semantics; `serve` exit-5 contract unchanged |
| `docs/usage.md` | modified | Failure-modes row for exit 5 + troubleshooting row for the repeated "Store treated as absent" symptom (with manual workaround for older versions) |
| `docs/tools.md` | modified | `schwab-mcp auth` section: quarantine semantics |
| `docs/CHANGELOG.md` | modified | `[Unreleased]` → Fixed entry + compare link |

## Diff Highlights

The dead-end guard becomes self-healing:

```python
# before (cli.py)
if peek_store_status(config.token_db) == "corrupted":
    raise TokenStoreCorruptedError(detail="Store treated as absent; run `schwab-mcp auth`")

# after
quarantined: Path | None = None
if peek_store_status(config.token_db) == "corrupted":
    try:
        quarantined = quarantine_corrupt_store(config.token_db)
    except OSError:
        raise TokenStoreCorruptedError(
            detail="Store could not be quarantined; fix permissions and re-run"
        ) from None
auth_event("auth_start", "initiated",
           f"corrupt store quarantined: {quarantined.name}"
           if quarantined else "browser flow requested")
```

Sidecar hygiene on restore (the poisoning mechanism):

```python
os.replace(backup, store_path)
_drop_sidecars(Path(store_path))  # foreign hot journal must not shadow the restored DB
```

## Tests Added or Updated

- `tests/unit/test_tokens_quarantine.py` (6) — quarantine moves a
  corrupt store with sidecars (content preserved, `0o600`, no sidecars
  left); present/absent stores untouched; same-second collisions get
  distinct names; **valid DB shadowed by a hot journal reads as
  "corrupted" and is quarantined intact** (Server1 mechanism);
  restore drops stray sidecars so the restored store reads "present".
- `tests/integration/test_failures.py::TestAuthCorruptedStore` (3,
  rewritten) — corrupt store ⇒ quarantined + flow reached (exit 3, no
  traceback, no secrets); content preserved at the quarantine path;
  bounded runtime.
- `tests/integration/test_auth.py::TestCorruptStoreRecovery` (2) —
  corrupted → real fresh flow → exit 0 + fresh tokens (hook invoked);
  cancelled recovery keeps the quarantine and never resurrects garbage.
- Removed: `test_auth_corrupted_store_exits_5` and
  `test_auth_corrupted_store_no_browser_no_prompt` (they pinned the
  dead-end itself). `serve` corrupted tests untouched.

## Local Verification

- Commands run:
  - New tests pre-implementation → RED: ImportError (`quarantine_corrupt_store`
    missing) + 4 failed / 1 passed (the fail-fast guard still live).
  - `uv run pytest tests/unit/test_tokens_quarantine.py tests/unit/test_tokens_backup.py tests/integration/test_failures.py tests/integration/test_auth.py`
    → 79 passed.
  - `uv run pytest` (full suite) → **1605 passed, 0 skipped**
    (was 1598: +6 unit, +2 integration, −1 obsolete test replaced).
- Manual checks: none (no corrupted store available in this
  environment; the interrupted-flow trigger requires a killed process —
  covered via the sidecar/journal unit tests).

## Deviations from Assessment

- The assessment's preferred remediation put quarantine "before the
  client construction" without pinning lock order; implemented **inside
  the `AuthLock`** so concurrent runs cannot race on the rename (second
  run then sees an absent store and is correctly refused by the lock).
- Added an `except OSError` fallback around the quarantine that
  re-raises `TokenStoreCorruptedError` (exit 5) — the assessment kept
  exit 5 only for the "cannot be renamed" corner without specifying the
  mechanism; this preserves a clean message instead of a raw traceback.
- Assessment's open question resolved: quarantine is reported via the
  existing `auth_start`/`initiated` event with detail
  `corrupt store quarantined: <file>` (the events contract's `detail`
  is free-form text; no new event type needed).

## Follow-ups

- On `Server1`: after deploying, run `uv run schwab-mcp auth` — the
  corrupt store should be quarantined automatically and the browser
  flow should run. Inspect `~/.schwab-mcp/` afterwards (`.corrupt.*` /
  `.bak.*` files confirm the diagnosis; they can be deleted once done).
- Consider a retention note (or a cap) for accumulated
  `.bak.*`/`.corrupt.*` files.
- Roll `[Unreleased]` into the next release commit (PATCH bump).