# Bug Fix: Store backup and quarantine repeat the same move-aside algorithm (DRY)

- **Slug**: td-011
- **Fixed**: 2026-11-04
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Extracted the duplicated safe move-aside sequence from `backup_token_store` and `quarantine_corrupt_store` into a shared `_move_store_aside(path, suffix, required_status)` helper; both public functions are now three-line wrappers. Behavior-preserving — the existing suites passed unchanged.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/tokens.py` | modified | Added `_move_store_aside` (single home of the sequence); `backup_token_store` → `_move_store_aside(path, "bak", "present")`; `quarantine_corrupt_store` → `_move_store_aside(path, "corrupt", "corrupted")`. Docstrings and return contracts unchanged; `_backup_timestamp` remains the stamp source and test patch seam. |
| `docs/tech-debt.md` | modified | TD-011 table row → `Fixed (v0.9.8, 2026-11-04)`; resolution paragraph added to the TD-011 section (mirrors TD-010's format). |
| `docs/CHANGELOG.md` | modified | New entry under `### Changed` describing the de-duplication, following the established per-fix style. |

No tests were changed (per the assessment: none new; existing suites are the characterization harness).

## Diff Highlights

New shared core (inserted after `_backup_timestamp`):

```python
def _move_store_aside(
    path: str | os.PathLike, suffix: str, required_status: str
) -> Optional[Path]:
    """Move the token store aside to a timestamped sibling (shared core)."""
    if peek_store_status(path) != required_status:
        return None
    src = Path(path)
    stamp = _backup_timestamp()
    target = src.with_name(f"{src.name}.{suffix}.{stamp}")
    counter = 1
    while target.exists():  # never overwrite an existing target
        target = src.with_name(f"{src.name}.{suffix}.{stamp}-{counter}")
        counter += 1
    os.rename(src, target)
    os.chmod(target, 0o600)
    _drop_sidecars(src)
    return target
```

The wrappers:

```python
def backup_token_store(path):        # docstring unchanged
    return _move_store_aside(path, "bak", "present")

def quarantine_corrupt_store(path):  # docstring unchanged
    return _move_store_aside(path, "corrupt", "corrupted")
```

Net effect: the 14-line duplicated body collapsed into one helper; each public function keeps its rationale docstring (FR-003/FR-010 vs FR-009/auth-corrupt-store-blocked).

## Tests Added or Updated

- None. Per the assessment, the existing suites pin the behavior:
  - `tests/unit/test_tokens_backup.py` — no-overwrite counter, untouched absent/empty/corrupted stores, permissions, restore/discard contracts.
  - `tests/unit/test_tokens_quarantine.py` — no-overwrite counter, untouched present/absent stores, sidecar drop.

## Local Verification

- Commands run:
  - `uv run pytest tests/unit/test_tokens_backup.py tests/unit/test_tokens_quarantine.py tests/unit/test_tokens.py -q` → 59 passed.
  - `uv run pytest -q` (full gate) → **1819 passed, 0 skipped** (same count as the pre-change baseline recorded for TD-010).
- Manual checks: confirmed the exact duplicated lines (`stamp`/counter/`os.rename`/`chmod 0o600`/`_drop_sidecars`) now exist only in `_move_store_aside`; both wrappers delegate via one-line returns; `_backup_timestamp` definition untouched (patch seam preserved).

## Deviations from Assessment

None. Scope stayed exactly within the assessment's file list (`src/schwab_mcp/tokens.py` + tech-debt doc update); the CHANGELOG entry follows the constitution's "affected documentation updated" rule, matching how TD-010's fix was recorded.

## Follow-ups

- Commit with the full green suite (constitution gate) — message should list the code + tech-debt + CHANGELOG changes together.
- Remaining open tech-debt siblings (TD-012, TD-013, …) are unrelated; no action here.