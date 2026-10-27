# Research: Underlying-Aware Symbol Filter and Underlying Reference

Feature: 007-underlying-symbol-filter | Date: 2026-10-24

## R1. How to assemble the filtered result given that the provider cannot filter options by underlying

**Decision**: when `symbol` is present, the tool queries the range
**unfiltered upstream** (same upcalls as the unfiltered query) and
applies the three-form matching **locally**, on the merged and
deduplicated history that 006's orchestration already produces.

**Rationale**: verified live (2026-10-23/24, feature 006):
- `symbol=NOK` (underlying) → the endpoint responds `200` with **0
  results** even though there were 14 NOK option transactions in the
  period: the upstream filter only matches the registered symbol of each
  transaction, and option transactions are registered under their OCC
  symbol.
- `symbol="NOK   261218P00011000"` (OCC) → the endpoint rejects the call
  with `HTTP 400 {"message":"symbol: Invalid Symbol"}`.

Therefore no use of the upstream `symbol` parameter delivers the result
the spec demands. The unfiltered sweep + local matcher:
(1) guarantees subset-consistency (FR-005) **by construction** — the
filtered result is literally a subset of the unfiltered result of the
same range; (2) adds no upcalls (the upcalls are identical to the
unfiltered query); (3) reuses the existing orchestration, bisection and
deduplication in full.

**Alternatives considered**:
- *Upstream filter as today + second sweep for options*: 2× upcalls per
  query, two merges, and the first set is already incomplete (same
  limitation) — rejected (KISS, V).
- *Querying each known OCC symbol of the underlying*: impossible to know
  in advance which OCC symbols the account registered without the sweep —
  rejected.
- *Keeping the upstream filter only for exact match and an extra sweep
  only if there are options*: indistinguishable in cost from the direct
  sweep and adds a conditional path — rejected (KISS).

Behavior note: by no longer sending `symbol` upstream, the filtered query
also stops suffering the `HTTP 400` for OCC symbols — the spec's
OC/AC4 case (a specific option) is supported without extra calls.

## R2. Root (underlying) derivation from the registered OCC symbol

**Decision**: the root of an option is the portion before the last 15
characters of the registered symbol (`root = symbol[:-15].strip()`),
right-anchoring identical to the one already verified live for positions
(`_parse_occ_option_symbol`, positions-response-unwrap bug: the last 15
characters are always `YYMMDD + C/P + strike×1000`).

**Rationale**: the OCC standard pads the root to 6 characters with spaces
(`AMD   261120P00630000` → root `AMD`); anchoring from the right makes
parsing independent of the padding. Validated live: real OPTION
instruments carry `symbol`, `putCall`, `underlyingSymbol` (but not
`strikePrice`/`expirationDate`) — the symbol is the reliable source.

**Fallback rules** (spec edge cases):
- If the 15-character tail does not match the OCC pattern (no digits in
  the expected positions, or C/P is not `C`/`P`), the root is not
  identifiable: the movement can only match by exact equality of the
  registered symbol (FR-001a) and does **not** expose `underlying_symbol`
  in the curated output.
- The root is reported as the source records it (after removing
  padding), without reformatting.

**Alternatives considered**:
- *Left-anchored root parsing (fixed 6 chars)*: breaks with roots of
  different lengths or inconsistent padding — rejected.
- *Using `instrument.underlyingSymbol` from the extended payload*: not
  available in curated mode (only `extended=true`) and the field can come
  empty; the OCC symbol is the complete source — rejected as primary
  source (stays in extended as passthrough).

## R3. Dual filter validation (spec clarification C)

**Decision**: keep the upcall
`instruments(symbols=[filter], projection="symbol-search")` as the first
step (a single lookup, as today). If the directory **resolves** the
filter → continue (current behavior). If it **does not resolve** → DO NOT
fail: proceed with the sweep and classify at the end — if there are
movements that match (registered symbol, root or complete OCC), return
them with `ok`; if there are none, return the `instrument_not_found`
error naming the filter (as today).

**Rationale**: direct implementation of clarification C. The
`CURRENCY_USD` case (not resolved in the directory but present as a
registered symbol in movements) goes from `instrument_not_found` to
returning its movements — behavior change documented in the contract and
in `docs/tools.md` (006's caveat is updated).

**Alternatives considered**:
- *Validation unchanged (clarify A)*: it would lie with
  `instrument_not_found` when there is activity with that root — rejected
  by the user.
- *Validating the derived root instead of the raw filter*: the filter can
  be a complete OCC or an underlying; the lookup of the raw filter is the
  current contract — rejected.

## R4. Case-insensitivity of matching

**Decision**: normalize the filter and candidates to uppercase for
comparison (`filter.upper() == symbol.upper()` / `root.upper()`); the
output reports symbols as the source records them, without reformatting.

**Rationale**: OCC roots are uppercase by standard; agents may send
`nok`. Comparing in uppercase is deterministic and avoids dependence on
input case. Source symbols are already uppercase in practice — the
normalization is idempotent.

**Alternatives considered**: case-sensitive matching + an instructive
error — unnecessary friction for the dominant case.

## R5. Impact of the `underlying_symbol` field on the 16 KB budget

**Decision**: `underlying_symbol` is added to the curated output only for
option movements (`Optional`, excluded with `exclude_none` like the
existing optional fields). Estimated impact: ~25 JSON bytes per option
movement (`"underlying_symbol":"AMD"` + overhead); a page of 50
all-option movements adds ~1.2 KB over the current maximum.

**Rationale**: 006's default page measured ≤ 16 KB with 50 movements
extended=false; the budget margin is verified with the existing
token-usage test extended to the worst case (50 option movements, each
with a root). If the worst case exceeded 16 KB, the constitution requires
recorded justification — preliminary research indicates sufficient margin
(a curated page of 50 ≈ 8-9 KB today).

**Alternatives considered**: an always-present field (includes `null`) —
token waste; OPTION-only + `exclude_none` is what the existing
`symbol`/`instrument_type` pattern already established.

## R6. `detail` semantics with the new matching

**Decision**: `detail` vocabulary unchanged: `history_retrieved`,
`no_movements`, `no_movements_for_instrument` (the latter now means
"nothing matches the filter in any form"). With dual validation,
`instrument_not_found` appears only when there is no match and the
directory did not resolve the filter.

**Rationale**: not extending the closed enum (006's data model) avoids
contract changes in the outcomes; the existing detail semantics are
refined without renaming anything.

**Alternatives considered**: a new detail
`no_movements_for_underlying` — would duplicate meaning (DRY, II).

## R7. Subset-consistency: how it is tested

**Decision**: the property is tested at the unit level by comparing, for
the same range and fixtures, the filtered result against the local
filtering of the unfiltered result (same matcher function); the
quickstart live test verifies it against the real API with an underlying
that has activity of both types.

**Rationale**: with R1 (sweep + local matcher) the property is
structural; the test pins it to prevent regressions if the implementation
plan introduces upstream shortcuts.

**Alternatives considered**: comparing against the provider in the test —
not deterministic.