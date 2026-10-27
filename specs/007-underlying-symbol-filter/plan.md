# Implementation Plan: Underlying-Aware Symbol Filter and Underlying Reference

**Branch**: `007-underlying-symbol-filter` | **Date**: 2026-10-24 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/007-underlying-symbol-filter/spec.md`

## Summary

Extend the MCP tool **`get_transaction_history`** (feature 006) so the
`symbol` filter is **underlying-aware**: `symbol="NOK"` returns the
movements registered under `NOK` **and** the movements of options whose
OCC symbol root is `NOK`, and — when the filter is a registered complete
option symbol — the movements of that specific option. In addition, every
option movement exposes the **underlying** as a first-class field
(`underlying_symbol`) in the curated output, derived from the registered
symbol (the source does not expose it separately).

Technical approach (from research): with the filter present, the tool
queries the range **unfiltered upstream** (same upcalls as the unfiltered
query: 1 `linked_accounts` + 1 `transactions` per account, with bisection
against the 3000 cap) and applies the three-form matching locally — the
provider endpoint cannot filter options by underlying (verified live:
`symbol=NOK` → 0 results; OCC symbol → HTTP 400). Dual filter validation
(clarification C): instrument directory lookup first; if it does not
resolve, the query proceeds anyway and `instrument_not_found` is reported
only if nothing matches. `underlying_symbol` is derived from the OCC root
(portion before the last 15 date/C-P/strike characters — same
right-anchoring verified live for positions). Case-insensitive
comparison. **No new dependencies.**

## Technical Context

**Language/Version**: Python ≥ 3.11 (pyproject: `requires-python = ">=3.11"`)

**Primary Dependencies**: `schwabdev==4.0.0` (`Client.linked_accounts`,
`Client.transactions`, `Client.instruments`), `mcp>=1.0.0`
(`mcp.add_tool`), Pydantic (via the MCP SDK dependency). `zoneinfo`
(stdlib). **No new dependencies.**

**Storage**: N/A — ephemeral result; no caching between requests (003/006
criterion).

**Testing**: pytest 9.x + pytest-asyncio (unit); `performance` marker for
budgets.

**Target Platform**: local `schwab-mcp serve` process, stdio transport
exclusively (constitution: no incoming sockets, no HTTP).

**Project Type**: local MCP server (stdio) — extension of the second
registered tool; no new tools are registered.

**Performance Goals**: same budgets as 006 (≤ 5 s p95, 006's SC-001):
the upcalls do not change (the filter no longer travels upstream, but the
per-account upcalls are the same 1 + N); 1 additional `instruments` call
only when there is a filter (as today).

**Constraints**: bounded default payload (≤ 16 KB per 50-movement page —
must hold **including** the new field, FR-007); no internal retries;
per-invocation audit; strict read-only; no secrets.

**Scale/Scope**: all linked accounts; upstream cap of 3000 per (account,
call) handled with the existing bisection; pages of 50.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Status | Evidence |
|------|--------|----------|
| I. Test-First | PASS | tasks.md (Phase 2) will order tests first: matching of the 3 forms, case-insensitivity, subset-consistency, dual validation, `underlying_symbol` per payload form, budgets |
| II. DRY | PASS | Reuses `response_json` (provider.py), the orchestration/bisection/pagination of `transactions.py`, and the right-anchoring of OCC symbols already verified in `positions.py`; the filter matcher is a single pure function with a single definition |
| III. Reuse Before Creation | PASS | No new libraries; existing SDK upcalls; the OCC parser builds on knowledge already coded and verified live |
| IV. KISS | PASS | A single sweep + local filter (versus the hybrid double query, discarded in research R1); no server state; no cache |
| V. Efficiency & Cost | PASS | Declared budgets unchanged (≤ 5 s p95, ≤ 16 KB default page) — the new field fits within the current budget (research R5 measures it); existing performance + token-usage tests are extended |
| Fixed layout | PASS | Code → `src/schwab_mcp/`; tests → `tests/`; affected docs (`docs/tools.md`, CHANGELOG) in the same commit |
| Credential safety | PASS | `underlying_symbol` is a public instrument identifier, not an account one; opaque `account_hash` is kept; no tokens/secrets |
| Read/write discipline | PASS | Read-only; no orders or money movements |

**Re-check post-Phase 1**: PASS — contracts and data model reuse 006's
outcome vocabulary and the event channel unchanged; no entries in
Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/007-underlying-symbol-filter/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   └── mcp-tools.md     # Contract changes for get_transaction_history
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/schwab_mcp/
├── transactions.py      # MODIFIED: filter matcher (3 forms, case-
│                        # insensitive), root/underlying derivation,
│                        # dual validation, field in MovementEntry; no
│                        # longer sends symbol upstream
├── provider.py          # REUSED unchanged (response_json)
├── positions.py         # REUSED unchanged (OCC pattern reference)
├── log.py               # REUSED unchanged (006 events)
└── server.py            # REUSED unchanged (already-registered tool)

tests/
├── unit/                # TDD tests: matching, subset-consistency, dual
│                        # validation, underlying_symbol, case-insensitivity
└── performance/         # extended budgets (16 KB with the new field)
```

**Structure Decision**: no new modules; the extension lives in
`transactions.py` (pure matcher + root derivation + wiring in the
existing orchestration). `server.py` does not change (same input
parameters).

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No entries: no constitution violations to justify.