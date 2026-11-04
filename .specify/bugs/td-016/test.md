# Bug Verification: TD-016 — Dead parameters in helpers

- **Slug**: td-016
- **Tested**: 2026-11-04
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The dead `range_days` parameter no longer exists: `_should_split` takes only `movements`,
the caller-side computation is gone, and the cap is the named constant `UPSTREAM_TXN_CAP`.
No regressions — the full suite (1826 tests) passes with 0 skipped.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | `grep -n "def _should_split\|range_days\|UPSTREAM_TXN_CAP\|>= 3000" src/schwab_mcp/transactions.py` | pass | `_should_split(movements: list)` at line 393 uses `UPSTREAM_TXN_CAP`; no `range_days` kwarg at the call site (line 487). Remaining `range_days` uses (lines 337–354) belong to `validate_history_query` span validation — legitimate, unrelated logic. No bare `>= 3000` literal remains outside the constant definition |
| New / updated tests | `uv run pytest tests/unit/test_transactions_split.py -q` | pass | 33 passed, including `test_cap_constant_value` and the cap-parameterized boundary tests |
| Regression suite | `uv run pytest -q` | pass | 1826 passed in ~33s (commit gate: full suite green, 0 skipped) |
| Lint / type-check | — | not-run | Project configures no lint/type-check tooling (`pyproject.toml` has none; CI runs only `uv sync && uv run pytest`) |

## Output Excerpts

```
$ uv run pytest tests/unit/test_transactions_split.py -q
.................................                                        [100%]
33 passed in 0.14s

$ uv run pytest -q
........................................................................ [ 98%]
..........................                                               [100%]
1826 passed in 33.15s

$ grep -n "def _should_split\|range_days\|UPSTREAM_TXN_CAP\|>= 3000" src/schwab_mcp/transactions.py
249:UPSTREAM_TXN_CAP = 3000
337:    range_days = (end - start).days        # validate_history_query — unrelated
393:def _should_split(movements: list) -> bool:
401:    return len(movements) >= UPSTREAM_TXN_CAP
```

## Residual Risks

- None material. This was an inspection-verified hygiene bug (no runtime reproduction
  existed, per the assessment); structural checks confirm the defect shape is gone and the
  behavior-identical trigger is locked by boundary tests against the named constant.
- `_should_split` remains a private helper with a single caller; any external (test-only)
  consumer using the old two-argument form would break, but none exists in this repo.

## Recommendation

Close the bug — TD-016 is fully resolved: both open `transactions.py` rows are fixed (the
other two rows were already fixed under TD-007/TD-008), docs are struck through, the
CHANGELOG entry is in place, and the full suite is green. Commit the change set together
(docs included) per the constitution gate.
