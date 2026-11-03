# Bug Fix: strict tool-argument validation — unknown arguments rejected loudly

- **Slug**: option-chain-dte-filter
- **Fixed**: 2026-11-03
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Every registered MCP tool now rejects unknown arguments with a validation
error naming the offending argument, instead of silently ignoring them (the
root cause of the reported "requested `expiration_date` absent from an
`ok` chain" symptom). The hardening is applied through one shared
registration helper (`server.register_tool`) used by all six tools, and the
advertised input schemas now set `additionalProperties: false`.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/server.py` | added `register_tool()`; added `_register_tools()`; modified `run_serve()` | `register_tool` wraps `mcp.add_tool` and hardens the SDK's per-tool argument model (`extra='forbid'` + forced rebuild) and the advertised schema (`additionalProperties: false`). The six inline registrations were extracted verbatim into `_register_tools(mcp, client)` and now route through `register_tool`. |
| `tests/unit/test_tool_arg_strictness.py` | added (new file) | Regression tests at the real registration path: unknown arguments rejected on every tool, the exact reported call shape rejected, rejection happens before any provider call, known arguments still accepted, missing required arguments still rejected, all advertised schemas forbid additional properties. |
| `tests/integration/test_serve.py` | modified | `FakeMCPServer` now models the SDK surface `register_tool` touches (`_tool_manager._tools`, `fn_metadata.arg_model`, `parameters`) so the serve flow exercises the hardening. |
| `tests/performance/test_startup_budget.py` | modified | Same `FakeMCPServer` surface update (startup-budget test constructs the real registration path). |
| `docs/tools.md` | modified | New "Strict tool arguments" note in the *Tool error surface (MCP boundary)* section: unknown argument names fail with a validation error naming the argument, never silently ignored. |
| `docs/CHANGELOG.md` | modified | New `[0.9.6]` `Fixed` entry describing the caller-visible behavior change. |
| `pyproject.toml` | modified | Version bump `0.9.5` → `0.9.6` (project release pattern: every bug fix ships as a patch bump). |

## Diff Highlights

`register_tool` — the shared hardening (one place, applied to every tool):

```python
def register_tool(mcp: MCPServer, fn: Any, *, name: str, description: str) -> None:
    mcp.add_tool(fn, name=name, description=description)
    tool = mcp._tool_manager._tools[name]
    arg_model = tool.fn_metadata.arg_model
    # Pydantic v2 only honours a post-hoc model_config change after a
    # forced rebuild of the validation schema.
    arg_model.model_config = ConfigDict(extra="forbid")
    arg_model.model_rebuild(force=True)
    tool.parameters["additionalProperties"] = False
```

Effect at the MCP boundary (verified in the new tests):

```text
call get_option_chain {"symbol":"LLY","expiration_date":"2027-01-15"}
→ ToolError: ... validation error for get_option_chainWrapperArguments
             expiration_date — Extra inputs are not permitted
```

## Tests Added or Updated

- `tests/unit/test_tool_arg_strictness.py::TestUnknownArgumentsRejected` —
  every registered tool rejects an unknown argument with an error naming it;
  the exact reported call (`expiration_date` on `get_option_chain`) fails
  loudly; rejection occurs before any provider call (guarded by a
  fail-loudly client stand-in).
- `tests/unit/test_tool_arg_strictness.py::TestKnownArgumentsStillAccepted` —
  known arguments pass the hardened schema unchanged (`get_quotes` reaches
  its tool body and returns the `validation_error` envelope) and a missing
  required argument still errors as before (no over-rejection).
- `tests/unit/test_tool_arg_strictness.py::TestAdvertisedSchema` — all six
  advertised input schemas set `additionalProperties: false`.
- `tests/integration/test_serve.py` / `tests/performance/test_startup_budget.py`
  — fakes updated to the SDK registration surface; existing serve-flow and
  startup-budget assertions unchanged and passing.

## Local Verification

- Commands run:
  - `uv run pytest tests/unit/test_tool_arg_strictness.py -q` → RED before
    implementation (`ImportError: cannot import name '_register_tools'`),
    6 passed after. The underlying silent-drop defect itself was
    demonstrated offline in the assessment (SDK experiment: extra argument
    returned `is_error=False` and was discarded).
  - `uv run pytest -q` (full suite) → **1730 passed, 0 skipped** (also
    re-run after docs/version changes: same result).
  - `uv run python -m py_compile src/schwab_mcp/server.py` → OK.
- Manual checks: an isolated `MCPServer` experiment confirmed unknown
  arguments raise `ToolError` ("Extra inputs are not permitted") while a
  known-argument call still succeeds, and `list_tools()` reflects
  `additionalProperties: false` in the advertised `input_schema`.

## Deviations from Assessment

- **Scope expansion (logged per the command contract)**: two existing test
  fakes outside the assessment's "Files likely to change" list required
  updates — `FakeMCPServer` in `tests/integration/test_serve.py` and in
  `tests/performance/test_startup_budget.py` — because both construct the
  real registration path, which now touches the SDK's `Tool` object.
  No production behavior change beyond the assessment's plan.
- The assessment offered mechanism (a) (post-registration
  `extra='forbid'` + forced rebuild) or (b) (tool-manager override);
  (a) was implemented and verified to work on the installed `mcp` 2.3.0,
  so no override layer was needed. The only SDK-internal access is
  `mcp._tool_manager._tools[name]`, documented in the helper and pinned
  by the new tests.

## Follow-ups

- **`expiration_date` as a first-class parameter** on `get_option_chain`
  (and possibly `get_option_expiration_chain`) remains a candidate feature
  spec (per-expiration chains); the strict-argument rejection now makes
  requests for it fail loudly instead of silently degrading.
- **SDK-upgrade watch**: the hardening mutates the SDK's registration
  artifacts (`_tool_manager._tools`, `fn_metadata.arg_model`, `parameters`);
  re-run `tests/unit/test_tool_arg_strictness.py` after any `mcp` version
  bump (currently pinned `mcp>=1.0.0`, installed 2.3.0).
- The stale comment in `tests/integration/test_serve.py` ("the real `mcp`
  package uses `Server`, not `MCPServer`") predates the SDK 2.x migration;
  correct it when that file is next touched.