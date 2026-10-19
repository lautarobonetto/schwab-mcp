# Implementation Plan: Automated Token Renewal

**Branch**: `002-automated-token-renewal` | **Date**: 2026-10-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/002-automated-token-renewal/spec.md`

## Summary

Make token renewal fully autonomous for an unattended AI agent (OpenClaw):
renewal fires preventively with a safety margin on every authenticated
operation (never on an expired credential), with zero interactive steps.
The agent gets two one-shot, non-interactive CLI actions — `schwab-mcp
renew` and `schwab-mcp auth-status` — that return a compact, machine-
readable outcome classifying itself as `renewed` / `not_needed` /
`transient_failure` / `reauth_required`. Refresh mechanics stay delegated
to `schwabdev` 4.0.0 (its built-in 61 s preventive margin and
single-flight coordination already match FR-001/FR-005/FR-009); this
feature adds only the thin orchestration, outcome-classification, and
agent-facing interface layer on top of feature 001's auth foundation.

## Technical Context

**Language/Version**: Python 3.11+ (unchanged from feature 001)

**Primary Dependencies**:
- `schwabdev` 4.0.0 — owns OAuth refresh mechanics (`update_tokens`,
  preventive 61 s access margin, single-flight via SQLite `BEGIN
  EXCLUSIVE` + threading lock, refresh-token rotation persistence)
- `mcp` — stdio server (no changes; this feature registers no tools)
- `pytest` + `pytest-asyncio` — testing

**Storage**: Same schwabdev SQLite token DB (default
`~/.schwab-mcp/tokens.db`); read-only timestamp peeks added. No new
storage. Advisory `auth.lock` reused for the explicit renewal command.

**Testing**: pytest; unit + integration + performance (renewal budget,
SC-002 ≤ 10 s) + token-usage (output size budgets, Principle V).

**Target Platform**: Owner's local machine (macOS/Linux), headless stdio
MCP server; agent runs one-shot CLI commands via shell.

**Project Type**: CLI + local stdio MCP server (single Python package).

**Performance Goals**: An automatic renewal adds at most 10 s to the
operation that triggered it (SC-002): per-attempt HTTP timeout 3 s × 3
attempts + 2 short waits (0.5 s) ≤ 10 s worst case. `auth-status` answers
in ≤ 2 s (local read, no network).

**Constraints**: Zero credential/token material in outputs, logs, or JSON
results (FR-004); no inbound sockets ever (constitution); renewal results
are a few short fields only (token-efficiency, Principle V); never hang
(bounded retries, bounded timeouts).

**Scale/Scope**: Single user, single credential set, ~1 new module
(`renewal.py`) + CLI wiring. No MCP tools in this feature.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Test-First Development | PASS | `renewal.py`, CLI wiring, and retry generalization are planned test-first; classification tests (each of the 4 outcome classes) written before implementation. |
| II. DRY | PASS | One outcome taxonomy (`RenewalOutcome`) shared by CLI, server path, and events; the existing `retry_once` is generalized into a single bounded-retry helper used by both startup validation and renewal (no second retry implementation). |
| III. Reuse Before Creation | PASS | Refresh mechanics, preventive margin, single-flight coordination, and refresh-token rotation persistence are all reused from schwabdev 4.0.0 (verified in research.md). Only orchestration + classification + CLI surface is new. Rationale in research.md D1. |
| IV. Simplicity (KISS) | PASS | One new module; agent interface is two one-shot CLI subcommands (no MCP tool surface yet, no background daemon, no scheduler — YAGNI). Alternative MCP tools rejected in research.md D3. |
| V. Efficiency & Cost Awareness | PASS | Performance tests assert the 10 s renewal budget (SC-002) and the 2 s status budget. Token-usage tests ARE applicable in this feature (the agent consumes the structured outputs): budgets asserted per contract field set (compact single-line JSON). |
| Repository Layout | PASS | Code in `src/schwab_mcp/`, tests in `tests/`, docs in `specs/`/`docs/`, scratch in `tmp/` (git-ignored). |
| Project Context (stdio-only, credential safety) | PASS | New commands are one-shot outbound-only (no listener); results carry no secrets (redaction filter reused). |

**Gate result**: PASS — no violations; no Complexity Tracking entries.

## Project Structure

### Documentation (this feature)

```text
specs/002-automated-token-renewal/
├── plan.md              # This file (/speckit.plan command output)
├── spec.md              # Feature specification (clarified 2026-10-19)
├── checklists/          # Spec quality checklist
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── contracts/
│   ├── cli.md           # `schwab-mcp renew` / `auth-status` contracts
│   └── events.md        # Renewal audit-event contract (extends 001)
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
src/schwab_mcp/
├── renewal.py           # NEW: renewal orchestration, outcome classification,
│                        #   auth-health read, bounded retry with waits
├── tokens.py            # MODIFIED: generalize retry_once → bounded retry
│                        #   (existing startup path reuses it — DRY)
├── cli.py               # MODIFIED: add `renew` and `auth-status` subcommands
├── errors.py            # MODIFIED: no new classes; map outcomes to existing
│                        #   ConnectivityError / ReauthorizationRequiredError
├── log.py               # UNCHANGED (redaction filter + auth_event reused)
├── config.py            # UNCHANGED
└── server.py            # MODIFIED (small): startup validation uses the
                        #   generalized bounded retry; renewal outcome events

tests/
├── unit/
│   ├── test_renewal.py          # outcome classification, margin logic, health
│   └── test_tokens.py           # updated for generalized retry helper
├── integration/
│   ├── test_renew.py            # `schwab-mcp renew` end-to-end per outcome
│   └── test_auth_status.py      # `schwab-mcp auth-status` end-to-end
└── performance/
    ├── test_renewal_budget.py   # SC-002: renewal ≤ 10 s worst case
    └── test_output_budget.py    # Principle V: compact JSON output budgets
```

**Structure Decision**: Option 1 (single project), identical to feature
001's flat `src/schwab_mcp/` layout. One new module (`renewal.py`); all
other changes are small extensions of existing modules.

## Complexity Tracking

> No Constitution Check violations — section intentionally empty.