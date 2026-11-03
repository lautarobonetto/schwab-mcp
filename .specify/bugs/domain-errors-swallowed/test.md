# Bug Verification: Domain errors swallowed behind "Error executing tool <name>"

- **Slug**: domain-errors-swallowed
- **Tested**: 2026-11-03
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The bug no longer reproduces: a domain failure inside `get_option_chain` now
reaches the MCP client with the actionable, classified text
(`provider_unreachable:` / `reauth_needed:`), where the pre-fix mechanism
produced only `Error executing tool get_option_chain`. All 1724 tests pass,
including the 10 new regression tests; no regressions found.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | In-process script: real `MCPServer` + real SDK `call_tool`, patched inner `get_option_chain` raising `ConnectivityError` / `ReauthorizationRequiredError` | pass | Client-visible text ends with `provider_unreachable: Check connectivity; stored tokens not modified: Schwab API unreachable after retry; …` and `reauth_needed: Run schwab-mcp auth: …` respectively; exact type `ToolError`, not the SDK crash wrapper |
| Gate contrast (pre-fix mechanism) | Same in-process setup with a **plain** tool function raising `ConnectivityError` (no wrapper conversion) | pass | Client text is exactly `"Error executing tool get_option_chain"` — the reported payload; proves the reproduction exercises the real SDK gate |
| New / updated tests | `uv run pytest tests/unit/test_tool_error_classification.py -q` | pass | 10 passed |
| Regression suite | `uv run pytest -q` (full suite, commit gate) | pass | 1724 passed, 0 skipped |
| Lint / type-check | — | skipped | No linter/type-checker configured in `pyproject.toml` (only `[tool.pytest.ini_options]`); nothing to run |
| Live provider reproduction (Schwab unreachable / `$SPX` timeout) | — | skipped | Network-dependent and time-costly; deferred — the in-process reproduction exercises the identical SDK gate the live path hits |

## Output Excerpts

Gate contrast (pre-fix mechanism, matching the reported payload):

```
CONTRAST (pre-fix mechanism):
  client text: "Error executing tool get_option_chain"
```

Post-fix, through the real `MCPServer.call_tool`:

```
POSTFIX connectivity:
  raised ToolError: "Error executing tool get_option_chain: provider_unreachable: Check connectivity; stored tokens not modified: Schwab API unreachable after retry; stored tokens were not modified"
POSTFIX reauth:
  raised ToolError: "Error executing tool get_option_chain: reauth_needed: Run schwab-mcp auth: run: schwab-mcp auth"
REPRODUCTION (in-process, real MCP SDK): PASS
```

Regression suites:

```
tests/unit/test_tool_error_classification.py → 10 passed
full suite → 1724 passed in 40.30s
```

## SDK-behaviour nuance (not a defect)

`Tool.run()` (`mcp/server/mcpserver/tools/base.py:208-210`) re-raises every
deliberate `ToolError` as `ToolError(f"Error executing tool {name}: {exc}")`
— its own prefix, with the tool's message **preserved after it** ("An
anticipated failure keeps its own text after the prefix"). So the client
sees `Error executing tool get_option_chain: provider_unreachable: …` rather
than a bare `provider_unreachable: …`. This is the same shape validation
errors have always surfaced through, and the classification prefix and
actionable text both reach the client, so clients can distinguish
connectivity/retryable from auth-required from bad request (the bug's
requirement). The crash case (raw exception) is still distinguished by
losing the message entirely. `docs/tools.md` documents matching by the
classification prefix.

## Residual Risks

- No live-against-Schwab run was performed (skipped, network-dependent). The
  in-process reproduction hits the exact SDK gate the stdio transport uses,
  but the end-to-end wire shape (`isError` content serialization) was not
  exercised over a real stdio session.
- Clients matching error text should look for the classification substring
  (`provider_unreachable:` / `reauth_needed:`), not a bare message prefix,
  because the SDK prepends `Error executing tool <name>: `.
- The two error styles (classified `ToolError` text for three tools;
  structured envelopes for `get_open_positions`/`get_quotes`/`get_price_history`)
  coexist, as documented in `docs/tools.md`.

## Recommendation

Close the bug — verified in-process end-to-end through the real MCP SDK
gate, with the pre-fix mechanism reproduced as contrast and the full
regression suite green. For extra confidence, the optional live check (a
`$SPX` slow-chain or provider-outage invocation surfacing
`provider_unreachable:` to a real stdio client) can be folded into routine
usage; it is not required to close.