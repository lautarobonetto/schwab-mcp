# Changelog

A record of the progress of the `schwab-mcp` codebase.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and versioning is [SemVer](https://semver.org/): MAJOR for
incompatible changes, MINOR for a new feature, PATCH for fixes.

## [Unreleased]

### Fixed

- **`auth_event` stderr timestamps are standard ISO-8601 again, and the
  secret-redaction loop lives in one place** (bug TD-013, 2026-11-04):
  `log.py:170` appended `.replace("+00:00", "Z+00:00")` to the
  `isoformat()` output, so every event line carried a malformed
  `Z+00:00` hybrid suffix that `datetime.fromisoformat()` rejects
  (e.g. `2026-11-04T12:00:00Z+00:00`). The suffix is now the plain
  `+00:00` offset produced by `isoformat()`, matching the
  `utc_now_iso()` contract already established in `positions.py` and
  `transactions.py` (which explicitly document "no non-standard
  `Z+00:00` suffix"). The duplicated redaction loop in `auth_event` was
  replaced by a shared `_redact(text)` helper also used by
  `_RedactionFilter.filter` (identical longest-first semantics). Two
  unit tests that codified the broken format (`ISO_8601_UTC_RE`
  requiring `Z` before an offset, and `test_timestamp_contains_z`) were
  rewritten; a `datetime.fromisoformat` regression test pins the fix.
  Example event lines in `docs/tools.md` and the event contracts
  (`specs/001`, `specs/002`, `specs/006`) were corrected.
  Assessment and fix report: `.specify/bugs/td-013/`.

### Changed

- **Spec Kit tooling upgraded from 1.2.3 to 1.3.0**: the `specify` CLI (uv
  tool) and the in-repo scaffolding (`.specify/`, OpenCode commands) are
  re-rendered at 1.3.0. The core `/speckit.taskstoissues` command was
  removed upstream (moved to the `github` extension) and its orphaned
  OpenCode command file deleted. The `roadmap` extension's pinned copy
  still references `speckit.taskstoissues` in its workflows; it tracks
  its own pinned version and was not re-rendered.

## [0.9.8] - 2026-11-04

### Fixed

- **`renew()` no longer risks a `RuntimeError: release unlocked lock` or
  parallel duplicate renewals under in-process concurrency** (bug TD-001,
  2026-11-04): the per-store coordination in `renewal.py` used a
  non-blocking acquire that, on contention, blocked-and-released inside
  the helper and returned `False` — so a waiter whose store was still
  expired proceeded to renew **without holding the lock**, and its
  `finally` released a lock it did not own (raising `RuntimeError` when
  the lock was free, or silently releasing another thread's lock). The
  coordination is now a single blocking critical section
  (`with _store_lock(store_path):`) that re-checks the store margin
  **inside** the lock and returns `not_needed` when another thread's
  renewal already refreshed it; `_acquire_store_lock` /
  `_release_store_lock` were deleted, making the FR-005 single-flight
  invariant structural. Behavior change under contention: a waiter that
  still finds an expired store now performs its own serialized renewal
  instead of renewing unlocked. Cross-process exclusion is unchanged
  (file-based `AuthLock` in the CLI). Pinned by a threaded regression
  test (no exception escapes `renew()`, `update_tokens()` calls never
  overlap) plus a deterministic sequential-renewal test.

### Changed

- **`tokens.py` store move-aside sequence de-duplicated** (tech debt
  TD-011, 2026-11-04): `backup_token_store` and
  `quarantine_corrupt_store` each repeated the same algorithm — status
  guard, timestamped collision-free `<name>.<suffix>.<stamp>[-<n>]`
  naming, `os.rename`, `os.chmod(0o600)`, `_drop_sidecars(src)` —
  differing only in the filename suffix and the required prior store
  status. A shared `_move_store_aside(path, suffix, required_status)`
  is now the single home of that sequence; the two public functions are
  three-line wrappers (`("bak", "present")` / `("corrupt",
  "corrupted")`) keeping their docstrings and return contracts, and the
  `_backup_timestamp` test patch seam is unchanged. Behavior-preserving:
  the existing backup/quarantine suites passed unchanged. Full suite
  green (1819 passed, 0 skipped). Assessment and fix report:
  `.specify/bugs/td-011/`.
- **`price_history.py` failure-event pattern de-duplicated** (tech debt
  TD-010, 2026-11-04): `get_price_history` repeated the same
  5-argument selection tuple `(normalized, frequency, period,
  extended_hours, extended)` across seven `_fail(...)` call sites and
  composed the audit-event detail `f"{detail} " + _selection_detail(...)`
  at seven sites, and the `ConnectivityError` handler duplicated the
  reauth/unreachable branches. The selection is now bound once by a
  `fail(detail, **extra)` closure created immediately after symbol
  normalization; `_fail_event(detail, ...)` is the single home of the
  detail composition; the connectivity handler collapses to one
  emission path via a `(state, reason, envelope)` lookup; the success
  event composes through the same path. Behavior is byte-identical
  (verified by a differential harness running the pre-refactor and
  post-refactor implementations side by side over 15 failure/success
  scenarios: identical events, envelopes and raised errors). One
  assessment claim was rejected during triage: the success event never
  logged a "raw" symbol — `_selection_detail` normalizes internally, so
  all events already logged the same normalized symbol. Net −28 lines;
  audit-event names, detail strings and envelopes unchanged. Full suite
  green (1819 passed, 0 skipped). Assessment, fix report and
  verification: `.specify/bugs/td-010-price-history-fail-dry/`.
- **Client-shim installation centralized in `build_schwab_client()`**
  (tech debt TD-012, 2026-11-04): the trailing-slash callback shim was
  installed by a pre-construction ritual at three entry points
  (`cli.run_auth`, `cli._do_run_renew`, `server.run_serve`), even though
  `client.py` is the declared single construction point — a future
  fourth entry point forgetting the ritual would silently reproduce the
  callback-trailing-slash bug. The install now happens inside
  `build_schwab_client()` itself (the shim is idempotent via its
  `_SHIM_MARKER` guard), the three call sites and their imports were
  deleted, and the factory guarantee (timeout + shim) is pinned by a new
  factory test. Behavior-preserving on the happy path. Full suite green
  (1820 passed, 0 skipped). Assessment and fix report:
  `.specify/bugs/td-012-client-shim-install/`.
- **Symbol grammar unified in `schwab_mcp.symbols`** (tech debt TD-009,
  2026-11-04): two definitions of "valid symbol" coexisted — the quotes
  grammars (`quotes.py`, declared single source of truth and already
  reused by `price_history.py`) and an ad-hoc "non-empty, no internal
  whitespace" check in `OptionChainQuery.validate()`. The grammars moved
  to a new shared module `schwab_mcp.symbols` (`classify_symbol` with
  public `INDEX_RE`/`EQUITY_RE`/`OPTION_RE`/`canonical_option_symbol`);
  `quotes.py`, `price_history.py` and the option tools all consume it.
  `OptionChainQuery.validate()` now classifies its raw symbol through
  the tolerant `classify_underlying()` wrapper (provider-internal slash
  form `BRK/B` and lowercase accepted; empty/whitespace messages
  unchanged) and rejects off-grammar symbols (e.g. `AAPL!`) and
  option-contract symbols with an actionable `ValueError` before any
  upcall — they previously passed local validation and surfaced the
  provider's HTTP 400 as a misleading `no_options_listed`. TDD (red
  confirmed first). Full suite green (1819 passed, 0 skipped).
- **`options_chain.py` internal duplication consolidated** (tech debt
  TD-008, 2026-11-04): the option-chain and expiration-chain tools had
  re-implemented the same provider semantics side by side — HTTP-400
  "no options listed" sniff, `underlying_price` extraction, the
  `no_expirations_in_range` detail string, `date.fromisoformat` with
  fallback-to-`None` (each expiration date parsed twice), a dead
  `payload` parameter in `_result_meta`, and the delta strikeCount
  expansion with the body-limit degradation buried two try levels deep
  in the orchestrator; `leg_maps` was built twice from the same payload
  (divergence risk). Shared helpers now own each pair
  (`_is_no_options_response`, `_underlying_price`,
  `_no_expirations_detail`, `_parse_expiration_date`);
  `build_chain_result` builds `leg_maps`/`underlying_price` once and
  passes them into `_map_expirations`; `_result_meta(query)` dropped the
  unused parameter; the delta expansion and degradation live in the new
  `_fetch_chain_payload(client, query)`. The error-mapping try/except
  blocks remain explicit near-duplicates (KISS / rule of three) with
  mutual cross-references. Behavior-preserving: outcomes, result shapes
  and `detail` strings are byte-identical — the shared detail string is
  pinned verbatim by tests on both paths, and each expiration date is
  parsed exactly once. Full suite green (1811 passed, 0 skipped).
- **Shared result taxonomy extracted to `schwab_mcp.results`** (tech debt
  TD-002, 2026-11-04): `positions.py` and `transactions.py` had each
  re-implemented the same self-classifying result shape (outcome enum,
  detail values, `AccountFailed` model, and the outcome↔field
  cross-validation rules with word-for-word identical error messages).
  Both modules now consume one definition from the new `results.py`
  (`ResultOutcome` aliased as `OutcomeType`/`TransactionOutcome`, shared
  `DETAIL_*` constants, one `AccountFailed`, shared validator for rules
  4–5) and keep only their feature-specific rules. The wire format is
  unchanged: enum values, accepted vocabulary, and validation messages
  are byte-identical to before (pinned by 25 new tests in
  `tests/unit/test_results_shared_taxonomy.py`, including a
  cross-module message-parity drift guard); the only visible tightening
  is that `TransactionsResult` account-failure `detail` now rejects
  non-enum strings it already never documented.
- **Token-store SQLite read consolidated** (tech debt TD-003,
  2026-11-04): the read-only store-read block (`os.stat` → empty-file
  check → `mode=ro` connect → query → close) existed three times across
  `tokens.py` and `renewal.py`, with `peek_store_status` and
  `read_store_lifetime` running the identical `schwabdev` query. The
  single implementation is now the private
  `tokens._read_schwabdev_row(path)` helper (tri-state
  absent/corrupted/present), consumed by `peek_store_status` and
  `read_store_lifetime`; the bool `peek_store()` helper was deleted
  (internal only — no CLI or tool-interface change) and its two `auth`
  call sites use `peek_store_status(...) == "absent"` instead.
  Behavior-preserving on all reachable states; pinned by tri-state and
  equivalence tests in `tests/unit/test_tokens.py`.
- **Result envelopes and the tool `ToolError` boundary unified** (tech
  debt TD-004, 2026-11-04): the four result-envelope builders existed
  twice — `quotes.py` (no `symbol`) and `price_history.py` (with a
  `symbol` field) carried near-verbatim copies of `_validation_error`,
  `_provider_unreachable`, `_reauth_needed` (+`_history_unavailable`).
  They are now shared `tool_errors.validation_error` /
  `provider_unreachable` / `reauth_needed` / `history_unavailable`
  builders with an optional `symbol: str | None = None` that is omitted
  from the envelope when absent; emitted dicts are byte-identical to the
  pre-dedup shapes (pinned by parity tests in
  `tests/unit/test_quotes_mapping.py` /
  `tests/unit/test_price_history_mapping.py`). The `get_quotes_tool` and
  `get_price_history_tool` wrappers also stopped hand-rolling the
  boundary mapping (`except (ValueError, TypeError) → ToolError`) and now
  route `AuthError` taxonomy errors through the shared
  `tool_errors.raise_classified_tool_error` like the transactions and
  option-chain wrappers, so a `ConnectivityError` /
  `ReauthorizationRequiredError` escaping the market-data domains
  surfaces as `provider_unreachable:` / `reauth_needed:` instead of the
  SDK's opaque `UnexpectedToolError` (pinned in
  `tests/unit/test_tool_error_classification.py`). Expected-failure
  envelopes on the normal path are unchanged (the domains still convert
  provider failures into structured results, per contracts/mcp-tools.md).
- **`get_transaction_history` result construction consolidated** (tech
  debt TD-005, 2026-11-04): the ~330-line orchestrator in
  `transactions.py` repeated each result shape two or more times —
  reauth/transient blocks ×2 with duplicated `__cause__` inspection, two
  "ok, no movements" sites, two output-equivalent `partial_failure`
  branches, and the page size 50 hard-coded in three places (paginator,
  validator rule 2, `returned` field description). Result construction is
  now single-definition: module-level `PAGE_SIZE` consumed by all three
  sites, shared `_classify_connectivity_cause` / `_reauth_result` /
  `_transient_result` / `_empty_ok_result` helpers, one
  `if failed_accounts:` branch (the all-failed case yields identical
  pagination values via `_paginate([])`), plus extracted `_paginate`,
  `_fetch_account_movements` and `_account_hash` helpers, and validator
  rule 7 parses each `occurred_at` once. The function drops from 333 to
  224 lines; emitted results are unchanged (pinned by the existing
  outcome/pagination suites plus the new
  `TestPageSizeConsistency` drift guard in
  `tests/unit/test_transactions_query.py`).
- **`TestDteCeiling` fixtures anchored to the fixed capture date** (test
  suite only): the two `dte_max` ceiling tests built expiration dates from
  the wall clock (`chain_expiry_date` without an explicit base) while
  asserting DTE values pinned to `TODAY = 2026-11-03`, producing off-by-one
  DTE failures starting 2026-11-04. All `TestDteCeiling` fixtures now pass
  `today=TODAY` explicitly, matching the convention used elsewhere in the
  suite; assertions unchanged, full suite green again.
- **Tool registration and CLI dispatch deduplicated** (tech debt TD-006,
  2026-11-04): `server.py` repeated a ~15-line wrapper-closure +
  manual-`__name__` + `register_tool` ceremony per tool (×6) and
  `cli.py` repeated the same `try / except AuthError / except
  Exception / else sys.exit(0)` mapping per command (×4). Registration
  is now one `_register_bound_tool(mcp, client, fn, name=...,
  description=...)` call per tool, binding the client with
  `functools.partial` — deliberately not `functools.wraps`, whose
  `__wrapped__` would leak `client` into the advertised input schema
  (pinned by the new `tests/unit/test_tool_registration.py`, which also
  locks the six tool names, byte-for-byte descriptions, and
  client-passing); CLI dispatch is now a `_COMMAND_RUNNERS` table with
  one `_run_command` mapping (and `_run_auth_command` keeping auth's
  distinct concurrent/cancelled handling and its deliberate lack of a
  generic `except Exception`), pinned by
  `tests/unit/test_cli_dispatch.py`. Emitted schemas, descriptions,
  exit codes, and audit events are unchanged; full suite green.

- **Positions pipeline computed each value once** (tech debt TD-007,
  2026-11-04): `positions.py` computed `unrealized_pl` three times per
  pipeline run (in `_transform_provider_payload`, in the consolidation
  map, and at `PositionEntry` construction) while only the last was
  ever read — a future multiplier/rounding change in one site would
  have silently diverged the others. The two dead computations are gone
  (single computation at entry construction), the transform layer
  reuses `_collect_extended` instead of an inline duplicate, the
  defensive timestamp override in `get_open_positions` (re-assigning
  values already propagated via the payload) is removed, and the dead
  `retrieved_at` parameter of `_detect_account_failures` was dropped.
  All `PositionsResult` constructions now pass `ResultOutcome` /
  `DetailType` / `AccountFailureDetail` enum members instead of raw
  strings, and the partial-failure path builds its result in a single
  `map_provider_positions` call via new `outcome` / `detail` /
  `accounts_failed` / `retryable` parameters — replacing the old
  mutate-after-validate flow that could bypass the shared outcome rules
  (pydantic v2 does not validate post-hoc assignment, so
  `accounts_failed` entries survived as raw dicts). Emitted values are
  unchanged (str enums serialize identically); pinned by a rewritten
  transform test, new mapping-level outcome-parameter tests, and a new
  orchestration-level partial-failure test class; full suite green.

- **Constitution amended to v1.6.0 — graph-first enforcement**:
  Principle VI (Graph-First Code Discovery) existed since v1.4.0 but was
  violated end-to-end during the TD-010 cycle (the graph was indexed but
  never queried; blast radius and duplication hunts ran on raw grep).
  The amendment closes the compliance gaps rather than re-declaring the
  principle: Principle VI gains an enforcement block (absolute priority
  for structural questions, with
  `.opencode/rules/graph-first-discovery.md` as the operational
  reference; session-start/compaction index verification via
  `list_projects`/`index_status` with declared evidence tiers
  Scout/Verify/Auditor; claim discipline via `get_code_snippet` +
  `check_index_coverage`, no absence/exhaustiveness claims from Scout);
  the Index Currency Rule is now bidirectional (refresh after changes
  AND freshness verification before consuming evidence; passive
  warehouse usage explicitly does not satisfy it); new quality gate 9
  (evidence-tier gate). No principle added, removed, or redefined.

### Removed

- **Repomix packing configuration**: deleted `repomix.config.json`,
  `.repomixignore` and the git-ignored `repomix-output.xml` snapshot,
  plus all textual references (`.gitignore` entry,
  `docs/development.md` setup paragraph, stale
  `mcp-repomix` package and `repomix` MCP-server entries in
  `.specify/extensions/roadmap/apm.lock.yaml` and the roadmap
  extension's `.gitignore`). Repomix was never actually load-bearing:
  codebase-memory-mcp indexes the working tree directly (watch
  strategy `git`), and the snapshot was git-ignored, so it never
  entered the graph. The graph was re-indexed after the removal;
  `search_code` confirms zero residual `repomix` mentions.

## [0.9.7] - 2026-11-03

### Fixed

- **`docs/tools.md` no longer claims `get_option_chain` can never return
  expirations with `dte > 60`** (documentation-only, no code change): the
  agent guidance wrongly stated a "hard ceiling is 60 days", but 60 is
  only the **default ceiling** applied when `dte_max: null` — an explicit
  `dte_max` (any integer ≥ 1, no hard upper limit) raises the ceiling to
  that value, exactly as `OptionChainQuery.dte_max_effective` and the
  008 contract implement it. Confirmed live: `dte_max: 90` on `$SPX`
  returned an expiration with DTE 73 (2026-11-03). The guidance now
  points to `filters.dte_max_effective` as the verifiable applied
  ceiling. Document version field bumped 0.8.0 → 0.9.7 (the field had
  drifted behind the doc updates shipped since 0.9.0).

## [0.9.6] - 2026-11-03

### Fixed

- **The `get_option_expiration_chain` settlement-type documentation now
  covers every observed provider value** (bug `settlement-type-a`,
  2026-11-03): a live `$SPX` expiration chain returns `settlement_type`
  `B` on the near-term standard monthly expirations (2026-11-20 …
  2027-03-19) in addition to `A` (farther monthlies) and `P` (weeklies)
  — `B` was absent from the documented value set in `docs/tools.md` and
  the spec-012 data-model/research/quickstart. `settlement_type` stays a
  verbatim provider pass-through by design (no normalization); the docs
  now mark the observed set (`C`, `P`, `A`, `B`) as **non-exhaustive**
  and instruct consumers never to branch on a closed enum. `A`/`B` both
  denote AM (open) index settlement per the observed date patterns (the
  letter split is not documented by Schwab). Pinned by a new unit test
  asserting a `B` value passes through unmodified.
- **Unknown tool arguments are now rejected with a loud validation error
  instead of being silently ignored** (bug `option-chain-dte-filter`,
  2026-11-03): the MCP SDK validates tool arguments against a Pydantic
  model built with the default `extra='ignore'` behaviour, so a
  misspelled or hallucinated argument — e.g. `expiration_date` passed to
  `get_option_chain`, which has no such parameter — was silently dropped
  and the tool answered a *different* question with `outcome: ok` (the
  reported case fetched the chain at the default 60-DTE ceiling and
  returned `ok` with the requested 73-DTE expiration simply absent,
  indistinguishable from "no such expiration"). All six registered tools
  now go through the shared `server.register_tool` hardening: the SDK's
  per-tool argument model is rebuilt with `extra='forbid'` (server-side
  rejection naming the offending argument) and the advertised input
  schema sets `additionalProperties: false` (conforming clients reject
  the call before it is sent). Known arguments are unchanged and a
  missing required argument still errors as before. Tool registration
  was extracted into `server._register_tools` so the hardening is pinned
  by unit tests at the real registration path. `docs/tools.md` documents
  the strict-argument behavior.

## [0.9.5] - 2026-11-03

### Fixed

- **Auth-taxonomy errors now surface to MCP clients with an actionable,
  classified message** (bug `domain-errors-swallowed`, 2026-11-03): when a
  tool raised `ConnectivityError` or `ReauthorizationRequiredError`
  (e.g. the `$SPX` timeout case), the MCP SDK wrapped it into the opaque
  `UnexpectedToolError("Error executing tool <name>")` and the client saw
  only `isError: true` with that text — the actionable message reached
  stderr only. The affected tool wrappers (`get_option_chain`,
  `get_option_expiration_chain`, `get_transaction_history`) now convert
  the auth taxonomy into a `ToolError` via the new shared
  `schwab_mcp.tool_errors.raise_classified_tool_error` helper, with a
  client-visible classification prefix: `provider_unreachable:` for
  `ConnectivityError` (retryable) and `reauth_needed:` for
  `ReauthorizationRequiredError` (run `schwab-mcp auth`), so clients can
  distinguish retryable from auth-required from bad request. The
  original exception is preserved as `__cause__`. Validation errors were
  already surfaced this way and are unchanged; `get_open_positions`,
  `get_quotes` and `get_price_history` already returned structured
  envelopes for these states and are unchanged.
- **`delta_target` with negative values (put targets, e.g. `-0.35`) no
  longer produces wrong strike windows or spurious re-fetches** (bug
  `delta-target-sign-bracketing`, 2026-11-03): the bracketing check and
  the delta anchor compared `abs(delta)` values against the **raw**
  negative target, so (1) every negative-target payload was classified
  "not bracketed", always triggering the internal `strikeCount=200`
  ceiling re-fetch, and (2) the window anchored on the deepest-OTM
  contract instead of `|delta| ≈ |target|` — silently wrong strikes
  reported as `outcome: ok` on every symbol. Both computations now use
  `|delta_target|`; positive-target behavior is unchanged and the
  `filters` echo keeps the signed value as passed.
- **`get_option_chain` no longer aborts on the provider response-body
  limit** (bug `spx-chain-body-limit`, 2026-11-03, observed live on
  `$SPX`): the `strikeCount=200` ceiling re-fetch exceeds Schwab's API
  gateway body limit — the backend assembles the response for ~44 s and
  rejects it with `502 {"fault":{"faultstring":"Body buffer overflow",
  "errorcode":"protocol.http.TooBigBody"}}`, which was misclassified as
  transient `ConnectivityError`. The fault is now detected and raised as
  `ProviderBodyLimitError` (a `ChainDataError`): with `delta_target` the
  ceiling re-fetch degrades to the last successful window (research R2:
  closest contracts to the target; audit event
  `options_chain_query_degraded` detail=`provider_body_limit`), and an
  explicit oversized `max_strikes` surfaces as an actionable
  `ChainDataError` naming the limit. Genuine transient 502s (without the
  fault marker) still map to `ConnectivityError`. `docs/tools.md`
  documents the new source-error row and audit event.

## [0.9.3] - 2026-11-03

### Fixed

- **`get_option_chain` with `delta_target` no longer times out on
  `$SPX`** (bug `spx-delta-timeout`, 2026-11-03): the schwabdev client
  was constructed without a request `timeout`, so the library's 10 s
  default applied. The `delta_target` path fetches with
  `strikeCount = max(max_strikes, 100)` and re-fetches at up to 200
  strikes when the target is not bracketed; a full `$SPX` chain at that
  size exceeds 10 s at Schwab's API, producing a deterministic
  `ReadTimeout` → `ConnectivityError` (reproduced 4/4 live, while
  equities/ETFs and `$XSP` worked). All three client construction sites
  (`serve`, `auth`, `renew`) now build the client through the shared
  `schwab_mcp.client.build_schwab_client` factory, which forwards
  `timeout=Config.request_timeout`. The timeout is configurable via the
  new `SCHWAB_MCP_REQUEST_TIMEOUT` environment variable (positive
  integer seconds, default `60`); invalid values fail fast with
  `InvalidConfigError` (exit 2). `docs/installation.md` and
  `specs/001-schwab-oauth-access/contracts/configuration.md` document
  the new variable.

## [0.9.2] - 2026-11-03

### Fixed

- **`renew`/`serve` no longer report phantom `renewal_success` when the
  refresh token is revoked server-side** (bug `renew-phantom-success`,
  2026-11-03): the tie-breaker probe and the `serve` startup validation
  treated any non-raising `linked_accounts()` call as success, but
  schwabdev client methods return `requests.Response` objects and an
  HTTP 401 does not raise — so a revoked token set was classified as
  `renewed` (exit 0) with nothing written to the store. Both paths now
  classify the response status through the shared
  `provider.response_json` unwrapper (401/403 → `reauth_required`,
  5xx/408/429 → `transient_failure`). A probe-derived `renewed` outcome
  is additionally verified against the store: a fresh store read is
  required, otherwise the result is `reauth_required` with the new
  `renewal_unverified` detail.
- **`renew`/`serve` classify stores with unparseable timestamps as
  `store_corrupted` instead of crashing** (bug
  `store-unparseable-timestamps`, 2026-11-03): a structurally valid
  SQLite store whose `access_token_issued`/`refresh_token_issued` values
  are not ISO-8601 text (e.g. numeric epoch values, observed live during
  manual testing) passed the peek and crashed inside schwabdev's client
  construction — `renew` exited 1 with a raw `Invalid isoformat string`
  error and `serve` exited 2 with the misleading "Fix the values in your
  environment" config message. `peek_store_status` now validates the
  loader contract (issued timestamps must be ISO-parseable text), so
  `renew` exits 3 with `detail: store_corrupted`, `serve` exits 5
  (`TokenStoreCorruptedError`), `auth` quarantines the store and
  proceeds, and `auth-status` reports `reauth_required` — all through
  the existing corrupted-store paths.

### Changed

- `auth` now warns on stderr (and in the `auth_success` event detail)
  that completing an authorization revokes the token sets of every
  other installation sharing the same app key (Schwab allows only one
  active token set per app key + user); `docs/usage.md` documents the
  one-token-set rule and the store-lifetime-only limitation of
  `auth-status`.

## [0.9.1] - 2026-11-03

### Fixed

- **`get_open_positions` no longer ignores the option contract multiplier
  in `unrealized_pl`** (bug `option-upl-multiplier`, 2026-11-03): the P/L
  was computed as `marketValue - averagePrice × quantity`, but
  `marketValue` is already dollarized (includes the ×100 contract
  multiplier) while `averagePrice` is the per-unit quote price — the
  cost-basis term was understated ×100 for every option position, wrong
  on all options and able to flip the sign of winning short legs (live
  evidence: XSP 805C short reported −$183.13 instead of +$200.34; SPX
  7705P short reported −$21,093.76 instead of −$6,616.29). The formula is
  now `marketValue - averagePrice × quantity × multiplier` with
  `multiplier = 100` for `assetType == "OPTION"`, `1` otherwise; equities
  are unchanged. Regression tests pin the live-observed SPX/XSP figures
  (short leg, long leg, sign-flip case) at the mapping and
  transform-payload levels.

## [0.9.0] - 2026-11-03

Sixth MCP tool `get_option_expiration_chain` (feature 012): the upcoming
option expirations of one underlying — expiration date, DTE (calendar
days), settlement type — in one cheap call, with the `get_option_chain`
DTE-ceiling semantics (MINOR bump per SemVer).

### Added

- **`get_option_expiration_chain` tool (feature 012)**: sixth MCP tool
  registered by `schwab-mcp serve` — the ordered list of upcoming option
  expirations of **exactly one underlying** per invocation (expiration
  date, DTE in calendar days, settlement type), curated-first with no
  strikes, quotes, or greeks. `dte_max` behaves exactly like
  `get_option_chain` (≥ 1 replaces the 60-day default ceiling, no hard
  upper limit) and is echoed as `filters.dte_max_effective`;
  `dte_max: null` applies the 60-day default, verifiable in the same
  echo. Structured empty outcomes follow the shared envelope:
  `no_expirations_in_range` (retryable; `detail` names the effective cap)
  and `no_options_listed` (the live HTTP-400 shape for underlyings with no
  listed options). Same-date entries (e.g. SPX AM/PM settlement) are kept
  as separate rows distinguished by `settlement_type` — never merged —
  and missing provider fields surface as explicit `null` (values are
  never invented, entries never silently dropped). `extended=true` adds
  the raw provider payload beside the curated list. Reuses the 008
  validated query (`OptionChainQuery`), fetch plumbing, outcome envelope,
  and ToolError pattern — no second surface; exactly one provider call
  per invocation (SC-004). Budgets (Principle V): ≤ 1,000 tokens for the
  curated default response, test-enforced on a dense 60-entry worst-case
  fixture, and ≤ 5 s p95 latency. Audit events
  `expiration_chain_query_start` / `expiration_chain_query_success` /
  `expiration_chain_query_failure` (no credentials in any output). The
  provider field-name fixture was first pinned from best-available
  evidence (the token store needed `schwab-mcp auth`), then **confirmed
  and corrected against the live endpoint on 2026-11-03** (T019): the
  list key is `expirationList` (not `expirations`), `status` is `null`
  with no `errorCode` key, and the curated field names
  (`expirationDate`, `daysToExpiration`, `settlementType`) are
  live-confirmed; `daysToExpiration` verified as calendar days. Docs: tool
  section in `docs/tools.md`; contract and data model in
  `specs/012-option-expiration-list/`.

## [0.8.2] - 2026-11-03

### Fixed

- **Corrupt store no longer blocks `auth` in a dead-end loop** (bug
  `auth-corrupt-store-blocked`, 2026-11-03): a corrupted token store
  (unreadable, missing the expected table, or shadowed by a hot SQLite
  journal left by an interrupted flow) made `schwab-mcp auth` exit 5
  with "Store treated as absent; run schwab-mcp auth" — a message that
  circularly pointed back at the failing command, permanently blocking
  recovery. `auth` now quarantines the unusable file (renamed to
  `tokens.db.corrupt.<UTC timestamp>`, chmod 600, content preserved for
  forensics, stray `-journal`/`-wal`/`-shm` sidecars removed), emits
  `auth_start` with detail `corrupt store quarantined: <file>`, and
  proceeds with the fresh authorization flow. Exit 5 remains only when
  the file cannot even be renamed. Backup/restore also drops stray
  SQLite sidecars so a restored store is never shadowed by a foreign
  hot journal. `serve` keeps its fail-fast exit 5.

## [0.8.1] - 2026-11-03

### Fixed

- **`auth` no longer reports success on dead tokens** (bug
  `auth-false-success`, 2026-11-03): with an existing store whose
  refresh token was revoked server-side (`invalid_grant`),
  `schwab-mcp auth` previously skipped the browser flow entirely —
  schwabdev's init-time silent refresh failed, the stale rows survived,
  and the CLI printed "Authorization successful" on unusable
  credentials. `auth` now always performs a full re-authorization: the
  existing store is moved to a `tokens.db.bak.<UTC timestamp>` sibling
  backup (chmod 600) before the client is constructed, restored
  byte-identically on any failure or cancellation (FR-010), and
  discarded on success. Success additionally requires evidence of a
  fresh write during the run (hook ran or store content changed),
  never merely the presence of pre-existing rows. This repairs the
  recovery loop `renew` → `reauth_required` → "run: schwab-mcp auth".

## [0.8.0] - 2026-11-02

Fifth MCP tool `get_price_history` (feature 011): OHLCV candles for
one symbol per invocation, with named period presets under a global
260-candle ceiling (MINOR bump per SemVer).

### Added

- **`get_price_history` tool (feature 011)**: fifth MCP tool
  registered by `schwab-mcp serve` — OHLCV candles for **exactly one
  symbol** per invocation (equity/ETF or index grammar;
  option-contract symbols rejected at validation). Declared frequency
  set `5m` / `15m` / `30m` / `1h` / `daily` / `weekly` (default
  `daily`), each with its own set of **named period presets** (default
  `1m`); the global ceiling of **260 candles** per invocation holds
  **by construction** — every preset's worst case is at or below it
  and there is no truncation path. `extended_hours=true` is an opt-in
  restricted to intraday frequencies (`daily`/`weekly` reject it with
  `extended_hours_not_applicable`); `1h` candles are aggregated 2:1
  from 30-minute provider data. The still-forming candle is marked
  `in_progress` (at most one per response); `window` and
  `candle_count` report the covered span so agents can judge coverage
  without counting, and `extended=true` adds the complete raw provider
  payload beside the curated candles. Fail-before-upcall validation
  (`malformed_symbol`, `unsupported_symbol_kind`,
  `unsupported_frequency`, `unsupported_period`,
  `extended_hours_not_applicable`), no partial data
  (`history_unavailable`), and the shared result envelope / error
  taxonomy of the existing tools (`provider_unreachable`,
  `reauth_needed`). Budgets (Principle V): ≤ ~650 tokens by default
  (22 daily candles; measured 588), ≤ ~6,500 tokens worst case
  (260 candles; measured ~6.3k), ≈ 23–24 tokens per curated candle,
  and ≤ 5 s p95 latency — token-usage and performance tests enforce
  all of these. The plan's research D5 arithmetic (550 / 5,200 /
  19–22 per candle) predated the mandatory `in_progress` field on every
  candle; the ceiling itself (260) is structural and unchanged. New
  module `src/schwab_mcp/price_history.py`; audit events
  `price_history_query_start` / `price_history_query_success` /
  `price_history_query_failure` (no credentials in any output).
  Live-captured fixtures pinned the provider's stamping conventions
  (research D8): intraday candles at period start, daily candles at
  05:00 UTC, weekly candles at the week's opening Monday — weekly
  labels are relabelled forward to the closing session (Friday) so
  FR-019 holds. Validated live (quickstart S1–S6 against the real API).
  Docs: tool section in `docs/tools.md`; contract and data model in
  `specs/011-price-history-ohlcv/`.

### Fixed

- **Class-share symbols resolve at the provider** (bug
  `dot-class-symbols-unresolved`, 2026-11-03): symbols with an
  embedded dot denoting the share class (`BRK.B`, `HEI.A`, `BF.B`,
  `LEN.B`) passed validation in both `get_quotes` and
  `get_price_history`, but the provider resolved none of them —
  quotes answered `not_found` and price history returned
  `history_unavailable`, and the hyphen spelling was rejected by the
  grammar, leaving class shares unreachable. A controlled live probe
  (2026-11-03) established that the provider resolves class shares
  only in slash form (`BRK/B` → candles and quotes; `BRK-B`, `BRK B`,
  `brk.b`, and padded forms → empty). The equity branch of
  `_classify` (`src/schwab_mcp/quotes.py`, the shared symbol source
  of truth) now rewrites the dotted agent-facing form to the slash
  form at the upcall, and `get_price_history`
  (`src/schwab_mcp/price_history.py`) sends that provider form
  instead of the raw normalized symbol. Everything agent-facing is
  unchanged: envelopes, echoes, and error keys keep the requested
  dotted form, and the input grammar is untouched (`BRK-B` and
  two-dot spellings still `malformed_symbol`). Documented in
  `docs/tools.md` (both symbol-grammar sections) and the feature
  010/011 contracts. Tests:
  `tests/unit/test_quotes_validation.py` (classification mapping and
  quotes-upcall pin), `tests/unit/test_price_history_validation.py`
  (provider-form upcall with preserved echo).

- **OAuth authorization with trailing-slash callbacks**: the
  compatibility shim for `schwabdev`'s callback validation restored the
  exact registered URL only *after* client initialization, but
  `schwabdev` runs its whole interactive flow *inside* initialization —
  the printed authorize URL and the token exchange used the
  slash-stripped spelling and could never match the portal
  registration (Schwab compares `redirect_uri` character for
  character). The shim now restores the exact value before the in-init
  flow, so `schwab-mcp auth` completes when the portal-registered
  callback is `https://127.0.0.1/`.

## [0.7.1] - 2026-11-02

### Fixed

- **`SCHWAB_CALLBACK_URL` preserves the exact configured value**
  (bug `callback-trailing-slash`, 2026-11-02): the previous
  `.rstrip("/")` normalization could produce a `redirect_uri`
  mismatch at the authorize step — Schwab compares the
  `redirect_uri` character for character against the developer-portal
  registration, and the portal may REQUIRE the trailing slash
  (`https://127.0.0.1/`; some apps enter an error state without it).
  `load_config()` now strips surrounding whitespace only and preserves
  the value verbatim. Because `schwabdev` 4.0.0 (latest on PyPI)
  rejects callbacks ending in `/`, a runtime compatibility shim
  (`src/schwab_mcp/schwabdev_compat.py`, installed by `auth`, `renew`,
  and `serve` before the client is constructed) relaxes only that
  validation — a single trailing `/` passes and the exact value is
  stored for authorize/exchange; `//` is still rejected; the shim
  fails loudly if a future schwabdev changes the internals it relies
  on. The shim lives in the package, so it survives `uv sync`
  (patching the vendored library file did not). Tests:
  `tests/unit/test_config.py` (trailing slash preserved),
  `tests/unit/test_schwabdev_compat.py`.

## [0.7.0] - 2026-10-27

Fourth MCP tool `get_quotes` (feature 010): real-time quotes with
curated compact output, plus the spec roadmap, Spec Kit 1.2.3, the
OpenCode agent-rules migration, and a documentation refresh
(MINOR bump per SemVer).

### Added

- **`get_quotes` tool (feature 010)**: fourth MCP tool registered by
  `schwab-mcp serve` — current quotes for 1..20 distinct symbols
  (equity/ETF, index, and option-contract kinds) in one invocation:
  last price, bid/ask, volume, net change (absolute and percent),
  quote freshness, and last-trade time, keyed by symbol. Curated-first
  (≤ 250 tokens per single quote, ≤ 2,500 for a 10-symbol batch, ≤ 5 s
  p95 latency — budget tests enforce both) with an `extended=true`
  passthrough of the complete raw provider payload. Freshness
  (`data_state`: `realtime` / `delayed` / `closed`) is derived
  deterministically from one market-hours check per invocation plus the
  provider's live flags — never guessed. Fail-before-upcall validation
  for the three symbol-kind grammars (20-distinct limit, de-duplication
  of option-contract aliases), no partial data (`quote_unavailable`
  with per-symbol `not_found` attribution), and the shared result
  envelope / error taxonomy of the existing tools
  (`validation_error`, `quote_unavailable`, `provider_unreachable`,
  `reauth_needed`). Audit events `quotes_query_start` /
  `quotes_query_failure`; no credentials or account identifiers in any
  output (FR-010). New module `src/schwab_mcp/quotes.py`; the
  epoch-milliseconds → ISO-8601-UTC trade-time normalization is now
  shared (`schwab_mcp.provider.trade_time_value`, used by 008 too).
  Docs: `docs/tools.md` gains the `get_quotes` section (document
  version 0.7.0).

- **Spec roadmap** (`.specify/memory/roadmap.md`, v1.0.0): new
  project-level governance artifact beside the constitution capturing
  project direction — vision and end states (autonomous trading-analysis
  capability, full coverage of the read-only `schwabdev` surface,
  derived-analysis tools, invariant agent contract), cross-cutting
  constraints and decisions (C-01…C-09, including the read-only surface
  decision C-06: `place_order`/`preview_order` are explicit scope-out,
  and the source-of-truth split with the FMP MCP, C-08), and the
  planned-specs ledger: 010 quotes, 011 price history, 012 option
  expiration list, 013 market hours, 014 instrument search, 015
  portfolio risk snapshot, 016 spread analysis (`planned`); 017 IV
  context, 018 transaction-chain reconstruction, 019 event-proximity
  join, 020 market movers, 021 order status (`undecided`).
- **Spec Kit roadmap extension**: installed
  `.specify/extensions/roadmap/` (config, templates, scripts) and the
  four OpenCode commands `speckit.roadmap.write`, `speckit.roadmap.sync`,
  `speckit.roadmap.brief`, and `speckit.roadmap.debrief`
  (`.opencode/commands/`) for creating/amending the roadmap and syncing
  it with spec lifecycles.

### Changed

- **Spec Kit updated to 1.2.3** (CLI via `uv tool upgrade specify-cli`,
  project templates via `specify init --here --force`): prerequisite
  and plan-setup scripts now fail with a clear error when
  `plan.md` or the plan template would be empty instead of creating an
  empty file (`check-prerequisites.sh`, `setup-plan.sh`); the
  `/speckit.taskstoissues` OpenCode command is marked deprecated in
  favor of the bundled `github` extension
  (`/speckit.github.taskstoissues`); local integration packages and
  the consent registry (`integrations/packages/`, `packages.json`) are
  git-ignored via `.specify/.gitignore`; `.specify/init-options.json`
  records `speckit_version: 1.2.3`. Constitution and spec/plan/tasks
  templates preserved unchanged.
- **Agent rules migrated from Claude Code to OpenCode**: moved
  `.claude/rules/filter-before-fetch.md` to
  `.opencode/rules/filter-before-fetch.md` (frontmatter removed —
  OpenCode instructions are plain markdown) and removed the `.claude/`
  directory. The new project `opencode.jsonc` declares
  `instructions: [".opencode/rules/*.md"]` so OpenCode loads the rule
  alongside `AGENTS.md`.
- **Documentation refresh for the fourth tool and live-verified examples**:
  `README.md` now lists all four read-only tools (`get_quotes` added to
  the tools table, the "what you can do" list, a batch-quotes example,
  and a corrected "no streaming or historical market data" statement —
  `get_quotes` is a point-in-time snapshot, not a streaming feed);
  expired option-contract example dates (`251127` — November 2025)
  were replaced with live-verified November-2026 forms (`261127`) in
  `README.md`, `docs/tools.md`,
  `specs/010-real-time-quotes/{quickstart,data-model,contracts/mcp-tools,research}.md`;
  and `docs/tools.md` gained a troubleshooting tip for the most common
  `not_found` cause on option contracts (a stale `YYMMDD` year portion,
  e.g. `251127` vs `261127`), pinned by the
  `index-option-root-grammar` bug investigation
  (`.specify/bugs/index-option-root-grammar/`).

## [0.6.4] - 2026-10-27

Public repository launch: license, CI, disclaimer, and documentation
alignment for the open-source release. No runtime code changes.

### Added

- **MIT LICENSE**: the repository is now licensed under the MIT license
  (`LICENSE`, `license` and `license-files` metadata in `pyproject.toml`).
- **CI workflow** (`.github/workflows/ci.yml`): on every push to `main`
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
  app registration. *(Reversed in Unreleased — stripping caused a
  `redirect_uri` mismatch; see `callback-trailing-slash`.)*
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

[0.8.0]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.7.1...v0.8.0
[0.8.1]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.8.0...v0.8.1
[0.8.2]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.8.1...v0.8.2
[0.7.1]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.6.4...v0.7.0
[0.6.4]: https://github.com/lautarobonetto/schwab-mcp/compare/v0.6.3...v0.6.4
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