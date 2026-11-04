# Bug Assessment: TD-006 — Registration boilerplate ×6 and CLI dispatch ×4 (DRY)

- **Slug**: td-006-registration-cli-dry
- **Created**: 2026-11-04
- **Source**: pasted text (TD-006 tech-debt ticket)
- **Verdict**: valid
- **Severity**: low

## Report (verbatim or summarized)

Pasted ticket, quoted verbatim:

> ### TD-006 — Registration boilerplate x6 and CLI dispatch x4 (DRY)
>
> **Area:** `src/schwab_mcp/server.py:195-381`, `src/schwab_mcp/cli.py:390-423`
>
> - `server.py`: six tool registrations repeat the same structure —
>   wrapper closure, manual `__name__`/`__qualname__` assignment,
>   `register_tool(...)` with description (~15 lines each). Every new tool
>   repeats it.
> - `cli.py`: the four commands (`renew`, `auth-status`, `serve`, plus
>   `auth`) repeat the identical
>   `except AuthError / except Exception / else sys.exit(0)` block.
>
> **Refactor:** `_register_bound_tool(mcp, fn, name, description, **defaults)`
> using `functools.wraps`/`partial` in `server.py`; a dispatch table
> `{command: runner}` with one `_run_command(fn)` wrapper in `cli.py`.

No URL supplied; no fetch performed.

## Symptom

This is tech debt, not a runtime defect: nothing misbehaves today. The
"symptom" is structural duplication — each of the six MCP tool
registrations repeats a ~15-line wrapper + metadata + `register_tool`
ceremony, and each of the four CLI commands repeats the same
try/except/exit scaffolding. Expected state: one helper per concern, so a
new tool or CLI command is a table entry, not a copy-paste.

## Reproduction

Not a runtime bug — verified by code inspection instead:

1. Open `src/schwab_mcp/server.py:195-381` (`_register_tools`): six
   near-identical blocks (import, closure binding `client`, manual
   `__name__`/`__qualname__` assignment, `register_tool(...)` with a
   description string), one per tool
   (`get_open_positions`, `get_transaction_history`, `get_option_chain`,
   `get_quotes`, `get_price_history`, `get_option_expiration_chain`).
2. Open `src/schwab_mcp/cli.py:374-425` (`main`): four `elif
   args.command == ...` arms each wrapping a runner in
   `try / except AuthError / except Exception / else sys.exit(0)`.
3. Note: adding a seventh tool or fifth command requires copying the
   pattern again.

## Suspected Code Paths

- `src/schwab_mcp/server.py:195` — `_register_tools`; lines 204-381 hold
  the six repeated registration blocks. `register_tool` itself
  (`server.py:50-81`) is already shared; the duplication is the wrapper
  closure + metadata ceremony around each call.
- `src/schwab_mcp/cli.py:374-425` — the four command arms in `main`.
  Important nuance: the report overstates uniformity. The `auth` arm
  (lines 374-391) additionally handles `ConcurrentAuthError` (with an
  `auth_event` audit log) and `AuthorizationCancelledError`, and has **no**
  generic `except Exception` clause; `renew`/`auth-status`/`serve` share
  the plain `AuthError`/`Exception`/`else` shape. Any dispatch-table
  refactor must preserve `auth`'s distinct handling.
- `src/schwab_mcp/positions.py:431`, `src/schwab_mcp/transactions.py:1307`,
  `src/schwab_mcp/options_chain.py:857` and `:1118`,
  `src/schwab_mcp/quotes.py:392`, `src/schwab_mcp/price_history.py:637` —
  the six underlying tool functions, all taking `client` as the first
  positional parameter. This uniform shape is what makes a
  `functools.partial(fn, client)` refactor viable.
- `tests/unit/test_tool_arg_strictness.py:72-78` — builds the real server
  via `_register_tools`; this is the regression net that any registration
  refactor must keep green (schema shape, `extra='forbid'`,
  `additionalProperties: false`).

## Root Cause Hypothesis

