# Data Model: Underlying-Aware Symbol Filter and Underlying Reference

Feature: 007-underlying-symbol-filter | Date: 2026-10-24
Base: data model of `specs/006-transaction-history/data-model.md` (the
tool and its models exist; this feature **extends** them without
replacing anything). 006's outcome/detail enums and all cross-rules 1–8
remain in force unchanged.

## §1. MovementEntry (extended)

Existing 006 fields unchanged: `account_hash`, `occurred_at`,
`category`, `description` (truncated to 80 in curated), `amount`,
`currency`, `symbol` (only with instrument), `instrument_type` (only
with instrument), `extended` (only with `extended=true`).

### New field

| Field | Type | Presence | Semantics |
|-------|------|----------|-----------|
| `underlying_symbol` | string | **only** movements whose instrument category is option (`instrument_type == "OPTION"` and identifiable OCC symbol) | Identifier of the underlying: the portion before the last 15 characters of the registered OCC symbol, without padding (`"AMD   261120P00630000"` → `"AMD"`). Reported as the source records it (after strip). Absent (not `null`) for non-options and for options whose symbol has no identifiable OCC encoding |

Rules:

0. **Terminology**: `underlying_symbol` (the output field) materializes
   the "underlying reference" defined in the spec (US2/FR-004); its
   value is derived from the **root** of the OCC symbol — the underlying
   identifier at the start of the standard option symbol. Three names,
   one concept.

1. **R1 — Derivation**: `root = symbol[:-15].strip()` when the last 15
   characters match the OCC pattern (`YYMMDD` digits + `C`/`P` +
   8 digits). Right-anchored, independent of root padding (same
   knowledge verified live in the positions fix).
2. **R2 — Presence**: `underlying_symbol` present ⇔ the movement is an
   option AND its root is identifiable. Never an explicit `null` in the
   JSON (same `exclude_none` pattern as `symbol`/`instrument_type`).
3. **R3 — Non-options unchanged**: transfers, interest, adjustments and
   equity/cash trades DO NOT carry the field (output identical to 006
   for those movements).
4. **R4 — Case**: reported as the source records it (uppercase in
   practice); case-insensitivity applies only to filter matching, never
   to the output.

## §2. HistoryQuery — extended semantics of the `symbol` filter

Input parameters unchanged: `start_date`, `end_date`, `symbol`
(optional), `extended`, `offset`.

### Matching rule (FR-001/FR-002 of the spec)

A movement **involves** the filtered instrument `F` (case-insensitive,
exact, no fuzzy comparison) if **any** of the following holds:

| # | Form | Condition | Example with `F = "NOK"` |
|---|------|-----------|--------------------------|
| M1 | Exact registered symbol | `movement.symbol.upper() == F.upper()` | trade of the equity `NOK`, dividend registered under `NOK` |
| M2 | Option root | the movement is an option with an identifiable OCC symbol and `root.upper() == F.upper()` | `NOK   261218P00011000` (buy/sell of the 20 puts) |
| M3 | Complete option symbol | `movement.symbol.upper() == F.upper()` when `F` is a complete option symbol | `F = "NOK   261218P00011000"` → only that option |

Note: M3 is a particular case of M1 (equality of the registered symbol);
it is listed separately because that input is today rejected by the
provider (HTTP 400) and the feature explicitly supports it — the tool no
longer sends the filter upstream (research R1).

### Dual validation (clarification C, FR-003)

1. Lookup `instruments(symbols=[F], projection="symbol-search")` — a
   single upcall, only when there is a filter (same as 006).
2. Directory resolves `F` → continue with the unfiltered-upstream sweep
   + local matching.
3. Directory does NOT resolve `F` → **do not fail**: run the sweep
   anyway. Final classification:
   - ≥ 1 movement matches (M1/M2/M3) → `ok` with those movements.
   - 0 movements match → `instrument_not_found` error naming `F`
     (actionable ToolError, as today).
4. Newly derived behavior: `F = "CURRENCY_USD"` (not resolved in the
   directory) now returns its tagged-cash movements instead of
   `instrument_not_found`.

### Filter with no movements and no directory entry

`instrument_not_found` preserves its honesty semantics: a mistyped
symbol (no directory entry, no movements) produces the error naming the
symbol — never an ambiguous `no_movements`.

## §3. TransactionsResult (no structural changes)

All 006 fields unchanged: `outcome`, `detail`, `retryable`,
`retrieved_at`, `total_count`, `movements`, `returned`, `has_more`,
`next_offset`, `accounts_failed`, `offset_echo`.

Refined semantics (nothing renamed):

- `total_count` = size of the complete **filtered** set of the range
  (all pages of the filtered result).
- `detail = no_movements_for_instrument` ⇔ the range was valid, there
  were no failures and **nothing** matched the filter in any form
  (M1/M2/M3).
- 006's cross-rules 1–8 remain in force (including rule 6:
  `no_movements_for_instrument` ⇒ … and pagination rules 2/3).
- Pagination computed over the filtered set; `offset`/`offset_echo`
  identical to 006.

## §4. Subset-consistency (FR-005)

Structural property guaranteed by the design (unfiltered sweep + local
matcher — research R1): for the same range,

```
filtered(result) == matcher(unfiltered(result), F)
```

where `matcher` applies M1∨M2∨M3. A unit regression test pins the
property against deterministic fixtures.

## §5. Budgets (Principle V)

| Budget | Declared value | Impact |
|--------|----------------|--------|
| p95 latency | ≤ 5 s (006's SC-001) | Unchanged: same upcalls (1 linked_accounts + N transactions) + 1 optional instruments |
| Default page (50 movements) | ≤ 16 KB (006's SC-003) | Maintained **including** `underlying_symbol` (~25 bytes × option movement; worst case 50 options ≈ +1.2 KB) |
| Extended page | ≤ 64 KB | Unchanged (extended already included the passthrough with the OCC) |