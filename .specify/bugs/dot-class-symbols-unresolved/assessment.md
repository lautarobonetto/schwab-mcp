# Bug Assessment: Class-share symbols (embedded dot) never resolve at the provider

- **Slug**: dot-class-symbols-unresolved
- **Created**: 2026-11-02
- **Source**: pasted text (hallazgo 2 of a live MCP tool-exploration session; verbatim excerpt below)
- **Verdict**: valid
- **Severity**: medium

## Report (verbatim or summarized)

> **Hallazgo 2: símbolos de clase (con punto) nunca resuelven.**
>
> | Símbolo | price_history | get_quotes |
> |---|---|---|
> | `BRK.B` | `history_unavailable` (diario y semanal, con retry) | `not_found` |
> | `HEI.A` / `BF.B` / `LEN.B` | `history_unavailable` | — |
> | `BRK-B` (control) | `malformed_symbol` (gramática local lo rechaza) | `malformed_symbol` |
>
> Es **sistemático, no puntual**: la gramática `[A-Z0-9.]{1,6}` los acepta
> (BRK.B es ejemplo normativo del contrato y está en los tests
> unitarios), pero el proveedor no resuelve ninguno con punto, y la
> gramática local bloquea la variante con guión. Resultado: **es
> imposible consultar class shares** por esta vía. Falta un mapeo de
> formato de símbolo hacia lo que Schwab espera, o la gramática está
> desalineada con el proveedor.

Context: gathered live against the running provider on 2026-11-02
(Sunday, market closed — all responses final, no in-progress candles).
Controls in the same batch: `TSLA` daily 3m → `ok` (66 candles), `SPY`
and `$SPX`/`$VIX` variants → `ok`. Normalization works: input
`brk.b` echoes `BRK.B` and still fails at the provider.

## Symptom

Equity/ETF symbols with an embedded dot denoting share class
(`BRK.B`, `HEI.A`, `BF.B`, `LEN.B`) pass local validation (the grammar
explicitly allows one embedded dot and is documented with `BRK.B` as
the normative example), but the provider never resolves them:
`get_price_history` returns `history_unavailable` /
`source_returned_no_candles` and `get_quotes` returns
`errors: {"BRK.B": "not_found"}`. The hyphen variant (`BRK-B`) is
rejected at validation, so there is **no** input form that reaches the
provider for class shares. Expected: class shares resolve to candles
and quotes like any other equity.

## Reproduction

1. `get_price_history({"symbol": "BRK.B", "frequency": "daily", "period": "1m"})` → `outcome: history_unavailable`, `detail: source_returned_no_candles`, `symbol: BRK.B`.
2. Repeat with `frequency: "weekly", "period": "1y"` → same failure (rules out a period-specific quirk).
3. Repeat with `HEI.A`, `BF.B`, `LEN.B` (daily 1m) → all `history_unavailable`.
4. Control: `get_price_history({"symbol": "TSLA", "frequency": "daily", "period": "3m"})` → `ok`, 66 candles (same session, same channel).
5. `get_quotes({"symbols": ["BRK.B"]})` → `quote_unavailable / source_could_not_quote_all_symbols`, `errors: {"BRK.B": "not_found"}`.
6. `get_price_history({"symbol": "BRK-B"})` (and quotes) → `validation_error / malformed_symbol` — the only other plausible provider form is unreachable by design.

[NEEDS CLARIFICATION: which symbol form the Schwab provider actually
expects for class shares (e.g. `BRK-B`, `BRK/B`, `BRK B`, padded OCC
root `BRK  B`, or something else) — the MCP grammar blocks testing
alternatives end to end; needs a controlled provider probe or provider
doc confirmation.]

## Suspected Code Paths

- `src/schwab_mcp/quotes.py:57` — `_EQUITY_RE = ^[A-Z0-9.]{1,6}$`: grammar accepts the embedded dot (input side is fine).
- `src/schwab_mcp/quotes.py:92-113` — `_classify` returns `(kind, provider_form)`; for equities `provider_form` is the symbol **verbatim** (`"BRK.B" → ("equity", "BRK.B")`). Only option contracts get rewritten to a provider-canonical form, so the mapping seam exists but is unused for dot equities.
- `src/schwab_mcp/price_history.py:492` — reuses `_classify` (single source of truth), then `src/schwab_mcp/price_history.py:563-572` passes `normalized` verbatim as the provider symbol to `client.price_history(...)` — no translation layer downstream.
- `docs/tools.md:804` — contract table documents `BRK.B` as a valid equity/ETF example (docs/contract are aligned with the grammar, so this is not a docs-only fix).
- `tests/unit/test_price_history_validation.py:115` and `tests/unit/test_quotes_validation.py:177` — pin `BRK.B` as a valid normalized input; they never assert the **provider** form actually resolves.

