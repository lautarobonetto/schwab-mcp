# Research: Real-Time Quotes (`get_quotes`) (010)

Feature: 010-real-time-quotes | Date: 2026-10-27
All decisions below resolve the technical unknowns of the spec. Evidence
sources: `schwabdev` 4.0.0 client source (installed package), existing tool
modules (`positions.py`, `transactions.py`, `options_chain.py`), and the
codebase-memory graph (tool registration and shared-helper patterns).

## D1 — Surface: single tool for 1..N symbols via `quotes()`

**Decision**: one MCP tool `get_quotes(symbols, extended=False)`. The
orchestration calls `schwabdev.quotes(symbols, fields=..., indicative=False)`
for every count, 1..20 included. The SDK's single-symbol `quote()` endpoint
is not used.

**Rationale**: the roadmap open question Q1 leaned DRY and the spec resolved
it the same way (Clarifications, Q3 session 2026-10-27). `quotes()` accepts a
list or comma-joined string and hits `/marketdata/v1/quotes` in one request,
so one code path serves single and batch; a second endpoint would duplicate
unwrap/curate logic (C-02) for zero benefit.

**Alternatives considered**:
- Use `quote()` for n=1 and `quotes()` for n>1 — two code paths, two test
  matrices, no payload benefit; rejected (C-02/C-04).

## D2 — `fields` parameter strategy

**Decision**: default (curated) requests call `quotes(..., fields="quote")`;
`extended=true` requests call `quotes(..., fields="all")`.

**Rationale**: `"quote"` bounds the provider payload to the market-data
fields the curated schema needs (prices, volume, quote type, trade time),
serving the token budget (C-05). The raw-payload guarantee of extended mode
(SC-006) requires the complete provider payload, which only `fields="all"`
returns. One parameter of the shared provider call varies per mode; no new
tool parameter is exposed to the agent (KISS).

**Alternatives considered**:
- Always `fields="all"` and curate afterwards — inflates transfer size on
  every invocation; rejected (C-05).
- Expose a `fields` tool parameter — speculative surface (YAGNI); rejected.

## D3 — Provider response shape and missing-symbol detection

**Decision**: treat `/marketdata/v1/quotes` as returning an object keyed by
requested symbol, where only symbols the provider could quote appear.
Detection of "provider could not quote a requested symbol" = requested
distinct symbols minus response keys. Each such symbol becomes a per-symbol
error entry in the structured error (FR-006 — no partial data).

**Rationale**: this is the documented behavior of the Schwab market-data
quotes endpoint (absent key, not an error entry, for unknown symbols). The
keyed shape also matches the clarification "object keyed by symbol". This
will be pinned by the first failing fixture test (TDD): a fake client that
returns a subset of requested keys must produce a structured error naming
the missing symbols, with no partial quotes.

**Alternatives considered**:
- Fabricate a zero/empty quote for missing keys — violates FR-012; rejected.

## D4 — `data_state` derivation (realtime / delayed / closed)

**Decision**: derivation ladder per symbol, computed server-side:

1. **Closed check first**: one `schwabdev.market_hours(...)` call per
   invocation covers the regular session shared by the three accepted symbol
   kinds (equities/ETFs, option contracts, and index symbols all trade on
   the same regular market schedule). If that market is closed →
   `data_state = "closed"`, regardless of `quoteType`.
2. **Open**: provider `quoteType == "Realtime"` → `"realtime"`; any other
   `quoteType` value (e.g., "Indicated") → `"delayed"`.
3. **Missing or unrecognized `quoteType`** → `"delayed"` (conservative:
   never claim live when uncertain).

If the market-hours call fails, the invocation fails with a structured
retryable error (FR-006/FR-011) — freshness must be deterministic or absent,
never guessed.

**Rationale**: provider quote payloads do not carry a market-open flag, and a
trade-time heuristic breaks on holidays and half-days (non-deterministic).
The SDK already exposes market hours (reuse before creation, C-03); one call
per invocation stays inside the 5 s p95 budget. The mapping is pinned by
fixture tests (`test_quotes_data_state.py`). If during implementation the
recorded provider payload is found to expose an authoritative open/closed
indicator, the ladder may drop the extra call — a strictly simplifying
change (C-04) recorded in tasks.

**Alternatives considered**:
- Two states only (spec Q2 option A) — superseded by the user's clarified
  choice of three states.
- Trade-time staleness heuristic — fails on holidays/short sessions;
  rejected.
- One market-hours call per symbol — needless provider traffic; rejected
  (single call per invocation).

## D5 — Symbol-kind validation (FR-013)

**Decision**: validate per kind by shape, before any upcall:

