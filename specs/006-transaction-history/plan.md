# Implementation Plan: Account Transaction History

**Branch**: `006-transaction-history` | **Date**: 2026-10-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-transaction-history/spec.md`

## Summary

Expose the MCP tool **`get_transaction_history`**: full history of
movements of all linked accounts between a start date and an end date
(both mandatory, both boundaries inclusive, maximum window 1 year —
clarify Q1), with an optional instrument filter. It brings **all**
movement types from the provider (trades, transfers, dividends and
interest, cash movements, adjustments, etc.), each with a normalized
category from a closed enum (clarify Q3), date/time, description,
amount with currency, account, and instrument when applicable.
Chronological ascending order, total count, explicit pagination of 50
movements per page with a continuation mechanism without duplicates or
gaps (clarify Q4). Actionable errors by category (validation, unknown
instrument, per-account failure, transient, re-auth), no internal
retries, audit per invocation, strictly read-only and declared budgets
(≤ 5 s p95, SC-001; ≤ 16 KB per default page, SC-003).

Technical approach (from research): new module
`src/schwab_mcp/transactions.py` (Pydantic models + provider→model
mapping + per-account orchestration + pagination) following the proven
pattern of `positions.py`; upcalls: 1 `linked_accounts` + 1
`transactions` per account (with the full comma-separated type list —
research D2), 1 `instruments` only when there is a symbol filter
(research D6); split by bisection when hitting the upstream cap of 3000
transactions (research D3). Registration in `server.py` via
`MCPServer.add_tool` with `structured_output`.
**No new dependencies.**

## Technical Context

**Language/Version**: Python ≥ 3.11 (pyproject: `requires-python = ">=3.11"`)

**Primary Dependencies**: `schwabdev==4.0.0` (`Client.linked_accounts`,
`Client.transactions`, `Client.instruments` — signature verified against
the installed SDK), `mcp>=1.0.0` (`MCPServer.add_tool`). Pydantic via
transitive dependency of the MCP SDK (already in use in `positions.py`).
`zoneinfo` (stdlib) for America/New_York. **No new dependencies.**

**Storage**: N/A — ephemeral result; the only storage is the schwabdev
SQLite token store (read-only, unchanged). No cache between requests
(same criterion as features 003 and 005).

**Testing**: pytest 9.x + pytest-asyncio (unit; `performance` marker
already configured for budgets).

**Target Platform**: local `schwab-mcp serve` process, stdio transport
exclusively (constitution: no incoming sockets, no HTTP).

**Project Type**: local MCP server (stdio) — fourth registered tool
alongside `get_open_positions`, `get_asset_metrics` and
`get_metric_catalog`.

**Performance Goals**: query ≤ 5 s p95 (SC-001); upcalls linear in
linked accounts (1 per account), all types grouped into 1 call per
account (never 1 per type).

**Constraints**: bounded default payload (SC-003: ≤ 16 KB page of 50
movements; extended ≤ 64 KB declared); window ≤ 1 year (clarify Q1);
no secrets in outputs; no internal retries (FR-010); audit per
invocation (FR-011); strictly read-only (FR-012).

**Scale/Scope**: all linked accounts; up to 3000 movements per
(account, call) — the upstream cap is handled with split by bisection
(research D3); pages of 50 movements (clarify Q4).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Status | Evidence |
|------|--------|-----------|
| I. Test-First | PASS | tasks.md (Phase 2) will order tests first: date/window validation, provider→category mapping with fixtures of the 15 types, pagination (no duplicates/gaps), errors by category, partial accounts, audit, performance, token-usage |
| II. DRY | PASS | Reuses `errors.py` (AuthError taxonomy), `log.auth_event` + redaction filter, `tokens.retry_call`, the outcome/detail/accounts_failed pattern of `positions.py`; the outcome vocabulary has a single reused definition |
| III. Reuse Before Creation | PASS | Existing SDK upcalls (`linked_accounts`/`transactions`/`instruments`); `MCPServer.add_tool` from the SDK; stdlib `zoneinfo`; mapping pattern of `positions.py` — **no new libs** |
| IV. KISS | PASS | Offset-based pagination without server state; no currency conversion (out of scope); no cache between requests; the SDK validator bypass is scoped to one documented helper function (research D2) — the alternative (15 upcalls per account) violates the latency budget |
| V. Efficiency & Cost | PASS | Declared budgets: ≤ 5 s p95 (SC-001), ≤ 16 KB default page (SC-003), ≤ 64 KB extended; description truncated to 80 characters in default (full text in extended); performance + token-usage tests required in tasks |
| Fixed layout | PASS | Code → `src/schwab_mcp/`; tests → `tests/`; affected docs (`docs/tools.md`, CHANGELOG) in the same implementation commit |
| Credential safety | PASS | No result field or event carries tokens/secrets; opaque account_hash (never account number); redaction filter remains active; the contract verifies it with a test |
| Read/write discipline | PASS | Strictly read-only tool: history query, no orders or money movements |

**Re-check post-Phase 1**: PASS — contracts and the data model reuse the
outcome vocabulary of 003 and the event channel of 002; the only
divergence from the spec (enum value `dividend_or_interest`, research
D5) is documented and applied to the spec; no entries in Complexity
Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/006-transaction-history/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   ├── mcp-tools.md     # get_transaction_history
│   └── events.md        # Audit events of the query
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/schwab_mcp/
├── transactions.py      # NEW: Pydantic models, provider→model mapping,
│                        # category normalization, per-account orchestration,
│                        # pagination, split at the 3000 cap
├── server.py            # MODIFIED: registers get_transaction_history
├── errors.py            # REUSED unchanged (AuthError taxonomy/exit codes)
├── log.py               # REUSED unchanged (auth_event + redaction filter)
├── tokens.py            # REUSED unchanged (retry_call)
├── positions.py         # REUSED unchanged (pattern reference: outcome/
│                        # detail/accounts_failed/_hash_account)
└── metrics.py           # REUSED unchanged (registration pattern reference)

tests/
├── unit/                # TDD tests: validation, mapping, categories, pagination,
│                        # errors, partial accounts, no secrets
└── performance/         # latency and token-usage budgets
```

**Structure Decision**: existing repo structure (src/ + tests/), no new
directories; `transactions.py` is the only new module and follows the
consolidated pattern of `positions.py` (models + mapping + orchestration
in one place).

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No entries: no constitution violations to justify.