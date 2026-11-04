# Bug Verification: TD-017 — Unused imports and members

- **Slug**: td-017
- **Tested**: 2026-11-04
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The confirmed dead imports/members are gone from `src/`, the enum-derived
`ALL_TRANSACTION_TYPES` holds, and the full suite is green (1828 passed,
0 skipped). No regressions appeared. The one assessment row not applied
(`Config.__getitem__`) was determined during the fix phase to be an invalid
claim — the method has real test callers — so it is not part of the symptom
and its retention is the correct end state.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | Static grep suite re-running the assessment's reproduction steps 1–6 (see Output Excerpts) | pass | All six confirmed dead items absent from source; `retry_once` absent from src **and** tests |
| Stale-row confirmation | `git show e3e5466^` + current greps | pass | `_os` duplication and dead `partial_failure` branch already resolved by v0.9.8 before this fix |
| New / updated tests | `uv run pytest tests/unit/test_transactions_models.py -k TestAllTransactionTypes -v` | pass (2/2) | Pins enum derivation + 15-value coverage |
| Regression suite | `uv run pytest` | pass | 1828 passed, 0 failed, 0 skipped, exit 0 (~35 s) |
| Lint / type-check | — | not-run | No lint/type tooling configured in `pyproject.toml` (only pytest/setuptools); ruff gate is a recorded follow-up |

## Output Excerpts

Post-fix static reproduction (numbered per `assessment.md` §Reproduction):

```
1. positions.py `import time`      → GONE (0 matches)
2. positions.py `List`             → GONE (0 matches; only the word "List"
                                     inside a field description string)
3. allowlist.py `Mapping`          → GONE (0 matches)
4. tokens.py `F`/`TypeVar`         → GONE (0 matches)
5. `retry_once` in src and tests   → GONE (0 matches, *.py)
6. renewal.py datetime import      → GONE (0 matches)
7. config.py `__getitem__`         → PRESENT (line 36 — expected; assessment
                                     claim invalid, see fix.md Deviations §1)
8. transactions.py:241             → ALL_TRANSACTION_TYPES = ",".join(
                                       t.value for t in ProviderTransactionType)
```

New tests:

```
tests/unit/test_transactions_models.py::TestAllTransactionTypes::test_derived_from_enum_values PASSED
tests/unit/test_transactions_models.py::TestAllTransactionTypes::test_covers_all_fifteen_upstream_types PASSED
2 passed, 104 deselected in 0.08s
```

Full suite:

```
============================ 1828 passed in 35.26s =============================
exit=0
```

## Residual Risks

- No lint gate exists, so future unused imports will not be caught
  mechanically (follow-up recorded in fix.md).
- `Config.__getitem__` removal, if ever revisited, is a contract change
  (15 bracket-access assertions in `tests/unit/test_config.py`), not dead-code
  cleanup — do not fold it into another cleanup pass.
- The `__pycache__` directories still contain stale bytecode mentioning the
  removed symbols; harmless (rebuilt on next run), but they can produce
  false grep hits.

## Recommendation

Close the bug — the six confirmed dead items are verified removed, the
two stale rows were already resolved by the v0.9.8 refactor, and the ninth
row was correctly re-classified as invalid (real callers exist). The suite
is green with the new derivation tests in place. Recommend prioritizing the
optional ruff `F401,F811,F841` CI gate so this class of debt is caught
mechanically going forward.