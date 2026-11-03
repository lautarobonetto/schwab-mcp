# Implementation Plan: Price History OHLCV (`get_price_history`)

**Branch**: `011-price-history-ohlcv` | **Date**: 2026-11-02 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/011-price-history-ohlcv/spec.md`

## Summary

Add the fifth MCP tool, `get_price_history`: OHLCV candles for one symbol per
invocation, with a declared frequency set (5m / 15m / 30m / 1h / daily /
weekly — clarifications Q3), named period presets bounded per frequency
(Q4), a small default (daily, 1 month), an `extended_hours` opt-in for
intraday requests (Q1), and an explicit in-progress marker on the forming
candle (Q2). The tool wraps `schwabdev.price_history()`, reuses the shared
unwrap / error taxonomy / result envelope of 003/006/008/010 (C-02, C-09),
and enforces a global candle ceiling of 260 per invocation so no request can
produce an oversized payload (C-05; spec FR-004).

## Technical Context

**Language/Version**: Python 3.11 (uv-managed virtualenv)

**Primary Dependencies**: `schwabdev` 4.0.0 (Schwab API client —
`price_history()`); `mcp` SDK (`MCPServer.add_tool`, `ToolError`); no new
dependencies.

**Storage**: N/A (stateless market-data passthrough; tokens remain in local
secure storage managed by 001/002).

**Testing**: pytest (`uv run pytest`); unit + integration + performance/token
tests in `tests/`, fake provider clients per the established fixture pattern.

**Target Platform**: local stdio MCP server (`schwab-mcp serve`); no network
sockets inbound.

**Performance Goals**: ≤ 5 s p95 per invocation; exactly one provider
`price_history` call per invocation (hourly/weekly derivation reuses the same
single call with a coarser native frequency — research D2/D3).

**Constraints**: ≤ ~20 tokens per curated candle (arithmetic baseline,
research D5); global candle ceiling 260 → worst case ≤ ~4,700 tokens; default
window (daily, 1 month, 22 candles) ≤ ~500 tokens; read-only surface (C-06);
credentials never in output (FR-011).

**Scale/Scope**: one new module (`src/schwab_mcp/price_history.py`), one tool
registration in `src/schwab_mcp/server.py`, `docs/tools.md` +
`docs/CHANGELOG.md` updates in the implementing commit.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Status | Evidence |
|---|---|---|
| I. TDD — tests first | PASS (planned) | tasks will order validation/mapping/aggregation/budget tests before the module; the first test records the live provider fixture that pins the stamping constants (research D6) |
| II. DRY — single source of truth | PASS | reuses `provider.response_json`, `errors` taxonomy, `tokens.retry_call`, envelope pattern of 003/006/008/010; one aggregation implementation serves hourly and weekly derivation paths |
| III. Reuse before creation | PASS | wraps `schwabdev.price_history()`; one new module justified: price-history logic does not belong in the quotes/positions/transactions/options_chain modules |
| IV. KISS/YAGNI | PASS | named period presets instead of open numeric/date-range input (FR-014, FR-018); no indicator computation (FR-013); no fields-selector surface; hourly/weekly derived from provider-native frequencies only where the provider cannot serve them directly |
| V. Token & performance budgets | PASS (planned) | ceiling-by-construction (presets cannot exceed 260 candles, FR-004); per-candle baseline from deterministic payload arithmetic (research D5), asserted by token-usage tests against a recorded fixture; performance test asserts ≤ 5 s p95 |
| VI. Graph-first discovery | PASS | tool pattern (`get_*` + `*_tool`), quotes orchestration precedent, shared helpers, and SDK cross-validity rules located via codebase-memory-mcp and package source before this plan |
| VII. English-only docs | PASS | all artifacts in English |
| Layout (`src/`,`tests/`,`docs/`) | PASS | module in `src/schwab_mcp/`, tests in `tests/`, contract doc updates in `docs/` |
| Credential safety | PASS | tool output carries market data only; no tokens/account identifiers (FR-011) |
| Read-only surface (C-06) | PASS | market data retrieval only; no order operations |
| Curated-first (C-09) | PASS | compact curated candle schema by default; raw payload only via `extended=true` |

**Post-Phase-1 re-check**: no new complexity introduced — the design adds one
module, one SDK call per invocation, and two small pure aggregation functions
(hourly, weekly) with no new abstractions beyond the existing envelope. The
only empirical unknown (provider candle stamping convention) is pinned by a
fixture test, not by new design. Result: **PASS**.

## Project Structure

### Documentation (this feature)

```text
specs/011-price-history-ohlcv/
├── plan.md              # This file
├── research.md          # Phase 0 output — decisions D1..D9
├── data-model.md        # Phase 1 output — Candle/PriceHistoryRequest entities, ceiling matrix, aggregation rules
├── quickstart.md        # Phase 1 output — validation scenarios S1..S6
├── contracts/
│   └── mcp-tools.md     # Phase 1 output — `get_price_history` tool contract
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
src/schwab_mcp/
├── price_history.py       # NEW — get_price_history orchestration + get_price_history_tool wrapper (pattern of quotes.py)
├── provider.py            # REUSED — response_json unwrap + shared error taxonomy
├── errors.py              # REUSED — ConnectivityError / ReauthorizationRequiredError
├── tokens.py              # REUSED — retry_call
├── log.py                 # REUSED — auth_event audit logging
└── server.py              # MODIFIED — register the get_price_history tool (pattern of 003/006/008/010)

tests/
├── unit/
│   ├── test_price_history_validation.py   # NEW — FR-007/FR-014/FR-018 fail-before-upcall rules
│   ├── test_price_history_mapping.py      # NEW — curated field mapping, as-delivered values, window metadata (FR-005/FR-015)
│   ├── test_price_history_aggregation.py  # NEW — hourly-from-30m derivation, weekly labeling (FR-019)
│   └── test_price_history_in_progress.py  # NEW — forming-candle marker rules (FR-017, Q2)
├── integration/
│   └── test_price_history.py              # NEW — end-to-end flows with fake client (SC-001/004/006 paths)
├── performance/
│   └── test_price_history_budgets.py      # NEW — token budgets (SC-002/SC-003) + latency budget (SC-001)
└── unit/fixtures/
    └── price_history_payloads.py          # NEW — recorded live provider payloads (first TDD step)
```

**Structure Decision**: single-package layout unchanged; the new tool follows
the module-per-tool pattern established by `positions.py`, `transactions.py`,
`options_chain.py`, and `quotes.py` (Constitution III — one implementation per
tool concern, shared helpers reused).

## Complexity Tracking

> No constitution violations — table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
