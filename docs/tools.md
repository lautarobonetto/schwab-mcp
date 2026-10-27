# Interface for AI agents

Complete reference of the surface consumable by an AI agent
(for example, OpenClaw). It documents **every command and every field** of
the output, with exact semantics so the agent can decide without
human intervention.

**Document version**: 0.6.2 (see [CHANGELOG](./CHANGELOG.md)).

## How this MCP is consumed

The project exposes **two surfaces**, with different roles:

| Surface | How it is invoked | State in this version |
|------------|----------------|------------------------|
| MCP server `serve` | MCP client connects over **stdio** | Active transport; **3 tools registered** (`get_open_positions`, `get_transaction_history` and `get_option_chain`) |
| One-shot CLI | The agent runs `schwab-mcp <command>` through the shell | **The agent's main surface** today |

The tools ``get_open_positions``, ``get_transaction_history`` and
``get_option_chain`` (first, second and third MCP tools registered)
are available through the ``serve`` server, complementing the
one-shot commands described below.

Cross-cutting guarantees of **all** agent-facing commands:

- **Non-interactive**: never open a browser, never read stdin, never
  listen on sockets. Safe for unattended execution.
- **Parseable output**: exactly **one JSON line** on stdout;
  nothing else on stdout. Auxiliary messages and events go to stderr.
- **No secrets**: no field contains tokens, app keys/secrets or
  authorization URLs. A redaction filter is active as an additional
  defense (stderr included).
- **Bounded time**: no command hangs; budgets per command.
- **Concurrency-safe**: lock-based coordination; they corrupt nothing.

---

## `get_open_positions` (first MCP tool)

First MCP tool registered by the ``serve`` server (feature
``003-list-open-positions``). Retrieves all effective holdings of
all linked accounts in a single upstream call, with self-classifying
structured results.

### Invocation

```json
{"name": "get_open_positions", "arguments": {}}
```

### Arguments (input schema)

| Field | Type | Default | Semantics |
|-------|------|---------|-----------|
| ``extended`` | bool | ``false`` | ``false`` (default): curated set only (compact). ``true``: each position adds the ``extended`` object with the full provider passthrough. |

No other parameters in v1: the query always covers **all** the
linked accounts.

### Output schema

Exactly one ``PositionsResult`` object per invocation. Fields:

| Field | Type | Values |
|-------|------|---------|
| ``outcome`` | closed enum | ``ok`` · ``partial_failure`` · ``transient_failure`` · ``reauth_required`` |
| ``positions`` | array | ``PositionEntry`` entries; ``[]`` valid only with ``outcome: "ok"`` |
| ``accounts_failed`` | array \| absent | Only ``partial_failure``: ``[{account_hash, detail}]``, ``detail ∈ {provider_error, transient}`` |
| ``retryable`` | bool | ``true`` only when ``outcome == "transient_failure"`` |
| ``detail`` | closed enum | ``data_received`` · ``no_positions`` · ``account_failed`` · ``provider_unreachable`` · ``reauth_needed`` · ``store_absent`` · ``store_corrupted`` |
| ``retrieved_at`` | string ISO-8601 UTC | Time the provider payload was retrieved |

The ``account_hash`` is the provider's opaque ``hashValue`` (from
``linked_accounts()``, cross-referenced by ``accountNumber``) — the same
identifier exposed by ``get_transaction_history``, consistent across
the whole MCP surface.

The full ``PositionEntry`` schema and the cross-validation
rules are in the
[data model](../specs/003-list-open-positions/data-model.md).

### Error mapping

| Condition | ``outcome`` | ``retryable`` | Agent action |
|-----------|-------------|---------------|-------------------|
| Network/provider unavailable | ``transient_failure`` | ``true`` | Retry with backoff |
| Refresh rejected / corrupted store | ``reauth_required`` | ``false`` | Notify the owner (``schwab-mcp auth``), monitor with ``auth-status`` |
| Some accounts failed, others did not | ``partial_failure`` | ``false`` | Assess whether to retry; partial data in ``positions`` |
| All accounts responded | ``ok`` | ``false`` | Continue normally |

### Guarantees

- **Read-only**: places no orders and moves no money.
- **No secrets**: no token/credential in the output.
- **Budget**: ≤ 5 s latency; ≤ 8 KB default (≈ 2,000 tokens),
  ≤ 16 KB extended.
- **No internal retries** on transient failure (FR-007): the agent
  decides.

### Reference

- Full contract:
  [`specs/003-list-open-positions/contracts/mcp-tools.md`](../specs/003-list-open-positions/contracts/mcp-tools.md)
- Data model:
  [`specs/003-list-open-positions/data-model.md`](../specs/003-list-open-positions/data-model.md)
- Audit events:
  [`specs/003-list-open-positions/contracts/events.md`](../specs/003-list-open-positions/contracts/events.md)

---

## `get_transaction_history` (second MCP tool)

