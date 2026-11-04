# Bug Assessment: TD-016 — Dead parameters in helpers

- **Slug**: td-016
- **Created**: 2026-11-04
- **Source**: pasted text (verbatim from `docs/tech-debt.md` § TD-016, lines 589–596)
- **Verdict**: valid
- **Severity**: low

## Report (verbatim or summarized)

> ### TD-016 — Dead parameters in helpers
>
> | Location | Issue |
> |----------|-------|
> | `transactions.py:386-394` | `_should_split(range_days)` — parameter "accepted for interface consistency", never used; `3000` cap should be a named constant (`UPSTREAM_TXN_CAP`) |
> | `transactions.py:480` | `range_days` computed only to feed the dead parameter |
> | `positions.py:580` | ~~`_detect_account_failures(payload, retrieved_at)` — `retrieved_at` never used~~ Fixed (TD-007, v0.9.8): parameter removed |
> | `options_chain.py:675-680` | ~~`_result_meta(query, payload)` — `payload` never used (also listed in TD-008)~~ Fixed (TD-008, v0.9.8): signature is now `_result_meta(query)` |

## Symptom

Code-hygiene defect, not a behavioral bug: `_should_split(movements, range_days)` in
`src/schwab_mcp/transactions.py:390` declares a `range_days` parameter that the body never
uses (the trigger is purely `len(movements) >= 3000`), and the caller at
`transactions.py:484-485` computes `range_days` from the ISO date range **only** to pass it
into that dead parameter. The magic number `3000` is inlined in three places
(`_should_split` body line 398, its docstring, and `_bisect_range`'s docstring line 459)
instead of a named constant.

Of the four report rows, two are already resolved and verified in code:

- `positions.py` — `_detect_account_failures(provider_payload)` at line 599 has no
  `retrieved_at` parameter (TD-007 fix confirmed).
- `options_chain.py` — `_result_meta(query: OptionChainQuery)` at line 717 has no `payload`
  parameter (TD-008 fix confirmed).

## Reproduction

Not a runtime bug; reproducible by inspection:

1. Open `src/schwab_mcp/transactions.py:390-398` — `_should_split` accepts `range_days` and
   returns `len(movements) >= 3000` without reading it.
2. Open `src/schwab_mcp/transactions.py:482-485` — `_bisect_range` computes
   `range_days = (end - start).days + 1` solely to call
   `_should_split(movements, range_days=range_days)`.
3. Grep for `3000` in `src/` — the cap appears as an inline literal in the helper body and
   in docstrings, with no shared named constant.

## Suspected Code Paths

- `src/schwab_mcp/transactions.py:390-398` — `_should_split(movements, range_days)`; the
  `range_days` parameter is dead (docstring itself admits it is "accepted for interface
  consistency").
- `src/schwab_mcp/transactions.py:484-485` — `range_days` computed only to feed the dead
  parameter; whole line + kwarg can go.
- `src/schwab_mcp/transactions.py:398` — inline `3000` literal; should be a module constant
  `UPSTREAM_TXN_CAP` per the report.
- `src/schwab_mcp/transactions.py:459` and `:391` — docstrings referencing "3000-txn cap"
  (candidates to reference the constant, low priority).
- `tests/unit/test_transactions_split.py:41-90` — every `_should_split` test passes
  `range_days=...` and will break when the parameter is removed.
- `docs/tech-debt.md:593-594` — the TD-016 rows to strike through once fixed.

## Root Cause Hypothesis

Refactor residue: the split-trigger logic was consolidated into `_should_split` at some
point, and an older condition that also considered the time span (e.g. "split if the range
is wide AND the response is at cap") was reduced to a pure length check — but the caller's
`range_days` computation and the parameter were left behind to "keep the interface stable"
for a caller that no longer needs it. Confidence: **high** (the dead parameter is
self-documented in the docstring, and the strikethrough rows show two sibling defects from
the same era already fixed in v0.9.8).

## Proposed Remediation

**Preferred**: Minimal, behavior-preserving cleanup in `src/schwab_mcp/transactions.py`:

1. Add a module-level constant near the other module constants:
   `UPSTREAM_TXN_CAP = 3000` (with a one-line comment: upstream returns at most 3000
   movements per query; hitting it triggers bisection).
2. Change the signature to `_should_split(movements: list) -> bool` and return
   `len(movements) >= UPSTREAM_TXN_CAP`; update the docstring to drop the
   "interface consistency" sentence.
3. In `_bisect_range`, delete the `range_days = ...` computation (line 484) and call
   `_should_split(movements)`; keep the DRY comment pointing at `_should_split` as the
   single source of truth for the cap trigger.
4. Optionally reference `UPSTREAM_TXN_CAP` in the `_bisect_range` docstring instead of the
   "3000-txn cap" prose (do not touch `docs/tools.md:303` or CHANGELOG — prose mentions of
   the number are fine and out of scope).
5. Strike through the two `transactions.py` rows in `docs/tech-debt.md` TD-016 the same way
   the TD-007/TD-008 rows are annotated (Fixed, vX.Y.Z), and add the entry to
   `docs/CHANGELOG.md` in the same commit (Constitution: docs updated in-commit).

**Alternatives**:

- Keep `range_days` for a future smarter trigger (e.g. split early when a wide range
  returns near-cap counts). Rejected for now: speculative — KISS; re-add when a real need
  exists.
- Inline the length check in `_bisect_range` and delete `_should_split` entirely. Rejected:
  `_should_split` is the documented single source of truth for the cap trigger and is
  directly unit-tested; removing it would concentrate logic in the recursive function and
  reduce testability.

**Files likely to change**:

- `src/schwab_mcp/transactions.py`
- `tests/unit/test_transactions_split.py`
- `docs/tech-debt.md`
- `docs/CHANGELOG.md`

**Tests to add or update**:

- `tests/unit/test_transactions_split.py` — update all `_should_split(...)` calls to the
  new one-argument signature (lines 41–90); add a test asserting the cap constant is
  honored, e.g. a list of `UPSTREAM_TXN_CAP` items triggers split and `UPSTREAM_TXN_CAP - 1`
  does not (locks the constant to behavior instead of a literal).
- Existing `_bisect_range` bisection tests should pass unchanged (behavior-preserving) —
  they are the regression net.

## Risks & Considerations

- Very low risk: pure signature/constant refactor with no behavior change; only caller is
  `_bisect_range` (verified: `_should_split` appears only at definition and line 485 in
  `src/`).
- `_should_split` is a private helper (leading underscore) — no public API breakage;
  `docs/tools.md` does not document it.
- Per the constitution, the fix must be TDD: update the tests to the new signature first
  (red), then the implementation (green).
- Magic-number hygiene: after introducing `UPSTREAM_TXN_CAP`, grep `src/` for `3000` to
  ensure no other literal copy remains in code (docstrings referencing the concept are
  acceptable).

## Open Questions

- None blocking. (Line numbers in the report are slightly stale: the helper now spans
  390–398 and the `range_days` computation is at 484, not 480 — likely shifted by the
  TD-007/TD-008 fixes. Substance confirmed unchanged.)
