# Bug Assessment: Two symbol-validation grammars in the package (DRY)

- **Slug**: duplicate-symbol-validation
- **Created**: 2026-11-04
- **Source**: pasted text (internal tech-debt report TD-009)
- **Verdict**: valid
- **Severity**: medium

## Report (verbatim or summarized)

TD-009 — Two symbol-validation grammars in the package (DRY).

**Area:** `quotes.py` (declared single source of truth, used by
`price_history.py:486-524`) vs `options_chain.py:196-215`.

`options_chain` validates symbols with its own ad-hoc check:

```python
if self.symbol.strip() != self.symbol or any(ch.isspace() for ch in self.symbol):
```

Two definitions of "valid symbol" coexist: `options_chain` would accept
e.g. `"BRK/B"` without the equity/index shape analysis that
`quotes._classify` performs.

**Refactor:** extract symbol validation into a shared helper (in
`quotes.py` or a `symbols.py`) returning `(kind, provider_form)` or an
error; `OptionChainQuery.validate()` calls it, keeping only its
contract-specific error messages on top of the single grammar.

## Symptom

Two independent definitions of "valid symbol" coexist in `src/schwab_mcp/`:
`quotes._classify` (regex grammars for index / option / equity kinds, with
provider-form rewriting) and `OptionChainQuery.validate()` (a hand-rolled
"non-empty, no internal whitespace" check that passes the symbol to the
provider as-is). The expected behavior, per the project constitution
(DRY — one implementation per piece of knowledge) and per
`price_history.py` (which already reuses `quotes._classify` as "single
source of truth"), is a single shared symbol grammar.

The divergence is observable, not just stylistic:

- `get_option_chain(symbol="AAPL!")` passes local validation and reaches
  the provider, which answers HTTP 400 → the tool reports
  `no_options_listed` ("the underlying has no listed options") for a
  symbol that is simply malformed — a misleading, wrong-detail result.
- `get_option_chain(symbol="BRK/B")` is accepted locally, while
  `get_quotes(symbols=["BRK/B"])` rejects the same string as
  `malformed_symbol` (the equity grammar `[A-Z0-9.]` has no `/`; quotes
  only rewrites dot→slash on the way *out*). One package, two answers.

## Reproduction

1. Call `get_option_chain` with `symbol="AAPL!"` (or any non-whitespace
   string outside the quotes grammars). Local validation passes; the
   provider 400 is mapped to the `no_options_listed` outcome.
2. Call `get_quotes` with `symbols=["AAPL!"]`. It returns
   `validation_error / malformed_symbol` before any upcall.
3. Call `get_option_chain(symbol="BRK/B")` (accepted, provider resolves
   it) vs `get_quotes(symbols=["BRK/B"])` (rejected as
   `malformed_symbol`).

[NEEDS CLARIFICATION: step 1's exact provider behavior for `AAPL!` is
inferred from the documented HTTP-400 "no options listed" mapping
(`_is_no_options_response`), not captured in a fixture; a live probe or
a fake-client test would pin it.]

## Suspected Code Paths

- `src/schwab_mcp/quotes.py:61-70` — the regex grammars
  (`_INDEX_RE`, `_EQUITY_RE`, `_OPTION_RE`).
- `src/schwab_mcp/quotes.py:97-124` — `_classify()` returning
  `(kind, provider_form)` or `None`; declared single source of truth.
- `src/schwab_mcp/options_chain.py:196-215` —
  `OptionChainQuery.validate()`'s ad-hoc symbol check (non-empty, no
  internal whitespace, passed as-is to the provider).
- `src/schwab_mcp/price_history.py:43,462-494` — the correct precedent:
  imports `_classify`/`_OPTION_RE` from `quotes` and reuses them.
- `tests/unit/test_options_chain_validation.py:154-174` — pins the
  current ad-hoc contract ("passed as-is to the provider"); must be
  revisited by the fix.
- `tests/unit/test_quotes_validation.py:177-203` — pins
  `_classify("BRK.B") == ("equity", "BRK/B")`.
- `docs/tools.md:684-696, 837-851` — documents the quotes /
  price-history grammars; the option-chain sections document the looser
  "as-is" contract.

## Root Cause Hypothesis

High confidence. `OptionChainQuery.validate()` was written before (or
independently of) the quotes symbol grammar and never consolidated.
`price_history` later reused `quotes._classify` (comment at
`price_history.py:18` explicitly calls it the "single source of truth"),
leaving `options_chain` as the only tool with a private grammar. The
option tools' looser check is arguably deliberate for pass-through
symbols like `BRK/B`, but that intent lives only in a test docstring —
not in a shared, documented grammar — so the package now has two
contradictory answers to "is this a valid symbol", and malformed symbols
on the chain path surface as misleading `no_options_listed` outcomes.

