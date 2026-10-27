# Changelog

A record of the progress of the `schwab-mcp` codebase.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and versioning is [SemVer](https://semver.org/): MAJOR for
incompatible changes, MINOR for a new feature, PATCH for fixes.

## [Unreleased]

### Added

- **MIT LICENSE**: the repository is now licensed under the MIT license
  (`LICENSE`, `license` and `license-files` metadata in `pyproject.toml`).
- **CI workflow** (`.github/workflows/ci.yml`): on every push to `master`
  and pull request, `uv sync && uv run pytest` runs the full suite with
  Python 3.11 pinned (matches the local development venv; the
  `filterwarnings = ["error"]` gate makes untested Python versions risky).

### Changed

- **Repository made public-ready**: removed the maintainer-only
  "Package for recipients" section from `README.md`; stopped tracking the
  regenerable `.codebase-memory/graph.db.zst` and `.codebase-memory/artifact.json`
  artifacts (now ignored); removed a stale `TODO` from the
  `_map_expirations` docstring in `src/schwab_mcp/options_chain.py`.
- **Documentation alignment for the public repository**: removed the
  "Release / distribution to recipients" row from the `README.md`
  documentation table (maintainer release docs remain in
  `docs/release-maintenance.md`, still linked from `AGENTS.md`); noted
  CI in `AGENTS.md` Commands; made the codebase-memory graph project
  reference path-independent in the constitution (Principle VI) and
  documented that the graph is a local, untracked artifact; removed the
  now-obsolete `.codebase-memory/.gitattributes`.
- **Unofficial disclaimer** in `README.md`: not affiliated with, endorsed
  by, or sponsored by Charles Schwab & Co., Inc.; read-only by design;
  API terms compliance is the user's responsibility.
- **Repository URL** in `docs/installation.md`: the `git clone` placeholder
  now points to `https://github.com/lautarobonetto/schwab-mcp.git`.

- **English-only migration** (Constitution v1.5.0, Principle VII): all
  documentation, Spec Kit artifacts (`specs/`, `.specify/assessments/`,
  `.specify/bugs/`), code comments, docstrings, and constraint quotes in
  error messages translated to English.
- **Documentation file renames** (Spanish filenames were non-compliant):
  `docs/instalacion.md` → `docs/installation.md`, `docs/uso.md` →
  `docs/usage.md`, `docs/release-mantenimiento.md` →
  `docs/release-maintenance.md`. All cross-file links updated.
- Data-model constraint quotes embedded in `OptionChainQuery` error
  messages and test docstrings now cite the English wording of
  `specs/008-extract-option-chain/data-model.md` verbatim.

## [0.6.3] - 2026-10-26

Feature 009 — **release packaging**: a single command to assemble a
complete, reproducible, and verifiable distribution package for
recipients who do not work with the repo.

### Added

- **`schwab-mcp-release build`** (maintainer-only,
  `src/schwab_mcp_release/`): produces `dist/schwab-mcp-<version>.zip` +
  `.zip.sha256` with the runtime wheel (`schwab_mcp` only), manuals
  in English, `install.sh`, `manifest.json` and `SHA256SUMS`, all under the
  wrapping `schwab-mcp-<version>/` directory. Normalized timestamps and
  member ordering + `SOURCE_DATE_EPOCH` for the wheel ⇒ byte-identical
  builds (FR-011). Guards: a dirty tree requires `--allow-dirty`
  (exit 2, `build_dirty` recorded in the manifest) and three checks before
  success — completeness (`MISSING:`/`UNEXPECTED:`), development
  material (`DEV-MATERIAL:`, included inside the wheel) and secrets
  (`SECRET:`, name only — never contents). Exit codes 0/1/2/3 by
  contract (`specs/009-mcp-release-packaging/contracts/`).
- **`docs/release/`**: five recipient manuals in English (README,
  installation, first-run-authentication, usage, troubleshooting) —
  Python ≥ 3.11 prerequisites, `install.sh` with actionable errors, auth
  with the user's own credentials, connecting an AI client, automatic
  renewal, in-place upgrade that preserves `~/.schwab-mcp/tokens.db`,
  and what to report / what to never share.
- **`install.sh`** (ships in the archive): Python ≥ 3.11 check, venv,
  bundled wheel install, verification via `schwab-mcp --help`;
  messages aligned with `manuals/installation.md`; never touches
  `~/.schwab-mcp/`.
- **`schwab-mcp --help`**: now shows the package version
  (source: package metadata — FR-005 visibility for the recipient).
- **`docs/release-maintenance.md`**: release instructions for the
  maintainer (build, checks, delivery workflow, reproducibility) and
  validation history. **`README.md`** (root): overview + pointers.
- **Tests** (`tests/unit/`): test_release_{version,allowlist,wheel,
  archive,manifest,checks,checks_dev_material,checks_secrets,cli,
  build_performance}.py, test_cli_version.py, test_install_script.py —
  full TDD, incl. performance < 60 s (SC-002) and no-leak tests for
  secret content.

### Fixed

- **Version desynchronization**: `pyproject.toml` lagged behind at
  `0.5.1` while the changelog recorded up to `0.6.3` — the release build
  stamps the version from `pyproject.toml` (single source, FR-005),
  so packages shipped with a version that did not match the
  release record. Aligned to `0.6.3`.
- **CHANGELOG**: removed the duplicate `0.3.0` entry (kept the
  one matching the actual test budgets: 12/20 KB, not
  the aspirational 8/16 KB); added the `[0.6.x]` link refs.
- **`docs/release/README.md`**: the checksum verification example
  no longer hardcodes a version (`schwab-mcp-<version>.zip: OK`).

## [0.6.2] - 2026-10-24

Documentation — anti-mistake guide for agents consuming
`get_option_chain` (findings from real usage).

### Added

- **`docs/tools.md` (`get_option_chain`)**: new section
  *Common invocation errors* with the 6 real pitfalls observed
  (plural `option_type` enum — singular `put`/`call` are rejected;
  `dte_max` is a ceiling and there is no `dte_min` — filtering DTE ≥ N is
  client-side post-processing; `dte_max: null` applies the 60-day ceiling;
  the `delta_target` window of ≤ 5 strikes per type requires multiple
  staggered calls to sweep the chain; `delta_target` is absolute
  \|delta\|; payload cost of `extended`). New section *Recipes*
  with correct invocations for common strategies (strangle legs by
  delta, put sweep for credit spreads).

## [0.6.1] - 2026-10-24

Bug fix — **`trade_time` epoch zero was reported as a 1970 trade**
(live finding during the tool's first real query, NOK).

### Fixed

- **`trade_time` for contracts that never traded**: the provider sends
  `tradeTimeInLong=0` (and `tradeTime=null`) for contracts that never
  traded; the epoch→ISO conversion showed them as
  `1970-01-01T00:00:00+00:00`, inventing a nonexistent timestamp.
  Epoch `0` (in either form of the field) is now reported
  as `null` in its column (FR-007: never invent data). In the
  live NOK query this affected 96 of 10,074 legs.

### Validation

- 2 regression tests (`tests/unit/test_options_chain_mapping.py`,
  `TestSerializeLeg`) reproduce the defect (direct epoch `0` and via
  the `tradeTimeInLong=0` fallback) and fail without the fix.
- Full suite: **989 tests**, 0 skipped, 0 failed.

## [0.6.0] - 2026-10-24

Feature 008 — **Option chain extraction with filters**
(spec: `specs/008-extract-option-chain/`).

### Added

- **Tool `get_option_chain`** (third MCP tool, read-only): extracts the
  option chain of an underlying in **a single invocation** (no
  pagination, FR-011), with optional bounding filters: `max_strikes`
  (default 50, per side of the money and per expiration), `option_type`
  (`both|calls|puts`, default `both`), `delta_target` (window of up to 5
  strikes per type around the contract with the closest |delta|;
  independent per type and not reduced by `max_strikes`), `dte_max`
  (default: current ceiling of 60 days) and `extended` (raw provider
  payload under `provider`).
- **Compact columnar schema**: per strike row, each leg as a positional
  array with a fixed order of 23 columns declared in `contract_fields`
  (all Greeks + technical values); missing field → explicit `null`
  (FR-006/FR-007); deterministic rounding to 2 decimals (prices) / 4
  (Greeks and IV); `trade_time` ISO-8601 UTC.
- **Structured states** (FR-009): `ok`/`chain_retrieved`,
  `no_options_listed`, `no_expirations_in_range` (current ceiling in
  `detail` and `filters` echo with `dte_max_effective`); filter
  validation **before** any upcall with actionable messages (FR-008);
  `ChainDataError` when an entire expiration has no data — error instead
  of a partial chain (FR-013).
- **Deterministic selection** (data-model §3): symmetric strike window
  around the ATM (≤ 2×`max_strikes` rows per expiration, ATM included,
  ties broken toward the lowest strike); delta window = anchor ± 2
  contiguous per type (≤ 5); DTE in calendar days with edge post-filter;
  internal `strikeCount` expansion (`max(limit, 100)` with
  `delta_target`, a single re-fetch at 200 when the target is not
  bounded).
- **Measurable budgets** (Principle V): ≤ **110,000 tokens** with
  defaults and < **6,000** with `delta_target` for the representative
  fixture (~12 expirations × 100 rows); latency ≤ 5 s p95.
  **Recorded adjustment**: the real measurement of the format (23
  columns per leg, ~80–88 tokens per row with both legs) yields
  ~95–106k / ~4.5–5k — above the 75k/3k of SC-002 — and the content of
  the response is fixed by FR-002/FR-006; the budgets were adjusted by
  user decision with justification in
  `specs/008-extract-option-chain/plan.md` (Complexity Tracking) and
  `docs/tools.md`.
- Audit: `options_chain_query_{start,success,failure}` events in the
  `log.py` taxonomy.

### Fixed (live findings 2026-10-24, with regression tests)

- `*ExpDateMap` keys with a suffix (`2026-10-23:-1`) normalized to
  `YYYY-MM-DD` (the previous parsing failed live).
- Expiration entries as strike-indexed lists
  (`{"737.0": [contract]}`) parsed in addition to the dict form.
- Provider HTTP 400 for symbols without options (`ZZZZZZ`) mapped to the
  structured state `no_options_listed` instead of a transport error.

### Validation

- Full suite: **975 tests**, 0 skipped, 0 failed (pre-feature baseline:
  842).
- Quickstart gates: unit 93, integration 30, performance 5.
- Live validation S1–S4 against the real provider (valid token): **24/24
  checks**, incl. SC-005 (per-type delta windows, one invocation per
  scenario). S1 SPY defaults: 1.4 s / ~67k tokens. Live note: SPY with 16
  expirations ≤60 DTE produces ~7.5k tokens with `delta_target` + both
  types (the <6,000 budget applies to the 12-expiration fixture).

### Changed (convergence, same date)

- **Re-baseline of the `delta_target` budget to ≤ 8,000 tokens** (T023,
  user decision): the live convergence measurement (SPY ~7,334,
  QQQ ~7,214, AAPL ~4,640, TSLA ~5,074 tokens) showed that wide
  16-expiration chains exceed the <6,000 ceiling; the 5-strike window
  per type applies per expiration (FR-004) and volume scales with the
  expirations within the DTE ceiling. Justification recorded in
  `specs/008-extract-option-chain/plan.md` (Complexity Tracking) and
  `docs/tools.md`; the budget test adds a wide-chain case
  (16 expirations) that pins the new ceiling.
- **Integer normalization in `serialize_leg`** (T024): `multiplier`
  arrives as a float from the live provider (`100.0`) and is now
  serialized as an integer (`volume`/`open_interest`/`multiplier`),
  without truncating non-integral values (regression test).
- **Test for the "source down" scenario** (T022): the integration suite
  pins the 5xx/408/429 path (quickstart S4): actionable
  `ConnectivityError`, `provider_unreachable` audit event, 1 upcall, no
  partial chain. Full suite after convergence: **987 tests**.

## [0.5.1] - 2026-10-24

Bug fix — **`get_transaction_history` labeled every trade as `CURRENCY_USD`**
(bug: `.specify/bugs/nok-symbol-filter-miss/`).

### Fixed

- **`symbol` of the movement in multi-leg trades**: in the real payload of
  `/transactions`, each TRADE carries in `transferItems` first the
  cash/commission legs (all with `instrument.symbol = "CURRENCY_USD"`,
  `assetType = CURRENCY`, non-None) and last the leg of the traded
  instrument. The mapper took the first item with a symbol → ~131 of 173
  real `trade` movements were labeled `CURRENCY_USD/CURRENCY`
  with an empty description, hiding the instrument. Consequence: the
  `symbol=X` filter (M1/M2/M3) never matched and the tool falsely
  claimed `no_movements_for_instrument` (e.g. 14 NOK option legs in the
  period were invisible). The mapper now curates the **first
  non-currency instrument** and only falls back to `CURRENCY_USD` for
  genuinely cash movements. `underlying_symbol` is derived from the
  corrected symbol.

### Validation

- 5 regression tests (`tests/unit/test_transactions_live_response.py`,
  multi-leg section) reproduce the real payload shape and fail without
  the fix. End-to-end live verification against the real provider: the
  bug's original query returns 14 NOK legs (pre-fix: 0) and the
  unfiltered sweep remains at 173 movements. Details:
  `.specify/bugs/nok-symbol-filter-miss/`.
- Full suite: **842 tests**, 0 skipped, 0 failed.

## [0.5.0] - 2026-10-24

Feature 007 — **Underlying-aware symbol filter and underlying reference
for options** (spec: `specs/007-underlying-symbol-filter/`).

### Added

- **Underlying-aware `symbol` filter**: `symbol="NOK"` returns
  **both** the movements recorded under `NOK` **and** the options
  whose OCC root is `NOK` (three matching forms: M1 registered symbol,
  M2 option root, M3 full OCC — data-model §2). Comparison
  **case-insensitive**; no fuzzy matching (substring does not match).
  The filter **no longer travels upstream** (research R1): it is
  applied locally after the sweep, guaranteeing subset-consistency by
  construction.
- **Dual filter validation (FR-003)**: if the instrument directory
  does not resolve the symbol, the tool **does not fail** — it
  proceeds with the sweep and only reports `instrument_not_found` if
  no movement matches in any form. This enables filtering by full OCC
  symbol (previously rejected by the provider with HTTP 400) and the
  `CURRENCY_USD` filter (previously `instrument_not_found`).
- **`underlying_symbol` in `MovementEntry`**: each option movement
  with an identifiable OCC exposes the underlying (unpadded root, e.g.
  `"NOK"` from `"NOK   261218P00011000"`). Field absent (excluded by
  `exclude_none`) for non-options and options without an identifiable
  OCC.

### Changed

- `src/schwab_mcp/transactions.py`: adds `_option_root()` and
  `movement_involves_filter()` (pure matching); `get_transaction_history`
  no longer sends `symbol` upstream (research R1), applies dual
  validation (FR-003) and filters locally before paginating;
  `map_provider_transactions` derives `underlying_symbol` for options.
  `validate_symbol()` is removed, dead after dual validation (its
  lookup logic now lives in `_symbol_resolved_in_directory()`, the
  single source of truth).
- `pyproject.toml`: package version aligned to 0.5.0.
- `docs/tools.md`: filter semantics updated (underlying + options,
  full OCC, case-insensitive, dual validation); `underlying_symbol`
  documented in the `MovementEntry` schema; options caveat
  replaced by the new behavior.
- `docs/CHANGELOG.md`: this entry.

### Validation

- Matching test: `_option_root()` with 12 cases (padding, no padding,
  short/long root, put/call, non-OCC, None, invalid) — all pass.
- Matcher test: `movement_involves_filter()` with 21 cases (M1/M2/M3,
  case-insensitive, no fuzzy, CURRENCY_USD, None filter) — all pass.
- US1 filter tests (31 tests): symbol not sent upstream, underlying
  filter includes options, full OCC, case-insensitivity,
  subset-consistency, pagination over filtering, dual validation
  (directory does not resolve + matches → ok; directory does not
  resolve + 0 matches → error), CURRENCY_USD, partial_failure with
  filter.
- `underlying_symbol` US2 tests (13 tests): present on options,
  absent on non-options, absent on unidentifiable OCC, extended
  unchanged, no secrets.
- Budget tests: worst case 50 options with `underlying_symbol`
  ≤ 16 KB default and ≤ 64 KB extended.
- Legacy tests updated: 3 tests adapted to the new semantics
  (symbol not sent upstream, dual validation).
- Full suite: **837 tests**, 0 skipped, 0 failed.

## [0.4.0] - 2026-10-23

Feature 006 — **Full movement history** (spec:
`specs/006-transaction-history/`).

### Added

- **`get_transaction_history` MCP tool**: retrieves the full movement
  history of all linked accounts in a date range (1
  `linked_accounts` + 1 `transactions` per account, with the complete
  list of the 15 upstream types comma-separated). Each movement is
  reported with a normalized category from a **closed enum**: `trade`,
  `transfer`, `dividend_or_interest`, `adjustment`, `other` (fallback
  for unknown types); `interest`, `dividend`, `fee` and
  `corporate_action` remain reserved with no upstream mapping in v1
  (the provider reports dividends and interest as a single
  indistinguishable type).
- **Input schema and filters**: `start_date` / `end_date` required
  (`YYYY-MM-DD`, inclusive bounds, interpreted in America/New_York) with
  validation before any upcall: range ≤ 1 year (366 days), `end_date` ≥
  `start_date`, `end_date` not in the future, `offset` ≥ 0; `symbol`
  optional to filter by instrument (validated against the provider via
  `instruments(..., "symbol-search")` — nonexistent symbol → error
  `instrument_not_found`, not an ambiguous empty); `extended: bool =
  false` for on-demand extended detail.
- **Upstream cap of 3000 movements**: range split by bisection with
  deduplication by `(account_hash, activityId)` — no silent truncation
  and no duplicates.
- **Structured output (`TransactionsResult`)**: contains `outcome`
  (`ok` · `partial_failure` · `transient_failure` · `reauth_required`),
  `detail` (`history_retrieved` · `no_movements` ·
  `no_movements_for_instrument` · `account_failed` ·
  `provider_unreachable` · `reauth_needed`), `retryable`,
  `retrieved_at`, `total_count`,
  `movements` (array of `MovementEntry`), `returned`, `has_more`,
  `next_offset`/`offset_echo` (explicit pagination of 50 movements per
  page, ascending chronological order with tie-breaking by
  `account_hash` and `activityId`), and `accounts_failed` (only in
  `partial_failure`, with `provider_error`/`transient` per account —
  explicit partial result, never accounts silently dropped).
- **Each movement (`MovementEntry`)**: `account_hash` (opaque, never an
  account number), `occurred_at` (ISO-8601), `category` (closed enum),
  `description` (truncated to 80 characters in default mode), `amount`,
  `currency` (default `"USD"`, no conversion), and optionally `symbol`,
  `instrument_type` and `extended` (only with `extended=true`: original
  provider type, full description, `fees`, `commissions`, `netAmount`,
  `settlementDate`, `transferItems`, `activityId`).
- **No internal retries** on transient failure:
  `transient_failure/provider_unreachable` is reported with
  `retryable=true` on the first attempt, so the agent applies its own
  playbook.
- **Error mapping**: consistent with the rest of the server
  (`ConnectivityError`→`transient_failure`,
  `ReauthorizationRequiredError`→`reauth_required`, per-account
  errors→`partial_failure`).
- **Audit**: `transactions_query_start` event → terminal
  `transactions_query_success` (ok/partial) or
  `transactions_query_failure` (transient/reauth/validation) on stderr,
  no secrets and no unredacted provider text.
- **Documentation**: MCP tool contract, data model, audit events
  and checklist in `specs/006-transaction-history/`. Full tool
  section in `docs/tools.md`.

### Fixed

- **Live SDK response handling** (found in manual testing against
  the real API 2026-10-23): the `schwabdev` client returns
  `requests.Response` — the orchestration unwraps the JSON body via
  `schwab_mcp.provider.response_json` (single source of truth,
  reusable by other tools) and classifies HTTP statuses (401/403 →
  reauth, 5xx/408/429 → transient, remaining 4xx → `provider_error` per
  account). Without this, every live invocation failed with
  `AttributeError` despite a green suite (the fakes returned dicts).
- **Real payload shape**: `linked_accounts()` uses `hashValue` (not
  `accountHash`); `transactions` responds with a JSON list at the top
  level (not `{"transactions": [...]}`); the timestamp lives in `time`
  (not `transactionDate`); the instrument travels inside
  `transferItems[].instrument` with `assetType`. The mapper accepts
  both shapes.
- **Dates for the provider**: the API rejects raw `YYYY-MM-DD`
  (`'2026-09-01' is not a valid value for startDate`); bounded
  ISO-8601 datetimes are sent in America/New_York (midnight to 23:59:59
  local, real DST offset) — inclusive bounds per spec.
- **Instrument search projection**: the SDK validator requires
  `symbol-search` (lowercase); `SYMBOL_SEARCH` was rejected.
- **Actionable errors on the MCP channel**: validation errors and
  `instrument_not_found` are converted to `ToolError` at the tool
  boundary (`get_transaction_history_tool`), so the actionable message
  reaches the agent instead of the generic SDK text (FR-009d, SC-005).
- **`SCHWAB_CALLBACK_URL` with trailing slash** (found live 2026-10-24):
  the Schwab developer portal may **require** the trailing slash on the
  registered callback (without it the app enters an error state and
  cannot be submitted for approval), while `schwabdev` rejects callbacks
  ending in `/`. `load_config()` now normalizes the value (strips
  trailing slashes), so both forms work without touching the
  app registration.
- **`get_open_positions` live** (bug `positions-response-unwrap`,
  2026-10-24): the tool failed on every real invocation for three
  chained reasons — the SDK returns an unparsed `requests.Response` (now
  unwrapped with `schwab_mcp.provider.response_json`, the same source of
  truth as 006), the real payload is a top-level list of
  `{aggregatedBalance, securitiesAccount}` (not the assumed
  `accountDetails` dict), and the account identifier is now the opaque
  provider `hashValue` cross-referenced by `accountNumber` with
  `linked_accounts()` (the truncated local SHA-256 hash of the account
  number was removed). **Breaking**: the
  `account_hash` values change — they are now consistent with
  `get_transaction_history`. Additionally, real OPTION instruments do
  not carry `strikePrice`/`expirationDate`: they are derived from the
  OCC symbol.

### Changed

- `src/schwab_mcp/server.py`: registers `get_transaction_history` via
  `mcp.add_tool(...)` with a wrapper that hides `client` from the MCP
  input schema.
- `src/schwab_mcp/transactions.py` (new): Pydantic models
  (`MovementEntry`, `TransactionsResult` with data-model cross-validation
  rules), enums (`MovementCategory`, `ProviderTransactionType`),
  `map_provider_transactions` mapping, per-account orchestration,
  query validation, symbol validation, bisection at the 3000 cap and
  offset pagination.
- `src/schwab_mcp/log.py`: adds the transactions events
  (`transactions_query_start`, `transactions_query_success`,
  `transactions_query_failure`) to the audit vocabulary.
- `docs/tools.md`: documents `get_transaction_history`, filters,
  categories, pagination, guarantees and error mapping.
- `docs/CHANGELOG.md`: this entry.

### Validation

- Registration test: the tool appears in `list_tools()` with the exact
  name.
- Empty-result test: `movements: []` with `outcome: ok` and
  `detail: no_movements`.
- Category test: each of the 15 upstream types maps to the correct
  closed-enum category; unrecognized types→`other`.
- Pagination test: chronological order, pages of 50, full walk
  (offset 0→50→100) without duplicates or omissions; `total_count`
  stable.
- Bisection test: responses at the 3000 cap trigger a range split;
  merge without duplicates or omissions.
- Date validation test: range > 366 days, `end < start`, malformed or
  future dates, `offset < 0` rejected before any upcall.
- Symbol filter test: only movements of the requested symbol;
  nonexistent symbol→`instrument_not_found`; without `symbol`, zero
  `instruments` upcalls.
- Error test: each upstream error class produces the correct `outcome`
  (transient on the first attempt, re-auth, partial failure per
  account).
- Event test: exactly one `transactions_query_start` + one terminal
  event per invocation.
- No-secrets test: neither the result nor the events contain tokens,
  app keys or account numbers.
- Budgets: p95 latency ≤ 5 s and default page ≤ 16 KB (extended
  ≤ 64 KB) in `tests/performance/test_transactions_budgets.py`.
- Full suite green (735 tests, 0 skipped).

## [0.3.0] - 2026-10-20

Feature 003 — **List Open Positions** as the first real MCP tool
(spec: `specs/003-list-open-positions/`).

### Added

- **`get_open_positions`** (MCP tool, US1 — MVP): first tool
  registered via `MCPServer.add_tool`. Retrieves all effective holdings
  of all linked accounts in a single upstream call
  (`account_details_all(fields="positions")`). Self-classifying
  structured result (`PositionsResult`) with curated per-position
  fields (`symbol`, `instrument_type`, `quantity` with sign,
  `average_price`, `market_value`, `unrealized_pl`, `price_timestamp`).
  Failure classification: `transient_failure` (network/provider),
  `reauth_required` (expired/corrupted auth). No internal retries
  (FR-007). Audit
  `positions_query_start` → `positions_query_success`/`positions_query_failure`
  on every invocation (FR-014).
- **Full per-position metadata (US2)**: `unrealized_pl` derived
  with sign (research D3), conditional option fields
  (`underlying_symbol`, `put_call`, `strike_price`, `expiration_date` for
  `assetType=OPTION`), and `extended=true` for passthrough of additional
  provider fields (FR-003a). Measurable budgets: ≤ 5 s
  latency, ≤ 12 KB default (50 positions), ≤ 20 KB extended.
- **Per-account failure isolation (US3)**: detection of individual
  errors in `accountDetails` → `partial_failure` with
  `accounts_failed` and positions from the successful accounts (FR-010).
  Cross-cutting secrets verification: all result forms
  (`ok`, `empty`, `partial`, `transient`, `reauth`) confirmed free of
  authentication data and raw account numbers (FR-008).

### Changed

- `src/schwab_mcp/positions.py` (new): Pydantic models
  (`PositionEntry`, `PositionsResult`, `AccountFailed`) with cross-validation;
  `map_provider_positions` mapping function and `get_open_positions`
  orchestration.
- `src/schwab_mcp/server.py`: registers the `get_open_positions` tool via
  `MCPServer.add_tool`.
- `src/schwab_mcp/log.py`: adds the positions events
  (`positions_query_start`, `positions_query_success`,
  `positions_query_failure`) to the audit vocabulary.
- `docs/tools.md`: full documentation of the tool, its invocation,
  results, and error mapping.
- `docs/CHANGELOG.md`: this entry.

## [0.2.0] - 2026-10-19

Feature 002 — **Automated token renewal** for unattended AI
agents (spec: `specs/002-automated-token-renewal/`).

### Added

- **`schwab-mcp renew`**: explicit non-interactive renewal with a
  classified result in one JSON line (≤ 300 bytes) and exit codes
  `0/2/3/6/7` — the agent distinguishes success, `not_needed`, transient
  failure (retryable) and `reauth_required` (human action) without
  interpreting free text.
- **`schwab-mcp auth-status`**: authentication health check in
  one request — state (`valid`/`reauth_required`), remaining lifetime
  of the access and refresh tokens. Strictly local read, no network,
  ≤ 2 s; never triggers renewals.
- **Outcome classification** (`renewal.py`): `RenewalOutcome` /
  `AuthHealth` types with closed enums (`renewed|not_needed|
  transient_failure|reauth_required`), compact serialization and zero
  secrets.
- **Transparent automatic path (US1)**: every authenticated operation
  with validity below the preventive margin (61 s, provided by
  schwabdev) renews on its own, without a browser or interaction; the
  shape of the operation's result does not change.
- **Renewal audit events**: `renew_start` →
  `renewal_success`/`renewal_failure` on stderr, with trigger
  `margin_trigger` (automatic) or `explicit_command` (CLI), no secrets.
- **Detectable "reauthorization required" state (US3)**: when the
  refresh token is rejected, all paths report the same consistent
  classification and bound attempts against the provider
  (no retry storms).
- **Guide for AI agents**: `docs/tools.md` — detailed reference of
  the agent-consumable interface.

### Changed

- `retry_once` generalized to `retry_call(fn, retries=2)` in
  `tokens.py`: the project's single bounded-retry implementation
  (DRY), reused by startup validation and renewal.
- `server.py`: startup validation uses the generalized retry and
  emits renewal lifecycle events.

### Fixed

- **ISO-8601 regression** in the lifetime reader: schwabdev stores
  `*_token_issued` as ISO text (`2026-10-19T22:00:27.004577+00:00`),
  not as a numeric epoch; the reader did `float - str` and crashed with
  exit 1. It now parses ISO (assuming UTC when the zone is missing),
  tolerates numeric epochs and degrades to `reauth_required` on
  unparseable timestamps instead of crashing. Covered with regression
  tests against the real DB schema.

### Validation

- 294 tests passing, 0 skipped (performance gate ≤ 10 s and
  token-usage gate ≤ 300 bytes included).
- Manual smoke verified: `renew` (`not_needed` exit 0),
  `auth-status` (`valid` exit 0), config fail-fast (exit 2).

## [0.1.0] - 2026-10-19

Feature 001 — **Schwab OAuth access layer** (spec:
`specs/001-schwab-oauth-access/`).

### Added

- **`schwab-mcp auth`**: interactive one-shot authorization with a
  paste-the-redirect-URL flow (owner's browser + paste of the redirect
  URL). No input sockets.
- **`schwab-mcp serve`**: headless stdio MCP server with proactive
  access validation at startup (< 5 s). Registers 0 tools in this
  version (reserved for future features).
- Local SQLite **token store** (via schwabdev 4.0.0) at
  `~/.schwab-mcp/tokens.db` with `0o600` permissions.
- **Error taxonomy** with actionable exit codes per failure type
  (configuration, authorization, store, connectivity) — no tracebacks.
- **Redaction filter** in logs: app secret, tokens and authorization
  codes never appear in output.
- **Authorization lock** to prevent concurrent runs.
- Documentation: `docs/installation.md`, `docs/usage.md`; spec
  artifacts in `specs/001-schwab-oauth-access/`.
- Test suite (unit/integration/performance) with TDD gates.

[0.6.3]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.6.2...v0.6.3
[0.6.2]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lautarobonetto/schwab-mcp/releases/tag/v0.1.0