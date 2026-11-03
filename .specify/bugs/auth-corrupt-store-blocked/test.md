# Bug Verification: corrupted store made `auth` a dead-end loop ("Store treated as absent")

- **Slug**: auth-corrupt-store-blocked
- **Tested**: 2026-11-03
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: partial

## Summary

The symptom no longer reproduces at the automated level: with a
corrupted store (non-SQLite file, or a valid DB shadowed by a hot
journal — the assessed Server1 mechanism), `auth` now quarantines the
file (content preserved) and runs the real flow instead of exiting 5
with the circular "run schwab-mcp auth" message. All 1605 tests pass.
The **live** reproduction on `Server1` was not exercised — the fix is
not yet deployed there — so the verdict is `partial` rather than
`verified`.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix, automated equivalent) | `uv run pytest tests/integration/test_auth.py::TestCorruptStoreRecovery tests/integration/test_failures.py::TestAuthCorruptedStore -v` | pass | 5/5. Corrupt file → quarantined (`*.corrupt.*`, content preserved) → flow reached (exit 0 with fresh tokens / exit 3 when cancelled); never exit 5 |
| Live reproduction on `Server1` | not exercised | skipped | Fix not yet deployed to the affected host; the transcript scenario needs the real corrupt store there |
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

- **Live validation pending**: the fix is proven against the fakes
  (inert client and schwabdev-shaped client) plus the unit-level
  journal-poisoning mechanism, but the real `Server1` state (whatever
  left the store unreadable — interrupted flow, hot journal, or
  permissions) has not been replayed after the fix.
- Quarantine/backup files (`*.corrupt.*`, `*.bak.*`) accumulate without
  retention; documented as a follow-up, not a functional risk.
- A running `serve` process is unaffected by quarantine of the on-disk
  file until restart (open SQLite fd keeps serving the old inode).

## Recommendation

Close the bug **after** live validation: deploy the fix to `Server1`
(next release), run `uv run schwab-mcp auth`, and confirm the corrupt
store is quarantined automatically (a `tokens.db.corrupt.*` file
appears), the authorization URL is printed, and the browser flow
completes. If it does, upgrade this verdict to `verified` retroactively;
if the dead-end persists on the host, reopen via
`/speckit.bug.assess slug=auth-corrupt-store-blocked` with the new
transcript and the `~/.schwab-mcp/` directory listing.