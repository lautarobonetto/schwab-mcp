# Bug Fix: TD-003 — SQLite token-store read triplicated (DRY)

- **Slug**: td-003-token-store-read-duplication
- **Fixed**: 2026-11-04
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Consolidated the three copies of the read-only token-store read block into a
single private helper `tokens._read_schwabdev_row(path) -> (status, row)`
(tri-state: absent / corrupted / present+row). `peek_store_status` and
`renewal.read_store_lifetime` now consume it; the duplicated `os.stat` →
empty-check → `mode=ro` connect → query → `finally: close()` blocks and the
identical `SELECT expires_in, access_token_issued, refresh_token_issued FROM
schwabdev LIMIT 1` query exist once. `peek_store` (bool) was deleted; its two
`run_auth` call sites now use `peek_store_status(...)`.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/tokens.py` | added `_read_schwabdev_row` | Single store-read implementation; returns `("absent"|"corrupted"|"present", row)` |
| `src/schwab_mcp/tokens.py` | modified `peek_store_status` | Body reduced to helper call + ISO-timestamp validation; docstring unchanged |
| `src/schwab_mcp/tokens.py` | removed `peek_store` | Deleted (assessment-preferred option); docstring reference in `backup_token_store` updated |
| `src/schwab_mcp/renewal.py` | modified `read_store_lifetime` | Consumes helper; removed duplicated block/query, function-local `import os as _os`, and module-level `sqlite3` import (both orphaned); added plain `import os` for the `os.PathLike` annotation; docstring now cites the helper |
| `src/schwab_mcp/cli.py` | modified `run_auth` | `peek_store` import removed; `cli.py:157` → `peek_store_status(...) == "absent" and hook_calls == 0`; `cli.py:169` → `peek_store_status(...) == "absent" or not fresh_write`; stale `peek_store` comments updated |
| `tests/unit/test_tokens.py` | added tests | `TestPeekStore` replaced by `TestReadSchwabdevRow` (tri-state fixtures) + `TestStoreReadEquivalence` |
| `tests/integration/test_auth.py` | modified | 7 `peek_store` usages migrated to `peek_store_status` (fake-client auto-start + success assertions); scope expansion — see Deviations |
| `tests/integration/test_serve.py` | modified | Docstring reference `peek_store()` → `peek_store_status()` (comment-only) |

## Diff Highlights

The single store-read implementation (`tokens.py`):

```python
def _read_schwabdev_row(path) -> tuple[str, Optional[tuple]]:
    ...
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return "absent", None
    except (OSError, ValueError):
        return "corrupted", None
    if st.st_size == 0:
        return "absent", None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return "corrupted", None
    try:
        row = con.execute(
            "SELECT expires_in, access_token_issued, refresh_token_issued "
            "FROM schwabdev LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        return "corrupted", None
    finally:
        con.close()
    if row is None:
        return "absent", None
    return "present", row
```

Consumers collapsed to one call (`renewal.py`):

```python
status, row = _read_schwabdev_row(path)
if status != "present" or row is None:
    return None
expires_in, access_issued, refresh_issued = row
```

`run_auth` success gate (`cli.py:169`) — faithful translation of the deleted
`not peek_store(...)`:

```python
if peek_store_status(config.token_db) == "absent" or not fresh_write:
```

## Tests Added or Updated

- `tests/unit/test_tokens.py::TestReadSchwabdevRow` — pins the helper's tri-state for: missing file, empty file, non-SQLite bytes, missing `schwabdev` table, empty table, valid full-schema row (returns the raw `(expires_in, access_token_issued, refresh_token_issued)` tuple).
- `tests/unit/test_tokens.py::TestStoreReadEquivalence::test_peek_store_status_aligns_with_helper` — `peek_store_status` output matches the helper's structural status across all fixtures (its only refinement is ISO-timestamp validation, which can downgrade "present" but never upgrade "absent"/"corrupted").
- `tests/unit/test_tokens.py::TestStoreReadEquivalence::test_auth_gate_expression_semantics` — pins `peek_store_status(...) == "absent"` as the translation of the deleted `not peek_store(...)` in the `run_auth` gate, documenting that corrupted stores are unreachable there (quarantined before the flow; store moved aside by `backup_token_store`).
- Existing `tests/unit/test_renewal.py::TestStoreLifetimeReader` (17 tests) and the full `tests/unit/test_tokens.py::TestPeekStoreStatus` suite act as the behavior-equivalence guard for `read_store_lifetime` / `peek_store_status` — all green unchanged.

TDD: red phase confirmed first (`ImportError: cannot import name '_read_schwabdev_row'`), then implementation.

## Local Verification

- Commands run: `uv run pytest tests/unit/test_tokens.py tests/unit/test_renewal.py -q` → 83 passed.
- Commands run: `uv run pytest -q` (full suite) → **1772 passed, 2 failed**.
- The 2 failures (`tests/unit/test_option_expirations.py::TestDteCeiling::test_dte_max_30_…` / `test_dte_max_365_…`) are **pre-existing and unrelated**: verified by `git stash` + full re-run of that subset on the base tree (same 2 failures). They belong to the uncommitted `dte_max` work already present in this working tree, not to TD-003.
- An intermediate full-suite run (before the gate-translation fix below) surfaced 39 failures across the auth flow — all traced to one inverted expression in `cli.py:169` and fixed; this is exactly the `cli.py:157,169` regression risk the assessment flagged.

## Deviations from Assessment

1. **Gate expression inverted relative to the assessment's literal proposal.** The assessment suggested replacing `peek_store` with `peek_store_status(...) != "absent"` at both `cli.py` call sites. As written that inverts the failure gate: `not peek_store(x)` means "no usable row" → fail, so the faithful translation is `== "absent"`, not `!= "absent"`. Using `!= "absent"` in the failure condition made every *successful* auth fail (39 test failures). Applied `== "absent"` at both sites; the semantics change for corrupted stores discussed in the assessment (old bool collapsed them into "missing") is preserved-and-documented rather than adopted, since corrupted stores are unreachable at both call sites (quarantine at `cli.py:103`, store moved aside by `backup_token_store` at `cli.py:128`).
2. **Scope expansion: `tests/integration/test_auth.py`.** The assessment's file list missed that this module imports `peek_store` directly and asserts with it in 7 places (including the `FakeSchwabdevClient` v4 auto-start simulation). Migrated to `peek_store_status` (auto-start: `== "absent"`; success assertions: `== "present"`). No production behavior changed by this — the fake mirrors schwabdev's "DB has no tokens" check.
3. **Minor hygiene inside assessed files**: removed the now-orphaned `import os as _os` (function-local and module-level) and `import sqlite3` from `renewal.py`, added plain `import os` there because the `read_store_lifetime` signature annotates `os.PathLike`.

## Follow-ups

- `docs/tech-debt.md` still lists TD-003 as open (lines ~130-141) — mark resolved when committing.
- `tests/integration/test_failures.py:449,460` docstrings still describe the historical `peek_store`-based behavior ("returns False for corrupted content") as *current*; they were stale before this change (server.py already uses `peek_store_status`) but were left untouched as out of scope — worth a comment cleanup.
- The 2 pre-existing `TestDteCeiling` failures in the working tree need resolution before any commit (constitution gate: full suite green).
- `docs/CHANGELOG.md` entry for the refactor + `peek_store` removal should accompany the commit.
