# Bug Fix: TD-016 — Dead parameters in helpers

- **Slug**: td-016
- **Fixed**: 2026-11-04
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Removed the dead `range_days` parameter from `_should_split` (and the caller-side
computation in `_bisect_range` that existed only to feed it), and replaced the inline
`3000` magic number with the module constant `UPSTREAM_TXN_CAP`. Behavior is unchanged;
the split trigger remains `len(movements) >= 3000`, now expressed via the named constant
and locked by a unit test.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/transactions.py` | modified | Added `UPSTREAM_TXN_CAP = 3000` constant after `ALL_TRANSACTION_TYPES`; `_should_split` signature reduced to `(movements)`; deleted the `range_days` computation in `_bisect_range`; docstrings updated to reference the cap without the inline literal |
| `tests/unit/test_transactions_split.py` | modified | `TestShouldSplit` rewritten to the one-argument signature, parameterized by `UPSTREAM_TXN_CAP`; added `test_cap_constant_value` |
| `docs/tech-debt.md` | modified | TD-016 `transactions.py` rows struck through with Fixed (td-016, v0.9.8) annotations, matching the TD-007/TD-008 style |
| `docs/CHANGELOG.md` | modified | Entry added under `[Unreleased] / Fixed` (Constitution: docs updated in-commit) |

## Diff Highlights

```python
# src/schwab_mcp/transactions.py
UPSTREAM_TXN_CAP = 3000
"""Upstream returns at most 3000 movements per query; hitting it triggers bisection."""

def _should_split(movements: list) -> bool:
    """Return True if the response has >= ``UPSTREAM_TXN_CAP`` items."""
    return len(movements) >= UPSTREAM_TXN_CAP

# _bisect_range — the dead computation is gone:
if not _should_split(movements):
    return movements
```

## Tests Added or Updated

- `tests/unit/test_transactions_split.py::TestShouldSplit::test_cap_constant_value` — pins
  `UPSTREAM_TXN_CAP == 3000` so the constant stays bound to the documented upstream limit.
- `TestShouldSplit::test_exactly_cap_triggers_split` / `test_cap_minus_one_does_not_trigger_split`
  / `test_cap_plus_one_triggers_split` — boundary tests parameterized by the constant
  (assessment asked for cap / cap−1; cap+1 retained from the previous suite).
- `TestShouldSplit::test_cap_with_single_day_range` — 1-day range at the cap still triggers
  (recursion stop belongs to the bisect function).
- All prior `range_days=...` calls removed; class docstring updated.

## Local Verification

- Commands run:
  - `uv run pytest tests/unit/test_transactions_split.py -x -q` → red first
    (`ImportError: cannot import name 'UPSTREAM_TXN_CAP'`), per TDD.
  - `uv run pytest tests/unit/test_transactions_split.py -q` → 33 passed after implementation.
  - `uv run pytest tests/unit -q` → 1531 passed.
  - `uv run pytest -q` (full suite, commit gate) → **1826 passed, 0 skipped, 0 failed**.
- Manual checks:
  - `grep -n "3000" src/schwab_mcp/transactions.py` → literal remains only in the constant
    definition and its docstring (plus an unrelated option-symbol example); docstring prose
    in `_bisect_range` and the tool description no longer hardcode the number.
  - `_should_split` has no other callers (verified during assessment; grep re-confirmed the
    only usage is the new `_bisect_range` call).

## Deviations from Assessment

- The assessment offered as optional "reference `UPSTREAM_TXN_CAP` in the `_bisect_range`
  docstring". Implemented as prose rewording ("hits the cap") instead of an interpolated
  f-string docstring — docstrings are static text here and the constant name is already
  documented on `_should_split`; simpler (KISS).
- Two of the assessment's test suggestions (`test_2999_long_range_does_not_trigger`,
  `test_exactly_3000_with_single_day_range`) were redundant with their sibling boundary
  tests once `range_days` disappeared (there is no range dimension anymore); merged into
  the constant-parameterized set rather than kept as literal duplicates.

## Follow-ups

- Commit with the full suite green, including `docs/CHANGELOG.md` and `docs/tech-debt.md`
  in the same commit (Constitution gate).
- None else — TD-016 is fully resolved; all four report rows are now fixed.
