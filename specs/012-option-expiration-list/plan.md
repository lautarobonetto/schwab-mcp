# Implementation Plan: Option Expiration List (`get_option_expiration_chain`)

**Branch**: `012-option-expiration-list` | **Date**: 2026-11-03 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/012-option-expiration-list/spec.md`

## Summary

Expose one new MCP tool, `get_option_expiration_chain`, that wraps the
provider's option expiration-chain capability (`schwabdev` 4.0.0
`option_expiration_chain()` → `GET /marketdata/v1/expirationchain`) and
returns the upcoming expirations of one underlying — expiration date, DTE
(calendar days), and settlement type — with the same DTE-ceiling semantics
as `get_option_chain` (default cap 60, provided value ≥ 1 replaces it, echo
`dte_max_effective`). Curated-first output (C-09) with `extended=true`
passthrough; no strikes, quotes, or greeks. The implementation reuses the
validated-input, fetch, outcome-envelope, and ToolError patterns of spec
008 (`src/schwab_mcp/options_chain.py`) instead of creating a second
surface.

## Technical Context

**Language/Version**: Python 3.11 (uv-managed venv)

**Primary Dependencies**: `schwabdev` 4.0.0 (provider SDK — reuse, C-03),
`mcp` (MCP SDK server), `pytest` (testing)

**Storage**: local token store only (existing, untouched by this feature);
no new persistence

**Testing**: pytest — unit (`tests/unit/`), integration
(`tests/integration/`), performance/token-budget
(`tests/performance/`); TDD mandatory (Principle I)

**Target Platform**: local stdio MCP server (no inbound network surface)

**Project Type**: single-package library + stdio MCP server
(`src/schwab_mcp/`)

**Performance Goals**: single provider invocation per tool request; curated
default response < 1,000 tokens (SC-001); tool completes within 10 s
(SC-002) — the performance test asserts the stricter measured budget of
**5 s** per invocation (008 precedent), keeping a safety margin inside the
spec ceiling

**Constraints**: read-only (C-06); token budget test-enforced (C-05,
Principle V); curated-only default output — no strikes/quotes/greeks
(FR-006); one upstream call per request (FR-009, SC-004)

**Scale/Scope**: one new tool function + tool registration + docs; reuses
the existing module — no new dependencies, no new provider calls beyond the
one SDK method

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Test-first (TDD) | PASS | Plan orders failing tests before implementation for every FR; tasks will encode Red→Green→Refactor |
| II. DRY | PASS | Reuses `OptionChainQuery` (symbol + `dte_max` validation + `dte_max_effective`), the `outcome`/`detail`/`retryable` envelope, `retry_call`/`response_json` unwrapping, `_result_meta`, and the `*_tool` ToolError pattern from 008 — no second envelope, no duplicated validation |
| III. Reuse before creation | PASS | Wraps `schwabdev.option_expiration_chain()`; extends `options_chain.py` rather than creating a parallel module; new modules need justification — none created |
| IV. KISS / YAGNI | PASS | One symbol per request (no multi-symbol variant); three curated fields only; no pagination; no speculative parameters |
| V. Efficiency / budgets | PASS | Token budget (< 1,000 default) and latency budget declared and test-enforced; worst-case dense-expiration fixture (index underlyings, ~daily expirations) included in the budget test |
| VI. Graph-first discovery | PASS | Planning used `search_graph`/`get_file_outline` on the indexed graph; `get_code_snippet` returned unusable per-line output (coverage note) and fell back to exact source reads of the same nodes the graph located |
| VII. English-only | PASS | All artifacts and future code/comments in English |
| Layout gate | PASS | Code in `src/schwab_mcp/`, tests in `tests/`, docs in `docs/`; this feature's artifacts in `specs/012-option-expiration-list/` |
| Read-only discipline | PASS | Market-metadata retrieval only; no order surface (C-06) |

**Post-Phase-1 re-check**: no violations introduced. The design adds zero
new abstractions (one function + one thin query reuse + one tool wrapper),
zero new dependencies, and one SDK call. Token-budget risk for dense
expirations (SPX-style daily expirations, ~60 entries) is measured by the
budget test with a worst-case fixture; if the measured value exceeds the
declared budget, growth requires recorded justification per Principle V
(Complexity Tracking below stays empty unless that happens).

## Project Structure

### Documentation (this feature)

```text
specs/012-option-expiration-list/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── mcp-tools.md     # Tool contract (input/output/errors)
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
src/schwab_mcp/
├── options_chain.py     # EXTEND: add get_option_expiration_chain + tool wrapper (008 module)
└── server.py            # EXTEND: register the new tool (same pattern as get_option_chain)

tests/
├── unit/
│   └── test_option_expirations.py       # NEW: mapping, settlement, ordering, outcomes, validation
├── integration/
│   └── test_option_expirations.py       # NEW: end-to-end via fake client (1 upcall, envelope, extended)
└── performance/
    └── test_option_expirations_budgets.py  # NEW: token + latency budgets, dense fixture
```

**Structure Decision**: extend the existing option-domain module
(`src/schwab_mcp/options_chain.py`) and register the tool in
`src/schwab_mcp/server.py` following the exact `get_option_chain`
registration pattern (wrapper function + `mcp.add_tool`). A separate module
was rejected: it would duplicate symbol validation, the DTE semantics, the
outcome envelope, or import-cycles-inducing shared helpers (C-02/C-03).

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

### Token-budget growth (SC-001, recorded 2026-11-03)

The spec (SC-001) asserts "fewer than 1,000 tokens in the default
request".  The pre-implementation estimate (data-model.md §6 draft)
computed each entry as 52 chars ≈ 13 tokens and the dense 60-entry
worst case at ≤ 1,000 tokens.  The implementation measures each
normative entry as **63 chars ≈ 16 tokens** (the masking effect was
the real entry includes the full field structure with commas and
colons — draft arithmetic omitted the outer brace context).  The
consequence:

- **Representative fixture (12 entries, AAPL-style)**: ~300 tokens —
  well within SC-001's < 1,000 bound.
- **Dense worst case (60 entries, near-daily index underlying)**:
  **~1,008 tokens** — 0.8% over the draft estimate.

**Decision** (user, 2026-11-03): adopt the corrected budget model.
SC-001's < 1,000-token assertion is proven against a **representative
12-entry fixture** (the shape of every real underlying); the dense
worst case gets its own **recorded ceiling of ≤ 1,100 tokens**,
asserted in the budget test (`test_dense_worst_case_records_measured_ceiling`).
The data-model.md §6 arithmetic is corrected to the measured 63 chars
per entry.  Growth justification recorded in this entry per Principle V.