Second MCP tool registered by the ``serve`` server (feature
``006-transaction-history``). Retrieves the transaction history of
all linked accounts in a date range, with structured results and
deterministic pagination.

### Invocation

```json
{
  "name": "get_transaction_history",
  "arguments": {
    "start_date": "2026-09-01",
    "end_date": "2026-09-30"
  }
}
```

With instrument filter and pagination:

```json
{
  "name": "get_transaction_history",
  "arguments": {
    "start_date": "2026-01-01",
    "end_date": "2026-09-30",
    "symbol": "AAPL",
    "offset": 50
  }
}
```

### Arguments (input schema)

| Field | Type | Default | Semantics |
|-------|------|---------|-----------|
| `start_date` | string | required | Range start date, `YYYY-MM-DD`. **Inclusive** bound, interpreted in America/New_York. |
| `end_date` | string | required | Range end date, `YYYY-MM-DD`. **Inclusive** bound; cannot be in the future. |
| `symbol` | string \| absent | no filter | If present: only movements that **involve** that instrument (data-model §2): the registered symbol matches exactly (M1), or it is an option whose underlying (OCC root) matches (M2), or it is a full OCC symbol (M3). **Case-insensitive** comparison. Dual validation: if the directory does not resolve the filter, the query proceeds anyway and `instrument_not_found` is reported only if no movement matches (FR-003). **No longer sent upstream** (research R1) — the filter is applied locally. |
| `extended` | bool | `false` | `false` (default): compact curated set. `true`: each movement adds `extended` with the provider passthrough (original type, full description, fees, netAmount, transferItems…). |
| `offset` | int | `0` | Pagination continuation: repeat the same query with the received `next_offset`. |

Maximum window: **1 year** (366 calendar days) between `start_date` and
`end_date`. Larger ranges → validation error stating the maximum
and suggesting splitting the query.

### Output schema

Exactly one `TransactionsResult` object per invocation:

| Field | Type | Presence | Semantics |
|-------|------|-----------|-----------|
| `outcome` | closed enum | always | `ok` · `partial_failure` · `transient_failure` · `reauth_required` |
| `detail` | closed enum | always | `history_retrieved` · `no_movements` · `no_movements_for_instrument` · `account_failed` · `provider_unreachable` · `reauth_needed` |
| `retryable` | bool | always | `true` only when `outcome == "transient_failure"` |
| `retrieved_at` | string ISO-8601 UTC | always | Time the provider payload was retrieved |
| `total_count` | int | `outcome=ok` | Total movements in the full range (all pages) |
| `movements` | array | `outcome=ok` | List of `MovementEntry` entries (see data-model); `[]` valid only with `no_movements`/`no_movements_for_instrument` |
| `returned` | int | `outcome=ok` | Number of movements on this page (≤ 50) |
| `has_more` | bool | `outcome=ok` | `true` if more movements remain to be delivered |
| `next_offset` | int \| absent | only `has_more=true` | Offset to request the next page |
| `accounts_failed` | array \| absent | only `partial_failure` | `[{"account_hash": str, "detail": "provider_error"|"transient"}]` |
| `offset_echo` | int | `outcome=ok` | Effective offset applied to this page |

Example response (`ok`, first page):

```json
{
  "outcome": "ok",
  "detail": "history_retrieved",
  "retryable": false,
  "retrieved_at": "2026-10-23T14:00:00+00:00",
  "total_count": 137,
  "returned": 50,
  "has_more": true,
  "next_offset": 50,
  "offset_echo": 0,
  "movements": [
    {
      "account_hash": "AB12CD34EF56GH78",
      "occurred_at": "2026-09-03T15:45:00-04:00",
      "category": "trade",
      "description": "You SOLD 10 shares of AAPL",
      "amount": -2318.9,
      "currency": "USD",
      "symbol": "AAPL",
      "instrument_type": "EQUITY"
    },
    {
      "account_hash": "AB12CD34EF56GH78",
      "occurred_at": "2026-09-03T15:46:00-04:00",
      "category": "trade",
      "description": "Option trade",
      "amount": -50.0,
      "currency": "USD",
      "symbol": "NOK   261218P00011000",
      "instrument_type": "OPTION",
      "underlying_symbol": "NOK"
    }
  ]
}
```

Each `MovementEntry` contains:

