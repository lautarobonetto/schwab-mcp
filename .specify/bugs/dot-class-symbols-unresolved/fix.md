# Bug Fix: Class-share symbols (embedded dot) never resolve at the provider

- **Slug**: dot-class-symbols-unresolved
- **Fixed**: 2026-11-03
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Class-share equities (`BRK.B`, `HEI.A`, …) now resolve at the provider:
`_classify` translates the dotted agent-facing form to the provider's
slash form (`BRK.B` → `BRK/B`), `get_price_history` sends the provider
form at its upcall (it previously ignored the tuple element), and
`get_quotes` inherits the mapping through its existing `provider_forms`
plumbing. Envelopes, echoes, and error keys keep the requested dotted
form.

## Evidence that determined the fix (assessment's open question resolved)

Controlled live probe (2026-11-03, scripts in `tmp/probe_class_share_forms.py`
and `tmp/probe_confirm_slash.py`, read-only market-data calls):

| Form | price_history | quote |
|------|---------------|-------|
| `BRK/B` | 23 candles, last_close 542.49, `empty=false` | last 556.87 |
| `HEI/A`, `BF/B`, `LEN/B` | 23 candles each | — |
| `BRK-B`, `BRK B`, `brk.b`, `BRK  B` | 0 candles, `empty=true` | errors |
| `BRK.B` (control) | 0 candles | `not_found` |

Conclusion: the provider resolves class shares **only in slash form**
(`.` → `/`), matching the assessment's preferred remediation.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/quotes.py` | modified | `_classify` equity branch returns the slash provider form for dot symbols (`symbol.replace(".", "/")`); docstring updated. Single source of truth — quotes inherits via its existing `provider_forms` upcall. |
| `src/schwab_mcp/price_history.py` | modified | Uses the `provider_form` element of the `_classify` tuple (`kind, provider_form = classified`) and sends it to `client.price_history`; echo/audit events keep `normalized` (dotted). |
| `docs/tools.md` | modified | Provider-form note added to both symbol-grammar sections (quotes §"Symbol-kind grammars" and price history §"Symbol-kind grammars"). |
| `specs/010-real-time-quotes/contracts/mcp-tools.md` | modified | Contract note: slash-form upcall translation, dotted display/error keys. |
| `specs/011-price-history-ohlcv/contracts/mcp-tools.md` | modified | Same contract note. |
| `tests/unit/test_quotes_validation.py` | modified + added test | `class-shares` parametrize case now pins `["BRK/B"]` at the quotes upcall; new `_classify` mapping test. |
| `tests/unit/test_price_history_validation.py` | added test | Upcall carries `BRK/B`, envelope echoes `BRK.B`. |

## Diff Highlights

`src/schwab_mcp/quotes.py` (`_classify`, equity branch):

```python
if _EQUITY_RE.match(symbol) and symbol.count(".") <= 1:
    # Class shares (embedded dot) resolve at the provider ONLY in the
    # slash form (live probe 2026-11-02 ...). The agent-facing echo
    # stays the dotted request form; this translation is provider-internal.
    return "equity", symbol.replace(".", "/")
```

`src/schwab_mcp/price_history.py` (upcall):

```python
kind, provider_form = classified
...
response = retry_call(
    client.price_history,
    0,
    provider_form,          # was: normalized (dotted form, not resolved)
```

## Tests Added or Updated

- `tests/unit/test_quotes_validation.py::TestAcceptedSymbolKinds::test_equity_index_spells_normalized[class-shares]` — quotes upcall receives `["BRK/B"]` for request `BRK.B` (pin updated from `["BRK.B"]`).
- `tests/unit/test_quotes_validation.py::TestAcceptedSymbolKinds::test_class_share_classified_to_slash_provider_form` — `_classify("BRK.B") == ("equity", "BRK/B")`, `_classify("HEI.A") == ("equity", "HEI/A")`; dotless equities and indexes pass through unchanged.
- `tests/unit/test_price_history_validation.py::TestAcceptedSymbolKinds::test_class_share_upcall_translated_echo_preserved` — provider call carries `BRK/B`, envelope echo stays `BRK.B`, exactly one upcall.

## Local Verification

- Commands run: `uv run pytest tests/unit/test_quotes_validation.py tests/unit/test_price_history_validation.py -q` → RED first (3 failing as intended), then **189 passed**.
- Commands run: `uv run pytest -q` (full suite, commit gate) → **1579 passed, 0 skipped**.
- Live manual checks (real provider client, new code): `get_price_history("BRK.B")` → `ok`, echo `BRK.B`, 23 candles, last close 542.49; `get_price_history("HEI.A")` → `ok`, 23 candles; `get_quotes(["BRK.B"])` → `ok`, `{"BRK.B": {last: 556.88, bid/ask/volume present, data_state: "realtime"}}` with dotted display key.
- Note: the MCP server process of the current session still serves the pre-fix code (persistent stdio process); the live checks above exercise the exact fixed functions with the real provider client. Restart the MCP server (or reopen the session) for the tools to pick up the fix.

## Deviations from Assessment

- None in substance. The assessment's open question (provider form)
  was resolved exactly as the preferred remediation anticipated:
  `BRK/B` slash form, confirmed by probe for all four failing symbols.
- Minor scope note: `get_quotes` needed no code change (its upcall
  already used `provider_forms`); only its test pin and the contract
  docs were updated.

## Follow-ups

- Restart/reconnect the MCP server session so `get_price_history` and
  `get_quotes` serve the translated form.
- Commit with the affected documentation included (constitution gate):
  code + tests + `docs/tools.md` + both spec contracts.
- `tmp/probe_class_share_forms.py` and `tmp/probe_confirm_slash.py`
  document the provider-form evidence (git-ignored scratch; keep or
  delete freely).
- Unrelated finding from the same exploration session (260-candle
  ceiling exceeded with `extended_hours=true`) is **not** covered here —
  it warrants its own assessment (`/speckit.bug.assess`).