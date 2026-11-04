# Bug Verification: TD-007 — `positions.py`: transform layer remaps itself (DRY/KISS)

- **Slug**: td-007-positions-transform-dry
- **Tested**: 2026-11-04
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The bug no longer reproduces: every one of the six structural claims from
the assessment was re-inspected statically and is resolved in the working
tree, the tests added by the fix all pass, and the full suite (the
project's commit gate) is green with 0 skipped. No regressions found.

Note on method: the assessment's reproduction steps are **static code
observation** (no runtime defect exists — output was already correct), so
"post-fix reproduction" here means re-exercising those static steps
against the fixed tree, which was done directly (evidence below), not
merely inferred from tests.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) — static, per assessment steps 2–6 | `grep` inspection of `src/schwab_mcp/positions.py` for each claim | pass | see evidence below; all six claims resolved |
| New / updated tests (Red-phase originals) | `uv run pytest tests/unit/test_positions.py::TestUnrealizedPlOptionMultiplier tests/unit/test_positions.py::TestMapProviderPositionsOutcomeParams tests/unit/test_server_tool.py::TestPartialFailure -q` | pass (15) | includes the rewritten transform test and the 6 orchestration partial-failure tests |
| Regression suite (changed modules) | `uv run pytest tests/unit/test_positions.py tests/unit/test_server_tool.py tests/unit/test_results_shared_taxonomy.py -q` | pass (146) | the three suites named by the assessment |
| Full suite (commit gate) | `uv run pytest -q` | pass (1810) | 0 skipped, per constitution gate |
| Lint / type-check | — | not-run | no linter or type-checker configured in `pyproject.toml`; pytest is the project's only configured gate |

## Output Excerpts

Static evidence, claim by claim (assessment steps 2–6):

1. **Transform-layer `unrealizedPL` (was 654–659)** — no `unrealizedPL`
   key is written anywhere; the only occurrences are the explanatory
   comment/docstring added by the fix.
2. **Consolidation-map `unrealized_pl` (was 365–367)** — `_compute_unrealized_pl`
   has exactly **one** call site: line 413, `PositionEntry` construction.
3. **Inline extended loop (was 682–685)** — replaced by
   `entry.update(_collect_extended(pos))` (line 709); helper used in both
   layers now.
4. **Timestamp override (was 560–563)** — no `pos_result.retrieved_at =`
   or `entry.price_timestamp =` assignments remain anywhere in the file.
5. **Raw outcome/detail strings + post-hoc mutation (was 379–385,
   541–544, 547–554)** — zero `outcome="…"`/`detail="…"` literals in any
   `PositionsResult` construction; the remaining literals (lines 486,
   499, 512, 590, 592) are **audit-event fields only**, explicitly left
   as-is in fix.md follow-ups. No `pos_result.*` mutations remain.
6. **Dead `retrieved_at` param (was 579)** — signature is now
   `_detect_account_failures(provider_payload)`; call site updated.

Test runs:

```
tests/unit/test_positions.py::TestUnrealizedPlOptionMultiplier … + OutcomeParams + TestPartialFailure
15 passed in 0.14s

uv run pytest tests/unit/test_positions.py tests/unit/test_server_tool.py tests/unit/test_results_shared_taxonomy.py -q
146 passed in 0.62s

uv run pytest -q
1810 passed in 36.14s
```

## Residual Risks

- **No lint/type-check available**: the project configures no ruff/mypy,
  so no static-analysis backstop beyond the test suite ran. Not-run by
  configuration, not by omission.
- **Behavior-neutrality rests on test equivalence**: the fix is a
  refactor, and correctness is established by the 1810-test suite plus
  the targeted new tests (including the pinned −6616.29 option-multiplier
  value and the enum-membership assertions). No production/staging run
  was performed — none is warranted, as there was never a runtime defect.
- **Audit-event outcome fields** still use literal strings (`"ok"`,
  `"partial_failure"`, …). Values are unchanged and consumers are safe;
  recorded as a follow-up in fix.md, out of TD-007's declared scope.

## Recommendation

Close the bug — verified. All six assessed claims are statically
resolved in the working tree, the fix's tests pass, and the full commit
gate is green (1810 passed, 0 skipped). The refactor is behavior-neutral
by test evidence. Ready for commit with the affected documentation, per
the constitution gate.