| Field | Type | Presence | Semantics |
|-------|------|-----------|-----------|
| `account_hash` | string | always | Opaque account identifier (never an account number) |
| `occurred_at` | string ISO-8601 | always | Movement date/time (provider timezone) |
| `category` | closed enum | always | Normalized category: `trade` · `transfer` · `dividend_or_interest` · `adjustment` · `other` |
| `description` | string | always | Readable description, **truncated to 80 characters** in default mode (full text in `extended`) |
| `amount` | float | always | Main monetary effect (provider sign, not reinterpreted) |
| `currency` | string | always | Movement currency (default `"USD"`) |
| `symbol` | string \| absent | only if there is an instrument | Symbol of the referenced instrument. In trades with cash/commission legs (`transferItems`), the **first non-currency instrument** is curated (`CURRENCY_USD` legs come first in the real payload); `CURRENCY_USD` only if the movement is genuinely cash |
| `instrument_type` | string \| absent | only if there is an instrument | Asset type (`EQUITY`, `ETF`, `OPTION`, …) |
| `underlying_symbol` | string \| absent | only option movements with an identifiable OCC | Underlying of the option: unpadded OCC symbol root (e.g. `"NOK"` from `"NOK   261218P00011000"`). Absent for non-options. |
| `extended` | object \| absent | only `extended=true` | Provider passthrough: original type, full description, fees, netAmount, transferItems… |

### Outcome and `detail` semantics

| Outcome | `detail` | Meaning for the agent |
|---------|----------|---------------------------|
| `ok` | `history_retrieved` | History retrieved; paginate with `next_offset` if `has_more` |
| `ok` | `no_movements` | Valid range, no movements in any account |
| `ok` | `no_movements_for_instrument` | Valid symbol, no movements of that instrument in the range |
| `partial_failure` | `account_failed` | Some accounts failed (see `accounts_failed`); partial data in `movements` |
| `transient_failure` | `provider_unreachable` | Transient failure on the first attempt; retry with backoff |
| `reauth_required` | `reauth_needed` | Same playbook: do not retry, notify the owner |

### Validation errors (standard MCP tool error, no upcalls)

| Condition | Expected message |
|-----------|------------------|
| `start_date`/`end_date` absent or malformed | States the expected `YYYY-MM-DD` format |
| `end_date < start_date` | Names both dates |
| Range > 366 days | States the 1-year maximum and suggests splitting into consecutive queries |
| Future `end_date` | States that the end date cannot be in the future |
| `symbol` present, directory does not resolve + 0 movements match | `instrument_not_found`, names the symbol (dual validation) |
| `symbol` present, directory does not resolve + ≥1 movement matches | `ok` with the matching movements (CURRENCY_USD, unregistered OCC) |
| `offset < 0` | States the minimum value |

Per-account errors (`accounts_failed[].detail`): `provider_error` ·
`transient` (same vocabulary as `get_open_positions`).

### Pagination

- **Limit**: at most **50** movements per page.
- **Order**: `occurred_at` ascending; tie-break by `account_hash` and `activityId`.
- **Continuation**: when `has_more=true`, repeat the same query with `offset=<next_offset>`.
- **Invariant**: walking with `next_offset` delivers the complete union without duplicates or omissions, over the snapshot of the history at query time.
- **Stateless caveat**: the tool is stateless; if new movements arrive between pages, the offset may shift. Paginate promptly.

### Guarantees

- **Read-only**: places no orders and moves no money.
- **No secrets**: no token/credential in the output; opaque `account_hash`.
- **Budget**: ≤ 5 s p95 latency; ≤ 16 KB default page (50 movements, **including** `underlying_symbol` — verified worst case: 50 options); ≤ 64 KB extended.
- **No silent truncation**: the upstream cap of 3000 is handled with bisection and deduplication.
- **No internal retries** on transient failure (FR-010): the agent decides.
- **Deterministic**: reproducible output for the same query with no underlying changes.

### Operational caveat

The provider may return `200 OK + []` for `/transactions` when
the registered app or the account lacks transaction read permission
(e.g. an account without thinkorswim enabled). From the
response it is indistinguishable from a genuine empty: the tool reports
`ok / no_movements`. Suggested diagnosis: if the account shows
activity on schwab.com and several wide ranges return
`no_movements` persistently, the likely cause is app/account
permission — not data.

As of version 0.5.0, filter validation is **dual**
(FR-003): if the instrument directory does not recognize the symbol
(e.g. `CURRENCY_USD`, a full OCC symbol, an underlying without
an entry in the index), the tool proceeds with the sweep anyway and only
reports `instrument_not_found` if no movement matches the filter
in any of the three forms (M1 registered symbol, M2 option root,
M3 full OCC). This replaces the previous behavior where
internal identifiers like `CURRENCY_USD` produced
`instrument_not_found` despite having movements.

### Reference

- Full contract (base 006):
  [`specs/006-transaction-history/contracts/mcp-tools.md`](../specs/006-transaction-history/contracts/mcp-tools.md)
- Filter/underlying_symbol extensions (007):
  [`specs/007-underlying-symbol-filter/contracts/mcp-tools.md`](../specs/007-underlying-symbol-filter/contracts/mcp-tools.md)
- Data model:
  [`specs/006-transaction-history/data-model.md`](../specs/006-transaction-history/data-model.md) ·
  [`specs/007-underlying-symbol-filter/data-model.md`](../specs/007-underlying-symbol-filter/data-model.md)
