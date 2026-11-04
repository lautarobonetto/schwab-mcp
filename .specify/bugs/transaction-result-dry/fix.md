# Bug Fix: TD-005 — Result construction repeated in `get_transaction_history` (DRY)

- **Slug**: transaction-result-dry
- **Fixed**: 2026-11-04
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Pure refactor of `src/schwab_mcp/transactions.py` eliminating the duplicated
result construction flagged by TD-005: shared result helpers, one
`__cause__` classifier, a module-level `PAGE_SIZE` used by all three
sites, a single `partial_failure` branch (the dead all-failed branch is
gone), extracted `_paginate` / `_fetch_account_movements` / `_account_hash`
helpers, and a single-parse validator rule 7. No behavioral change — the
full suite (1789 tests) stayed green throughout.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/transactions.py` | modified | Module-level `PAGE_SIZE = 50` above `TransactionsResult`; referenced by paginator, validator rule 2, and the `returned` field description (f-string) |
| `src/schwab_mcp/transactions.py` | modified | New helpers: `_classify_connectivity_cause`, `_reauth_result`, `_transient_result`, `_empty_ok_result`, `_paginate`, `_account_hash`, `_fetch_account_movements` |
| `src/schwab_mcp/transactions.py` | modified | `get_transaction_history` deduplicated: reauth/transient blocks ×2 → helpers; two `partial_failure` branches → one `if failed_accounts:`; two "ok, no movements" sites → `_empty_ok_result`; inline pagination → `_paginate`; inline per-account fetch → `_fetch_account_movements` |
| `src/schwab_mcp/transactions.py` | modified | Validator rule 7 parses each `occurred_at` once (list comprehension in the `try`, comparison in the `else`); redundant `filter_match_count is not None` conjunction removed (detail now derived from `symbol` in `_empty_ok_result`) |
| `src/schwab_mcp/transactions.py` | modified | Step section comments renumbered (old step 5 moved into `_fetch_account_movements`) |
| `tests/unit/test_transactions_query.py` | added tests | `TestPageSizeConsistency` pins `PAGE_SIZE` as the single source of the page size |

## Diff Highlights

Module constant + single definition of the page size:

```python
PAGE_SIZE = 50
"""Movements per page (TD-005: defined once; used by the paginator in
``get_transaction_history``, validator rule 2, and the ``returned`` field
description)."""
```

Shared cause classifier replacing two `__cause__` inspections:

```python
def _classify_connectivity_cause(exc: ConnectivityError) -> str:
    cause = exc.__cause__
    if isinstance(cause, (ReauthorizationRequiredError, PermissionError)):
        return "reauth"
    if isinstance(cause, (ConnectivityError, ConnectionError)):
        return "transient"
    return "provider_error"
```

Dead all-failed `partial_failure` branch deleted; one branch now covers
both cases (with no successes, `_paginate([])` yields exactly the
previously hardcoded values):

```python
if failed_accounts:
    # Single partial-failure branch (TD-005): ...
    return TransactionsResult(
        outcome=TransactionOutcome.partial_failure,
        ...,
        movements=_page, total_count=_total, returned=_returned,
        has_more=_has_more, next_offset=_next_offset, offset_echo=offset,
    )
```

## Tests Added or Updated

- `tests/unit/test_transactions_query.py::TestPageSizeConsistency::test_page_size_is_module_level_constant` — `PAGE_SIZE` is importable and equals 50 (TDD Red before the refactor: `AttributeError`).
- `tests/unit/test_transactions_query.py::TestPageSizeConsistency::test_returned_field_description_derives_from_page_size` — the `returned` field description mentions the `PAGE_SIZE` value, so the sites cannot diverge.
- No behavioral tests were added: the existing suite already locks every
  outcome class touched (ok/no_movements, transient, reauth,
  partial_failure both all-fail `test_all_accounts_fail_returns_partial_failure`
  and some-fail variants, plus the filter variants).

## Local Verification

- `uv run pytest tests/unit/test_transactions_query.py::TestPageSizeConsistency` (before refactor) → 1 failed (`AttributeError: no attribute 'PAGE_SIZE'`) — Red confirmed.
- `uv run pytest` (after refactor) → **1789 passed, 0 skipped** in ~34s — commit gate satisfied.
- Manual equivalence checks: empty-`symbol` edge (truthiness vs `is not None`) is safe because `validate_history_query` rejects empty symbols (`transactions.py:371`); all-failed pagination values arithmetically equal the deleted branch's hardcoded values for any valid `offset >= 0`.

## Deviations from Assessment

- **Line-count estimate**: the assessment targeted a "~80-line" orchestrator. The function is now 224 lines total (~170 body lines after the 46-line docstring) — down from 333, with all listed refactors applied. The residual length is the docstring, numbered step comments, audit-event calls, and outcome classification, which are already single-definition; compressing further would trade clarity for line count (KISS).
- **Extra helper `_account_hash`**: splitting the account-hash normalization out of the per-account fetch keeps the `ConnectivityError` handling (which needs early returns) in the orchestrator loop — not explicitly listed in the report, but required to extract `_fetch_account_movements` without contorting control flow.
- **Rule 2 error message**: now built from `PAGE_SIZE` (`f"has_more=true requires returned=={PAGE_SIZE}"`); rendered text is unchanged ("returned==50") since the constant is 50.

## Follow-ups

- `docs/CHANGELOG.md` entry should accompany the commit (internal refactor, no user-visible change; `docs/tools.md` unaffected).
- If the page size ever changes, update only `PAGE_SIZE` — the pin test will catch divergence between the constant and the field description.