# Research: List Open Positions

**Feature**: `003-list-open-positions` | **Date**: 2026-10-20

All decisions were verified against the versions installed in the repo
(`uv run python -c ...` against `schwabdev==4.0.0` and the SDK
`mcp>=1.0.0`), not against generic documentation.

## D1 — Surface: first real MCP tool via `MCPServer.add_tool`

**Decision**: Register the tool using the `mcp` SDK API already used in
`server.py`: `mcp.add_tool(fn, name="get_open_positions", description=...)`
(or the equivalent decorator `@mcp.tool`). The function is **sync** and the
SDK invokes it correctly (verified: `add_tool` accepts synchronous
functions; `structured_output` auto-detects from the return type annotation —
annotate with the pydantic result model to guarantee structured output).

**Rationale**: The spec (Q1) decided on a real MCP tool. The server already
instantiates `MCPServer("schwab-mcp")`; registering a tool is the minimal
extension and establishes the pattern for future tools (KISS, Reuse). There
is no second CLI path (Q1 discarded "both").

**Alternatives considered**:
- One-shot CLI command: rejected — contradicts the user's decision (Q1: A).
- Implementing the `call_tool` handler by hand on top of `Server` (lowlevel):
  rejected — it would duplicate what the SDK already solves (DRY).

## D2 — Data source: `account_details_all(fields="positions")`

**Decision**: A single upstream call per query:
`client.account_details_all(fields="positions")` (schwabdev 4.0.0,
verified: `GET /trader/v1/accounts?fields=positions`). It returns all
linked accounts with their positions in a single response.

**Rationale**: Satisfies FR-001 + FR-004 (all accounts, all
positions, one query) with the minimum number of provider calls (latency
budget SC-002 and rate-limit courtesy). `linked_accounts()` is already used
in 001/002 to validate access; no need to call it separately here.

**Alternatives considered**:
- `account_details(account_hash)` per account (N calls): rejected —
  N× latency and N× quota for the same data.
- A separate quotes endpoint to refresh prices: rejected —
  it duplicates calls; the positions payload already carries `marketValue`
  and the provider's quote data (see D4).

## D3 — Curated metadata set (FR-003 / FR-003a)

**Decision** — provider payload fields → curated set per position:

| Curated field | Source in provider payload |
|--------------|---------------------------|
| `symbol` | `instrument.symbol` |
| `instrument_type` | `instrument.assetType` (provider enum: `EQUITY`, `OPTION`, `MUTUAL_FUND`, `FIXED_INCOME`, `CASH_EQUIVALENT`) |
| `description` | `instrument.description` |
| `quantity` (signed) | `longQuantity - shortQuantity` |
| `average_price` | `averagePrice` |
| `market_value` | `marketValue` |
| `unrealized_pl` | derived: `marketValue - (averagePrice × |quantity|) × sign(quantity)`; verified against `currentDayProfitLoss` when the provider provides it |
| `price_timestamp` | see D4 |
| `account_hash` | hash of the account holding the position (opaque, safe to display; never the raw account number) |
| Options only: `underlying_symbol`, `put_call`, `strike_price`, `expiration_date` | `instrument.underlyingSymbol`, `instrument.putCall`, `instrument.strikePrice`, `instrument.expiration*` |

**Extended on demand (`extended=true`, FR-003a)**: the remaining fields the
provider carries for that position (e.g. `cusip`,
`settledLongQuantity`, `settledShortQuantity`, `dayQuanity` —sic, provider
field—, `currentDayProfitLoss`, `maintenanceRequirement`, and the entire
`instrument` object) are passed through without interpretation, with
`price_timestamp` included all the same.

**Rationale**: covers everything the spec defines as "understand and decide"
(US2) while keeping the payload compact (Constitution V). The option fields
are mandatory for the use case declared by the owner
(strangles / condors / rolls).

**Alternatives considered**:
- Full raw passthrough by default: rejected (Q2 of the specify).
- Filtering the extended set too: rejected — the value of `extended` is
  precisely the provider's full fidelity.

## D4 — `price_timestamp` when the provider does not carry a per-position quote time

**Decision**: The API's positions payload does not guarantee a per-position
quote timestamp field. The tool sets `price_timestamp` to the **moment the
provider response was retrieved** (UTC ISO-8601)
and adds a result-level `market_state` (`open` | `closed`) per
account based on each instrument's market hours… **revision
(KISS)**: deriving market open/closed per instrument adds logic
and calendar assumptions outside the system's control. Final decision:
`price_timestamp` = UTC retrieval time; the reported value is the one
the provider computed when generating that payload (live during market
hours, last close outside them — provider behavior, not ours). This is
documented explicitly in the contract so the agent does not attribute
freshness that does not exist.

