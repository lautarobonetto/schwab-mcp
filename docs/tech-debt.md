# Technical Debt Backlog

Working backlog of KISS/DRY violations found in a full audit of `src/`
(2026-11-04). Items are resolved one at a time; update the **Status**
column as each item lands. Line numbers refer to the state of the code at
audit time and may shift as fixes merge — re-verify before editing.

TD-019–TD-034 come from a **second audit pass** (2026-11-04, after
v0.9.9) covering the DRY/KISS debt TD-001–TD-018 did not reach —
including the `tests/` tree, whose duplication had never been audited.
Structural evidence for TD-019/TD-024 was cross-checked against the
codebase-memory knowledge graph (`SIMILAR_TO` edges among the affected
functions).

Per the project constitution, every fix follows TDD: write the failing
test first (Red → Green → Refactor). Bug fixes (marked **BUG**) start
with a regression test that reproduces the defect. Affected `docs/`
pages are updated in the same commit.

## Summary

| ID | Priority | Type | Area | Status |
|----|----------|------|------|--------|
| TD-001 | High | KISS + BUG | `renewal.py` renewal lock | Fixed (v0.9.8, 2026-11-04) |
| TD-002 | High | DRY | Outcome/detail taxonomy duplicated across modules | Fixed (v0.9.8, 2026-11-04) |
| TD-003 | High | DRY | SQLite token-store read triplicated | Fixed (v0.9.8, 2026-11-04) |
| TD-004 | High | DRY | Error envelopes and tool `ToolError` boundary divergent | Fixed (v0.9.8, 2026-11-04) |
| TD-005 | High | DRY | Result construction repeated in `get_transaction_history` | Fixed (v0.9.8, 2026-11-04) |
| TD-006 | High | DRY | Tool registration boilerplate x6; CLI dispatch x4 | Fixed (v0.9.8, 2026-11-04) |
| TD-007 | Medium | DRY/KISS | `positions.py` transform remaps itself | Fixed (v0.9.8, 2026-11-04) |
| TD-008 | Medium | DRY | `options_chain.py` internal duplication (x7) | Fixed (v0.9.8, 2026-11-04) |
| TD-009 | Medium | DRY | Two symbol-validation grammars in the package | Fixed (v0.9.8, 2026-11-04) |
| TD-010 | Medium | DRY | `price_history.py` failure-event pattern repeated manually | Fixed (v0.9.8, 2026-11-04) |
| TD-011 | Medium | DRY | Store backup/quarantine: same algorithm twice | Fixed (v0.9.8, 2026-11-04) |
| TD-012 | Medium | DRY | Client-shim installation scattered across 3 entry points | Fixed (v0.9.8, 2026-11-04) |
| TD-013 | Medium | DRY + BUG | `log.py` redaction duplicated; malformed timestamp | Fixed (v0.9.8, 2026-11-04) |
| TD-014 | Medium | DRY | Release: member list hardcoded twice | Fixed (v0.9.8, 2026-11-04) |
| TD-015 | Medium | DRY | Release: duplicated validation and except-clones in `cmd_build` | Fixed (v0.9.8, 2026-11-04) |
| TD-016 | Low | Dead code | Dead parameters in helpers | Fixed (v0.9.9, 2026-11-04) |
| TD-017 | Low | Dead code | Unused imports and members | Fixed (v0.9.9, 2026-11-04) |
| TD-018 | Low | KISS | Obscured imports and misc readability | Fixed (v0.9.9, 2026-11-04) |
| TD-019 | High | DRY | OCC symbol parsing triplicated (`symbols`/`transactions`/`positions`) | Fixed (v0.9.11, 2026-11-04) |
| TD-020 | High | DRY | Transactions test fakes x5, `_validator` x3, 15-types literal (tests) | Open |
| TD-021 | High | KISS | `positions.py`: payload crosses 3 shapes before mapping | Open |
| TD-022 | Medium | DRY | `ConnectivityError` cause classification written 3x | Open |
| TD-023 | Medium | DRY | `utc_now_iso()` duplicated; UTC-timestamp convention x4 | Open |
| TD-024 | Medium | DRY | Five `*_tool` wrappers repeat the same boilerplate skeleton | Open |
| TD-025 | Medium | DRY/KISS | `retry_call` used without retries at 13/14 sites; manual retry in `renewal` | Open |
| TD-026 | Medium | KISS | `TransactionsResult` validator: outcome→detail rules as dict | Open |
| TD-027 | Low | DRY | `options_chain.py` mirrored error-mapping except blocks (re-opens TD-008 site 1) | Open |
| TD-028 | Low | DRY | `cli.py`: identical result branches in `run_auth_status`/`run_renew` | Open |
| TD-029 | Low | DRY | `to_json`/`from_json` duplicated in `renewal.py` | Open |
| TD-030 | Low | KISS | `movement_involves_filter`: M3 documented but identical to M1 (doc debt) | Open |
| TD-031 | Low | DRY | Market-timezone constant x3; `positions` plumbing and event-emission inconsistencies | Open |
| TD-032 | Low | KISS | `quotes.get_quotes` validates and accumulates in the same loop | Open |
| TD-033 | Low | KISS | `log.py` event registry hand-maintained; `quotes` never emits a success event | Open |
| TD-034 | Medium | KISS | `transactions.py`: 1336 lines, 9 responsibilities (optional split) | Open |

---

## High priority

### TD-001 — Renewal lock: latent bug and needless complexity (KISS + BUG)

**Area:** `src/schwab_mcp/renewal.py:208-287`

`_acquire_store_lock` tries a non-blocking acquire; on failure it blocks,
releases, and returns `False`. The caller in `renew()` then:

1. Re-reads the store; if still expired it falls into
   `try: _do_renew(...)` **without holding the lock**, and the
   `finally: _release_store_lock(store_path)` calls `lock.release()` on a
   lock this thread does not own → `RuntimeError: release unlocked lock`,
   and two threads can renew in parallel.
