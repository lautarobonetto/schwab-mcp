# Decision: Read-only Schwab MCP server

- **Slug**: api-engine
- **Decided**: 2026-10-19
- **Verdict**: go
- **Artifacts reviewed**: intake.md | research.md | problem.md | concept.md

## Scorecard

| Criterion | Rating | Justification |
|-----------|--------|---------------|
| Problem validity | strong | Real, sharply bounded personal problem (no LLM access to Schwab account data), owner-confirmed scope (read-only), grounded in intake + problem definition |
| Evidence strength | adequate | Library health and prior art fully cited from fetched primary sources (PyPI, GitHub); one accepted gap — Schwab ToS full text unread (HTTP 403) with documented residual risk, and theOAuth-headless assumption flagged for validation. Nothing decision-critical is assumption-driven |
| Value vs. inaction | adequate | Manual fallback exists (bounded cost), but the project's purpose stays unfulfilled without it; personal utility is clear even if modest in market terms |
| Feasibility / appetite | strong | Option B is a thin layer on an actively maintained client (Schwabdev v4.0.0, Aug 2026); prior art (`jkoelker/schwab-mcp`) proves the concept is buildable; appetite small–medium fits a personal project |
| Strategic fit | strong | Option B operationalizes the constitution directly: reuse at the client layer (Principle III), minimal surface (KISS), TDD-first, token-usage tests (Principle V), read-only discipline per Project Context |
| Risk posture | adequate | Major risks identified and consciously handled: fork-of-fork dependency avoided by design, ToS residual risk documented and accepted, OAuth-headless and payload-shaping assumptions explicitly deferred to specification for validation. No serious unmitigated risk remains open |

## Verdict & Rationale

**Go.** The problem is real and precisely bounded; evidence is cited and
sufficient for a delivery decision (the single gap — unread ToS text — is
documented with an accepted, compliant-by-design mitigation path: the
owner's own registered developer app); a recommended concept exists whose
appetite fits the project; and the recommended option (B — thin read-only
MCP layer on Schwabdev) aligns with every constitution principle,
resolving the reuse-vs-build tension by reusing the maintained Schwab
client while owning the thin, testable MCP layer. The one acknowledged
`unknown`-adjacent item (ToS text) is recorded, not glossed: it does not
block specification because the access approach is compliant under the
documented assumption, and the residual risk is accepted by the sole
stakeholder (the owner).

## If needs-clarification

Not applicable — verdict is go.

## If go — Handoff to `/speckit.specify`

- **Problem**: The owner cannot query his Schwab trading account data
  through LLM tools; there is no reliable, credential-safe, decided access
  path from a local Python MCP server to the Schwab API.
- **Chosen approach**: Option B — build a thin, read-only, local stdio MCP
  server in Python; reuse `schwabdev` (actively maintained Schwab API
  client, v4.0.0) for OAuth/token lifecycle and endpoint calls; own only
  the thin MCP tool layer, response shaping, and tests.
- **In scope / out of scope**: In — read-only tools for balances,
  positions, and order/transaction history, token-budgeted responses,
  TDD-driven implementation. Out — orders/trading of any kind, streaming,
  quotes/market data, multi-user, remote/hosted deployment, public
  distribution.
- **Success metrics**: read completes end-to-end without manual steps;
  responses within declared token budgets (tested); full suite green at
  every commit; zero credential leaks; authenticated reads work without
  manual token fiddling between sessions.
- **Carried-forward open questions**:
  1. Validate `schwabdev` covers account details + positions +
     transactions/order history for the read-only surface (during
     specification)
  2. Validate `schwabdev`'s OAuth bootstrap/token refresh works headless
     with a one-time browser login (during specification)
  3. Confirm the owner's Schwab developer app is registered/approved
     (owner action; approval can take days)
  4. Accepted gap: Schwab ToS full text unread — residual risk accepted;
     revisit only if Schwab policy signals change
