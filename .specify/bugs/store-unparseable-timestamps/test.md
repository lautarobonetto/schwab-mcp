# Bug Verification: structurally valid store with unparseable timestamps → classified `store_corrupted`

- **Slug**: store-unparseable-timestamps
- **Tested**: 2026-11-03
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The original symptom no longer reproduces: a structurally valid SQLite
store with numeric-epoch TEXT timestamps (the live-observed corruption of
2026-11-03 ~19:21) now classifies as `store_corrupted` at the peek —
`renew` exits 3 with `detail: store_corrupted`, `serve` exits 5,
`auth-status` exits 3 `reauth_required` — and the raw
"Invalid isoformat string" crash and the misleading "Fix the values in
your environment" config error are gone. The regression suite is green
with no failures. This bug is fully local (no provider dependency), so
the reproduction was exercised literally end-to-end.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | `uv run python tmp/verify_store_unparseable_timestamps.py` — real CLI stack, no mocks on our code; `schwabdev.Client` replaced by a canary that aborts if client construction is ever reached (proves classification happens at the peek) | pass | `renew`: exit 3, `{"detail":"store_corrupted","outcome":"reauth_required","retryable":false}`. `serve`: exit 5, no "Fix the values in your environment". `auth-status`: exit 3, `reauth_required`. Store mtime unchanged (FR-009). Canary never tripped → client construction never reached. |
| Reproduction (pre-fix reference) | Observed live 2026-11-03 ~19:21 CST during `renew-phantom-success` manual testing (user terminal transcript, quoted in assessment.md) | pass (reference) | `renew` exit 1 "Unexpected error: Invalid isoformat string: '1793726428'"; `serve` exit 2 "Fix the values in your environment". Same store shape as the post-fix run above. |
| New / updated tests | `uv run pytest tests/unit/test_tokens.py tests/unit/test_tokens_quarantine.py tests/unit/test_tokens_backup.py tests/unit/test_renewal.py tests/integration/test_failures.py tests/integration/test_renew.py tests/integration/test_auth_status.py tests/integration/test_renewal_flow.py tests/integration/test_auth.py tests/integration/test_serve.py tests/performance/test_renewal_budget.py tests/performance/test_startup_budget.py -q` | pass | 194 passed — includes the 12 new/updated tests from fix.md. |
| Regression suite | `uv run pytest -q` (full suite, commit gate) | pass | 1690 passed, 0 skipped, ~37 s. |
| Lint / type-check | — | not-run | No linter/type-checker configured in `pyproject.toml` or `.github/workflows/ci.yml` (CI runs `uv sync && uv run pytest` only). |

## Output Excerpts

Post-fix reproduction (real CLI stack, store = valid schema + epoch TEXT timestamps):

```text
renew: exit=3 stdout='{"detail":"store_corrupted","expires_in_seconds":null,"outcome":"reauth_required","retryable":false}'
serve: exit=5
auth-status: exit=3 stdout='{"access_expires_in_seconds":null,"refresh_expires_in_seconds":null,"state":"reauth_required"}'
ok: store mtime unchanged (FR-009)
RESULT: PASS
```

Full suite:

```text
uv run pytest -q → 1690 passed in 36.93s
```

## Residual Risks

- **Fixture-format coupling**: the strict peek criterion (ISO text only)
  means any future producer writing numeric epochs will have its stores
  quarantined by `auth` (preserved for forensics, recovery = re-auth).
  This is intentionally conservative and matches the current bundled
  schwabdev loader; revisit if schwabdev ever widens its loader
  tolerance (noted as a follow-up in fix.md).
- **Canary scope**: the reproduction stub only guards `renew`, `serve`,
  and `auth-status`; the `auth` quarantine path is covered by the
  integration test (`TestUnparseableTimestampStore::test_auth_quarantines_and_reaches_flow`),
  not by the standalone script.
- Manual-test backups `~/.schwab-mcp/tokens.db.pretest*` from the earlier
  `renew-phantom-success` verification still contain real credentials;
  delete them when no longer needed.

## Recommendation

Close the bug — verified end-to-end: the exact live-observed store shape
now classifies as `store_corrupted` through every CLI entry point with
the contract exit codes, the store is never modified, client construction
is provably never reached, and the full suite (1690 tests) is green.