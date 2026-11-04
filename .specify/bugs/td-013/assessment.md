# Bug Assessment: `log.py` redaction duplicated; malformed `Z+00:00` timestamp (DRY + BUG)

- **Slug**: td-013
- **Created**: 2026-11-04
- **Source**: pasted text (tech-debt register entry TD-013; see `docs/tech-debt.md:494-507`)
- **Verdict**: valid
- **Severity**: medium

## Report (verbatim or summarized)

> The secret-redaction loop exists twice: `_RedactionFilter.filter`
> (`115-116`) and `auth_event` (`175-176`), both
> `for secret in sorted(_secrets, key=len, reverse=True): text.replace(secret, "***")`.
>
> `log.py:170` produces a malformed suffix:
> `.replace("+00:00", "Z+00:00")` outputs `2026-11-04T12:00:00Z+00:00`
> (presumably meant to end in `Z`).

## Symptom

Every `auth_event` stderr line carries a malformed timestamp suffix
(`...T12:00:00Z+00:00`) that is **not parseable** by
`datetime.fromisoformat()` (verified empirically: raises
`ValueError: Invalid isoformat string`), contradicting the ISO-8601
contract the codebase established elsewhere. Additionally, the
secret-redaction logic is duplicated verbatim in two places in
`log.py` (DRY violation). Expected: a standard ISO-8601 UTC timestamp
and a single redaction implementation.

## Reproduction

1. Emit any auth event (e.g. from Python: `auth_event("auth_start", "initiated")`, or run any CLI flow that logs an auth/renewal event).
2. Observe stderr: `2026-11-04T12:00:00Z+00:00 auth_event=auth_start outcome=initiated` — note the hybrid `Z+00:00` suffix.
3. `datetime.fromisoformat("2026-11-04T12:00:00Z+00:00")` → `ValueError` (verified with the project interpreter). Standard ISO-8601 log ingestion (`date -d`, Splunk/Elastic date parsers, `fromisoformat`) all reject or mis-handle it.

The DRY duplication needs no runtime reproduction — it is visible in source (`log.py:115-116` vs `log.py:175-176`, identical loops).

## Suspected Code Paths

- `src/schwab_mcp/log.py:170` — `.replace("+00:00", "Z+00:00")` produces the malformed hybrid suffix directly; this is the defect.
- `src/schwab_mcp/log.py:115-116` — redaction loop #1 (`_RedactionFilter.filter`).
- `src/schwab_mcp/log.py:175-176` — redaction loop #2 (`auth_event`, on `detail`), identical to #1.
- `src/schwab_mcp/log.py:144` — docstring says "ISO-8601 UTC timestamp" without pinning the exact suffix; ambiguity that let the hybrid survive.
- `tests/unit/test_log.py:33-35` (`ISO_8601_UTC_RE` requires `Z` followed by an offset), `:410-415` (`test_timestamp_is_utc_with_offset`), `:417-422` (`test_timestamp_contains_z`) — **these tests codify the malformed format**; two of them would fail against a correct implementation.
- Prior art / contract precedent: `src/schwab_mcp/positions.py:260-266` and `src/schwab_mcp/transactions.py:508-512` — `utc_now_iso()` docstrings explicitly state *"standard ISO-8601, no non-standard `Z+00:00` suffix. Parseable via `datetime.fromisoformat()`"*.
- `docs/tools.md:1262-1263` — example stderr output documents the malformed `Z+00:00` lines, propagating the defect to consumers.

## Root Cause Hypothesis

**Confidence: high.** `log.py:170` appends `.replace("+00:00", "Z+00:00")` to
`isoformat()` output, which is a literal recipe for the hybrid suffix
`Z+00:00`. The intent was presumably a `Z` suffix (the replacement text
even starts with `Z`), but the string was written to *include* the
original `+00:00` instead of replacing it. Critically, the unit tests
(`ISO_8601_UTC_RE`, `test_timestamp_contains_z`) were written to match
the buggy output rather than the ISO-8601 standard, so the suite is
green while the format is broken — a TDD escape. The codebase has
already decided the correct contract: `utc_now_iso()` in
`positions.py` and `transactions.py` returns plain `+00:00` and its
docstring explicitly rejects the `Z+00:00` suffix (this class of bug
was previously fixed for the token store, bug `store-unparseable-timestamps`).
`log.py` was left behind.

