# Bug Assessment: `$SPX` delta re-fetch at `strikeCount=200` aborts on provider response-body limit (`502 TooBigBody`)

- **Slug**: spx-chain-body-limit
- **Created**: 2026-11-03
- **Source**: session evidence — live diagnostics run today (`tmp/diag_spx.py`, `tmp/verify_spx_live.py`) and the failed-verification findings in `../spx-delta-timeout/test.md`
- **Verdict**: valid
- **Severity**: high

## Report (verbatim or summarized)

Follow-up bug to `spx-delta-timeout` (whose client-timeout layer is fixed and verified). After the
timeout fix, the live reproduction still fails. Direct provider diagnosis (real tokens, `$SPX`,
60-DTE window, `contractType=ALL`, `includeUnderlyingQuote=true`):

```
strikeCount=50:  status=200 elapsed=2.5s  bytes=3,994,462
strikeCount=100: status=200 elapsed=3.8s  bytes=7,700,322
strikeCount=200: status=502 elapsed=43.8s bytes=98
  body: {"fault":{"faultstring":"Body buffer overflow","detail":{"errorcode":"protocol.http.TooBigBody"}}}
```

Post-fix live tool path: `$SPX` + `delta_target` (max_strikes 50 and 100) → first fetch at
`strikeCount=100` succeeds (~4 s, 7.7 MB), the ceiling re-fetch at 200 returns the 502 above after
~44 s, mapped to `ConnectivityError("… unreachable after retry …")` at 45.7 s / 48.5 s total.
Controls pass as documented: `$SPX` no-delta ok (2.4 s), `SPY` + `delta_target` ok (5.5 s).
Verdict of `../spx-delta-timeout/test.md`: **failed**, with this as the newly exposed root cause.

Relevant prior art in the repo: `specs/008-extract-option-chain/research.md` (R2) already named the
"Body buffer overflow" SDK risk as the reason to reject `range="ALL"`, and the accepted design
states: *"if it is still not bracketed, the available contracts closest to the target are
returned"* — i.e. graceful degradation was the documented intent, never an abort.

## Symptom

`get_option_chain` with `delta_target` on `$SPX` raises `ConnectivityError` ("check connectivity")
~46–48 s per call, even though the first `strikeCount=100` fetch succeeds — the failure comes from
the internal ceiling re-fetch at `strikeCount=200`, whose response exceeds Schwab's API-gateway
body limit. Expected per the design (R2): the re-fetch failure should degrade to the already-fetched
window (closest contracts to the target), not error — and certainly not present as a transient
connectivity failure.

## Reproduction

1. Build the real client (fixed factory, `timeout=60`) with valid tokens.
2. Call `get_option_chain(client, "$SPX", delta_target=-0.35)` (any `max_strikes` ≤ 100).
3. First fetch at `strikeCount=max(max_strikes, 100)` succeeds; `_delta_bracketed` is False; the
   ceiling re-fetch at 200 runs ~44 s and gets `502 …TooBigBody` → `ConnectivityError`.
   Reproduced live today (2/2 tool-path attempts; provider diagnosis confirms the fault body).

Works as intended for equities/ETFs and smaller chains (SPY, and `$SPX` without `delta_target`).
[NEEDS CLARIFICATION: whether `strikeCount=100` itself can exceed the body limit on days with more
expirations inside the 60-DTE window — 7.7 MB sits close to the ~10 MB-class limit.]

## Suspected Code Paths

- `src/schwab_mcp/options_chain.py:751-755` (`get_option_chain`, delta path) — unconditionally
  re-fetches at `DELTA_STRIKE_COUNT_CEILING=200` when `_delta_bracketed` is False; no handling of a
  provider size-limit failure.
- `src/schwab_mcp/options_chain.py:307-313` (`fetch_option_chain`) — the place where provider HTTP
  statuses are already intercepted pre-parse (400 → no-options `{}`); a 502 `TooBigBody` fault body
  currently falls through.
- `src/schwab_mcp/provider.py:47-49` (`response_json`) — `status >= 500 → ConnectivityError`
  ("transient"), which is both the wrong classification for a deterministic request-shape fault and
  what turns the abort into a misleading "check connectivity" message.
- `src/schwab_mcp/options_chain.py:798-827` (`get_option_chain_tool`) — catches
  `ChainDataError`/`ValueError` into `ToolError` with the actionable message, but
  `ConnectivityError` passes through unwrapped (relates to open Bug 2: generic MCP-boundary error).

## Root Cause Hypothesis

For `$SPX`, the delta path's ceiling re-fetch requests a chain whose JSON response exceeds the
Schwab API gateway's response body buffer limit; the backend assembles it for ~44 s and the edge
proxy rejects it with `502 {"fault":{"faultstring":"Body buffer overflow","errorcode":
"protocol.http.TooBigBody"}}`. The code classifies any 5xx as transient `ConnectivityError` and
never anticipates this failure mode at the only call site that requests 200 strikes, so the
documented graceful-degradation design (R2: return closest contracts) never executes. Confidence:
**high** — provider fault body captured live, exact request reproduced, controls pass.

## Proposed Remediation

**Preferred** (two parts, contract-neutral where possible):

