# Bug Assessment: TD-019 — OCC option symbol parsing triplicated (DRY)

- **Slug**: td-019-occ-symbol-parsing
- **Created**: 2026-11-04
- **Source**: pasted text (tech-debt report TD-019)
- **Verdict**: valid
- **Severity**: low

## Report (verbatim or summarized)

Pasted report (condensed; the knowledge *"the last 15 characters of an OCC
option symbol encode `YYMMDD` + `C/P` + 8-digit strike×1000`"* lives in three
modules, each pinned by different tests, with nothing asserting they agree):

- `src/schwab_mcp/symbols.py:31-53` — `OPTION_RE` +
  `canonical_option_symbol()`; module docstring proclaims it "the package's
  single source of truth" (established by TD-009).
- `src/schwab_mcp/transactions.py:53-81` — its own `_OCC_TAIL_RE`
  (`^\d{6}[CP]\d{8}$`) plus `_option_root()`, re-encoding the same tail
  grammar independently of the SSOT.
- `src/schwab_mcp/positions.py:173-192` — `_parse_occ_option_symbol()`
  re-implements the tail checks by hand (`len(tail) < 15 or tail[6] not in
  "CP"`, `yymmdd.isdigit() and strike_millis.isdigit()`) — it does not even
  reuse the regex, and holds the only derivation of the ISO expiry
  (`20{YYMMDD}`).

Proposed refactor: add `parse_occ_symbol(symbol)` to `symbols.py`; the two
private copies become thin wrappers or are deleted; expiry derivation moves
next to the strike decoding it mirrors. TDD: parity tests first, then the
shared function, existing suites green unchanged.

## Symptom

This is a tech-debt / DRY violation, not a user-facing defect: the OCC tail
grammar (15-char tail = `YYMMDD` + `C/P` + 8-digit strike×1000) is encoded
independently in three modules. Expected: one parser in
`schwab_mcp.symbols` (the declared SSOT) with all consumers reusing it.
Observed: three divergent implementations, none imported across module
boundaries — a change to the OCC encoding (strike digits, decimals,
separator tolerance) must be fixed in three places and the copies can drift
silently.

## Reproduction

1. Read `src/schwab_mcp/transactions.py:53` — `_OCC_TAIL_RE = re.compile(r"^\d{6}[CP]\d{8}$")` exists as an independent encoding of the tail grammar; `transactions.py` does not import `schwab_mcp.symbols` (verified: no import found in the module).
2. Read `src/schwab_mcp/positions.py:173-192` — `_parse_occ_option_symbol()` re-validates the tail with hand-written checks (`tail[6] not in "CP"`, `isdigit()` on both fields) and derives the ISO expiry (`f"20{yymmdd[:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}"`), duplicated knowledge again not sourced from `symbols.py`.
3. Run a fixture such as `"AMD   261120P00630000"` through all three parsers: each produces a consistent answer *today* (root `AMD` / strike 63.0 / expiry `2026-11-20`), but only by coincidence of three separate encodings — nothing in the test suite asserts the parsers agree.

No runtime failure exists to reproduce; reproduction is by code inspection
(above), which was performed and confirmed.

## Suspected Code Paths

- `src/schwab_mcp/symbols.py:31-53` — SSOT: `OPTION_RE` + `canonical_option_symbol()` (strike×1000 encoding lives here). Consumers today: `quotes.py`, `price_history.py`, `options_chain.py`.
- `src/schwab_mcp/transactions.py:53-81` — `_OCC_TAIL_RE` + `_option_root()`; graph-traced inbound callers (5, all internal to `transactions.py`): `get_transaction_history`, `get_transaction_history_tool`, `map_provider_transactions`, `movement_involves_filter`. Pinned by `tests/unit/test_transactions_underlying.py` (`_option_root` cases incl. padded root `"AMD   261120P00630000"`, unseparated `"NOK261218P00011000"`, and invalid tails).
- `src/schwab_mcp/positions.py:173-192` — `_parse_occ_option_symbol()`; graph-traced inbound callers (2): `_transform_provider_payload`, `get_open_positions`. Tested indirectly via `tests/unit/test_positions_live_response.py:132` (`test_option_strike_and_expiry_parsed_from_occ_symbol`, `strike_price == 90.0`) and the option-entry paths in `tests/unit/test_positions.py`.

## Root Cause Hypothesis

The three parsers were introduced at different times under different
features (007 underlying-aware matching in `transactions`, the live
positions transform in `positions`, and the TD-009 SSOT consolidation in
`symbols`), and the TD-009 consolidation captured quotes/price-history/
option-chain consumers but never migrated the transactions and positions
tail parsers. Confidence: **high** — all three code sites were read and
confirmed verbatim as described, and imports confirm zero cross-module
reuse (`transactions` and `positions` never import `schwab_mcp.symbols`).

## Proposed Remediation

**Preferred**: Add `parse_occ_symbol(symbol) -> OccSymbol | None` to
`src/schwab_mcp/symbols.py` (a small frozen dataclass or NamedTuple with
`root`, `expiry` (ISO `YYYY-MM-DD`), `put_call`, `strike`), built on the
existing SSOT machinery. It must parse the **strict 15-character OCC tail**
(`YYMMDD` + `[CP]` + exactly 8 digits) right-anchored — note the design
subtlety: `OPTION_RE`'s strike group is deliberately permissive (literal
strikes like `261120P63` are valid for `classify_symbol`), so the shared
parser must **not** simply reuse `OPTION_RE` wholesale; it should reuse the
tail grammar (`\d{6}[CP]\d{8}`) while keeping the root/separator handling
and the strike-÷1000 decoding consistent with `canonical_option_symbol`.
Then make `transactions._option_root` and `positions._parse_occ_option_symbol`
thin wrappers over it (lowest-risk option: internal signatures and call
sites stay untouched, blast radius limited to the two helper bodies; deletion
in favour of direct calls is a possible follow-up if the wrappers add no
value). The ISO expiry derivation moves into `symbols.py` next to the strike
decoding it mirrors. Parity is pinned by new tests before the switch.

**Alternatives**:
- Delete the private helpers and call `parse_occ_symbol` directly at the 7 call sites — slightly less code, but touches `transactions.py` matching logic and `positions.py` transform logic; higher review burden for zero behavioral gain. Reasonable as a fast-follow, not in the same change.
- Leave as-is with a cross-module parity test only (no shared function) — cheapest, but keeps three encodings alive and violates the TD-009 SSOT decree; not recommended.

**Files likely to change**:
- `src/schwab_mcp/symbols.py` (add `OccSymbol` + `parse_occ_symbol`)
- `src/schwab_mcp/transactions.py` (`_OCC_TAIL_RE`/`_option_root` become wrapper)
- `src/schwab_mcp/positions.py` (`_parse_occ_option_symbol` becomes wrapper)
- `tests/unit/test_symbols_grammar.py` or a new `tests/unit/test_occ_symbol_parity.py` (parity + shared-parser tests)
- `docs/tools.md` only if the agent-facing symbol contract gains a documented helper (likely not needed)

**Tests to add or update** (TDD: parity tests first — Red before Green):
- Parity fixture table feeding the same OCC symbols to the three current parsers and pinning agreement: padded root (`"AMD   261120P00630000"`), unseparated root (`"NOK261218P00011000"`), 1-char padded root (`"A     261120C00100000"`), index-style root (`"SPXW  261218C05000000"`), and the invalid tails already pinned in `test_transactions_underlying.py` (wrong C/P char, wrong-length date, non-digit strike, too-short symbol, `None`/empty).
- Shared-parser unit tests: strike decoding (÷1000), ISO expiry derivation, root strip of padding, `None` on every malformed tail.
- Existing suites must stay green **unchanged**: `tests/unit/test_transactions_underlying.py`, `tests/unit/test_positions_live_response.py`, `tests/unit/test_positions.py`, plus the quotes/price-history suites guarding `symbols.py`.

## Risks & Considerations

- **Permissiveness mismatch (the main trap)**: `OPTION_RE` accepts literal-strike tails and dotted roots that the strict tail parsers reject; a naive "reuse `OPTION_RE`" refactor would *widen* acceptance and change behavior of `movement_involves_filter` (M2 matching) and the positions transform. The shared parser must preserve the strict `\d{6}[CP]\d{8}` tail contract; parity tests lock this.
- **No range validation drift**: `_parse_occ_option_symbol` does not validate `YYMMDD` ranges (month 13 parses); the shared parser must not silently add stricter validation without a deliberate decision, or positions output could change.
- **Graph vs. reality**: blast radius is small (7 internal call sites, all in the two modules), verified via `trace_path` on 2026-11-04 (index generation `2026-11-04T20:11:46Z`, best-effort caveat noted).
- Low severity because there is no current user-facing defect — the risk is latent drift on a future OCC encoding change, which is exactly what TD-009's SSOT decree was meant to prevent.
- Per the constitution: mandatory TDD (parity tests Red first), existing suite green and unskipped at commit, and affected docs updated in the same commit.

## Open Questions

- Wrapper vs. deletion for the two private helpers: wrapper is recommended for this fix; confirm at `/speckit.bug.fix` time whether direct-call migration should be part of the same change or a follow-up.
- [NEEDS CLARIFICATION: should `parse_occ_symbol` expose `put_call`/`expiry` to callers that don't need them today (`_option_root` only needs the root), or should the dataclass fields simply be ignored by that wrapper? The dataclass-with-ignored-fields approach is simplest and avoids two public functions.]