**Rationale**: FR-012 requires the timestamp of the price used; the price used
IS the one in the provider payload, and its retrieval timestamp is the
observable truth without reinventing market calendars (KISS, and it avoids
a source of silent bugs).

**Alternatives considered**:
- Computing open/closed with calendars (a library like `exchange_calendars`):
  rejected — new dependency + unjustifiable holiday/hours assumptions
  for v1 (YAGNI).

## D5 — Zero-quantity omission (FR-015)

**Decision**: A position with `longQuantity == shortQuantity == 0` (or
`longQuantity - shortQuantity == 0` with both > 0, e.g. closed but not
yet settled) is **omitted** from the result. The contract documents this.

**Rationale**: FR-015 resolved the edge case: only effective holdings;
the agent never sees ghost positions.

## D6 — No internal retries (FR-007)

**Decision**: Network/provider failure → `ConnectivityError` (existing
taxonomy, exit 7) maps to a `transient_failure` result **on the first
attempt**, with no retry. `retryable: true` only in that class.

**Rationale**: Decision Q4 of the clarify. It reuses 002's classification
pattern (same `retryable`/outcome classes vocabulary) without duplicating its
retry mechanics, which do not apply to a cheap read.

## D7 — Failure classification: reuse of the `errors.py` taxonomy

**Decision**: Direct mapping of the existing exceptions to tool outcomes:

| Exception (errors.py) | Tool outcome |
|---|---|
| `ConnectivityError` | `transient_failure` (`retryable: true`) |
| `ReauthorizationRequiredError`, `TokenStoreCorruptedError` | `reauth_required` |
| One account fails and others succeed (FR-010) | `partial_failure` with `accounts_failed` + per-account `detail` |
| `MissingConfigError`/`InvalidConfigError` | should not occur in serve (fail-fast at startup); if they occur, they are reported as a generic `error` with detail |

**Rationale**: Full DRY with the `docs/tools.md` playbook; the agent uses
exactly the same decision rules it already knows.

**Alternatives considered**: a new taxonomy for the tool: rejected (DRY).

## D8 — Audit events (FR-014)

**Decision**: Reuse `log.auth_event(event, outcome, detail=)` with new
vocabulary, analogous to renew:
`positions_query_start` → (`positions_query_success` |
`positions_query_failure`). One `start` followed by exactly one
terminal per invocation; output through the auxiliary channel (stderr), without
secrets; the existing redaction filter covers these lines.

**Rationale**: Q3 decided to always audit; reuse of the existing mechanism
(DRY) with its own event names to avoid colliding with the auth vocabulary
(separate contract in `contracts/events.md`).

## D9 — Token budget / payload size (SC-003)

**Decision**: Budget declared for the implementation:
- Default (50 curated positions): **≤ 8 KB** of serialized JSON
  (~2 000 tokens), measured by test.
- `extended=true`: separate budget declared in the contract
  (≤ 16 KB for 50 positions); any growth requires
  recorded justification (Constitution V).
- Compact format: short snake_case field names, no informative
  null fields (omission > null when the field does not apply).

**Rationale**: SC-003 requires a measurable budget; the per-position estimate
(~150 bytes curated) comes from the field count of D3.

## D10 — Concurrency with automatic renewal

**Decision**: The tool does not coordinate renewal (schwabdev handles it
internally with its SQLite `BEGIN EXCLUSIVE` — proven in 002). If a
renewal is in flight, the schwabdev call waits or reflects the state; the
tool never initiates authorization flows (the guard hook of
`serve` guarantees this).

**Rationale**: Reuse of 002's proven mechanism; no new locks (KISS).

---

## Post-implementation correction (2026-10-24)

The payload shape assumed in this research
(`{"accountDetails": [{"accountNumber", "positions"}]}` with responses already
parsed) **does not match the real SDK/endpoint contract**:

- `Client.account_details_all()` returns a `requests.Response` (the body
  must be unwrapped with `.json()` — see `schwab_mcp.provider.response_json`,
  introduced by the fix of feature 006).
- The actual payload is a **top-level list** of
  `{"aggregatedBalance", "securitiesAccount": {...}}`.
- The real `securitiesAccount` does not carry the account hash: the opaque
  identifier is the `hashValue` from `linked_accounts()`, joined by
  `accountNumber`.
- Real OPTION instruments do not carry `strikePrice` or
  `expirationDate`: they are derived from the OCC symbol.

Detected and fixed in the bug `positions-response-unwrap`
(`.specify/bugs/positions-response-unwrap/`).