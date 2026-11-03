# Bug Assessment: `unrealized_pl` from `get_open_positions` ignores the option contract multiplier

- **Slug**: option-upl-multiplier
- **Created**: 2026-11-03
- **Source**: pasted text (live-verified bug report against v0.8.2 / v0.9.0, observed 2026-11-03 11:59 CT)
- **Verdict**: valid (root cause confirmed by code reading; reported live numbers reproduce exactly from the code formula)
- **Severity**: high

## Report (verbatim or summarized)

> `unrealized_pl` from `get_open_positions` ignores the option contract
> multiplier (broken for all options, worst on short positions).
>
> `get_open_positions` computes `unrealized_pl` as
> `market_value - average_price * quantity`. The provider payload carries
> `marketValue` already dollarized (includes the option contract multiplier,
> ×100) while `averagePrice` is the per-unit quote price (points, no
> multiplier). The cost-basis term is therefore understated ×100 for options.
> For equities (multiplier = 1) the formula happens to be correct, masking
> the bug. Aggravating detail: the provider payload already includes its own
> `unrealizedPL` field, and the mapping code discards it and replaces it
> with the local (broken) computation.

Live evidence (single call, account `...5105`, 2026-11-03T17:59:52+00:00, all
legs multiplier 100):

| Position | qty | avg_price | market_value | uPL reported by MCP | uPL correct |
|---|---|---|---|---|---|
| SPX 7705P (short) | −1 | 146.2371 | −21,240.00 | −21,093.76 | −6,616.29 |
| SPX 7695P (long) | +1 | 142.7129 | +20,745.00 | +20,602.29 | +6,473.71 |
| XSP 735P (short) | −1 | 6.3334 | −968.00 | −961.67 | −334.66 |
| XSP 805C (short) | −1 | 3.8734 | −187.00 | −183.13 | **+200.34** (sign flipped) |
| SPY 750P (long) | +1 | 12.5066 | +1,429.50 | +1,416.99 | +178.84 |
| SPY 760P (short) | −1 | 15.6331 | −1,797.00 | −1,781.37 | −233.69 |

Strategy-level consequence: summing the two per-leg `unrealized_pl` values of
a spread is also wrong (e.g. SPX put spread 7695/7705 real P/L −$142.58 vs
MCP leg-sum −$491.47), and the XSP 805C short leg flips sign (actually
winning +$200.34, reported as −$183.13) — a sign flip that changes trading
decisions.

## Symptom

Every OPTION position returned by `get_open_positions` reports an
`unrealized_pl` computed as `market_value − average_price × quantity`
without the ×100 contract multiplier on the cost-basis term; expected
`market_value − average_price × quantity × multiplier` (multiplier 100 for
options, 1 for equities). Short option legs can even flip sign.

## Reproduction

1. Call `get_open_positions` while holding any standard option (multiplier 100).
2. Compare the returned `unrealized_pl` against
   `market_value / (|quantity| × 100)` vs `average_price`.
3. Reported uPL ≡ `market_value − average_price × quantity` (no ×100 on the
   cost-basis term) for every option leg, long or short.

Verified against the code without a live call: for SPX 7705P
(MV −21,240.00, avg 146.2371, qty −1) the code formula gives
`−21240 − 146.2371 × (−1) = −21093.7629` — exactly the value the live call
reported. [NEEDS CLARIFICATION: none blocking; live reproduction was already
performed by the reporter on 2026-11-03.]

## Suspected Code Paths

- `src/schwab_mcp/positions.py:242-252` — `_compute_unrealized_pl()`:
  `return market_value - average_price * quantity` — the cost-basis term
  omits the contract multiplier. Docstring cites "research D3".
- `src/schwab_mcp/positions.py:360` — first call site in
  `map_provider_positions()` (new consolidated entries).
- `src/schwab_mcp/positions.py:390-392` — second call site
  (re-computation when emitting `PositionEntry` objects).
- `src/schwab_mcp/positions.py:646-650` — `_transform_provider_payload()`
  recomputes `unrealizedPL` from raw fields instead of passing through the
  provider's own `unrealizedPL` (the docstring of
  `map_provider_positions`, line 298, documents that the provider payload
  carries `unrealizedPL`). The `assetType` is available right there
  (line 640) as `instrument.assetType`.
