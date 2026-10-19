# Problem Definition: LLM access to Schwab account data

- **Slug**: api-engine
- **Created**: 2026-10-19
- **Inputs used**: intake.md | research.md

## Problem Statement

The project owner cannot query his Charles Schwab trading account data
through LLM-based tools: today every consultation (balances, positions,
order history) requires manual access, and there is no decided, reliable,
credential-safe path to connect a local AI agent to the Schwab API — the
access route (direct HTTP or an existing wrapper library) is undecided and
unevaluated against maintenance, compliance, and efficiency criteria.

## Affected Users & Stakeholders

- **Users**: the project owner — the only person who experiences the
  problem; he wants to consult his trading account data conversationally
  via a local MCP client (research confirms single-user, personal utility,
  read-only scope).
- **Stakeholders**: the project owner (decider and funder); Charles Schwab
  (ToS counterpart — the API may only be used through an approved,
  user-registered developer application; compliance is non-negotiable per
  research).

## Goals

- An LLM tool (MCP client) can read the owner's account data — balances,
  positions, and order history — locally, without manual steps per query.
- Account access is reliable: authentication and token lifecycle work
  without manual intervention.
- Credentials and tokens are never exposed in version control, logs, or
  tool outputs (constitution: Project Context & Constraints).
- Responses are token-efficient: payloads shaped to minimize LLM token
  cost, enforced by tests (constitution Principle V).
- The access route to the Schwab API is chosen from evidence (library
  health, ToS compliance, reuse of existing work — constitution
  Principles II–IV), not from enthusiasm.

## Non-Goals

- Placing, modifying, or canceling orders — no money-moving operations of
  any kind (intake resolution: read-only account data only).
- Real-time/streaming market data or quotes (intake resolution).
- Multi-user support, hosted/remote deployment, or public distribution —
  local stdio, single user only.
- Brokerage features beyond account reading (option chains, movers,
  trading strategies, paper trading).
- Solving the ToS question by assumption — it must be verified, not
  presumed (research gap).

## Success Metrics

- A read of balances/positions/order history completes end-to-end from the
  MCP client without manual steps (baseline: manual portal/API access
  required today — qualitative).
- Tool responses stay within declared token budgets per call, asserted by
  token-usage tests (baseline: unknown — no code exists yet).
- The full test suite passes with zero skipped tests at every commit
  (constitution Commit Discipline; baseline: no suite exists yet).
- Zero credential/token leaks across code, logs, and git history
  (baseline: N/A — no code exists yet).
- Authenticated read success rate in routine use approaches 100% with no
  manual token fiddling between sessions (baseline: unknown).

## Cost of Inaction

If nothing is built, every account consultation stays manual: the owner
opens the Schwab portal or scripts API calls by hand each time, loses the
conversational/analytical value of an LLM over his own data, and the
`schwab-mcp-v2` project delivers nothing. The opportunity cost is bounded —
the owner can always fall back to manual access — but the project's
purpose remains unfulfilled.

## Open Questions

- [RESOLVED 2026-10-19] Schwab ToS: direct fetch of
  developer.schwab.com returned HTTP 403. Resolution: proceed on secondary
  evidence with an accepted, documented residual risk — access via the
  owner's own registered and approved developer app (Individual Developer
  product); the access vehicle (wrapper library vs. direct HTTP) does not
  change the legal point, since both use the user's own app. The full ToS
  text remains unread; flagged as an accepted gap.
- [RESOLVED 2026-10-19 (verified)] jkoelker/schwab-mcp builds on
  **schwab-py**, pinned to the author's own fork (`jkoelker/schwab-py`,
  branch `proxy_support`) rather than the upstream PyPI package — evidence
  that upstream schwab-py's staleness (16+ months without a release)
  already forced a third-party patch. It also uses the official `mcp` SDK
  (FastMCP), Python >=3.10, and a token-oriented output format
  (python-toon). [source: github.com/jkoelker/schwab-mcp pyproject.toml,
  allowlisted]
- [CARRIED TO SHAPE] Adopt `jkoelker/schwab-mcp` (as-is or fork/adapt) vs.
  build our own thin read-only MCP layer on top of a maintained Schwab
  client library — deliberately left as the central option set for
  `/speckit.assess.shape` to frame with full trade-offs and for
  `/speckit.assess.decide` to resolve.
