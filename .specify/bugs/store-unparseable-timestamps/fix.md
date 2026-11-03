# Bug Fix: structurally valid store with unparseable timestamps now classifies as `store_corrupted`

- **Slug**: store-unparseable-timestamps
- **Fixed**: 2026-11-03
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

`peek_store_status` now validates the loader contract — the row's
`access_token_issued`/`refresh_token_issued` must be ISO-8601-parseable
text — so a structurally valid store with unparseable timestamps is
classified `corrupted` at the peek. `renew` exits 3 with
`detail: store_corrupted`, `serve` exits 5 (`TokenStoreCorruptedError`),
`auth` quarantines and proceeds, and `auth-status` reports
`reauth_required` — instead of the previous raw exit-1 crash (`renew`)
and misleading exit-2 config error (`serve`). The timestamp parse logic
moved to a single shared helper in `tokens.py`.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/tokens.py` | modified | Added `parse_issued_datetime(value)` (strict ISO-text criterion mirroring schwabdev's `_parse_dt`) and `issued_to_epoch(value, *, strict=False)` (lenient numeric branch preserved for the lifetime reader). `peek_store_status` now selects `expires_in, access_token_issued, refresh_token_issued` and classifies `corrupted` when the timestamps are not ISO-parseable (also covers missing columns via `sqlite3.Error`). `NULL expires_in` stays `present` — the loader does not consume it at load time. |
| `src/schwab_mcp/renewal.py` | modified | `_issued_to_epoch` delegates to the shared `tokens.issued_to_epoch(..., strict=False)` (single source of truth, Constitution II); `read_store_lifetime` behavior unchanged. Top-level import verified cycle-free. |
| `tests/unit/test_tokens.py` | added tests | `TestPeekStoreStatus`: ISO → present; epoch TEXT / epoch REAL / NULL timestamp / missing columns → corrupted; NULL `expires_in` → present. |
| `tests/unit/test_renewal.py` | added test + fixture update | `read_store_lifetime` returns `None` (never raises) for the live-observed epoch-TEXT store; `TestRenew._seed_store` now writes ISO-8601 TEXT instead of numeric epochs. |
| `tests/integration/test_failures.py` | added tests | `TestUnparseableTimestampStore`: `renew` → exit 3 + `store_corrupted` JSON (no raw isoformat error, no exit 1); `serve` → exit 5 (no "Fix the values in your environment"); `auth` → quarantined + flow reached (exit 3). |
| `tests/unit/test_tokens_quarantine.py` | fixture update | `_make_valid_store` uses the full schwabdev schema with ISO timestamps (the old 2-column row is unloadable under the loader contract). |
| `tests/integration/test_renew.py`, `test_auth_status.py`, `test_renewal_flow.py`, `tests/performance/test_renewal_budget.py` | fixture updates | `_make_token_db` helpers write ISO-8601 UTC TEXT instead of numeric epoch REAL values (aligned with what the real schwabdev loader requires). |
| `docs/tools.md` | modified | `renew` internal behavior: `corrupted` covers loadable-schema-but-unparseable-timestamp rows; classification happens at the peek. |
| `specs/002-automated-token-renewal/contracts/cli.md` | modified | Peek step documents the widened `corrupted` definition (no new enum values — `store_corrupted` semantics extended). |
| `docs/CHANGELOG.md` | modified | `[Unreleased]` Fixed entry for this bug. |

## Diff Highlights

Classification at the peek (`src/schwab_mcp/tokens.py`, `peek_store_status`):

```python
row = con.execute(
    "SELECT expires_in, access_token_issued, refresh_token_issued FROM schwabdev LIMIT 1"
).fetchone()
...
_expires_in, access_issued, refresh_issued = row
if (parse_issued_datetime(access_issued) is None
        or parse_issued_datetime(refresh_issued) is None):
    return "corrupted"   # loader could not load this row — FR-009
return "present"
```

Shared criteria (`src/schwab_mcp/tokens.py`): `parse_issued_datetime` is
the strict loader contract (ISO text only); `issued_to_epoch(value,
strict=False)` keeps the lenient numeric branch for the lifetime reader.

## Tests Added or Updated

- `tests/unit/test_tokens.py::TestPeekStoreStatus::test_present_for_loadable_iso_timestamps` / `test_corrupted_for_numeric_epoch_text` / `test_corrupted_for_numeric_epoch_real` / `test_corrupted_for_null_timestamp` / `test_present_for_null_expires_in` / `test_corrupted_for_missing_timestamp_columns` — pin the exact strict/lenient boundary of the classification.
- `tests/unit/test_renewal.py::TestStoreLifetimeReader::test_returns_none_for_unparseable_epoch_text_timestamps` — the lifetime reader never raises on the live-observed store.
- `tests/integration/test_failures.py::TestUnparseableTimestampStore::test_renew_exits_3_store_corrupted` / `test_serve_exits_5` / `test_auth_quarantines_and_reaches_flow` — end-to-end exit codes and messages for `renew`, `serve`, and `auth`.

## Local Verification

- Commands run:
  - `uv run pytest tests/unit/test_tokens.py tests/unit/test_renewal.py tests/integration/test_failures.py -q` → 98 passed
  - Fixture-conversion sweep (`test_tokens.py test_renewal.py test_tokens_quarantine.py test_tokens_backup.py test_renew.py test_renewal_flow.py test_auth_status.py test_renewal_budget.py`) → 95 passed before adding new tests
  - `uv run pytest -q` (full suite, commit gate) → **1690 passed, 0 skipped**
- Manual checks: the live reproduction of 2026-11-03 19:21 (`renew` exit 1 "Invalid isoformat string", `serve` exit 2 "Fix the values in your environment") is now covered by the integration tests; no manual re-run needed since the exact store shape (epoch TEXT in a valid SQLite schema) is reproduced programmatically.

## Deviations from Assessment

- **Fixture alignment was a larger change than the assessment's file list implied.** Applying the strict peek criterion (the assessment's preferred remediation) necessarily reclassified the test fixtures that write numeric epoch timestamps (REAL columns in `test_renew.py`, `test_auth_status.py`, `test_renewal_flow.py`, `test_renewal_budget.py`, `test_renewal.py::_seed_store`, and the minimal 2-column `_make_valid_store` in `test_tokens_quarantine.py`) as corrupted. All those fixtures were converted to write ISO-8601 UTC TEXT — which is what the real schwabdev loader requires anyway (real stores are always ISO TEXT per schwabdev's TEXT-column schema). This is the "leniency divergence" risk the assessment flagged; the chosen rule is: **peek = strict (ISO text only), lifetime reader = lenient (numeric tolerated for compatibility)**, both from one shared helper.
- **Open question resolved with evidence**: `expires_in` NULL is *not* corrupted — schwabdev only reads `expires_in` via `token_dictionary.get("expires_in", 1800)` when writing (`schwabdev/tokens.py:223`), never at load time. Pinned by `test_present_for_null_expires_in`.
- The lenient numeric branch was kept in the shared helper (assessment left this conditional) because `read_store_lifetime`'s documented compatibility behavior is pinned by its docstring and the delegation keeps behavior byte-identical.

## Follow-ups

- Consider hardening `auth`'s quarantine message to name the actual
  corruption reason (schema vs unparseable timestamps) if operators need
  to distinguish tampering from damage.
- The strict peek now guards every consumer; if a future schwabdev
  version widens its loader tolerance (e.g. accepts numeric epochs), the
  peek criterion should be revisited to avoid over-quarantining.
- Monitoring: none needed — the classification path is fully offline.