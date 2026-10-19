# Idea Intake: Schwab API access strategy for the MCP server

- **Slug**: api-engine
- **Created**: 2026-10-19
- **Source**: pasted text (with two URLs)
- **Type**: exploration

## Idea (as captured)

> "Necesito conectarme a las APIs de Schwab, y no estoy seguro si me conviene
> interacturar con las API directamente, o si mejor uso alguna libreria ya
> existe te (ej: https://schwab-py.readthedocs.io/en/latest/ o
> https://github.com/tylerebowers/Schwabdev)"

### Referenced sources

**URL 1: `https://github.com/tylerebowers/Schwabdev`**
- Sanitized URL: `https://github.com/tylerebowers/Schwabdev` (no credentials present)
- Host: `github.com`
- URL Trust Policy branch: **allowlisted** (fetched without prompting)
- Title: "Schwabdev"
- Excerpt: "An easy and lightweight python wrapper for using the Charles
  Schwab API." Not affiliated with or endorsed by Schwab; maintained by
  Tyler Bowers; MIT licensed; "Acts in accordance with Schwab's API terms
  and conditions." Claims: automatic token management and refreshes,
  authenticate and access the full API with minimal code, streaming with
  customizable response handler, order placement, sync and async support,
  optional token database encryption, 878 stars / 284 forks.

**URL 2: `https://schwab-py.readthedocs.io/en/latest/`**
- Sanitized URL: `https://schwab-py.readthedocs.io/en/latest/` (no credentials present)
- Host: `schwab-py.readthedocs.io`
- URL Trust Policy branch: **confirmed-by-user** (host not on safe list; user approved fetch)
- Title: "`schwab-py`: An Unofficial Charles Schwab API Client"
- Excerpt: unofficial API wrapper, "in no way endorsed by or affiliated with
  Charles Schwab"; only supports Python 3.10 and up; documentation covers
  authentication and client creation (OAuth, token expiration), HTTP client
  (accounts, price history, quotes, option chains, instrument search, orders),
  streaming client, order templates and `OrderBuilder`, utilities. The docs
  link to the source repo `github.com/alexgolec/schwab-py` (not fetched).

## Restated

For the Schwab MCP server, a decision is needed on how to reach the Charles
Schwab APIs: calling the REST APIs directly, or going through an existing
third-party Python library (schwab-py or Schwabdev being the examples named).

## Origin & Context

- **Raised by**: the project owner (via conversation), 2026-10-19
- **Trigger**: kickoff of the `schwab-mcp-v2` project — the MCP server needs
  Schwab API access, and the implementation approach is still undecided.
  The project constitution already mandates "reuse before creation"
  (Principle III), which makes the library-vs-direct question a natural
  first assessment.

## First-Glance Unknowns

- [RESOLVED 2026-10-19] The MCP needs **read-only account data only**
  (balances, positions, order history). No order placement, no streaming.
  (User decision, aligned with KISS/YAGNI.)
- [DEFERRED TO RESEARCH] What the Schwab API terms of service say about
  third-party wrappers vs. direct use — hypothesis to verify in
  `/speckit.assess.research` (current ToS at developer.schwab.com; access
  via a user-registered app).
- [DEFERRED TO RESEARCH] Maintenance/health comparison of schwab-py vs
  Schwabdev (release cadence, Schwab API drift coverage, open issues) —
  to be gathered in `/speckit.assess.research`.
- [RESOLVED 2026-10-19] Token cost and latency are **orthogonal** to the
  wrapper-vs-direct choice: both approaches receive the same Schwab JSON
  payloads; the MCP layer's response shaping (field selection, pagination,
  compact formats) determines cost, enforced by constitution Principle V
  token-usage tests. Point benchmarks deferred to `/speckit.plan`.
  (Reasoned decision, user-approved.)
- [RESOLVED 2026-10-19] The MCP server is planned in **Python** (user
  decision), which makes both candidate libraries relevant under
  constitution Principle III (reuse before creation).
