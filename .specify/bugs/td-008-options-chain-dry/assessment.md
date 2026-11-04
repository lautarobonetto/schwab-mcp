# Bug Assessment: TD-008 — `options_chain.py` internal duplication, seven sites (DRY)

- **Slug**: td-008-options-chain-dry
- **Created**: 2026-11-04
- **Source**: pasted text (TD-008 report, verbatim below)
- **Verdict**: valid
- **Severity**: medium

## Report (verbatim or summarized)

> **TD-008 — `options_chain.py` internal duplication, seven sites (DRY)**
> **Area:** `src/schwab_mcp/options_chain.py`
>
> 1. Audit try/except blocks copied between `get_option_chain` (818-839) and
>    `get_option_expiration_chain` (1089-1105).
> 2. HTTP-400 "no options listed" sniff duplicated (326-327 vs 919-920), with
>    comments referring to each other.
> 3. `underlying_price` extraction duplicated (604-607 vs 731-734).
> 4. `leg_maps` built twice from the same payload (600-603 vs 700-704) —
>    divergence risk if normalization changes.
> 5. `"no_expirations_in_range: ... excludes all expirations"` detail string
>    duplicated (721-725 vs 1037-1041).
> 6. `date.fromisoformat` with fallback-to-`None` duplicated (938-942 vs
>    959-963); each expiration date parsed twice.
> 7. `_result_meta(query, payload)` (675-680) ignores `payload`; three call
>    sites pass it needlessly.
> 8. The orchestrator nests five levels of try/except (791-839); the
>    body-limit degradation logic is buried three levels deep — extract
>    `_fetch_chain_payload(client, query)`.
>
> **Refactor:** helpers for each pair (`_no_options_response`,
> `_underlying_price`, `_no_expirations_detail`, `_parse_expiration_date`);
> build `leg_maps`/`underlying_price` once in `build_chain_result` and pass
> them down; `_result_meta(query)`.

## Symptom

Not a behavioral defect — internal duplication (DRY violation) in the core
options-chain module. All seven duplication sites exist in the current file;
the risk is divergence: e.g. `leg_maps` is normalized twice from the same
payload (site 4), so a future change to `_leg_map` normalization applied to
only one of the two builds could make the `no_options_listed` gate in
`build_chain_result` disagree with what `_map_expirations` actually maps.

## Reproduction

Not reproducible as a runtime failure; verified statically against the
working tree (`src/schwab_mcp/options_chain.py`, 1144 lines):

1. Read the cited line ranges in the current file.
2. Each duplication site is present at (or within a few lines of) the
   reported location.
3. `_result_meta(query, payload)` at line 675 never reads `payload`
   (confirmed: function body uses only `query`).

## Suspected Code Paths

- `src/schwab_mcp/options_chain.py:326-327` and `:919-920` — HTTP-400 → `{}` "no
  options listed" sniff duplicated in `fetch_option_chain` and
  `_fetch_expiration_chain`; comments explicitly cross-reference each other.
- `src/schwab_mcp/options_chain.py:600-603` (`_map_expirations`) vs
  `:700-704` (`build_chain_result`) — `leg_maps` built twice from the same
  payload. Highest-divergence-risk site.
- `src/schwab_mcp/options_chain.py:604-607` vs `:731-734` — `underlying_price`
  extraction (`underlyingPrice`, fallback `underlying.last`) duplicated.
- `src/schwab_mcp/options_chain.py:721-725` vs `:1037-1041` — identical
  `"no_expirations_in_range: ... excludes all expirations"` detail string in
  both result builders.
- `src/schwab_mcp/options_chain.py:936-942` (`_expiration_entry`) vs
  `:957-963` (`_expiration_sort_key`) — `date.fromisoformat` with
  fallback-to-`None` duplicated; each expiration date string parsed twice.
- `src/schwab_mcp/options_chain.py:675-680` — `_result_meta(query, payload)`
  ignores `payload`. **Correction to the report:** there are two call sites
  (lines 705 and 1020), not three.
- `src/schwab_mcp/options_chain.py:818-839` vs `:1089-1105` — near-identical
  error-mapping try/except blocks (Reauth / Connectivity / ValueError +
  `auth_event` emission). They have already diverged slightly: the chain path
  also catches `ChainDataError`; the expiration path does not (semantically
  justified — no chain data there — but it is exactly the drift this
  duplication invites).
- `src/schwab_mcp/options_chain.py:791-839` — orchestrator fetch/validation
  nesting. **Correction to the report:** two try levels, not five
  (`try:` line 791 → nested `try:` line 799 in the delta path), but the
  substantive point stands: the body-limit degradation (`auth_event` at
  810-814) is buried inside the delta-refetch branch and the whole fetch
  sequence has no named seam.

## Root Cause Hypothesis

The chain tool (feature 008) and the expiration tool (feature 012) were built
against the same provider semantics (HTTP-400 no-options shape, DTE ceiling,
result states) as separate vertical slices, so identical logic was
re-implemented per tool instead of being extracted. Each later feature copied
the nearest existing block rather than factoring a shared helper. Confidence:
**high** — every cited site is present in the current file and the
cross-referencing comments ("See fetch_option_chain: ...") document the copy
relationship explicitly.

