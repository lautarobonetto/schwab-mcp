# Bug Assessment: negative `delta_target` breaks bracketing + anchoring (silent wrong strikes) and always triggers the SPX-fatal 200-strike re-fetch

- **Slug**: delta-target-sign-bracketing
- **Created**: 2026-11-03
- **Source**: session evidence — pure-function verification run today plus live provider diagnostics (`tmp/diag_spx.py`, `tmp/verify_spx_live.py`); prior layers documented in `../spx-chain-body-limit/` (halted fix, this file supersedes its remediation premise) and `../spx-delta-timeout/` (timeout layer, fixed + verified)
- **Verdict**: valid
- **Severity**: critical

## Report (verbatim or summarized)

Combined re-assessment of the `$SPX` + `delta_target` failure chain after the body-limit fix was
correctly halted (`../spx-chain-body-limit/fix.md`, status `not-applied`). Two confirmed layers:

**Layer A — sign defect (verified with pure functions, no network).** Payload whose put deltas
(−0.20…−0.50) perfectly straddle |target| = 0.35:

```
target=-0.35: bracketed=False                            ← WRONG: payload brackets the target
  put window strikes=[90.0, 95.0, 100.0]                 ← WRONG: anchor on deepest-OTM (|delta|=0.20)
target=+0.35: bracketed=True                             ← correct
  put window strikes=[90.0, 95.0, 100.0, 105.0, 110.0]   ← correct (anchor |delta|≈0.35)
```

- `_delta_bracketed` (`options_chain.py:504-526`) compares `abs(delta)` values against the **raw**
  `query.delta_target` (e.g. `-0.35`). Positive `abs` values are always `> -0.35`, so every
  negative target is classified "not bracketed" → the ceiling re-fetch at
  `DELTA_STRIKE_COUNT_CEILING=200` runs on **every** negative-target call, regardless of payload.
- `_select_delta_window` (`options_chain.py:473-501`) anchors on
  `min(abs(abs(delta) - delta_target))`; with target `-0.35` this minimizes `abs(abs(delta) + 0.35)`
  → selects the **smallest** `abs(delta)` (deepest OTM) instead of `|delta| ≈ |target|`. So for
  negative targets on ANY symbol the tool returns `outcome: ok` with strikes around the wrong
  contract — silently wrong data, already shipped behavior.

**Layer B — provider body limit (confirmed live today).** `$SPX`, 60-DTE window, `contractType=ALL`:

```
strikeCount=50:  status=200 elapsed=2.5s  bytes=3,994,462
strikeCount=100: status=200 elapsed=3.8s  bytes=7,700,322
strikeCount=200: status=502 elapsed=43.8s bytes=98
  body: {"fault":{"faultstring":"Body buffer overflow","detail":{"errorcode":"protocol.http.TooBigBody"}}}
```

