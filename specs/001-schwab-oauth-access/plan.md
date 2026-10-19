# Implementation Plan: Schwab OAuth Access

**Branch**: `001-schwab-oauth-access` | **Date**: 2026-10-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-schwab-oauth-access/spec.md`

## Summary

Implement the full OAuth access layer for the local stdio Schwab MCP server:
an explicit `schwab-mcp auth` command that performs the one-time browser
authorization (no inbound HTTP listener — the owner pastes the redirect URL),
persistent local token storage (schwabdev-managed SQLite file outside the
repo, owner-only permissions), silent token reuse and automatic refresh on
every subsequent server start, proactive access validation before the server
signals ready, and a distinct, actionable error message per authentication
failure mode. The OAuth/token mechanics are delegated to `schwabdev` v4
(assessment Option B); this feature owns only the thin CLI/config/logging/
error-mapping layer. No account tools yet — they arrive in a later feature.

## Technical Context

**Language/Version**: Python 3.11+ (schwabdev requires >=3.11; local
toolchain has Python 3.14.6 and `uv`)

**Primary Dependencies**:
- `schwabdev` 4.0.0 (MIT, actively maintained) — OAuth authorization-code
  flow, token exchange, refresh, SQLite token persistence
- `mcp` (official Model Context Protocol Python SDK, FastMCP) — stdio server
- `pytest` — test framework

**Storage**: SQLite token database file (schema owned by schwabdev, single
row: access/refresh/id tokens, issue timestamps, expiry, scope), default
`~/.schwab-mcp/tokens.db`, outside the repository, chmod 600. Only an
advisory lock file and the token DB touch the filesystem.

**Testing**: pytest (unit + integration), pytest-asyncio where the MCP SDK
requires async. Performance tests assert the startup-validation budget.

**Target Platform**: Owner's local machine (macOS/Linux), headless stdio
MCP server; browser only used once, during explicit `schwab-mcp auth`.

**Project Type**: CLI + local stdio MCP server (single Python package).

**Performance Goals**: Proactive startup access validation completes and the
server reaches ready state within 5 seconds (SC-004); authorization flow
completes in under 2 minutes of owner interaction (SC-001).

**Constraints**: Zero credential/token material in logs, errors, or tool
output (FR-006); no inbound network sockets ever (constitution — the auth
flow uses paste-the-redirect-URL, not a callback listener); read-only scope
(FR-005); fail-fast, never hang (FR-007).

**Scale/Scope**: Single user, single account, ~6 modules. No data model
beyond the token set. No MCP tools in this feature.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Test-First Development | PASS | Every module below is planned test-first; regression tests for each failure mode of US3 before implementation. No production code without a preceding failing test. |
| II. DRY | PASS | Error taxonomy, redaction filter, and config parsing each have exactly one implementation; CLI and server share the same auth module. |
| III. Reuse Before Creation | PASS | OAuth/token lifecycle, token storage, and refresh are reused from `schwabdev` 4.0.0 (actively maintained, MIT); server layer reuses the official `mcp` SDK. Nothing here is hand-rolled except glue. Rationale recorded in research.md. |
| IV. Simplicity (KISS) | PASS | Flat module layout (6 modules); paste-the-URL auth instead of a callback HTTP server (also required by the no-inbound-socket constraint); plain schwabdev SQLite store without extra encryption (owner decision 2026-10-19); no speculative config surface beyond FR-012. |
| V. Efficiency & Cost Awareness | PASS (scoped) | Performance tests assert the 5 s startup-validation budget (SC-004). Token-usage tests: this feature introduces **no MCP tool outputs**, so no token budget applies yet — justification recorded below in Complexity Tracking; token-usage tests become applicable with the first tools feature. SC-003 leak checks are covered as automated security tests. |
| Repository Layout | PASS | All code in `src/`, all tests in `tests/`, docs in `docs/`/`specs/`, scratch in `tmp/` (git-ignored). Token artifacts live outside the repo by requirement. |
| Project Context (stdio-only, credential safety, read-only) | PASS | stdio-only server; no inbound sockets (paste-URL auth avoids a listener); credentials from env only; this feature adds no trading capability. |

**Gate result**: PASS — no violations requiring justification beyond the
noted Principle V scope deferral (recorded in Complexity Tracking).

## Project Structure

### Documentation (this feature)

```text
specs/001-schwab-oauth-access/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output: library wiring decisions
├── data-model.md        # Phase 1 output: token set, auth events, failure modes
├── quickstart.md        # Phase 1 output: end-to-end validation guide
├── contracts/
│   ├── cli.md           # `schwab-mcp auth` / `schwab-mcp serve` contracts
│   ├── configuration.md # Environment variables contract
│   └── events.md        # Authentication event log schema
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
src/schwab_mcp/
├── __init__.py          # package metadata
├── __main__.py          # `python -m schwab_mcp` → cli.main
├── cli.py               # single entrypoint: `schwab-mcp auth` | `schwab-mcp serve`
├── config.py            # env-var credential/config loading + fail-fast validation
├── errors.py            # AuthError taxonomy — one distinct actionable message per failure mode (FR-007)
├── tokens.py            # thin lifecycle wrapper around schwabdev Tokens/Client:
│                        #   store-presence peek, auth hook, permission enforcement,
│                        #   corrupted-store handling, concurrent-auth advisory lock
├── log.py               # redaction filter (secrets never reach output) + auth event logging (FR-014)
└── server.py            # stdio MCP server startup + proactive access validation before ready (FR-013)

tests/
├── unit/                # config parsing, error mapping, redaction, token-store peek, lock
├── integration/         # full auth flow against a stubbed schwabdev client; startup validation
└── performance/         # SC-004 startup-validation latency budget

docs/                    # (empty in this feature; user-facing docs come later)
tmp/                     # scratch only (git-ignored)
```

**Structure Decision**: Single flat Python package (`src/schwab_mcp/`)
because the feature is one cohesive concern (auth access layer) with no
internal boundaries worth directories; constitution Option 1 (single
project). The CLI is one console script (`schwab-mcp`) with two
subcommands — `auth` (interactive, browser) and `serve` (headless stdio) —
matching the clarified requirement that authorization is an explicit,
dedicated command and the server is fully headless.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Principle V token-usage tests deferred | This feature produces no MCP tool outputs (no tools yet); only CLI/stderr and log events. | Writing token-budget tests for non-tool output would test nothing meaningful; the gate applies from the first tools feature, which is the next feature on the roadmap. |

All other gates pass with no tracking needed. Post-Phase-1 re-check: no new
violations introduced by the design (see research.md — all complexity is
delegated to schwabdev).
