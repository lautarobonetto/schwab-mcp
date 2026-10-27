# Implementation Plan: Option Chain Extraction with Filters

**Branch**: `008-extract-option-chain` | **Date**: 2026-10-23 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/008-extract-option-chain/spec.md`

## Summary

New read-only MCP tool `get_option_chain` that extracts the option chain
of an instrument with bounding optional filters: strike limit per side
(default 50), option type (both/calls/puts), target delta (window of 5
strikes per type around the contract with the closest delta, over all
expirations within the DTE cap) and maximum DTE (default 60 days).
Returns all the Greeks and all the relevant technical values the source
exposes, in a compact per-strike format (both legs per row) to respect
the token budget. The data source is the chains endpoint of the already
integrated SDK (`schwabdev.Client.option_chains` →
`/marketdata/v1/chains`), reusing the shared unwrapping
(`provider.response_json`), the existing error taxonomy and the tool
registration pattern of `server.py`.

## Technical Context

**Language/Version**: Python ≥ 3.11 (pyproject `requires-python = ">=3.11"`)

**Primary Dependencies**: schwabdev 4.0.0 (Schwab Trader API), mcp ≥ 1.0.0 (MCPServer stdio)

**Storage**: N/A — read-only tool with no state of its own; reuses the existing token store (`tokens.py`)

**Testing**: pytest ≥ 9.1.1 (unit / integration / performance, marker `performance`)

**Target Platform**: local MCP server over stdio (`schwab-mcp serve`); no HTTP surface

**Project Type**: library/cli (local MCP stdio server)

**Performance Goals**: p95 latency ≤ 5 s per invocation (aligned with 006 and SC-001); token budget with default filters ≤ 75,000 tokens for a typical underlying and < 3,000 tokens with `delta_target` active (SC-002, decision of the clarification session 2026-10-24, with justification recorded below — Principle V)

**Constraints**: stdio transport exclusively; credentials never in logs/outputs; response in a single invocation with no pagination (FR-011); no partial data upon failure of an entire expiration (FR-013)

**Scale/Scope**: 1 new module (`src/schwab_mcp/options_chain.py`), 1 new tool registered in `server.py`, unit/integration/performance test suites

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|---|---|---|
| I. TDD | ✅ Pass | The feature will be implemented Red → Green → Refactor; filter, delta-window and validation tests first |
| II. DRY | ✅ Pass | Reuses `provider.response_json`, `tokens.retry_call`, taxonomy of `errors.py`; no duplicated unwrapping or error mapping |
| III. Reuse Before Creation | ✅ Pass | A new module only because the domain (option chain) is new; the SDK already exposes `option_chains()` |
| IV. KISS | ✅ Pass | One upstream call + local post-filter for delta; no speculative abstractions |
| V. Efficiency & Budgets | ✅ Pass (resolved) | Budget set by clarification 2026-10-24: ≤75,000 tokens with defaults (justification recorded in Complexity Tracking + R4) and <3,000 with `delta_target`; mitigation: compact columnar schema per strike, rounding, explicit `null` only for missing fields |
| VI. Graph-First | ✅ Pass | Discovery done via codebase-memory-mcp (`get_architecture`, `search_graph`, `get_code_snippet`, `get_file_outline`); filesystem fallback annotated due to raw format of `search_graph` results |
| Layout | ✅ Pass | Code in `src/`, tests in `tests/`, docs in `docs/`, scratch in `tmp/` |
| Commit discipline | ✅ Pass | `docs/tools.md` is updated in the same feature |

## Project Structure

### Documentation (this feature)

```text
specs/008-extract-option-chain/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── mcp-tools.md     # Contract of the get_option_chain tool
└── tasks.md             # Phase 2 output (/speckit.tasks — not created here)
```

### Source Code (repository root)

```text
src/
└── schwab_mcp/
    ├── options_chain.py   # NEW: validation, mapping, filters, delta-window, curation
    └── server.py          # Registration of the get_option_chain tool (existing wrapper pattern)

tests/
├── unit/
│   ├── test_options_chain_validation.py   # NEW: filter validation (Red first)
│   ├── test_options_chain_mapping.py      # NEW: payload mapping and curation
│   ├── test_options_chain_filters.py      # NEW: strikes/dte/type
│   └── test_options_chain_delta.py        # NEW: window of 5 strikes per type
├── integration/
│   └── test_options_chain.py              # NEW: end-to-end flow with provider double
└── performance/
    └── test_options_chain_budgets.py      # NEW: token budget and latency
```

**Structure Decision**: existing single-project structure; one module is
added per feature (pattern of `positions.py` and `transactions.py`) and
the tool is registered in `server.py` with the same wrapper-closure as
the two existing tools. Contracts and docs are updated in the same
feature.

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Potential token budget growth (Principle V) | The defaults required by the spec (50 strikes/side, both types, 60 DTE, curated field superset, FR-011 without pagination) produce responses of ~45–75k estimated tokens on wide chains. **Resolved in the 2026-10-24 clarification**: the default of 50 stays (user decision) and the budget with defaults is set at ≤75,000 tokens (SC-002), with <3,000 for calls with `delta_target` | Trimming Greeks or paginating violates FR-006/FR-011; reducing defaults changes the behavior required by the user. Mitigated with a compact columnar schema (both legs per strike row, rounding to 4 decimals, explicit `null` only for missing fields). Test T008 must target the 75k budget; the justification is also documented in `docs/tools.md` |
| **Second token budget adjustment (Principle V) — user decision 2026-10-24 (implementation 008)** | The actual measurement of the serialization of the contract format (23 columns per leg, rounding 2/4 decimals, ~80–88 tokens per row with both legs) shows that the representative fixture required by T008 (12 expirations × 100 rows ≈ 1,200 rows) serializes to **~95,000–106,000 tokens**, and the case with `delta_target` (12 expirations × ≤5 strikes × 2 types ≈ 120 single-leg rows) to **~4,500–5,000 tokens** — above the 75,000 / 3,000 of SC-002. The response content is fixed by FR-002/FR-006 (no trimming is allowed without violating the spec). Budgets adjusted by user decision: **≤110,000 tokens** with defaults and **<6,000** with `delta_target` (T008 targets these values; documented in `docs/tools.md`) | Reducing `max_strikes` or trimming `contract_fields` violates FR-002/FR-006; paginating violates FR-011; using a non-representative fixture (few expirations) would make the test not verify SC-002. The compact columnar schema is kept as the only format mitigation |
| **Third adjustment: re-baseline of the `delta_target` budget (Principle V) — user decision 2026-10-24 (convergence 008, T023)** | Live measurement (convergence T023): wide chains of **16 expirations ≤60 DTE** (SPY ~7,334, QQQ ~7,214 tokens) exceed the `<6,000` budget set in the second adjustment, while typical underlyings (AAPL ~4,640, TSLA ~5,074) comply with margin. The per-delta window is ≤5 strikes per type **per expiration** (FR-004) — the volume scales with the number of expirations the DTE cap lets through, and cannot be trimmed without violating the spec. Budget re-baselined by user decision: **≤8,000 tokens** with `delta_target`; test T008 adds a wide-chain case (16 expirations) that fixes the new cap; documented in `docs/tools.md` | The window of 5 per type is fixed by FR-004 (clarification 2026-10-23); trimming it violates the spec. Limiting additional expirations would violate FR-005. The only valid margin is the format, already compacted (R4); the re-baseline is the Principle V procedure |