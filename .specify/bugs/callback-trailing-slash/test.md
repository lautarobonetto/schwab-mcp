# Bug Verification: Callback URL preserves the exact configured value (trailing "/")

- **Slug**: callback-trailing-slash
- **Tested**: 2026-11-02
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The original symptom no longer reproduces: a real `schwab-mcp auth` run with `SCHWAB_CALLBACK_URL=https://127.0.0.1/` constructs the schwabdev client, prints the authorize URL with the trailing slash preserved, and proceeds through the normal flow — the pre-fix `ValueError: callback_url cannot be a path` is gone. A control check confirms the underlying schwabdev rejection still exists when the shim is absent, so the shim is what neutralizes it. No regressions: full suite green (1269 passed, 0 skipped).

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | `SCHWAB_CALLBACK_URL=https://127.0.0.1/ SCHWAB_TOKEN_DB=<tmp> BROWSER=/bin/true uv run schwab-mcp auth` (dummy creds, isolated token DB) | pass | Client constructed; authorize URL printed with the slash (`redirect_uri=https://127.0.0.1/`); flow ended in the expected clean cancellation (exit 3, `auth_failure outcome=cancelled`) — NOT the pre-fix `ValueError` |
| Control (constraint still upstream) | direct `schwabdev.tokens.Tokens(..., 'https://127.0.0.1/')` in a fresh process, no shim | pass | Raises the original `ValueError` — proves the compat shim is load-bearing, not redundant |
| New / updated tests | `uv run pytest tests/unit/test_config.py tests/unit/test_schwabdev_compat.py -q` | pass | 24 passed (config 19 incl. the inverted preservation test; compat 5) |
| Regression suite | `uv run pytest -q` | pass | **1269 passed, 0 skipped** in ~35 s (commit gate) |
| Lint / type-check | — | not-run | No linter configured in the project (CI runs `uv sync && uv run pytest` only) |
| Live OAuth exchange with Schwab | — | skipped | Requires real portal-registered credentials and network; the original reproducible symptom (construction-time rejection) does not need it and is covered above |

## Output Excerpts

Reproduction (post-fix) — slash preserved, clean cancellation:

```
https://api.schwabapi.com/v1/oauth/authorize?client_id=...&redirect_uri=https://127.0.0.1/
auth_event=auth_failure outcome=cancelled detail=run: schwab-mcp auth to retry
exit=3
```

Control — unshimmed schwabdev still rejects:

```
ValueError as expected: [Schwabdev] callback_url cannot be a path (ends with "/").
```

Suites:

```
tests/unit/test_config.py + tests/unit/test_schwabdev_compat.py: 24 passed
full suite: 1269 passed in 35.65s
```

## Residual Risks

- The **live token exchange against Schwab's servers** was not exercised (needs real credentials); the fix's correctness there rests on the literal-comparison rule (OAuth RFC 6749 §3.1.2.3 + reporter's end-to-end success in their repo) and on the exact value now reaching both authorize and exchange.
- The shim wraps schwabdev internals (`Tokens.__init__`, `_callback_url`); if upstream changes them, the shim raises a loud `RuntimeError` (covered by `test_shim_fails_loudly_if_internals_change`) rather than silently mismatching — update the wrap when that fires.
- A callback ending in `//` is still rejected by design (documented in `docs/usage.md`).

## Recommendation

Close the bug — the symptom is verified gone at the real CLI level with the full suite green. The only unexercised step (live exchange) was never reproducible offline and is guarded by upstream-confirmed semantics; optionally confirm once on the reporter's installation after upgrading, and consider the upstream `schwabdev` PR noted in `fix.md` follow-ups.
