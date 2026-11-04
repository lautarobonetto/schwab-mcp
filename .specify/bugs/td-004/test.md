# Bug Verification: TD-004 — Error envelopes and `ToolError` boundary divergent

- **Slug**: td-004
- **Tested**: 2026-11-04
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The bug no longer reproduces: taxonomy errors raised at the
`get_quotes_tool` / `get_price_history_tool` boundaries now surface as
classified `ToolError`s with the `provider_unreachable:` / `reauth_needed:`
prefixes, and the envelope duplication is gone. The normal-path envelope
contract (in-domain conversion, `symbol` presence/absence) is unchanged, and
the full regression suite is green — no regressions found.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction — boundary escape (post-fix) | `uv run python tmp/td004_verify_repro.py` (monkeypatches the domain functions to raise `ConnectivityError` / `ReauthorizationRequiredError` and calls both tool wrappers) | pass | 4/4: exact `ToolError` type, correct prefix, `__cause__` preserved. This is the assessment's dynamic repro; it failed before the fix (Red, captured during `/speckit.bug.fix`) |
| Reproduction — normal-path envelope contract | same script | pass | 3/3: provider 503/401 *inside* the domains still return structured envelopes (not exceptions); quotes envelopes carry no `symbol`, price_history's do |
| Reproduction — duplication (static) | grep both modules | pass | 0 hits for `_validation_error` / `_provider_unreachable` / `_reauth_needed` / `_history_unavailable` and hand-rolled `except (ValueError, TypeError)`; 4 shared builders in `tool_errors.py`; both wrappers call `raise_classified_tool_error` |
| New / updated tests | `uv run pytest tests/unit/test_tool_error_classification.py tests/unit/test_quotes_mapping.py::TestSharedEnvelopeBuilders tests/unit/test_price_history_mapping.py::TestSharedEnvelopeBuilders -q` | pass | 23 passed — the 13 tests added by the fix plus the pre-existing classification tests |
| Regression suite | `uv run pytest -q` | pass | **1787 passed, 0 skipped** (commit gate met) |
| Lint / type-check | — | not-run | No linter or type-checker configured in `pyproject.toml` (only `[tool.pytest.ini_options]`) |

## Output Excerpts

Post-fix reproduction script (`tmp/td004_verify_repro.py`):

```
PASS  get_quotes_tool raises classified ToolError for ConnectivityError
PASS  get_quotes_tool raises classified ToolError for ReauthorizationRequiredError
PASS  get_price_history_tool raises classified ToolError for ConnectivityError
PASS  get_price_history_tool raises classified ToolError for ReauthorizationRequiredError
PASS  quotes 503 returns provider_unreachable envelope (no exception)
PASS  quotes 401 returns reauth envelope (no exception)
PASS  price_history 503 returns envelope with symbol

td-004 post-fix reproduction: ALL CHECKS PASSED
```

Regression suite:

```
1787 passed in 34.84s
```

## Residual Risks

- Verification used in-process doubles (fixture clients / monkeypatched
  domain functions), consistent with how the assessment defined the repro;
  no live-provider call was made. The classification logic itself is
  provider-independent, so this does not weaken the verdict.
- A first pass of the reproduction script failed one check due to a flawed
  scratch stub (a hand-rolled double that raised instead of returning a 401
  response, so the domain never saw the 401); switching to the suite's
  `FakeQuotesClient(quotes_status=401)` fixture resolved it. Not a product
  defect — recorded for transparency.
- The escaped-error path remains a residual case by design: on the normal
  path the domains convert taxonomy errors to envelopes, so the classified
  boundary is defense-in-depth (this matches the assessment's framing).

## Recommendation

Close the bug — verified end-to-end: the assessment's dynamic reproduction
was exercised post-fix and no longer reproduces, the duplication is
structurally gone, all 13 fix tests pass, and the full suite (1787 tests,
0 skipped) is green. The fix is ready for the commit gate
(`/speckit.commit` or equivalent); no reopen needed.