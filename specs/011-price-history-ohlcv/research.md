# Research: Price History OHLCV (`get_price_history`) (011)

Feature: 011-price-history-ohlcv | Date: 2026-11-02
All decisions below resolve the technical unknowns of the spec. Evidence
sources: `schwabdev` 4.0.0 client source (installed package, `validation.py`
cross-validity tables), the `quotes.py` tool precedent (010), the
codebase-memory graph, and the spec clarifications (session 2026-11-02).

## D1 — Surface: one symbol per invocation via `price_history()`

**Decision**: one MCP tool `get_price_history(symbol, frequency, period,
extended_hours=False, extended=False)`. The orchestration calls
`schwabdev.price_history(symbol, periodType, period, frequencyType,
frequency, needExtendedHoursData=...)` exactly once per invocation.

**Rationale**: the spec fixes one symbol per invocation (FR-001), and the
provider exposes a single price-history endpoint. One call per invocation
serves the latency budget (SC-001) and keeps the code path identical to the
quotes precedent.

**Alternatives considered**:
- Batch multi-symbol support — spec scope-out (FR-001); rejected.
- Two calls (fetch + verification) — no benefit, doubles latency; rejected.

## D2 — Frequency set and SDK mapping (clarification Q3)

**Decision**: the tool exposes exactly these frequencies, mapped to the
provider as follows:

| Tool frequency | Provider call | Notes |
|---|---|---|
| `5m` | `frequencyType="minute", frequency=5` | native |
| `15m` | `frequencyType="minute", frequency=15` | native |
| `30m` | `frequencyType="minute", frequency=30` | native |
| `1h` | `frequencyType="minute", frequency=30`, aggregated 2:1 locally | provider has no hourly frequency |
| `daily` | `frequencyType="daily", frequency=1` | native |
| `weekly` | `frequencyType="weekly", frequency=1` | native; label verified/normalized per D7 |

**Rationale**: the provider's minute frequency only supports 1/5/10/15/30 and
its `frequencyType` set is {minute, daily, weekly, monthly} — there is no
hourly frequency (verified in `schwabdev/validation.py`:
`_VALID_FREQUENCIES`). The clarified frequency set (Q3) drops 1-minute and
monthly, so every requested frequency is either native (5m/15m/30m/daily/
weekly) or derivable by a small pure aggregation (1h from 30m). The
cross-validity rules (`_VALID_FREQ_TYPES`) constrain which `periodType` each
frequency may use — see D3.

**Alternatives considered**:
- Serve 1h by requesting `frequency=60` — not a valid provider value;
  rejected.
- Derive weekly from daily candles locally — duplicates a provider capability
  and multiplies fetch size ~5×; rejected unless D7's fixture shows the
  provider weekly labels violate FR-019 (contingency recorded there).

## D3 — Named period presets bounded per frequency (clarification Q4)

**Decision**: the period is one of a declared set of named presets; the
allowed presets per frequency are chosen so that **no preset can produce more
than 260 candles** (ceiling-by-construction, FR-004):

| Frequency | Presets | Max candles (ceiling driver) |
|---|---|---|
| `5m` | `1d`, `2d`, `3d` | 3d ≈ 234 (78 candles/session) |
| `15m` | `1d`, `2d`, `5d`, `10d` | 10d = 260 |
| `30m` | `1d`, `2d`, `5d`, `10d` | 10d = 130 |
| `1h` | `1d`, `2d`, `5d`, `10d` | 10d = 65 (130 fetched 30m) |
| `daily` | `1m`, `3m`, `6m`, `1y`, `ytd` | 1y = 252 |
| `weekly` | `1m`, `3m`, `6m`, `1y`, `2y`, `3y`, `5y`, `ytd` | 5y ≈ 260 |

Default when `period`/`frequency` are omitted: `daily` + `1m` (≈ 22 candles).

**Rationale**: the provider cross-validity rules force this shape —
`periodType "day"` pairs only with minute frequencies, while daily/weekly
need `periodType` month/year/ytd. The presets translate 1:1 to provider
parameters (e.g., `1d` → `periodType="day", period=1`; `5y` →
`periodType="year", period=5`), so validation is a table lookup, no
arithmetic, and the ceiling is enforced by construction rather than by
post-hoc truncation (FR-004, C-04). The 260-candle global ceiling follows
from the token baseline in D5. Long horizons beyond 5 years stay reachable
later only with a stated need and a recorded budget justification
(Principle V).

**Alternatives considered**:
- Numeric look-back or start/end dates — spec scope-out (FR-014); rejected.
- Per-frequency ceilings above 260 (e.g., weekly 10y = 520 candles ≈ 9.4k
  tokens) — violates the "few thousand tokens" budget intent of roadmap Q4;
  rejected.

## D4 — Extended-hours flag mapping (clarification Q1)

**Decision**: `extended_hours=True` maps to the provider parameter
`needExtendedHoursData=True`; default `False`. The flag is **valid only for
intraday frequencies** (`5m`, `15m`, `30m`, `1h`); setting it on `daily` or
`weekly` is a validation error (`extended_hours_not_applicable`) raised
before any upcall.

**Rationale**: `needExtendedHoursData` exists natively on the provider call
(reuse before creation). Extended-hours sessions do not change daily/weekly
aggregates meaningfully, so accepting the flag there would be a speculative
surface (C-04); failing fast keeps validation semantics uniform.

**Alternatives considered**:
- Silently ignore the flag on daily/weekly — hides agent mistakes; rejected
  (validation-error pattern of the existing tools).

