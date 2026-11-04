# Technical Debt Backlog

Working backlog of KISS/DRY violations found in a full audit of `src/`
(2026-11-04). Items are resolved one at a time; update the **Status**
column as each item lands. Line numbers refer to the state of the code at
audit time and may shift as fixes merge — re-verify before editing.

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
| TD-016 | Low | Dead code | Dead parameters in helpers | Open |
| TD-017 | Low | Dead code | Unused imports and members | Open |
| TD-018 | Low | KISS | Obscured imports and misc readability | Open |

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
| `positions.py:10, 13` | `import time` and `List` unused |
| `allowlist.py:19` | `from collections.abc import Mapping` unused |
| `tokens.py:18` | `TypeVar F` unused (`retry_call` does not annotate) |
| `tokens.py:380-385` | `retry_once` has no src callers (tests and comments only) — remove with test updates |
| `renewal.py:106` | `from datetime import datetime, timezone` unused |
| `renewal.py:102, 389` | `import os as _os` duplicated (module level and inside `read_store_lifetime`) |
| `config.py:36-37` | `Config.__getitem__` has no callers — speculative over-engineering |
| `transactions.py:218-242` | `ALL_TRANSACTION_TYPES` lists the 15 enum values twice (map keys and joined string); derive as `",".join(t.value for t in ProviderTransactionType)` |
| `transactions.py:1191-1205` | Dead `partial_failure` branch producing an identical result (also listed in TD-005) |

### TD-018 — Obscured imports and readability nits

| Location | Issue |
|----------|-------|
| `cli.py:356-357` | `__import__("logging").root` — plain `import logging` at module top is strictly simpler |
| `cli.py:154-159` | Auth-URL fallback exists only for inert test stubs (per its own comment); consider moving to a test fixture |
| `renewal.py:1-5, 101-114` | Docstring says "value types" but the module also holds the orchestrator, locks, and store reader; imports appear mid-file — split or fix docstring, move imports to top |
| `transactions.py:381-384` (pattern) | Results constructed with raw strings where enums exist; post-hoc mutation (`positions.py:542-545`) bypasses validator intent (also listed in TD-002/TD-007) |
| `options_chain.py:367-386` | `serialize_leg` elif-chain; move the `trade_time` alias into the key map as candidate keys (`("tradeTime", "tradeTimeInLong")`) |
| `archive.py:71` | `payloads.get(spec.path, generated.get(spec.path))` fails with a cryptic `TypeError` if a member is in neither dict; use an explicit merged lookup with a clear error |

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

## Suggested resolution order

1. TD-001 (bug, regression test first) → 2. TD-004 (live divergence) →
3. TD-005 → 4. TD-002 → 5. TD-003 → 6. TD-006 → 7. TD-013 (bug) →
8. remaining medium items → 9. low-priority cleanup (TD-016..018 can be
batched into one commit each area, still TDD-gated).