2. If the re-read finds the token valid, it returns early and the lock is
   simply left held (never released by this path's semantics).

**Evidence:**

```python
acquired = lock.acquire(blocking=False)
if not acquired:
    lock.acquire()
    lock.release()
return acquired
```

**Refactor:** replace the acquire/release dance with a blocking
`with _store_lock(store_path):` context, re-check the margin **inside**
the lock, and return `not_needed` if another thread already renewed.
Delete `_acquire_store_lock`/`_release_store_lock`.

**TDD:** regression test where two sequential `renew()` calls race (first
holder renews, second sees the refreshed store) and asserts no
`RuntimeError` and no double renewal.

**Resolved** (v0.9.8, 2026-11-04): `renew()` now runs the renewal inside a
single blocking critical section (`with _store_lock(store_path):`) that
re-checks the store margin inside the lock and returns `not_needed` when
another thread already renewed; `_acquire_store_lock`/`_release_store_lock`
were deleted. Pinned by `test_waiter_renews_serialized_when_first_renewal_leaves_store_expired`,
`test_second_sequential_renew_sees_refreshed_store`, and
`test_acquire_release_store_lock_helpers_removed` in
`tests/unit/test_renewal.py`. Assessment: `.specify/bugs/td-001-renewal-lock/assessment.md`.

---

### TD-002 — Outcome/detail taxonomy duplicated across modules (DRY)

**Area:** `transactions.py` vs `positions.py`

The central "self-classifying result" shape was re-implemented from
scratch in both feature modules instead of being shared:

- `transactions.py:144-154` `TransactionOutcome` duplicates
  `positions.py:36-42` `OutcomeType` — same four values. The docstring
  even claims *"Reused from the positions feature (003)"*, but it is a
  re-definition, not reuse.
- `transactions.py:157-169` `TransactionDetail` vs `positions.py:52-61`
  `DetailType` — overlapping values (`account_failed`,
  `provider_unreachable`, `reauth_needed`).
- `transactions.py:546-552` `TransactionAccountFailed` vs
  `positions.py:124-128` `AccountFailed` — near-identical models.
- Worst part: the outcome↔field cross-validation rules are duplicated
  with error messages identical word for word
  (`transactions.py:653-671` `_validate_cross_rules` vs
  `positions.py:152-165` `_validate_outcome_rules`): "retryable=True
  only with transient_failure", "partial_failure requires
  accounts_failed", etc.

**Refactor:** shared module `src/schwab_mcp/results.py` holding the
outcome enum, the shared detail values, `AccountFailed`, and a common
outcome-rules validator; both modules import from it and add only their
feature-specific rules.

**TDD:** existing model-validation tests must stay green unchanged
(behavior preserved); add tests asserting both modules' enums share
identity with the shared source.

**Resolved** (v0.9.8, 2026-11-04): the shared taxonomy now lives in
`src/schwab_mcp/results.py` — one `ResultOutcome` enum (aliased by both
feature modules, preserving both member casings), the three shared detail
values as single-source constants, one `AccountFailed`/`AccountFailureDetail`
pair, and a shared validator for outcome rules 4–5. Both feature modules
import from it and keep only their feature-specific rules; the false
"Reused from the positions feature (003)" docstring claim is gone because
the reuse is now real. Pinned by 25 tests in
`tests/unit/test_results_shared_taxonomy.py` (enum/model identity, casing
aliases, vocabulary preservation, contract messages, cross-module message
parity). Assessment: `.specify/bugs/td-002-outcome-taxonomy-duplication/assessment.md`.

---

### TD-003 — SQLite token-store read triplicated (DRY)

**Area:** `src/schwab_mcp/tokens.py:75-98, 126-161`, `src/schwab_mcp/renewal.py:391-417`

Three functions repeat the same block: `os.stat` → `st_size == 0` check
→ `sqlite3.connect(f"file:{path}?mode=ro", uri=True)` → query →
`finally: con.close()`. Worse, `peek_store_status` and
`read_store_lifetime` run the **exact same query**:

```sql
SELECT expires_in, access_token_issued, refresh_token_issued FROM schwabdev LIMIT 1
```

(`renewal.py:407-409` vs `tokens.py:142-144`; `read_store_lifetime`'s
docstring even says it "uses the same pattern" — copy, not reuse.)
`peek_store` (bool) is subsumed by `peek_store_status(...) != "absent"`;
its only src callers are `cli.py:157,169`.

**Refactor:** one private helper in `tokens.py`, e.g.
`_read_schwabdev_row(path) -> tuple | None` (distinguishing absent vs
corrupted), consumed by `peek_store_status`, `read_store_lifetime`, and
the store check in `run_auth`. Delete `peek_store` or keep it as a
one-line alias.

**Resolved** (v0.9.8, 2026-11-04): the single store-read implementation
is `tokens._read_schwabdev_row(path) -> (status, row)` (tri-state
absent/corrupted/present+row); `peek_store_status` and
`renewal.read_store_lifetime` consume it, the duplicated block and
identical query exist once, and `peek_store` was deleted — its two
`run_auth` call sites now use `peek_store_status(...) == "absent"`
(the faithful translation of the old `not peek_store(...)`; corrupted
stores are unreachable at both sites). Pinned by
`TestReadSchwabdevRow` + `TestStoreReadEquivalence` in
`tests/unit/test_tokens.py`. Assessment:
`.specify/bugs/td-003-token-store-read-duplication/assessment.md`.

---

### TD-004 — Error envelopes and `ToolError` boundary divergent (DRY, live divergence)

**Area:** `quotes.py`, `price_history.py` vs `tool_errors.py`, `transactions.py`, `options_chain.py`

1. `price_history.py:147-182` duplicates the four envelope helpers from
   `quotes.py:128-150` almost literally, adding only a `symbol` field:
   `_validation_error`, `_provider_unreachable`, `_reauth_needed`,
   `_history_unavailable`.
2. **Live divergence:** `quotes.py:411-429` and
   `price_history.py:667-695` hand-roll the tool-boundary mapping
   (`except (ValueError, TypeError) → ToolError`), while
   `transactions.py:1298` and `options_chain.py:877` already use the
   shared helper `tool_errors.raise_classified_tool_error`, which also
   prefixes `reauth_needed:`/`provider_unreachable:`. A
   `ConnectivityError` or `ReauthorizationRequiredError` escaping in
   quotes or price_history today reaches the agent unclassified.

**Resolved** (v0.9.8, 2026-11-04): the four envelope builders live once in
`tool_errors.py` (`validation_error`, `provider_unreachable`,
`reauth_needed`, `history_unavailable`) with an optional
`symbol: str | None = None` that is omitted from the envelope when absent —
`quotes.py` and `price_history.py` consume them and their module-private
copies are deleted; emitted dicts are byte-identical to before. Both
market-data tool wrappers now route `(AuthError, ValueError, TypeError)`
through the shared `raise_classified_tool_error`, closing the
unclassified-escape gap for `ConnectivityError` /
`ReauthorizationRequiredError`. Pinned by parity tests in
`tests/unit/test_quotes_mapping.py` /
`tests/unit/test_price_history_mapping.py` and wrapper-classification
tests in `tests/unit/test_tool_error_classification.py`. Assessment:
`.specify/bugs/td-004/assessment.md`.

---

### TD-005 — Result construction repeated in `get_transaction_history` (DRY)

**Area:** `src/schwab_mcp/transactions.py:939-1272` (~330-line orchestrator)

- Identical reauth result blocks x2 (`1020-1025`, `1122-1127`) and
  transient blocks x2 (`1029-1034`, `1132-1137`); the `__cause__`
  inspection is also duplicated (`1017-1018`, `1119-1120`).
- The two `partial_failure` branches (`1191-1205` vs `1207-1221`)
  produce **exactly the same result**: with no successes,
  `all_movements == []` yields `_total=0, _page=[], _returned=0,
  _has_more=False, _next_offset=None` — precisely what the first branch
  hardcodes. First branch is dead code in disguise.
- The "ok, no movements" result is built twice (`1045-1056` no accounts;
  `1240-1251` filtered to empty), including the duplicated
  detail/event computation (`1038-1044` vs `1229-1239`).
- `PAGE_SIZE = 50` is a local constant in the function (`1168`) and
  hard-coded again in the model validator (`699`) and its message
  (`630`).
- Redundant condition at `1229-1233`: `filter_match_count is not None`
  is equivalent to `symbol is not None` there (`1172-1178`).
- Validator rule 7 (`709-723`) parses `occurred_at` dates twice.

**Refactor:** helpers `_reauth_result`/`_transient_result`/
`_empty_ok_result(retrieved_at, offset, symbol)`; one shared
`ConnectivityError` handler that classifies by cause; module-level
`PAGE_SIZE` used by both sites; delete the dead `partial_failure`
branch; extract `_paginate(movements, offset)` and
`_fetch_account_movements(...)` so the orchestrator drops to ~80 lines.

**Resolved** (v0.9.8, 2026-11-04): all listed duplications collapsed.
`_reauth_result` / `_transient_result` /
`_empty_ok_result(retrieved_at, offset, symbol)` replace the repeated
result blocks; one `ConnectivityError` handler classifies by `__cause__`
via `_classify_connectivity_cause` (reauth / transient / provider_error);
`PAGE_SIZE = 50` is a module-level constant consumed by the orchestrator,
the validator rule and both rendered messages; the dead all-failed
`partial_failure` branch is deleted (a single branch covers both cases —
with no successes `_paginate([])` yields exactly the previously
hardcoded values); `_paginate(movements, offset)` and
`_fetch_account_movements(...)` were extracted (plus `_account_hash`),
dropping the orchestrator from 333 to 224 lines (the residual is
docstring, numbered step comments, audit events and single-definition
outcome classification — compressing further would trade clarity for
line count). Behavior preserved: the existing suite already locked every
outcome class touched, so no behavioral tests were added; `PAGE_SIZE` is
pinned by `TestPageSizeConsistency` in
`tests/unit/test_transactions_query.py` (module-level constant +
field-description derivation). Full suite green (1789 passed, 0 skipped
at the time). Assessment and fix report:
`.specify/bugs/transaction-result-dry/`.

---

### TD-006 — Registration boilerplate x6 and CLI dispatch x4 (DRY)

**Area:** `src/schwab_mcp/server.py:195-381`, `src/schwab_mcp/cli.py:390-423`

- `server.py`: six tool registrations repeat the same structure —
  wrapper closure, manual `__name__`/`__qualname__` assignment,
  `register_tool(...)` with description (~15 lines each). Every new tool
  repeats it.
- `cli.py`: the four commands (`renew`, `auth-status`, `serve`, plus
  `auth`) repeat the identical
  `except AuthError / except Exception / else sys.exit(0)` block.

**Refactor:** `_register_bound_tool(mcp, fn, name, description, **defaults)`
using `functools.wraps`/`partial` in `server.py`; a dispatch table
`{command: runner}` with one `_run_command(fn)` wrapper in `cli.py`.

**Resolved** (v0.9.8, 2026-11-04): each registration is now a single
`_register_bound_tool(mcp, client, fn, name=..., description=...)` call;
the helper binds the client with `functools.partial` — deliberately not
`functools.wraps`, which was verified to leak `client` into the
advertised input schema via `__wrapped__` (`inspect.signature` follows
it) — plus the manual `__name__`/`__qualname__` assignment the SDK
requires, centralized once. Parameter defaults now live only in the
underlying tool functions' signatures (the proposed `**defaults`
channel would have created a second source of truth). In `cli.py`, a
module-level `_COMMAND_RUNNERS` table with one `_run_command` mapper
replaced the duplicated arms; `auth` keeps its distinct
`_run_auth_command` (concurrent/cancelled handling, no generic
`except Exception`). Pinned by `tests/unit/test_tool_registration.py`
(six names, no `client` in any schema, byte-for-byte descriptions,
client binding) and `tests/unit/test_cli_dispatch.py` (table coverage,
exit-code mapping, `SystemExit` passthrough, auth special cases). Full
suite green (1800 passed, 0 skipped).