## D5 — Token baseline and ceilings (roadmap Q4)

**Decision**: the curated candle is emitted as a compact JSON object with
epoch-millisecond timestamps:

```json
{"t": 1734560400000, "o": 585.12, "h": 585.67, "l": 584.9, "c": 585.45, "v": 35412300}
```

Deterministic size arithmetic (≈ 4 chars/token): timestamp 13 digits + keys
and separators ≈ 75 chars ≈ **≈ 19–22 tokens per candle**. Consequences:
default (22 candles) ≈ ≤ 550 tokens; worst-case preset (260 candles) ≈
≤ 5,200 tokens; plus a ~150-token envelope. The in-progress marker adds one
short field to the last candle only.

**Rationale**: roadmap Q4 asked for a measured baseline in this plan. A live
measurement was attempted during planning but blocked by the expired refresh
token of the local credential store (the project's `renew` reported success
while the raw SDK still refuses — an environment state outside this
feature's scope). The arithmetic baseline is exact for the fixed field shape
and precision, and the first TDD step records a real provider payload as a
fixture (`tests/unit/fixtures/price_history_payloads.py`); the token-usage
tests assert budgets **against that fixture**, and any measured excess
forces the ceiling downward with a recorded justification (Principle V).

**Alternatives considered**:
- ISO 8601 timestamp strings (like 010's `trade_time`) — +7 tokens/candle
  across hundreds of candles for no analysis benefit; rejected (C-05).
- Wait for a live measurement before planning — blocks the flow on an
  environment issue unrelated to the design; rejected with the fixture-pinned
  verification above.

## D6 — In-progress candle detection (clarification Q2)

**Decision**: a candle is marked `in_progress: true` iff its period window
extends beyond the fetch time — concretely, the last candle of the response
is in-progress when `period_end(candle) > fetch_time`; all other candles are
`in_progress: false` (the field is emitted on every candle for a uniform
shape, or only on the last when budget-measured tighter — pinned by the
mapping tests against the fixture).

Period-end derivation per frequency: intraday native candles = provider
timestamp + frequency span (pending the stamping convention pin in D8);
aggregated hourly = end of the hour bucket; daily/weekly = pinned by the
recorded fixture (provider stamps daily/weekly candles at a fixed session
offset — the fixture determines whether the stamp is session start or end,
and the mapping normalizes to period end deterministically).

**Rationale**: the rule is deterministic and testable with a frozen
`fetch_time` injected in tests; no market-hours call is needed (unlike 010's
freshness derivation), keeping one provider call per invocation.

**Alternatives considered**:
- Use a market-hours call to decide "forming vs closed" — a second provider
  call per invocation for information the period-end comparison already
  yields; rejected (C-05).
- Never mark in-progress (treat all as final) — violates clarified Q2 and
  FR-017; rejected.

## D7 — Weekly candle labeling (clarification Q5)

**Decision**: pass through provider weekly candles, then verify the label
convention against the recorded fixture. FR-019 requires the closing
session's timestamp. If the fixture shows the provider stamps weekly candles
at the closing session, the mapping is a pass-through; if not, the mapping
normalizes each weekly label forward to the last session of that ISO week
(derivable from the stamp + weekday arithmetic, no extra provider call).

**Rationale**: the provider already offers weekly frequency (C-03); the only
open point is its stamping convention, which is a constant to be pinned by a
test, not a design fork. The contingency keeps FR-019 guaranteed either way
without a second implementation path up front (KISS).

**Alternatives considered**:
- Always aggregate weekly from daily candles locally — duplicates a provider
  capability and multiplies fetch size; rejected unless the contingency
  triggers.

## D8 — Provider stamping convention (the one empirical constant)

**Decision**: treat the provider candle `datetime` (epoch ms) convention —
period start vs period end, per frequency — as an empirical constant pinned
by the first TDD step: record one real payload per frequency (daily, weekly,
5m, 30m) into `tests/unit/fixtures/price_history_payloads.py` and assert the
observed convention; the mapping and the D6 rule parameterize on it.

**Rationale**: the Schwab market-data API does not document the convention
explicitly; guessing risks a silently wrong in-progress rule and weekly
labels. A recorded fixture converts the unknown into a regression test. This
is an implementation-time pin, not an open design question: the mechanism
(period-end comparison, D6) is fully decided.

**Alternatives considered**:
- Hard-code an assumed convention — untestable guess; rejected (violates the
  test-first gate for the affected rules).

## D9 — Validation, errors, and symbol kinds

**Decision**: validation runs before any upcall (FR-007) and covers: symbol
presence and format, symbol kind (equity/ETF and index grammars only —
option-contract symbols are rejected as `unsupported_symbol_kind`, since the
provider price-history endpoint serves underlyings, not option contracts),
frequency membership in the declared set (`unsupported_frequency`), period
membership in the per-frequency preset table (`unsupported_period`),
extended-hours applicability (D4). Missing data surfaces as
`history_unavailable` / `source_returned_no_candles`; transport failures as
`provider_unreachable` (retryable); 401/403 as `reauth_needed`. The response
envelope is the shared outcome/detail/retryable one (FR-009, C-02).

**Rationale**: mirrors the 010 validation and error taxonomy exactly; the
preset-table membership checks replace arithmetic bound checks because the
period is preset-based (D3). Option symbols are rejected at validation
rather than left to a provider error, keeping the fail-before-upcall
guarantee.

**Alternatives considered**:
- Accept option-contract symbols and let the provider answer — the provider
  does not serve option price history; failing locally is more deterministic
  and cheaper; rejected.
