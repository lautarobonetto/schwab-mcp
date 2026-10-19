# Idea Research: Schwab API access strategy for the MCP server

- **Slug**: api-engine
- **Created**: 2026-10-19
- **Evidence confidence (overall)**: medium

## Users & Demand

- The primary user is the project owner himself: a local, single-user stdio
  MCP server for his own trading account (intake context). Demand is personal
  utility, not market-facing — [source: intake.md, conversation] (confidence: high, cited)
- Community demand for a Schwab MCP exists: an active r/Schwab thread
  ("SCHWAB needs an MCP. All the cool brokers are doing it now") shows
  third-party brokers' MCP integration is a felt need — [source: reddit.com
  r/Schwab thread via websearch snippet, not fetched] (confidence: medium, cited)

## Prior Art

- **`jkoelker/schwab-mcp`** (GitHub, MIT, Python): a Schwab MCP server that
  does almost exactly what this project proposes — stdio transport by
  default, market data + account info tools (balances, positions,
  transactions, orders), optional trading gated behind approval workflows.
  65 stars, 23 forks, 338 commits, actively structured (src/ + tests/,
  pytest, ruff, mutation testing, uv). Notably it already addresses token
  efficiency: a `--json` mode that "strips null/empty fields to reduce token
  usage" — [source: https://github.com/jkoelker/schwab-mcp, allowlisted]
  (confidence: high, cited)
- **`sudowealth/schwab-mcp`** (GitHub, TypeScript): MCP server for Schwab
  built on `@modelcontextprotocol/sdk` + `workers-mcp` — [source:
  github.com/sudowealth/schwab-mcp via websearch snippet, not fetched]
  (confidence: medium, cited)
- **`chensirui2008/schwab-mcp`**: "production-grade, single-user remote MCP
  server self-hosted on Cloudflare Workers" — [source:
  mcpservers.org/servers/chensirui2008/schwab-mcp via websearch snippet, not
  fetched] (confidence: low, cited)