1. **Classify the fault explicitly.** In `fetch_option_chain`, next to the existing HTTP 400
   interception, detect `status == 502` with the `TooBigBody` fault (match `errorcode ==
   "protocol.http.TooBigBody"` or `faultstring == "Body buffer overflow"` in the body) and raise a
   dedicated domain exception — e.g. `ProviderBodyLimitError(ChainDataError)` in
   `schwab_mcp.errors` (or locally in `options_chain`) with
   `detail="provider_body_limit"` and the attempted `strike_count`. Genuine transient 502s (without
   the fault marker) keep mapping to `ConnectivityError`.
2. **Degrade the delta re-fetch.** In the `get_option_chain` delta path, attempt the ceiling
   re-fetch inside a narrow `except ProviderBodyLimitError` and fall back to the already-fetched
   `strikeCount=100` payload, then `build_chain_result` as today. Because R2 already documents
   "closest contracts to the target" as the behavior when still unbracketed, the resulting output
   shape is unchanged (`outcome: ok`, window clipped to available strikes) — no new response fields
   required (KISS, no contract change).
3. For **non-delta** oversized requests (e.g. explicit `max_strikes=200` on `$SPX`), let
   `ProviderBodyLimitError` surface as `ChainDataError` → `ToolError` with an actionable message
   ("provider response body limit exceeded for this symbol; reduce max_strikes") — the tool
   wrapper already maps `ChainDataError` to `ToolError`, which sidesteps the Bug 2 generic-error
   swallow for this case.

**Alternatives** (optional):
- *Adaptive ceiling*: skip the 200 re-fetch when the floor response body already exceeds a size
  threshold (e.g. > ~8 MB, measured off `response.content`), avoiding the ~44 s wasted call. Faster,
  but adds a heuristic that guesses the provider limit; combine with (1) as a belt-and-braces only
  if the wasted latency matters in practice.
- *Halving retry*: on body-limit fault, retry once at `strike_count // 2`. More robust if the limit
  can bite below 100, but multiplies upcalls and complexity; not justified by current evidence
  (100 → 7.7 MB is comfortably under).
- *Fixed index-symbol cap at 100*: simplest, but silently degrades bracketing quality for every
  index symbol and does nothing for oversized equity chains; rejected.

**Files likely to change**:
- `src/schwab_mcp/options_chain.py` — fault detection in `fetch_option_chain`; fallback in the
  delta path of `get_option_chain`; `_TOOBIGBODY` fault constant.
- `src/schwab_mcp/errors.py` — `ProviderBodyLimitError` (if placed there).
- `tests/unit/test_options_chain_delta.py` and/or a new `tests/unit/test_options_chain_body_limit.py`.
- `docs/tools.md` + `specs/008-extract-option-chain/contracts/` — only if a degraded-flag output
  change is opted into; the contract-neutral fallback needs no doc change beyond a changelog line.

**Tests to add or update** (TDD, regression-first):
- Unit: `fetch_option_chain` with a fake 502 response whose body contains
  `protocol.http.TooBigBody` → raises the body-limit domain error (not `ConnectivityError`).
- Unit: fake 502 **without** the fault marker → still `ConnectivityError` (no false classification).
- Unit: delta path — floor fetch returns an unbracketed payload, ceiling fetch raises the
  body-limit error → result built from the floor payload, `outcome: ok`, strikes closest to target,
  no exception raised; ceiling fetch attempted exactly once.
- Unit: non-delta path with explicit oversized `max_strikes` + body-limit fault →
  `ChainDataError`/`ProviderBodyLimitError` with actionable detail reaching the tool wrapper as
  `ToolError`.
- Regression: all existing delta-window tests (`tests/unit/test_options_chain_delta.py`) unchanged
  and green.

## Risks & Considerations

- **Contract**: the contract-neutral fallback keeps the documented R2 behavior; if a `degraded`
  echo field is added later, `docs/tools.md` and the 008 contract must move in the same commit
  (constitution gate). Recommended: no new field now.
- **Wasted latency**: the fallback still pays ~44 s for the doomed 200 request once per unbracketed
  SPX call. Acceptable initially; the adaptive-ceiling alternative exists if it hurts.
- **Boundary drift**: the limit is provider infrastructure (Apigee-class ~10 MB), not documented in
  Schwab's API docs; it could change. The fault-marker detection (rather than a hard-coded
  strikeCount cap) tracks the provider's own signal.
- **Observability**: classify with a distinct `auth_event` detail (e.g. `provider_body_limit`) so
  stderr logs distinguish degradation from transient failure.
- **Bug 2 interplay**: `ConnectivityError` still swallows into the generic MCP error for other
  paths; this assessment deliberately routes the new error through `ChainDataError` → `ToolError`
  to keep the message actionable without needing Bug 2 fixed first.

## Open Questions

- [NEEDS CLARIFICATION: measured provider body limit — is 7.7 MB (strikeCount=100) reliably under
  it day-to-day, or should the floor fetch also degrade (halving) when it hits the limit?]
- [NEEDS CLARIFICATION: product call on whether a degraded (unbracketed) SPX delta result should
  carry a visible echo (e.g. `filters.delta_window_clipped: true`) so callers know the target was
  not bracketed — currently R2's "closest contracts" behavior is silent.]