---

## Medium priority

### TD-007 — `positions.py`: transform layer remaps itself (DRY/KISS)

**Area:** `src/schwab_mcp/positions.py`

- `unrealized_pl` computed and discarded **three times**: in
  `_transform_provider_payload` (`655-660`), in the consolidation map
  (`366-368` — key never read afterwards), and in `PositionEntry`
  construction (`398-401`, the only one that matters).
- `_collect_extended` (`286-292`) exists but `_transform_provider_payload`
  re-implements the same loop inline (`683-686`).
- Defensive timestamp override (`561-564`) duplicates propagation that
  already happens via the payload injection (`699-702`) and
  `map_provider_positions` (`310, 369`) — dead work.
- Results built with raw strings (`381-384`: `outcome="ok"`,
  `detail="no_positions"`) instead of the defined enums, and mutated
  post-hoc on the partial path (`542-545`), bypassing the validator's
  intent.

**Refactor:** compute `unrealized_pl` once at entry construction; use
`_collect_extended`; drop the timestamp override; always pass enum
members and build the final `PositionsResult` in one place (parameterize
`map_provider_positions` with outcome/detail instead of mutating).
Related dead params: `_detect_account_failures(..., retrieved_at)`
(`580`) never uses `retrieved_at`.

**Resolved** (v0.9.8, 2026-11-04): `unrealized_pl` is now computed
exactly once, at `PositionEntry` construction — the transform-layer
`unrealizedPL` bake (never read by the mapping core) and the never-read
consolidation-map key were removed. `_transform_provider_payload` reuses
`_collect_extended` instead of an inline duplicate, and the defensive
timestamp override in `get_open_positions` was dropped (values already
propagate via the payload injection). Every `PositionsResult`
construction passes `ResultOutcome`/`DetailType` members instead of raw
strings; `map_provider_positions` gained `outcome` / `detail` /
`accounts_failed` / `retryable` parameters so the partial-failure path
builds its result in a single call instead of mutating a validated
result — the post-hoc assignment bypassed pydantic validation
(`accounts_failed` entries survived as raw dicts, confirmed by the Red
run). `_detect_account_failures` lost its dead `retrieved_at`
parameter (TD-016 row closed). Pinned by the rewritten transform test,
`TestMapProviderPositionsOutcomeParams` and `TestPartialFailure` in
`tests/unit/test_positions.py` / `tests/unit/test_server_tool.py`.
Full suite green (1810 passed, 0 skipped at the time). Assessment, fix
report and verification: `.specify/bugs/td-007-positions-transform-dry/`.

---

### TD-008 — `options_chain.py` internal duplication, seven sites (DRY)

**Area:** `src/schwab_mcp/options_chain.py`

1. Audit try/except blocks copied between `get_option_chain`
   (`818-839`) and `get_option_expiration_chain` (`1089-1105`).
2. HTTP-400 "no options listed" sniff duplicated (`326-327` vs
   `919-920`), with comments referring to each other.
3. `underlying_price` extraction duplicated (`604-607` vs `731-734`).
4. `leg_maps` built twice from the same payload (`600-603` vs
   `700-704`) — divergence risk if normalization changes.
5. `"no_expirations_in_range: ... excludes all expirations"` detail
   string duplicated (`721-725` vs `1037-1041`).
6. `date.fromisoformat` with fallback-to-`None` duplicated
   (`938-942` vs `959-963`); each expiration date parsed twice.
7. `_result_meta(query, payload)` (`675-680`) ignores `payload`; three
   call sites pass it needlessly.
8. The orchestrator nests five levels of try/except (`791-839`); the
   body-limit degradation logic is buried three levels deep — extract
   `_fetch_chain_payload(client, query)`.

**Refactor:** helpers for each pair (`_no_options_response`,
`_underlying_price`, `_no_expirations_detail`,
`_parse_expiration_date`); build `leg_maps`/`underlying_price` once in
`build_chain_result` and pass them down; `_result_meta(query)`.

**Resolved** (v0.9.8, 2026-11-04): all eight sites consolidated.
`_is_no_options_response` (site 2), `_underlying_price` (site 3),
`_no_expirations_detail` (site 5) and `_parse_expiration_date` (site 6)
replace the duplicated pairs; `build_chain_result` builds `leg_maps` and
`underlying_price` once and passes them into `_map_expirations` (site 4 —
the normalization can no longer diverge between the no-data gate and the
mapping); `_result_meta(query)` lost its unused `payload` parameter
(site 7; two call sites, not three); the delta strikeCount expansion and
the body-limit degradation were extracted as `_fetch_chain_payload(client,
query)` (site 8 — both orchestrators are now flat, max nested try depth 1).
The error-mapping try/except blocks (site 1) remain explicit
near-duplicates by decision (KISS / rule of three), annotated with mutual
TD-008 cross-references: their only variations are the per-tool
`auth_event` prefixes and the chain path's `ChainDataError` clause.
Behavior-preserving: outcomes, result shapes and `detail` strings are
unchanged; the shared `no_expirations_in_range` detail string is pinned
verbatim by tests on both paths (new characterization test for the
expiration tool). Each expiration date is parsed exactly once. Full suite
green (1811 passed, 0 skipped). Assessment, fix report and verification:
`.specify/bugs/td-008-options-chain-dry/`.

---

### TD-009 — Two symbol-validation grammars in the package (DRY)

**Area:** `quotes.py` (declared single source of truth, used by
`price_history.py:486-524`) vs `options_chain.py:196-215`

`options_chain` validates symbols with its own ad-hoc check:

```python
if self.symbol.strip() != self.symbol or any(ch.isspace() for ch in self.symbol):
```

Two definitions of "valid symbol" coexist: `options_chain` would accept
e.g. `"BRK/B"` without the equity/index shape analysis that
`quotes._classify` performs.

**Refactor:** extract symbol validation into a shared helper (in
`quotes.py` or a `symbols.py`) returning `(kind, provider_form)` or an
error; `OptionChainQuery.validate()` calls it, keeping only its
contract-specific error messages on top of the single grammar.

**Resolved** (v0.9.8, 2026-11-04): the grammars moved to a new shared
module `src/schwab_mcp/symbols.py` (`INDEX_RE`, `EQUITY_RE`, `OPTION_RE`,
`canonical_option_symbol`, `classify_symbol`) — the package's single
source of truth, consumed by `quotes.py`, `price_history.py` (import
path updated) and now `options_chain.py`. `OptionChainQuery.validate()`
classifies the raw symbol through the new `classify_underlying()`
wrapper (slash-form `BRK/B` and lowercase tolerated — both resolve at
the provider), rejecting off-grammar symbols (`AAPL!`) and
option-contract symbols with an actionable `ValueError` **before any
upcall**; the empty/internal-whitespace messages are unchanged on top
of the shared grammar. This closes the misleading path where an
off-grammar chain symbol reached the provider's HTTP 400 and surfaced
as `no_options_listed`. TDD (red confirmed first: 5 failing regression
tests). Full suite green (1819 passed, 0 skipped). Assessment, fix
report and verification: `.specify/bugs/duplicate-symbol-validation/`.

