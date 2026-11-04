# Bug Verification: TestDteCeiling clock-dependent fixtures (off-by-one DTE)

- **Slug**: dte-ceiling-time-dependent
- **Tested**: 2026-11-04
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The symptom no longer reproduces: the same command that failed earlier today
(2026-11-04, drift +1) now passes with the original expected DTE lists, and
the fixtures are provably clock-independent (every `TestDteCeiling` call
site is anchored to the fixed `TODAY`). Full suite is green — 1774 passed,
0 failed — restoring the constitution's commit gate.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | `uv run pytest tests/unit/test_option_expirations.py -q` (same command that failed on this date pre-fix) | pass | 34 passed, 0 failed — the exact reproduction from the assessment (2 `TestDteCeiling` failures with `assert [8, 201, 361] == [7, 200, 360]`) no longer occurs on the same clock date. |
| Anchor coverage | `grep -n "chain_expiry_date(" tests/unit/test_option_expirations.py` | pass | All 7 call sites pass `today=TODAY` (lines 253-255, 266-268, 277); zero default-using sites remain in the file. |
| Determinism proof | python check: `(date.fromisoformat(chain_expiry_date(n, TODAY)) - TODAY).days == n` for n ∈ {7, 30, 70, 200, 360} | pass | All five anchors yield `dte == days_ahead` — the value no longer depends on the wall clock, so the drift mechanism from the assessment is structurally removed. |
| Updated tests | `uv run pytest tests/unit/test_option_expirations.py::TestDteCeiling -q` (within the file run) | pass | All three `TestDteCeiling` tests green with unchanged assertions (`[7, 30]`, `[7, 200, 360]`, `no_expirations_in_range`). |
| Regression suite (full) | `uv run pytest -q` | pass | 1774 passed, 0 failed — the two `TestDteCeiling` failures that blocked the commit gate are resolved; no regressions. |
| Lint / type-check | — | not-run | No lint or type-check tooling configured in `pyproject.toml` (pytest/setuptools only). |

## Output Excerpts

```
$ uv run pytest tests/unit/test_option_expirations.py -q
..................................                                       [100%]
34 passed in 0.38s

$ uv run python -c "… dte == days_ahead for all five anchors …"
anchored fixtures: dte == days_ahead for all five anchors (deterministic, clock-independent)

$ uv run pytest -q
..............................................                           [100%]
1774 passed in 34.52s
```

Pre-fix baseline for comparison (earlier today, same date):
`2 failed, 32 passed` with `assert [8, 201, 361] == [7, 200, 360]`.

## Residual Risks

- The `chain_expiry_date` helper still defaults `today=None` → `date.today()`
  for other call sites. They are self-consistent (both fixture and assertion
  use the real clock) and therefore deterministic, but any future test that
  mixes the default helper with a pinned `today` would reintroduce this bug
  class. A docstring warning on the helper remains an optional follow-up.
- Long-run confidence relies on the arithmetic proof plus the anchor
  coverage grep rather than on an actual run on a *different* calendar date;
  however, the mechanism (expiry − pinned TODAY, both sides fixed) is
  date-independent by construction.

## Recommendation

Close the bug — verified: the failing reproduction is gone on the same date
it failed, the anchors are provably clock-independent, and the full suite
(git commit gate) is green. The one-file test change is ready to commit
(e.g. `🐛 fix(tests): anchor TestDteCeiling fixtures to fixed TODAY`), with
the `.specify/bugs/dte-ceiling-time-dependent/` records included.