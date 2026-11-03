# Bug Verification: strict tool-argument validation — unknown arguments rejected loudly

- **Slug**: option-chain-dte-filter
- **Tested**: 2026-11-03
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The reported call shape (`get_option_chain` with `expiration_date`) no
longer returns a silent `ok`: against the real production registration
path it fails loudly with a `ToolError` naming the offending argument,
before any provider call. All new regression tests pass and the full
suite is green (1730 passed, 0 skipped); no regressions found.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | `MCPServer` + real `server._register_tools`; `call_tool("get_option_chain", {"symbol":"LLY","expiration_date":"2027-01-15"})` | pass | Rejected with `ToolError … expiration_date — Extra inputs are not permitted`. The client stand-in raises on any provider call, so the rejection provably happens at argument validation — no network needed post-fix. |
| Reproduction (differential, pre-fix path) | Same call through unhardened `mcp.add_tool` (SDK 2.3.0 default) | pass (contrast) | Still silently drops the argument (`is_error=False`, tool runs without it) — confirming the before/after difference at the boundary, matching the assessment's root-cause finding. |
| Advertised schemas | `list_tools()` on the real registration path | pass | All 6 tool schemas set `additionalProperties: false`. |
| New / updated tests | `uv run pytest tests/unit/test_tool_arg_strictness.py -q` | pass | 6 passed (rejection on every tool, known args accepted, missing-required still errors, schema assertions). |
| Regression suite | `uv run pytest -q` | pass | 1730 passed, 0 skipped, ~35 s — includes serve-flow integration and startup-budget tests over the changed registration path. |
| Lint / type-check | — | not-run | No lint or type-check tool is configured in `pyproject.toml` (only `[tool.pytest.ini_options]`, `[tool.setuptools]`). |
| Live served-instance confirmation | `schwab-mcp serve` + real LLY call | skipped | Network- and auth-dependent; not run without explicit user consent. Not required to prove the mechanism: the defect was the SDK silently dropping the argument, which is fully observable offline, and post-fix the rejection precedes any network activity. |

## Output Excerpts

```text
POST-FIX RESULT: rejected -> ToolError | Error executing tool get_option_chain:
1 validation error for get_option_chainArguments
expiration_date
  Extra inputs are not permitted [type=extra_forbidden, ...

UNHARDENED SDK PATH: silently dropped -> is_error: False | content: {"symbol": "LLY"}

SCHEMAS additionalProperties=false on all 6 tools: True
```

```text
tests/unit/test_tool_arg_strictness.py … 6 passed in 0.31s
uv run pytest -q … 1730 passed in 34.61s
```

## Residual Risks

- The fix touches SDK registration artifacts (`_tool_manager._tools`,
  `fn_metadata.arg_model`, `parameters` on the `Tool` object); a future
  `mcp` SDK upgrade could move these — `tests/unit/test_tool_arg_strictness.py`
  will catch it, but re-run it after any SDK bump.
- Callers that previously relied (accidentally) on extra arguments being
  ignored will now see validation errors — intended, caller-visible, and
  documented in `docs/tools.md` and the `0.9.6` CHANGELOG entry.
- A live end-to-end confirmation through a served instance with real
  credentials was skipped (see table); the offline evidence fully covers
  the defect mechanism and its removal.

## Recommendation

Close the bug — the reported symptom no longer reproduces: the exact
reported call fails loudly at the MCP boundary with the offending
argument named, all new regression tests pass at the real registration
path, and the full suite is green with no skipped tests. The optional
follow-up feature (a first-class `expiration_date` parameter) should be
tracked as its own spec, not a reopening of this bug.