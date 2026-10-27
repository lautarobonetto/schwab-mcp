<!--
SYNC IMPACT REPORT
==================
Version change: (none) → 1.0.0
Bump rationale: MINOR-equivalent initial ratification — roadmap created from
  template with the harvested vision, cross-cutting constraints, and the
  12-spec ledger (010–021) confirmed by the user in session.

Changes this revision:
  - Created roadmap (initial ratification, v1.0.0)
  - Added specs 010–016 (status: planned) — passthrough market-data tools and
    first derived-analysis tools
  - Added specs 017–021 (status: undecided) — value-add derived tools pending
    prioritization
  - Decision recorded: C-06 — read-only surface; place_order / preview_order
    are explicit scope-out (no spec will be created for them)
  - Decision recorded: C-08 — source-of-truth split with the `fmp` MCP

Specs affected: 010, 011, 012, 013, 014, 015, 016, 017, 018, 019, 020, 021
Open questions added/resolved: added Q1–Q4 (see Open Questions)

Notes: Ledger numbering continues after the last existing spec directory
  (specs/009-mcp-release-packaging). Specs 004 and 005 are absent from
  specs/ (not created); the ledger only records specs from 010 onward —
  001–009 are already implemented and tracked by their spec directories.
-->

# Schwab MCP — Spec Roadmap

Living, non-binding map of the specs planned for Schwab MCP. It is **not a
commitment to order or scope** — it captures the spec-specific discussion,
decisions, technology choices, outcomes, and constraints surfaced during the
constitution and grilling phases so they are not lost before the spec that
needs them is written. Specs are scoped and clarified when they are actually
started. Foundations: the project
[constitution](constitution.md) and the agent-facing interface contract
[docs/tools.md](../../docs/tools.md).

Status legend (lifecycle): **undecided** · **needs-info** · **planned** ·
**specced** · **in-progress** · **implemented** · **verified** ·
**deferred** · **abandoned**.

---

## Vision & End States

- **End state 1 — Autonomous trading-analysis capability.** An AI agent can
  complete an end-to-end trading analysis (screening, technical, options,
  portfolio risk) using only this MCP plus `fmp`, without human
  intervention and without stitching raw passthrough payloads by hand.
- **End state 2 — Full market-data coverage of the underlying SDK.** Every
  read-only capability of `schwabdev` 4.0.0 that is useful to an agent
  (quotes, price history, expiration chains, market hours, instrument
  search, movers, order status) is exposed through an MCP tool or a
  documented reason why it is not.
- **End state 3 — Derived-analysis surface.** Composite tools compute what
  agents repeatedly recompute by hand (portfolio greeks, spread economics,
  IV context, transaction chains) so analysis outputs are deterministic,
  token-bounded, and tested.
- **End state 4 — Invariant agent contract.** Every tool keeps the
  cross-cutting guarantees of the existing surface: non-interactive, one
  JSON line, no secrets, bounded time, structured outcomes, read-only.

## Constraints & Decisions

- **C-01 — TDD is mandatory:** every spec starts with failing tests
  (constitution Principle I); bug fixes begin with a regression test.
- **C-02 — DRY / single source of truth:** shared provider unwrapping,
  error mapping, schemas, and rounding rules stay in one implementation
  (constitution Principle II).
- **C-03 — Reuse before creation:** `schwabdev` capabilities are wrapped,
  not reimplemented; new modules need written justification
  (constitution Principle III).
- **C-04 — KISS / YAGNI:** the simplest tool that satisfies the stated
  analysis need wins; speculative parameters are not built
  (constitution Principle IV).
- **C-05 — Token and performance budgets per tool:** each tool documents
  its expected payload size and latency budget; token-usage and performance
  tests are part of the definition of done (constitution Principle V).
- **C-06 — Read-only surface (decision, 2026-10-27):** the MCP places no
  orders and moves no money. `place_order`, `cancel_order`,
  `replace_order`, and `preview_order` are **explicit scope-out**: no spec
  will be created for them. `preview_order` as a paper-trading simulator
  could be revisited only as a separate governance decision; it is not on
  the roadmap.
- **C-07 — English-only documentation and comments** (constitution
  Principle VII).
- **C-08 — Source-of-truth split with `fmp` (decision, 2026-10-27):** this
  MCP serves Schwab data only (positions, transactions, chains, quotes,
  candles, hours, instruments, orders status). Earnings calendars,
  dividends, and fundamentals come from the `fmp` MCP and are never
  duplicated here. Specs that need both sources do the **join** on this
  side only if Schwab holds one half (see 019).
- **C-09 — Curated-first output pattern (established by 003/006/008):**
  tools return a compact curated result by default and add a raw
  `extended`/`provider` passthrough only on request; filtering parameters
  exist to bound payload before fetch, not to paginate afterwards.

## Planned Specs

### Market-data passthrough (SDK capabilities not yet served)

### 010 — Real-time quotes (`get_quotes`)  [status: planned]

- **Description:** MCP tool wrapping `schwabdev` `quotes()` (multi-symbol)
  and/or `quote()` (single symbol): current price, bid/ask, volume, and
  quote freshness for 1..N symbols in one invocation.
