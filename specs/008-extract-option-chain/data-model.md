# Data Model: Option Chain Extraction with Filters

Feature: 008-extract-option-chain | Date: 2026-10-23

## 1. Entities

### OptionChainQuery (validated input)

Invocation parameters, validated before any upcall.

| Field | Type | Default | Validation |
|---|---|---|---|
| `symbol` | string | — (mandatory) | non-empty, no internal spaces; passed as-is to the provider (matching/normalization is the provider's job) |
| `max_strikes` | int | `50` | ≥ 1 |
| `option_type` | enum `both` \| `calls` \| `puts` | `both` | enum value |
| `delta_target` | float \| null | `null` | if present: `0 < |delta_target| < 1` |
| `dte_max` | int \| null | `null` | if present: ≥ 1; if absent, current cap = 60 |

Semantics of defaults: `dte_max=null` does NOT mean "no cap" — it means
"I don't choose a DTE" and it applies the default cap of 60 days
(FR-005).

### ChainMeta (response metadata)

| Field | Type | Semantics |
|---|---|---|
| `symbol` | string | queried instrument (echo) |
| `generated_at` | ISO-8601 UTC string | time of the query |
| `data_state` | `realtime` \| `delayed` | freshness reported by the source |
| `underlying_price` | float \| null | current price of the underlying (`includeUnderlyingQuote`) |
| `filters` | object | echo of the effective query (includes `dte_max_effective`: 60 or the requested value) |
| `contract_fields` | list of strings | column order of each leg array (see §2) |

### Expiration (expiration date)

| Field | Type | Semantics |
|---|---|---|
| `expiration_date` | string `YYYY-MM-DD` | expiration date (key of `*ExpDateMap`) |
| `dte` | int | calendar days from today to the expiration |
| `atm_strike` | float | strike closest to `underlying_price` (center of the strike window; analysis reference) |
| `strikes` | list of StrikeRow | rows ordered by ascending strike |

### StrikeRow (row per strike)

| Field | Type | Semantics |
|---|---|---|
| `strike` | float | exercise price |
| `call` | array of numbers/null \| absent | CALL leg in `contract_fields` order; absent if the filter excludes CALLs |
| `put` | array of numbers/null \| absent | PUT leg in `contract_fields` order; absent if the filter excludes PUTs |

Rules: a leg exists only if the type is included by `option_type`; the
strike appears if at least one included leg exists in the payload.

### ContractFields (columns of each leg — fixed order)

`bid`, `ask`, `last`, `mark`, `mark_change`, `mark_pct_change`,
`high`, `low`, `open`, `close`, `volume`, `open_interest`,
`iv`, `delta`, `gamma`, `theta`, `vega`, `rho`,
`theoretical_value`, `time_value`, `multiplier`, `trade_time`,
`deliverable_note`

- Complete Greeks: delta, gamma, theta, vega, rho (FR-006).
- Deterministic rounding: prices/values to 2 decimals; Greeks and IV to
  4 decimals; no rounding for `volume`/`open_interest`/`multiplier`
  (integers).
- Field missing at the source → `null` in its column (FR-007).
- Structural fields excluded from the curated format (available via
  `extended=true`): see research R6.

## 2. Relationships

```
OptionChainQuery --validates--> provider upcall
ChainMeta 1 --N Expiration
Expiration 1 --N StrikeRow
StrikeRow 0..1 call leg + 0..1 put leg
```

- Each `Expiration` comes from a key of `callExpDateMap` /
  `putExpDateMap` in the payload (union of both keys by date).
- `atm_strike` is calculated per expiration against `underlying_price`.
- The strike window (without delta) is symmetric around `atm_strike`;
  the per-delta window is per type (clarification 2026-10-23).

## 3. Selection algorithms (deterministic)

- **Strike window (without delta)**: per expiration, the `max_strikes`
  closest strikes below and above `atm_strike` (including the ATM if it
  exists); if there are fewer, all of them.
- **Delta window**: per expiration and per included type: contract with
  the delta closest to `delta_target` (absolute value) + 2 contiguous on
  each side → up to 5 (or the available ones around). Does not interact
  with `max_strikes` (clarification 2026-10-23).
- **DTE filter**: `dte ≤ dte_max_effective`; the filtering also happens
  at the origin (`fromDate`/`toDate`) and the post-filter corrects the
  edges.

## 4. Validation and result states

Result states (no lifecycle: stateless tool):

| State | When | Shape |
|---|---|---|
| `ok` | chain returned | ChainMeta + expirations |
| `no_options_listed` | the source reports no expiration maps for the symbol | structured result with `detail` (FR-009) |
| `no_expirations_in_range` | the DTE cap excludes all expirations | structured result with `detail` and the current cap (FR-009) |
| validation error | invalid filters (§1) | actionable error before upcall (FR-008) |
| transport error | source failure / entire expiration without data | structured error without partial chain (FR-013) |

## 5. Expected volume (for budget tests)

- Strike row with both legs: ~55–75 tokens (columns, rounding).
- Typical underlying with defaults (50/side → 100 strikes × ~12
  expirations): ~600–1200 rows → **~45–75k estimated tokens**;
  normative budget set at **≤75,000 tokens** with defaults (clarification
  2026-10-24, SC-002, justification in plan.md) and **<3,000** with
  `delta_target`. The budget test uses a representative fixture and
  measures the actual serialization.
- With `delta_target` active: ~5 strikes × 2 types × N expirations →
  typically < 3k tokens.