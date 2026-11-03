# Bug Assessment: Domain errors swallowed behind "Error executing tool <name>"

- **Slug**: domain-errors-swallowed
- **Created**: 2026-11-03
- **Source**: pasted text
- **Verdict**: valid
- **Severity**: medium

## Report (verbatim or summarized)

Pasted text, quoted in full (header condensed):

> **Bug 2 — domain errors are swallowed: caller sees only "Error executing tool \<name\>"**
>
> **Severity: medium (diagnostics lost; retryable/auth errors indistinguishable at the MCP boundary).**
>
> When Bug 1 fires, the MCP response is:
>
> ```
> {"content":[{"text":"Error executing tool get_option_chain","type":"text"}],"isError":true}
> ```
>
> The server's own `ConnectivityError` message ("Schwab API unreachable after retry; stored tokens
> were not modified") never reaches the client — FastMCP wraps it in
> `UnexpectedToolError("Error executing tool ...")` (full traceback visible only on stderr, which a
> stdio client normally doesn't see). Compare with validation errors, which DO surface nicely
> (e.g. `{"outcome":"validation_error","detail":"too_many_symbols","limit":20,...}` for
> `get_quotes` with 21 symbols).
>
> Suggested fix: map the domain errors (`ConnectivityError`, `ReauthorizationRequiredError`,
> `ChainDataError`, …) to structured error content at the tool wrapper level (like the validation
> path already does), so MCP clients can distinguish "connectivity/retryable" from "auth required"
> from "bad request".

Note: "Bug 1" is the previously triaged `spx-chain-body-limit` / `spx-delta-timeout` family;
`spx-delta-timeout/fix.md` line 101 explicitly defers this wrapper issue: *"the generic
'Error executing tool …' wrapper … is still open; triage it separately."*

## Symptom

When a domain (non-validation) error is raised inside a tool — e.g. `ConnectivityError` after
retry exhaustion, `ReauthorizationRequiredError` on 401/403, or `ChainDataError` — the MCP client
receives only `isError: true` with the opaque text `Error executing tool <name>`; the actionable
message (`"Run schwab-mcp auth"`, `"Check connectivity; stored tokens were not modified"`) never
reaches it. Expected: the client should see the actionable, classified error so it can decide
between retrying, re-authorizing, or fixing the request.

## Reproduction

1. Start the server with valid tokens (`schwab-mcp serve`).
2. Call `get_option_chain` while the provider is unreachable / returns 5xx (or exhausts retries,
   e.g. the `$SPX` slow-chain case): `tokens.retry_call` raises
   `ConnectivityError("Schwab API unreachable after retry; stored tokens were not modified")`
   (`src/schwab_mcp/tokens.py:372-374`), and `get_option_chain` re-raises it
   (`src/schwab_mcp/options_chain.py:828-834`).
3. Observe the MCP response: `{"content":[{"text":"Error executing tool get_option_chain",...}],"isError":true}`;
   the actionable message is only on stderr.

Live occurrences of step 2 were recorded in `.specify/bugs/spx-delta-timeout/` (45.7 s timeout →
`ConnectivityError`) and `.specify/bugs/spx-chain-body-limit/`.

[NEEDS CLARIFICATION: none — the wrapper-gating mechanism was verified directly in the installed
SDK source, see Root Cause.]

## Suspected Code Paths

- `.venv/lib/python3.11/site-packages/mcp/server/mcpserver/tools/base.py:161` — the gate: any
  exception that is not already a `ToolError` is wrapped in
  `UnexpectedToolError(f"Error executing tool {self.name}")`, whose message is all the client
  sees (verified in the installed SDK; `UnexpectedToolError` subclasses `ToolError`, so only
  deliberate `ToolError` messages pass through).
- `src/schwab_mcp/options_chain.py:873-886` (`get_option_chain_tool`) — converts only
  `(ChainDataError, ValueError, TypeError)` to `ToolError`; `ConnectivityError` and
  `ReauthorizationRequiredError` (raised at `:823-834`) escape to the SDK wrapper.
- `src/schwab_mcp/options_chain.py:1118-1136` (`get_option_expiration_chain_tool`) — converts
  only `(ValueError, TypeError)`; both auth-taxonomy errors escape.
- `src/schwab_mcp/transactions.py:1291-1307` (`get_transaction_history_tool`) — converts only
  `(InstrumentNotFoundError, ValueError, TypeError)`; both auth-taxonomy errors escape.
- Contrast (already correct): `src/schwab_mcp/positions.py:466-490` returns structured
  `PositionsResult` envelopes (`transient_failure` / `reauth_needed`), and `quotes.py` /
  `price_history.py` return `provider_unreachable` / `reauth_needed` envelopes — those tools
  never leak raw taxonomy errors.

## Root Cause Hypothesis

**Confidence: high.** The tool-boundary wrappers in `options_chain.py` and `transactions.py`
convert *some* exceptions to `ToolError` (the validation path) but do not catch the auth-taxonomy
errors (`ConnectivityError`, `ReauthorizationRequiredError`, both subclasses of `AuthError`).
Those propagate out of the tool function, and the installed MCP SDK's `Tool.run()` wraps any
non-`ToolError` into `UnexpectedToolError(f"Error executing tool {name}")` — deliberately
discarding the original message from the client-visible result (only `__cause__` reaches stderr).
Validation errors surface nicely precisely because their wrappers already raise `ToolError`.

One caveat for the fix phase: `pytest.raises(ToolError)` in existing wrapper tests
(e.g. `tests/unit/test_option_expirations.py:342-377`) would also pass if the raw exception were
SDK-wrapped, because `UnexpectedToolError` subclasses `ToolError`. New regression tests must
assert the exact type/message (e.g. `type(exc) is ToolError` plus a message match) to actually
discriminate the fix.

## Proposed Remediation

**Preferred**: map the auth-taxonomy domain errors to `ToolError` at the tool-wrapper level,
using the established validation-error pattern, with a shared helper so the mapping lives in one
place (DRY). Create a small helper (e.g. in `errors.py` or a new `tool_errors.py`) such as
`raise_tool_error(exc)` that raises `ToolError` with a *classified, actionable* message — for
example prefixing the taxonomy outcome so clients can distinguish classes:

- `ConnectivityError` → `ToolError("provider_unreachable: Check connectivity; stored tokens were
  not modified: Schwab API unreachable after retry …")`
- `ReauthorizationRequiredError` → `ToolError("reauth_needed: Run schwab-mcp auth …")`
- `AuthError` (catch-all) → `ToolError(str(exc))` with its actionable base message.

Then extend the three affected wrappers — `get_option_chain_tool`, `get_option_expiration_chain_tool`,
`get_transaction_history_tool` — to route `AuthError` (covering both `ConnectivityError` and
`ReauthorizationRequiredError`) through the helper, alongside their existing
`ChainDataError`/`InstrumentNotFoundError`/`ValueError`/`TypeError` conversions. Optionally
migrate `quotes`/`price_history`/`positions`-style wrappers to the same helper for uniformity.
`ToolError` keeps the existing MCP contract (deliberate error, message reaches the client,
`isError: true`) without changing any tool's return shape, matching how validation errors already
behave and how `docs/tools.md` documents tool errors.

**Alternatives**:

- *Structured result envelopes* (return `{"outcome": "provider_unreachable", "retryable": true,
  …}` instead of raising), mirroring `positions.py`/`quotes.py`. Trade-off: richer and
  machine-readable, but introduces a second error style for these tools (envelope vs `isError`),
  requires contract/docs changes for return types, and agents that check `isError` lose the
  signal. More invasive than the `ToolError` path.
- *Single server-level wrapper* in `server.py` (a decorator around every registered tool that
  converts domain exceptions once, instead of per-tool try/except). Trade-off: most DRY at the
  registration layer and eliminates the six copy-pasted wrappers, but the per-tool wrappers also
  carry tool-specific exception sets (`ChainDataError`, `InstrumentNotFoundError`); a server-level
  map can handle `AuthError` generically while per-tool wrappers keep their specific types. Could
  be combined with the preferred fix later, but is a larger refactor than the bug requires.

**Files likely to change**:

- `src/schwab_mcp/options_chain.py` (both tool wrappers)
- `src/schwab_mcp/transactions.py` (tool wrapper)
- `src/schwab_mcp/errors.py` or new `src/schwab_mcp/tool_errors.py` (shared helper)
- `docs/tools.md` (document that provider/auth failures surface as classified `ToolError` text)
- `docs/CHANGELOG.md` (change history, same commit per constitution)

**Tests to add or update**:

- Unit tests asserting the three affected wrappers raise exactly `ToolError` (assert
  `type(exc) is ToolError`, not just `pytest.raises(ToolError)` — see caveat above) with an
  actionable, classified message when the inner call raises `ConnectivityError` and
  `ReauthorizationRequiredError` (fakes already exist: `tests/integration/test_options_chain.py:926+`,
  `tests/integration/test_option_expirations.py:294-340`).
- Extend `tests/unit/test_option_expirations.py:TestToolWrapperToolErrorConversion` and
  `tests/unit/test_transactions_live_response.py:TestToolErrorConversion` with the taxonomy-error
  cases.
- One test asserting the classification prefix distinguishes `provider_unreachable` from
  `reauth_needed` in the surfaced message.

## Risks & Considerations

- **API surface**: error text becomes client-visible contract; keep the wording aligned with
  `docs/tools.md` and the taxonomy messages (`errors.py`) so agents can pattern-match.
- **Over-catching**: converting *all* `AuthError` subclasses to `ToolError` must not mask genuine
  server bugs — restrict the catch-all to the intended taxonomy and let unexpected exceptions
  still crash into `UnexpectedToolError` (stderr) where they belong.
- **Consistency**: `positions`/`quotes`/`price_history` already return envelopes; two error styles
  will coexist. Document which style each tool uses in `docs/tools.md` to avoid agent confusion.
- **Observability**: stderr logging of the original exception (SDK behavior) is unchanged; audit
  events (`options_chain_query_failure`, etc.) already fire before the raise.

## Open Questions

- None blocking. (Choice between `ToolError` text and structured envelopes is a design decision
  for `/speckit.bug.fix`; the preferred path matches the existing validation-error contract.)