- **Outcome:** the agent can obtain current prices without pulling an
  option chain (~95k tokens) or other heavyweight payload.
- **Scope (in):** single and multi-symbol queries; curated compact output
  with `data_state` (realtime/delayed); `extended` passthrough (C-09).
- **Scope (out):** order book depth not provided by the SDK; chart data
  (that is 011).
- **Depends on:** none.
- **Governed by:** C-05, C-06, C-09.
- **Notes:** first implementation priority together with 011; expected
  payload must stay in the hundreds of tokens per symbol.

### 011 — Price history OHLCV (`get_price_history`)  [status: planned]

- **Description:** MCP tool wrapping `schwabdev` `price_history()` with
  bounded `periodType`/`frequencyType` selection: OHLCV candles for
  technical analysis, historical volatility, trends, and backtesting.
- **Outcome:** the agent can run technical and volatility analysis from a
  single deterministic call.
- **Scope (in):** period/frequency parameters with hard defaults and
  ceilings that bound payload (C-05); volume included; `extended`
  passthrough.
- **Scope (out):** indicator computation (agent-side or later derived
  spec); intraday tick data beyond what the SDK exposes.
- **Depends on:** none.
- **Governed by:** C-04, C-05, C-09.
- **Notes:** unbounded candle windows are a context hazard — the default
  must be small and every ceiling test-enforced.

### 012 — Option expiration list (`get_option_expiration_chain`)  [status: planned]

- **Description:** MCP tool wrapping `schwabdev`
  `option_expiration_chain()`: the list of expirations for an underlying
  without strikes or greeks.
- **Outcome:** "which expirations exist?" costs hundreds of tokens instead
  of the 5–110k of a full `get_option_chain` call.
- **Scope (in):** expiration dates with DTE; DTE ceiling consistent with
  008's `dte_max_effective` semantics.
- **Scope (out):** strikes, greeks, quotes (that is `get_option_chain`).
- **Depends on:** 008 (semantics alignment).
- **Governed by:** C-05, C-09.
- **Notes:** highest token-saving ratio of the passthrough group; natural
  pre-step before a targeted `delta_target` chain query.

### 013 — Market hours and holidays (`get_market_hours`)  [status: planned]

- **Description:** MCP tool wrapping `schwabdev` `market_hours()` /
  `market_hour()`: is the market open, closed, or pre/post for one or more
  markets, plus holiday schedules.
- **Outcome:** the agent can interpret quote/chain freshness correctly
  (stale vs delayed) and avoid analyzing frozen data as if it were live.
- **Scope (in):** single-market and multi-market queries; explicit
  open/closed/pre/post state enum.
- **Scope (out):** order routing logic (read-only surface, C-06).
- **Depends on:** none.
- **Governed by:** C-05.

### 014 — Instrument search (`search_instruments`)  [status: planned]

- **Description:** MCP tool wrapping `schwabdev` `instruments()` /
  `instrument_cusip()`: resolve company names or CUSIPs to canonical
  symbols before calling other tools.
- **Outcome:** no more failed chains caused by ambiguous or misresolved
  symbols; deterministic symbol resolution step in agent workflows.
- **Scope (in):** symbol lookup by search pattern and CUSIP; curated
  compact result (symbol, description, exchange, type).
- **Scope (out):** full fundamental profiles of instruments (C-08 — that
  is `fmp` territory).
- **Depends on:** none.
- **Governed by:** C-08, C-09.

### Derived analysis (computed on top of served data)

### 015 — Portfolio risk snapshot (`get_position_risk`)  [status: planned]

- **Description:** composite tool joining `get_open_positions` (003) with
  quotes (010) and, for options, chain greeks (008): net
  delta/theta/vega/gamma exposure per underlying and per account, unrealized
  P/L, and concentration.
- **Outcome:** portfolio-level risk the agent currently computes by hand
  across N calls and manual arithmetic.
- **Scope (in):** per-position and aggregated views; explicit `null` when a
  component is unavailable (no invented data).
- **Scope (out):** scenario/stress simulation; VaR modeling (YAGNI, C-04).
- **Depends on:** 003, 010, 008.
- **Governed by:** C-05, C-09.
- **Notes:** token budget needs care — aggregate first, per-leg detail
  behind an explicit parameter.

### 016 — Spread analysis (`analyze_spread`)  [status: planned]

- **Description:** composite tool that, given two or more legs
  (type/strike/expiration), computes net debit/credit, breakevens, max
  profit/loss, risk-reward ratio, and IV skew between legs, from
  `get_option_chain` data.
- **Outcome:** deterministic evaluation of verticals, calendars, and
  diagonals before the agent proposes them.
- **Scope (in):** two-leg spreads first; leg validation; explicit outcomes
  when quotes/greeks are missing.
- **Scope (out):** order construction (C-06); multi-leg exotic structures
  (YAGNI until a stated need exists).
- **Depends on:** 008.
- **Governed by:** C-04, C-05.

### Undecided / pending prioritization

### 017 — IV context (`get_iv_context`)  [status: undecided]

