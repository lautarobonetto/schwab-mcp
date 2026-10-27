# MCP Tool Contract: `get_option_chain` (008)

Feature: 008-extract-option-chain | Date: 2026-10-23
Read-only tool. Does not move money or place orders. Transport: stdio
exclusively via `schwab-mcp serve`.

## 1. Input schema

| Parameter | Type | Default | Constraints |
|---|---|---|---|
| `symbol` | string | — (mandatory) | non-empty |
| `max_strikes` | int | `50` | ≥ 1; applies per expiration, symmetric around the at-the-money strike |
| `option_type` | `"both"` \| `"calls"` \| `"puts"` | `"both"` | enum value |
| `delta_target` | number \| null | `null` | if present: `0 < |delta| < 1` |
| `dte_max` | int \| null | `null` | if present: ≥ 1; if `null`, current cap = 60 days |

Validation errors (before any upcall, FR-008): empty `symbol`,
`max_strikes ≤ 0`, `option_type` outside the enum,
`|delta_target| ∉ (0,1)`, `dte_max ≤ 0`.

## 2. Output schema (`ok`)

```json
{
  "symbol": "AAPL",
  "generated_at": "2026-10-23T15:04:05+00:00",
  "data_state": "realtime",
  "underlying_price": 251.31,
  "filters": {
    "max_strikes": 50,
    "option_type": "both",
    "delta_target": null,
    "dte_max_requested": null,
    "dte_max_effective": 60
  },
  "contract_fields": [
    "bid", "ask", "last", "mark", "mark_change", "mark_pct_change",
    "high", "low", "open", "close", "volume", "open_interest",
    "iv", "delta", "gamma", "theta", "vega", "rho",
    "theoretical_value", "time_value", "multiplier", "trade_time",
    "deliverable_note"
  ],
  "expirations": [
    {
      "expiration_date": "2026-10-30",
      "dte": 7,
      "atm_strike": 251.0,
      "strikes": [
        {
          "strike": 250.0,
          "call": [25.1, 25.3, 25.2, 25.2, 0.4, 0.5, 24.5, 23.0, 250, 310,
                   0.2105, 0.0312, -0.0842, 0.0621, -0.0118, 0.0,
                   25.2, 24.4, 100, "2026-10-23T15:00:00+00:00", null],
          "put":  [6.05, 6.15, 6.10, 6.10, -0.2, -1.1, 5.9, 5.5, 410, 920,
                   0.2101, -0.2894, 0.0310, -0.0841, 0.0620, -0.0118,
                   6.10, 0.4, 100, "2026-10-23T15:00:00+00:00", null]
        }
      ]
    }
  ]
}
```

Conventions:

- Each leg is a **positional array** whose order is `contract_fields`
  (declared in the response itself); `null` = not reported by the source
  (FR-007). The array may carry fewer elements than `contract_fields`
  when the trailing fields are not reported.
- `call`/`put` absent: the type is excluded by `option_type`.
- Rounding: prices 2 decimals; Greeks and IV 4 decimals.
- `dte_max_effective`: 60 (default) or the requested value — the agent
  can always verify the applied cap.
- `extended=true` (additional tool parameter): adds `provider` with the
  raw payload of the source (pattern of 003/006), without curation. The
  structural fields excluded from the curated format (`skipBars`,
  `isPitRanged`, `executable`, `settlementType`, `deliverables`) are
  accessible through this channel.

## 3. Strike selection (normative summary)

- Without `delta_target`: per expiration, up to `max_strikes` strikes per
  side of the money (ATM included if it exists).
- With `delta_target`: per expiration and **per included type**, up to 5
  strikes around the contract with the delta closest to the target
  (absolute value); `max_strikes` does not reduce this window.
- DTE: only expirations with `dte ≤ dte_max_effective`; DTE in calendar
  days.

## 4. No-data results and errors

| Case | Response |
|---|---|
| Instrument without listed options | structured `no_options_listed` result with `detail` (not a transport error) |
| DTE cap excludes all expirations | structured `no_expirations_in_range` result with `detail` and the current cap |
| Invalid filters | actionable validation error before upcall |
| Source failure / entire expiration without data | structured error; **never** a partial chain (FR-013) |
| 401/403, 5xx/408/429, 4xx | standard mapping of `provider.response_json` (taxonomy shared with 003/006) |

## 5. Guarantees

- A single invocation returns the complete chain within the requested
  limits; no pagination (FR-011).
- The limits (`max_strikes`, `option_type`, DTE) are respected 100%
  (FR-012, SC-006).
- All the Greeks and technical values of the `contract_fields` list are
  present per contract or carry explicit `null` (FR-006/FR-007).
- No state between invocations; no credentials in outputs (credential
  safety of the constitution).

## 6. Budgets

- Latency: ≤ 5 s p95 per invocation (aligned with 006 and SC-001).
- Tokens (default filters): ≤ 75,000 for a typical underlying (decision
  of the 2026-10-24 clarification; growth justification recorded in
  plan.md, Principle V); the columnar schema compacts the format.
  `docs/tools.md` reflects the expected size.
- With `delta_target`: typically < 3k tokens.
- Test: `tests/performance/test_options_chain_budgets.py`.

## 7. Auditing

- The tool emits no new authentication events (it does not touch the
  token cycle); it reuses the existing serve guard.
- Validation errors and no-data results are reported in the structured
  detail of the response, not in logs with market content.