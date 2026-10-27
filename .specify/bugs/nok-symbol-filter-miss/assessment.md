# Bug Assessment: `get_transaction_history` drops the instrument leg in multi-leg trades (`symbol=NOK` never matches)

- **Slug**: nok-symbol-filter-miss
- **Created**: 2026-10-23 (updated 2026-10-24 with live evidence)
- **Source**: pasted text
- **Verdict**: valid (reproduced and root cause confirmed with a live payload)
- **Severity**: high

## Report (verbatim or summarized)

> "Because the tool schwab.get_transaction_history [start_date=2026-04-23, end_date=2026-10-23, symbol=NOK] returned no records, even though there were NOK options transactions and the OCC of those transactions must have had NOK as the root."

User's second pass: "if you remove the instrument filter from the tool you will see that the options transactions do exist in that period."

## Symptom

`get_transaction_history(symbol="NOK")` over the 2026-04-23..2026-10-23 window returns `ok / no_movements_for_instrument` with 0 records, although there are 14 NOK options legs in the period. In fact the bug is broader: **almost every `trade` movement ends up labeled `CURRENCY_USD | CURRENCY` with an empty description** — the real instrument leg (option/equity) is lost in the mapping, so the symbol filter can never match.

## Reproduction (confirmed live, 2026-10-24)

1. Invoke `get_transaction_history(start_date="2026-09-24", end_date="2026-10-23")` (no filter): 23 movements, **18 with `category=trade` but all `symbol=CURRENCY_USD`**, amount pairs at the same timestamp (spread legs).
2. Re-invoke the same window with `extended=true`: the raw `extended.transferItems` **do contain the option leg** (e.g. `PLTR  261120P00180000`, `INTC  261120P00085000`) after 4 cash/fee items (`CURRENCY_USD` with `feeType` COMMISSION/SEC_FEE/OPT_REG_FEE/TAF_FEE).
3. Invoke with `symbol="NOK"` → 0 records; with `symbol="AMD"` → 0 records (AMD was also traded in the period).
4. Six-month sweep with `extended=true`: **131 of the `trade` movements are labeled `CURRENCY_USD` hiding a real instrument**; 14 NOK legs were identified in `transferItems`.

## Suspected Code Paths

- `src/schwab_mcp/transactions.py:824-860` (`map_provider_transactions`) — **ROOT CAUSE CONFIRMED**. It extracts the symbol from the top-level `instrument` or from the **first** `transferItems[].instrument` with a `symbol` (lines 829-833). In real payloads, the first `transferItems` items are the cash/fee legs with `instrument: {symbol: "CURRENCY_USD", assetType: "CURRENCY"}` (non-None), so `symbol` ends up as `CURRENCY_USD` and `instrument_type` as `CURRENCY`. `underlying_symbol` (lines 857-860) depends on the same `symbol`, so it is lost too. Note: the test `test_transactions_live_response.py:_real_trade_tx` models the cash leg with `instrument: None` — the real payload of 2026-10-24 carries it **non-None** (`CURRENCY_USD`), and first.
- `src/schwab_mcp/transactions.py:75-120` (`movement_involves_filter`) — **correct** (M1/M2/M3 verified live and via `tests/unit/test_transactions_underlying.py`); the filter does not match because the curated movement no longer contains the instrument.
- `docs/tools.md` (tool guarantees) — the contract claims curated description/symbol; the multi-leg case with fee legs is not modeled.

## Root Cause Hypothesis

**Confirmed (high confidence)**: in the real `/transactions` payload, every TRADE carries the cash and fee legs first in `transferItems` (all with `instrument.symbol = "CURRENCY_USD"`, `assetType = "CURRENCY"`) and the traded instrument leg last. The mapper takes the first item with a non-None symbol → every trade is curated as `CURRENCY_USD/CURRENCY`. Consequence: the local filter `symbol=X` never matches unless the movement is pure cash; `no_movements_for_instrument` is emitted as a false claim of absence. Evidence: the 14 NOK legs (05-05, 05-06, 06-02, 06-05 ×8, 06-24 ×2, 08-27) are present in `transferItems` with `assetType: OPTION` and `rootSymbol: NOK`, but their curated movements say `CURRENCY_USD`.

## Proposed Remediation

**Preferred**:
1. **Mapping** (`map_provider_transactions`): when scanning `transferItems`, choose as the movement's symbol the first **non-currency** instrument (prefer `assetType != CURRENCY`; fall back to `CURRENCY_USD` only if there is no other). At minimum, the decision must be deterministic and tested against the real shape (fees first). Also keep the list of involved symbols (e.g. `instruments: [...]`) so no legs are discarded.
2. **Filter** (`movement_involves_filter` + orchestrator): match `filter_symbol` against **all** the movement's instruments (M1/M2 on the curated symbol + M4 over `instruments[]`/`transferItems`), so a multi-leg trade with NOK in any leg matches. Document the new shape in data-model §2 and `docs/tools.md`.

**Alternatives**:
- Only (1): fixes the curated symbol of the simple trade, but multi-instrument spreads (e.g. roll NOK 260717→260821 at the same timestamp in separate transactions) would still show a single instrument per movement. Smaller contract change, partial solution.
- Expose only `extended` and let the agent filter client-side: already possible today, but it contradicts the `symbol` parameter contract and is fragile (the agent must know about the bug).

**Files likely to change**:
- `src/schwab_mcp/transactions.py` (`transferItems` mapping; filter and its invocation in the orchestrator)
- `tests/unit/test_transactions_live_response.py` (regression with the real shape: 4 non-None `CURRENCY_USD` fee legs first + OPTION leg last)
- `tests/unit/test_transactions_filter_query.py` (M4 / multi-instrument match)
- `docs/tools.md`, `specs/006-transaction-history/contracts/` (data-model §2: new match shape and/or `instruments` field)

**Tests to add or update**:
- Mapping regression: real transaction (non-None `CURRENCY_USD` fees first, option last) → `symbol` = option's OCC, `instrument_type = OPTION`, `underlying_symbol` = root.
- End-to-end regression: `get_transaction_history(symbol="NOK")` with that payload must return the movement (M2).
- Multi-leg: movement with two non-currency instruments → the filter matches if either matches.
- No breakage: a genuine cash movement (only `CURRENCY_USD`) is still curated the same way.

## Risks & Considerations

- Data-model contract change (§2 and `MovementEntry` schema) → update spec/contracts and budget tests (`tests/performance/test_transactions_budgets.py`).
- Trades already curated in previous outputs change shape: semantic breaking change for MCP consumers (document in CHANGELOG).
- `no_movements_for_instrument` will become reliable; today agents may have drawn false conclusions (it happened in this session: "you didn't trade NOK").

## Open Questions

- None blocking; the root cause is confirmed with live evidence.