---

### TD-010 — `price_history.py`: failure-event pattern repeated manually (DRY)

**Area:** `src/schwab_mcp/price_history.py`

- `_fail` invoked six times repeating the same 5-argument tuple
  `(normalized, frequency, period, extended_hours, extended)`
  (`488-557`).
- The event-detail composition `f"{detail} " + _selection_detail(...)`
  repeated five times (`226, 473-476, 582-585, 591-594, 609-612`).
- Inconsistency exposing the manual duplication: failure events log the
  normalized symbol, the success event (`653-656`) logs the raw one —
  the same instrument appears under two keys.
- The `ConnectivityError` handler duplicates reauth/unreachable branches
  (`575-596`).

**Refactor:** a closure `fail(detail, **extra)` created once after
normalization (or pass a selection object); a `_fail_event(detail)`
helper; use `normalized` everywhere; collapse the two failure branches
into one parameterized helper.

**Resolved** (v0.9.8, 2026-11-04): the selection tuple is bound once by
a `fail(detail, **extra)` closure created immediately after symbol
normalization (all seven `_fail` call sites are now one-liners);
`_fail_event(detail, ...)` is the single home of the
`f"{reason} " + _selection_detail(...)` composition (used by `_fail`,
the `invalid_request` site and the `fail_event` closure); the
`ConnectivityError` handler collapses to one emission path via a
`(state, reason, envelope)` lookup; the success event composes through
the same closure path. One report claim was rejected during triage: the
success event never logged a "raw" symbol — `_selection_detail`
normalizes internally, so all events already emitted the same normalized
symbol (only the START event keeps passing the raw argument, provably
output-identical). Behavior verified byte-identical by a differential
harness (pre- vs post-refactor over 15 scenarios: identical events,
envelopes, raised errors). Full suite green (1819 passed, 0 skipped).
Assessment, fix report and verification:
`.specify/bugs/td-010-price-history-fail-dry/`.

---

### TD-011 — Store backup and quarantine: same algorithm twice (DRY)

**Area:** `src/schwab_mcp/tokens.py:169-198` vs `252-278`

`backup_token_store` and `quarantine_corrupt_store` repeat: unique name
via `stamp` + `while target.exists()` counter, `os.rename`,
`os.chmod(0o600)`, `_drop_sidecars(src)`. Only the suffix
(`.bak.` vs `.corrupt.`) and the required prior status differ.

**Refactor:** `_move_store_aside(path, suffix, required_status)` plus two
three-line wrappers.

**Resolved** (v0.9.8, 2026-11-04): `_move_store_aside` is now the single
home of the safe move-aside sequence (status guard, `<name>.<suffix>.<UTC
stamp>[-<counter>]` collision-free naming, `os.rename`, `0o600`,
sidecar drop); `backup_token_store` and `quarantine_corrupt_store` are
three-line wrappers (`("bak", "present")` / `("corrupt", "corrupted")`)
keeping their docstrings and contracts, and reusing the `_backup_timestamp`
patch seam. Behavior-preserving: the existing backup/quarantine suites
passed unchanged. Full suite green (1819 passed, 0 skipped). Assessment
and fix report: `.specify/bugs/td-011/`.

---

### TD-012 — Client-shim installation scattered across entry points (DRY)

**Area:** `cli.py:149, 321`, `server.py:124`

`install_trailing_slash_callback_support()` is called at three sites
before every `schwabdev.Client` construction, but `client.py:24-54` is
already the declared single construction point. Forgetting it at a
fourth entry point silently reproduces the callback-trailing-slash bug.

**Refactor:** move installation inside `build_schwab_client()` (it is
idempotent — `schwabdev_compat.py:71-72`). Deletes three lines of
coupling and closes the error class.

**Resolved** (v0.9.8, 2026-11-04): the install now happens inside
`build_schwab_client()` itself; the three call sites (`cli.run_auth`,
`cli._do_run_renew`, `server.run_serve`) and their imports were deleted.
The factory guarantee (request timeout **and** trailing-slash shim) is
pinned by `tests/unit/test_client_factory.py::
TestClientInstallsTrailingSlashShim`. Assessment, fix report and
verification: `.specify/bugs/td-012-client-shim-install/`.

---

### TD-013 — `log.py`: redaction duplicated; malformed timestamp (DRY + BUG)

**Area:** `src/schwab_mcp/log.py:115-116, 170, 175-176`

- The secret-redaction loop exists twice: `_RedactionFilter.filter`
  (`115-116`) and `auth_event` (`175-176`), both
  `for secret in sorted(_secrets, key=len, reverse=True): text.replace(secret, "***")`.
- `log.py:170` produces a malformed suffix:
  `.replace("+00:00", "Z+00:00")` outputs `2026-11-04T12:00:00Z+00:00`
  (presumably meant to end in `Z`).

**Refactor:** `_redact(text) -> str` helper used by both; decide the
timestamp contract and use `.replace("+00:00", "Z")` if `Z` is intended.

**TDD:** regression test for the timestamp format.

**Resolved** (v0.9.8, 2026-11-04): the redaction loop lives once in
`_redact(text)` (`log.py`), called by both `_RedactionFilter.filter` and
`auth_event`. The timestamp contract was decided as **standard ISO-8601
with a plain `+00:00` offset** (matching the `utc_now_iso()` precedent in
`positions.py`/`transactions.py`, which explicitly reject the
non-`fromisoformat`-parseable `Z+00:00` suffix); the malformed
`.replace("+00:00", "Z+00:00")` was deleted. Two unit tests that codified
the broken format were rewritten; a `datetime.fromisoformat` regression
test pins the fix. Assessment and fix report:
`.specify/bugs/td-013/`.

---

### TD-014 — Release: member list hardcoded twice (DRY)

**Area:** `src/schwab_mcp_release/allowlist.py:44-60` vs `68-79`

The same member set (`README.md`, `dist/<wheel>`, `manuals/*.md` x4,
`install.sh`) exists once as `MemberSpec`s and once as the source map.
Adding a manual requires editing two synchronized places; desync breaks
the build silently. The module docstring proclaims "one authoritative
member list, no duplication".

**Refactor:** one table `(_MEMBER_PATH, _SOURCE_REL, _PROVENANCE)` from
which both `member_specs()` and `source_map()` derive; generated members
(`manifest.json`, `SHA256SUMS`) stay separate as today.

**Resolved** (v0.9.8, 2026-11-04): the member list lives once, in a
`_CONTENT_MEMBER_TABLE` of `(archive path, source path, provenance)` rows —
`member_specs()` and `source_map()` both derive from it (the wheel is the
one dynamic entry, resolved via a `_WHEEL` sentinel), so adding a member is
a one-place edit. Signatures, fixed order (FR-011), provenance strings and
the generated members are unchanged. A new invariant test pins
`set(source_map(...)) == {spec.path for spec in content_members(...)}`,
turning either desync direction into a loud suite failure — one report
claim was corrected during assessment: only the `source_map`-superset
direction was silent (a `member_specs`-only addition already failed loudly
with `ReleaseError`). Full suite green (1821 passed, 0 skipped).
Assessment, fix report and verification: `.specify/bugs/td-014/`.

---

### TD-015 — Release: duplicated validation and except-clones in `cmd_build` (DRY)

**Area:** `src/schwab_mcp_release/cli.py:74-106`, `archive.py:56-58`, `checks.py`, `wheel.py`

- `cli.py:92-95` duplicates the source-file validation already performed
  by `assemble_archive` (`archive.py:56-58`), with divergent message
  style.
- Three identical `try/except → print error → return 3` blocks
  (`74-78, 85-89, 97-106`) collapse into one because `VersionError` and
  `WheelBuildError` already subclass `ReleaseError` (`version.py:18`,
  `wheel.py:27`).