- Audit events:
  [`specs/006-transaction-history/contracts/events.md`](../specs/006-transaction-history/contracts/events.md)

---

## `get_option_chain` (third MCP tool)

Third MCP tool registered by the ``serve`` server (feature
``008-extract-option-chain``). Retrieves the option chain of an
underlying in **a single invocation**, with deterministic
strike selection (symmetric around-the-money window or delta window)
and a DTE filter. Read-only: places no orders and moves no money.

### Invocation

```json
{"name": "get_option_chain", "arguments": {"symbol": "AAPL"}}
```

### Arguments (input schema)

| Field | Type | Default | Semantics |
|-------|------|---------|-----------|
| `symbol` | string | — (required) | Underlying instrument. Non-empty, no internal spaces; passed as-is to the provider. |
| `max_strikes` | int | `50` | ≥ 1. Strikes per side of the money (ATM included) per expiration: up to `2 × max_strikes` rows. With `delta_target` it does not reduce that window. |
| `option_type` | enum `both` \| `calls` \| `puts` | `both` | Which legs the response includes. |
| `delta_target` | number \| null | `null` | If present: `0 < \|delta_target\| < 1`. Selects, per expiration and per included type, up to 5 strikes around the contract with \|delta\| closest to the target. |
| `dte_max` | int \| null | `null` | If present: ≥ 1 (calendar days). **`null` does not mean "no ceiling"**: it applies the current 60-day ceiling (FR-005). |
| `extended` | bool | `false` | `false` (default): compact curated set. `true`: adds `provider` with the raw provider payload (003/006 pattern). |

### Output schema

Exactly one result object per invocation. Result states
(`outcome` is the explicit marker):

| `outcome` | `detail` | Meaning for the agent |
|-----------|----------|---------------------------|
| `ok` | `chain_retrieved` | Full chain in `expirations` |
| `no_options_listed` | `no_options_listed` | The instrument has no listed options (structured result, **not** an error) |
| `no_expirations_in_range` | `no_expirations_in_range: dte_max_effective=N excludes all expirations` | There are expirations, but the DTE ceiling excludes them all; `expirations: []` |

Metadata (`ok`):

| Field | Type | Semantics |
|-------|------|-----------|
| `symbol` | string | Echo of the queried instrument |
| `generated_at` | string ISO-8601 UTC | Time of the query |
| `data_state` | closed enum | `realtime` · `delayed` (freshness reported by the source) |
| `underlying_price` | float \| null | Current price of the underlying |
| `filters` | object | Echo of the effective query: `{max_strikes, option_type, delta_target, dte_max_requested, dte_max_effective}`. `dte_max_effective` is 60 or the requested value — the agent can always verify the applied ceiling. |
| `contract_fields` | array of strings | Column order of each leg array (23 columns, see below) |
| `expirations` | array | Expirations ordered by ascending `expiration_date` |

Each expiration: `{expiration_date: "YYYY-MM-DD", dte: int,
atm_strike: float, strikes: [...]}` — `dte` in calendar days;
`atm_strike` is the strike closest to `underlying_price` (ties: the
lowest); `strikes` ordered by ascending strike.

#### Columns of each leg (`contract_fields`, fixed order)

```json
["bid", "ask", "last", "mark", "mark_change", "mark_pct_change",
 "high", "low", "open", "close", "volume", "open_interest",
 "iv", "delta", "gamma", "theta", "vega", "rho",
 "theoretical_value", "time_value", "multiplier", "trade_time",
 "deliverable_note"]
```

**Columnar** shape of each strike row
(`{strike: float, call: [...], put: [...]}`):

- Each leg is a **positional array** in the order of `contract_fields`
  (declared in the response itself). The array may carry fewer
  elements when the trailing fields are not reported.
- Field missing at the source → explicit `null` in its column
  (FR-007); values are never invented.
- `call`/`put` **absent** (not `null`) when the type is excluded by
  `option_type` or the strike fell outside that type's delta window.
  The row exists if at least one included type selected it.
- The 5 Greeks (`delta`, `gamma`, `theta`, `vega`, `rho`) are
  present by contract or with explicit `null` (FR-006/FR-007).
- Deterministic rounding: prices/values to 2 decimals; Greeks and IV
  to 4 decimals; `volume`/`open_interest`/`multiplier` unrounded
  (integers: integral floats from the source are normalized to `int`);
  `trade_time` in ISO-8601 UTC — `null` when the contract never
  traded (the source sends epoch `0`; FR-007: never invent data).

#### Strike selection (normative summary)

- **Without `delta_target`**: per expiration, up to `max_strikes`
  closest strikes below and above `atm_strike` (ATM included if
  present) → ≤ `2 × max_strikes` rows per expiration.
- **With `delta_target`**: per expiration and **per included type**,
  the contract with \|delta\| closest to the target + 2 contiguous per
  side → up to 5 strikes per type. `max_strikes` does not intervene.
