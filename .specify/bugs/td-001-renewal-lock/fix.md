# Bug Fix: Renewal lock — single blocking critical section replaces the acquire/release dance (TD-001)

- **Slug**: td-001-renewal-lock
- **Fixed**: 2026-11-04
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Replaced the broken non-blocking acquire / block-release / unconditional-release
coordination in `renewal.py` with a single blocking critical section
(`with _store_lock(store_path):`) that re-checks the store margin inside the
lock and returns `not_needed` when another thread already renewed.
`_acquire_store_lock` and `_release_store_lock` were deleted, so a release can
never be paired with a foreign acquire — the FR-005 single-flight invariant is
now structural.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/renewal.py` | modified | Added `_store_lock` context manager (blocking acquire over the existing `_renew_locks` registry); rewrote `renew()` coordination — margin re-check inside the lock, renewal under the lock across retries; deleted `_acquire_store_lock` / `_release_store_lock`; extracted `_not_needed_outcome` helper (DRY: the `not_needed` outcome was constructed twice); added `import contextlib` |
| `tests/unit/test_renewal.py` | added tests | 3 regression/guard tests (see below), appended to `TestRenew` |
| `docs/tech-debt.md` | modified | TD-001 summary row → `Fixed (v0.9.8, 2026-11-04)`; resolution note added to the TD-001 section |
| `docs/CHANGELOG.md` | modified | New `## [0.9.8] - 2026-11-04` Fixed entry describing the bug, the fix, and the contention behavior change |
| `pyproject.toml` | modified | Version bump `0.9.7` → `0.9.8` (repo convention: each fix commit bumps the version) |

## Diff Highlights

Before (the defect — `renewal.py:208-225, 270-287`):

```python
acquired = lock.acquire(blocking=False)
if not acquired:
    lock.acquire()
    lock.release()          # waiter owns nothing afterwards
return acquired
...
try:
    return _do_renew(client, store_path, trigger_detail=trigger_detail)
finally:
    _release_store_lock(store_path)   # releases a lock this thread may not own
```

After:

```python
@contextlib.contextmanager
def _store_lock(store_path):
    if store_path is None:
        yield
        return
    with _renew_locks_lock:
        lock = _renew_locks.setdefault(store_path, threading.Lock())
    with lock:
        yield

# in renew():
with _store_lock(store_path):
    lifetime = read_store_lifetime(store_path)
    if lifetime is not None and lifetime.access_remaining_seconds > ACCESS_MARGIN:
        return _not_needed_outcome(lifetime)   # another thread already renewed
    return _do_renew(client, store_path, trigger_detail=trigger_detail)
```

The outside-the-lock margin short-circuit (step 1) is kept as an advisory fast
path; the authoritative re-check runs inside the lock. `store_path is None`
goes straight to `_do_renew` (unchanged behavior: no coordination possible).

## Tests Added or Updated

TDD followed: Red → Green. All three tests were written and run against the
unfixed code first.

- `tests/unit/test_renewal.py::TestRenew::test_waiter_renews_serialized_when_first_renewal_leaves_store_expired` — **the regression**: two threads race, the first holder's `update_tokens()` does NOT refresh the store. RED reproduced the exact defect (`RuntimeError('release unlocked lock')` escaping `renew()`). GREEN asserts: no exception escapes, both threads return `renewed`, both renewals happen serialized (`max in-flight == 1`, tracked inside the side effect), `update_tokens().call_count == 2`.
- `tests/unit/test_renewal.py::TestRenew::test_second_sequential_renew_sees_refreshed_store` — deterministic (no threads) companion: first `renew()` refreshes the store, second returns `not_needed` / `still_valid` with `call_count == 1`. (Passed pre-fix as well — behavior lock-in, per the assessment.)
- `tests/unit/test_renewal.py::TestRenew::test_acquire_release_store_lock_helpers_removed` — negative guard: `_acquire_store_lock` / `_release_store_lock` must stay deleted and `_store_lock` must exist (RED pre-fix, GREEN post-fix).
- `test_single_flight_sharing` (pre-existing) — still green; with the re-check inside the lock it observes exactly one `update_tokens()` call as before.

## Local Verification

- Red phase: `uv run pytest tests/unit/test_renewal.py -k "waiter_renews or second_sequential or helpers_removed"` → 1 failed with `RuntimeError('release unlocked lock')` (exact defect reproduced), 1 failed guard, 1 passed.
- Green phase: `uv run pytest tests/unit/test_renewal.py tests/integration/test_renewal_flow.py tests/integration/test_renew.py tests/performance/test_renewal_budget.py` → **58 passed**.
- Flakiness check: the two threaded tests run 10× consecutively → 10× `2 passed`.
- Full suite (commit gate): `uv run pytest -q` → **1732 passed, 2 failed** — both failures are in `tests/unit/test_option_expirations.py::TestDteCeiling` and were confirmed pre-existing at HEAD (`git stash` → same 2 failures; they are date-sensitive DTE-ceiling tests, unrelated to this fix; 0 skipped).

## Deviations from Assessment

- `pyproject.toml` version bump (0.9.7 → 0.9.8): not listed under "Files likely to change", added because every prior fix commit in this repo bumps the version together with its CHANGELOG entry (e.g. v0.9.6, v0.9.7).
- Extracted the small `_not_needed_outcome(lifetime)` helper: the assessment's sketch duplicated the `not_needed` outcome construction at the fast path and inside the lock; the constitution's DRY rule favors the helper. Behavior identical.
- No other deviations; the fix follows the assessment's preferred remediation as written.

## Follow-ups

- The 2 pre-existing `TestDteCeiling` failures at HEAD are date-sensitive and unrelated — worth their own triage (they will block the commit gate for any change today).
- Optional (noted in assessment, intentionally not done): `_renew_locks` grows one `threading.Lock` per store path for the process lifetime — fine for the CLI's single store, but if this ever serves many paths, consider an LRU or weak-value registry; could get its own tech-debt row.
- Commit (per constitution): full suite green required — resolve or triage the pre-existing `TestDteCeiling` failures before committing, or record a justification if they are environmental.