- `src/schwab_mcp/positions.py:317` / `:648-649` — quantity built as
  `longQuantity − shortQuantity`; mixed long/short quantities on both sides
  would also break the formula (pre-existing, out of scope for the minimal fix).
- `tests/unit/test_positions.py:823-879` — existing uPL tests
  (`test_unrealized_pl_long`, `test_unrealized_pl_short`) cover **EQUITY
  only**, which is why the bug went unnoticed (multiplier = 1).

## Root Cause Hypothesis

`_compute_unrealized_pl()` multiplies the per-unit quote price
(`averagePrice`, in points for options) by raw quantity without the contract
multiplier, while `marketValue` is already dollarized (multiplier included).
For options this understates the cost-basis term by ×100; for equities the
multiplier is 1 so the formula is accidentally correct. The provider's own
`unrealizedPL` field is available in the payload but
`_transform_provider_payload` overwrites it with the locally computed value.
Confidence: **high** — formula read directly from source, and the reported
live values reproduce exactly from it.

## Proposed Remediation

**Preferred**: fix the formula in `_compute_unrealized_pl()` by threading the
contract multiplier through it. Change the signature to
`_compute_unrealized_pl(market_value, average_price, quantity, asset_type="EQUITY")`
(or accept an explicit `multiplier`), set
`multiplier = 100.0 if asset_type == "OPTION" else 1.0`, and compute
`market_value - average_price * quantity * multiplier`. Update the three call
sites (lines 360, 390, 646) to pass `asset_type` — at line 646 the asset type
is already extracted as `instrument.assetType`; at lines 360/390 it is the
position's `assetType`. The default `asset_type="EQUITY"` (multiplier 1)
keeps every other call path behavior-identical. Keep recomputing rather than
passing through the provider's `unrealizedPL`: the mapping layer is the
single source of truth, the consolidated-entries path (lines 339-348) sums
MV and averages avg_price and would need its own passthrough logic, and
provider field presence is not guaranteed across account/instrument types.

**Alternatives**:
- Pass through the provider's `unrealizedPL` from the raw payload instead of
  recomputing. Trade-off: trusts provider semantics blindly, breaks on the
  consolidation path (needs per-account aggregation of `unrealizedPL`, not
  averaging), and loses the single-source-of-truth property of the pure
  mapping core.
- Expose `multiplier` / `mark_price` in the curated output (report
  recommendation 1). Valuable for agent cross-validation but is a schema
  addition, not the fix — record as a follow-up, not part of this change.

**Files likely to change**:
- `src/schwab_mcp/positions.py`
- `tests/unit/test_positions.py`

**Tests to add or update**:
- Regression test pinning `unrealized_pl` for an OPTION short leg against the
  reported SPX 7705P figures (MV −21240.00, avg 146.2371, qty −1 →
  −6,616.29).
- OPTION long leg (SPX 7695P figures → +6,473.71).
- Sign-flip case: short option currently in profit (XSP 805C: MV −187.00,
  avg 3.8734, qty −1 → +200.34).
- Equity long/short results unchanged (existing tests
  `test_unrealized_pl_long` / `test_unrealized_pl_short` must keep passing).
- Direct unit test of `_compute_unrealized_pl` with `asset_type="OPTION"` vs
  `"EQUITY"`.
- `_transform_provider_payload` path: an OPTION raw position (assetType in
  the `instrument` sub-object) produces the multiplier-correct
  `unrealizedPL` in the internal payload.

## Risks & Considerations

- **Mini options** (multiplier 10, rare): the provider positions payload does
  not expose a multiplier field, so the `assetType == "OPTION" → 100` rule
  would still be wrong for them. Accept for now; document the limitation.
- **Output value change**: consumers relying on the old (wrong) numbers will
  see corrected — larger-magnitude — values; `docs/tools.md` describes the
  tool contract and may need a note if it documents the uPL semantics.
- **Mixed long/short quantities on both sides** (non-zero `longQuantity` and
  `shortQuantity` simultaneously) remain ambiguous; the minimal fix does not
  address it (pre-existing behavior, unchanged). Flagged as follow-up.
- **Existing test data oddity**: `test_unrealized_pl_short` uses a positive
  `marketValue` with a short equity position; since equities keep
  multiplier 1, that test is unaffected by this fix.

## Open Questions

- [NEEDS CLARIFICATION: none blocking the fix.]
