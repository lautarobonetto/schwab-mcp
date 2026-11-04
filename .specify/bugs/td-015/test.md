# Bug Verification: Release: duplicated validation and except-clones in `cmd_build` (DRY)

- **Slug**: td-015
- **Tested**: 2026-11-04
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The bug does not reproduce: all four duplications cited in the assessment are gone from the source (single `except ReleaseError`, no pre-validation loop, no version re-resolution, one `_relative_name` helper), and the refactored pipeline passes the full suite plus a real end-to-end `build` run with the exact stdout contract. No regressions found.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | Static re-inspection of the four assessment sites (`cli.py:68-112`, `wheel.py:46`, `checks.py:26/43/72`) + grep for old duplication signatures | pass | The assessment's reproduction is explicitly static/inspection-based; each of the four observations was re-verified as eliminated. Grep for `except VersionError\|except WheelBuildError\|missing source file for {\|resolve_version(project_root)\|len(prefix)` in `src/schwab_mcp_release/` → no matches |
| New / updated tests | `uv run pytest tests/unit/test_release_wheel.py::TestBuildWheel::test_version_argument_names_the_expected_wheel tests/unit/test_release_checks.py::TestRelativeName tests/unit/test_release_cli.py::TestPrerequisiteFailure -q` | pass | 8 passed — version-argument pinning, all 4 `_relative_name` cases, and the three exit-3 behavioral locks (through the single except path) |
| Regression suite | `uv run pytest -q` (full suite) | pass | 1826 passed, 0 skipped in 33.9s (1821 before + 5 new tests) |
| End-to-end build | `uv run schwab-mcp-release build --allow-dirty` | pass | Exit 0; stdout exactly matches the stable contract (7 lines); `dist/schwab-mcp-0.9.8.zip` + `.sha256` emitted; staging cleaned. `--allow-dirty` required only because the fix itself is uncommitted |
| Lint / type-check | — | not-run | No lint or type-check tooling is configured in this project (no ruff/mypy in `pyproject.toml`, no config files, no pre-commit hooks) |

## Output Excerpts

Static re-inspection — the four assessment claims post-fix:

1. ~~`cli.py:74-78/85-89/97-106` three except blocks~~ → one handler at `cli.py:96-98`: `except ReleaseError as exc: print(f"error: {exc}", ...); return 3`, covering resolve/build/assemble
2. ~~`cli.py:92-95` duplicate validation loop~~ → deleted; `assemble_archive` (`archive.py:56-58`) is the sole missing-source check
3. ~~`wheel.py:45` re-resolves the version~~ → `expected = wheel_name(version)` from the new parameter (`build_wheel(project_root, version, out_dir)`)
4. ~~`checks.py:38` vs `67` copied strip logic~~ → `_relative_name` defined once (`checks.py:26`), used at both sites (`:43`, `:72`)

End-to-end run:

```
BUILD schwab-mcp 0.9.8
WHEEL  schwab_mcp-0.9.8-py3-none-any.whl
ARCHIVE members=7 bytes=93692
CHECKS completeness=PASS exclusion=PASS secrets=PASS
OUT    dist/schwab-mcp-0.9.8.zip
OUT    dist/schwab-mcp-0.9.8.zip.sha256
OK     build complete in 0.5s
EXIT=0
```

Full suite: `1826 passed in 33.91s`

## Residual Risks

- Message-wording drift (recorded in the assessment): a missing source file now surfaces with `assemble_archive`'s phrasing ("missing source file for member …") instead of the deleted loop's variant. Exit code 3 and the member path in stderr are unchanged and test-locked; any consumer grepping for the exact old phrase would notice.
- The end-to-end build ran with `--allow-dirty` because the fix is uncommitted; a committed-tree build was not exercised separately (behavior there is guarded by `test_clean_git_tree_builds_without_the_flag`, which passes).

## Recommendation

Close the bug — verified end-to-end. The static reproduction no longer holds, the new tests pin the single-path structure against regression, the full suite is green, and a real build produces contract-conformant output. Ready to commit (full suite green, docs included per the constitution); `/speckit.bug.fix`'s follow-up of marking TD-015 fixed in `docs/tech-debt.md` is already in place.