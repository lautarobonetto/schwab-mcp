# Bug Fix: Index option contracts cannot be quoted (`get_quotes`)

- **Slug**: index-option-root-grammar
- **Fixed**: 2026-10-27
- **Assessment**: ./assessment.md
- **Status**: not-applied

## Summary

Investigation per the assessment's step 1 (pin provider evidence) **disproved
the root-cause hypothesis**: the grammar and the tool work correctly for
index option contracts. Every tested symbol used expiry `251127` — November
**2025**, an expired contract — instead of `261127` (November 2026). With the
correct date, `SPXW 261127C7725` and `XSP 261127C772` quote successfully end
to end, rewritten by the tool to the provider's exact canonical keys. No code
change was needed; the `$`-prefixed-root theory and the proposed grammar
extension are withdrawn.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `tmp/probe_index_option_symbols.py` | added (scratch, git-ignored) | one-call probe of 12 candidate canonical keys; all SPXW/XSP candidates missed (expired dates), AAPL control hit |
| `tmp/probe_chain_symbols.py` | added (scratch, git-ignored) | read the RAW option-chains response for `$SPX`/`$XSP` @ 2026-11-27; exposed the provider's real contract symbols |
| `tmp/probe_index_option_symbols.py`, `tmp/probe_chain_symbols.py` | removed after evidence captured | scratch only; results recorded below |
| — | **no source, test, or doc changes** | the code conforms to the contract; behavior verified correct |

## Diff Highlights (optional)

None — no production diff.

## Tests Added or Updated

None. The existing suites (`test_quotes_validation.py`,
`test_quotes_mapping.py`, `test_quotes_data_state.py`) already pin the
behavior that turned out to be correct: `$`-prefixed option roots are
`malformed_symbol` per the contract grammar, and compact spellings are
rewritten to canonical OCC form.

## Local Verification

**Probe 1 — direct client, one `quotes()` call, 12 candidates** (expired
dates `251127`):

- AAPL control `"AAPL  261127C00350000"` → HIT (last=9.63).
- All 11 SPXW/XSP candidates (roots `SPXW`, `$SPXW`, `$SPX`, `.SPXW`,
  `XSP`, `$XSP`, `.XSP`; padded and unpadded) → `errors.invalidSymbols`.

**Probe 2 — raw `option_chains()` response, `fromDate=toDate=2026-11-27`:**

- `$SPX` → `SPXW  261127C07720000`, `SPXW  261127C07725000`,
  `SPXW  261127C07730000`
- `$XSP` → `XSP   261127C00772000`, `XSP   261127C00773000`,
  `XSP   261127C00774000`

The provider's canonical form is exactly what the tool builds from the
compact spelling — root padded to six columns, `$` absent. The probes failed
only because `251127` selects a **2025** expiry.

**End-to-end via the MCP `get_quotes` tool (correct dates, live):**

- `SPXW 261127C7725` → `ok`; provider key `SPXW  261127C07725000`; curated
  quote: last 133.44, bid 132.70, ask 133.60, volume 150,
  `net_change` 19.54, `net_change_pct` 17.16, `data_state=realtime`,
  description "SPXW 11/27/2026 7725.00 C" (extended mode).
- `XSP 261127C772` → `ok`; curated `net_change` 1.995 (4-decimal option
  rounding preserved), `data_state=realtime`.

**Suite**: not run for a fix (no change); baseline was green in the converge
session (1263 passed, 0 skipped).

## Deviations from Assessment

1. **Root cause was wrong.** The assessment hypothesized a `$`-prefixed
   canonical root for index options excluded by `_OPTION_RE`. The raw chain
   evidence shows the provider's canonical key has **no `$`**
   (`SPXW  261127C07725000`) — precisely the form the tool already produces
   from `SPXW 261127C7725`. The actual cause of every `not_found` in the
   original manual session was input error: expiry `251127` is November
   2025 (expired), not 2026. Consequently the preferred remediation
   (grammar extension + fixtures + docs) was **not applied** — there is
   nothing to fix.
2. The `validation_error` for `$SPX 251127C7700` is correct behavior per
   `contracts/mcp-tools.md` §1 (option roots are `[A-Z0-9.]{1,6}`; `$` is
   the index-underlying prefix, not part of an option root). The assessment
   flagged this as a potential FR-013 gap; it is not.
3. One genuine (minor, doc-only) finding emerged: the quickstart example S2
   (`specs/010-real-time-quotes/quickstart.md:38`) uses
   `AAPL 251127C200` — a 2025 expiry — as its live example; run today it
   returns `not_found` and misleads validation sessions. Recommend updating
   the example date (e.g. `AAPL 261127C200`) in a docs-only change.

## Follow-ups

- Re-run `/speckit.bug.assess slug=index-option-root-grammar` (or close the
  bug) — the corrected verdict is **invalid / not a bug**: expected behavior
  confirmed by provider evidence; expired-symbol inputs correctly surface as
  `not_found` (spec edge case, second bullet of Edge Cases).
- Docs-only cleanup: refresh the stale `251127` example in
  `specs/010-real-time-quotes/quickstart.md` (and audit other artifacts for
  expired example dates, e.g. `data-model.md`'s `AAPL 251127C200`).
- Optional hardening (no bug): document in `docs/tools.md` that expired
  contracts return `quote_unavailable` / `not_found`, so agents can
  self-correct the year portion of a symbol before escalating.