- **Description:** composite tool comparing current chain IV against
  historical volatility (from 011) to produce IV rank/percentile context.
- **Outcome:** the agent can distinguish "options expensive" from
  "options cheap" — the central decision in premium selling.
- **Scope (in):** _to be defined_
- **Depends on:** 011, 008.
- **Notes:** undecided pending: lookback window definition for the rank
  (see Q2) and whether HV is computed here or the agent computes it from
  011 output (C-04 pushback).

### 018 — Transaction chain reconstruction (`get_trade_chain_context`)  [status: undecided]

- **Description:** tool that, given a symbol and date range, reconstructs
  the roll/spread chain behind orphan trades (the manual procedure already
  documented in AGENTS.md: backward symbol-filtered sweeps until the
  opening trade is found) and returns the chain with per-leg P/L.
- **Outcome:** codifies a repetitive, error-prone manual workflow into a
  tested, auditable tool.
- **Scope (in):** _to be defined_
- **Depends on:** 006.
- **Notes:** undecided pending: whether the backward-sweep strategy is
  deterministic enough to spec now; overlaps with the AGENTS.md trade
  analysis rule (would need that doc updated in the same commit).

### 019 — Event proximity join (positions/expirations × earnings/dividends)  [status: undecided]

- **Description:** tool that crosses this MCP's positions and option
  expirations against `fmp` earnings dates and dividend ex-dates, flagging
  exposures inside event windows.
- **Outcome:** neither surface does this join alone; it removes a
  recurring manual cross-check before holding options through events.
- **Scope (in):** _to be defined_
- **Depends on:** 003, 008; external: `fmp` MCP.
- **Notes:** undecided pending: C-08 boundary — whether the join lives here
  (Schwab half is local) or the agent composes both surfaces; FMP estimates
  caveat must surface in the output if included.

### 020 — Market movers (`get_movers`)  [status: undecided]

- **Description:** MCP tool wrapping `schwabdev` `movers()`: top
  up/down movers per index — the only screening entry point the SDK
  offers.
- **Outcome:** "discover opportunities" workflows without an external
  screener.
- **Scope (in):** _to be defined_
- **Depends on:** none.
- **Notes:** undecided pending prioritization: screening is lower value
  than analysis enablement for the current usage pattern.

### 021 — Order status (`get_account_orders`)  [status: undecided]

- **Description:** MCP tool wrapping `schwabdev` `account_orders()` /
  `order_details()`: working, partially filled, and historical orders.
- **Outcome:** `get_transaction_history` shows executions but a working or
  partially filled order is invisible today; this completes the
  position-formation picture.
- **Scope (in):** _to be defined_
- **Depends on:** none.
- **Governed by:** C-06 (read-only — status retrieval, not placement).
- **Notes:** undecided pending: read-only governance is satisfied, but the
  owner's current workflows rarely hold resting orders; prioritize only if
  that changes.

## Open Questions

- **Q1 — Multi-symbol quote batching:** does 010 expose one tool with an
  array parameter, or reuse a single tool for 1..N symbols (SDK supports
  both `quote` and `quotes`)? Resolve during 010 spec clarification
  (DRY favors one tool).
- **Q2 — IV rank lookback:** what window and frequency define the
  historical distribution for 017 (e.g., 252 trading days of daily IV)?
  Resolve when 017 moves to `planned`.
- **Q3 — Derived-tool placement:** do derived tools (015–018) compute
  server-side in this MCP (tested, token-bounded) or stay agent-side
  recipes in `docs/tools.md`? Current leaning: server-side for anything
  invoked more than occasionally (C-04/C-05 tension resolved per tool).
- **Q4 — Payload budget baseline for candles:** what default period and
  ceiling keep 011 under a few thousand tokens while still serving trend
  analysis? Resolve in the 011 plan with a measured baseline
  (constitution Principle V requires recorded justification for growth).

## Cross-Cutting Notes

- **Shared result-shape contract:** every new tool reuses the established
  `outcome`/`detail`/`retryable` envelope and the validation-error pattern
  (fail before any upcall) from 003/006/008 — never invent a second
  envelope (C-02).
- **`extended` passthrough everywhere:** raw provider payloads stay
  reachable through `extended=true` (C-09); curated schemas stay
  token-minimal.
- **`schwabdev 4.0.0` capability ceiling:** the passthrough group (010–014,
  020, 021) is bounded by SDK surface; any SDK upgrade re-opens the ledger
  (reuse-before-creation, C-03).
- **Docs obligation:** every new tool updates `docs/tools.md` (the
  agent-facing contract) and `docs/CHANGELOG.md` in the same commit
  (constitution Commit Discipline).
- **Fixture note (tooling):** `.specify/extensions/roadmap/` self-hosts a
  dev fixture `.specify/` tree; `load-config.sh` resolves to it when run
  by script path. When invoking roadmap commands on this repo, run from
  the repo root and verify `roadmap_path` points at `.specify/memory/`.

---

**Version**: 1.0.0 | **Ratified**: 2026-10-27 | **Last Amended**: 2026-10-27