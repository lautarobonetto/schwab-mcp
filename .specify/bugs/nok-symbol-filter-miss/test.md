# Bug Verification: `get_transaction_history` curated every trade as `CURRENCY_USD`

- **Slug**: nok-symbol-filter-miss
- **Tested**: 2026-10-24
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The original symptom no longer reproduces: the exact query from the report (`start_date=2026-04-23, end_date=2026-10-23, symbol="NOK"`) executed live against the real API with the corrected code returns the period's **14 NOK options legs** (pre-fix: `ok / no_movements_for_instrument` with 0 records). All legs curate with the correct OCC and `underlying_symbol=NOK`; the unfiltered control remains at 173 movements (no regression in data volume).

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | `uv run python tmp/live_check_nok.py` (one-off read-only script with the real client + stored tokens; runs the exact query from the assessment with pagination) | **pass** | 14 NOK movements returned (pre-fix: 0); the user's consent was granted for this network verification |
| Reproduction (pre-fix baseline) | Same query via MCP in the session (old code loaded in the server process) | pass (baseline) | Confirmed the original symptom (`ok / no_movements_for_instrument`, total=0) — baseline obtained before the fix |
| New / updated tests | `uv run pytest tests/unit/test_transactions_live_response.py -q` | pass | 20 passed — includes the `1c. Multi-leg trade shape` section (5 regression tests) |
| Regression suite | `uv run pytest -q` | pass | **842 passed, 0 skipped, 0 failed** (constitution commit gate) |
| Lint / type-check | — | not-run | No lint/type-check tooling configured in `pyproject.toml` |
| Unfiltered control (same window) | `get_transaction_history(client, "2026-04-23", "2026-10-23")` in the live script | pass | total=173, identical to the pre-fix sweep — the fix did not alter the volume of fetched movements |

## Output Excerpts

Live post-fix reproduction (`symbol=NOK`, 6-month window):

```
page offset=0: outcome=TransactionOutcome.ok detail=TransactionDetail.history_retrieved total=14 returned=14

NOK movements retrieved: 14
  2026-05-05T15:43:38+0000  trade  NOK   260618P00012000  type=OPTION  underlying=NOK
  2026-05-06T14:19:44+0000  trade  NOK   260618P00012000  type=OPTION  underlying=NOK
  2026-06-02T13:48:48+0000  trade  NOK   260717P00014000  type=OPTION  underlying=NOK
  2026-06-05T18:59:46+0000  trade  NOK   260821P00013000  type=OPTION  underlying=NOK   (×3)
  2026-06-05T18:59:46+0000  trade  NOK   260717P00014000  type=OPTION  underlying=NOK   (×3)
  2026-06-24T19:08:58+0000  trade  NOK   260821P00013000  type=OPTION  underlying=NOK
  2026-06-24T19:08:58+0000  trade  NOK   261218P00011000  type=OPTION  underlying=NOK
  2026-08-27T13:31:07+0000  trade  NOK   261218P00011000  type=OPTION  underlying=NOK

control unfiltered: outcome=TransactionOutcome.ok total=173
```

The 14 legs match 1:1 with those identified in the assessment via `extended.transferItems` (dates, contracts, quantities), confirming that the fix recovers exactly the movements the bug was hiding.

## Residual Risks

- **Stale MCP server process**: the running `schwab-mcp` server still has the pre-fix code loaded; the MCP tools in this session will keep showing the bug until it is restarted (`uv run schwab-mcp serve`). The live verification was executed in-process with the corrected code, so the result is valid.
- **Transactions with multiple non-currency instruments**: out of scope by documented decision (fix.md, Deviations) — 0 cases among 173 live movements; if they appear (e.g. RECEIVE_AND_DELIVER assignments), only the first non-currency leg will be curated.
- **Empty description in trades**: real trades do not carry a transaction-level `description`; the fix does not derive it from the instrument (follow-up recorded).
- **Verification script**: `tmp/live_check_nok.py` remains in `tmp/` (git-ignored) as a verification artifact; it is re-runnable and read-only.

## Recommendation

Close the bug — verified end-to-end: the original reproduction from the assessment was exercised live against the real provider with the corrected code and the symptom disappeared (14/14 NOK legs recovered), the full suite is green, and the data volume of the unfiltered sweep did not change. Single remaining operational step: restart the MCP server process so the served tools use the corrected code.