- **Candidate libraries** (the idea's central question):
  - `schwabdev` (Tyler Bowers): latest release **4.0.0, Aug 9, 2026**;
    releases through 2024–2026 (3.0.x Feb–May 2026, 3.0.0 Dec 2025, 2.5.x
    2025); MIT; Python >=3.11; PyPI classifier "Production/Stable"; 878
    stars, 284 forks; publishes with PyPI trusted publishing from GitHub
    Actions — [source: pypi.org/project/schwabdev/, confirmed-by-user;
    github.com/tylerebowers/Schwabdev, allowlisted] (confidence: high, cited)
  - `schwab-py` (Alex Golec): latest release **1.5.1, Jun 30, 2025** — no
    release in ~16 months; prior releases 1.5.0 (Mar 2025), 1.4.0 (Sep
    2024); MIT; Python >=3.10; 477 stars, 129 forks, 39 open issues, 17
    open PRs; positions itself as "thin and unopinionated" (returns raw
    responses); comprehensive readthedocs — [source:
    pypi.org/project/schwab-py/, confirmed-by-user;
    github.com/alexgolec/schwab-py, allowlisted] (confidence: high, cited)

## Market & Context

- Schwab officially operates a Developer Portal with an "Individual
  Developer" product ("Trader API -- Individual") requiring app approval
  before use; approval "can take several days" per schwab-py's README —
  [source: developer.schwab.com pages via websearch snippets (direct fetch
  returned 403); github.com/alexgolec/schwab-py README] (confidence: high, cited)
- Today's alternatives for LLM access to Schwab accounts: the existing MCP
  servers listed above (DIY vs. hosted options), plus manual portal/API use.
  Cost of doing nothing: no LLM access to the account — [source: prior art
  section] (confidence: medium, cited)

## Data & Constraints

- Both candidate libraries are Python (matches the resolved runtime choice,
  Python) and require the user's own Schwab developer app credentials (API
  key + app secret + callback URI) — [source: both libraries' READMEs/PyPI]
  (confidence: high, cited)
- Neither library is affiliated with or endorsed by Schwab; both carry
  disclaimers to read the Schwab API ToS — [source: both libraries' pages]
  (confidence: high, cited)
- Schwab account access uses OAuth 2.0 with token refresh; Schwabdev
  advertises automatic token management/refresh and optional token
  encryption; schwab-py handles token fetch/refresh — [source: both
  libraries' pages] (confidence: high, cited)
- Scope constraint resolved at intake: read-only account data only
  (balances, positions, order history); no orders, no streaming — [source:
  intake.md] (confidence: high, cited)
- Read-only subset needed is small: accounts/balances/positions and
  transactions/order history endpoints, all covered by both libraries'
  HTTP client surface — [source: schwab-py docs index (client.html covers
  Account Info, Orders); Schwabdev "access the full api"] (confidence:
  medium, cited)

## Evidence Against the Idea

- **Prior art may already solve the problem**: `jkoelker/schwab-mcp` is a
  Python, stdio, MIT Schwab MCP server with account-info tools and even
  token-efficiency features. Building from scratch duplicates it — this is
  the strongest challenge and directly engages constitution Principle III
  (reuse before creation): the decide stage must weigh "adopt/adapt
  jkoelker/schwab-mcp" vs "build our own" — [source:
  github.com/jkoelker/schwab-mcp] (confidence: high, cited)
- **The "use a library" half of the idea has a stale candidate**: schwab-py
  has had no release in ~16 months while Schwab's API has drifted before
  (tda-api broke completely when TDAmeritrade was retired) — [source:
  pypi.org/project/schwab-py/; schwab-py tda-transition docs] (confidence:
  medium, cited)
- **The "direct API" half has a real onboarding cost**: implementing OAuth
  2.0 token lifecycle by hand is exactly the complexity schwab-py warns
  about ("too many people online end up rolling their own implementation of
  the OAuth callback flow. This is both unnecessarily complex and
  dangerous") — [source: github.com/alexgolec/schwab-py README]
  (confidence: high, cited)
- **ToS ambiguity is unresolved**: the developer program terms exist but
  could not be read directly (403); we only know an approved app is
  required and that both wrappers disclaim affiliation — [source:
  developer.schwab.com/terms-and-conditions via snippet; 403 on direct
  fetch] (confidence: medium, cited)

## Gaps & Open Questions

- [NEEDS CLARIFICATION: full text of Schwab's developer terms/ToS — direct
  fetch of developer.schwab.com returned HTTP 403; verify ToS status of
  personal-use API access before the decide stage]
- [NEEDS CLARIFICATION: which Schwab client library jkoelker/schwab-mcp
  builds on (README does not say) — relevant to evaluate it as a reuse
  candidate; inspectable later at github.com/jkoelker/schwab-mcp (repo,
  allowlisted)]
- [NEEDS CLARIFICATION: whether the user wants a personal bespoke server
  (learning/control) or would adopt an existing MCP server as-is]

## Sources

- https://github.com/alexgolec/schwab-py (host: github.com, policy: allowlisted)
- https://github.com/jkoelker/schwab-mcp (host: github.com, policy: allowlisted)
- https://github.com/tylerebowers/Schwabdev (host: github.com, policy: allowlisted; fetched at intake)
- https://schwab-py.readthedocs.io/en/latest/ (host: schwab-py.readthedocs.io, policy: confirmed-by-user; fetched at intake)
- https://pypi.org/project/schwab-py/ (host: pypi.org, policy: confirmed-by-user)
- https://pypi.org/project/schwabdev/ (host: pypi.org, policy: confirmed-by-user)
- https://developer.schwab.com/ (host: developer.schwab.com, policy: confirmed-by-user — fetch failed HTTP 403)
- https://developer.schwab.com/terms-and-conditions (host: developer.schwab.com, policy: confirmed-by-user — referenced via websearch snippet only)
- https://www.reddit.com/r/Schwab/comments/1uflbg5/ (host: reddit.com — websearch snippet only, not fetched)