- `wheel.py:45` re-resolves the version by re-reading `pyproject.toml`
  although `cmd_build` already resolved it (`cli.py:75`) — change
  signature to `build_wheel(project_root, version, out_dir)`.
- `checks.py:38` vs `67`: same `wrap/` prefix-strip logic copied;
  extract `_relative_name(entry, wrap)`.

**Refactor:** single `except ReleaseError` around resolve/build/
assemble; delete the duplicate validation loop; pass the resolved
version through; share the strip helper.

**Resolution (v0.9.8, 2026-11-04):** all four duplications collapsed.
`cmd_build` now wraps resolve/build/assemble in one
`except ReleaseError → print → return 3` (the dirty-tree guard moved
inside the try as a plain `return 2`, preserving the original
version-error-before-dirty-guard exit-code ordering); the source-file
pre-validation loop is deleted — `assemble_archive` remains the single
missing-source check (exit 3 and the member path in stderr are
unchanged); `build_wheel(project_root, version, out_dir)` receives the
caller-resolved version instead of re-reading `pyproject.toml`;
`checks.py` strips the `wrap/` prefix through one `_relative_name`
helper. Full suite green (1826 passed, 0 skipped).
Assessment, fix report and verification: `.specify/bugs/td-015/`.

---

## Low priority

### TD-016 — Dead parameters in helpers

| Location | Issue |
|----------|-------|
| `transactions.py` | ~~`_should_split(range_days)` — parameter "accepted for interface consistency", never used; `3000` cap should be a named constant (`UPSTREAM_TXN_CAP`)~~ Fixed (td-016, v0.9.8): parameter removed, cap is now `UPSTREAM_TXN_CAP` |
| `transactions.py` | ~~`range_days` computed only to feed the dead parameter~~ Fixed (td-016, v0.9.8): computation removed with the parameter |
| `positions.py:580` | ~~`_detect_account_failures(payload, retrieved_at)` — `retrieved_at` never used~~ Fixed (TD-007, v0.9.8): parameter removed |
| `options_chain.py:675-680` | ~~`_result_meta(query, payload)` — `payload` never used (also listed in TD-008)~~ Fixed (TD-008, v0.9.8): signature is now `_result_meta(query)` |

### TD-017 — Unused imports and members

| Location | Issue |
|----------|-------|
| `positions.py:10, 13` | ~~`import time` and `List` unused~~ `import time` Fixed (TD-017, v0.9.9): removed. `List` was **not** unused — used by `accounts_failed`; annotation normalized to `list[...]` in the same change |
| `allowlist.py:19` | ~~`from collections.abc import Mapping` unused~~ Fixed (TD-017, v0.9.9): removed |
| `tokens.py:18` | ~~`TypeVar F` unused (`retry_call` does not annotate)~~ Fixed (TD-017, v0.9.9): removed |
| `tokens.py:380-385` | ~~`retry_once` has no src callers (tests and comments only) — remove with test updates~~ Fixed (TD-017, v0.9.9): removed; docstring mentions updated to `retry_call(..., retries=1)` |
| `renewal.py:106` | ~~`from datetime import datetime, timezone` unused~~ Fixed (TD-017, v0.9.9): removed |
| `renewal.py:102, 389` | ~~`import os as _os` duplicated (module level and inside `read_store_lifetime`)~~ Stale — already removed by the v0.9.8 refactor (commit e3e5466); a single `import os` remains |
| `config.py:36-37` | ~~`Config.__getitem__` has no callers — speculative over-engineering~~ Corrected (TD-017, v0.9.9): claim **invalid** — `tests/unit/test_config.py` exercises `config["key"]` bracket access 15×; the method and the `Any` import are retained |
| `transactions.py:218-242` | ~~`ALL_TRANSACTION_TYPES` lists the 15 enum values twice (map keys and joined string); derive as `",".join(t.value for t in ProviderTransactionType)`~~ Fixed (TD-017, v0.9.9): derived from the enum, pinned by unit test |
| `transactions.py:1191-1205` | ~~Dead `partial_failure` branch producing an identical result (also listed in TD-005)~~ Stale — already consolidated by TD-005 (v0.9.8): a single branch now covers both cases |

### TD-018 — Obscured imports and readability nits

| Location | Issue |
|----------|-------|
| `cli.py:424-425` | ~~`__import__("logging").root` — plain `import logging` at module top is strictly simpler~~ Fixed (TD-018, v0.9.9): `import logging` added to the top-level stdio imports; both redaction-filter call sites use it directly |
| `cli.py:152-160` | ~~Auth-URL fallback exists only for inert test stubs (per its own comment); consider moving to a test fixture~~ Resolved (TD-018, v0.9.9): kept as deliberate hardening against a schwabdev hook-timing change — comment reframed and behavior pinned by `TestAuthUrlFallbackForInertClient` (URL printed exactly once, never reports success) |
| `renewal.py:1-5, 101-114` | ~~Docstring says "value types" but the module also holds the orchestrator, locks, and store reader; imports appear mid-file — split or fix docstring, move imports to top~~ Fixed (TD-018, v0.9.9): docstring describes all three responsibilities, mid-file import block hoisted to the top, misplaced section banners corrected. The module split was deliberately deferred (higher blast radius, zero behavior gain) |
| `transactions.py:1204, 1212` (pattern) | ~~Results constructed with raw strings where enums exist; post-hoc mutation (`positions.py:542-545`) bypasses validator intent (also listed in TD-002/TD-007)~~ Fixed (TD-018, v0.9.9): `AccountFailureDetail` enum used at both `TransactionAccountFailed` constructions (pinned by `test_enum_construction_serializes_canonical_values`). The post-hoc-mutation claim was stale — already fixed by TD-007; the remaining `positions.py` raw-dict `accounts_failed_list` construction stays with TD-002/TD-007 |
| `options_chain.py:390-423` | ~~`serialize_leg` elif-chain; move the `trade_time` alias into the key map as candidate keys (`("tradeTime", "tradeTimeInLong")`)~~ Fixed (TD-018, v0.9.9): `_PROVIDER_KEY_MAP` retyped to candidate-key tuples in precedence order, `trade_time` maps to `("tradeTime", "tradeTimeInLong")`, `serialize_leg` takes the first candidate present; the special-case branch is gone (pinned by two `TestSerializeLeg` alias tests) |
| `archive.py:71` | ~~`payloads.get(spec.path, generated.get(spec.path))` fails with a cryptic `TypeError` if a member is in neither dict; use an explicit merged lookup with a clear error~~ Fixed (TD-018, v0.9.9): explicit membership check raises `ReleaseError("no payload or generated artifact for archive member <path>")` — pinned red→green by `TestMemberLookupRobustness` (pre-fix failure was the predicted `zipfile` `TypeError`) |

---

## Second audit pass (TD-019–TD-034, open)

### TD-019 — OCC option symbol parsing triplicated (DRY)

**Area:** `src/schwab_mcp/symbols.py:31-53`, `src/schwab_mcp/transactions.py:53-81`,
`src/schwab_mcp/positions.py:173-192`

The knowledge *"the last 15 characters of an OCC option symbol encode
`YYMMDD` + `C/P` + 8-digit strike×1000"* lives in three modules:

- `symbols.py` — `OPTION_RE` + `canonical_option_symbol()`. The module
  docstring proclaims it "the package's single source of truth"
  (established by TD-009).
- `transactions.py:53` — its own `_OCC_TAIL_RE`
  (`^\d{6}[CP]\d{8}$`) plus `_option_root()`, re-encoding the same tail
  grammar independently of the SSOT.
- `positions.py:173-192` — `_parse_occ_option_symbol()` re-implements
  the tail checks by hand (`len(tail) < 15 or tail[6] not in "CP"`,
  `yymmdd.isdigit() and strike_millis.isdigit()`) — it does not even
  reuse the regex. It also holds the only derivation of the ISO expiry
  (`20{YYMMDD}`).

**Risk:** a change in the OCC encoding (strike digits, decimals,
separator tolerance) must be fixed in three places, each pinned by
different tests; the copies can drift silently because nothing asserts
they agree.

