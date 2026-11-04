# Bug Fix: Release: duplicated validation and except-clones in `cmd_build` (DRY)

- **Slug**: td-015
- **Fixed**: 2026-11-04
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Applied the assessment's preferred DRY refactor verbatim: `cmd_build` now has a single `except ReleaseError` failure path (exit 3), the duplicate source-file validation loop is deleted, `build_wheel` receives the caller-resolved version instead of re-reading `pyproject.toml`, and `checks.py` strips the `wrap/` prefix through one shared `_relative_name` helper. Behavior-preserving; full suite green (1826 passed, 0 skipped).

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp_release/cli.py` | modified | Single `except ReleaseError → print → return 3` around resolve/build/assemble; deleted the `sources.items()` pre-validation loop; dropped now-unused `VersionError`/`WheelBuildError` imports; docstring documents the single failure path |
| `src/schwab_mcp_release/wheel.py` | modified | Signature changed to `build_wheel(project_root, version, out_dir)`; `expected = wheel_name(version)`; removed the `resolve_version` import; docstring states the version is resolved exactly once by the caller |
| `src/schwab_mcp_release/checks.py` | modified | Extracted `_relative_name(entry, wrap)`; used in `_iter_entries` (replacing the inline `prefix` strip) and in `check_completeness`'s `UNEXPECTED:` branch |
| `tests/unit/test_release_cli.py` | modified | All three fake builders updated to the `(project_root, version, out_dir)` signature (fixture, `boom`, dev-material `build`) |
| `tests/unit/test_release_wheel.py` | modified + added | Six direct `build_wheel` calls updated; added `test_version_argument_names_the_expected_wheel` pinning that the version argument names the wheel |
| `tests/unit/test_release_checks.py` | added tests | `TestRelativeName`: four cases covering the strip, bare top-level, outside-wrap, and lookalike-prefix (`wrap-extra/…` not stripped) |
| `docs/tech-debt.md` | modified | TD-015 ledger row → `Fixed (v0.9.8, 2026-11-04)`; resolution paragraph appended to the TD-015 detail section |
| `docs/CHANGELOG.md` | modified | Entry under `[Unreleased] → Changed`, following the TD-014 precedent |

## Diff Highlights

`cli.py` — three except blocks become one; the validation loop disappears:

```python
        try:
            version = resolve_version(root)

            build_dirty = _tree_is_dirty(root)
            if build_dirty and not allow_dirty:
                print(_DIRTY_MESSAGE, file=sys.stderr)
                return 2

            wheel = build_wheel(root, version, staging)
            sources = source_map(root, version, wheel.path)
            result = assemble_archive(...)
        except ReleaseError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 3
```

`wheel.py` — no re-resolution:

```python
def build_wheel(project_root: Path, version: str, out_dir: Path) -> WheelBuild:
    expected = wheel_name(version)
```

`checks.py` — one strip helper:

```python
def _relative_name(entry: str, wrap: str) -> str:
    """*entry* relative to the wrapping directory (unchanged when outside)."""
    return entry[len(wrap) + 1 :] if entry.startswith(f"{wrap}/") else entry
```

## Tests Added or Updated

- `tests/unit/test_release_wheel.py::TestBuildWheel::test_version_argument_names_the_expected_wheel` — pins that the caller-passed version names the wheel (`build_wheel` no longer re-reads `pyproject.toml`)
- `tests/unit/test_release_checks.py::TestRelativeName` (4 tests) — pins the single prefix-strip helper: wrapped member stripped, bare top-level kept, outside-wrap kept, `wrap`-prefix lookalike (`schwab-mcp-9.9.9-extra/…`) kept whole
- `tests/unit/test_release_cli.py` — all fakes moved to the new signature; existing behavioral locks kept green unchanged: `test_exit_3_on_missing_source_file` (exit 3 + member path via `assemble_archive`'s `ReleaseError`), `test_exit_3_when_version_unresolvable`, `test_exit_3_on_wheel_build_failure` (all now through the single except)

## Local Verification

- Commands run: `uv run pytest tests/unit/test_release_cli.py tests/unit/test_release_wheel.py tests/unit/test_release_checks.py tests/unit/test_release_archive.py tests/unit/test_release_allowlist.py tests/unit/test_release_checks_dev_material.py tests/unit/test_release_checks_secrets.py -q` → **106 passed**
- Commands run: `uv run pytest -q` → **1826 passed, 0 skipped** (1821 before the change + 5 new tests)
- TDD gate: tests updated/added first, confirmed **Red** (20 failed + 1 collection ImportError: old-signature `TypeError`s and missing `_relative_name`), then source implemented → **Green** with no test weakened.

## Deviations from Assessment

None material. One detail worth recording: the assessment said "the dirty-tree guard (`return 2`) stays outside the try" — implementing it that way (guard before resolution) would have changed exit-code ordering when both the version is unresolvable *and* the tree is dirty (original code: version error wins with 3; guard-first would return 2). To preserve exact behavior while keeping a single except, the guard moved *inside* the try as a plain `return 2` (returns are not exception paths, so the except cannot swallow it) and the original ordering (resolve → guard → wheel → assemble) was kept. No test or contract observes the difference; behavior is bit-identical to pre-refactor.

## Follow-ups

- Commit with the full suite green and the doc updates included (constitution gate) — `/speckit.bug.test slug=td-015` next for the formal verification pass.
- TD-016/TD-017 (dead parameters/imports in the same module family) remain Open in the ledger — unrelated but adjacent cleanup candidates.