- **DTE**: only expirations with `dte ≤ dte_max_effective`.

#### `extended=true`

Adds `provider` with the raw source payload (uncurated). Structural
fields excluded from the curated format (`skipBars`,
`isPitRanged`, `executable`, `settlementType`, `deliverables`) are
accessible through this path.

### Expected payload size (Budget, Principle V)

**This tool has the largest payload on the MCP surface** — budget it
before invoking:

| Filters | Expected size | Normative budget |
|---------|-----------------|-----------------------|
| Default (wide chain: ~12 expirations × ≤ 100 strike rows) | ~95–106k tokens | **≤ 110,000 tokens** |
| With `delta_target` (typical underlying: 10–12 expirations) | ~4.5–5k tokens | **≤ 8,000 tokens** |
| With `delta_target` (live wide chain: 16 expirations, SPY/QQQ) | ~7.2–7.3k tokens | **≤ 8,000 tokens** |

> **Recorded growth justification** (Principle V): the
> budgets were adjusted on 2026-10-24 by user decision
> because an honest measurement of both-legs rows with the required 23
> columns yields ~80–88 tokens per row, and the content of the
> response is fixed by FR-002/FR-006 (it does not admit trimming
> without violating the spec). **Later re-baseline (same date,
> convergence T023)**: the `delta_target` budget moved from <6,000 to
> ≤8,000 because the 5-strike window per type applies **per
> expiration** (FR-004) and volume scales with the expirations the
> DTE ceiling lets through — live chains of 16 expirations
> (SPY/QQQ) measure ~7.2–7.3k tokens.
> The full growth justification is recorded in
> [`specs/008-extract-option-chain/plan.md`](../specs/008-extract-option-chain/plan.md)
> (Complexity Tracking).

**Tip for the agent**: if you only need a slice of the chain,
prefer `delta_target`, a small `max_strikes` or a low `dte_max` — they reduce the
payload without paginating (the tool does not paginate). The FR-012
limit guarantees the response never exceeds `expirations × types × strikes`.

### Validation errors (standard MCP tool error, no upcalls)

All occur **before any upcall** (FR-008) with an actionable
message naming the parameter and the constraint:

| Condition | Expected message |
|-----------|------------------|
| `symbol` empty or whitespace only | Names `symbol` and the non-empty constraint |
| `symbol` with internal spaces | Names `symbol` and the constraint |
| `max_strikes ≤ 0` | Names `max_strikes` and `>= 1` |
| `option_type` outside the enum | Names `option_type` and the values `both, calls, puts` |
| `\|delta_target\| ∉ (0,1)` | Names `delta_target` and `0 < \|delta_target\| < 1` |
| `dte_max ≤ 0` | Names `dte_max` and `>= 1` |

### Common invocation errors (real pitfalls — read before calling)

Failures observed in practice with agents; each produces an avoidable
validation error:

1. **`option_type` is a PLURAL enum**: the only valid values are
   `both`, `calls`, `puts`. `option_type: "put"` (singular) is rejected
   with `option_type must be one of: both, calls, puts`. Do not translate
   "I want the puts" into `"put"` — the enum is already defined.
2. **`dte_max` is a ceiling, NOT a minimum.** There is no `dte_min`. To
   look for expirations with **DTE ≥ N**: invoke with the maximum
   allowed `dte_max` and filter client-side using `expirations[].dte`. Also,
   since the hard ceiling is 60 days, the tool can **never** return
   expirations with `dte > 60` — if your analysis requires further out,
   the tool falls short and that must be stated explicitly.
3. **`dte_max: null` does not mean "no ceiling"**: it applies the current
   60-day ceiling (verifiable in `filters.dte_max_effective`).
4. **With `delta_target` the window is narrow**: up to **5 strikes per
   type and per expiration** around the delta anchor; `max_strikes`
   does not intervene. Sweeping the whole chain (e.g. to build spreads
   by looking for strike pairs) **cannot be done in a single call**:
   make several calls with different `delta_target` values (e.g. 0.2,
   0.35, 0.5) and merge by strike, or call without `delta_target` with
   a large `max_strikes` and accept the huge payload.
5. **`delta_target` is about absolute \|delta\|**: for puts the delta is
   negative, but `delta_target: 0.2` selects the put with
   |delta| ≈ 0.2 (delta ≈ −0.2). Do not pass `delta_target: -0.2`
   expecting a different result — it is equivalent.
6. **`extended: true` multiplies the payload**: it includes the full raw
   provider passthrough. Use it only if you really need
   a field that is not in the curated format.

### Recipes for common strategies

**Legs of a short strangle (OTM put and call at |delta| ~0.2), DTE ≥ 45:**

```json
{"name": "get_option_chain", "arguments": {
  "symbol": "SPY", "option_type": "both", "delta_target": 0.2, "max_strikes": 3, "extended": true}}
```

