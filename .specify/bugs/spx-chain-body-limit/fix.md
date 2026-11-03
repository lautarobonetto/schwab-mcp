# Bug Fix: `$SPX` delta re-fetch aborts on provider body limit (`502 TooBigBody`)

- **Slug**: spx-chain-body-limit
- **Fixed**: 2026-11-03
- **Assessment**: ./assessment.md
- **Status**: not-applied

## Summary

Execution halted **before any code change**. While preparing the TDD tests for the contracted
remediation, a pure-function check proved a load-bearing premise of the assessment wrong: the
ceiling re-fetch at `strikeCount=200` is not triggered by genuine unbracketing for negative
`delta_target` values — it is triggered **on every call** by a separate sign-handling defect in
`_delta_bracketed`/`_select_delta_window`. Applying only the contracted body-limit fallback would
silently return wrong-anchored results for the exact flagship case (`delta_target=-0.35`) while
masking that defect. Per the fix guardrails ("the root cause is elsewhere" → STOP), no source file
was modified.

## Changes

| File | Change | Notes |
|------|--------|-------|
| — | none | No source or test file touched; execution stopped at the plan-confirmation stage |

## New Finding (documented per guardrails, not fixed)

**Negative `delta_target` values are mishandled by both the bracketing check and the anchor
selection.** Verified with pure functions (no network), payload whose put deltas (−0.20…−0.50)
perfectly straddle |target| = 0.35:

```
target=-0.35: bracketed=False          ← WRONG: payload brackets the target
  put window strikes=[90.0, 95.0, 100.0]   ← WRONG: anchored on deepest-OTM (|delta|=0.20)
target=+0.35: bracketed=True           ← correct
  put window strikes=[90.0, 95.0, 100.0, 105.0, 110.0]  ← correct (anchor |delta|≈0.35)
```

Code paths:

- `src/schwab_mcp/options_chain.py:504-526` (`_delta_bracketed`) — compares `abs(delta)` values
  against the raw `query.delta_target` (e.g. `-0.35`); `all(v > -0.35)` is vacuously true, so any
  negative target is classified "not bracketed" → the ceiling re-fetch at 200 runs **always**.
  This is why the live SPX calls always reached the doomed `strikeCount=200` request.
- `src/schwab_mcp/options_chain.py:473-501` (`_select_delta_window`) — anchor minimizes
  `abs(abs(delta) - delta_target)`; with a negative target this minimizes `abs(abs(delta) + 0.35)`,
  selecting the smallest `abs(delta)` (deepest OTM) instead of `|delta| ≈ |target|`.

Consequence chain for the field-reported case: sign defect → spurious 200-strike re-fetch for
`$SPX` → provider `502 TooBigBody` (the body-limit layer this assessment targeted) →
`ConnectivityError`. The body-limit assessment remains valid as a layer, but the re-fetch
trigger itself must be fixed first; otherwise the contracted fallback degrades results that were
fetched for the wrong reason and hides the wrong-anchor behavior.

## Deviations from Assessment

- **Status is `not-applied`, by the guardrail for a mid-fix root-cause discovery** — not a judgment
  that the body-limit remediation was wrong; its layer (fault classification + graceful fallback)
  is still needed, but the remediation must now be designed against the corrected trigger model
  (fix the sign handling; the body-limit fallback then applies only to genuinely-unbracketed
  targets).
- No scope expansion was made to "quickly also fix" the sign defect here: it changes
  bracketing/anchor semantics covered by `specs/008-extract-option-chain` (FR-004, research R2) and
  needs its own assessment (contract interpretation: is a negative `delta_target` put-target
  normalized via `|target|`, and does the fix affect the documented output?).

## Follow-ups

- Re-run `/speckit.bug.assess` covering the **combined** failure chain — suggested slug:
  `delta-target-sign-bracketing` — with this file and `../spx-delta-timeout/test.md` as evidence.
  The re-assessment should decide: (1) the sign normalization for bracketing + anchoring
  (`|delta_target|`), (2) whether the existing 008 contract/tests encode the intended semantics for
  negative targets, (3) the already-assessed body-limit classification + fallback
  (this slug's assessment content carries over).
- After the combined fix: re-run the live verification (`tmp/verify_spx_live.py`,
  `tmp/diag_spx.py` kept in git-ignored `tmp/`) — a correct sign fix means the SPX call should
  bracket at `strikeCount=100` and never reach the 200 re-fetch.
- Related open items: Bug 2 (domain errors swallowed at the MCP boundary) and the `retry_call`
  "after retry" wording noted in `../spx-delta-timeout/fix.md`.