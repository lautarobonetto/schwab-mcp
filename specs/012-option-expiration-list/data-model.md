# Data Model: Option Expiration List (`get_option_expiration_chain`)

Feature 012 — Phase 1 output. Normative for implementation; field names and
semantics here are the contract the tests assert.

## 1. Validated input

Reuses `OptionChainQuery` (spec 008 data-model §1) — no new input type.

| Field | Type | Default | Constraint |
|-------|------|---------|------------|
| `symbol` | str | required | non-empty, no internal whitespace (008 validation reused) |
| `dte_max` | int \| null | null | if present: ≥ 1; if absent, current cap = 60 |

Semantics of defaults (identical to 008 FR-005): `dte_max=null` does NOT
mean "no cap" — it applies the default cap of 60 days.
`dte_max_effective` = 60, or the provided value when ≥ 1. No hard upper
limit (clarification 2026-11-03, Q1 option A).

Not accepted by this tool (rejected with a validation error naming the
unknown parameter, per the shared validation-error pattern):
`max_strikes`, `option_type`, `delta_target` — strikes and per-type
selection are out of scope (FR-006).

## 2. Result schema (curated, `extended=false`)

```json
{
  "symbol": "AAPL",
  "generated_at": "2026-11-03T15:30:00+00:00",
  "outcome": "ok",
  "detail": null,
  "retryable": null,
  "filters": {"dte_max_requested": null, "dte_max_effective": 60},
  "expirations": [
    {"expiration_date": "2026-11-06", "dte": 3, "settlement_type": "C"},
    {"expiration_date": "2026-11-13", "dte": 10, "settlement_type": "C"}
  ],
  "expiration_count": 2
}
```

| Field | Type | Semantics |
|-------|------|-----------|
| `symbol` | string | echo of the requested symbol |
| `generated_at` | string | ISO-8601 UTC timestamp (`_result_meta` reuse) |
| `outcome` | string | `ok`, `no_expirations_in_range`, `no_options_listed`, `provider_error`, `unauthorized`, `transient_provider_failure` — the shared envelope taxonomy |
| `detail` | string \| null | human-readable detail for non-`ok` outcomes; includes `dte_max_effective` for `no_expirations_in_range` |
| `retryable` | bool \| null | envelope semantics unchanged from 008/003/006 |
| `filters` | object | echo `{dte_max_requested, dte_max_effective}` — the agent can always verify the applied ceiling |
| `expirations` | array | entries below; ascending by `expiration_date`; empty on non-data outcomes |
| `expiration_count` | int | `len(expirations)`; present on `ok` and `no_expirations_in_range` (0) |

### Expiration entry

| Field | Type | Semantics |
|-------|------|-----------|
| `expiration_date` | string | provider `expirationDate`, YYYY-MM-DD, passed through unmodified |
| `dte` | int | calendar days from **today** to `expiration_date`, computed locally (008 DTE definition; provider `daysToExpiration` is NOT used — R4) |
| `settlement_type` | string \| null | provider `settlementType` passed through — non-exhaustive observed set: `"C"` close-settled (equities), `"P"` PM index settlement, `"A"`/`"B"` AM (open) index settlement (bug `settlement-type-a`, live 2026-11-03); explicit `null` when the provider omits it — never inferred, unknown letters pass through verbatim |

Identity rule: entries are unique by `(expiration_date, settlement_type)`
pair as returned by the provider. Same-date entries MUST NOT be merged or
deduplicated (clarification 2026-11-03, Q2 option B). Ordering: ascending
`expiration_date`; ties (same date) keep provider order.

## 3. Empty and error outcomes

| Outcome | When | Shape |
|---------|------|-------|
| `no_expirations_in_range` | provider returned expirations, all with `dte > dte_max_effective` | `expirations: []`, `expiration_count: 0`, `detail` names the effective cap, `retryable: true` (agent may retry with a larger `dte_max`) |
| `no_options_listed` | provider rejects the symbol (HTTP 400, the live shape found 2026-10-24 in 008) | `expirations: []`, `retryable: false`, `detail` states the underlying has no listed options |
| `provider_error` / `unauthorized` / `transient_provider_failure` | shared taxonomy | no partial `expirations` — the envelope carries the mapped error only |

Validation failures (bad symbol, `dte_max` < 1 or non-int) raise before
any upstream call; the tool wrapper converts them to `ToolError` with the
actionable message (008 pattern).

## 4. `extended=true`

Adds `"provider": <raw payload dict>` to the curated result (same key and
pattern as 008/003/006). The raw payload includes every provider field
(`expirationType`, `isStandardOptions`, `optionDeliverables`, `lastTradingDay`,
…) untouched.

## 5. Determinism rules

- One provider invocation per request — always (FR-009, SC-004).
- DTE filter: `dte ≤ dte_max_effective`; a DTE-0 (today) entry is included
  whenever the cap ≥ 1 (validation guarantees ≥ 1 effective).
- Sorting is stable and total: ascending `expiration_date`, then provider
  order for same-date ties.
- No rounding: dates are strings, DTE is an exact integer, settlement type
  passes through verbatim.

## 6. Token budget model (SC-001, C-05)

Entry serialized compactly:
`{"expiration_date":"2026-11-06","dte":3,"settlement_type":"C"}` ≈ 63
characters ≈ 16 tokens (measured in implementation — estimator:
`len(json.dumps(..., separators=(",", ":")))/4`).
Worst case (index underlying, ~60 entries inside the cap) ≈ 63 × 60 = 3,780
chars + envelope (~188 chars) ≈ 3,968 chars ≈ 992 tokens. The recorded
implementation measurement of a synthetic dense 60-entry fixture is
**≈ 1,008 tokens** (the real envelope is slightly wider). SC-001 is
asserted on a **representative 12-entry fixture** (AAPL-style, every real
underlying): ≤ 1,000 tokens. The dense worst case has its own **recorded
ceiling of ≤ 1,100 tokens** (plan.md Complexity Tracking).
See `tests/performance/test_option_expirations_budgets.py`.