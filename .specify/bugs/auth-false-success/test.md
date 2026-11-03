# Bug Verification: `schwab-mcp auth` reports success with dead tokens in the store

- **Slug**: auth-false-success
- **Tested**: 2026-11-03
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: partial

## Summary

The symptom no longer reproduces at the automated level: with a stale
store and a client that models schwabdev's exact stale behavior
(silent refresh fails with `invalid_grant`, hook never invoked),
`auth` now runs the real flow, never reports false success, and
restores the previous store on cancellation. All 1598 tests pass.
The **live** reproduction from the assessment (real revoked refresh
token on `Server1` against Schwab's API) was not exercised — it
requires server-side token revocation and real credentials — so the
verdict is `partial` rather than `verified`.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix, automated equivalent) | `uv run pytest tests/integration/test_auth.py::TestStaleStoreReauthorization -v` | pass | 4/4. The fake client replicates the assessment's transcript mechanism (confirmed in schwabdev source: `tokens.py:_update_access_token` returns `False` without invoking `call_on_auth`); pre-fix these fail, post-fix they pass |
| Live reproduction on real Schwab API | not exercised | skipped | Requires a server-side revoked refresh token + real credentials on `Server1` (credential safety; not available here) |
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

- **Live validation pending**: the fix is proven against a fake that
  mirrors schwabdev 4.0.0 behavior at the cited source lines, but the
  original transcript scenario (real `invalid_grant` on `Server1`) has
  not been replayed after the fix.
- A running `serve` process keeps serving the renamed (stale) store
  until restarted — documented in `fix.md` Follow-ups, unchanged by
  this verification.
- `auth-status` remains `valid` for server-side-revoked tokens (local
  read by design); out of scope per assessment.

## Recommendation

Close the bug **after** one live validation: once this fix reaches
`Server1`, re-run the assessment's reproduction (store with
`invalid_grant` refresh token → `uv run schwab-mcp auth`) and confirm
the authorization URL is printed, the browser flow runs, and success is
reported only after the fresh exchange. If that passes, the `partial`
verdict can be upgraded to `verified` retroactively in this file; if
the symptom still reproduces live, reopen via
`/speckit.bug.assess slug=auth-false-success` with the new transcript.