| Kind | Shape (normalized uppercase) | Examples |
|---|---|---|
| Index | leading `$` + 1–5 alphanumerics | `$SPX`, `$VIX`, `$DJI` |
| Option contract | OCC-style: root (letters, `.` allowed) + `YYMMDD` + `C`/`P` + strike (≥ 1 digit, optional decimals), separators (space/underscore) allowed between root and OCC tail | `AAPL 251127C200`, `AAPL_251127P200.5` |
| Equity/ETF | 1–6 alphanumerics with at most one embedded `.` (class shares) | `AAPL`, `NOK`, `BRK.B` |

Normalization: strip whitespace, uppercase, de-duplicate after
normalization; the count limit (20) applies to distinct symbols. A malformed
symbol fails validation naming the symbol. Exact regexes are normative in
`contracts/mcp-tools.md` and pinned by `test_quotes_validation.py`.

**Rationale**: the provider accepts these three kinds on the quotes endpoint;
shape-based routing keeps validation deterministic without a lookup upcall
(fail before fetch, FR-005). The OCC tail grammar mirrors the registered
OCC handling already used by 007's underlying derivation (reuse of
established knowledge).

**Alternatives considered**:
- Accept anything and let the provider reject — error attribution would be
  coarse and violates fail-before-fetch; rejected.
- Symbol-kind lookup call before quoting — extra provider round trip per
  invocation; rejected (KISS/C-05).

## D6 — Curated field mapping and rounding

**Decision** (provider field → curated field):

| Provider (`/marketdata/v1/quotes`) | Curated | Rounding / rule |
|---|---|---|
| `symbol` | `symbol` | as requested (normalized) |
| `description` | `description` | truncated to 80 chars (token bound) |
| `lastPrice` | `last` | 2 decimals (4 for option symbols) |
| `bidPrice` | `bid` | same rounding rule as `last` |
| `askPrice` | `ask` | same rounding rule as `last` |
| `totalVolume` | `volume` | integer, as reported |
| `netPriceChange` | `net_change` | same rounding rule as `last` |
| computed: `net_change / closePrice × 100` | `net_change_pct` | 2 decimals; `null` when `closePrice` is missing or 0 (FR-012) |
| `quoteType` + market-hours check (D4) | `data_state` | enum |
| `tradeTime` | `trade_time` | ISO 8601 UTC |

Missing provider fields → explicit `null` (FR-012); the curated schema is
declared in the response (`quote_fields`, pattern of 008's
`contract_fields`). Option-symbol rounding uses 4 decimals because option
quotes carry sub-cent increments.

**Alternatives considered**:
- Include `openPrice`/`daysHighPrice`/`daysLowPrice` in the curated set —
  each adds tokens to every invocation for fields rarely needed for price
  checks; remain reachable via extended mode (C-09); rejected.

## D7 — Result envelope, logging, and registration

**Decision**: follow the established module pattern exactly:

- `get_quotes(client, symbols, extended=False)` orchestrates: validate →
  market-hours call → `quotes()` call via `tokens.retry_call` →
  `provider.response_json` unwrap → curate → envelope.
- Envelope: success = `{"outcome": "ok", "detail": "quotes_retrieved",
  ...}`; any failure = structured error outcome with `errors` keyed by
  symbol (per-symbol reason), consistent with FR-006/FR-008 and the
  clarification on keyed attribution.
- `get_quotes_tool(...)` converts `ValueError`/`TypeError`/data errors into
  MCP `ToolError` (pattern of `get_option_chain_tool`).
- Registration in `server.py` via `mcp.add_tool` wrapper closure (pattern of
  003/006/008).
- Audit events: `quotes_query_start` / `quotes_query_failure` with
  outcome classification `validation` / `error` / `reauth` /
  `provider_unreachable` (pattern of `options_chain_query_*`), no
  credentials in any output (FR-010).

**Rationale**: one envelope, one error taxonomy, one logging pattern
(C-02/C-09); the graph confirmed all four prior tools share this shape.

**Alternatives considered**:
- A second, quote-specific envelope or a per-symbol partial-success outcome —
  violates FR-006/FR-008; rejected.

## Budget declarations (Principle V)

- **Token budget**: ≤ 250 tokens curated response for a single symbol;
  ≤ 2,500 tokens for a 10-symbol batch (≤ ~5,000 worst case at the 20-symbol
  limit). Enforced by `tests/performance/test_quotes_budgets.py` fixtures.
- **Latency budget**: ≤ 5 s p95 per invocation at 20 symbols (two provider
  calls: one market-hours + one quotes). Enforced by the same module.
- Growth beyond these budgets requires recorded justification per
  constitution Principle V (the 008 precedent: measured payload may force a
  re-declared budget with justification in `plan.md`).

## Open items for the tasks phase

- Record the exact live provider payload shape (fixture) in the first RED
  test of the mapping module (TDD: fixture first, then implementation).
- If the recorded payload exposes an authoritative market-open indicator,
  simplify D4's ladder and note it in the tasks (C-04).