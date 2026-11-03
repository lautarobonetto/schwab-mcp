# MCP Tool Contract: `get_option_expiration_chain` (012)

Agent-facing contract for the new tool. Mirrors the established envelope of
`get_option_chain` (008) — read alongside `docs/tools.md`.

## 1. Input

| Parameter | Type | Default | Meaning |
|-----------|------|---------|---------|
| `symbol` | string | required | exactly one underlying symbol; non-empty, no internal whitespace |
| `dte_max` | int \| null | `null` | if present: ≥ 1 — replaces the 60-day default ceiling; **`null` does not mean "no ceiling"**: it applies the current 60-day ceiling |
| `extended` | bool | `false` | `false` (default): compact curated set. `true`: adds `provider` with the raw provider payload (003/006/008 pattern) |

No other parameters are accepted: `max_strikes`, `option_type`, and
`delta_target` are `get_option_chain` concerns and are rejected here.

## 2. Output schema (curated)

See data-model.md §2 for the full field table. Summary:

```json
{"symbol": "AAPL", "generated_at": "…", "outcome": "ok",
 "detail": null, "retryable": null,
 "filters": {"dte_max_requested": null, "dte_max_effective": 60},
 "expirations": [{"expiration_date": "2026-11-06", "dte": 3,
                  "settlement_type": "C"}],
 "expiration_count": 1}
```

- `expirations` is ascending by `expiration_date`; same-date entries are
  kept separately, distinguished by `settlement_type` (never merged).
- `dte` is calendar days from today (same definition as
  `get_option_chain`).
- Only `expiration_date`, `dte`, `settlement_type` are curated — no
  strikes, quotes, greeks, or per-strike data (FR-006).

## 3. Outcomes

| Outcome | When | `retryable` |
|---------|------|-------------|
| `ok` | at least one expiration inside the ceiling | `null` |
| `no_expirations_in_range` | expirations exist but all have `dte > dte_max_effective`; `detail` names the cap; `expirations: []` | `true` |
| `no_options_listed` | provider rejects the symbol (HTTP 400) — no listed options | `false` |
| `provider_error` | provider returned an unusable payload | `false` |
| `unauthorized` | token rejected / reauth required | `false` |
| `transient_provider_failure` | connectivity / throttling | `true` |

## 4. Validation errors (before any upcall)

| Trigger | Error names |
|---------|-------------|
| empty / whitespace / internal-space symbol | `symbol` and the constraint |
| `dte_max` non-int or < 1 | `dte_max` and `>= 1` |
| unknown extra parameter | the parameter name |

The unknown-parameter rule is enforced by the tool wrapper's fixed
signature (plus the MCP tool-schema layer) and asserted in tests by
tasks.md T008.

## 5. Agent guidance (normative)

1. `dte_max` is a ceiling, NOT a minimum — there is no `dte_min`. To find
   expirations with **DTE ≥ N**, request the maximum window you accept and
   filter client-side using `expirations[].dte`.
2. `dte_max: null` applies the 60-day default (verifiable in
   `filters.dte_max_effective`) — exactly like `get_option_chain`.
3. Prefer this tool over `get_option_chain` whenever the question is
   "which expirations exist?" — it costs hundreds of tokens instead of
   thousands to ~110k. Follow up with a targeted `get_option_chain` query
   (`dte_max`, `delta_target`, `max_strikes`) for the chosen expiration.
4. Same-date duplicate entries (index underlyings, e.g. SPX AM/PM
   settlement) are intentional: pick the entry whose `settlement_type`
   matches your analysis.
5. `extended=true` is for debugging/schema discovery only — payloads are
   larger and provider fields are unstable.

## 6. Budgets (Principle V)

- Curated default response (representative ~12-entry fixture) ≤ 1,000
  tokens (SC-001), test-enforced on a representative AAPL-style fixture.
  Dense worst-case ceiling (60 near-daily entries): ≤ 1,100 tokens
  (recorded in plan.md Complexity Tracking).
- Latency ≤ 10 s per invocation (spec SC-002); the performance test
  asserts the measured budget of ≤ 5 s, mirroring 008's p95 hook.
- Exactly one provider invocation per request in every scenario,
  test-enforced (SC-004).