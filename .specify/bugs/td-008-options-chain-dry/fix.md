# Bug Fix: TD-008 — `options_chain.py` internal duplication, seven sites (DRY)

- **Slug**: td-008-options-chain-dry
- **Fixed**: 2026-11-04
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Behavior-preserving refactor of `src/schwab_mcp/options_chain.py` implementing
the assessment's preferred remediation: shared helpers for each duplicated
pair, `leg_maps`/`underlying_price` computed once in `build_chain_result` and
passed down, `_result_meta(query)` without the unused `payload` parameter, and
the delta strikeCount expansion extracted as `_fetch_chain_payload`. Public
API (function signatures, result shapes, `detail` strings) is unchanged.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/options_chain.py` | modified | All 8 TD-008 sites addressed (see below) |
| `tests/unit/test_option_expirations.py` | modified | Characterization test pinning the shared detail string |

Per-site detail:

1. **Error-mapping try/except blocks** — kept as explicit near-duplicates per
   the assessment's open-choice resolution (KISS); both blocks now carry a
   mutual cross-reference comment naming TD-008 site 1 and the one real
   difference (`ChainDataError` only on the chain path).
2. **HTTP-400 no-options sniff** — new `_is_no_options_response(response)`
   predicate; used by `fetch_option_chain` and `_fetch_expiration_chain`,
   with the canonical rationale moved into its docstring.
3. **`underlying_price` extraction** — new `_underlying_price(payload)`
   helper (`underlyingPrice` with `underlying.last` fallback), used by the
   `ok` state and passed into `_map_expirations` for ATM selection.
4. **`leg_maps` double build** — `build_chain_result` builds `leg_maps` once
   and passes it into `_map_expirations(leg_maps, query, today,
   underlying_price)`; the no-data gate and the mapping now share one
   normalization, eliminating the divergence risk.
5. **`no_expirations_in_range` detail string** — new `_no_expirations_detail(query)`
   used by both `build_chain_result` and `build_expiration_result`.
6. **Expiration-date double parse** — new `_parse_expiration_date(raw)`;
   `_map_expiration_list` parses each entry's date exactly once and hands the
   parsed date to both the DTE filter and `_expiration_sort_key`
   (whose item shape changed from `(int, dict)` to
   `(date | None, int, dict)`).
7. **`_result_meta` unused parameter** — signature is now `_result_meta(query)`;
   both call sites updated. (Assessment said three call sites; there were
   two — confirmed during assessment.)
8. **Orchestrator nesting** — new `_fetch_chain_payload(client, query)`
   containing the delta floor fetch, `_delta_bracketed` check, ceiling
   re-fetch and body-limit degradation (with its
   `options_chain_query_degraded` / `provider_body_limit` auth event);
   `get_option_chain` keeps validation, error mapping, `extended` handling
   and the success event. The flat early-return structure (no-delta path,
   bracketed path, degraded path) replaces the nested try/except.

## Diff Highlights

`build_chain_result` — one build, passed down:

```python
leg_maps = {"call": _leg_map(payload, "call"), "put": _leg_map(payload, "put")}
underlying_price = _underlying_price(payload)
...
expirations = _map_expirations(leg_maps, query, today, underlying_price)
```

`_fetch_chain_payload` — degradation as a named seam:

```python
if query.delta_target is None:
    return fetch_option_chain(client, query)
payload = fetch_option_chain(client, query, strike_count=max(query.max_strikes, DELTA_STRIKE_COUNT_FLOOR))
if _delta_bracketed(payload, query):
    return payload
try:
    return fetch_option_chain(client, query, strike_count=DELTA_STRIKE_COUNT_CEILING)
except ProviderBodyLimitError:
    auth_event("options_chain_query_degraded", "degraded", detail="provider_body_limit")
    return payload
```

`_map_expiration_list` — one parse per date, shared by filter and sort:

```python
parsed = _parse_expiration_date(entry.get("expirationDate"))
dte = None if parsed is None else (parsed - today).days
if dte is not None and dte > query.dte_max_effective:
    continue
kept.append((parsed, index, _expiration_entry(entry, dte)))
```

## Tests Added or Updated

- `tests/unit/test_option_expirations.py::TestDteCeiling::test_no_expirations_in_range_detail_string_is_pinned`
  — characterizes the verbatim `no_expirations_in_range` detail string for
  the expiration path (the chain-path string was already pinned verbatim at
  `tests/unit/test_options_chain_filters.py:635`). Written and run green
  **before** the refactor, per TDD.

## Local Verification

- Commands run:
  - `uv run pytest tests/unit/test_option_expirations.py -q` → 35 passed
    (pre-refactor, with the new test)
  - `uv run pytest -q` → **1811 passed, 0 skipped, 0 failed** in ~34 s
    (post-refactor, full suite — the constitution's commit gate)
- Manual checks:
  - `git diff --stat`: only the two files above changed; no unrelated code
    touched.
  - Grep confirmed no other module references the renamed/re-signed internal
    helpers (`_result_meta`, `_map_expirations`, `_expiration_entry`,
    `_expiration_sort_key`, `_fetch_chain_payload`).
  - The body-limit degradation on the ceiling re-fetch is behavior-pinned by
    the pre-existing `tests/unit/test_options_chain_body_limit.py::TestDeltaDegradation::test_ceiling_body_limit_falls_back_to_floor_payload`
    (floor outcome + exactly 2 provider calls + ceiling strikeCount=200) —
    no new test needed for the extracted helper.

## Deviations from Assessment

- **Site 1 resolution**: the assessment left the error-mapping blocks as
  "extract a context manager OR annotate as near-duplicates — decide in
  `/speckit.bug.fix`". Decision: annotated near-duplicates (KISS; the
  per-tool `auth_event` prefixes and the single-block `ChainDataError`
  difference would make an abstraction carry more variation than it removes).
- **`_expiration_sort_key` item shape changed** from `(index, entry)` to
  `(parsed, index, entry)`: required to actually eliminate the double parse
  (the assessment suggested "if the entry carries its parsed date, the sort
  key can consume it" — implemented by carrying the parsed date in the sort
  item rather than in the contract-facing entry dict, which must keep
  exactly the three curated fields).
- No assessment inaccuracy invalidated the remediation; the two known
  report corrections (two `_result_meta` call sites; two try levels) were
  already documented in the assessment.

## Follow-ups

- Documentation: no tool-visible behavior or wording changed; `docs/tools.md`
  needs no update. Commit message should note the refactor per the
  constitution (tests green, docs unaffected).
- Optional: if a third tool ever adopts the same result-state pattern,
  revisit site 1 with a shared error-mapping helper — two near-duplicates do
  not justify one yet (rule of three).
- Run `/speckit.bug.test slug=td-008-options-chain-dry` to validate the fix
  independently.