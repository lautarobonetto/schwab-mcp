# Bug Verification: TD-005 — Result construction repeated in `get_transaction_history` (DRY)

- **Slug**: transaction-result-dry
- **Tested**: 2026-11-04
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The bug was a code-inspection finding (no runtime defect), so the
post-fix reproduction equivalent is a re-inspection of each of the eight
claims from the assessment: all duplication is gone — one reauth result
construction (was 2), one `__cause__` inspection (was 2), one transient
construction (was 2), one `partial_failure` construction (was 2), both
"ok, no movements" sites now share `_empty_ok_result`, a single
module-level `PAGE_SIZE` with no stray hard-coded `50`s, the redundant
`filter_match_count is not None` conjunction removed, and validator rule 7
parses each `occurred_at` once. No regressions: full suite green.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | grep/read inspection of `src/schwab_mcp/transactions.py` against all 8 assessment claims | pass | Duplication counts: `reauth_required` ×1, `transient_failure` ×1, `partial_failure` ×1, `__cause__` ×1, `filter_match_count is not None` ×0, `PAGE_SIZE` defined once (`:610`) with no `!= 50`/`<= 50` literals; rule 7 parses `occurred_at` once (`:715`); both empty-ok sites use the helper (`:1172`, `:1278`) |
| New / updated tests | `uv run pytest tests/unit/test_transactions_query.py::TestPageSizeConsistency` | pass | 2 passed — pin test was Red (AttributeError) before the fix, Green after |
| Regression suite (transactions) | `uv run pytest tests/unit/test_transactions_{query,filter_query,pagination,models,events,live_response,mapping,split,symbol,underlying,validation}.py` | pass | 417 passed — covers ok/no_movements, transient, reauth, partial_failure (all-fail and some-fail), pagination, filtering |
| Regression suite (full commit gate) | `uv run pytest` | pass | **1789 passed, 0 skipped** in ~36s |
| Lint / type-check | — | not-run | No lint or type-check tooling is configured in the project (no ruff/flake8/mypy in `pyproject.toml`; CI gate is `uv sync && uv run pytest`) |

## Output Excerpts

```
$ uv run pytest tests/unit/test_transactions_query.py::TestPageSizeConsistency -q
..                                                                       [100%]
2 passed in 0.17s

$ uv run pytest tests/unit/test_transactions_*.py -q  (11 files)
417 passed in 1.00s

$ uv run pytest -q
1789 passed in 35.67s
```

Post-fix source inspection (grep counts over `src/schwab_mcp/transactions.py`):

```
outcome=TransactionOutcome.reauth_required   : 1  (in _reauth_result)
exc.__cause__                                : 1  (in _classify_connectivity_cause)
outcome=TransactionOutcome.transient_failure : 1  (in _transient_result)
outcome=TransactionOutcome.partial_failure   : 1  (single branch)
filter_match_count is not None               : 0
PAGE_SIZE = 50                               : 1  (module level, :610)
```

## Residual Risks

- The all-failed `partial_failure` path now computes its pagination values
  via `_paginate([])` instead of hardcoded literals; equivalence holds for
  any valid `offset >= 0` (offset validation rejects negatives) and is
  pinned by `test_all_accounts_fail_returns_partial_failure`, but it is the
  one semantic (vs purely structural) change in the fix.
- Validator rule 2's error message is now f-string-rendered from
  `PAGE_SIZE`; text is identical today ("returned==50") but would change
  with a future page-size bump — acceptable, arguably an improvement.
- The `_empty_ok_result` detail check uses truthiness (`if symbol`) rather
  than `symbol is not None`; equivalent because `validate_history_query`
  rejects empty symbols (`transactions.py:371`).

## Recommendation

Close the bug — verified. All eight DRY claims from the assessment are
resolved in source, the new pin tests pass (and demonstrably failed before
the fix), and the full commit-gate suite is green with zero skipped tests.
The fix is a pure refactor with no user-visible change; a `docs/CHANGELOG.md`
entry should ride along with the commit per the constitution.