## Proposed Remediation

**Preferred**: Extract module-private helpers, one per duplicated pair, and
pass computed values down instead of recomputing:

- `_no_options_response()` — or a shared `_is_no_options_response(response)`
  predicate used by both fetchers (keeps each fetcher's distinct post-400
  logic: the chain fetcher's 502/body-limit check stays in
  `fetch_option_chain`).
- `_underlying_price(payload)` — `underlyingPrice` with `underlying.last`
  fallback; call it in `build_chain_result` and pass the value into
  `_map_expirations` (removes the duplicate extraction and the second
  `leg_maps` build in one move — see below).
- `_no_expirations_detail(query)` — single source for the detail string.
- `_parse_expiration_date(raw) -> date | None` — used by both
  `_expiration_entry` (for `dte`) and `_expiration_sort_key`; if the entry
  carries its parsed date, the sort key can consume it instead of re-parsing,
  eliminating the double parse.
- `_result_meta(query)` — drop the unused `payload` parameter (2 call sites).
- Build `leg_maps` once in `build_chain_result` and pass it into
  `_map_expirations` (signature becomes `_map_expirations(leg_maps, query,
  today, underlying_price)`), removing site 4 entirely.
- Extract `_fetch_chain_payload(client, query)` from the orchestrator body
  (lines 791-817): the delta-floor fetch, bracket check, ceiling re-fetch and
  body-limit degradation move into one named function; `get_option_chain`
  keeps only validation, the error-mapping try/except, `extended` handling
  and the success `auth_event`.
- For the near-duplicate error-mapping blocks (site 1): a shared
  `_map_provider_errors(events: str_prefix)` context manager is possible but
  risks obscuring the per-tool `auth_event` prefixes and the `ChainDataError`
  difference. Recommend either extracting it or, at minimum, leaving the
  blocks with a mutual cross-reference comment — decide in
  `/speckit.bug.fix` with the contract tests in view.

This is a behavior-preserving refactor. Per the project constitution it
requires TDD: the existing suite is the red/green harness (see Tests below);
any helper extraction must keep the full suite green with zero skipped tests,
and affected documentation (`docs/tools.md` if tool-visible behavior or
docstrings change) must be updated in the same commit.

**Alternatives**:
- *Do nothing / annotate only*: add cross-reference comments like site 2
  already has. Zero risk, but leaves the `leg_maps` double-build hazard
  in place.
- *Merge the two result builders*: not recommended — the chain and
  expiration results have genuinely different shapes (`retryable`,
  `strikes`, `settlement_type`); over-unification would trade real clarity
  for superficial DRY.

**Files likely to change**:
- `src/schwab_mcp/options_chain.py` (all sites; no public API changes —
  `get_option_chain` / `get_option_expiration_chain` signatures and result
  shapes stay identical)
- `docs/tools.md` — only if any docstring-visible behavior wording changes
  (likely minimal or none)

**Tests to add or update**:
- No new behavioral tests should be required — the existing suite must pass
  unchanged as the refactor gate:
  `tests/unit/test_options_chain_mapping.py`,
  `tests/unit/test_options_chain_filters.py`, `tests/unit/test_options_chain_delta.py`,
  `tests/unit/test_options_chain_body_limit.py`,
  `tests/unit/test_option_expirations.py` (+ its fixture
  `expiration_chain_payloads.py`), `tests/unit/test_tool_error_classification.py`.
- Add one characterization test pinning the exact
  `no_expirations_in_range` detail string for both tools, if not already
  asserted verbatim — it is the one duplicated string a refactor could
  silently alter and that downstream consumers may match on.
- If `_fetch_chain_payload` is extracted, verify the body-limit degradation
  path (`options_chain_query_degraded` / `provider_body_limit` event) is
  covered by `test_options_chain_body_limit.py`; add a case for the
  degradation occurring on the ceiling re-fetch if missing.

## Risks & Considerations

- **Contract stability**: result `detail` strings and outcomes are
  contract-facing (data-model §3/§4, contract §2); helpers must reproduce
  them byte-for-byte. The verbatim-string test above guards this.
- **Subtle behavior drift in `_expiration_sort_key`**: its fallback ordering
  (`(1, 0, index)` for unparseable dates) must survive the refactor to
  `_parse_expiration_date`.
- **`_result_meta` signature change**: private function, two internal call
  sites — low risk; no external consumers.
- **Over-abstraction**: the report's "five levels" nesting claim is
  overstated (two try levels); extract `_fetch_chain_payload` for the named
  seam, but do not invent additional layers beyond what the duplication
  justifies (constitution: KISS / simplest thing that works).
- **Performance budgets**: no hot-path change expected; `leg_maps` build
  going from twice to once per request is a (small) improvement.

## Open Questions

- None blocking. Site 1 (shared error-mapping try/except) has a design
  choice (context-manager extraction vs annotated near-duplicates) that
  `/speckit.bug.fix` should settle against the contract tests.
- Report inaccuracies to carry into the fix (already corrected above):
  `_result_meta` has two call sites, not three; the orchestrator nests two
  try levels, not five.