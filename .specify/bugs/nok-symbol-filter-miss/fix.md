# Bug Fix: `get_transaction_history` curated every trade as `CURRENCY_USD`

- **Slug**: nok-symbol-filter-miss
- **Fixed**: 2026-10-24
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

The `map_provider_transactions` mapper picked the first `transferItems[].instrument` with a symbol for curation; in the real payload the cash/fee legs (`CURRENCY_USD`) come first, so ~131 of 173 real trades ended up labeled as currency and the `symbol=NOK` filter never matched. The mapper now collects all candidates (top-level `instrument` + `transferItems`) and curates the **first non-currency instrument**, falling back to the first candidate only for genuinely cash movements. TDD: regression failing on Red with the real shape → fix → Green → full suite 842 passed, 0 skipped.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/transactions.py` | modified | `map_provider_transactions`: curation by first non-currency instrument; new `_is_currency_instrument()` helper (single definition of "currency leg", DRY) |
| `tests/unit/test_transactions_live_response.py` | added tests | `1c. Multi-leg trade shape` section with the real payload (4 non-None `CURRENCY_USD` fee legs first + OPTION leg last, observed live on 2026-10-24) |
| `docs/tools.md` | modified | `symbol` row of `MovementEntry`: documents the non-currency curation rule |
| `specs/006-transaction-history/data-model.md` | modified | Same rule in the `MovementEntry` table |
| `docs/CHANGELOG.md` | modified | New `[0.5.1]` section with the fix |
| `pyproject.toml` | modified | Version `0.5.0` → `0.5.1` (PATCH, consistent with CHANGELOG) |

## Diff Highlights

```python
# Before: first instrument with a symbol → fee legs masked it
instrument = tx.get("instrument")
if not (isinstance(instrument, dict) and instrument.get("symbol")):
    instrument = None
    for item in tx.get("transferItems") or []:
        cand = item.get("instrument") if isinstance(item, dict) else None
        if isinstance(cand, dict) and cand.get("symbol"):
            instrument = cand
            break

# Now: candidates in encounter order, first non-currency wins
candidates: list[dict] = []
top_instrument = tx.get("instrument")
if isinstance(top_instrument, dict) and top_instrument.get("symbol"):
    candidates.append(top_instrument)
for item in tx.get("transferItems") or []:
    cand = item.get("instrument") if isinstance(item, dict) else None
    if isinstance(cand, dict) and cand.get("symbol"):
        candidates.append(cand)

chosen = next(
    (cand for cand in candidates if not _is_currency_instrument(cand)),
    candidates[0] if candidates else None,
)
```

```python
def _is_currency_instrument(instrument: dict) -> bool:
    asset_type = instrument.get("assetType") or instrument.get("instrumentType")
    if asset_type:
        return str(asset_type).upper() == "CURRENCY"
    symbol = instrument.get("symbol") or ""
    return symbol.upper().startswith("CURRENCY_")
```

## Tests Added or Updated

- `tests/unit/test_transactions_live_response.py::TestMultiLegTradeShape::test_option_leg_curated_over_fee_legs` — pin: the OPTION leg wins over 4 non-None `CURRENCY_USD` fee legs; `underlying_symbol = "NOK"` derived from the corrected symbol
- `...::test_symbol_filter_matches_multileg_option` — e2e pin: `symbol="NOK"` returns the movement whose OCC root is NOK (M2), not `no_movements_for_instrument`
- `...::test_cash_only_trade_stays_currency` — pin: genuinely cash movements still curate to `CURRENCY_USD/CURRENCY`
- `...::test_first_noncurrency_leg_wins_deterministically` — pin: deterministic rule (first non-currency leg in encounter order)
- `...::test_top_level_currency_instrument_not_preferred_over_legs` — pin: a top-level currency `instrument` does not mask the `transferItems` instrument

## Local Verification

- `uv run pytest tests/unit/test_transactions_live_response.py::TestMultiLegTradeShape -x -q` (before the fix) → **1 failed** (Red: `CURRENCY_USD` masked the OCC — reproduces the defect)
- `uv run pytest tests/unit/test_transactions_live_response.py -q` (after the fix) → 20 passed
- `uv run pytest -q` (full suite, commit gate) → **842 passed, 0 skipped, 0 failed**
- Verification with live data: the fixture shape replicates byte-for-byte the one observed in the real payload of 2026-10-24 (`extended.transferItems` of PLTR/INTC/NOK trades). End-to-end verification against the live MCP server requires restarting the `schwab-mcp` process to load the corrected code (see Follow-ups).

## Deviations from Assessment

- **The `instruments[]` field and match shape M4 were not implemented** (part 2 of the preferred remediation). Justification with new evidence: live analysis of the 173 movements in the period showed **0 transactions with more than one non-currency instrument** (135 with exactly 1, 38 cash-only); the provider emits one transaction per leg. The existing M1/M2/M3 filter over the corrected curated symbol covers 100% of observed cases; `instruments[]` + M4 was speculative generality (constitution: KISS/YAGNI) and would have changed the payload contract and the 16 KB/page budget with no observed benefit. Left as a follow-up in case multi-instrument payloads appear (e.g. RECEIVE_AND_DELIVER assignments with stocks+options).
- **`tests/unit/test_transactions_filter_query.py` was not modified** (listed in the assessment for the M4 tests): the filter did not change and the e2e `symbol="NOK"` test lives in `test_transactions_live_response.py` next to the real-shape fixtures.
- **No description fallback**: real trades come with an empty transaction-level `description`; deriving it from the instrument description would be a useful improvement but out of the assessment's scope (follow-up).

## Follow-ups

- Restart the MCP server (`uv run schwab-mcp serve`) and re-run `get_transaction_history(symbol="NOK", start_date="2026-04-23", end_date="2026-10-23")` live to confirm the 14 NOK legs (end-to-end verification of the fix against the real provider).
- Watch future sweeps for transactions with multiple non-currency instruments (assignments/exercises); if they occur, implement `instruments[]` + match M4 per the assessment.
- Consider deriving `description` from the instrument description when the transaction does not carry one (reduces "anonymous" movements in curated trades).
- `/speckit.bug.test slug=nok-symbol-filter-miss` for formal verification.