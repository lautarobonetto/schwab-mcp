# Data Model: Account Transaction History (006)

Date: 2026-10-23. Derived from [spec.md](./spec.md) and [research.md](./research.md).
Conventions inherited from the data models of 002/003: closed enums,
explicit optional fields, never secrets.

## Closed enums

### `TransactionOutcome` (reused from 003 — single definition)

| Value | Meaning |
|-------|-------------|
| `ok` | Complete query: all accounts responded |
| `partial_failure` | Some accounts failed, others responded (see `accounts_failed`) |
| `transient_failure` | Network/provider unavailable on the first attempt |
| `reauth_required` | Credentials rejected/missing or corrupt store: human re-authorization |

### `TransactionDetail` (closed enum of this tool)

| Value | Meaning |
|-------|-------------|
| `history_retrieved` | History retrieved (≥ 1 movement) |
| `no_movements` | No movements in the range for any account (valid range) |
| `no_movements_for_instrument` | Symbol filter active, valid symbol, no movements in the range |
| `account_failed` | ≥ 1 account failed (only with `partial_failure`) |
| `provider_unreachable` | Transient failure (only with `transient_failure`) |
| `reauth_needed` | Re-authorization required (only with `reauth_required`) |

### `MovementCategory` (clarify Q3 + research D5)

| Value | Mapped upstream types (v1) |
|-------|------------------------------|
| `trade` | `TRADE` |
| `transfer` | `RECEIVE_AND_DELIVER`, `ACH_RECEIPT`, `ACH_DISBURSEMENT`, `CASH_RECEIPT`, `CASH_DISBURSEMENT`, `ELECTRONIC_FUND`, `WIRE_IN`, `WIRE_OUT` |
| `dividend_or_interest` | `DIVIDEND_OR_INTEREST` |
| `adjustment` | `JOURNAL`, `SMA_ADJUSTMENT` |
| `other` | `MEMORANDUM`, `MARGIN_CALL`, `MONEY_MARKET` |
| `interest` | *(reserved, no mapping in v1)* |
| `dividend` | *(reserved, no mapping in v1)* |
| `fee` | *(reserved, no mapping in v1)* |
| `corporate_action` | *(reserved, no mapping in v1)* |

Any upstream type **not listed** (a new provider type) → `other`
(spec FR-002 fallback), with the original text in `extended`.

### `ProviderTransactionType` (SDK mirror, frozen copy in the app)

`TRADE`, `RECEIVE_AND_DELIVER`, `DIVIDEND_OR_INTEREST`, `ACH_RECEIPT`,
`ACH_DISBURSEMENT`, `CASH_RECEIPT`, `CASH_DISBURSEMENT`,
`ELECTRONIC_FUND`, `WIRE_OUT`, `WIRE_IN`, `JOURNAL`, `MEMORANDUM`,
`MARGIN_CALL`, `MONEY_MARKET`, `SMA_ADJUSTMENT`.

The tool **always queries with the full comma-separated list**
(research D2) — there is no type-filtering parameter in v1: the
default is "everything" (FR-002).

## Entities

### `HistoryQuery` (request)

| Field | Type | Default | Validation rule |
|-------|------|---------|---------------------|
| `start_date` | string | mandatory | Parseable `YYYY-MM-DD`; real date |
| `end_date` | string | mandatory | Parseable `YYYY-MM-DD`; ≥ `start_date`; ≤ today (America/New_York) |
| `symbol` | string \| absent | no filter | not empty; validated against `instruments` (research D6) |
| `extended` | bool | `false` | — |
| `offset` | int | `0` | ≥ 0 |

Validation errors (FR-004) → standard MCP tool error with an actionable
message, **before** any upcall (including `linked_accounts`):
malformed date; `end_date < start_date`; range > 1 year (366 calendar
days); future `end_date`; empty `symbol`.

Range semantics: both boundaries **inclusive**, interpreted in
America/New_York (clarify Q2): `startDate` = 00:00:00 NY on the start
day, `endDate` = end of the end day (23:59:59.999 NY), the day's actual
(DST) offset via `zoneinfo`.

### `MovementEntry` (individual movement)

| Field | Type | Presence | Semantics |
|-------|------|-----------|-----------|
| `account_hash` | string | always | Opaque account identifier (never the account number) |
| `occurred_at` | ISO-8601 string | always | Date/time of the movement (from the payload; if the provider only gives a date, documented NY noon) |
| `category` | `MovementCategory` | always | Normalized category (closed enum) |
| `description` | string | always | Human-readable description, **truncated to 80 characters** in default (full text in `extended`) |
| `amount` | float | always | Main monetary effect as reported by the provider (provider's sign, not reinterpreted) |
| `currency` | string | always | Currency of the movement: use the provider's currency field **if it exposes one**; otherwise `"USD"` (USD-denominated accounts, research R10). Never convert. |
| `symbol` | string \| absent | only if there is an instrument | Symbol of the referenced instrument; in multi-leg trades the first non-currency instrument of `transferItems` is curated (the `CURRENCY_USD` fee legs come first in the real payload) |
| `instrument_type` | string \| absent | only if there is an instrument | Asset type (`EQUITY`, `ETF`, `OPTION`, …) |
| `extended` | object \| absent | only `extended=true` | Provider item passthrough: original `type`, full `description`, `fees`, `commissions`, `netAmount`, `settlementDate`, `transferItems` (relevant subset), `activityId` |

Default curation (FR-007): only the table fields, without `extended`.
No secrets; opaque `account_hash`.

### `TransactionsResult` (response)

| Field | Type | Presence | Semantics |
|-------|------|-----------|-----------|
| `outcome` | `TransactionOutcome` | always | See enum |
| `detail` | `TransactionDetail` | always | See enum |
| `retryable` | bool | always | `true` only when `outcome == "transient_failure"` |
| `retrieved_at` | ISO-8601 UTC string | always | Time the payload was retrieved |
| `total_count` | int | `outcome=ok` | Total movements of the full range (all pages) |
| `movements` | array of `MovementEntry` | `outcome=ok` | Current page, chronological ascending order (tie-break `account_hash`, `activityId`); `[]` valid only with `no_movements`/`no_movements_for_instrument` |
| `returned` | int | `outcome=ok` | Number of movements on this page (≤ 50) |
| `has_more` | bool | `outcome=ok` | `true` if movements remain to be delivered |
| `next_offset` | int \| absent | only `has_more=true` | Offset for the next page |
| `accounts_failed` | array \| absent | only `partial_failure` | `[{"account_hash": str, "detail": "provider_error"|"transient"}]` |
| `offset_echo` | int | `outcome=ok` | Effective offset applied to this page |

Pagination invariant (SC-006): walking with `next_offset` delivers the
complete union without duplicates and without omissions, over the
snapshot of the history at query time.

## Cross-validation rules (validated by the model)

1. `outcome=ok` + `movements=[]` ⇔ `detail ∈ {no_movements,
   no_movements_for_instrument}`.
2. `has_more=true` ⇒ `next_offset` present and `returned == 50`.
3. `next_offset` present ⇒ `has_more=true`.
4. `accounts_failed` present ⇔ `outcome=partial_failure`.
5. `retryable=true` ⇔ `outcome=transient_failure`.
6. `detail ∈ {no_movements_for_instrument}` ⇒ `symbol` was present
   in the request.
7. `retrieved_at` ≥ `occurred_at` of every delivered movement.
8. No field contains tokens, app keys, secrets or authorization URLs
   (asserted by the no-secrets test).

## Lifecycle / state

No persistent state: the tool is stateless and has no cache between
requests (same criterion as 003/005). The only "state" is the `offset`
the agent sends back.