# Concept: Read-only Schwab MCP server

- **Slug**: api-engine
- **Created**: 2026-10-19
- **Recommended option**: B — build a thin read-only MCP layer on Schwabdev

## Options

### Option A — Adopt `jkoelker/schwab-mcp` as-is

- **Sketch**: The owner installs and configures the existing, actively
  maintained Schwab MCP server (MIT, Python, stdio by default) and points
  his MCP client at it. No code is written in this repo; `schwab-mcp-v2`
  becomes configuration and documentation only. The user experience
  immediately includes account-info tools (balances, positions,
  transactions, orders) plus a large set of features he does not need
  (trading with Discord/Signal approval workflows, technical analysis).
- **Appetite**: small (days)
- **Trade-offs**: wins speed and battle-tested maturity (65 stars, 338
  commits, mutation-tested); sacrifices ownership of the code, enforces an
  opinionated surface far beyond the read-only need, and inherits its
  dependency risk — the server pins `schwab-py` to the author's own fork
  (`jkoelker/schwab-py`, branch `proxy_support`), a fork-of-fork chain
  outside the owner's control. Tension with the project's stated purpose
  (`schwab-mcp-v2` as a real project) and with learning/ownership goals.
- **Rabbit holes**: if any desired behavior differs from upstream (token
  budgets, response shaping, read-only guarantee), the owner must fork and
  maintain a fork — silently converting A into B with worse provenance;
  upstream dependency drift (Schwab API changes) arrives uninvited.

### Option B — Build a thin read-only MCP layer on Schwabdev (recommended)

- **Sketch**: The owner gets a small, purpose-built local stdio MCP server
  written in Python (`src/`), exposing only read-only account tools:
  balances, positions, and order/transaction history, with deliberately
  shaped, token-budgeted responses. The Schwab-specific work (OAuth token
  lifecycle, endpoint calls) is reused from `schwabdev` — the actively
  maintained client (v4.0.0, Aug 2026, Production/Stable, trusted
  publishing) — while the thin MCP layer, the response shaping, and the
  token/performance tests are the owner's code, driven by TDD per the
  constitution.
- **Appetite**: small–medium (1–2 weeks of part-time work)
- **Trade-offs**: wins exact fit to the read-only scope (KISS), full
  ownership and testability, token budgets enforced by tests (Principle
  V), and principled reuse (Principle III) at the layer where reuse
  matters most — the API client — without adopting unneeded machinery;
  sacrifices the maturity/community surface of an existing server (65★
  vs. a fresh codebase) and takes on maintenance of the MCP layer when
  Schwab's API drifts (mitigated by Schwabdev's active cadence).
- **Rabbit holes**: replicating features of the existing server (trading,
  streaming, technical analysis) — the non-goals exist to prevent this;
  Schwab's account/transactions JSON is large and nested, so response
  shaping can balloon into a general-purpose transformer if not kept
  minimal; the one-time OAuth browser flow may be awkward to wire into a
  headless stdio server (Schwabdev provides token management; verify how
  its auth bootstrap fits `tests/`-driven development).

### Option C — Direct HTTP client, no wrapper library

- **Sketch**: The MCP layer speaks to Schwab's REST endpoints directly
  (httpx/requests), implementing OAuth 2.0 authorization, token refresh,
  and endpoint calls in-repo. Maximum control, zero third-party client
  dependencies.
- **Appetite**: medium (weeks) — driven by auth, not endpoints
- **Trade-offs**: wins total control and zero wrapper-dependency risk;
  sacrifices the biggest reuse opportunity and re-implements the exact
  part both candidate libraries (and the prior-art MCP server) already
  solved — schwab-py's author explicitly calls rolling your own OAuth
  flow "unnecessarily complex and dangerous". Constitution Principle III
  (reuse before creation) weighs directly against it; justified only if
  no library were acceptable.
- **Rabbit holes**: OAuth edge cases (refresh windows, callback URL
  hosting, token expiry), silent API drift without an upstream to track,
  and security-sensitive code (credentials) that must be tested but
  duplicates known solutions.

## Recommendation

**Option B — build a thin read-only MCP layer on Schwabdev.** Rationale
tied to the problem's goals and metrics:

- It is the only option that satisfies the read-only scope *exactly*
  while keeping ownership and testability (goals: reliable access,
  token-efficient responses, evidence-based route).
- It applies Principle III where it pays off: reuse the maintained Schwab
  client (Schwabdev) and the official MCP SDK; build only the thin,
  purpose-specific layer.
- It avoids Option A's fork-of-fork dependency (`jkoelker/schwab-py` on
  `schwab-py`) and its scope bloat; avoids Option C's OAuth re-
  implementation that research flags as complex and risky.
- It matches the project's evident intent (`schwab-mcp-v2` as a real,
  owned codebase) and its constitution gates (TDD-first, token-usage
  tests, performance budgets) fit a small greenfield layer better than a
  large adopted one.

## Out of Scope (for the recommended option)

- Order placement, modification, cancellation — any money-moving operation
- Real-time/streaming data and market quotes
- Multi-user support, remote/hosted deployment, public distribution
- Brokerage features beyond account reading (option chains, movers,
  paper trading, technical analysis)
- Discord/Signal approval workflows (irrelevant without trading)

## Assumptions to Validate

- `schwabdev` covers the read-only surface needed: account numbers,
  account details with positions, and transactions/order history
  (verify against its API docs during `/speckit.specify`)
- `schwabdev`'s OAuth bootstrap and token refresh work in a headless
  stdio-server context, with a one-time interactive browser login
- The owner has (or will register) an approved Schwab developer app;
  approval may take days — acceptable residual ToS risk documented in
  problem.md
- Local Python 3.11+ environment (Schwabdev requires >=3.11) is
  acceptable — it was implicitly chosen at intake
- Schwab's account/transactions payloads can be shaped into
  token-budget-compliant responses with simple field selection and
  pagination (validated by token-usage tests)