**Refactor:** add `parse_occ_symbol(symbol) -> {root, expiry, put_call,
strike} | None` (or a small dataclass) to `symbols.py`, built on
`OPTION_RE`/`canonical_option_symbol` — one parse of the tail, three
consumers. `transactions._option_root` and
`positions._parse_occ_option_symbol` become thin wrappers (or are
deleted in favour of direct calls); the expiry derivation moves next to
the strike decoding it mirrors.

**TDD:** parity tests first (Red): feed the same OCC fixtures to the
three current parsers and pin that the shared parser reproduces every
existing result (root/strike/expiry, including the padded-root case
`"AMD   261120P00630000"`); then Green with the shared function. The
existing suites must stay green unchanged.

**Resolved** (v0.9.11, 2026-11-04): the tail grammar now lives once, in
`src/schwab_mcp/symbols.py` (`OCC_TAIL_RE` + frozen dataclass
`OccSymbol` + `parse_occ_symbol()`, with the ISO expiry derivation moved
next to the strike÷1000 decoding it mirrors). `transactions._option_root`
and `positions._parse_occ_option_symbol` are thin wrappers over it (their
signatures and call sites untouched — the direct-call migration remains a
follow-up); `_OCC_TAIL_RE` and the hand-written tail checks are deleted.
The strict-tail contract is pinned against the permissive `OPTION_RE`
(`parse_occ_symbol("AMD   261120P63") is None`) and cross-parser parity
is locked by `tests/unit/test_occ_symbol_parity.py` (shared parser vs.
both former private parsers over the fixtures already pinned in
`test_transactions_underlying.py` and `test_positions_live_response.py`).
Behavior-preserving; existing suites green unchanged (1875 passed, 0
skipped). Assessment and fix report: `.specify/bugs/td-019-occ-symbol-parsing/`.

---

### TD-020 — Transactions test fakes x5, `_validator` x3, 15-types literal (DRY, tests)

**Area:** `tests/unit/test_transactions_query.py:62-157`,
`tests/unit/test_transactions_symbol.py:68-174`,
`tests/unit/test_transactions_filter_query.py:79-193`,
`tests/unit/test_transactions_pagination.py:43`,
`tests/unit/test_transactions_live_response.py:47-89`,
`tests/unit/helpers.py`

`tests/unit/helpers.py` declares itself "single source of truth
(Constitution II)" and already centralizes `FakeQuotesClient` /
`FakePriceHistoryClient`, but the transactions domain re-implements its
own fake per file — five clients (~100 lines each) sharing
`linked_accounts()`, `transactions()`, `call_log`, `set_accounts`,
`set_response`, `reset_tracking`:

| File | Fake class | Extra behaviour |
|------|-----------|-----------------|
| `test_transactions_query.py` | `FakeClient` | global/per-account `transactions()` errors, `instruments()` with a hardcoded known-symbol set |
| `test_transactions_symbol.py` | `FakeClient` | symbol-aware `transactions()` filtering, own known-symbol set |
| `test_transactions_filter_query.py` | `FilterFakeClient` | same, plus raw-response passthrough |
| `test_transactions_pagination.py` | `FakeClient` | minimal copy |
| `test_transactions_live_response.py` | `LiveLikeClient` | live-shaped responses |

Additional copies inside the same files:

- `class _validator` (a two-line stub of `schwabdev.validation.Validator`)
  duplicated at `test_transactions_query.py:56`,
  `test_transactions_symbol.py:62`, `test_transactions_pagination.py:37`.
- The 15-type literal `ALL_TYPES` re-declared in
  `test_transactions_query.py:40-45` (plus `EXPECTED_TYPE_COUNT`) when
  `transactions.ALL_TRANSACTION_TYPES` is derived from the enum precisely
  so "the two lists cannot drift apart" (TD-017).

The knowledge graph shows these fakes with in-degree 15–39 — they are
the backbone of the transactions suite; every change to
`get_transaction_history` touches up to five synchronized copies. There
are 22 `Fake*` classes across 13 test files in total.

**Refactor:** one configurable `FakeTransactionsClient` in
`tests/unit/helpers.py` — flags for global/per-account errors, raw
responses, and symbol-filtering mode; `_validator` promoted to the same
module; the type-literal tests import `ALL_TRANSACTION_TYPES` from
`src`.

