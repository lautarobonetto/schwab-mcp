# Bug Verification: TD-019 — OCC option symbol parsing triplicated (DRY)

- **Slug**: td-019-occ-symbol-parsing
- **Tested**: 2026-11-04
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The original condition (the OCC tail grammar encoded in three modules with
no parity assertion) no longer holds: `grep` confirms the only remaining
encoding lives in `schwab_mcp.symbols`, the three parsers demonstrably
agree on the assessment's own fixture, and the new 42-case parity suite
plus the full regression suite (1875 tests) pass with zero changes to any
pre-existing test file.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | live snippet: run `parse_occ_symbol`, `_option_root`, `_parse_occ_option_symbol` on `"AMD   261120P00630000"` and assert agreement; `grep` for `_OCC_TAIL_RE`/`tail[6]`/`isdigit` across `src/` | pass | All three parsers agree (root `AMD`, strike 630.0, expiry `2026-11-20`); the only remaining `tail[6]` occurrence is the SSOT's own field extraction in `symbols.py:109` — `_OCC_TAIL_RE` and the hand-written checks are gone. The assessment's reproduction was inspection-based; both the inspection (grep) and its executable equivalent (parity snippet) were re-performed post-fix. |
| New / updated tests | `uv run pytest tests/unit/test_occ_symbol_parity.py -q` | pass | 42 passed — shared parser (7 valid + 6 invalid + `None` + literal-strike rejection), parity vs. `_option_root`, parity vs. `_parse_occ_option_symbol` |
| Regression suite | `uv run pytest -q` (full suite) | pass | 1875 passed, 0 skipped — includes the suites that pin the old parsers' behavior (`test_transactions_underlying.py`, `test_positions_live_response.py`, `test_positions.py`, `test_quotes_validation.py`, `test_options_chain_validation.py`), unchanged |
| Lint / type-check | — | not-run | No lint or type-check tooling is configured in `pyproject.toml` (no ruff/mypy/flake8/black config found); nothing to run |

## Output Excerpts

```
parse_occ_symbol      : OccSymbol(root='AMD', expiry='2026-11-20', put_call='P', strike=630.0)
_option_root          : AMD
_parse_occ_option_sym : (630.0, '2026-11-20')
PARITY OK — all three parsers agree
```

```
$ uv run pytest tests/unit/test_occ_symbol_parity.py -q
..........................................                               [100%]
42 passed in 0.06s

$ uv run pytest -q
...                                                                      [100%]
1875 passed in 35.99s
```

## Residual Risks

- `parse_occ_symbol` deliberately performs no `YYMMDD` range validation
  (month 13 still parses) — preserved from the historical parsers by
  design; any future decision to validate ranges is a behavioral change
  that must go through its own TDD cycle, not a silent side effect of
  this consolidation.
- The strict-tail contract (8-digit strike only) is pinned by
  `test_literal_strike_tail_is_rejected`, but `OPTION_RE`'s permissive
  literal-strike branch remains intentionally separate for
  `classify_symbol`; a future contributor could still conflate the two —
  the `symbols.py` docstrings now warn against exactly this.
- The two thin wrappers are retained (not deleted) per the assessment's
  lowest-risk option; the direct-call migration at the 7 call sites is an
  optional fast-follow, not yet done.
- Lint/type-check coverage is absent project-wide (not specific to this
  fix).

## Recommendation

Close the bug — verified. The grammar now has exactly one encoding
(`schwab_mcp.symbols.parse_occ_symbol`), cross-parser parity is locked by
the new test suite, the full suite is green with 0 skipped, and the
documentation currency rule is satisfied (`docs/tech-debt.md` and
`docs/CHANGELOG.md` updated in `fix.md`). Remaining work is optional
clean-up (wrapper deletion, TD-030) and belongs to the tech-debt backlog,
not this bug.
