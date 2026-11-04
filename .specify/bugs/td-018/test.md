# Bug Verification: TD-018 — Obscured imports and readability nits

- **Slug**: td-018
- **Tested**: 2026-11-04
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The six tech-debt items no longer appear in the source (verified by direct source inspection), the four tests added by the fix pass, and the full 1833-test suite is green with zero skips. The one item with a genuine behavioral failure mode (`archive.py` cryptic `TypeError`) was demonstrated red-before-fix during `/speckit.bug.fix` and is green after.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | Source inspection per item (greps/reads below) | pass | Assessment's "reproduction" was code-reading, not user-visible steps; the automated equivalent was exercised for all six items |
| — item 1: `__import__("logging")` gone | `grep -n '__import__' src/schwab_mcp/cli.py` | pass | No matches; `import logging` present at module top; redaction filter installed via `logging.root` / `logging.getLogger` |
| — item 2: fallback kept + pinned | `tests/integration/test_auth.py::TestAuthUrlFallbackForInertClient` | pass | Inert client + absent store → URL printed exactly once, never reports success |
| — item 3: `renewal.py` docstring/imports | read `renewal.py:1-22` | pass | Docstring names all three responsibilities; stdio + `schwab_mcp.*` imports at top; no mid-file import block |
| — item 4: raw strings gone | `grep 'detail="transient"\|detail="provider_error"' src/schwab_mcp/transactions.py` | pass | No matches; `AccountFailureDetail` imported and used at both construction sites |
| — item 5: alias in key map | `grep -n 'tradeTimeInLong' src/schwab_mcp/options_chain.py` | pass | Only the comment and the map entry `"trade_time": ("tradeTime", "tradeTimeInLong")` remain; `serialize_leg` special-case branch removed |
| — item 6: archive domain error | `grep 'no payload or generated artifact' src/schwab_mcp_release/archive.py` | pass | Explicit membership check + `ReleaseError` in place |
| Red-before-fix evidence (item 6) | recorded during `/speckit.bug.fix` | pass | Test failed pre-fix with `TypeError: object of type 'NoneType' has no len()` — the exact cryptic failure the assessment predicted; green post-fix |
| New / updated tests | `uv run pytest tests/unit/test_release_archive.py::TestMemberLookupRobustness tests/unit/test_options_chain_mapping.py::TestSerializeLeg tests/unit/test_results_shared_taxonomy.py::TestAccountFailedShared tests/integration/test_auth.py::TestAuthUrlFallbackForInertClient -v` | pass | 23 passed in 0.29 s |
| Regression suite | `uv run pytest -q` | pass | 1833 passed, 0 skipped, 0 failed in ~44 s (commit-gate green) |
| Lint / type-check | — | not-run | Not configured in this project (no ruff/mypy in `pyproject.toml`; dev deps are pytest-only). `filterwarnings = ["error"]` in the pytest config acts as the strictness gate and passed as part of the suite |

## Output Excerpts

```
tests/unit/test_results_shared_taxonomy.py::TestAccountFailedShared::test_enum_construction_serializes_canonical_values PASSED
tests/integration/test_auth.py::TestAuthUrlFallbackForInertClient::test_fallback_prints_url_once_and_never_reports_success PASSED
============================== 23 passed in 0.29s ==============================
```

```
uv run pytest -q
........................................................................ [100%]
1833 passed in 44.08s
```

Red evidence (captured during the fix run, before the archive change):

```
E       TypeError: object of type 'NoneType' has no len()
FAILED tests/unit/test_release_archive.py::TestMemberLookupRobustness::test_member_in_neither_dict_raises_release_error
1 failed, 22 passed in 0.44s
```

## Residual Risks

- No user-visible behavior existed to reproduce end-to-end: this was a code-hygiene batch, so "reproduction" is necessarily source-level verification plus tests, not a live run of the MCP server.
- The `archive.py` guard is unreachable with today's allowlist (defensive hardening); the red→green evidence came from a monkeypatched `member_specs`, which is the only way to reach the path.
- Item 4's `positions.py` raw-dict construction remains intentionally untouched (TD-002/TD-007 territory, per the assessment).
- Two assessment Open Questions carry forward (fallback contract documentation; whether the positions raw-dict pattern is tracked under TD-002/TD-007).

## Recommendation

Close the bug — all six remediation items are in place, the behavioral failure mode was demonstrated red→green, the new pinning tests pass, and the full suite (1833 tests, 0 skipped) is green. No lint/type-check exists to run. Ready for commit with the `docs/CHANGELOG.md` update included per the constitution.