# Bug Fix: TD-002 — Outcome/detail taxonomy duplicated across modules (DRY)

- **Slug**: td-002-outcome-taxonomy-duplication
- **Fixed**: 2026-11-04
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Extracted the shared result taxonomy into `src/schwab_mcp/results.py`: one `ResultOutcome` enum (aliased by both feature modules, preserving both member casings), the three shared detail values as single-source constants, one `AccountFailed`/`AccountFailureDetail` pair, and a shared validator for outcome rules 4–5. Both feature modules now import from it and keep only their feature-specific rules; the false "Reused from the positions feature (003)" docstring claim is gone because the reuse is now real.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/results.py` | added | Shared taxonomy: `ResultOutcome` (lowercase members + uppercase aliases), `DETAIL_*` constants, `AccountFailureDetail` (+ aliases), `AccountFailed`, `validate_shared_outcome_rules()` |
| `src/schwab_mcp/positions.py` | modified | `OutcomeType = ResultOutcome` alias; `DetailType` takes the 3 shared values from constants; local `AccountFailureDetail`/`AccountFailed` deleted (names re-exported from results); `_validate_outcome_rules` delegates rules 4–5, keeps positions rules |
| `src/schwab_mcp/transactions.py` | modified | `TransactionOutcome = ResultOutcome` alias (docstring corrected); `TransactionDetail` takes the 3 shared values from constants; `TransactionAccountFailed = AccountFailed` alias (**tightened** `detail: str` → enum); `_validate_cross_rules` delegates rules 4–5 |
| `tests/unit/test_results_shared_taxonomy.py` | added test | 25 tests: identity, casing aliases, vocabulary preservation, validator contract messages, cross-module message parity, tightening |

Diff totals: `positions.py` 67 lines changed, `transactions.py` 76 — net **−76/+67** (duplication removed).

## Diff Highlights

Single shared outcome enum with casing aliases (alias members don't add values, so accepted vocabulary is unchanged):

```python
class ResultOutcome(str, Enum):
    ok = "ok"
    partial_failure = "partial_failure"
    transient_failure = "transient_failure"
    reauth_required = "reauth_required"
    # Uppercase aliases — preserve the positions-style member spellings
    OK = ok
    ...
```

Feature modules alias instead of re-defining:

```python
# positions.py / transactions.py
OutcomeType = ResultOutcome            # was a full re-definition
TransactionOutcome = ResultOutcome     # docstring had claimed (nonexistent) reuse
```

Shared validator replaces the word-for-word duplicated rules 4–5:

```python
# both _validate_outcome_rules and _validate_cross_rules now start with:
validate_shared_outcome_rules(self.outcome, self.retryable, self.accounts_failed)
```

## Tests Added or Updated

- `tests/unit/test_results_shared_taxonomy.py::TestOutcomeEnumIdentity` — `OutcomeType is TransactionOutcome is ResultOutcome`; both casings alias the same members; the four values preserved.
- `...::TestSharedDetailValues` — shared values come from `results.DETAIL_*`; each feature's vocabulary is exactly its own set (no widening).
- `...::TestAccountFailedShared` — model/enum identity across all three modules; `detail="nonsense"` rejected (tightening); plain strings coerce to members.
- `...::TestSharedOutcomeRules` — the four contract violations raise the exact contract messages; valid combinations pass.
- `...::TestMessageParity` — `PositionsResult` and `TransactionsResult` raise byte-identical messages for rules 4 and 5 (drift guard).
- **No existing test file was modified** (reporter's constraint).

## Local Verification

- `uv run pytest tests/unit/test_results_shared_taxonomy.py -q` → RED first (`No module named 'schwab_mcp.results'`), then **25 passed**.
- `uv run pytest -q` (full suite) → **1757 passed, 2 failed**.
- The 2 failures (`tests/unit/test_option_expirations.py::TestDteCeiling::*`) are **pre-existing on HEAD**: verified via `git stash -u` → same 2 failures without this change → `git stash pop`. They belong to other in-flight work (DTE ceiling docs/pyproject) and are untouched by this fix.
- No linter is configured in this project (`ruff` is not a dependency in `pyproject.toml`; absent from the venv). An initial "ruff clean" claim in this report was retracted during `/speckit.bug.test` — lint is not part of this project's quality gate (CI runs `uv run pytest` only).
- Manual: `positions.OutcomeType is results.ResultOutcome` → `True`; `str()` member rendering changes prefix (`OutcomeType.OK` → `ResultOutcome.ok`) — no production code stringifies members, and serialized values are unchanged.

## Deviations from Assessment

- **Shared detail values as constants, not a shared enum base.** The assessment left the detail-enum shape open. Python `Enum` classes cannot be subclassed to add members, and a single merged 10-value enum would widen each feature's accepted `detail` vocabulary (a behavior change). Implementation uses module-level `DETAIL_*` string constants in `results.py`, consumed by each feature enum — the three shared values have a single definition, and feature vocabularies are provably unchanged (pinned by test).
- **Rule-order nuance in `positions._validate_outcome_rules`.** The shared validator runs rules 5→4 before the positions-specific rules; previously rule 4 came *after* them. For inputs violating multiple rules simultaneously the first reported message can differ; the full suite (which includes positions validator message tests) is green, so no test pins the old combined-violation order.
- **`positions.AccountFailureDetail`/`AccountFailed` re-exported, not deleted.** The assessment said "delete duplicated definitions"; they were deleted and the names re-exported from `results` so any importer of `schwab_mcp.positions.AccountFailed` keeps working.
- **`docs/tools.md` not changed.** Verified during fix: it never references the taxonomy class names or module locations.

## Follow-ups

- Spec-level duplication (rules 4/5 restated in `specs/003-.../data-model.md` and `specs/006-.../data-model.md`) remains by design; consider a cross-reference note in both data-models in a future docs pass.
- CHANGELOG entry for the `TransactionAccountFailed.detail` tightening (`str` → closed vocabulary) should accompany the commit per the constitution's docs-in-same-commit rule.
- The two pre-existing `TestDteCeiling` failures belong to the in-flight DTE-ceiling work — track them there, not under this slug.