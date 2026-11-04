# Bug Verification: TD-010 — `price_history.py`: failure-event pattern repeated manually (DRY)

- **Slug**: td-010-price-history-fail-dry
- **Tested**: 2026-11-04
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The duplication described by the assessment no longer reproduces (inspection confirms one `_fail` invocation, one detail-composition site, one `ConnectivityError` emission path), and a differential harness proved the refactor is byte-identical to the pre-fix code across all 15 failure/success scenarios. Full suite green; no regressions found.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | grep inspection of `src/schwab_mcp/price_history.py` | pass | `_fail` invoked exactly once (inside the `fail` closure, line 478; was 7 call sites). `_fail_event` is the single `f"{reason} " + _selection_detail(...)` site (line 192; was 7 composition sites). `ConnectivityError` handler has one `auth_event` + one `return` (was two branches). |
| Byte-identity (differential) | `PYTHONPATH=$PWD uv run python tmp/td010-verify/differential.py` | pass | HEAD implementation vs working tree, 15 scenarios (missing/malformed/option/bad-frequency/bad-period/extended-hours/no-candles/500/transport/401/403/ok-daily/ok-lowercase+ws/ok-weekly/ok-extended): every emitted event tuple `(name, outcome, detail)`, every returned envelope (JSON-compared), and raised errors identical. This strengthens the suite, which pins presence/absence rather than exact detail strings. |
| New / updated tests | n/a — none required | pass | Fix added no tests per assessment gate; characterization coverage was verified complete pre-refactor. `git status` confirms zero test-file modifications — the suite passing unchanged is the regression proof. |
| Regression suite (module) | `uv run pytest tests/{unit/test_price_history_events,test_price_history_validation,test_price_history_mapping,test_price_history_in_progress,test_price_history_aggregation}.py tests/performance/test_price_history_budgets.py -q` | pass | 234 passed in 0.87s. |
| Regression suite (full, commit gate) | `uv run pytest -q` | pass | **1819 passed, 0 skipped** in 34.03s. |
| Lint / type-check | — | not-run | No lint or type-checker is configured in this project (no ruff/mypy/flake8/black in `pyproject.toml` or CI). CI (`ci.yml`) runs `uv sync && uv run pytest` only. Style check done manually: wrapped the two lines exceeding the file's ~88-char convention. |

## Output Excerpts

```
# differential harness (HEAD vs working tree)
OK: 15 scenarios byte-identical (events + envelopes + raised errors)

# full suite
1819 passed in 34.03s

# git diff --stat
 src/schwab_mcp/price_history.py | 136 ++++++++++++++++------------------------
 1 file changed, 54 insertions(+), 82 deletions(-)
```

## Residual Risks

- The differential harness covers all reachable paths of `get_price_history` with the test fixtures' fake client; a real Schwab transport layer is not exercised (not needed — the refactor touches no I/O code, and the fake client drives the same `retry_call`/`ConnectivityError` plumbing).
- One documented deviation stands: the START event still passes raw `symbol` (it must precede the tool-boundary type check). The differential harness proves the emitted string is identical, so no user-visible risk.
- The differential script remains at `tmp/td010-verify/differential.py` (git-ignored scratch, per constitution) if it needs re-running.

## Recommendation

Close the bug — verified end-to-end. The duplication is eliminated (net −28 lines), behavior is proven byte-identical, and the full commit gate is green. Safe to commit per the constitution (affected documentation: none — the audit-event surface and all documented contracts are unchanged).