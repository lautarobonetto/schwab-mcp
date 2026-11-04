# Bug Verification: TD-006 — Registration boilerplate ×6 and CLI dispatch ×4 (DRY)

- **Slug**: td-006-registration-cli-dry
- **Tested**: 2026-11-04
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

This was structural tech debt, not a runtime defect, so "reproduction"
is the structural check the assessment prescribed: the duplication
pattern must no longer exist. Post-fix inspection confirms one
registration helper with six call sites and one dispatch table with
zero duplicated `elif` arms, and the behavioral contracts (schemas,
descriptions, exit codes, audit events) are pinned green by the new and
pre-existing suites. No regressions found.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix) | structural script: count `_register_bound_tool` defs/calls, manual `__name__` sites, `_COMMAND_RUNNERS` keys, remaining `elif args.command` arms | pass | 1 helper def, 6 call sites, manual `__name__` assignment only inside the helper; 4 table entries; 0 `elif` arms left (was 4) |
| New / updated tests | `uv run pytest tests/unit/test_tool_registration.py tests/unit/test_cli_dispatch.py tests/unit/test_tool_arg_strictness.py -q` | pass | 17 passed — includes the schema-leak guard (`test_schemas_do_not_expose_client`), byte-for-byte description pin, client-binding check, full error-mapping table, auth special handling |
| Regression suite | `uv run pytest -q` | pass | 1800 passed, 0 skipped (constitution commit gate, same as CI) |
| Lint / type-check | — | not-run | No lint/type-check tooling configured in the repo (no ruff/mypy in `pyproject.toml`, no config files; CI runs only `uv sync && uv run pytest`) |
| CLI surface smoke | `uv run schwab-mcp --help` | pass | Usage, subcommand list, and version banner unchanged |

## Output Excerpts

```text
server.py: 1 helper def, 6 call sites, manual __name__ assignment only in helper (2)
cli.py: dispatch table with 4 commands, 0 elif arms left (was 4)

.........................                                    [100%]
17 passed in 0.54s

........................................................................ [100%]
1800 passed in 34.86s

usage: schwab-mcp [-h] {auth,renew,auth-status,serve} ...
schwab-mcp 0.9.8 — local stdio MCP server for Schwab account data
```

## Residual Risks

- The client-binding check (`test_bound_client_is_passed_to_tool_function`)
  exercises only `get_open_positions`; the other five tools are covered
  for schema/description but not for live client delivery (documented as
  a follow-up in `fix.md`).
- Descriptions are pinned in the test by copied strings; if the
  intended text legitimately changes, the test must be updated in the
  same commit (deliberate friction — descriptions are contract text).
- No runtime MCP session was exercised (would require live Schwab
  credentials); argument validation and schema shape are covered by the
  SDK-level `test_tool_arg_strictness.py` regressions instead.

## Recommendation

Close the bug — the duplication the assessment documented is
structurally gone, the contracts pinned by the new tests hold, and the
full suite (the commit gate) is green with zero skips.
