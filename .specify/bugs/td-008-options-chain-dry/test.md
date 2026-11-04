# Bug Verification: TD-008 — `options_chain.py` internal duplication, seven sites (DRY)

- **Slug**: td-008-options-chain-dry
- **Tested**: 2026-11-04
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

This was a static duplication (DRY) finding, not a runtime defect — the
assessment's "reproduction" was verification that the seven duplication sites
exist in the working tree. That reproduction was fully exercised post-fix and
no longer holds: every duplicated site now has a single shared implementation.
No regressions: the full suite is green (1811 passed, 0 skipped, 0 failed).

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | grep/AST audit of `src/schwab_mcp/options_chain.py` | pass | All 7 duplication sites eliminated (details below) |
| Site 2 (HTTP-400 sniff) | `grep -n "status_code.*== 400"` | pass | Exactly 1 occurrence (line 292, inside `_is_no_options_response`) |
| Site 3 (underlying price) | `grep -n "underlyingPrice"` | pass | Only in `_underlying_price` (line 605 + docstring) |
| Site 4 (leg_maps double build) | `grep -n "_leg_map(payload"` | pass | Builds only in `build_chain_result` (734-735); passed down into `_map_expirations` |
| Site 5 (detail string) | `grep -c "no_expirations_in_range: "` | pass | 1 occurrence (inside `_no_expirations_detail`) |
| Site 6 (date double parse) | `grep -n "fromisoformat"` in the expiration-list path | pass | Only `_parse_expiration_date` (line 971); line 635 is the unrelated chain-map-key DTE computation, not part of the reported pair |
| Site 7 (`_result_meta` payload) | `grep -n "_result_meta(query"` | pass | One-arg signature everywhere (695 def; 738, 1064 call sites) |
| Site 1 (error-mapping blocks) | `grep -n "TD-008"` | pass | Mutual cross-reference comments present (lines 848, 1126) per the fix decision |
| Site 8 (orchestrator nesting) | AST max-nested-try-depth | pass | `get_option_chain`: 1, `get_option_expiration_chain`: 1 (was 2 with the degradation logic buried) |
| New / updated tests | `uv run pytest tests/unit/test_option_expirations.py …` (6 targeted files) | pass | 138 passed, including the new characterization test |
| Regression suite | `uv run pytest -q` | pass | 1811 passed, 0 skipped, 0 failed (~34 s) — the constitution's commit gate |
| Lint / type-check | — | skipped | Not configured: `pyproject.toml` declares only `[tool.pytest.ini_options]`/`[tool.setuptools]`; CI (`.github/workflows/ci.yml`) gates on `uv sync && uv run pytest` only |

## Output Excerpts

```
$ uv run pytest -q
........................................................................ [ 99%]
...........                                                              [100%]
1811 passed in 34.42s

$ uv run pytest tests/unit/test_option_expirations.py \
    tests/unit/test_options_chain_filters.py \
    tests/unit/test_options_chain_body_limit.py \
    tests/unit/test_options_chain_mapping.py \
    tests/unit/test_options_chain_delta.py \
    tests/unit/test_tool_error_classification.py -q
138 passed in 0.45s

AST audit: get_option_chain: max nested try depth = 1
           get_option_expiration_chain: max nested try depth = 1
```

Reproduction details (static audit): each of the eight TD-008 sites is
traceable to its single implementation via the `TD-008 site N` markers
written into the helper docstrings/comments during the fix (grep found all
ten markers: sites 1×2 comments, 2, 3, 4, 5, 6×2, 7, 8).

## Residual Risks

- The fix is a behavior-preserving refactor validated by the existing suite;
  no live-provider (network) verification was run — not needed for a pure
  internal refactor, and the suite's fixtures pin the provider shapes.
- Lint/type-check tooling is not configured in this project, so style
  regressions (if any) are not machine-checked.
- Site 1 remains two near-duplicate blocks by explicit decision (KISS); if a
  third tool adopts the same error-mapping pattern, revisit (rule of three).

## Recommendation

Close the bug — verified. The reproduction (static duplication audit) was
actually exercised post-fix and no longer holds, all targeted and full-suite
tests are green with zero skipped, and the two result-state detail strings
are now pinned verbatim by tests on both paths. Ready to commit (include
`assessment.md`, `fix.md`, and `test.md` in the same commit per the
constitution).