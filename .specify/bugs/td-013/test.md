# Bug Verification: `log.py` redaction duplicated; malformed `Z+00:00` timestamp (DRY + BUG)

- **Slug**: td-013
- **Tested**: 2026-11-04
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The original symptom no longer reproduces: `auth_event` now emits a
standard ISO-8601 `+00:00` timestamp that `datetime.fromisoformat()`
parses successfully, and the redaction logic works identically through
both the logging filter and the event-detail path via the shared
`_redact()` helper. The full regression suite is green with no
regressions found.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | Emit `auth_event("auth_start", "initiated")`, split the timestamp field, `datetime.fromisoformat(ts)` + offset assertion + `'Z+00:00' not in ts` | pass | Parsed to `2026-11-04 17:49:50+00:00` with zero UTC offset — the exact failure mode from the assessment (previously `ValueError`) is gone |
| Redaction path 1 (filter) | `register_secret` + `_RedactionFilter.filter` on a synthetic LogRecord containing the secret | pass | Record redacted to `leak *** here`, returns `False` (args-clearing semantics preserved) |
| Redaction path 2 (event detail) | `auth_event(..., detail="token=my-secret-token")`, inspect stderr | pass | Line shows `detail=token=***`; secret absent |
| New / updated tests | `uv run pytest tests/unit/test_log.py -k "timestamp or iso8601" -v` | pass | 3 passed — includes `test_timestamp_is_fromisoformat_parseable` (the TD-013 regression test) and the rewritten `ISO_8601_UTC_RE` check |
| Full unit module | `uv run pytest tests/unit/test_log.py -q` | pass | 76 passed |
| Regression suite (commit gate) | `uv run pytest -q` | pass | **1820 passed, 0 skipped** |
| Lint / type-check | — | not-run | No lint or type-check tooling is configured in this project (`pyproject.toml` has no ruff/mypy/etc.) |

## Output Excerpts

Post-fix reproduction:

```text
2026-11-04T17:49:43+00:00 auth_event=auth_start outcome=initiated
TIMESTAMP OK: 2026-11-04T17:49:50+00:00 -> 2026-11-04 17:49:50+00:00
FILTER REDACTION OK: leak *** here
EVENT REDACTION OK: 2026-11-04T17:49:50+00:00 auth_event=auth_success outcome=ok detail=token=***
```

Test runs:

```text
3 passed, 73 deselected in 0.02s        # timestamp/iso8601 selection
1820 passed in 34.08s                   # full suite, 0 skipped
```

## Residual Risks

- External consumers that (incorrectly) parsed the old `Z+00:00` format would see a format change — mitigated: the old format was not parseable by standard tooling, and `docs/tools.md` plus the event contracts now document the corrected format.
- Longest-first redaction semantics are covered by unit tests, but the `_redact` helper is not exercised against multi-byte/unicode secrets beyond the existing substring test; unchanged behavior relative to pre-fix code (identical loop), so no new risk introduced.
- The follow-up consolidation of `utc_now_iso()` (`positions.py`, `transactions.py`, `log.py`) remains open as recorded in `fix.md`.

## Recommendation

Close the bug — verified end-to-end: the reproduction steps from the
assessment were exercised post-fix and pass, the regression test added
by the fix is in place and red-confirmed (it failed against the old
format during `/speckit.bug.fix`), and the full suite is green with no
regressions. Ready for commit with the updated docs and contracts
included.