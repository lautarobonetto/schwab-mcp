# Bug Verification: `$SPX` + `delta_target` timeout — configurable provider request timeout

- **Slug**: spx-delta-timeout
- **Tested**: 2026-11-03 (live run after user re-auth)
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: failed

## Summary

The timeout fix works exactly as designed and survives the full regression suite — but the
**original symptom still reproduces live**: `$SPX` + `delta_target` still fails with
`ConnectivityError`. The fix removed the first failure layer (10 s client timeout), which exposed a
deeper, previously-masked root cause: Schwab's API gateway rejects the `strikeCount=200` response
body (`502 protocol.http.TooBigBody` / "Body buffer overflow") for `$SPX`. The
`DELTA_STRIKE_COUNT_CEILING=200` re-fetch is structurally doomed for SPX-sized chains regardless of
client timeout. Re-run `/speckit.bug.assess` with the evidence below.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | `tmp/verify_spx_live.py` — real client via fixed factory, live Schwab API (user consented) | **fail** | `$SPX` + `delta_target` (both max_strikes=50 and 100) still → `ConnectivityError`, now after ~46–48 s instead of ~10 s |
| Controls (same live run) | same script | pass | `$SPX` no-delta → ok (2.4 s); `SPY` + `delta_target` → ok (5.5 s) — matches the report's repro table exactly |
| Root-cause diagnosis | `tmp/diag_spx.py` — direct `client.option_chains` at strikeCount 50/100/200 | pass | 50 → 200/4.0 MB/2.5 s; 100 → 200/7.7 MB/3.8 s; **200 → 502 after 43.8 s: `{"fault":{"faultstring":"Body buffer overflow","detail":{"errorcode":"protocol.http.TooBigBody"}}}`** |
| New / updated tests | `uv run pytest tests/unit/test_config.py::TestRequestTimeout tests/unit/test_client_factory.py tests/integration/test_serve.py::TestClientRequestTimeout -v` | pass | 13/13 |
| Real-library mechanism check | factory-built real `schwabdev.client.Client` | pass | `timeout` attribute = 60 (also confirmed in the live script output: `client timeout (s): 60`) |
| Regression suite | `uv run pytest -q` | pass | 1703 passed, 0 skipped |
| Lint / type-check | — | not-run | No linter configured in the project |

## Output Excerpts

Live verification (post-fix, real tokens):

```
client timeout (s): 60
FAIL $SPX + delta_target (the failing case): ConnectivityError: … unreachable after retry … elapsed=45.7s
FAIL $SPX + delta_target + max_strikes=100: ConnectivityError: … elapsed=48.5s
PASS $SPX no delta (report says OK): outcome='ok' detail='chain_retrieved' … elapsed=2.4s
PASS SPY + delta_target (report says OK): outcome='ok' detail='chain_retrieved' … elapsed=5.5s
```

Provider diagnosis (direct call, `$SPX`, dte window 60):

```
strikeCount=50:  status=200 elapsed=2.5s  bytes=3994462
strikeCount=100: status=200 elapsed=3.8s  bytes=7700322
strikeCount=200: status=502 elapsed=43.8s bytes=98
  body: {"fault":{"faultstring":"Body buffer overflow","detail":{"errorcode":"protocol.http.TooBigBody"}}}
```

## New Root-Cause Understanding (supersedes part of the assessment)

The assessment's root cause (missing `timeout` → 10 s default) was real and is fixed, but it was
only the **outermost** layer:

1. **Layer 1 (fixed)**: 10 s client timeout killed long fetches. With `timeout=60`, the
   `strikeCount=100` fetch (~4 s) now succeeds — pre-fix, it was at the edge of the timeout and the
   200-refetch attempt always died at 10 s (matching the report's observed `strikeCount=200`
   ReadTimeout).
2. **Layer 2 (newly discovered, NOT fixed)**: with the target not bracketed at 100, the code
   re-fetches at `DELTA_STRIKE_COUNT_CEILING=200` (`options_chain.py:751-755`). For `$SPX` the
   response at 200 exceeds Schwab's gateway **response body limit** — the backend spends ~44 s
   assembling it, then the edge returns `502 protocol.http.TooBigBody`. `response_json` maps the
   5xx → `ConnectivityError`. No client timeout value can fix this; the request must not be made.
3. Note `strikeCount=100` already yields 7.7 MB — close to the limit (~10 MB class). Daily variance
   (more expirations in the 60-DTE window, larger quotes) could push even 100 over the edge, so a
   hard cap at 100 alone is not a durable fix either.

Confidence: **high** — reproduced directly with status codes and the provider's own fault body.

## Residual Risks

- The `TooBigBody` 502 surfaces as a generic transient `ConnectivityError` ("check connectivity") —
  misleading diagnostics for a deterministic request-shape problem (relates to open Bug 2: domain
  error fidelity at the MCP boundary).
- The ceiling re-fetch costs ~44 s of wasted latency before failing every time for SPX.
- If a re-assessed fix caps/degrades `strike_count` for huge chains, delta-bracketing quality on
  SPX degrades (window may not contain the target) — the product trade-off must be decided in the
  re-assessment.

## Recommendation

**Reopen** — rerun `/speckit.bug.assess slug=spx-delta-timeout` (or a successor slug) with this
evidence. Candidate directions for the new remediation (to be evaluated there, not implemented
here):

- Detect the `502 … TooBigBody` fault in `response_json`/`fetch_option_chain` and treat it as a
  distinct domain error (e.g. `ChainDataError` with detail `provider_body_limit`), **not** transient
  connectivity.
- On that fault, degrade the `delta_target` path: reuse the last successful (`strikeCount=100`)
  fetch result and report `bracketed: false` / a degraded outcome, instead of re-fetching at 200.
- Consider a provider-aware ceiling (e.g. halve `strike_count` when a body-limit fault occurs, one
  bounded retry) rather than a fixed index-symbol cap.
- Keep the `SCHWAB_MCP_REQUEST_TIMEOUT` fix — it is correct and necessary regardless.

Diagnostic scripts kept for the re-assessment: `tmp/verify_spx_live.py`, `tmp/diag_spx.py`
(`tmp/` is git-ignored scratch).