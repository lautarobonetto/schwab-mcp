# Bug Assessment: Renewal lock — latent double-renewal / RuntimeError and needless complexity (TD-001)

- **Slug**: td-001-renewal-lock
- **Created**: 2026-11-04
- **Source**: pasted text (mirrors the open entry `TD-001` in `docs/tech-debt.md`)
- **Verdict**: valid
- **Severity**: medium

## Report (verbatim or summarized)

Pasted report (TD-001 from `docs/tech-debt.md:42-72`):

> `_acquire_store_lock` tries a non-blocking acquire; on failure it blocks, releases,
> and returns `False`. The caller in `renew()` then:
>
> 1. Re-reads the store; if still expired it falls into `try: _do_renew(...)`
>    **without holding the lock**, and the `finally: _release_store_lock(store_path)`
>    calls `lock.release()` on a lock this thread does not own →
>    `RuntimeError: release unlocked lock`, and two threads can renew in parallel.
> 2. If the re-read finds the token valid, it returns early and the lock is simply
>    left held (never released by this path's semantics).
>
> Refactor: replace the acquire/release dance with a blocking
> `with _store_lock(store_path):` context, re-check the margin inside the lock, and
> return `not_needed` if another thread already renewed. Delete
> `_acquire_store_lock`/`_release_store_lock`.
>
> TDD: regression test where two sequential `renew()` calls race (first holder
> renews, second sees the refreshed store) and asserts no `RuntimeError` and no
> double renewal.

No URL was supplied; nothing was fetched.

## Symptom

When two threads call `renew()` concurrently for the same store and the first
thread's renewal does **not** leave the store fresh (renewal fails, or the wait
outlives the holder), the second thread falls through into `_do_renew()` while
holding no lock. Its `finally` then calls `lock.release()` on a lock it does not
own — raising `RuntimeError: release unlocked lock` when the lock is free at that
moment, or silently releasing a lock held by *another* thread (permitted for
`threading.Lock`) — and in both cases two threads can renew in parallel,
violating the FR-005 single-flight guarantee. Expected behavior: exactly one
renewal in flight per store, no exception escaping `renew()`.

## Reproduction

1. Seed a token store that is inside the renewal margin (e.g.
   `expires_in=1800, access_age=1790`, as `tests/unit/test_renewal.py::test_single_flight_sharing`
   does).
2. Thread A enters `renew()` and takes the per-path lock; its `update_tokens()`
   fails to refresh the store (store still expired afterwards).
3. Thread B enters `renew()`: `_acquire_store_lock` fails non-blocking, blocks on
   `lock.acquire()`, immediately `release()`s, and returns `False`.
4. B re-reads the store — still expired — and proceeds to `_do_renew()` **without
   the lock** (parallel with any other thread that did the same).
5. In B's `finally`, `_release_store_lock` releases an unlocked lock →
   `RuntimeError: release unlocked lock` propagates out of `renew()`; if instead
   another thread took the lock in the meantime, B's release silently breaks that
   thread's mutual exclusion.

[NEEDS CLARIFICATION: no production reproduction — the bug is latent. The only
production caller (`cli.py:327`, `schwab-mcp renew`) is single-threaded and runs
under the cross-process `AuthLock` (exit 6 when busy), so the race currently
manifests in multithreaded/test usage rather than in the shipped CLI flow.]

## Suspected Code Paths

- `src/schwab_mcp/renewal.py:208-225` — `_acquire_store_lock`: the
  "block-then-release-then-return-False" dance destroys the evidence that the
  waiter ever held the lock and opens a race window between release and the
  caller's re-read.
- `src/schwab_mcp/renewal.py:228-235` — `_release_store_lock`: unconditional
  `lock.release()` on a `threading.Lock` this thread may not own (raises
  `RuntimeError` when unlocked; silently releases a foreign holder otherwise).
- `src/schwab_mcp/renewal.py:270-287` — `renew()`: coordination block. On
  `acquired=False` it re-reads the store and, if still expired, renews unlocked;
  the early-return path (valid store) is safe but relies on the same broken
  dance.
- `src/schwab_mcp/renewal.py:118-119` — `_renew_locks` / `_renew_locks_lock`: the
  lock registry itself stays, but its non-blocking acquire semantics are the
  root of the complexity.
- `tests/unit/test_renewal.py:847-891` — `test_single_flight_sharing`: covers
  only the happy path (waiter finds a fresh store); does not cover the
  store-still-expired path where the defect fires.

## Root Cause Hypothesis

**Confidence: high.** `_acquire_store_lock` conflates "I own the lock until I
release it" with "someone else was renewing; go re-check". By blocking *and*
releasing inside the acquire helper, it returns `False` to a thread that now owns
nothing, while `renew()`'s `finally` unconditionally releases — a mismatch that
raises `RuntimeError: release unlocked lock` (lock free at release time) or
releases a lock held by a third thread (allowed for `threading.Lock`, which is
not owner-checked), both leaving the critical section unprotected so two threads
can call `update_tokens()` concurrently. One nuance where the report overstates:
the early-return path (`acquired == False`, re-read finds a valid token) does
**not** leak the lock — the helper already released it after blocking — so claim
(2) in the report is inaccurate in detail, though it points at the same broken
semantics. The margin re-read also happens *outside* any lock, so it can observe
a store mid-write by another thread.

