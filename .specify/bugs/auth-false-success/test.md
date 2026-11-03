# Bug Verification: `schwab-mcp auth` reports success with dead tokens in the store

- **Slug**: auth-false-success
- **Tested**: 2026-11-03
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The symptom no longer reproduces at the automated level: with a stale
store and a client that models schwabdev's exact stale behavior
(silent refresh fails with `invalid_grant`, hook never invoked),
`auth` now runs the real flow, never reports false success, and
restores the previous store on cancellation. All 1598 tests pass.
**Live validation on `Server1` (2026-11-03, v0.8.2) confirmed by the
maintainer**: the re-auth over the previously-stale store completed as
a real fresh authorization flow — no false "Authorization successful"
on dead credentials.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix, automated equivalent) | `uv run pytest tests/integration/test_auth.py::TestStaleStoreReauthorization -v` | pass | 4/4. The fake client replicates the assessment's transcript mechanism (confirmed in schwabdev source: `tokens.py:_update_access_token` returns `False` without invoking `call_on_auth`); pre-fix these fail, post-fix they pass |
| Live reproduction on real Schwab API | maintainer-confirmed live run on `Server1` after deploying v0.8.2 (2026-11-03) | pass | Real re-auth over the stale store completed as a fresh flow — no captured transcript, confirmed verbally by the maintainer |
| New / updated tests | `uv run pytest tests/integration/test_auth.py` | pass | 32 passed (incl. updated `TestReauthFlow` + 4 regression tests) |
| Helper unit tests | `uv run pytest tests/unit/test_tokens_backup.py` | pass | 12 passed (backup/restore/discard contract, permissions, collision safety) |
| Regression suite | `uv run pytest` | pass | 1598 passed, 0 skipped (pre-fix baseline: 1582) |
| Lint / type-check | — | not-run | No linter/type-checker configured; the project's gate is `uv sync && uv run pytest` (`.github/workflows/ci.yml`), which is the regression suite above |

## Output Excerpts

```text
tests/integration/test_auth.py::TestStaleStoreReauthorization::test_stale_store_runs_fresh_flow_not_silent_success PASSED
tests/integration/test_auth.py::TestStaleStoreReauthorization::test_stale_store_with_inert_client_never_reports_success PASSED
tests/integration/test_auth.py::TestStaleStoreReauthorization::test_cancelled_reauth_restores_store_and_leaves_no_backup PASSED
tests/integration/test_auth.py::TestStaleStoreReauthorization::test_successful_reauth_leaves_no_backup PASSED

1598 passed in 34.30s
```

## Residual Risks

- The live confirmation was verbal (no captured transcript); the
  automated suite remains the pinned regression evidence.
- A running `serve` process keeps serving the renamed (stale) store
  until restarted — documented in `fix.md` Follow-ups, unchanged by
  this verification.
- `auth-status` remains `valid` for server-side-revoked tokens (local
  read by design); out of scope per assessment.

## Recommendation

Close the bug — verified end-to-end (automated suite + live validation
on the affected host with v0.8.2).