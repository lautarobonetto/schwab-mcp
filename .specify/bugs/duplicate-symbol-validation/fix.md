# Bug Fix: Two symbol-validation grammars in the package (DRY)

- **Slug**: duplicate-symbol-validation
- **Fixed**: 2026-11-04
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

The symbol grammars moved from `quotes.py` into a new shared module
`src/schwab_mcp/symbols.py` (public names: `INDEX_RE`, `EQUITY_RE`,
`OPTION_RE`, `canonical_option_symbol()`, `classify_symbol()`), which is
now the package's single source of truth consumed by quotes, price
history, and the option tools. `OptionChainQuery.validate()` delegates
symbol validation to the shared grammar (via the new
`classify_underlying()` wrapper), so off-grammar symbols (`AAPL!`) and
option-contract symbols are rejected with an actionable `ValueError`
before any upcall instead of surfacing the provider's HTTP 400 as a
misleading `no_options_listed`.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/symbols.py` | added | Shared grammar module: public regexes + `classify_symbol()` (moved verbatim from quotes) + new `classify_underlying()` (slash-form and lowercase tolerant wrapper for underlyings). |
| `src/schwab_mcp/quotes.py` | modified | Grammar block removed; imports `classify_symbol` from `symbols`; unused `import re` dropped; pointer comment left in the constants section. |
| `src/schwab_mcp/price_history.py` | modified | Import path updated (`schwab_mcp.symbols` instead of `schwab_mcp.quotes`); module docstring now names the new owner. |
| `src/schwab_mcp/options_chain.py` | modified | `OptionChainQuery.validate()` calls `classify_underlying()` after the existing empty/whitespace checks; rejects off-grammar symbols and option-contract symbols with `ValueError` before any upcall. |
| `tests/unit/test_options_chain_validation.py` | added tests | New `TestSymbolGrammar` class (TDD red first, see below). |
| `tests/unit/test_quotes_validation.py` | modified | Class-share mapping test imports `classify_symbol` from `schwab_mcp.symbols`. |
| `docs/tools.md` | modified | Both chain tools' `symbol` rows replaced ("passed as-is" → shared grammar, slash/lowercase accepted); both validation-error tables gained the off-grammar and option-contract rows. |

## Diff Highlights

`options_chain.py` — the ad-hoc check is now on top of the shared grammar:

```python
classified = classify_underlying(self.symbol)
if classified is None:
    raise ValueError(
        "symbol matches no supported grammar "
        "(equity/ETF like AAPL or BRK.B, or index like $SPX "
        "— schwab_mcp.symbols.classify_underlying); "
        f"got {self.symbol!r}"
    )
if classified[0] == "option":
    raise ValueError(
        "symbol must be an underlying (equity/ETF or index), "
        "not an option contract — the chain endpoints serve "
        f"underlyings; got {self.symbol!r}"
    )
```

`symbols.py` — the tolerant wrapper that keeps every currently-working
chain symbol working:

```python
def classify_underlying(symbol: str) -> tuple[str, str] | None:
    return classify_symbol(symbol.replace("/", ".").upper())
```

## Tests Added or Updated

- `tests/unit/test_options_chain_validation.py::TestSymbolGrammar::test_symbol_off_grammar_rejected` (parametrized: `AAPL!`, `$BAD$`, `BRK.B.C`, `A#B`) — the bug regression: off-grammar symbols raise `ValueError` before any upcall. Written first and confirmed failing (`DID NOT RAISE`, 5 failed) before implementation.
- `...::test_symbol_slash_form_accepted` — `BRK/B` still passes (live probe 2026-11-02: provider resolves the slash form).
- `...::test_symbol_lowercase_accepted` — `"aapl"` still passes (case is the provider's job on the as-is chain path).
- `...::test_symbol_index_accepted` — `$SPX` matches the shared grammar.
- `...::test_symbol_option_contract_rejected` — option-contract symbols are rejected as non-underlyings with an actionable message.
- `tests/unit/test_quotes_validation.py` — class-share mapping test re-pointed to `symbols.classify_symbol` (same assertions).

## Local Verification

- Commands run:
  - `uv run pytest tests/unit/test_options_chain_validation.py -k TestSymbolGrammar -q` → **red**: 5 failed (rejections), 3 passed (acceptances), before the fix.
  - `uv run pytest tests/unit/test_options_chain_validation.py -q` → 34 passed (green).
  - `uv run pytest -q` → **1819 passed, 0 skipped** (full suite, commit gate met).
- Manual checks: `grep` for stale references (`_classify`, `_canonical_option_symbol`, `_INDEX_RE`, `_EQUITY_RE`) across `src/` and `tests/` — only the unrelated `transactions._classify_connectivity_cause` remains (connectivity taxonomy, not symbol grammar).

## Deviations from Assessment

- **`classify_underlying()` uppercases the input before classifying.** The assessment proposed only slash→dot normalization; case tolerance was added because the chain endpoints pass `symbol` to the provider as-is, so lowercase input (`"aapl"`) worked before the fix and must keep working (risk "behavior tightening" from the assessment). Pinned by `test_symbol_lowercase_accepted`.
- **Option-contract symbols are explicitly rejected on the chain path** (kind `option` → `ValueError`). The assessment said "reject malformed_symbol-shaped input" without naming option-kind symbols; this follows the `price_history` precedent (D9: the endpoint serves underlyings) and closes the same misleading-`no_options_listed` hole for option-shaped symbols. Pinned by `test_symbol_option_contract_rejected`.
- **`symbols.py` chosen over public names in `quotes.py`.** The assessment left the module decision open, noting the third-consumer trigger; with quotes, price_history, and options_chain all consuming, the dedicated module is the cleaner cut (and matches the original TD-009 suggestion).

## Follow-ups

- **Quotes slash-form acceptance** (assessment open question): `get_quotes` still rejects `"BRK/B"` while the chain tools accept it — deliberate per the quotes contract ("agents never send the slash form themselves", docs line ~699), but worth a deliberate decision if agents ever echo slash forms into quotes.
- **Commit**: constitution gate requires the full suite green (met) with docs in the same commit — commit `src/schwab_mcp/{symbols,quotes,price_history,options_chain}.py`, the two test files, `docs/tools.md`, and `.specify/bugs/duplicate-symbol-validation/` together.
- Optional: if a fourth symbol consumer appears, consider re-homing the grammar doc table from `docs/tools.md` §quotes into the `symbols.py` module docstring to keep one narrative.