## Proposed Remediation

**Preferred**: Collapse the coordination in `renew()` into a single blocking
critical section, per the report's refactor:

```python
if store_path is None:
    return _do_renew(client, store_path, trigger_detail=trigger_detail)

# fast-path margin check outside the lock (unchanged, step 1)
...
with _store_lock(store_path):          # blocking acquire; context manager owns release
    lifetime = read_store_lifetime(store_path)
    if lifetime is not None and lifetime.access_remaining_seconds > ACCESS_MARGIN:
        return RenewalOutcome(outcome="not_needed", ..., detail="still_valid")
    return _do_renew(client, store_path, trigger_detail=trigger_detail)
```

Introduce a small `_store_lock(store_path)` context manager (or reuse the
existing `_renew_locks` registry via `contextlib.contextmanager`) that yields the
per-path `threading.Lock` under `with lock:`; the context manager guarantees the
release is paired with the acquire and cannot double-release. Keep the existing
outside-the-lock margin short-circuit as a cheap fast path (it is advisory only;
the authoritative check moves inside the lock). Delete `_acquire_store_lock` and
`_release_store_lock`. `_do_renew`'s retries (with `time.sleep(0.5)`) stay inside
the held lock — holding it across retries is correct for single-flight. The
`_renew_locks` dict growth per store path is a pre-existing trait; leave it
untouched (KISS) or note it in `docs/tech-debt.md` separately.

This also removes the reported needless complexity: one blocking critical
section replaces the non-blocking try + block/release/False + unlocked retry +
unconditional release, and the FR-005 single-flight invariant becomes structural
rather than convention.

**Alternatives**:
- Keep the two-phase design but track ownership (e.g. `threading.RLock` +
  boolean return, or return the acquired `Lock` object and release only if
  owned). Trade-off: preserves the current control flow but keeps the double
  bookkeeping the report flags as needless; more code for the same guarantee.
- Drop the in-process lock entirely and rely on schwabdev's SQLite-level
  coordination. Trade-off: would not serialize the `update_tokens()` call itself
  and would couple correctness to a third-party library's internals; rejected.

**Files likely to change**:
- `src/schwab_mcp/renewal.py` — replace coordination block in `renew()`; add
  `_store_lock` context manager; delete `_acquire_store_lock` / `_release_store_lock`.
- `tests/unit/test_renewal.py` — add regression tests (see below).
- `docs/tech-debt.md` — mark TD-001 resolved (constitution: docs updated in the
  same commit).
- `docs/CHANGELOG.md` — bugfix entry.

**Tests to add or update**:
- Regression (the reported TDD ask): two threads race on `renew()` where the
  first holder's `update_tokens()` does **not** refresh the store — assert no
  exception escapes (in particular no `RuntimeError: release unlocked lock`) and
  that `update_tokens()` calls never overlap (track in-flight count, assert
  max concurrency == 1).
- Companion deterministic test: sequential `renew()` calls where the first
  renews and refreshes the store → second returns `not_needed` / `still_valid`
  with no `RuntimeError` (locks the "second sees refreshed store" behavior
  without threading flakiness).
- Keep `test_single_flight_sharing` green: with the re-check moved inside the
  lock it should still observe exactly one `update_tokens()` call.
- Negative guard: assert `_acquire_store_lock` / `_release_store_lock` are gone
  (import check) so the dance cannot be reintroduced.

## Risks & Considerations

- **Behavior change under contention**: after the fix, a waiter whose store is
  still expired performs its own (serialized) renewal instead of renewing
  unlocked; this is strictly safer but means `update_tokens()` can be called
  twice sequentially in the failure scenario — acceptable and intentional.
- **Lock hold duration**: the lock is now held across network retries
  (`retries` × ~0.5 s sleeps + provider latency). Other threads block for that
  duration; bounded by `RETRIES = 2` and mirrors the intent of the current
  design.
- **Public API**: `_acquire_store_lock` / `_release_store_lock` are
  module-private with no external callers (verified by grep); deletion is not an
  API break. The `RenewalOutcome` contract (`docs/tools.md`, exit codes) is
  unchanged.
- **Cross-process dimension untouched**: concurrent *processes* are excluded by
  the file-based `AuthLock` in `cli.py`; this fix only repairs in-process
  threading semantics. Do not conflate the two in the fix commit.
- **Test flakiness**: threaded regression tests need explicit handoff (barrier +
  side-effect timing like the existing test) to be deterministic under TDD's
  red phase.

## Open Questions

- [NEEDS CLARIFICATION: none blocking. Optional: whether `_renew_locks`'s
  unbounded per-path dict growth deserves its own tech-debt row or should ride
  along with this fix.]