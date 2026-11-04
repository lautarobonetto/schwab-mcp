# Bug Fix: TD-017 — Unused imports and members

- **Slug**: td-017
- **Fixed**: 2026-11-04
- **Assessment**: ./assessment.md
- **Status**: partial

## Summary

Applied the confirmed portion of the TD-017 cleanup: removed six dead
imports/members, derived `ALL_TRANSACTION_TYPES` from the enum (locked by a
new unit test), and updated the `retry_once` docstring mentions. One
assessment row (`config.py:36-37`) turned out to be **wrong** — the test
suite exercises `Config.__getitem__` — so that deletion was reverted and the
row corrected rather than "fixed".

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/positions.py` | modified | Removed unused `import time`; normalized `Optional[List[AccountFailed]]` → `Optional[list[AccountFailed]]` (drops the now-unneeded `List` import) |
| `src/schwab_mcp_release/allowlist.py` | modified | Removed unused `from collections.abc import Mapping` |
| `src/schwab_mcp/tokens.py` | modified | Removed unused `TypeVar F` (and `TypeVar` from the typing import); removed caller-less `retry_once()` wrapper |
| `src/schwab_mcp/renewal.py` | modified | Removed unused `from datetime import datetime, timezone` (mid-file import block) |
| `src/schwab_mcp/transactions.py` | modified | `ALL_TRANSACTION_TYPES` now derived as `",".join(t.value for t in ProviderTransactionType)` — verified byte-identical to the old hardcoded string |
| `tests/unit/test_transactions_models.py` | added tests | Pins the enum derivation and the 15-value coverage |
| `tests/integration/test_failures.py` | modified | Docstring mentions of `retry_once` → `retry_call` (retries=1), matching `server.py:156` |
| `tests/performance/test_startup_budget.py` | modified | Docstring mention of `retry_once()` → `retry_call()` (retries=1) |
| `tests/unit/test_tokens.py` | modified | Class docstring no longer describes `retry_once` as "existing" (minor scope note, see Deviations) |
| `docs/tech-debt.md` | modified | TD-017 summary row → `Partial (unreleased, 2026-11-04)`; six rows marked Fixed, one row Corrected (invalid claim), two rows marked Stale (already fixed by v0.9.8 refactor) |
| `src/schwab_mcp/config.py` | **reverted** | `__getitem__` deletion attempted, then reverted — see Deviations |

## Diff Highlights

`transactions.py` — duplication eliminated at the source:

```python
# before: 15 enum values hand-copied into a string literal
ALL_TRANSACTION_TYPES = (
    "TRADE,RECEIVE_AND_DELIVER,DIVIDEND_OR_INTEREST,ACH_RECEIPT,"
    ...
)

# after: derived, cannot drift from the enum
ALL_TRANSACTION_TYPES = ",".join(t.value for t in ProviderTransactionType)
```

`tokens.py` — dead wrapper removed:

```python
- def retry_once(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
-     """Retry exactly once (backward-compatible wrapper).
-     ...
-     return retry_call(fn, retries=1, *args, **kwargs)
```

## Tests Added or Updated

- `tests/unit/test_transactions_models.py::TestAllTransactionTypes::test_derived_from_enum_values` — pins `ALL_TRANSACTION_TYPES` to the enum derivation, so a future enum edit propagates instead of drifting.
- `tests/unit/test_transactions_models.py::TestAllTransactionTypes::test_covers_all_fifteen_upstream_types` — pins the 15-value count, uniqueness, and first/last values (`TRADE` … `SMA_ADJUSTMENT`).
- Docstring-only updates in `test_failures.py`, `test_startup_budget.py`, `test_tokens.py` (no functional change; no test called `retry_once` directly — confirmed during assessment).

## Local Verification

- Commands run: `uv run pytest` → **1828 passed, 0 failed, 0 skipped** (35–37 s). Commit gate green.
- Commands run: `uv run python -c "...assert ALL_TRANSACTION_TYPES == ','.join(...)"` → derived value byte-identical to the previous hardcoded string; all touched modules import cleanly.
- Commands run: `grep -rn "retry_once|TypeVar" src/` → no remaining references in source (only stale `__pycache__` artifacts).

## Deviations from Assessment

1. **`config.py:36-37` (`Config.__getitem__`) — assessment claim was invalid.**
   The assessment's caller check searched for `Config[` and `__getitem__`
   literally and concluded zero callers. The full-suite run failed with 11
   `TypeError`s in `tests/unit/test_config.py`: that file asserts via bracket
   access (`config["callback_url"]`, `config["app_key"]`, …) **15 times**, so
   `__getitem__` has real test callers and bracket access is part of the
   tested `Config` contract. Per the guardrails I stopped modifying that area,
   reverted the deletion (method and `Any` import restored), and corrected the
   row in `docs/tech-debt.md` instead of marking it fixed. Re-assessment of
   that single item is recommended before any removal attempt (it would
   require rewriting 15 test assertions to attribute access — a contract
   change, not a dead-code cleanup).
2. **`tests/unit/test_tokens.py` docstring updated** — the assessment listed
   only `test_failures.py` and `test_startup_budget.py`, but the
   `TestRetryCall` class docstring also described `retry_once` as "existing";
   reworded to keep test documentation accurate after the removal. Same
   category of change (docstring mention), flagged for transparency.
3. **`positions.py` `List` normalization applied** — the assessment marked
   the "List unused" claim incorrect but noted the `Optional[list[...]]`
   normalization "may ride along"; it did, which also removes the `List`
   import legitimately (the original row's import-level outcome, for the
   right reason).

## Follow-ups

- Re-assess the `Config.__getitem__` item in isolation if removal is still
  desired (requires deciding whether bracket access stays part of the
  `Config` contract and rewriting the 15 test assertions).
- Consider adding a lint gate (e.g. `ruff check --select F401,F811,F841`) to
  CI to catch unused imports mechanically — the assessment listed this as an
  optional follow-up.
- `renewal.py` still has a duplicated mid-file import block (lines ~101–107);
  merging it upward was left out as a style call beyond TD-017's minimal scope.
