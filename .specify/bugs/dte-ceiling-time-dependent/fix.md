# Bug Fix: TestDteCeiling clock-dependent fixtures (off-by-one DTE)

- **Slug**: dte-ceiling-time-dependent
- **Fixed**: 2026-11-04
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Anchored the three `TestDteCeiling` fixtures to the module's fixed
`TODAY = date(2026, 11, 3)` by passing `today=TODAY` to every
`chain_expiry_date(...)` call in the class, eliminating the wall-clock
dependence (`date.today()` inside the helper's default) that produced the
off-by-one DTE drift starting 2026-11-04. No assertions changed; no
production code touched.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `tests/unit/test_option_expirations.py` | modified | 3 fixtures in `TestDteCeiling` now pass `today=TODAY` (7 call sites: 253-255, 266-268, and the `test_default_ceiling_is_60…` fixture at 276) |

## Diff Highlights

```python
# before (clock-based base, pinned-clock assertions → drift)
(chain_expiry_date(7), 7, "C"),

# after (explicit anchor — matches the suite's dominant convention)
(chain_expiry_date(7, TODAY), 7, "C"),
```

## Tests Added or Updated

- `tests/unit/test_option_expirations.py::TestDteCeiling::test_dte_max_30_excludes_entries_beyond_the_ceiling` — pins the ceiling filter `[7, 30]` deterministically (was the failing test).
- `tests/unit/test_option_expirations.py::TestDteCeiling::test_dte_max_365_accepted_without_hard_upper_limit` — pins no-hard-cap `[7, 200, 360]` deterministically (was the failing test).
- `tests/unit/test_option_expirations.py::TestDteCeiling::test_default_ceiling_is_60_when_dte_max_is_none` — was passing by accident (`70 + drift > 60` holds forever); anchored too since it was the same latent pattern listed in the assessment (line 276).

TDD note: the "red" state pre-existed (the two failing tests); the fix turns
them green with zero assertion changes — no assertion was weakened.

## Local Verification

- Commands run: `uv run pytest tests/unit/test_option_expirations.py -q` → **34 passed** (was 32 passed / 2 failed).
- Commands run: `uv run pytest -q` (full suite) → **1774 passed, 0 failed**. The constitution's green-suite commit gate is restored (the two `TestDteCeiling` failures that blocked it are resolved).

## Deviations from Assessment

None. The preferred remediation was applied exactly as proposed (explicit
`today=` at the listed call sites, helper and production code untouched).
The only judgment call: the third fixture (`test_default_ceiling_is_60…`,
line 276) was also anchored — it was listed in the assessment's Suspected
Code Paths as part of the same class and could never *fail* (its drift only
increases the margin), but leaving it clock-based would have preserved the
inconsistent pattern within the very class being fixed.

## Follow-ups

- Optional: add a one-line note to the `chain_expiry_date` docstring
  (tests/unit/helpers.py:335) warning that the `today=None` default is
  clock-based and must only be used in self-consistent fixtures — the
  mistake class is cheap to reintroduce.
- CHANGELOG: test-only fix; per repo convention (v0.9.7 entry style) not
  changelog-worthy, but can be folded into the next release entry if
  desired.