## Proposed Remediation

**Preferred**: promote the symbol grammar to a true single source of
truth and make the option tools consume it. Concretely:

1. Extract the grammar into a shared module — either keep it in
   `quotes.py` (matches the existing `price_history` import precedent
   and avoids churn) or create `src/schwab_mcp/symbols.py` with
   `classify_symbol(symbol: str) -> tuple[str, str] | None` plus the
   compiled regexes (public names, no `_` prefix). Re-export from
   `quotes.py` if keeping the module, or update `price_history`'s
   import if moving. KISS favors leaving them in `quotes.py` with
   public names unless a third consumer appears.
2. In `OptionChainQuery.validate()`, replace the whitespace-only symbol
   check with a call to the shared classifier: reject
   `malformed_symbol`-shaped input with a `ValueError` whose message
   quotes the shared grammar, while keeping the existing
   type/whitespace error messages for empty/whitespace input (the
   contract-specific wording stays on top of the single grammar, per
   the report).
3. Accept the provider-internal slash form on the chain path: classify
   `symbol` after normalizing `/` → `.` (or extend the equity grammar
   to accept one `/`), so `"BRK/B"` — which the provider demonstrably
   resolves — keeps passing, and the quotes-vs-chain inconsistency on
   `BRK/B` is resolved deliberately rather than by tightening blindly.
4. Update `docs/tools.md` option-chain/expiration sections to reference
   the shared grammar instead of the "passed as-is" wording, and fold
   the change into the same commit (constitution gate).

**Alternatives**:

- Keep the loose check and only add a shared `is_valid_symbol()`
  boolean wrapper: smallest diff, but it preserves two grammars in
  spirit and does not fix the misleading `no_options_listed` detail for
  malformed symbols — fails the DRY intent of TD-009.
- Tighten `validate()` to `_classify` with no slash tolerance: simplest
  grammar unification, but breaks `get_option_chain("BRK/B")`, which
  currently works against the live provider — a regression.

**Files likely to change**:

- `src/schwab_mcp/quotes.py` (or new `src/schwab_mcp/symbols.py`)
- `src/schwab_mcp/options_chain.py` (`OptionChainQuery.validate()`)
- `src/schwab_mcp/price_history.py` (import path, only if moving to
  `symbols.py`)
- `tests/unit/test_options_chain_validation.py`,
  `tests/unit/test_quotes_validation.py`,
  `tests/unit/test_price_history_validation.py`
- `docs/tools.md`

**Tests to add or update**:

- Update the options-chain validation tests that pin the "passed
  as-is" contract: `"AAPL!"` (and similar off-grammar symbols) must now
  raise `ValueError` before any upcall.
- Add a test that `get_option_chain("BRK/B")` still passes local
  validation (slash-form tolerance) and that
  `OptionChainQuery(symbol="BRK/B").validate()` does not raise.
- Add a test that empty/whitespace symbols keep the existing
  contract-specific error messages (no regression on wording).
- Add a test that `price_history` classification still behaves
  identically after any import-path move (existing suite likely covers
  this; verify no skip).

## Risks & Considerations

- **Behavior tightening on the chain tools**: any symbol currently
  accepted by the loose check but outside the shared grammar would
  start failing locally. Sweep existing callers/tests for symbols that
  rely on pass-through (e.g. non-US underlyings) before merging.
- **Slash-form equity symbols**: quotes rejects `BRK/B` while the
  provider accepts it — decide deliberately whether the shared grammar
  owns slash acceptance (and whether `get_quotes` should also accept
  it) or whether normalization `/`→`.` happens per tool. Fixing only
  the chain side leaves the quotes inconsistency.
- **Error-message contracts**: options-chain validation messages are
  pinned by tests and quoted in the data-model docs; keep the exact
  wording for empty/whitespace and add a distinct message for
  off-grammar symbols.
- **Constitution gates**: mandatory TDD (failing test first for the
  `AAPL!` regression), docs updated in the same commit, full suite
  green with no skipped tests.
- Not urgent: no data corruption or auth risk; impact is misleading
  error detail and grammar drift.

## Open Questions

- [NEEDS CLARIFICATION: should the shared grammar accept the
  provider-internal slash form (`BRK/B`) everywhere, including
  `get_quotes`, or should each tool normalize `/`→`.` before classifying?]
- [NEEDS CLARIFICATION: preferred module — public names in `quotes.py`
  (KISS, matches `price_history` precedent) vs a new `symbols.py`
  (cleaner layering if more tools adopt it later).]