# Bug Fix: negative `delta_target` sign handling + provider body-limit degradation

- **Slug**: delta-target-sign-bracketing
- **Fixed**: 2026-11-03
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Two-layer fix per the assessment: (1) delta bracketing and anchoring now operate on
`|delta_target|` — negative put targets (e.g. `-0.35`) get correct windows on every symbol and no
longer trigger the internal `strikeCount=200` ceiling re-fetch when the floor payload brackets the
target; (2) the provider's `502 Body buffer overflow / protocol.http.TooBigBody` fault is
classified as a deterministic `ProviderBodyLimitError(ChainDataError)` — the delta ceiling
re-fetch degrades to the last successful window (research R2), oversized explicit requests get an
actionable error, and genuine transient 502s still map to `ConnectivityError`.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/options_chain.py` | modified | `ProviderBodyLimitError(ChainDataError)` added next to `ChainDataError`; `_delta_bracketed` compares against `abs(delta_target)`; `_select_delta_window` anchors on `abs(delta_target)`; `fetch_option_chain` detects the 502 `TooBigBody` fault marker (same spot as the existing 400 interception); delta path catches the error on the ceiling re-fetch only and falls back to the floor payload with audit event `options_chain_query_degraded` |
| `src/schwab_mcp/log.py` | modified | Registered `options_chain_query_degraded` (outcome `degraded`) in `ALLOWED_EVENTS` / `_ALLOWED_OUTCOMES` |
| `docs/tools.md` | modified | New source-error row for the `TooBigBody` fault in the `get_option_chain` error table (degradation behavior + agent action) |
| `docs/CHANGELOG.md` | modified | `[0.9.4]` entries for both layers |
| `pyproject.toml` | modified | Version bump 0.9.3 → 0.9.4 (project bug-release pattern) |
| `tests/unit/test_options_chain_body_limit.py` | added | 11 tests covering both layers (see below) |

## Diff Highlights

Magnitude normalization (Layer A):

```python
# _select_delta_window
delta_target = abs(delta_target)          # was: raw signed value

# _delta_bracketed
target = abs(target)                      # was: raw signed value
```

Fault classification + degradation (Layer B):

```python
if getattr(response, "status_code", None) == 502:
    body = getattr(response, "text", "") or ""
    if "protocol.http.TooBigBody" in body or "Body buffer overflow" in body:
        raise ProviderBodyLimitError(
            f"provider rejected the chain response body as too large "
            f"(requested strikeCount={count}); reduce max_strikes or "
            f"narrow dte_max for this symbol")

# delta path, ceiling re-fetch only:
except ProviderBodyLimitError:
    auth_event("options_chain_query_degraded", "degraded",
               detail="provider_body_limit")
    # keep floor payload — R2: closest contracts to the target
```

## Tests Added or Updated

- `TestNegativeDeltaBracketing` (4) — straddling/below/above against a negative target, plus a
  positive-target regression guard.
- `TestNegativeDeltaAnchor` (2) — put and call windows centered on `|delta| ≈ |target|` for
  negative targets.
- `TestRefetchEconomy` (1) — a floor payload that brackets a negative target makes **exactly one**
  provider call at `strikeCount=100` (the `$SPX`-fatal 200 request never happens).
- `TestBodyLimitClassification` (2) — 502 + fault marker → `ProviderBodyLimitError` (a
  `ChainDataError`, not a `ConnectivityError`); 502 without the marker stays `ConnectivityError`.
- `TestDeltaDegradation` (2) — ceiling body-limit falls back to the floor payload (`outcome: ok`,
  ceiling attempted exactly once at `strikeCount=200`); non-delta oversized request raises
  `ChainDataError` with an actionable message naming `max_strikes`.

## Local Verification

- Commands run:
  - `uv run pytest tests/unit/test_options_chain_body_limit.py -q` (red first) → **7 failed / 4
    passed**, matching the defect layers exactly.
  - `uv run pytest tests/unit/test_options_chain_body_limit.py tests/unit/test_options_chain_delta.py tests/unit/test_log.py -q` → **100 passed** after the fix.
  - `uv run pytest -q` (full suite, commit gate) → **1714 passed, 0 skipped** (+11 vs the previous
    gate).
- Manual checks: `docs/tools.md` anchor wording ("contract with |delta| closest to the target") —
  the fixed behavior now matches the documented contract; no contract edit required.

## Deviations from Assessment

- **New audit event registered** (`options_chain_query_degraded`): the assessment suggested "a
  distinct `auth_event` detail"; implementation required adding the event name + outcome to
  `log.py`'s allowlist because `auth_event` validates against `ALLOWED_EVENTS` (discovered at
  test time — the naive new event name raised `ValueError`). Documented in `docs/tools.md`'s
  `get_option_chain` error table.
- **Fault detection placement**: implemented in `fetch_option_chain` (chain fetch only), not in the
  shared `provider.response_json` — the expiration-chain fetch has its own 400 interception and
  doesn't request oversized bodies; keeping the classification in the chain path matches the
  assessment's file list and avoids widening the shared taxonomy.
- Two test-expectation corrections during green phase (miscounted union windows in my own new
  tests — the `both` type unions the CALL and PUT windows; documented in the test docstrings).

## Follow-ups

- Live re-verification: `tmp/verify_spx_live.py` should now show `$SPX` + `delta_target` passing
  with a **single** `strikeCount=100` call (~4 s) and a correctly anchored window (the sign fix
  removes the spurious ceiling re-fetch; the degradation covers genuinely-unbracketed targets).
  → `/speckit.bug.test slug=delta-target-sign-bracketing`.
- [NEEDS CLARIFICATION carried over]: whether the `strikeCount=100` floor fetch can itself hit the
  body limit on heavy days (7.7 MB observed vs ~10 MB-class limit) — if so, the same fault marker
  enables a floor-level degradation later.
- Related open items: Bug 2 (domain errors swallowed at the MCP boundary — the degradation path's
  `outcome: ok` is visible to callers, but `ChainDataError` messages still may not reach stdio
  clients), and the `retry_call` "after retry" wording noted in `../spx-delta-timeout/fix.md`.