Client-side post-processing: discard expirations with `dte < 45`; the
put with delta ≈ −0.2 is the lower short leg, the call with delta ≈ +0.2
the upper short leg.

**Put sweep to build fixed-width credit spreads** (e.g. $10):

The width is built with strike pairs; the `delta_target` window is
too narrow to cover the zone between the short and the long. Make
**multiple calls with staggered `delta_target`** (0.2, 0.35, 0.5)
with `option_type: "puts"` and merge the strikes, deduplicating by
strike; then compute the credit of each pair `(S, S − width)`
client-side.

```json
{"name": "get_option_chain", "arguments": {"symbol": "AMD", "option_type": "puts", "delta_target": 0.35}}
```

**Short slice bounded by price and time:**

```json
{"name": "get_option_chain", "arguments": {"symbol": "AAPL", "max_strikes": 10, "dte_max": 7}}
```

### Source errors (shared standard mapping)

| Condition | Behavior | Agent action |
|-----------|----------------|-------------------|
| Entire expiration without data (FR-013, `ChainDataError`) | Structured **error** naming the date and the type; **never** a partial chain | Retry later or reduce the scope; do not trust partial data |
| 401/403 | Reauthorization required | `renew` playbook (`reauth_required`) |
| 5xx/408/429 | Transient failure | Retry with backoff |
| Other 4xx | The provider reviewed and rejected the request | Fix the parameters; do not retry identically |

The provider error taxonomy is **shared** with
`get_open_positions` and `get_transaction_history`
(`provider.response_json`): see their error sections for details
on handling `reauth_required` and transient failures. FR-013: an
asymmetry at the **date** level between the included maps (an
expiration with data in one type and no data in the other) is a partial
chain → error; asymmetry at the **strike** level is normal: that
strike keeps only the existing leg and the row omits the other key.

### Examples

**Default chain** (all expirations ≤ 60 DTE, both types):

```json
{"name": "get_option_chain", "arguments": {"symbol": "AAPL"}}
```

Response (truncated; the real payload is huge):

```json
{
  "outcome": "ok",
  "detail": "chain_retrieved",
  "symbol": "AAPL",
  "generated_at": "2026-10-24T15:04:05+00:00",
  "data_state": "realtime",
  "underlying_price": 251.31,
  "filters": {"max_strikes": 50, "option_type": "both", "delta_target": null,
              "dte_max_requested": null, "dte_max_effective": 60},
  "contract_fields": ["bid", "ask", "...", "trade_time", "deliverable_note"],
  "expirations": [
    {"expiration_date": "2026-10-30", "dte": 6, "atm_strike": 251.0,
     "strikes": [
       {"strike": 250.0,
        "call": [25.10, 25.30, "...", 100, "2026-10-24T15:00:00+00:00", null],
        "put":  [6.05, 6.15, "...", 100, "2026-10-24T15:00:00+00:00", null]},
       "... (up to 100 strike rows, ordered by strike)"
     ]},
    "... (up to ~12 expirations, ordered by date)"
  ]
}
```

**Puts with a delta target** (per-type window, ≤ 5 strikes/expiration):

```json
{"name": "get_option_chain", "arguments": {"symbol": "AAPL", "option_type": "puts", "delta_target": 0.20}}
```

Only `put` keys per row (no `call`); per expiration, ≤ 5 strikes
around the contract with \|delta\| ≈ 0.20. Typical payload ~5k tokens.

**Explicit limits** (short slice):

```json
{"name": "get_option_chain", "arguments": {"symbol": "AAPL", "max_strikes": 10, "dte_max": 7}}
```

≤ 20 strike rows per expiration (2 × 10, centered on `atm_strike`),
only expirations with `dte ≤ 7` (`filters.dte_max_effective == 7`). If the
nearest expiration expires further out → structured
`no_expirations_in_range`, not a generic error.

**Edge: instrument without options**:

```json
{"name": "get_option_chain", "arguments": {"symbol": "ZZZZZZ"}}
```

```json
{"outcome": "no_options_listed", "detail": "no_options_listed",
 "symbol": "ZZZZZZ", "generated_at": "2026-10-24T15:04:05+00:00"}
```

### Guarantees

- **A single invocation returns the full chain** within the
  requested limits (FR-011): no pagination, no `cursor`/`offset`/
  `has_more` in the response.
- **Limits respected 100%** (`max_strikes`, `option_type`, DTE)
  (FR-012, SC-006); the response never exceeds
  `expirations × types × strikes`.
- **Complete Greeks**: the 5 Greeks and the rest of `contract_fields`
  present by contract or with explicit `null` (FR-006/FR-007).
- **Deterministic**: strike selection reproducible for the same
  input data.
