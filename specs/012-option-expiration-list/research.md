# Research: Option Expiration List (`get_option_expiration_chain`)

Feature 012 — Phase 0 output. Resolves every open question from the
spec/plan before design. Evidence tiers: live probe attempts on this
machine (2026-11-03), installed `schwabdev` 4.0.0 source, public API
documentation, and the indexed codebase graph.

## R1 — Provider SDK surface (CONFIRMED)

**Decision**: wrap `schwabdev.Client.option_expiration_chain(symbol:
str) -> requests.Response`, which issues `GET /marketdata/v1/expirationchain?symbol=…`
(verified in the installed SDK source, `client.py` lines 499–511).

**Rationale**: reuse-before-creation (C-03) — the SDK method exists, takes
exactly one symbol, and takes no filter parameters; the DTE ceiling must
therefore be applied **client-side after fetch** (the payload is tiny, so
this does not violate the filter-before-fetch rule, which exists to bound
heavyweight payloads).

**Alternatives considered**:
- Deriving the expiration list from the full `option_chains()` payload
  (spec 008's endpoint): rejected — heavyweight (5k–110k tokens), defeats
  the entire purpose (SC-001); C-09 curated-first requires the cheap
  endpoint.
- Direct HTTP call without the SDK: rejected — C-03 reuse-before-creation,
  and `schwabdev_compat` / retry machinery is already wired around the SDK.

## R2 — Provider response shape (PARTIALLY CONFIRMED — defensive mapping)

**Decision**: map defensively. Treat the payload as
`{"status": …, "errorCode": …, "expirations": [ {…}, … ]}` and read from
each entry: `expirationDate` (YYYY-MM-DD string), `daysToExpiration` (int),
`settlementType` (provider string; observed `"C"`/`"P"`/`"A"`/`"B"` —
non-exhaustive, letters pass through verbatim). Any missing
field yields explicit `null` in the curated output — values are never
invented (008's FR-007 pattern). Unknown/extra provider fields surface only
via `extended=true`.

**Evidence**:
- schwabdev endpoint confirmed (R1).
- Public OpenAPI stub (apis.io `charles-schwab-options-api-openapi.yml`,
  saved to `tmp/options-api-openapi.yml`) declares the operation but no
  response schema.
- Community consumers (R wrapper docs; elkingarcia11/schwab-options-api-client)
  read `expiration['expirationDate']` and `expiration['daysToExpiration']`;
  the R wrapper documents "expiration dates, expiration types, settlement
  types" in the response.
- **Live probe attempt 2026-11-03**: inconclusive — the MCP's own
  `renew`/`auth-status` report the token store valid, but a raw
  `schwabdev` session against the shared token DB gets 401/`invalid_grant`
  (the MCP's token machinery differs from a bare SDK session). Probing
  further into credential internals was stopped deliberately (credential
  safety).
- **Live probe re-attempt 2026-11-03 (T002, implementation phase)**:
  capture still impossible — the same probe run through the MCP's own
  machinery (`load_config` + `install_trailing_slash_callback_support` +
  the shared token store) answers 401/`invalid_grant`, and the configured
  Schwab MCP returns `reauth_needed` for plain quote calls. The stored
  refresh token is expired/revoked server-side; a human must run
  `schwab-mcp auth` before any live capture can succeed. **T002 fallback
  applied**: the fixture module
  `tests/unit/fixtures/expiration_chain_payloads.py` was pinned from the
  best available evidence above and flagged for re-capture.
- **Live capture CONFIRMED 2026-11-03 (T019, after `schwab-mcp auth`
  renewed the store)**: the probe succeeded (HTTP 200) and the fixture
  module now pins the live payload verbatim. **Field-name corrections
  applied** (update-only-the-mapping rule, research R2): the top-level
  list key is **`expirationList`** (not the candidate `expirations`), the
  wrapper is `{"expirationList": [...], "status": null}` with **no
  `errorCode` key**, and the raw entry fields are `expirationType`
  (`W`/`S`), `optionRoots` and `standard` (not the candidate
  `isStandardOptions`/`optionDeliverables`/`lastTradingDay`). The curated
  candidate set is **confirmed live**: `expirationDate` (YYYY-MM-DD),
  `daysToExpiration` (int — live values are calendar days: 2026-11-04 was
  reported as 1 on 2026-11-03, matching R4's local computation), and
  `settlementType` (live `"P"` for AAPL equity options). The re-capture
  flag is **cleared**.

**Consequence for tasks**: implementation MUST start with a task that
captures one live payload and pins the exact field names in a **committed
fixture module** at `tests/unit/fixtures/expiration_chain_payloads.py`
(the established convention — see `quotes_payloads.py`,
`price_history_payloads.py`); the mapping's first failing test is written
against that fixture. If a field name differs from the candidate set, the
mapping and fixture are adjusted together — the curated schema
(`expiration_date`, `dte`, `settlement_type`) does not change. If the
capture is temporarily impossible (invalid tokens), the fixture is pinned
from the best available evidence and flagged for re-capture before the
final commit gate (tasks.md T018).

**Alternatives considered**:
- Hard-coding field names without a live fixture: rejected — silent
  `null`s across the whole output would violate "never invent data" and
  the empty-case outcomes.
- Blocking planning until a live capture succeeds: rejected — the curated
  contract is stable regardless of provider field naming; capture is an
  implementation-phase task.

## R3 — Reuse of spec 008 building blocks (CONFIRMED)

**Decision**: reuse, do not duplicate:
- `OptionChainQuery(symbol=…, dte_max=…)` as the validated input: with its
  defaults (`max_strikes=50`, `option_type="both"`, `delta_target=None`)
  its `validate()` always passes for the unused fields, so it provides
  symbol validation (type/non-empty/no internal whitespace), `dte_max ≥ 1`
  validation, and `dte_max_effective` (60 default, provided value ≥ 1
  replaces it — identical to spec 008 FR-005) with zero new validation
  code.
- The shared `outcome`/`detail`/`retryable` envelope and
  `no_expirations_in_range` outcome (008, FR-008 of this spec).
- `retry_call` + `response_json` for the upcall (shared unwrapping and
  error taxonomy — 008 `fetch_option_chain` pattern).
- `_result_meta` (`symbol`, `generated_at`) unchanged.
- The `get_option_chain_tool` ToolError pattern for the tool wrapper.

**Rationale**: C-02 (single source of truth) and C-03; graph evidence
(`get_file_outline` of `src/schwab_mcp/options_chain.py`) confirmed all
pieces exist and are importable within the same module.

**Alternatives considered**:
- A new `ExpirationChainQuery` dataclass: rejected — duplicates symbol and
  `dte_max` validation for no behavioral gain (KISS, C-04).
- A new module `option_expirations.py`: rejected — same-domain code with
  shared semantics belongs in one module; a split would either duplicate
  helpers or force shared-helper extraction churn in 008 code.

## R4 — DTE semantics and same-date entries (CONFIRMED)

**Decision**: DTE is calendar days from today to `expirationDate`
(008 data-model definition). The provider's `daysToExpiration` is NOT
reused for filtering: computing DTE locally from the date keeps one
definition across both tools (the provider's day count may differ, e.g.
trading days). Same-date entries (SPX morning/afternoon settlement) are
kept as separate entries distinguished by `settlement_type`; deduping by
date is forbidden (spec clarification 2026-11-03, option B).

**Rationale**: SC-005 (semantics indistinguishable from
`get_option_chain`); clarification Q2 of this feature.

**Alternatives considered**: trusting provider `daysToExpiration` —
rejected (second DTE definition, DRY violation).

## R5 — Token budget and serialization shape (CONFIRMED with a measured plan)

**Decision**: curated entries as compact objects
`{"expiration_date": "2026-11-06", "dte": 3, "settlement_type": "C"}`
≈ 13 tokens each (measured as `len(json.dumps(result, separators=(",", ":")))/4`,
the repo's established estimator). Worst realistic case: an index
underlying with near-daily expirations — ~60 entries inside the 60-day cap
≈ 800 tokens + envelope, within the < 1,000 budget (SC-001). The budget
test uses a dense fixture (60 entries) as the worst case, not a
representative mid-size one.

**Rationale**: C-05 — the budget must hold at the worst case; a
representative fixture would flatter the number (008's budget test
comment warns exactly this).

**Alternatives considered**: positional arrays (008's `CONTRACT_FIELDS`
style) if the dense measurement exceeds budget — kept as the recorded
fallback; switching requires a Principle V justification entry, not a
silent schema change.

## R6 — Error and empty-case mapping (CONFIRMED)

**Decision**:
- Validation errors (`ValueError`/`TypeError`) → structured validation
  error before any upcall (reuse 008 semantics; the tool wrapper converts
  to `ToolError`).
- Provider HTTP 400 after validation → "no options listed" non-retryable
  outcome with `expirations: []` (008 found live 2026-10-24 that the
  provider rejects non-optionable symbols with 400 — the same mapping
  applies here).
- All expirations beyond the effective ceiling → `no_expirations_in_range`
  retryable outcome with `dte_max_effective` in the detail.
- Connectivity/auth failures → shared taxonomy
  (`ConnectivityError`, `ReauthorizationRequiredError`) unchanged.
- Malformed/expired entries (e.g., unparseable date) → entry skipped is
  FORBIDDEN; a whole-payload parse failure surfaces the provider error;
  individual unparseable dates surface explicit `null` fields rather than
  silent drops (never-invented-data rule).

**Rationale**: FR-007/FR-008 + C-02 (one envelope, one taxonomy).

## R7 — Registration and docs (CONFIRMED)

**Decision**: register in `src/schwab_mcp/server.py` with the identical
wrapper-function pattern used for `get_option_chain` (lines 191–221 of
`server.py`): wrapper sets `__name__`/`__qualname__`, `mcp.add_tool` with a
one-line description pointing at `extended`. Update `docs/tools.md` (new
tool section) and `docs/CHANGELOG.md` in the delivery commit (constitution
Commit Discipline).

**Alternatives considered**: none — the pattern is established five times
(003/006/008/010/011).