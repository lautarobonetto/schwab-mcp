# Bug Verification: Undocumented settlement_type values in get_option_expiration_chain (A/B)

- **Slug**: settlement-type-a
- **Tested**: 2026-11-03
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The documentation-gap symptom no longer reproduces: a live `$SPX`
expiration chain returns `settlement_type` values `P`/`B`/`A` and every
observed letter is now covered by the documented (non-exhaustive)
enumeration in `docs/tools.md` and the spec-012 artifacts. The new `B`
pass-through test and the full unit regression suite are green; no
regressions found. No production code was touched by the fix, so the
pass-through behavior is unchanged by construction.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | Live `get_option_expiration_chain` on `$SPX`, `dte_max=365`; group by `settlement_type` and compare against the documented set | pass | `outcome: ok`, 47 expirations: `P`×35, `B`×5, `A`×7 — identical to the assessment's pre-fix capture; all observed letters ∈ documented {C, P, A, B} |
| New / updated tests | `uv run pytest "tests/unit/test_option_expirations.py::TestCuratedFieldMapping::test_settlement_type_b_passes_through_unmodified" -v` | pass | 1 passed — `B` passes through verbatim |
| Module suite | `uv run pytest tests/unit/test_option_expirations.py -q` | pass | 34 passed |
| Regression suite (unit scope) | `uv run pytest tests/unit -q` | pass | 1436 passed, 0 skipped (commit-gate unit scope) |
| Docs consistency sweep | grep for stale value enumerations (`PM/AM`, `` `P`/`A` ``) across docs/ and specs/ | pass | Only historical mentions remain (assessment.md, fix.md, CHANGELOG narrative); live docs/specs all list C/P/A/B |
| Lint / type-check | — | not-run | No lint/type tooling (ruff/mypy) configured in `pyproject.toml` |
| Integration suite | — | skipped | Network-dependent (live Schwab API); read-only live verification was instead performed via the MCP tool above |

## Output Excerpts

Live reproduction, post-fix:

```json
{"outcome": "ok", "count": 47,
 "observed": {"P": 35, "B": 5, "A": 7},
 "allObservedCoveredByDocs": true}
```

Test runs:

```
tests/unit/test_option_expirations.py::TestCuratedFieldMapping::
test_settlement_type_b_passes_through_unmodified PASSED [100%]
1436 passed in 27.07s   (tests/unit -q)
```

## Residual Risks

- The exact provider semantics of `B` remain unverified against Schwab
  documentation (assessment open question); the docs deliberately describe
  `A`/`B` as "AM (open) index settlement, per observed patterns" without
  asserting provider-documented meaning. If Schwab ever publishes the enum,
  revisit the wording.
- The B→A split at the 2027-03/2027-04 monthly boundary may drift over time;
  the non-exhaustive enumeration is date-agnostic, so no doc churn is expected,
  but a future live check could observe a new letter — which the contract now
  explicitly permits.
- Verification exercised the read-only live tool path, not the integration test
  suite (network-dependent, skipped per guardrail).

## Recommendation

Close the bug — verified: the documented contract now covers every observed
provider value, the live reproduction confirms coverage, and the new unit test
plus the full unit suite are green. Commit the docs + spec + test + changelog
changes together per the constitution (full suite green, 0 skipped).