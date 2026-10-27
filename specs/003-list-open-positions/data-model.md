# Data Model: List Open Positions

**Feature**: `003-list-open-positions` | **Date**: 2026-10-20

There is no new persistence: the model is **ephemeral** (the result of a
snapshot query) plus **audit events** append-only in the auxiliary
channel (contract in `contracts/events.md`). The schwabdev SQLite token
store remains untouched (only implicit read via the client).

## Entities

### 1. PositionEntry (ephemeral; one entry per (account, instrument))

Unit of FR-003/FR-013. Serialized inside the tool result.

| Field | Type | Validation | Notes |
|-------|------|------------|-------|
| account_hash | str | non-empty, opaque | Owning account; never the raw number (research D3) |
| symbol | str | non-empty | Provider's `instrument.symbol` |
| instrument_type | enum str | `EQUITY` \| `OPTION` \| `MUTUAL_FUND` \| `FIXED_INCOME` \| `CASH_EQUIVALENT` | `instrument.assetType`; closed provider vocabulary |
| description | str | non-empty | Human-readable description of the instrument |
| quantity | float | ≠ 0, signed | `longQuantity − shortQuantity`; long positive, short negative (FR-013) |
| average_price | float | ≥ 0 | Average acquisition cost (`averagePrice`) |
| market_value | float | sign consistent with quantity | Current market value (`marketValue`) |
| unrealized_pl | float | — | Derived (research D3); negative = loss |
| price_timestamp | str (ISO-8601 UTC) | parseable | Payload retrieval moment; the value is the one computed by the provider (FR-012, research D4) |
| underlying_symbol | str \| absent | — | `OPTION` only (research D3) |
| put_call | enum str \| absent | `PUT` \| `CALL` | `OPTION` only |
| strike_price | float \| absent | > 0 | `OPTION` only |
| expiration_date | str \| absent | — | `OPTION` only |

Rules:
- Identity: `(account_hash, symbol)` unique within the result (FR-013);
  lots of the same instrument consolidated with an average `average_price`.
- Zero quantity ⇒ the entry **does not exist** in the result (FR-015, D5).
- Option fields present ⇔ `instrument_type == "OPTION"`; for other
  types they are omitted (never `null` — token budget, research D9).

### 2. PositionsResult (ephemeral; the tool's single result, FR-002)

One structured object per invocation; self-classifying (FR-007).

| Field | Type | Validation | Notes |
|-------|------|------------|-------|
| outcome | enum str | `ok` \| `partial_failure` \| `transient_failure` \| `reauth_required` | Single class (SC-004) |
| positions | list[PositionEntry] | empty only allowed if `outcome == "ok"` | Full list of effective holdings (FR-001); `[]` = no positions, valid (FR-005) |
| accounts_failed | list[{account_hash, detail}] \| absent | — | Only in `partial_failure` (FR-010): account + fixed reason (`provider_error` \| `transient`) |
| retryable | bool | — | `true` only with `outcome == "transient_failure"` (D6) |
| detail | enum str | closed vocabulary | `data_received` · `no_positions` · `account_failed` · `provider_unreachable` · `reauth_needed` · `store_absent` · `store_corrupted` |
| retrieved_at | str (ISO-8601 UTC) | parseable | Retrieval timestamp; equal to each entry's `price_timestamp` |

Rules:
- No field contains secrets (FR-008); the redaction filter of
  `log.py` is defense in depth.
- `outcome: ok` + `positions: []` is success, not an error (FR-005/SC-006).
- `partial_failure` is a partial success: the positions of the accounts
  that responded DO come in `positions` (FR-010).

### 3. ExtendedPositionFields (ephemeral; FR-003a, only with `extended=true`)

Uninterpreted passthrough of the provider's remaining fields
(`cusip`, `settledLongQuantity`, `settledShortQuantity`,
`currentDayProfitLoss`, `maintenanceRequirement`, full `instrument`,
etc.). No schema of its own: keys exactly as the provider names them,
documented as opaque but stable per API version. With
`extended=true`, each `PositionEntry` adds the `extended` object with
this content (and the declared payload budget grows — research D9).

### 4. PositionsAuditRecord (audit event line; pattern from 002)

`positions_query_start` → exactly one terminal
(`positions_query_success` | `positions_query_failure`), without secrets,
auxiliary channel. Vocabulary and format in `contracts/events.md`.

### 5. TokenSet (persisted; UNCHANGED — do not duplicate)

Owned by schwabdev; this feature only consumes it through the client
already instantiated in `server.py`. See
`specs/002-automated-token-renewal/data-model.md` §4.

## State transitions

There are no states of this feature's own (snapshot without persistence). The
relevant transitions are those of the authentication state (002), which
determine the observable `outcome`:

```text
credentials valid            → outcome ok | partial_failure | transient_failure
refresh rejected / store     → outcome reauth_required
absent/corrupted
network/provider down        → outcome transient_failure (retryable: true)
```

The same entry rules (`store_absent`, `store_corrupted`,
re-auth) that govern `serve` apply here: the tool never triggers
interactive authorization (guard hook from 001/002).