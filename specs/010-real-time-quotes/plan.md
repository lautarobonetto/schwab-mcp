# Implementation Plan: Real-Time Quotes (`get_quotes`)

**Branch**: `010-real-time-quotes` | **Date**: 2026-10-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/010-real-time-quotes/spec.md`

## Summary

Add the fourth MCP tool, `get_quotes`: current price, bid/ask, volume, net
change, quote freshness (`realtime`/`delayed`/`closed`), and last-trade
timestamp for 1..N symbols (≤ 20, de-duplicated) in one invocation, keyed by
symbol, with an `extended` passthrough for the raw provider payload. The tool
wraps the existing schwabdev market-data integration (`quotes()`), reuses the
shared response unwrap / error taxonomy / result envelope of 003/006/008
(C-02, C-09), and derives quote freshness deterministically from the provider
`quoteType` plus one market-hours check per invocation.

## Technical Context

**Language/Version**: Python 3.11 (uv-managed virtualenv)

**Primary Dependencies**: `schwabdev` 4.0.0 (Schwab API client — `quotes()`,
`market_hours()`); `mcp` SDK (`MCPServer.add_tool`, `ToolError`); no new
dependencies.

**Storage**: N/A (stateless market-data passthrough; tokens remain in local
secure storage managed by 001/002).

**Testing**: pytest (`uv run pytest`); unit + integration + performance/token
tests in `tests/`, fake provider clients per the established fixture pattern.

**Target Platform**: local stdio MCP server (`schwab-mcp serve`); no network
sockets inbound.

**Project Type**: cli / library (stdio MCP server, single package
`src/schwab_mcp`).

**Performance Goals**: ≤ 5 s p95 per invocation at the maximum symbol count
(20); one provider quotes call plus one market-hours call per invocation.

**Constraints**: ≤ 250 tokens curated payload for a single symbol; ≤ 2,500
tokens for a 10-symbol batch (≈ ≤ 5,000 worst case at 20 symbols); read-only
surface (C-06); credentials never in output (FR-010).

**Scale/Scope**: one new module (`src/schwab_mcp/quotes.py`), one tool
registration in `src/schwab_mcp/server.py`, `docs/tools.md` +
`docs/CHANGELOG.md` updates in the implementing commit.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Status | Evidence |
|---|---|---|
| I. TDD — tests first | PASS (planned) | tasks will order validation/mapping/budget tests before the module; bug-fix rule N/A (new feature) |
| II. DRY — single source of truth | PASS | reuses `provider.response_json`, `errors` taxonomy, `tokens.retry_call`, envelope pattern of 003/006/008; one tool for 1..N symbols (no separate single-quote tool) |
| III. Reuse before creation | PASS | wraps `schwabdev.quotes()` + `schwabdev.market_hours()`; one new module justified: quotes logic does not belong in positions/transactions/options_chain modules |
| IV. KISS/YAGNI | PASS | no speculative parameters (no fields-selector surface, no indicative flag exposed, no pagination); scope-out: order book depth, chart data |
| V. Token & performance budgets | PASS (planned) | token-usage tests assert ≤ 250 tokens/symbol and linear batch growth; performance test asserts ≤ 5 s p95; budgets declared here and in contracts |
| VI. Graph-first discovery | PASS | architecture, tool pattern (`get_*` + `*_tool`), registration flow, and shared helpers located via codebase-memory-mcp before this plan |
| VII. English-only docs | PASS | all artifacts in English |
| Layout (`src/`,`tests/`,`docs/`) | PASS | quotes module in `src/schwab_mcp/`, tests in `tests/`, contract doc updates in `docs/` |
| Credential safety | PASS | tool output carries market data only; no tokens/account identifiers (FR-010) |
| Read-only surface (C-06) | PASS | market data retrieval only; no order operations |
| Curated-first (C-09) | PASS | compact curated schema by default; raw payload only via `extended=true` |

**Post-Phase-1 re-check**: no new complexity introduced — the design adds one
module, two SDK calls, and no new abstractions beyond the existing envelope.
Result: **PASS**.

## Project Structure

### Documentation (this feature)

```text
specs/010-real-time-quotes/
├── plan.md              # This file
├── research.md          # Phase 0 output — decisions D1..D7
├── data-model.md        # Phase 1 output — Quote/QuoteRequest entities, field mapping, state rules
├── quickstart.md        # Phase 1 output — validation scenarios S1..S5
├── contracts/
│   └── mcp-tools.md     # Phase 1 output — `get_quotes` tool contract
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
src/schwab_mcp/
├── quotes.py            # NEW — get_quotes orchestration + get_quotes_tool wrapper (pattern of options_chain.py)
├── provider.py          # REUSED — response_json unwrap + shared error taxonomy
├── errors.py            # REUSED — ConnectivityError / ReauthorizationRequiredError
├── tokens.py            # REUSED — retry_call
├── log.py               # REUSED — auth_event audit logging
└── server.py            # MODIFIED — register the get_quotes tool (pattern of 003/006/008)

tests/
├── unit/
│   ├── test_quotes_validation.py        # NEW — FR-005/FR-007/FR-013 fail-before-upcall rules
│   ├── test_quotes_mapping.py           # NEW — curated field mapping, rounding, unavailable fields
│   └── test_quotes_data_state.py        # NEW — realtime/delayed/closed derivation (FR-003)
├── integration/
│   └── test_quotes.py                   # NEW — end-to-end flows with fake client (SC-001/004/006 paths)
└── performance/
    └── test_quotes_budgets.py           # NEW — token budgets (SC-002) + latency budget (SC-001)
```

**Structure Decision**: single-package layout unchanged; the new tool follows
the module-per-tool pattern established by `positions.py`, `transactions.py`,
and `options_chain.py` (Constitution III — one implementation per tool
concern, shared helpers reused).

## Complexity Tracking

> No constitution violations — table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |