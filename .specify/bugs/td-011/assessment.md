# Bug Assessment: Store backup and quarantine repeat the same move-aside algorithm (DRY)

- **Slug**: td-011
- **Created**: 2026-11-04
- **Source**: pasted text (tracked as TD-011 in `docs/tech-debt.md:446`)
- **Verdict**: valid
- **Severity**: low

## Report (verbatim or summarized)

> ### TD-011 — Store backup and quarantine: same algorithm twice (DRY)
>
> **Area:** `src/schwab_mcp/tokens.py:169-198` vs `252-278`
>
> `backup_token_store` and `quarantine_corrupt_store` repeat: unique name
> via `stamp` + `while target.exists()` counter, `os.rename`,
> `os.chmod(0o600)`, `_drop_sidecars(src)`. Only the suffix
> (`.bak.` vs `.corrupt.`) and the required prior status differ.
>
> **Refactor:** `_move_store_aside(path, suffix, required_status)` plus two
> three-line wrappers.

## Symptom

Not a behavioral defect — a maintainability/DRY violation. Two functions in `src/schwab_mcp/tokens.py` implement an identical "move store aside safely" algorithm (timestamped collision-safe name, `os.rename`, `0o600` chmod, sidecar drop), differing only in the filename suffix and the required prior store status. Expected: one shared implementation, two thin wrappers. If one copy gains a fix (e.g., a new sidecar rule or permission tweak), the other silently drifts.

## Reproduction

1. Open `src/schwab_mcp/tokens.py` and read `backup_token_store` (lines 166–195).
2. Read `quarantine_corrupt_store` (lines 249–275).
3. Compare lines 182–195 with 265–275: both do `stamp = _backup_timestamp()`, build `src.with_name(f"{src.name}.{suffix}.{stamp}")`, loop with a `-<counter>` suffix while the target exists, `os.rename(src, target)`, `os.chmod(target, 0o600)`, `_drop_sidecars(src)`, and return the new path.

Verified directly against the source; no runtime reproduction is needed for a structural finding.

## Suspected Code Paths

- `src/schwab_mcp/tokens.py:166-195` (`backup_token_store`) — first copy: guard `peek_store_status(path) != "present"` → return `None`; then stamp/counter/`os.rename`/`chmod 0o600`/`_drop_sidecars(src)`.
- `src/schwab_mcp/tokens.py:249-275` (`quarantine_corrupt_store`) — second copy: guard `peek_store_status(path) != "corrupted"` → return `None`; identical body with `.corrupt.` suffix.
- `src/schwab_mcp/tokens.py:161-163` (`_backup_timestamp`) — already a shared, patchable-in-tests timestamp helper; the natural hook the shared helper should reuse.
- `src/schwab_mcp/tokens.py:237-246` (`_drop_sidecars`) — already shared; both copies call it identically, confirming the duplication is purely in the move sequence.
- `tests/unit/test_tokens_backup.py` — covers `backup_token_store` (no-overwrite counter, untouched absent/empty/corrupted stores, permissions).
- `tests/unit/test_tokens_quarantine.py` — covers `quarantine_corrupt_store` (no-overwrite counter, untouched present/absent stores, sidecar drop).

## Root Cause Hypothesis

The two features (auth backup, corrupted-store quarantine) were built as separate bug fixes (auth-false-success and auth-corrupt-store-blocked, per the docstrings) and each inherited the same move-aside sequence without extracting a helper. Confidence: **high** — the duplication is verbatim in the source; only the guard predicate and filename suffix differ.

## Proposed Remediation

**Preferred**: Extract a private helper in `src/schwab_mcp/tokens.py`:

```python
def _move_store_aside(path: str | os.PathLike, suffix: str, required_status: str) -> Optional[Path]:
    """Move the store aside if its status matches *required_status*.

    Renames to ``<name>.<suffix>.<UTC stamp>[-<counter>]`` (never
    overwriting), sets 0o600, and drops sidecars at the original name.
    Returns the new path, or ``None`` when the store is not in
    *required_status*.
    """
    if peek_store_status(path) != required_status:
        return None
    src = Path(path)
    stamp = _backup_timestamp()
    target = src.with_name(f"{src.name}.{suffix}.{stamp}")
    counter = 1
    while target.exists():
        target = src.with_name(f"{src.name}.{suffix}.{stamp}-{counter}")
        counter += 1
    os.rename(src, target)
    os.chmod(target, 0o600)
    _drop_sidecars(src)
    return target
```

Then `backup_token_store` becomes a three-line wrapper calling `_move_store_aside(path, "bak", "present")` (keeping its docstring and return contract) and `quarantine_corrupt_store` calls `_move_store_aside(path, "corrupt", "corrupted")`. Keep `_backup_timestamp` as the stamp source so the existing test patch seam continues to work. This is pure refactoring — the constitution's TDD gate is satisfied by the existing green suites (`test_tokens_backup.py`, `test_tokens_quarantine.py`) acting as the characterization harness; no new behavior, so no new tests are strictly required, though a test exercising the shared no-overwrite counter through both public wrappers already exists in both files.

**Alternatives**:
- Do nothing / leave as-is: zero risk, but the drift risk stands — any future fix to one copy (e.g., handling `PermissionError` on rename) must be remembered in both.
- Merge into one public function with a `mode: Literal["backup", "quarantine"]` parameter: rejects the duplication but changes the public API and callers (`auth`/`serve`/`renew` CLI flows) — violates KISS and breaks the documented per-function contracts for no gain.

**Files likely to change**:
- `src/schwab_mcp/tokens.py` (add `_move_store_aside`, slim both wrappers; update `docs/tech-debt.md` to close TD-011)

**Tests to add or update**:
- None new — existing `tests/unit/test_tokens_backup.py` and `tests/unit/test_tokens_quarantine.py` must stay green unchanged (that they do is itself the proof the refactor is behavior-preserving). If the refactor accidentally changes naming, permissions, or sidecar behavior, these suites catch it.

## Risks & Considerations

- Very low. Both wrappers are private-adjacent module API used by internal CLI flows; signature and return contract stay identical.
- Preserve the `_backup_timestamp` patch seam — some tests patch it; the helper must not inline its own `time.strftime`.
- Keep the distinct docstrings on the public wrappers: each documents a different bug rationale (FR-003/FR-010 vs FR-009/auth-corrupt-store-blocked) that readers of the shared helper shouldn't need.
- Constitution gate: affected docs (`docs/tech-debt.md`) must be updated in the same commit.

## Open Questions

- None.