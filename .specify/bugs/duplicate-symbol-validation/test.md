# Bug Verification: Two symbol-validation grammars in the package (DRY)

- **Slug**: duplicate-symbol-validation
- **Tested**: 2026-11-04
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The bug no longer reproduces: off-grammar symbols (`AAPL!`, `$BAD$`,
`BRK.B.C`, `A#B`) and option-contract symbols are now rejected with an
actionable `ValueError` by `get_option_chain` before any provider
upcall, while `BRK/B`, lowercase, and index symbols keep passing. The
full suite is green (1819 passed, 0 skipped); no regressions found.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | `uv run python` script exercising the assessment's 3 steps against a call-recording stub client | pass | Steps 1–3 of assessment reproduction, automated equivalent. Any provider upcall would have raised `AssertionError` — none did. |
| — step 1: `get_option_chain("AAPL!")` + off-grammar variants | raises `ValueError` naming the grammar | pass | Was: local validation passed, provider HTTP 400 surfaced as misleading `no_options_listed`. |
| — step 1b: option-contract symbol as underlying | raises `ValueError` naming `underlying` | pass | `AAPL240119C00195000` rejected pre-upcall. |
| — step 3: `BRK/B` / `"aapl"` / `$SPX` on the chain path | `OptionChainQuery.validate()` returns `None` | pass | Slash-form and case tolerance preserved (regression guard). |
| — step 2: `get_quotes(["AAPL!"])` | returns `validation_error` / `malformed_symbol` | pass | Unchanged, as documented. |
| New / updated tests | `uv run pytest tests/unit/test_options_chain_validation.py tests/unit/test_quotes_validation.py tests/unit/test_price_history_validation.py -q` | pass | 223 passed — includes the TDD-red `TestSymbolGrammar` tests from fix.md. |
| Regression suite | `uv run pytest -q` | pass | 1819 passed in 33.17s, 0 skipped (constitution commit gate). |
| Lint / type-check | — | not-run | No lint or type-check tool is configured in `pyproject.toml`. |

## Output Excerpts

Reproduction script (stub client, zero upcalls):

```
pass: 'AAPL!' -> ValueError before any upcall: symbol matches no supported grammar (equity/ETF like AAPL or...
pass: option contract -> ValueError: symbol must be an underlying (equity/ETF or index), not an o...
pass: BRK/B, aapl, $SPX still accepted by OptionChainQuery.validate()
pass: get_quotes(['AAPL!']) -> validation_error/malformed_symbol (unchanged)
```

Suites:

```
tests/unit/test_options_chain_validation.py tests/unit/test_quotes_validation.py tests/unit/test_price_history_validation.py
223 passed in 0.51s

uv run pytest -q
1819 passed in 33.17s
```

## Residual Risks

- **Quotes slash-form inconsistency remains by design**: `get_quotes(["BRK/B"])` still returns `malformed_symbol` while the chain tools accept it (quotes contract: "agents never send the slash form themselves"). This was the assessment's open question, deliberately out of fix scope — recorded as a follow-up in fix.md.
- **No live-provider probe**: the pre-upcall validation boundary is deterministic and covered by unit tests; the assessment's `[NEEDS CLARIFICATION]` about the provider's exact HTTP-400 behavior for off-grammar symbols was never live-probed, but it is now unreachable through the tool surface (rejected locally first).
- **No lint/type-check gate**: the project configures none, so import hygiene (e.g. the removed `import re` in quotes.py) was only exercised by the suite, not a static checker.

## Recommendation

Close the bug — verified. The original symptom (misleading
`no_options_listed` for off-grammar chain symbols; two contradictory
symbol grammars) is gone, the grammar now has one home
(`schwab_mcp.symbols`) consumed by all three domains, the full suite is
green, and the only residual is the documented, deliberate quotes
slash-form contract. Commit per the constitution gate (code + tests +
docs + `.specify/bugs/duplicate-symbol-validation/` in one commit).