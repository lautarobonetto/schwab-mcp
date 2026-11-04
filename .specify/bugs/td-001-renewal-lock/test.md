# Bug Verification: Renewal lock — single blocking critical section replaces the acquire/release dance (TD-001)

- **Slug**: td-001-renewal-lock
- **Tested**: 2026-11-04
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The original symptom no longer reproduces: an independent harness exercising the
assessment's exact reproduction scenario (two threads racing into `renew()` with
a renewal that leaves the store expired) runs clean — no exception escapes
`renew()` and the renewals are strictly serialized. All new regression tests,
the full renewal test surface, and the full suite pass; the only failures are
two pre-existing, unrelated date-sensitive tests confirmed failing at HEAD
before the fix.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | `uv run python tmp/td001_repro_post_fix.py` (independent harness, not the unit test; run 4×) | pass | Assessment's reproduction steps exercised directly: barrier-synchronized two-thread race, holder's `update_tokens()` does NOT refresh the store → `errors: []`, 2 × `renewed`, `call_count == 2`, `max in-flight == 1` |
| Reproduction (pre-fix evidence) | Red-phase run recorded in `./fix.md` (test-first, against unfixed code) | pass (defect observed) | Same scenario failed pre-fix with the exact symptom: `RuntimeError('release unlocked lock')` escaping `renew()` |
| New / updated tests | `uv run pytest tests/unit/test_renewal.py::TestRenew::test_waiter_renews_serialized_when_first_renewal_leaves_store_expired tests/unit/test_renewal.py::TestRenew::test_second_sequential_renew_sees_refreshed_store tests/unit/test_renewal.py::TestRenew::test_acquire_release_store_lock_helpers_removed` | pass | 3 passed in 0.24 s |
| Regression suite (renewal + touched surfaces) | `uv run pytest tests/unit/test_renewal.py tests/integration/test_renewal_flow.py tests/integration/test_renew.py tests/performance/test_renewal_budget.py tests/unit/test_cli_version.py tests/unit/test_client_factory.py tests/unit/test_server_tool.py` | pass | 131 passed in 4.43 s — includes pre-existing `test_single_flight_sharing` (still exactly one `update_tokens()` call) |
| Full suite (commit gate) | `uv run pytest -q` | pass (with pre-existing failures) | 1732 passed, 2 failed, 0 skipped — the 2 failures are `tests/unit/test_option_expirations.py::TestDteCeiling`, confirmed pre-existing at HEAD via `git stash` during `/speckit.bug.fix` (unrelated to this fix) |
| Stale-reference sweep | `grep -rn "_acquire_store_lock\|_release_store_lock" src/ tests/ docs/` | pass | Only expected hits: the negative-guard test itself and docs prose describing the deletion; no code references remain in `src/` |
| Lint / type-check | — | not-run | No linter or type-checker is configured in the project (`pyproject.toml`, CI workflow) |

## Output Excerpts

Reproduction harness (post-fix, 4/4 runs identical):

```
results: ['renewed', 'renewed']
errors: []
update_tokens call_count: 2
max in-flight update_tokens overlap: 1
REPRODUCTION POST-FIX: PASS
```

Red-phase evidence (from `./fix.md`, pre-fix):

```
E       AssertionError: No exception may escape renew(); got [RuntimeError('release unlocked lock')]
```

Full suite:

```
2 failed, 1732 passed in 34.51s   (both failures pre-existing at HEAD, TestDteCeiling)
```

## Residual Risks

- **No production exercise**: the defect is latent by nature — the only
  production caller (`schwab-mcp renew`) is single-threaded and guarded by the
  cross-process `AuthLock`, so the race can only be exercised in
  multithreaded/test usage. Validation is therefore harness- and suite-based,
  not live-server-based; the renewal path's network behavior itself is
  unchanged (same `_do_renew`, same outcomes, same exit codes).
- **Behavior change under contention** (intentional, from the assessment): a
  waiter that still finds an expired store now performs its own serialized
  renewal instead of renewing unlocked — `update_tokens()` can be called twice
  sequentially where the old code called it concurrently (and crashed). Pinned
  by the regression test.
- **Blocking wait**: the lock is now held across `_do_renew`'s retries
  (bounded: initial + 2 retries with 0.5 s sleeps); other threads block for
  that duration. Bounded and intentional per the assessment.
- **Pre-existing unrelated failures**: the two `TestDteCeiling` failures will
  block the constitution's "full suite green" commit gate for any change until
  triaged separately.

## Recommendation

Close the bug — verified. The assessment's reproduction scenario was exercised
directly (independent harness, 4× clean) against the fixed code, the red-phase
run had reproduced the exact `RuntimeError` pre-fix, and no regressions were
introduced (1732 passing; the only failures pre-date the fix). Before
committing, triage the two pre-existing `TestDteCeiling` failures separately —
they are unrelated to TD-001 but will fail the commit gate as-is.