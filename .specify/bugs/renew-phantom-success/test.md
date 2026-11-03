# Bug Verification: phantom `renewal_success` on revoked tokens (unchecked HTTP status)

- **Slug**: renew-phantom-success
- **Tested**: 2026-11-03
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The phantom `renewed` symptom no longer reproduces — confirmed both by the
automated CLI-level reproduction and by the **live manual reproduction**
(exact incident shape: access token expired + refresh token rejected with
`invalid_grant`). `renew` now exits 3 with `reauth_required` /
`refresh_rejected`, `serve` exits 4 fast with `renewal_failure`, and no
`renewal_success` is ever emitted while the API rejects the calls. The
full regression suite is green. No regressions found.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix, automated) | `uv run python tmp/verify_renew_phantom_success.py` (CLI-level: seeded store + revoked-token client → `main(["renew"])`, `main(["serve"])`) | pass | `renew`: exit 3, `reauth_required`/`refresh_rejected`, store mtime unchanged. `serve`: exit 4. stderr shows only `renewal_failure outcome=reauth_required`; zero `renewal_success`. |
| Reproduction (post-fix, LIVE) | Manual: backed up `~/.schwab-mcp/tokens.db`, then set `access_token_issued` to 2 h ago (ISO-8601) and set `access_token`/`refresh_token` to invalid values (same `invalid_grant` server response as a revocation); ran `uv run schwab-mcp renew` and `uv run schwab-mcp serve`; restored the backup afterwards | pass | `renew` (19:27:45): exit **3**, stdout `{"detail":"refresh_rejected","expires_in_seconds":null,"outcome":"reauth_required","retryable":false}`, stderr `auth_event=renewal_failure outcome=reauth_required detail=run: schwab-mcp auth`, **no** `renewal_success`. `serve` (19:27:58): exit **4** immediately, `renewal_failure outcome=reauth_required`, message `Run schwab-mcp auth`. Exactly the expected post-fix behavior for the 11:53/12:32/12:35 incident shape. |
| Issue 2 warning (LIVE) | `uv run schwab-mcp auth` after restoring the store (19:21–19:22) | pass | stderr printed `Note: any other installation using this app key (another machine, server, or integration) has now had its token set revoked by Schwab.` and the event carried `auth_success outcome=ok detail=token set stored; other installations sharing this app key are now revoked`. |
| Guard asymmetry case (LIVE, bonus) | Same live procedure but with only the refresh token broken (access token left genuinely valid) | pass | Probe returned a real 2xx (access valid) but the store was never written → outcome `reauth_required` with the new detail `renewal_unverified`, exit 3 — the Issue 2 asymmetry ("API OK now, refresh dead") caught by the Issue 3 store-consistency guard instead of being reported as `renewed`. |
| New / updated tests | `uv run pytest tests/unit/test_renewal.py tests/integration/test_renew.py tests/integration/test_renewal_flow.py tests/integration/test_failures.py tests/integration/test_serve.py tests/integration/test_auth.py -q` | pass | 138 passed — includes the 9 new/updated regression tests from fix.md. |
| Regression suite | `uv run pytest -q` (full suite, commit gate) | pass | 1678 passed, 0 skipped, ~34 s. |
| Lint / type-check | — | not-run | No linter/type-checker is configured in `pyproject.toml` or `.github/workflows/ci.yml` (CI runs `uv sync && uv run pytest` only). |

## Output Excerpts

Automated reproduction:

```text
renew: exit=3 stdout='{"detail":"refresh_rejected","expires_in_seconds":null,"outcome":"reauth_required","retryable":false}'
  ok: store mtime unchanged
serve: exit=4 stdout=''
RESULT: PASS
```

Live reproduction (19:27, both tokens invalid — incident shape):

```text
2026-11-03T19:27:46Z+00:00 auth_event=renewal_failure outcome=reauth_required detail=run: schwab-mcp auth
{"detail":"refresh_rejected","expires_in_seconds":null,"outcome":"reauth_required","retryable":false}
exit=3

2026-11-03T19:27:59Z+00:00 auth_event=renewal_failure outcome=reauth_required detail=run: schwab-mcp auth
Run schwab-mcp auth
exit=4
```

Full suite:

```text
uv run pytest -q → 1678 passed in 34.15s
```

## Observations (non-blocking)

- `serve` blocks after a successful startup — expected: it is a stdio MCP
  server waiting for the MCP handshake on stdin, not a hang. Its
  `renewal_success outcome=ok` in the access-valid-but-refresh-dead run
  meant "live access validation passed" (FR-013), which was factually true
  (2xx from the API); it is not the phantom bug, which reported success
  while every call returned 401.
- New follow-up found while testing (unrelated to this bug): a store whose
  timestamps are present but unparseable (e.g. epoch numbers as TEXT in
  `access_token_issued`) makes `renew` fail with a raw schwabdev parse
  error and exit 1, instead of a classified `store_corrupted` result.

## Residual Risks

- **Probe store-guard race window**: in a genuine cross-process renewal,
  the guard requires the other process's store write to be visible at
  probe time; SQLite visibility is effectively immediate, but a
  pathological slow writer could classify a legitimate concurrent renewal
  as `renewal_unverified` (conservative failure: exit 3, not a phantom
  success).
- **`renewal_unverified` is a new contract detail value** — agents and
  automation matching on the `reauth_required` detail set should treat it
  like `refresh_rejected` (notify owner to run `schwab-mcp auth`).
- Manual-test backups `~/.schwab-mcp/tokens.db.pretest*` remain outside
  the repo; delete them once satisfied (they contain real credentials).

## Recommendation

Close the bug — verified end-to-end: the original symptom (phantom
`renewal_success` + exit 0 on revoked tokens) no longer reproduces live or
in the automated regression, the full suite is green, and the Issue 2
warning behaves as specified. The deferred follow-ups (the
`refresh_rejected_but_access_valid` detail at the tool boundary and the
unparseable-timestamp store handling) can be tracked separately.