- **Read-only**, **no state between invocations** and **no credentials**
  in the output (constitution's credential safety).
- **Budget**: ≤ 5 s p95 latency per invocation.

### Reference

- Full contract:
  [`specs/008-extract-option-chain/contracts/mcp-tools.md`](../specs/008-extract-option-chain/contracts/mcp-tools.md)
- Data model (`contract_fields` order, selection algorithms):
  [`specs/008-extract-option-chain/data-model.md`](../specs/008-extract-option-chain/data-model.md)
- Usage scenarios (S1–S4):
  [`specs/008-extract-option-chain/quickstart.md`](../specs/008-extract-option-chain/quickstart.md)

---

## `schwab-mcp renew`

Explicit renewal of the access credential using the stored refresh
credential. It is the agent's recovery lever when it detects
authentication problems, independent of the automatic path.

```sh
uv run schwab-mcp renew
```

- **Arguments**: none. **stdin**: never read.
- **Requires**: `SCHWAB_APP_KEY` and `SCHWAB_APP_SECRET` in the environment.
- **May call the Schwab API** (only if the token is within the
  preventive 61 s margin of expiring).
- **Budget**: ≤ 10 s worst case (3 attempts × 3 s HTTP
  timeout + 2 waits of 0.5 s between retries).

### Internal behavior (in order)

1. Loads and validates the configuration — fails **before** any network.
2. Inspects the token store: absent or corrupted →
   `reauth_required` result without attempting renewal.
3. Reads the remaining validity from the store; if it is above the
   margin → `not_needed` **without calling the API** and without
   invalidating anything.
4. Acquires the authorization lock (non-blocking): busy → exit 6.
5. Performs the refresh via schwabdev with up to **2 retries** on
   transient failures (network/provider). Existing valid tokens are
   **never discarded** due to a transient failure.
6. Classifies the result and emits **one JSON line** on stdout.
7. Emits audit events on stderr (`renew_start` → terminal).

### Output (stdout, one JSON line, ≤ 300 bytes)

```json
{"outcome": "renewed", "expires_in_seconds": 1800, "retryable": false, "detail": "access_renewed"}
```

| Field | Type | Values |
|-------|------|---------|
| `outcome` | closed enum | `renewed` · `not_needed` · `transient_failure` · `reauth_required` |
| `expires_in_seconds` | int ≥ 0 or `null` | New lifetime of the access token; `null` except in `renewed` |
| `retryable` | bool | `true` **only** when `outcome == "transient_failure"` |
| `detail` | closed enum | `access_renewed` · `still_valid` · `provider_unreachable` · `refresh_rejected` · `reauth_needed` · `store_absent` · `store_corrupted` |

### Exit codes

| Code | `outcome` | Meaning for the agent |
|--------|-----------|---------------------------|
| 0 | `renewed` or `not_needed` | Success: the token was renewed or was still valid |
| 2 | — | Missing or malformed configuration (owner action) |
| 3 | `reauth_required` | Refresh credential rejected or store absent/corrupted: **human reauthorization required** |
| 6 | — | Another renewal or authorization is already in progress |
| 7 | `transient_failure` | Transient network/provider failure: retrying later is safe |

### Semantics of each result

- **`renewed`** (`detail: access_renewed`): the access token was
  renewed; `expires_in_seconds` carries the new lifetime (~1800 s). If
  the provider rotated the refresh token, it has already been persisted
  to the store.
- **`not_needed`** (`detail: still_valid`): the token is still valid
  above the margin; **no network call was made** and nothing was
  invalidated. Treat as success, not as an error.
- **`transient_failure`** (`detail: provider_unreachable`, `retryable:
  true`): network or provider unavailable after exhausting the 2
  retries. Valid tokens remain intact. Retry later.
- **`reauth_required`** (`detail: refresh_rejected` / `reauth_needed` /
  `store_absent` / `store_corrupted`): automatic renewal is
  **impossible**. The agent must NOT keep retrying: it must notify
  the owner to run `schwab-mcp auth` (the only step that requires a
  human, by provider constraint). The state persists until
  reauthorization.

### Events on stderr (audit)

```text
2026-10-19T14:00:00Z+00:00 auth_event=renew_start outcome=initiated detail=explicit_command
2026-10-19T14:00:02Z+00:00 auth_event=renewal_success outcome=ok detail=access token renewed
```

Each attempt emits exactly one `renew_start` followed by exactly
one terminal event (`renewal_success` | `renewal_failure`). They never
contain secrets.

---

## `schwab-mcp auth-status`

Authentication health check in **a single request**: state,
lifetime of the access token and the refresh token, and whether
reauthorization is needed. **Strictly local read**: it does not call
the API, never triggers a renewal.

```sh
uv run schwab-mcp auth-status
```

- **Arguments**: none. **stdin**: never read.
- **Budget**: ≤ 2 s (local SQLite read).

### Output (stdout, one JSON line)

```json
{"state": "valid", "access_expires_in_seconds": 1520, "refresh_expires_in_seconds": 412000}
```

| Field | Type | Values |
|-------|------|---------|
| `state` | closed enum | `valid` · `reauth_required` |
| `access_expires_in_seconds` | int ≥ 0 or `null` | Seconds remaining on the access token; `null` if unknown |
| `refresh_expires_in_seconds` | int ≥ 0 or `null` | Seconds remaining on the refresh token (~7 days of life); `null` if unknown |

### Exit codes

| Code | `state` | Meaning |
|--------|---------|-------------|
| 0 | `valid` | Credentials usable; the fields indicate how much remains (even if little) |
| 2 | — | Missing or malformed configuration |
| 3 | `reauth_required` | Store absent or corrupted → human reauthorization required |

> Note: refresh token rejection by the provider (`refresh_rejected`)
> **is not detectable locally** — it manifests when using `renew` or the
> server. If `auth-status` says `valid` but an operation fails with
> `reauth_required`, believe the operation.

### Recommended use

It is the **cheap, upfront** check: consult it before long
operations, after a long pause of the agent, or at the first symptom
of authentication failure. It does not consume provider quota.

---

## `schwab-mcp serve` (MCP server)

A **stdio**, headless MCP server. Registers 3 tools
(``get_open_positions``, ``get_transaction_history`` and
``get_option_chain``) and is the process
an MCP client (opencode, Claude Desktop, etc.) launches and talks to
over stdio.

At startup:

1. Validates the configuration (fail fast).
2. Checks the token store: absent/corrupted → exits with a
   specific code **before** the MCP handshake.
3. Renews the access token if it is expired or within the margin
   (`renew_start` → `renewal_success`/`renewal_failure` events on
   stderr, trigger `margin_trigger`).
4. Validates real access with `linked_accounts()` (< 5 s).
5. Connects the stdio transport and waits for the client.

If the refresh credential is rejected, `serve` **does not start**: it
exits with a clear message asking for `schwab-mcp auth`. In that
state, the agent's recovery is: notify the owner, and monitor with
`auth-status` until the state returns to `valid` — from then on
everything works without further agent action.

In operation, automatic renewal is **transparent**: the
agent's operations do not change shape and require no extra steps.

---

## `schwab-mcp auth` — humans only

Interactive authorization flow (browser + URL paste). **An agent
must not try to run it**: it requires a human login at Schwab by
provider constraint. When a command returns
`reauth_required`, the agent's correct action is to notify the owner.

---

## Decision playbook for the agent

```text
On an authentication failure in an operation:
1. uv run schwab-mcp auth-status        # cheap, local diagnosis
2. uv run schwab-mcp renew              # recovery lever

Interpretation:
- exit 0 + renewed/not_needed  → continue normally
- exit 7 + transient_failure   → retry later (backoff); nothing was lost
- exit 6 (lock busy)           → wait and retry
- exit 3 + reauth_required     → STOP retrying; notify the owner:
                                 "run schwab-mcp auth"; monitor with
                                 auth-status until state=valid
- exit 2 (configuration)       → owner action (process env)
```

## Normative references

- MCP tool contract for ``get_open_positions``:
  [specs/003-list-open-positions/contracts/mcp-tools.md](../specs/003-list-open-positions/contracts/mcp-tools.md)
- Positions data model:
  [specs/003-list-open-positions/data-model.md](../specs/003-list-open-positions/data-model.md)
- Positions audit events:
  [specs/003-list-open-positions/contracts/events.md](../specs/003-list-open-positions/contracts/events.md)
- Full CLI contract:
  [specs/002-automated-token-renewal/contracts/cli.md](../specs/002-automated-token-renewal/contracts/cli.md)
- Renewal events contract:
  [specs/002-automated-token-renewal/contracts/events.md](../specs/002-automated-token-renewal/contracts/events.md)
- Data model (closed enums):
  [specs/002-automated-token-renewal/data-model.md](../specs/002-automated-token-renewal/data-model.md)
- MCP tool contract for ``get_transaction_history``:
  [specs/006-transaction-history/contracts/mcp-tools.md](../specs/006-transaction-history/contracts/mcp-tools.md)
- Transactions data model:
  [specs/006-transaction-history/data-model.md](../specs/006-transaction-history/data-model.md)
- Transactions audit events:
  [specs/006-transaction-history/contracts/events.md](../specs/006-transaction-history/contracts/events.md)
- MCP tool contract for ``get_option_chain``:
  [specs/008-extract-option-chain/contracts/mcp-tools.md](../specs/008-extract-option-chain/contracts/mcp-tools.md)
- Option chain data model:
  [specs/008-extract-option-chain/data-model.md](../specs/008-extract-option-chain/data-model.md)
- Option chain validation guide:
  [specs/008-extract-option-chain/quickstart.md](../specs/008-extract-option-chain/quickstart.md)
- [Usage guide](./usage.md) · [Installation guide](./installation.md)