Full chain for the field-reported case (`$SPX`, `delta_target=-0.35`): Layer A fires the 200-strike
re-fetch on every call → Layer B: the provider rejects the oversized response with
`502 protocol.http.TooBigBody` after ~44 s → `provider.response_json` maps 5xx → transient
`ConnectivityError` → tool errors after ~46–48 s. Controls verified live: `$SPX` no-delta ok
(2.4 s), `SPY` + `delta_target=-0.35` ok (5.5 s — but with Layer A's wrong anchor!).

Design prior art: `specs/008-extract-option-chain/research.md` R2 documents the "Body buffer
overflow" SDK risk and promises *"if it is still not bracketed, the available contracts closest to
the target are returned"*. `docs/tools.md` documents the anchor as *"the contract with |delta|
closest to the target"* — the code's negative-target behavior contradicts the documented contract.

## Symptom

With `delta_target` **negative** (the documented put-target form, e.g. `-0.35`): (1) on any symbol
the returned delta window is anchored on the deepest-OTM contract instead of `|delta| ≈ target`,
reported as `outcome: ok` — silently wrong strikes; (2) the internal `strikeCount=200` re-fetch
always runs, which on `$SPX` hits the provider body limit and errors with a misleading
`ConnectivityError` after ~46 s. Expected: bracketing/anchoring computed against `|delta_target|`;
re-fetch only when genuinely unbracketed; graceful degradation when the provider rejects the
re-fetch.

## Reproduction

1. Offline (Layer A): build a payload with put deltas straddling 0.35 (e.g. −0.20…−0.50); call
   `_delta_bracketed` with `delta_target=-0.35` → returns `False` (wrong); window anchors on the
   lowest-strike/lowest-`|delta|` contract (wrong).
2. Live (Layer B, post-timeout-fix): `get_option_chain(client, "$SPX", delta_target=-0.35)` →
   ~46–48 s → `ConnectivityError`; direct diagnosis shows the `502 TooBigBody` at 200 strikes.
3. [NEEDS CLARIFICATION: whether `strikeCount=100` itself can exceed the body limit on days with
   more expirations in the 60-DTE window — 7.7 MB sits close to the ~10 MB-class limit.]

## Suspected Code Paths

- `src/schwab_mcp/options_chain.py:512-525` (`_delta_bracketed`) — `target = query.delta_target`
  used raw; must compare against `abs(target)`.
- `src/schwab_mcp/options_chain.py:493-496` (`_select_delta_window`) — anchor key
  `abs(abs(item[1]["delta"]) - delta_target)`; must use `abs(delta_target)`.
- `src/schwab_mcp/options_chain.py:743-755` (`get_option_chain` delta path) — ceiling re-fetch
  has no handling for the provider body-limit failure.
- `src/schwab_mcp/options_chain.py:307-313` (`fetch_option_chain`) — provider status interception
  point (existing 400 → no-options pattern) where the 502 `TooBigBody` fault must be classified.
- `src/schwab_mcp/provider.py:47-49` (`response_json`) — `status >= 500 → ConnectivityError`
  misclassifies the deterministic fault as transient.
- `src/schwab_mcp/options_chain.py:139-144` (`ChainDataError`) — base class for the new
  body-limit error so the tool wrapper's existing `ChainDataError → ToolError` mapping applies.
- `tests/unit/test_options_chain_delta.py` — existing delta tests use positive targets only; no
  negative-target coverage exists (coverage gap that let Layer A ship).

## Root Cause Hypothesis

The delta feature internally treats `delta_target` as a magnitude when documenting behavior
(`|delta| closest to the target`, bracketing on `abs(delta)` values) but passes the signed value
into both comparisons. For negative targets both computations degenerate — bracketing is vacuously
false, anchoring selects minimal `|delta|` — which (a) silently returns wrong strike windows for
every negative-target query and (b) always triggers the 200-strike ceiling re-fetch, which for
`$SPX` exceeds the provider's response-body limit and aborts with a misclassified transient error.
Confidence: **high** — Layer A proven offline with pure functions; Layer B proven live with the
provider's own fault body.

## Proposed Remediation

**Preferred** (three parts; Parts 1–2 are a pure bug fix against the already-documented contract,
Part 3 carries over the still-valid `spx-chain-body-limit` classification + fallback):

1. **Magnitude normalization (Layer A).** In `_delta_bracketed`, compute
   `target = abs(query.delta_target)` before the comparison. In `_select_delta_window`, anchor on
   `abs(abs(delta) - abs(delta_target))`. `query.delta_target` itself is NOT rewritten — the
   `filters` echo keeps the user's signed value (contract-compatible).
2. **Fault classification (Layer B).** In `fetch_option_chain`, next to the existing HTTP 400
   interception: `status == 502` with fault body matching `errorcode == "protocol.http.TooBigBody"`
   (fallback match `faultstring == "Body buffer overflow"`) → raise
   `ProviderBodyLimitError(ChainDataError)` with `detail="provider_body_limit"` and the attempted
   `strike_count`. Genuine transient 502s (no fault marker) keep mapping to `ConnectivityError`.
3. **Graceful degradation.** In the delta path, catch `ProviderBodyLimitError` around the ceiling
   re-fetch only and fall back to the already-fetched floor payload (`strikeCount=100`), building
   the result per R2's documented "closest contracts to the target" behavior — no new response
   fields (contract-neutral). Non-delta oversized requests (explicit `max_strikes` beyond the
   limit) surface as `ChainDataError` → `ToolError` with an actionable "reduce max_strikes"
   message. Add a distinct `auth_event` detail (`provider_body_limit`) for observability.

**Alternatives** (optional):
- *Adaptive ceiling*: skip the 200 re-fetch when the floor response body already exceeds ~8 MB —
  avoids the ~44 s wasted call but adds a heuristic; only worth it if the wasted latency matters
  after Part 1 (which removes the re-fetch for correctly-bracketed targets).
- *Rewrite `query.delta_target` to its absolute value at validation time*: simpler inward, but
  changes the `filters` echo and contradicts the documented echo; rejected.
- *Halving retry on body-limit*: robustness against the limit biting below 100; no current evidence
  it does; deferred.

**Files likely to change**:
- `src/schwab_mcp/options_chain.py` — magnitude normalization (2 sites), `ProviderBodyLimitError`,
  fault detection in `fetch_option_chain`, fallback in the delta path, auth_event detail.
- `tests/unit/test_options_chain_delta.py` — negative-target bracketing/anchoring cases.
- `tests/unit/test_options_chain_body_limit.py` (new) — classification + fallback cases.
- `docs/CHANGELOG.md`, `pyproject.toml` — patch release per project pattern (0.9.4).
- `docs/tools.md` — no contract change expected (behavior now matches the documented
  "|delta| closest to the target"); confirm during fix.

**Tests to add or update** (TDD, red first):
- Bracketing: negative target, deltas straddling |target| → `True`; all `|delta| < |target|` →
  `False`; all `> |target|` → `False`; symmetric positive-target cases unchanged.
- Anchoring: negative target → window centered on the contract with `|delta| ≈ |target|` (both
  calls and puts); positive-target windows unchanged (existing tests stay green).
- Refetch economy: negative target + floor payload that brackets → **no** second
  `option_chains` call (the SPX-fatal request never happens).
- Classification: fake 502 + `TooBigBody` body → `ProviderBodyLimitError`; fake 502 without the
  marker → `ConnectivityError`.
- Degradation: delta path where the ceiling fetch raises `ProviderBodyLimitError` → result from
  floor payload, `outcome: ok`, ceiling attempted exactly once.
- Non-delta oversized → `ChainDataError` with actionable detail reaching the tool wrapper.

## Risks & Considerations

- **Silent-data-fix semantics**: after Part 1, previously "ok" negative-target responses change
  their strike windows (they were wrong). This is the intended contract per `docs/tools.md`, but
  consumers relying on today's (wrong) output see different strikes — call it out in the changelog.
- **Contract**: no output-shape change; behavior aligns with the documented R2/design text.
  `docs/tools.md` and the 008 contract should be re-checked (not edited) during the fix.
- **Provider limit drift**: detect via the provider's own fault marker, not a hard-coded cap; the
  ~10 MB-class limit is undocumented infrastructure and could change.
- **Wasted latency**: a genuinely-unbracketed SPX target still pays ~44 s once for the doomed 200
  request before degrading. Acceptable initially; adaptive ceiling is the follow-up if it hurts.
- **Bug 2 interplay**: routing the new error through `ChainDataError → ToolError` keeps the
  message actionable without waiting for the open MCP-boundary error-fidelity fix.
- **Version**: patch bump 0.9.4 with a changelog entry covering both layers (project release
  pattern; release tests pin CHANGELOG top against `pyproject.toml`).

## Open Questions

- [NEEDS CLARIFICATION: can the `strikeCount=100` floor fetch itself exceed the body limit on
  heavy days (7.7 MB observed)? If yes, a floor-level degradation (halving) is needed; the
  provider fault marker makes that detectable with the same mechanism.]
- [NEEDS CLARIFICATION: should a degraded (still-unbracketed) result carry a visible echo
  (e.g. `filters.delta_window_clipped: true`)? R2's documented behavior is silent; product call.]