**TDD:** behavior-preserving — every transactions test stays green with
only the import/constructor changes; add a guard test asserting the
per-file fake classes are gone (e.g. via a helpers-only inventory test
in the style of TD-014's invariant test).

---

### TD-021 — `positions.py`: payload crosses three shapes before mapping (KISS)

**Area:** `src/schwab_mcp/positions.py:195-237` (`_normalize_positions_payload`),
`636-724` (`_transform_provider_payload`), `293-439` (`map_provider_positions`)

The `get_open_positions` pipeline converts the provider payload through
three shapes before the real mapping:

1. Raw provider form (top-level list of `{"aggregatedBalance",
   "securitiesAccount": {...}}`, live 2026-10-23).
2. `_normalize_positions_payload()` → the **legacy** `{"accountDetails":
   [...]}` dict — kept only for historical/test compatibility.
3. `_transform_provider_payload()` → the "internal" `{"accounts":
   [{"accountHash", "positions": [...]}]}` shape.
4. `map_provider_positions()` → `PositionsResult`.

Two whole functions exist purely to re-shape data between steps 2 and 3
(~120 lines); the legacy `accountDetails` shape is ceremonial. TD-007
already removed the intra-layer duplication (triple `unrealized_pl`,
inline `_collect_extended`, post-hoc mutation) but left the shape
pipeline intact.

**Refactor:** normalize once into a single internal shape (either the
raw securitiesAccount entries or the `accounts` form) and map directly
from it; retire the `accountDetails` intermediate, updating the tests
that construct it (T004 constructs the internal shape already, so the
blast radius is `_normalize_positions_payload` + `_transform_provider_payload`
callers).

**TDD:** the mapping-core tests (`T004`) must stay green unchanged; if
any normalization edge case is not already pinned (non-dict elements,
missing `accountNumber`, per-entry `error` keys), add the test first.

---

### TD-022 — `ConnectivityError` cause classification written three times (DRY)

**Area:** `src/schwab_mcp/transactions.py:946-958`, `src/schwab_mcp/price_history.py:532-545`,
`src/schwab_mcp/quotes.py:280-290`, `src/schwab_mcp/renewal.py:185-209`

The rule "`__cause__` is `ReauthorizationRequiredError`/`PermissionError`
→ reauth, otherwise transient" is implemented three times:

- `transactions._classify_connectivity_cause()` — the named helper
  (introduced by TD-005), which also returns `"provider_error"`.
- `price_history.py:536-538` — inline `isinstance(exc.__cause__, (...)
  )` despite importing both exception classes.
- `quotes.py:281-283` — inline again.
- `renewal._tie_breaker_probe` branches over the same exception pair
  (its contract differs — probe, not cause classification — but it is
  the fourth consumer of the same taxonomy knowledge).

**Risk:** re-classifying a cause (e.g. treating a permission-scoped 403
differently from a full reauth) requires three coordinated edits;
`price_history` and `quotes` can drift from the helper.

**Refactor:** promote the classifier to a shared home —
`errors.classify_connectivity_cause(exc)` or `provider.py` — and
consume it from `transactions`, `price_history` and `quotes`.

**TDD:** unit tests for the classifier (all three return values,
including `PermissionError` cause and a non-connectivity cause) plus
the existing per-tool event-parity tests staying green.

---

### TD-023 — `utc_now_iso()` duplicated; UTC-timestamp convention x4 (DRY)

**Area:** `src/schwab_mcp/transactions.py:506-512`, `src/schwab_mcp/positions.py:259-265`,
`src/schwab_mcp/options_chain.py:732`, `src/schwab_mcp/log.py:183`

`utc_now_iso()` exists twice with an identical body and a near-identical
docstring (`transactions` and `positions`). The ISO-8601-UTC
`isoformat(timespec="seconds")` convention is additionally written
inline in `options_chain._result_meta` (`generated_at`) and
`log.auth_event` (the audit-line timestamp). Four copies of one
convention that TD-013 just finished normalizing ("no non-standard
`Z+00:00` suffix") across the codebase.

**Refactor:** one `utc_now_iso()` in a shared home (a small
`time_util.py`, or `results.py` next to the models that consume it);
`transactions`, `positions` and `options_chain` import it. `log.py` may
keep its own copy *only* if the audit-line contract demands isolation —
in that case document the decision at both sites so the fourth copy is
explicit, not accidental.

**TDD:** identity test (the three consumers return identical-shape
values) + the existing `fromisoformat` regression tests from TD-013.

---

### TD-024 — Five `*_tool` wrappers repeat the same boilerplate skeleton (DRY)

**Area:** `src/schwab_mcp/transactions.py:1307-1337`,
`src/schwab_mcp/options_chain.py:926-959` and `1191-1217`,
`src/schwab_mcp/price_history.py:610-642`, `src/schwab_mcp/quotes.py:338-360`

Every MCP tool wrapper repeats the same skeleton (~30 lines each):
late imports of `AuthError` and `raise_classified_tool_error`,
`try: return fn(...) except (AuthError, ChainDataError?, ValueError,
TypeError): raise_classified_tool_error(exc)`, and a near-identical
docstring ("Converts validation errors ... into the MCP SDK's
`ToolError` so the actionable message ... reaches the agent"). The
knowledge graph connects all five functions pairwise with `SIMILAR_TO`
edges — structural duplication confirmed independently of source
reading. Variation points: the domain-error tuple (only
`transactions` adds `InstrumentNotFoundError`, only the chain tools add
`ChainDataError`) and the forwarded parameters.

Related inconsistency: `positions.get_open_positions` is registered
directly without any `*_tool` wrapper, so it follows a third pattern.

**Refactor:** one shared factory in `tool_errors.py`, e.g.

```python
def make_tool(fn, *, domain_errors: tuple[type[Exception], ...] = (ValueError, TypeError)):
    def tool(client, *args, **kwargs):
        try:
            return fn(client, *args, **kwargs)
        except (AuthError, *domain_errors) as exc:
            raise_classified_tool_error(exc)
    tool.__name__ = fn.__name__
    tool.__qualname__ = fn.__qualname__
    return tool
```

Each `*_tool` collapses to a one-line `get_x_tool = make_tool(...)`
plus the tool-specific docstring; the domain-error tuple becomes the
only declared variation. Decide the `positions` question (adopt the
factory or document why it has no wrapper).

**TDD:** the existing wrapper-classification tests
(`tests/unit/test_tool_error_classification.py`) must stay green;
add a test asserting every registered tool's wrapper routes
`(AuthError, ValueError, TypeError)` through the shared factory (e.g.
pinning `__wrapped__`/factory identity).

---

### TD-025 — `retry_call` used without retries at 13/14 sites; manual retry in `renewal` (DRY/KISS)

**Area:** `src/schwab_mcp/tokens.py:333-378`, `src/schwab_mcp/renewal.py:303-322`

- **13 of 14** production call sites pass `retries=0` (positional `0`):
  `transactions.py:1057,1065,1158`; `options_chain.py:349,385,983,991`;
  `price_history.py:521,531`; `quotes.py:169,170,276,279`. Only
  `server.py:156` uses an actual retry (`retries=1`). At `retries=0`
  the function is not a retry — it is a one-shot
  "wrap any exception in `ConnectivityError`" — and both its name and
  its error message lie: `"Schwab API unreachable after retry"` when
  no retry happened (`tokens.py:373-375`).
- `renewal._do_renew` (lines 303-322) re-implements its own retry loop —
  `for attempt in range(1 + RETRIES)` with `time.sleep(0.5)` — i.e. the
  same knowledge `retry_call` already owns (retry count + 0.5 s wait).

**Refactor (decide first, then edit):** either (a) `retry_call` becomes
the retry mechanism of record — the `renewal` manual loop is replaced by
a `retry_call`-based attempt helper, and call sites that genuinely want
a retry declare it — or (b) the wrapper is renamed/re-messaged for what
it mostly is (e.g. `unwrap_call` with `ConnectivityError` mapping, with
the message "Provider call failed" not "after retry") and `renewal`'s
loop is the documented second mechanism. Option (a) removes a
duplicated loop; option (b) removes a lie from 13 call sites. Do not
leave both the misleading message and the duplicate loop.

**TDD:** pin the chosen message/behaviour contract in
`tests/unit/test_tokens.py`; the renewal retry tests
(`tests/unit/test_renewal.py`) must stay green under option (a).

---

### TD-026 — `TransactionsResult` validator: outcome→detail rules as a table (KISS)

**Area:** `src/schwab_mcp/transactions.py:658-766`
(`_validate_cross_rules`, 108 lines)

The final block repeats three "outcome X ⇒ detail Y" checks with the
same shape (`is_partial`/`is_transient`/`is_reauth` flags computed at
the top, lines 665-668, then three consecutive `if` blocks at 748-764).
A `dict{TransactionOutcome: TransactionDetail}` iterated once expresses
the same contract. Two adjacent fragilities worth keeping pinned while
touching this function: rules 2-3 (has_more ⇔ next_offset, lines
695-706) and rule 7's silent `pass` on unparseable fixture dates
(709-725).

**Refactor:** replace the three outcome⇒detail `if`s with a module-level
`_OUTCOME_REQUIRED_DETAIL` map; keep the numbered contract comments for
the remaining rules.

**TDD:** the data-model rule tests must stay green unchanged (this is a
pure code-shape change).

---

### TD-027 — `options_chain.py` mirrored error-mapping except blocks (DRY; re-opens TD-008 site 1)

**Area:** `src/schwab_mcp/options_chain.py:884-908`
(`get_option_chain`) vs `1159-1178` (`get_option_expiration_chain`)

Seven `except` clauses that only emit `auth_event(...)` and re-raise,
near-mirrored between the two orchestrators. TD-008 resolved its site 1
by declaring the mirrors deliberate ("the per-tool auth_event prefixes
and this one-block difference are the only variation"). The second
audit pass challenges that call: the variation is fully parameterizable
— a `{exc_type: (state, detail)}` table iterated once, with
`ChainDataError` and the event prefix as parameters — and the current
shape adds a new error class in two places that can diverge silently.

**Refactor:** one `_emit_failure_event(exc, event_prefix, mapping)` loop
in the module; both orchestrators shrink to a single `try/except`
wrapper. If after implementing it the table reads worse than the
explicit blocks, record that judgement here instead of merging it.

**TDD:** event-parity characterization tests: for each error class on
each path, the emitted `(event, outcome, detail)` tuple is unchanged.

---

### TD-028 — `cli.py`: identical result branches in `run_auth_status`/`run_renew` (DRY)

**Area:** `src/schwab_mcp/cli.py:229-262`, `281-305`

- `run_auth_status` constructs the identical
  `AuthHealth(state="reauth_required", access_expires_in_seconds=None,
  refresh_expires_in_seconds=None)` **three times** (absent store,
  corrupted store, unreadable lifetime) and prints/exits the same way.
- `run_renew` has two near-identical blocks for absent/corrupted
  (differing only in the `detail` string: `"store_absent"` vs
  `"store_corrupted"`).

**Refactor:** a `status → (detail, health-or-outcome, exit_code)` map
consumed by one branch each; ~30 lines removed and a fourth status
requires one table row.

**TDD:** the CLI exit-code/status contract tests
(`tests/unit/test_cli_*`) must stay green unchanged.

---

### TD-029 — `to_json`/`from_json` duplicated in `renewal.py` (DRY)

**Area:** `src/schwab_mcp/renewal.py:80-89` (`RenewalOutcome`) and
`108-117` (`AuthHealth`)

Both frozen dataclasses carry byte-identical
`to_json()`/`from_json()` implementations
(`json.dumps(dataclasses.asdict(self), separators=(",", ":"),
sort_keys=True)` / `cls(**json.loads(data))`).

**Refactor:** one mixin (e.g. `_CompactJson`) or a free pair
`to_compact_json(obj)` / `from_compact_json(data, cls)`; the two
classes keep only their `__post_init__` validation.

**TDD:** the existing serialization round-trip tests cover it; no new
tests needed beyond keeping them green.

---

### TD-030 — `movement_involves_filter`: M3 documented but identical to M1 (KISS, doc debt)

**Area:** `src/schwab_mcp/transactions.py:100-145`

The docstring describes three matching forms (M1 exact symbol, M2 option
OCC root, M3 "same as M1, listed separately in the data model"), but M3
is literally the same `if` as M1 — the code implements two rules, not
three. A reader looking for the third branch finds none. The data-model
distinction is historical (the provider used to reject full OCC
symbols); the docstring should say that once instead of enumerating a
rule the code does not have.

**Refactor:** rewrite the docstring to describe the two implemented
rules and cite the data-model §2 note about the historical M1/M3 split;
or fold M2's comment accordingly. No code change.

**TDD:** none (docstring only).

---

### TD-031 — Market-timezone constant x3; `positions` plumbing and event-emission inconsistencies (DRY)

**Area:** `src/schwab_mcp/transactions.py:336,523`, `src/schwab_mcp/price_history.py:65`,
`src/schwab_mcp/positions.py:479-480`, `src/schwab_mcp/transactions.py:997,1287`

Three small inconsistencies, batched because each is a one-liner:

1. `ZoneInfo("America/New_York")` is constructed twice inside
   `transactions.py` (`validate_history_query`, `_provider_datetime`)
   while `price_history.py` already defines the shared `ET` constant —
   the exchange timezone should be one constant (in `symbols.py`? in a
   shared util?) consumed by both modules.
2. `positions.get_open_positions` (479-480) calls `response_json` **without**
   `retry_call` — the only orchestration that skips the shared
   retry/unwrap plumbing (TD-005/TD-008 established it everywhere
   else). Align it or document why positions is exempt.
3. Transactions emits its success event in two conventions:
   `_empty_ok_result` emits *inside* the result builder (997 — a
   side effect in a helper documented as canonical result construction)
   while the main path emits at the call site (1287). Pick one
   convention.

**Refactor:** each item independent; all three are small.

**TDD:** event-parity and timezone-dependent tests stay green; add a
pin for the chosen positions retry behaviour if it changes.

---

### TD-032 — `quotes.get_quotes` validates and accumulates in the same loop (KISS)

**Area:** `src/schwab_mcp/quotes.py:241-258`

The symbol loop appends to `errors` **and** fills `symbols_out`/
`provider_forms`/`kinds`/`seen` in the same pass; if any symbol is
malformed, the accumulated valid symbols are then discarded by the
early return. Two concerns in one loop with throwaway work on the
error path.

**Refactor:** validate all symbols first (collect only errors), then
accumulate the output lists in a second pass once validation is known
clean. Same observable behaviour, one concern per loop.

**TDD:** existing quotes validation tests must stay green unchanged.

---

### TD-033 — `log.py` event registry hand-maintained; `quotes` never emits a success event (KISS + contract question)

**Area:** `src/schwab_mcp/log.py:11-91`; `src/schwab_mcp/quotes.py:204-330`

1. `ALLOWED_EVENTS` + `_ALLOWED_OUTCOMES` are two hand-maintained levels
   for six domains × (start/success/failure): the failure-outcome sets
   of `options_chain_query_failure`, `expiration_chain_query_failure`,
   `quotes_query_failure` and `price_history_query_failure` are four
   copies of the same set; every new tool extends both structures by
   hand. A factory — e.g. `register_tool_events(prefix,
   success_outcomes=..., failure_outcomes=DEFAULT_FAILURE_OUTCOMES)` —
   derives both registries from per-tool declarations.
2. **Inconsistency (decide the contract):** every tool emits a success
   event except `get_quotes`, which emits only start/failure — and
   `quotes_query_success` is not even in `ALLOWED_EVENTS`. Either the
   quotes contract genuinely requires no success event (then document
   why, there and here) or it is a gap from feature 010 (then add the
   event + `ALLOWED_EVENTS`/`_ALLOWED_OUTCOMES` entries with the
   regression test).

**TDD:** item 1 is behavior-preserving (the event-parity tests pin
every emitted tuple); item 2 is a contract decision — whichever way,
add the test that pins it.

---

### TD-034 — `transactions.py`: 1336 lines, 9 responsibilities (KISS, optional split)

**Area:** `src/schwab_mcp/transactions.py` (whole module)

The largest module in the repo mixes: custom exception
(`InstrumentNotFoundError`, 39-44), OCC matching (47-145), four enums +
type-category map (148-259), query validation (262-383), bisection
machinery (386-543), three pydantic models (545-766), the provider
mapper (769-905), the orchestrator with dual validation (908-1299) and
the MCP tool wrapper (1302-1337). The thematic cohesion is real, but
the seams are clean: validation and the OCC parser are independent of
the models; the exception belongs in `errors.py`; the tool wrapper is
TD-024's factory.

**Refactor (deferred — only if the module keeps growing or TD-019/TD-024
do not land first):** extract `transactions_validation.py` (query
validation + bisection) and move `InstrumentNotFoundError` to
`errors.py`; re-export from `transactions.py` to keep import paths
stable. Do not split the models from the mapper — they share the
data-model contract.

**TDD:** import-path stability test (the public surface listed in
`docs/tools.md` and consumed by tests imports unchanged).

---

## Accepted complexity — do not fix (second-pass verdict)

These were flagged during the audit and deliberately accepted; recorded
so future audits do not re-open them without new evidence:

- **`server.register_tool` reaches into SDK internals**
  (`server.py:50-81`, `mcp._tool_manager._tools[name]`): no public API
  for the unknown-argument hardening; pinned by
  `tests/unit/test_tool_arg_strictness.py`. Fragile by necessity.
- **`schwabdev_compat.py` shim**: monkeypatching schwabdev internals is
  the only mechanism that survives `uv sync` and preserves the
  portal-registered callback exactly; fails loudly on upstream change.
- **`cli.run_auth` fresh-write detection** (`cli.py:128-198`): the
  counted hook + pre/post byte comparison + status checks are justified
  by the auth-false-success and auth-corrupt-store-blocked bugs.
- **`validate_history_query` rules 2b/2c** (`transactions.py:339-363`):
  the future-date/range interplay is driven by contract error messages;
  the comments already document why each branch exists.
- **`Config.__getitem__`** (`config.py:36-37`): verified used (15× by
  `tests/unit/test_config.py`); the earlier TD-017 note stands corrected.

---

## Dominant patterns

1. **Each feature re-implemented the same self-classifying result shape**
   (outcome/detail/retryable/retrieved_at + cross-validation) instead of
   sharing it — a shared `results.py` plus construction helpers removes
   most of the high-impact duplication (TD-002, TD-005, TD-007).
2. **Tool boundaries and error envelopes have 2-3 divergent
   implementations**, one of which is already inferior (no
   auth/connectivity classification) — TD-004, TD-006.
3. **Dead parameters "for interface consistency"** in four helpers —
   abstractions outgrew their usage — TD-016.
4. **Provider-format knowledge is re-encoded per feature** instead of
   imported from the module that owns it — the OCC tail grammar (TD-019),
   the connectivity-cause taxonomy (TD-022), the UTC-timestamp
   convention (TD-023). `symbols.py` and `results.py` exist precisely to
   stop this; the second pass found the modules that never adopted them.
5. **Test doubles are re-implemented per test file** despite
   `tests/unit/helpers.py` declaring itself the single source of truth
   (TD-020) — the tests were never part of any TD-001–TD-018 audit.

## Suggested resolution order

First pass (TD-001–TD-018) — **done**: TD-013 … TD-018 all resolved
(2026-11-04, one commit per area, TDD-gated).

Second pass (TD-019–TD-034):

1. TD-019 (OCC parsing, highest DRY payoff) →
2. TD-020 (tests consolidation — unlocks safe edits to `transactions.py`) →
3. TD-021 (positions pipeline) →
4. TD-022 + TD-023 (one commit: shared taxonomy/timestamp helpers) →
5. TD-025 (retry decision) →
6. TD-024 (tool factory) →
7. TD-026, TD-027, TD-028, TD-029 (medium/low DRY batch) →
8. TD-030, TD-031, TD-032, TD-033 (low batch; TD-033 needs a contract decision first) →
9. TD-034 (optional split — revisit only after 1-6 land).