## Proposed Remediation

**Preferred**: Two changes in `src/schwab_mcp/log.py`, driven TDD-first:

1. **Timestamp contract** — align with the established codebase
   contract (plain `+00:00`, standard ISO-8601, `fromisoformat()`-parseable):
   drop the `.replace(...)` entirely at `log.py:170` and pin the
   contract in the `auth_event` docstring (`log.py:144`). Do **not**
   switch to a `Z` suffix — that would create a third timestamp style,
   inconsistent with `retrieved_at`/`generated_at` and with the
   explicit "no non-standard `Z+00:00`" precedent.
2. **DRY redaction** — extract a module-level `_redact(text: str) -> str`
   helper that loops over `sorted(_secrets, key=len, reverse=True)` and
   returns the redacted text; both `_RedactionFilter.filter` and
   `auth_event` call it. Preserve the filter's exact semantics
   (`redacted == msg` pass-through decision, `record.args = ()` clearing).

**Alternatives**:

- `.replace("+00:00", "Z")` (as the report suggests): valid ISO-8601,
  but introduces a divergent style vs `utc_now_iso()` consumers and
  contradicts the documented precedent. Rejected for consistency.
- Consolidate `utc_now_iso()` (currently duplicated in
  `positions.py` and `transactions.py`) with the new helper into one
  shared timestamp utility. Most DRY-correct long-term, but risks
  import-direction churn (log.py is a low-level module; importing from
  tool modules risks cycles). Recommend as a follow-up task, not part
  of this fix.

**Files likely to change**:

- `src/schwab_mcp/log.py`
- `tests/unit/test_log.py`
- `docs/tools.md` (example stderr lines at 1262-1263 must show the corrected format — constitution requires docs in the same commit)
- `docs/CHANGELOG.md` (entry)

**Tests to add or update** (TDD: update tests first → red → fix → green):

- Replace `ISO_8601_UTC_RE` (`tests/unit/test_log.py:33-35`) and
  `test_timestamp_contains_z` (`:417-422`) — they codify the malformed
  hybrid and must be removed, not skipped (constitution: 0 skipped).
- New regression test: the timestamp field of an emitted line parses via
  `datetime.fromisoformat()` and ends with `+00:00`.
- Keep/strengthen `test_timestamp_is_utc_with_offset` (`:410-415`).
- Existing redaction tests (`test_log.py:145-260`, `:593`) should pass
  unchanged through the `_redact` helper; add one asserting
  `auth_event` redacts secrets in `detail` (the second copy's behavior)
  if not already covered.

## Risks & Considerations

- **Format consumers**: anything that already parses the (malformed)
  `Z+00:00` output would break — unlikely, since the format is not
  machine-parseable today; in-repo consumers (integration tests) only
  substring-match event names, never the timestamp. `docs/tools.md`
  must be updated so external consumers are told the corrected format.
- **Test replacement vs. addition**: two existing tests actively assert
  the wrong format and must be deleted/rewritten, not bypassed — flag
  for review since this touches a green suite.
- **Redaction helper semantics**: the filter relies on
  `redacted == msg` to decide whether to mutate the record; the helper
  must return the text so both callers keep current behavior (no
  secret leakage regression — verify with the existing secret-leak tests).
- **Import hygiene**: keep the helper local to `log.py` (or a neutral
  util) to avoid circular imports with tool modules.

## Open Questions

- Should consolidating `utc_now_iso()` (positions.py + transactions.py +
  the new log helper) into one shared utility be a separate follow-up
  task? (Recommended: yes — keeps this fix minimal.)