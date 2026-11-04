# Bug Fix: `log.py` redaction duplicated; malformed `Z+00:00` timestamp (DRY + BUG)

- **Slug**: td-013
- **Fixed**: 2026-11-04
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Removed the malformed `Z+00:00` timestamp suffix from `auth_event`
(plain `+00:00`, per the established `utc_now_iso()` contract) and
deduplicated the secret-redaction loop into a shared `_redact(text)`
helper used by both `_RedactionFilter.filter` and `auth_event`. Tests
that codified the broken format were rewritten TDD-first (red → green).

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/log.py` | modified | Dropped `.replace("+00:00", "Z+00:00")` at the timestamp construction; added `_redact(text)` helper; `_RedactionFilter.filter` and `auth_event` now call it; docstring pins the ISO-8601 `+00:00` contract |
| `tests/unit/test_log.py` | modified | Rewrote `ISO_8601_UTC_RE` (now `...\+00:00$`), replaced `test_timestamp_contains_z` with `test_timestamp_is_fromisoformat_parseable`; added `datetime` import |
| `docs/tools.md` | modified | Example stderr event lines corrected (`Z+00:00` → `+00:00`) |
| `specs/001-schwab-oauth-access/contracts/events.md` | modified | Example event lines corrected (6 lines) |
| `specs/002-automated-token-renewal/contracts/events.md` | modified | Example event lines corrected (2 lines) |
| `specs/006-transaction-history/contracts/events.md` | modified | Example event line corrected (1 line) |
| `docs/CHANGELOG.md` | modified | `### Fixed` entry under `[Unreleased]` |
| `docs/tech-debt.md` | modified | TD-013 marked **Resolved** with remediation summary |

## Diff Highlights

`src/schwab_mcp/log.py`:

```python
def _redact(text: str) -> str:
    """Return *text* with every registered secret replaced by ``***``."""
    for secret in sorted(_secrets, key=len, reverse=True):
        text = text.replace(secret, "***")
    return text
```

```python
# before
ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z+00:00")
# after
ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
```

`tests/unit/test_log.py` — the regex that codified the bug:

```python
# before: r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z[+-]\d{2}:\d{2}"
# after:
r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$"
```

## Tests Added or Updated

- `tests/unit/test_log.py::TestAuthEventFormat::test_timestamp_is_fromisoformat_parseable` — regression test (TD-013): the emitted timestamp parses via `datetime.fromisoformat()` with a zero UTC offset; fails with `ValueError` on the old `Z+00:00` output.
- `tests/unit/test_log.py::TestAuthEventFormat::test_line_starts_with_iso8601_timestamp` — `ISO_8601_UTC_RE` rewritten to pin standard `+00:00` format (was requiring `Z` before the offset).
- `test_timestamp_contains_z` — **removed** (codified the malformed hybrid; constitution forbids skipping, so it was replaced rather than skipped).
- Existing redaction tests (`test_log.py`: scrub tests, `test_secret_in_detail_is_scrubbed`, `test_secret_does_not_scrub_substrings`) pass unchanged through the `_redact` helper — semantics preserved.

## Local Verification

- Commands run:
  - `uv run pytest tests/unit/test_log.py -x -q` **before** the source fix → `1 failed` (red, as expected: timestamp `2026-11-04T17:46:59Z+00:00` rejected by the new regex)
  - `uv run pytest tests/unit/test_log.py -q` after the fix → `76 passed`
  - `uv run pytest tests/unit tests/performance -q` → `1566 passed`
  - `uv run pytest -q` (full suite, commit gate) → **`1820 passed`, 0 skipped**
- Manual check (pre-fix, during assessment): `datetime.fromisoformat("2026-11-04T12:00:00Z+00:00")` → `ValueError`; post-fix format verified by the new regression test.
- Manual grep: no unintended `Z+00:00` remains in `src/`, `tests/`, `specs/`, `docs/` (remaining hits describe the old bug: tech-debt register, changelog, docstrings, regression-test docstring).

## Deviations from Assessment

- **Scope expansion (documentation/contracts)**: the assessment listed `docs/tools.md` and `CHANGELOG.md`, but the example event lines in the authoritative event contracts also carried the malformed format — `specs/001-schwab-oauth-access/contracts/events.md`, `specs/002-automated-token-renewal/contracts/events.md`, and `specs/006-transaction-history/contracts/events.md` were corrected too (constitution: affected documentation in the same commit). `docs/tech-debt.md` was updated to mark TD-013 resolved, following the convention of the other resolved TD entries.
- Everything else follows the preferred remediation exactly (plain `+00:00` contract, not the `Z` suffix; `_redact` helper kept local to `log.py` to avoid import cycles).

## Follow-ups

- Consolidate `utc_now_iso()` (duplicated in `positions.py` and `transactions.py`) with `log.py`'s timestamp construction into one shared utility — deferred per the assessment to keep this fix minimal.
- Consider having `specify` re-render contract examples from a single source if contract/example drift recurs.