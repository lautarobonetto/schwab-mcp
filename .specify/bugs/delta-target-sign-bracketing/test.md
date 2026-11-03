# Bug Verification: negative `delta_target` sign handling + provider body-limit degradation

- **Slug**: delta-target-sign-bracketing
- **Tested**: 2026-11-03
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

Both layers of the bug no longer reproduce: the offline Layer-A reproduction (negative target
bracketing/anchoring) now behaves correctly, and the live `$SPX` + `delta_target=-0.35` call that
failed for the whole session passes in ~4 s with a single provider call and a correctly anchored
window. All 11 new tests, the touched suites, and the full regression gate (1714 passed, 0
skipped) are green.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction, Layer A (post-fix) | Pure-function check: payload with put deltas −0.20…−0.50 straddling 0.35, `_delta_bracketed` + `_select_delta_window` with target −0.35 and +0.35 | pass | `target=-0.35: bracketed=True put_window=[90, 95, 100, 105, 110]` — identical to the correct positive-target behavior (pre-fix: `bracketed=False`, window `[90, 95, 100]` anchored on deepest-OTM) |
| Reproduction, Layer B (post-fix, live) | `tmp/verify_spx_live.py` — real client via fixed factory, live Schwab API (user consented earlier this session; re-authed for this purpose) | pass | `$SPX` + `delta_target=-0.35` → `outcome=ok` in **4.0 s** (pre-fix: `ConnectivityError` at 45.7–48.5 s); elapsed proves a single `strikeCount=100` call — the SPX-fatal 200 re-fetch never ran |
| Anchor check (live) | Same script, prints the returned window's deltas | pass | SPY window centers on put delta **−0.344** ≈ \|target\| = 0.35 |
| Controls (live) | Same script | pass | `$SPX` no-delta ok (2.2 s); `SPY` + delta ok (1.7 s) — matches the original report's control table |
| New / updated tests | `uv run pytest tests/unit/test_options_chain_body_limit.py tests/unit/test_options_chain_delta.py tests/unit/test_log.py -q` | pass | 100 passed (11 new + existing delta + event-allowlist suites) |
| Regression suite | `uv run pytest -q` (full gate) | pass | **1714 passed, 0 skipped** |
| Degradation path (live) | Deliberate oversized request to hit the ~44 s `TooBigBody` fault live | skipped | Expensive/slow; covered by `TestDeltaDegradation` unit tests with the exact captured fault body |
| Lint / type-check | — | not-run | No linter configured in the project |

## Output Excerpts

```
offline Layer A (post-fix):
target=-0.35: bracketed=True put_window=[90.0, 95.0, 100.0, 105.0, 110.0]
target=+0.35: bracketed=True put_window=[90.0, 95.0, 100.0, 105.0, 110.0]

live (post-fix):
client timeout (s): 60
PASS $SPX + delta_target (the failing case): outcome='ok' detail='chain_retrieved' strikes=306 expirations=31 elapsed=4.0s
PASS $SPX + delta_target + max_strikes=100: … elapsed=4.0s
PASS $SPX no delta: … elapsed=2.2s
PASS SPY + delta_target: … elapsed=1.7s
    strike=754.0: deltas={'call': 1.0, 'put': -0.344}   ← anchor |delta| ≈ 0.35

uv run pytest -q → 1714 passed in 33.75s
```

## Chain of Evidence

1. **Layer A** was proven broken offline pre-fix (bracketed=False + OTM anchor for a perfectly
   bracketing payload) and is now proven correct offline post-fix, with the positive-target
   regression guard in place.
2. **Layer B** was proven live pre-fix (502 `TooBigBody` at 200 strikes; `ConnectivityError` at
   ~46 s) and is now avoided at the source: the sign fix means correctly-bracketing floor payloads
   never trigger the ceiling re-fetch (live elapsed 4.0 s = one call). The degradation fallback for
   genuinely-unbracketed targets is pinned by unit tests using the exact captured provider fault
   body.
3. Full regression gate green — no collateral damage to the 1703 pre-existing tests or the other
   `schwabdev.Client` call paths.

## Residual Risks

- The live **degradation** path (genuinely-unbracketed target → 44 s wasted ceiling call → fallback)
  is unit-tested but not exercised live (skipped as slow); its first real occurrence will be
  visible in stderr as `auth_event=options_chain_query_degraded`.
- The `strikeCount=100` floor fetch (7.7 MB observed) sits near the provider's body limit — a heavy
  day could push it over; the fault marker would then surface as an actionable
  `ProviderBodyLimitError` for the floor fetch (per open question in the assessment).
- The SPX window for the nearest (0-DTE-class) expiration shows extreme delta spacing between
  adjacent strikes (provider-side strike selection); observed again post-fix and internally
  consistent (call + |put| ≈ 1), not related to this bug — noted only as an observation.
- Bug 2 (domain errors swallowed at the MCP boundary) remains open: a `ChainDataError` from an
  oversized explicit `max_strikes` still reaches stdio clients as the generic
  "Error executing tool" wrapper.

## Recommendation

Close the bug — verified offline (Layer A) and live end-to-end (Layer B), with the regression gate
green. Remaining follow-ups tracked in `./fix.md` (floor-fetch limit headroom, Bug 2 error
fidelity, `retry_call` wording) are separate items, not regressions of this fix.