High confidence. The duplication is by construction, not by accident:
`_register_tools` grew one hand-written block per feature spec
(003, 006, 008, 010, 011, 012), and `main()` grew one `elif` arm per
command. No abstraction was extracted when the second and third instances
appeared. A related risk hides inside the ticket's proposed remedy:
`functools.wraps` copies `__wrapped__` onto the wrapper, and
`inspect.signature` (and therefore the SDK's Pydantic argument-model
generation) follows `__wrapped__` by default — that would leak the
underlying function's `client` parameter into the advertised input
schema, regressing bug `option-chain-dte-filter`'s strictness work.
`functools.partial(fn, client)` avoids this (partial-bound positional
arguments are dropped from the inspected signature), so `partial` is the
safe mechanism, not `wraps`.

## Proposed Remediation

**Preferred**:

1. `server.py` — add `_register_bound_tool(mcp, fn, name, description)`
   that does `register_tool(mcp, functools.partial(fn, client), ...)`
   inside `_register_tools` (passing `client` once). Each tool then
   collapses to one call: import, `_register_bound_tool(..., name=...,
   description=...)`. Do **not** apply `functools.wraps` to the partial —
   it would re-expose `client` in the schema via `__wrapped__`. Keep the
   six description strings verbatim (they are agent-facing contract text
   mirrored in `docs/tools.md`).
2. `cli.py` — replace the four `elif` arms with a dispatch dict
   `{command: runner}` and a single `_run_command(fn)` executing the
   shared `try / except AuthError / except Exception / else sys.exit(0)`.
   Because `auth` has extra exception types (and no generic `Exception`
   catch), either (a) keep `auth` as a pre-arm before the generic
   dispatcher, or (b) make the table value carry an optional
   per-command pre-handler that maps `ConcurrentAuthError` /
   `AuthorizationCancelledError` first. Preserve the lazy
   `from schwab_mcp.server import run_serve` import inside the `serve`
   arm (it exists so the CLI can patch imports before the server module
   loads) — a dict of plain callables must not defeat that laziness; use
   a thunk or import inside the runner.

**Alternatives**:

- Keep per-tool closures but move them into a data-driven loop
  `(module, func_name, description)` tuples — still removes the
  `__name__`/`__qualname__` ceremony but keeps closure boilerplate;
  strictly worse than `partial`.
- Decorator-based tool registration on the tool modules themselves —
  larger blast radius (touches six feature modules and the
  late-import/patching story), not justified for a DRY fix.

**Files likely to change**:

- `src/schwab_mcp/server.py`
- `src/schwab_mcp/cli.py`
- `tests/unit/test_tool_arg_strictness.py` (should pass unchanged — that
  is the point)
- `docs/CHANGELOG.md` (per constitution: docs updated in the same commit)

**Tests to add or update**:

- Unit test: `_register_tools` registers exactly the six expected tool
  names; the advertised schema of each tool contains **no** `client`
  parameter (guards the `wraps`/`__wrapped__` regression) — partially
  covered by `test_tool_arg_strictness.py` `VALID_ARGUMENTS`, make it
  explicit.
- Unit test: every description string survives the refactor byte-for-byte
  (agents depend on them; `docs/tools.md` parity).
- CLI unit test: dispatch covers all four commands; `AuthError` → its
  `exit_code`, generic `Exception` → 1 with "Unexpected error" on stderr,
  success → 0; `auth` still maps `ConcurrentAuthError` /
  `AuthorizationCancelledError` to their codes and still emits the
  `auth_failure/refused_concurrent` audit event.
- Existing `tests/integration/test_failures.py:1032` ("Unexpected error"
  not in stderr) must stay green.

## Risks & Considerations

- **Schema regression**: `functools.wraps` (as the ticket suggests) would
  leak `client` into every tool's input schema via `__wrapped__` — use
  `partial` only.
- **Silent behavior change in CLI**: a naive uniform `_run_command` would
  add a generic `except Exception` to `auth` (it deliberately has none
  today) or drop the concurrent-auth audit event; either is a contract
  change (contracts/cli.md) and must be preserved or consciously decided.
- **Strictness hardening**: every registration must still flow through
  `register_tool` (`extra='forbid'` + `additionalProperties: false`);
  a helper that bypasses it would silently regress bug
  `option-chain-dte-filter`.
- **Startup budget**: `tests/performance/test_startup_budget.py` pins
  the import surface; keep the late `run_serve` import lazy.
- Description strings are duplicated in `docs/tools.md`; refactor should
  not drift them.

## Open Questions

- None blocking. If the team prefers `auth` outside the dispatch table
  (option a above) vs. a per-command pre-handler (option b), decide at
  `/speckit.bug.fix` time; option (a) is the smaller change.
