# Bug Fix: `unrealized_pl` from `get_open_positions` ignores the option contract multiplier

- **Slug**: option-upl-multiplier
- **Fixed**: 2026-11-03
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

`_compute_unrealized_pl()` now includes the option contract multiplier in
the cost-basis term (`market_value - average_price × quantity × multiplier`,
with `multiplier = 100` for `assetType == "OPTION"` and `1` otherwise), and
all three call sites pass the asset type through. Every option position now
reports a correct dollarized unrealized P/L; equities are behavior-identical.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/positions.py` | modified | `_compute_unrealized_pl()` gains an `asset_type: str = "EQUITY"` parameter and applies `multiplier = 100.0 if asset_type == "OPTION" else 1.0`; docstring updated to document the dollarized-`marketValue` / per-unit-`averagePrice` scale mismatch. All three call sites updated: the consolidated-entry path (line ~360, passes `instrument_type_str`), the `PositionEntry`-emission path (line ~390, passes `data["instrument_type"]`), and `_transform_provider_payload()` (line ~646, passes `instrument.get("assetType", "EQUITY")`). |
| `tests/unit/test_positions.py` | added tests | New `TestUnrealizedPlOptionMultiplier` class (5 tests) pinning the live-observed SPX/XSP figures. |
| `specs/003-list-open-positions/research.md` | modified | D3 decision table row for `unrealized_pl` annotated with the correction (the original research formula was the source of the bug). |
| `docs/CHANGELOG.md` | modified | `[Unreleased] → Fixed` entry following the repo's fix-commit pattern (version bump deferred to the release commit). |

## Diff Highlights

```python
def _compute_unrealized_pl(
    market_value: float,
    average_price: float,
    quantity: float,
    asset_type: str = "EQUITY",
) -> float:
    multiplier = 100.0 if asset_type == "OPTION" else 1.0
    return market_value - average_price * quantity * multiplier
```

Call sites now pass the asset type, e.g. in `_transform_provider_payload()`:

```python
"unrealizedPL": _compute_unrealized_pl(
    pos.get("marketValue", 0.0),
    pos.get("averagePrice", 0.0),
    pos.get("longQuantity", 0.0) - pos.get("shortQuantity", 0.0),
    instrument.get("assetType", "EQUITY"),
),
```

## Tests Added or Updated

- `tests/unit/test_positions.py::TestUnrealizedPlOptionMultiplier::test_compute_unrealized_pl_option_vs_equity` — direct unit test: OPTION applies ×100 (−6,616.29 for the SPX 7705P figures), EQUITY applies ×1 (the old buggy −21,093.7629, pinned as the multiplier-1 result).
- `...::test_unrealized_pl_option_short_leg` — SPX 7705P short: −21,240.00 MV, avg 146.2371, qty −1 → **−6,616.29** (was −21,093.76).
- `...::test_unrealized_pl_option_long_leg` — SPX 7695P long: +20,745.00 MV, avg 142.7129, qty +1 → **+6,473.71** (was +20,602.29).
- `...::test_unrealized_pl_option_short_sign_flip` — XSP 805C short in profit: −187.00 MV, avg 3.8734, qty −1 → **+200.34** (the sign-flip case; was −183.13).
- `...::test_transform_payload_option_upl_multiplied` — the raw provider path (`assetType` inside the `instrument` sub-object) produces a multiplier-correct `unrealizedPL` in the internal payload.

Existing equity tests (`test_unrealized_pl_long`, `test_unrealized_pl_short`) keep passing unchanged — equities are behavior-identical.

## Local Verification

- Commands run:
  - `uv run pytest tests/unit/test_positions.py::TestUnrealizedPlOptionMultiplier -q` → **Red first**: 1 failed (`TypeError: unexpected keyword argument 'asset_type'`) before the fix; **5 passed** after.
  - `uv run pytest -q` → **1669 passed, 0 skipped** (full suite, run twice: after the fix and after the doc updates).
- Manual checks: recomputed the live SPX 7705P example by hand from the new formula — mark 212.40, `(146.2371 − 212.40) × 1 × 100 = −6,616.29` — matching the report's correct column; the old formula reproduced the reported buggy value exactly, confirming the diagnosis.

## Deviations from Assessment

- **Scope expansion (logged per the fix command rules)**: the assessment listed only `src/schwab_mcp/positions.py` and `tests/unit/test_positions.py`, but the constitution requires affected documentation in the same commit. Two docs were affected: `specs/003-list-open-positions/research.md` (its D3 row documented the buggy formula — the origin of the defect) and `docs/CHANGELOG.md` (the repo's established fix-commit pattern adds an `[Unreleased] → Fixed` entry; version bump stays with the release commit). `docs/tools.md` was checked and needs no change — it does not document the uPL computation semantics.
- Assessment recommendation 1 (expose `multiplier`/`mark_price` in the curated output) and recommendation 2 (mixed long/short quantities) were deliberately **not** implemented — they are schema/behavior additions beyond the minimal fix; recorded as follow-ups.

## Follow-ups

- Consider exposing `multiplier` and `mark_price` (= `market_value / (|quantity| × multiplier)`) in the curated output so agent consumers can cross-validate against `get_quotes` / `get_option_chain` (assessment recommendation 1; schema change → separate spec).
- Document or validate mixed positions with non-zero `longQuantity` **and** `shortQuantity` simultaneously — the `longQuantity − shortQuantity` quantity plus a single `average_price` remains ambiguous there (pre-existing, unchanged by this fix).
- Mini options (multiplier 10, rare) would still be miscomputed: the provider positions payload does not expose a per-contract multiplier. If one ever appears in a live payload, extend the mapping.
- Live re-verification: call `get_open_positions` against the live account after deploying and confirm the SPX/SPY/XSP legs match the report's "uPL correct" column (the `/speckit.bug.test` step).
