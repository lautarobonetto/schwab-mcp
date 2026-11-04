# Bug Verification: Store backup and quarantine repeat the same move-aside algorithm (DRY)

- **Slug**: td-011
- **Tested**: 2026-11-04
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The duplication no longer reproduces: the move-aside sequence exists exactly once in `src/schwab_mcp/tokens.py` (inside `_move_store_aside`), and both public wrappers delegate to it. Behavior is pinned by the unchanged existing suites plus an independent end-to-end functional check; no regressions found.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | `grep -n 'os.rename\|os.chmod\|while target.exists\|with_name(f"{src.name}'` over `src/schwab_mcp/tokens.py` | pass | The assessment's "reproduction" was static (compare two identical bodies). Post-fix, the sequence exists only in `_move_store_aside` (lines 184–191). The other `os.chmod` hits (289, 291) belong to `enforce_permissions`, unrelated and pre-existing. |
| Independent functional check | `uv run python tmp/scratch_verify_td011.py` (scratch, since removed) | pass | Exercised both wrappers end to end on temp fixtures: exact `<name>.<suffix>.<UTC stamp>` naming, `0o600` after move (from a deliberately permissive 0o644), content preserved, guard no-ops (backup skips absent/corrupted; quarantine skips present), sidecar `-journal` dropped, and collision counter `-1` fallback forced through both wrappers. |
| Pinning suites (fix-relevant) | `uv run pytest tests/unit/test_tokens_backup.py tests/unit/test_tokens_quarantine.py tests/unit/test_tokens.py -q` | pass | 59 passed — unchanged from pre-fix baseline, proving behavior preservation. |
| Regression suite (full gate) | `uv run pytest -q` | pass | 1819 passed, 0 skipped — identical count to the pre-fix baseline recorded in the assessment/fix report. |
| Lint / type-check | — | not-run | No linter or type-checker is configured in this project (`pyproject.toml` dev deps: pytest, pytest-asyncio only); nothing to run. |

## Output Excerpts

```
$ uv run pytest tests/unit/test_tokens_backup.py tests/unit/test_tokens_quarantine.py tests/unit/test_tokens.py -q
...........................................................              [100%]
59 passed in 4.23s

$ uv run pytest -q
........................................................................ [ 98%]
...................                                                      [100%]
1819 passed in 33.37s

$ uv run python tmp/scratch_verify_td011.py
ALL TD-011 FUNCTIONAL CHECKS PASSED
```

Structural grep excerpt (post-fix, single occurrence of the algorithm):

```
184:    target = src.with_name(f"{src.name}.{suffix}.{stamp}")
186:    while target.exists():  # never overwrite an existing target
189:    os.rename(src, target)
191:    os.chmod(target, 0o600)
```

## Residual Risks

- The `_move_store_aside` naming/permission/sidecar behavior is covered by the existing suites at the public-wrapper level; there is no dedicated unit test calling `_move_store_aside` directly. Acceptable per the assessment (characterization harness), and the private helper is exercised through both wrappers.
- Scratch functional check ran on macOS temp fixtures only; platform-specific rename semantics (e.g., Windows) are not exercised here — same limitation as the existing suite.

## Recommendation

Close the bug — the DRY symptom is eliminated (single home of the algorithm), behavior is verified preserved end to end, and the full gate is green (1819 passed, 0 skipped). Ready to commit per the constitution (code + `docs/tech-debt.md` + `docs/CHANGELOG.md` in one commit).