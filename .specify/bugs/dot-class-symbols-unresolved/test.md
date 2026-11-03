# Bug Verification: Class-share symbols (embedded dot) never resolve at the provider

- **Slug**: dot-class-symbols-unresolved
- **Tested**: 2026-11-03
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The original symptom no longer reproduces: all four previously-failing
class-share symbols now return `ok` with candles/quotes, the dotted
echo semantics hold, and the negative controls (`BRK-B`, `A.B.C`) still
reject at validation. The full regression suite (1579 tests) passes
with 0 skipped; no regressions found.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | `uv run python tmp/verify_post_fix_repro.py` — assessment steps 1–6 against the real provider with the fixed code | pass | All 4 symbols `ok` with candles; quotes `realtime`; controls intact |
| New / updated tests | `uv run pytest tests/unit/test_quotes_validation.py::TestAcceptedSymbolKinds tests/unit/test_price_history_validation.py::TestAcceptedSymbolKinds -v` | pass | 19 passed, incl. the 3 fix-pinning tests |
| Regression suite | `uv run pytest -q` | pass | **1579 passed, 0 skipped** (project commit gate) |
| Lint / type-check | — | not-run | No lint/type-check configured in `pyproject.toml`; CI gate is `uv sync && uv run pytest` |
| MCP transport check | `tools.schwab.get_price_history({symbol: "BRK.B"})` + full step matrix via the session's MCP tools (server restarted post-fix) | pass | All steps pass at the MCP tool boundary; quotes entry: `{"BRK.B": {last: 556.88, bid: 556.3, ask: 556.98, data_state: "realtime"}}` with dotted display key |

## Output Excerpts

Post-fix reproduction (real provider client, fixed code):

```json
{
  "step1_brk_b_daily_1m":   {"outcome": "ok", "echo": "BRK.B", "candles": 23, "last_close": 542.49},
  "step2_brk_b_weekly_1y":  {"outcome": "ok", "candles": 52},
  "step3_hei_a":            {"outcome": "ok", "candles": 23},
  "step3_bf_b":             {"outcome": "ok", "candles": 23},
  "step3_len_b":            {"outcome": "ok", "candles": 23},
  "step4_control_tsla":     {"outcome": "ok", "candles": 66},
  "step5_quotes_brk_b":     {"outcome": "ok", "detail": "quotes_retrieved", "display_key": "BRK.B", "last": 556.88, "data_state": "realtime"},
  "step6_brk_dash_still_malformed": {"outcome": "validation_error", "detail": "malformed_symbol"},
  "step6_abc_still_malformed":      {"outcome": "validation_error", "detail": "malformed_symbol"},
  "echo_lowercase_input":   {"outcome": "ok", "echo": "BRK.B"}
}
```

Test runs:

```
19 passed in 0.06s   (isolated symbol-grammar suites)
1579 passed in 35.73s (full suite, 0 skipped)
```

## Residual Risks

- The provider-form mapping was confirmed by live probe on 2026-11-02/03
  for four symbols; if the provider ever changes its class-share
  format, the mapping (one `str.replace` in `_classify`) would need
  re-verification — the new unit tests pin the current expectation.
- The unrelated finding of the same exploration session (260-candle
  ceiling exceeded with `extended_hours=true`) remains open and is not
  covered by this verification.

## Recommendation

Close the bug — verified end-to-end at both the function level and the
MCP tool boundary (server restarted with the fix): the symptom no
longer reproduces, negative controls hold, and the full suite is green
with 0 skipped. Include the updated `docs/tools.md` + spec contracts in
the same commit (constitution gate).