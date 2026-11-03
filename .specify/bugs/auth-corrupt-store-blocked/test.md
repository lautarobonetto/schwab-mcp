# Bug Verification: corrupted store made `auth` a dead-end loop ("Store treated as absent")

- **Slug**: auth-corrupt-store-blocked
- **Tested**: 2026-11-03
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The symptom no longer reproduces at the automated level: with a
corrupted store (non-SQLite file, or a valid DB shadowed by a hot
journal — the assessed Server1 mechanism), `auth` now quarantines the
file (content preserved) and runs the real flow instead of exiting 5
with the circular "run schwab-mcp auth" message. All 1605 tests pass.
**Live validation on `Server1` (2026-11-03, v0.8.2) confirmed by the
maintainer**: `auth` recovered on its own — the corrupt store was
handled and the fresh authorization flow completed successfully.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix, automated equivalent) | `uv run pytest tests/integration/test_auth.py::TestCorruptStoreRecovery tests/integration/test_failures.py::TestAuthCorruptedStore -v` | pass | 5/5. Corrupt file → quarantined (`*.corrupt.*`, content preserved) → flow reached (exit 0 with fresh tokens / exit 3 when cancelled); never exit 5 |
| Live reproduction on `Server1` | maintainer-confirmed live run after deploying v0.8.2 (2026-11-03) | pass | `auth` recovered on its own and the fresh flow completed — no captured transcript, confirmed verbally by the maintainer |
| New unit tests (quarantine + sidecar hygiene) | `uv run pytest tests/unit/test_tokens_quarantine.py tests/unit/test_tokens_backup.py` | pass | 18 passed, incl. the poisoning mechanism: valid DB + hot journal reads "corrupted" → quarantined intact |
| Regression suite | `uv run pytest` | pass | 1605 passed, 0 skipped (pre-fix baseline: 1598) |
| Lint / type-check | — | not-run | No linter/type-checker configured; the project gate is `uv sync && uv run pytest` (CI), covered by the regression suite |

## Output Excerpts

```text
tests/integration/test_auth.py::TestCorruptStoreRecovery::test_corrupt_store_quarantined_then_fresh_flow_succeeds PASSED
tests/integration/test_auth.py::TestCorruptStoreRecovery::test_corrupt_store_cancelled_keeps_quarantine PASSED
tests/integration/test_failures.py::TestAuthCorruptedStore::test_auth_corrupted_store_quarantines_and_reaches_flow PASSED
tests/integration/test_failures.py::TestAuthCorruptedStore::test_auth_corrupted_store_content_preserved PASSED
tests/integration/test_failures.py::TestAuthCorruptedStore::test_auth_corrupted_store_bounded PASSED

1605 passed in 34.88s
```

## Residual Risks

- Quarantine/backup files (`*.corrupt.*`, `*.bak.*`) accumulate without
  retention; documented as a follow-up, not a functional risk.
- A running `serve` process is unaffected by quarantine of the on-disk
  file until restart (open SQLite fd keeps serving the old inode).

## Recommendation

Close the bug — verified end-to-end (automated suite + live validation
on the affected host with v0.8.2). The maintenance follow-ups
(retention of `*.bak.*`/`*.corrupt.*` files) remain optional cleanup.