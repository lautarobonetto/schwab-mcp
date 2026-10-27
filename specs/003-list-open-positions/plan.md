# Implementation Plan: List Open Positions

**Branch**: `003-list-open-positions` | **Date**: 2026-10-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-list-open-positions/spec.md`

## Summary

Expose the server's **first MCP tool**: `get_open_positions`, which in a
single invocation returns all effective holdings (non-zero signed
quantity) across all linked accounts, each with the curated metadata set
(instrument identification, signed quantity, average cost, market value
with the price timestamp, unrealized P/L, instrument classification),
with extended fields available only under explicit request
(`extended=true`). No internal retries; failures self-classify
(`transient_failure`, `reauth_required`, `partial_failure`) with the same
vocabulary as the existing playbook, and every query emits audit events
without secrets.

Technical approach (from research): a single call to
`schwabdev.Client.account_details_all(fields="positions")` feeds the
tool; a new module `src/schwab_mcp/positions.py` maps the provider
payload to the data model and `server.py` registers the tool via
`MCPServer.add_tool` (SDK `mcp` ≥ 1.0.0, API verified in the repo).

## Technical Context

**Language/Version**: Python ≥ 3.11 (pyproject: `requires-python = ">=3.11"`)

**Primary Dependencies**: `schwabdev==4.0.0` (Schwab API), `mcp>=1.0.0`
(stdio MCP server; `MCPServer.add_tool` with `structured_output`). No
new dependencies.

**Storage**: N/A — ephemeral result; the only storage is schwabdev's
SQLite token store (read-only credential access, unchanged).

**Testing**: pytest 9.x + pytest-asyncio (unit; `performance` marker
already configured for budgets).

**Target Platform**: local `schwab-mcp serve` process, stdio transport
exclusively (constitution: no inbound sockets, no HTTP).

**Project Type**: local MCP server (stdio) + existing one-shot CLI.

**Performance Goals**: full query ≤ 5 s (SC-002); a single upstream call
to the Schwab API per query.

**Constraints**: default payload bounded by the token budget
(SC-003: declared below, ≤ 8 KB for 50 curated positions; growth
justifiable only for `extended=true`); no secrets in any output;
no internal retries (FR-007); audit on every invocation (FR-014).

**Scale/Scope**: representative portfolio ≤ 50 open positions; linked
accounts already enumerable via `linked_accounts()` (feature 001).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Status | Evidence |
|------|--------|----------|
| I. Test-First | PASS | tasks.md (Phase 2) will order tests before implementation: mapping test, tool registration test, failure test, audit test, performance, token-usage |
| II. DRY | PASS | Reuses `errors.py` (AuthError taxonomy/exit codes), `log.auth_event` + redaction filter, `config.load_config`; the provider→model mapping lives in a single module (`positions.py`) |
| III. Reuse Before Creation | PASS | schwabdev's `account_details_all()` replaces N per-account calls; SDK `MCPServer.add_tool` instead of hand-rolled protocol; no new libraries |
| IV. KISS | PASS | No per-account filters (spec FR-004: all accounts), no cache (FR-006 forbids stale data), no strategy logic (grouping belongs to the agent); a single upstream call |
| V. Efficiency & Cost | PASS | Declared budgets: ≤ 5 s (SC-002), ≤ 8 KB default for 50 positions (~2k tokens) and a separate declared budget for `extended` (contracts); performance + token-usage tests required in tasks |
| Fixed layout | PASS | Code → `src/schwab_mcp/`; tests → `tests/`; affected docs (`docs/tools.md`, CHANGELOG) updated in the same implementation commit |
| Credential safety | PASS | No result field carries tokens/secrets; redaction filter remains active; contract verifies it with a test |
| Read/write discipline | PASS | Tool is strictly read-only: no orders, no money movements |

**Re-check post-Phase 1**: PASS — the contracts and data model introduce
no duplication (they reuse enums/vocabulary from 002), nor unjustified
complexity (see research D1–D8; no entries in Complexity Tracking).

## Project Structure

### Documentation (this feature)

```text
specs/003-list-open-positions/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── mcp-tools.md     # Contract for the get_open_positions tool
│   └── events.md        # Positions audit events
└── tasks.md             # Phase 2 output (/speckit.tasks - NOT created here)
```

### Source Code (repository root)

```text
src/schwab_mcp/
├── positions.py         # NEW: provider→model mapping + result assembly
├── server.py            # MODIFIED: registers the tool via MCPServer.add_tool
├── errors.py            # REUSED: taxonomy and exit codes (unchanged)
├── log.py               # REUSED: auth_event + redaction filter (unchanged)
└── config.py            # REUSED: load_config (unchanged)

tests/
├── unit/
│   ├── test_positions.py            # NEW: mapping, consolidation, sign, qty=0 omission
│   ├── test_server_tool.py          # NEW: tool registration, structured result, classified failures
│   └── test_no_secrets_in_output.py # EXTENDED: cover the tool's output
└── performance/
    └── test_positions_budgets.py    # NEW: 5 s budget + token budget
```

**Structure Decision**: single existing project; one new module
(`positions.py`) + registration in `server.py`. No new subdirectories in
`src/` because the codebase is flat per feature (consistent with
001/002).

## Complexity Tracking

> No constitution violations to justify — empty table.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |