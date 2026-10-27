# Bug Assessment: "Index option contracts cannot be quoted (`get_quotes`)" — re-triage

- **Slug**: index-option-root-grammar
- **Created**: 2026-10-27 (supersedes the original 2026-10-27 assessment after
  the fix investigation disproved its root-cause hypothesis; overwrite
  confirmed by the user)
- **Source**: pasted text — manual live-testing session of `get_quotes`
  (feature 010) plus the provider evidence captured during
  `/speckit.bug.fix` (see `./fix.md`).
- **Verdict**: invalid — not a bug
- **Severity**: low (residual value is a docs-only cleanup)

## Report (verbatim or summarized)

Original report: during manual live validation, option contracts on index
underlyings could not be quoted by any spelling the tool accepts —
`$SPX 251127C7700` → `validation_error`/`malformed_symbol`; every expressible
root (`SPX`, `SPXW`, `.SPX`, `.SPXW`, `XSP`) with strike 7700/7725 →
`quote_unavailable`/`not_found`. Control `AAPL 261127C350` → `ok`.

The fix investigation (`./fix.md`) then established, with raw provider
evidence, that the tested expiry was wrong, not the tool:

- Probe of the raw `option_chains()` response for `2026-11-27`:
  `$SPX` contracts are `SPXW  261127C07720000`, `SPXW  261127C07725000`,
  `SPXW  261127C07730000`; `$XSP` contracts are `XSP   261127C00772000`,
  etc. The canonical root carries **no `$`** — exactly the form the tool
  already builds from the compact spelling.
- End-to-end with correct dates, via the MCP tool:
  `SPXW 261127C7725` → `ok` (provider key `SPXW  261127C07725000`, curated
  quote complete, `data_state=realtime`); `XSP 261127C772` → `ok` (4-decimal
  option rounding preserved).

## Symptom

None remains. The original "symptom" was caused by inputs selecting expired
contracts: `251127` is the YYMMDD for November **2025**, not 2026. The tool
behaves exactly as specified: expired/unlisted contracts surface as
`quote_unavailable`/`not_found` (a spec edge case), and option roots without
`$` are validated per the contract grammar (`$` is the index-underlying
prefix, never part of an option root).

## Reproduction

The original failure reproduces only with expired inputs:

1. Invoke `get_quotes` with `{"symbols": "SPXW 251127C7725"}` (Nov 2025
   expiry) → `quote_unavailable`, `errors["SPXW 251127C7725"] = "not_found"`
   — correct: the contract expired.
2. Invoke with `{"symbols": "SPXW 261127C7725"}` (Nov 2026 expiry) → `ok`;
   extended mode shows the provider key `SPXW  261127C07725000`.
3. Invoke with `{"symbols": "$SPX 261127C7700"}` → `validation_error`
   naming the symbol `malformed_symbol` — correct per
   `contracts/mcp-tools.md` §1 (root grammar excludes `$`).

## Suspected Code Paths

No code defect. For completeness, the paths that were audited and confirmed
correct:

- `src/schwab_mcp/quotes.py:62-65` (`_OPTION_RE`) — root class
  `[A-Z0-9.]{1,6}` matches the provider's canonical root form
  (verified against raw chain symbols, no `$` present).
- `src/schwab_mcp/quotes.py:73-89` (`_canonical_option_symbol`) — produces
  `f"{root:<6}{date}{cp}{encoded:08d}"`, byte-identical to the keys the
  provider returns for live index options.
- `specs/010-real-time-quotes/contracts/mcp-tools.md:22` — the normative
  grammar is consistent with provider reality.

## Root Cause Hypothesis

The original observation was an input error (expiry year `25` instead of
`26` in the YYMMDD portion), amplified by a stale example in the feature's
own artifacts: `specs/010-real-time-quotes/quickstart.md:38` (scenario S2)
uses `AAPL 251127C200` — a November-2025 expiry — as its live example, and
`data-model.md` shows `AAPL 251127C200` too, so validation sessions copy the
stale date and read the resulting `not_found` as a tool defect. Confidence:
**high** — proven by direct provider evidence and end-to-end success with
corrected dates.

## Proposed Remediation

**Preferred**: docs-only cleanup, no code change.

1. Update the stale example dates in the feature artifacts:
   `AAPL 251127C200` → `AAPL 261127C200` in
   `specs/010-real-time-quotes/quickstart.md` (S2) and
   `specs/010-real-time-quotes/data-model.md` (curated envelope example).
2. Add one sentence to `docs/tools.md` (`get_quotes` section): expired or
   not-listed contracts return `quote_unavailable` with
   `errors[symbol] = "not_found"` — agents should verify the date portion of
   a contract symbol before escalating a missing quote.

**Alternatives**:
- None needed. No code or test change is justified: the existing suites
  already pin the correct behavior, and adding an "expired contract" fixture
  would test provider absence, not tool logic (the `not_found` path is
  already covered by the unknown-symbol tests).

**Files likely to change**:
- `specs/010-real-time-quotes/quickstart.md`
- `specs/010-real-time-quotes/data-model.md`
- `docs/tools.md`

**Tests to add or update**:
- None (behavior already covered; see above).

## Risks & Considerations

- Doc-only change; no runtime, API, security, or performance risk.
- Stale dates recur naturally over time — examples pinned to concrete dates
  expire; a dated example is unavoidable, but using the current-year form
  (26xxxx) delays recurrence.

## Open Questions

- None.