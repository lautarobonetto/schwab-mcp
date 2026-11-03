# Bug Fix: Domain errors swallowed behind "Error executing tool <name>"

- **Slug**: domain-errors-swallowed
- **Fixed**: 2026-11-03
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

The three tool wrappers that leaked auth-taxonomy exceptions
(`get_option_chain_tool`, `get_option_expiration_chain_tool`,
`get_transaction_history_tool`) now convert `ConnectivityError` /
`ReauthorizationRequiredError` (and every other caught domain type)
through a new shared helper, `schwab_mcp.tool_errors.raise_classified_tool_error`,
into a MCP `ToolError` carrying a classified, actionable message
(`provider_unreachable:` / `reauth_needed:` prefixes) — so clients can
distinguish retryable from auth-required from bad request instead of
seeing only the SDK's opaque `Error executing tool <name>`.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/tool_errors.py` | added | Shared helper `raise_classified_tool_error(exc)`: `ReauthorizationRequiredError` → `reauth_needed: <msg>`, `ConnectivityError` → `provider_unreachable: <msg>`, anything else → `<msg>` unchanged; original preserved as `__cause__` (one implementation of the mapping, per DRY) |
| `src/schwab_mcp/options_chain.py` | modified | `get_option_chain_tool` and `get_option_expiration_chain_tool` catch `AuthError` and route all caught domain types through the helper; docstrings updated |
| `src/schwab_mcp/transactions.py` | modified | `get_transaction_history_tool` catches `AuthError` alongside `InstrumentNotFoundError`/`ValueError`/`TypeError`, all through the helper; docstring updated |
| `tests/unit/test_tool_error_classification.py` | added | 10 regression tests: helper mapping (both prefixes + no-prefix passthrough, exact type + `__cause__`) and per-wrapper taxonomy-error conversion for all three tools |
| `docs/tools.md` | modified | New cross-cutting "Tool error surface (MCP boundary)" section documenting the prefix contract and which tools use envelopes instead |
| `docs/CHANGELOG.md` | modified | Entry under `[0.9.4]` Fixed |

## Diff Highlights

New helper (`src/schwab_mcp/tool_errors.py`):

```python
def raise_classified_tool_error(exc: Exception) -> NoReturn:
    from mcp.server.mcpserver.exceptions import ToolError

    if isinstance(exc, ReauthorizationRequiredError):
        raise ToolError(f"reauth_needed: {exc}") from exc
    if isinstance(exc, ConnectivityError):
        raise ToolError(f"provider_unreachable: {exc}") from exc
    raise ToolError(str(exc)) from exc
```

Wrapper change (shape identical in all three tools):

```python
    except (AuthError, ChainDataError, ValueError, TypeError) as exc:
        raise_classified_tool_error(exc)
```

Client-visible effect for the reported case:

```json
{"content":[{"text":"provider_unreachable: Check connectivity; stored tokens were not modified: Schwab API unreachable after retry; stored tokens were not modified","type":"text"}],"isError":true}
```

instead of `{"content":[{"text":"Error executing tool get_option_chain",...}]}`.

## Tests Added or Updated

- `tests/unit/test_tool_error_classification.py::TestClassifiedToolErrorHelper` — helper mapping: prefix per taxonomy class, no-prefix passthrough for validation types, exact `ToolError` type and `__cause__` preservation
- `tests/unit/test_tool_error_classification.py::TestOptionChainToolClassifiedErrors` — `get_option_chain_tool` converts `ConnectivityError`/`ReauthorizationRequiredError` to classified `ToolError`; explicit distinguishability test for the two prefixes
- `tests/unit/test_tool_error_classification.py::TestOptionExpirationChainToolClassifiedErrors` — same contract for `get_option_expiration_chain_tool`
- `tests/unit/test_tool_error_classification.py::TestTransactionHistoryToolClassifiedErrors` — same contract for `get_transaction_history_tool`

Tests use `type(excinfo.value) is ToolError` (not just `pytest.raises(ToolError)`), because the SDK's `UnexpectedToolError` subclasses `ToolError` and would pass a bare match even with the bug present — the discrimination caveat flagged in the assessment.

## Local Verification

- `uv run pytest tests/unit/test_tool_error_classification.py -q` → 10 passed (Red before the fix: `ModuleNotFoundError: schwab_mcp.tool_errors`, then raw exceptions propagated)
- `uv run pytest tests/unit/test_option_expirations.py tests/unit/test_transactions_live_response.py tests/unit/test_transactions_filter_query.py tests/unit/test_options_chain_body_limit.py tests/unit/test_quotes_validation.py tests/unit/test_price_history_validation.py -q` → 284 passed (no regressions in the touched modules)
- `uv run pytest -q` (full suite, commit gate) → **1724 passed, 0 skipped**
- Manual check of the SDK contract: with the fix, the wrapped function raises a deliberate `ToolError`, which `Tool.run()` passes through unwrapped (`tools/base.py:161` only wraps non-`ToolError`), so the classified message reaches the client.

## Deviations from Assessment

- None in substance. Two refinements within the assessment's stated shape:
  - The helper handles **all** caught domain types (not only the auth taxonomy): non-auth errors surface as unprefixed `ToolError(str(exc))`, which keeps the pre-fix validation behavior byte-identical while satisfying the DRY "one implementation of the mapping" goal. `quotes`/`price_history` wrappers were left untouched (the assessment marked migrating them "optional"; those tools already return structured envelopes for provider/auth states, and their only wrapper conversions are `ValueError`/`TypeError`, which the helper would treat identically — no behavioral gain for the churn).
  - Doc updates went into `docs/tools.md` (new cross-cutting "Tool error surface" section) and `docs/CHANGELOG.md`, both listed in the assessment's "Files likely to change".

## Follow-ups

- Future consolidation (optional, out of scope here): the six per-tool wrappers in `server.py`/modules could share one registration-level decorator; noted in the assessment as the larger alternative.
- When live-testing against Schwab (`/speckit.bug.test`), confirm the `$SPX` timeout case now surfaces `provider_unreachable:` to the MCP client.
- `docs/tools.md` now documents two coexisting error styles (classified `ToolError` text for three tools, structured envelopes for `get_open_positions`/`get_quotes`/`get_price_history`); if a future spec unifies them, update that section.