## Root Cause Hypothesis

The equity grammar accepts class-share symbols and `_classify` passes
them to the provider verbatim, but the Schwab provider requires a
different representation for class shares (returns `not_found` /
empty candles for the dotted form). Because `_classify` already owns a
`provider_form` translation concept (used for option contracts → OCC),
the missing piece is the equity provider-form mapping (dot form →
whatever the provider expects). The bug predates `get_price_history`
(it is equally visible in `get_quotes`, feature 010), so it is
long-standing, not a regression of feature 011. Confidence: **high**
that the symptom is a missing provider-form mapping (systematic across
4 dot symbols, controls pass, normalization confirmed); **medium** on
which exact provider form is correct.

## Proposed Remediation

**Preferred**: keep the *input* grammar unchanged (dotted form stays
the documented, agent-facing form) and add the missing
*provider-form* translation in `_classify` (the single source of
truth, so both `get_quotes` and `get_price_history` inherit the fix):

1. Empirically confirm the provider's class-share form (one
   controlled probe per candidate form, e.g. `BRK-B`) outside the
   validation path, or from provider documentation.
2. In `_classify`'s equity branch, translate symbols containing `.`
   to the confirmed provider form and return it as `provider_form`.
3. Ensure both call sites actually send `provider_form` (not the raw
   normalized symbol) to the provider: `quotes` upcall and
   `price_history.py:563-572` (`client.price_history(0, normalized, ...)`
   currently ignores the `provider_form` element of the tuple).
4. Keep echoing the agent-facing (dotted) symbol in envelopes; the
   translation is provider-internal.

**Alternatives**:
- Reject dot symbols at validation (`unsupported_symbol_kind`-style
  detail): honest error instead of misleading
  `history_unavailable`, but it permanently drops BRK.B-class
  coverage and contradicts the documented grammar example.
- Hard-coded per-symbol mapping table (known class shares only):
  brittle, requires maintenance as listings change; no better than a
  mechanical dot→form rule if one exists.

**Files likely to change**:
- `src/schwab_mcp/quotes.py` (classify → provider-form mapping; quotes upcall site)
- `src/schwab_mcp/price_history.py` (send `provider_form` to `client.price_history`)
- `docs/tools.md` (document the provider-form mapping under the symbol-kind grammars section)
- `specs/011-price-history-ohlcv/contracts/mcp-tools.md` and `specs/010-real-time-quotes/contracts/mcp-tools.md` (contract note; per constitution, docs travel in the same commit)

**Tests to add or update**:
- Unit: `_classify("BRK.B")` returns the confirmed provider form (pin it once known).
- Unit: `price_history` passes `provider_form` (not the dotted input) to a mocked `client.price_history`; envelope still echoes `BRK.B`.
- Unit: `get_quotes` sends the mapped form in the provider request while errors/echo keep the input form.
- Regression (live or recorded fixture): `BRK.B` daily 1m returns `ok` with candles.
- Keep existing grammar tests (`BRK-B` still `malformed_symbol`, `A.B.C` still rejected).

## Risks & Considerations

- **Wrong guessed provider form**: probing forms against the live
  provider must be done deliberately (a handful of controlled
  requests); a wrong mechanical translation must not affect ordinary
  symbols — scope the mapping strictly to symbols containing `.`.
- **Contract/docs change**: the grammar table in `docs/tools.md` and
  the two spec contracts describe symbol handling; per the
  constitution, affected documentation must ship in the same commit.
- **Envelope echo semantics**: error/success envelopes must keep
  naming the requested (normalized, dotted) symbol (FR-008) — the
  mapping must not leak the provider form into agent-facing output
  (tests should pin this).
- **Blast radius**: touching `_classify` affects both quotes and
  price history simultaneously (intended reuse, but every call site
  must honor `provider_form` consistently).

## Open Questions

- [NEEDS CLARIFICATION: exact provider form for class shares (`BRK-B`? padded OCC-style root? other) — requires one controlled probe batch or provider documentation confirmation before implementing the mapping.]
- [NEEDS CLARIFICATION: are there class-share ETFs/indices with the same issue (e.g. index symbols never carry dots, so likely unaffected — no evidence of index impact in the live sweep).]