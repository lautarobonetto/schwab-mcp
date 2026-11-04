# Bug Verification: TD-002 — Outcome/detail taxonomy duplicated across modules (DRY)

- **Slug**: td-002-outcome-taxonomy-duplication
- **Tested**: 2026-11-04
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The bug does not reproduce post-fix: the outcome taxonomy, `AccountFailed` model, and outcome rules 4–5 now exist as single shared definitions in `src/schwab_mcp/results.py`, with both feature modules consuming them. All new tests pass and all 294 tests of the affected modules pass unchanged; the full suite shows only 2 pre-existing failures proven unrelated to this fix (present on HEAD before the change).

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) — claim 1 | `grep -c "class TransactionOutcome\|class OutcomeType"` on both modules | pass | 0 occurrences in each — no re-definitions remain; runtime check `p.OutcomeType is t.TransactionOutcome is r.ResultOutcome` → `True` |
| Reproduction (post-fix) — claim 2 | `grep` the four duplicated rule messages across `src/` | pass | 4 occurrences, all in `results.py` only — the word-for-word duplication is gone |
| Reproduction (post-fix) — claim 3 | `grep "Reused from the positions feature"` | pass | False docstring gone (superseded by real aliasing) |
| New tests | `uv run pytest tests/unit/test_results_shared_taxonomy.py -q` | pass | 25 passed — identity, casing aliases, vocabulary preservation, contract messages, cross-module message parity, tightening |
| Regression — affected modules | `uv run pytest tests/unit/test_transactions_*.py tests/unit/test_positions*.py -q` | pass | 294 passed, zero existing test files modified (reporter's constraint) |
| Regression — full suite | `uv run pytest -q` | pass | 1757 passed, 2 failed — both failures pre-existing on HEAD (verified via `git stash` during `/speckit.bug.fix`); unrelated option-expiration DTE-ceiling work |
| Lint / type-check | `uv run ruff check …` | not-run | No linter is configured in this project (`ruff` absent from `pyproject.toml` and the venv; pyenv shim fails with 127). CI's quality gate is `uv run pytest` only. Correction: `fix.md`'s initial "ruff clean" line was retracted during this verification. |

## Output Excerpts

```
== claim 1: outcome enum re-definition ==
src/schwab_mcp/transactions.py:0
src/schwab_mcp/positions.py:0
== claim 2: duplicated error messages ==
   4 src/schwab_mcp/results.py
== claim 3: false docstring ==
gone

identity: single shared definitions confirmed

tests/unit/test_results_shared_taxonomy.py  25 passed in 0.07s
affected modules                            294 passed in 0.56s
full suite                                  2 failed, 1757 passed in 34.96s
  (both failures pre-existing on HEAD: TestDteCeiling × 2)
```

## Residual Risks

- **Pre-existing failures (out of scope)**: `tests/unit/test_option_expirations.py::TestDteCeiling` × 2 fail on HEAD independent of this fix — must be resolved by the in-flight DTE-ceiling work before the next commit passes the full-suite gate.
- **`TransactionAccountFailed.detail` tightening**: constructing the model with a detail string outside `{provider_error, transient}` now raises `ValidationError` (previously any `str` was accepted). No production code or test relied on that; external consumers would be affected — cover in the CHANGELOG entry.
- **Rule-order nuance**: in `positions._validate_outcome_rules`, shared rule 4 now runs before the positions-specific rules; a multi-rule-violating input can report a different first error than before. Pinned by the message-parity tests; single-violation behavior unchanged.
- **Lint not exercised**: no lint/type-check tooling is configured for this project, so that dimension is unverifiable by design, not skipped for convenience.

## Recommendation

Close the bug — verified. The assessment's three duplication claims (re-defined outcome enum, duplicated word-for-word validator rules, false reuse docstring) all fail to reproduce against the fixed tree; the structural fix is pinned by 25 new tests plus an unmodified 294-test regression suite for both feature modules. Commit gate note: the 2 pre-existing `TestDteCeiling` failures must be resolved separately before the constitution's "full suite green" commit requirement can be met.