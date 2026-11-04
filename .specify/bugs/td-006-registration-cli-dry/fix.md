# Bug Fix: TD-006 — Registration boilerplate ×6 and CLI dispatch ×4 (DRY)

- **Slug**: td-006-registration-cli-dry
- **Fixed**: 2026-11-04
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Replaced the six hand-written tool-registration blocks in
`server.py` with a single `_register_bound_tool` helper (client bound via
`functools.partial`), and the four duplicated CLI error-mapping arms in
`cli.py` with a `_COMMAND_RUNNERS` dispatch table plus one shared
`_run_command` mapper (auth keeps its distinct `_run_auth_command`).
Behavior — schemas, descriptions, exit codes, audit events — is
unchanged.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/server.py` | modified | New `_register_bound_tool(mcp, client, fn, *, name, description)`; `_register_tools` collapsed from ~187 lines of boilerplate to six helper calls; added `functools` import |
| `src/schwab_mcp/cli.py` | modified | New `_run_command`, `_run_auth_command`, `_run_serve_command`, and module-level `_COMMAND_RUNNERS` table; `main` is now a single table lookup; added `Callable`/`partial` imports |
| `tests/unit/test_tool_registration.py` | added | Pins the registration contract (names, schema shape, descriptions, client binding) |
| `tests/unit/test_cli_dispatch.py` | added | Pins the dispatch-table coverage and error mapping |
| `docs/CHANGELOG.md` | modified | 0.9.8 → Changed entry for TD-006 (constitution: docs in the same commit) |

## Diff Highlights

`server.py` — each registration is now one call; defaults live only in
the tool modules:

```python
def _register_bound_tool(mcp, client, fn, *, name, description) -> None:
    bound = functools.partial(fn, client)
    bound.__name__ = name          # SDK derives the arg-model name from this
    bound.__qualname__ = name
    register_tool(mcp, bound, name=name, description=description)
```

`cli.py` — one mapping, one table, one lookup:

```python
_COMMAND_RUNNERS: dict[str, Callable[[], None]] = {
    "auth": partial(_run_auth_command, run_auth),
    "renew": partial(_run_command, run_renew),
    "auth-status": partial(_run_command, run_auth_status),
    "serve": partial(_run_command, _run_serve_command),
}
```

Empirical check performed before implementation (guided by the
assessment's risk note): `functools.wraps` on a `(client, ...)` wrapper
leaks `client` into the SDK's argument model (`arg fields: ['client',
'x', 'y']`), while `partial` + manual `__name__` yields the correct
schema (`['x', 'y']`). Plain `partial` alone fails — the SDK requires
`__name__` — hence the explicit attribute assignment in the helper.

## Tests Added or Updated

- `tests/unit/test_tool_registration.py::TestToolRegistration::test_exactly_six_documented_tools_registered` — the six tool names and no others
- `...::test_schemas_do_not_expose_client` — regression guard against a `wraps`/`__wrapped__` schema leak re-exposing the bound client
- `...::test_descriptions_survive_byte_for_byte` — agent-facing description text cannot drift (docs/tools.md parity)
- `...::test_bound_client_is_passed_to_tool_function` — the partial binding actually delivers the client to the tool function
- `tests/unit/test_cli_dispatch.py::TestDispatchTable::test_dispatch_table_covers_all_commands` — all four commands have dispatch entries
- `...::TestRunCommandErrorMapping::test_success_exits_zero` / `test_auth_error_maps_to_exit_code` / `test_unexpected_error_exits_one_with_stderr` / `test_runner_self_exit_is_not_intercepted` — the shared mapping (0 / per-class exit code / 1 + "Unexpected error" / `SystemExit` passthrough for `run_renew`'s outcome codes)
- `...::TestAuthCommandSpecialHandling::test_concurrent_auth_maps_to_its_exit_code` / `test_cancelled_auth_maps_to_its_exit_code` — auth's distinct exception handling is preserved, not flattened

## Local Verification

- Commands run: `uv run pytest tests/unit/test_tool_registration.py tests/unit/test_cli_dispatch.py tests/unit/test_tool_arg_strictness.py -q` → 17 passed (new tests failed before implementation: 7 failed on missing symbols — Red→Green honored)
- Commands run: `uv run pytest -q` → **1800 passed, 0 skipped** (commit gate)
- Commands run: `uv run schwab-mcp --help` → usage unchanged, all four subcommands listed; `_COMMAND_RUNNERS` keys confirmed via import
- TDD note: the four registration-contract tests passed against the
  pre-refactor code (they pin existing behavior); the seven CLI tests
  failed on the missing `_run_command`/`_COMMAND_RUNNERS`/
  `_run_auth_command` symbols before implementation.

## Deviations from Assessment

- **`functools.wraps` rejected with new evidence**: the assessment
  already flagged the `__wrapped__` schema-leak risk as a caution; the
  fix went further and established empirically that `wraps` **does**
  leak `client` into the SDK argument model, and that a bare
  `partial` fails registration entirely (no `__name__`). The
  implemented helper is `partial` + manual `__name__`/`__qualname__`
  assignment — the manual assignment the assessment hoped to eliminate
  is retained, but centralized in one place instead of repeated ×6.
- **`**defaults` parameter dropped**: the ticket's sketch
  (`_register_bound_tool(..., **defaults)`) is unnecessary — every
  default already lives in the underlying tool function's signature,
  which `partial` preserves. Adding a defaults channel would create a
  second source of truth.
- **Dispatch shape**: the assessment offered option (a) (auth as a
  separate mapper) vs. option (b) (per-command pre-handler); option (a)
  was implemented as the assessment preferred, with `auth` also given a
  table entry (`partial(_run_auth_command, run_auth)`) so `main` is a
  single uniform lookup.
- **Scope addition**: `docs/CHANGELOG.md` was listed in the
  assessment's "Files likely to change" and was updated; no other
  out-of-scope files were touched.

## Follow-ups

- `docs/tools.md` remains the agent-facing interface doc; tool
  descriptions in `server.py` are now the code-side single copy — a
  future TD could extract them to a shared registry if drift ever
  bites (out of scope here).
- The `test_bound_client_is_passed_to_tool_function` recorder currently
  exercises `get_open_positions`; extending it to loop over all six
  tools would need per-tool valid-argument payloads — left as-is to
  keep the fix minimal.

## Follow-up verification

- Next gate: `/speckit.bug.test slug=td-006-registration-cli-dry`
