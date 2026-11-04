# Bug Assessment: TestDteCeiling clock-dependent fixtures (off-by-one DTE)

- **Slug**: dte-ceiling-time-dependent
- **Created**: 2026-11-04
- **Source**: pasted text ("resolvamos el problema de esos 2 tests que no pasan")
- **Verdict**: valid
- **Severity**: low

## Report (verbatim or summarized)

User report (translated): "let's resolve the problem of those 2 tests that
don't pass." The two failing tests are:

- `tests/unit/test_option_expirations.py::TestDteCeiling::test_dte_max_30_excludes_entries_beyond_the_ceiling`
- `tests/unit/test_option_expirations.py::TestDteCeiling::test_dte_max_365_accepted_without_hard_upper_limit`

Actual failure output (2026-11-04):

```
assert [8] == [7, 30]              # test_dte_max_30...
assert [8, 201, 361] == [7, 200, 360]   # test_dte_max_365...
```

Every produced DTE is exactly the expected value + 1.

## Symptom

Two `TestDteCeiling` tests fail with an off-by-one DTE (e.g. `8` instead of
`7`) and over-inclusive ceiling filtering, even though the production DTE
logic is correct. They passed when written (2026-11-03) and broke the next
day — the failures are clock-dependent, not code-dependent.

## Reproduction

1. Run `uv run pytest tests/unit/test_option_expirations.py -q` on any date
   after 2026-11-03 → the two `TestDteCeiling` tests fail with expected DTE
   values each short by the number of days elapsed since 2026-11-03
   (observed: +1 on 2026-11-04).
2. Mechanism: `chain_expiry_date(7)` (tests/unit/helpers.py:335-338)
   defaults `today=None` → `date.today()` (real clock), producing an expiry
   at real-today + 7.
3. The test then calls `build_expiration_result(payload, _query(dte_max=…), TODAY)`
   with the fixed module constant `TODAY = date(2026, 11, 3)`
   (test_option_expirations.py:44). The code computes
   `dte = (expiry − TODAY).days` (options_chain.py:615) = days_ahead +
   (real_today − 2026-11-03) — off by +1 on 2026-11-04.
4. The ceiling filter (`dte > dte_max_effective → skip`, options_chain.py:616)
   then drops the 30-day entry (31 > 30), shrinking the expected list.

[NEEDS CLARIFICATION: none — mechanism fully verified; the +N drift grows
daily, which is why the suite shows exactly these two failures today.]

## Suspected Code Paths

- `tests/unit/helpers.py:335-338` — `chain_expiry_date(days_ahead, today=None)`:
  the default `today or date.today()` makes fixtures wall-clock-dependent.
- `tests/unit/test_option_expirations.py:253-255, 266-268, 276` — the three
  `TestDteCeiling` fixtures call the helper **without** `today=` while
  asserting exact DTE values pinned to the module's fixed `TODAY`
  (`:44`).
- `src/schwab_mcp/options_chain.py:615-616` — the DTE computation and
  ceiling filter: verified correct; not at fault.

## Root Cause Hypothesis

High confidence. This is a test time-bomb, not a production defect: the
fixtures mix a clock-based base (`date.today()` inside the helper default)
with assertions pinned to the fixed capture date `TODAY = 2026-11-03`
(the T002 live-capture date). The suite's dominant convention is to pass
`today=` explicitly — `test_options_chain_filters.py`, `test_options_chain_delta.py`
(`_TODAY` wrapper at `:80`), and `test_options_chain_body_limit.py` (`:57`)
all do — but `TestDteCeiling` was written relying on the default. The other
default-using call sites (mapping, integration, performance, no-secrets)
stay green because they are *self-consistent*: they don't pin `today`, so
the builder (which also defaults to the real clock) computes
`dte == days_ahead` exactly, independent of the date. Only the mixed
fixed-clock/clock-based combination drifts.

## Proposed Remediation

**Preferred**: pass the fixed `TODAY` explicitly at the three `TestDteCeiling`
fixture sites — `chain_expiry_date(7, TODAY)`, `chain_expiry_date(30, TODAY)`,
`chain_expiry_date(70, TODAY)` (and the 200/360 pairs) in
`tests/unit/test_option_expirations.py:253-255, 266-268, 276`. This restores
determinism, matches the established suite convention (explicit `today=`),
keeps the helper's convenient default for self-consistent call sites, and
touches only the failing test file. TDD note per the constitution: the
"red" state already exists (the two failing tests); the fix turns them green
without weakening any assertion.

**Alternatives**:
- Make `today` a required parameter of `chain_expiry_date` — prevents the
  mistake class entirely, but touches ~30 call sites across unit,
  integration, and performance tests and would break the intentional
  self-consistency pattern (clock-relative fixtures with clock-relative
  assertions); higher churn for the same determinant outcome here.
- Freeze time via `monkeypatch`/`freezegun` in `TestDteCeiling` — works, but
  the project already standardized on passing `today=` through the result
  builders; adding a freezing dependency/mechanism for two tests is more
  machinery than the problem needs.

**Files likely to change**:
- `tests/unit/test_option_expirations.py` (only)

**Tests to add or update**:
- Update the three `TestDteCeiling` fixtures to pass `today=TODAY`; both
  failing tests must then assert their original expected lists (`[7, 30]`
  and `[7, 200, 360]`) with zero assertion changes.

## Risks & Considerations

- Minimal: test-only change; no production code touched, no interface impact.
- The same latent pattern (default `today`) remains in other call sites; they
  are currently self-consistent and deterministic, but a future test that
  mixes the default helper with a pinned `today` would reintroduce this bug.
  A convention note on the helper docstring could help (optional).
- The commit gate (constitution: full suite green) is currently blocked by
  exactly these two failures, so this unblocks committing — that urgency,
  not user impact, is the reason to fix it now.

## Open Questions

- None.