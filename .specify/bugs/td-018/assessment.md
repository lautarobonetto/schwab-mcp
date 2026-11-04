# Bug Assessment: TD-018 — Obscured imports and readability nits

- **Slug**: td-018
- **Created**: 2026-11-04
- **Source**: pasted text (TD-018 tech-debt list, six items)
- **Verdict**: valid (as tech-debt / readability findings; no functional defect — item 4 partially duplicates TD-002/TD-007)
- **Severity**: low

## Report (verbatim or summarized)

Pasted table titled "TD-018 — Obscured imports and readability nits" with six rows:

1. `cli.py:356-357` — `__import__("logging").root`; plain `import logging` at module top is strictly simpler.
2. `cli.py:154-159` — auth-URL fallback exists only for inert test stubs (per its own comment); consider moving to a test fixture.
3. `renewal.py:1-5, 101-114` — docstring says "value types" but the module also holds the orchestrator, locks, and store reader; imports appear mid-file — split or fix docstring, move imports to top.
4. `transactions.py:381-384` (pattern) — results constructed with raw strings where enums exist; post-hoc mutation (`positions.py:542-545`) bypasses validator intent (also listed in TD-002/TD-007).
5. `options_chain.py:367-386` — `serialize_leg` elif-chain; move the `trade_time` alias into the key map as candidate keys `("tradeTime", "tradeTimeInLong")`.
6. `archive.py:71` — `payloads.get(spec.path, generated.get(spec.path))` fails with a cryptic `TypeError` if a member is in neither dict; use an explicit merged lookup with a clear error.

**Note on line numbers**: every cited line range has drifted from the current code. Actual locations are given in "Suspected Code Paths" below.

## Symptom

Not a runtime defect: a batch of six code-hygiene findings. Obscured/dead code and structure that misleads readers (obscured imports, a production fallback that only test stubs exercise, a module docstring that understates the module's contents, raw strings where domain enums exist, an ad-hoc alias branch next to a declarative key map, and a dict lookup whose failure mode is a cryptic `zipfile` `TypeError` instead of a domain error). Expected: each location expresses its intent directly.

## Reproduction

Not reproducible as a user-visible failure. Verification was by code reading:

1. Read each cited location in the current tree.
2. Confirm the reported pattern exists at (drifted) line numbers.
3. Assess reachability/blast radius.

All six patterns were confirmed present; none produces incorrect behavior today.

## Suspected Code Paths

*All verified in source on 2026-11-04; line numbers are current as of this assessment.*

1. **`src/schwab_mcp/cli.py:424-425`** (report said 356-357) — `install_redaction_filter(__import__("logging").root)` and `install_redaction_filter(__import__("logging").getLogger("Schwabdev"))`. Confirmed: `logging` is **not** imported at module top (top-level imports are `argparse`, `sys`, `webbrowser`, `collections.abc`, `functools`, `importlib.metadata`, `pathlib`, `schwabdev`, plus `schwab_mcp.*`). The `__import__` indirection buys nothing here — there is no test monkeypatching `sys.modules["logging"]` in the suite that this would dodge. Note the file does have precedent for deliberate late imports (`cli.py:148`, `noqa: PLC0415 — late import for testability`), but that is a different, documented rationale.

2. **`src/schwab_mcp/cli.py:152-160`** (report said 154-159) — the fallback:

   ```python
   if peek_store_status(config.token_db) == "absent" and hook_calls == 0:
       auth_url = _build_auth_url(config.app_key, config.callback_url)
       counted_hook(auth_url)
   ```

   The comment itself says it covers "e.g. inert test stubs". In production the `schwabdev.Client` constructor invokes `call_on_auth` whenever the store is empty (per the comment at `cli.py:144-147` and integration tests `tests/integration/test_auth.py:233`), so `hook_calls == 0` with an absent store is unreachable outside stubbed clients. Confirmed production-dead-by-design; it does keep `auth` correct if schwabdev ever changes hook timing, which is the counter-argument to removing it.

3. **`src/schwab_mcp/renewal.py:1-5` and `102-114`** — confirmed. The module docstring promises "Value types for token renewal results (FR-003) and auth health queries (FR-008)", but the module (405 lines) also contains: the renewal orchestrator (`renew` :237, `_do_renew` :278, `_tie_breaker_probe` :156), per-store-path single-flight locks (`_renew_locks` / `_renew_locks_lock` :118-119, `_store_lock` :219), and the store lifetime reader (`StoreLifetime` :345, `read_store_lifetime` :364). Imports split in two blocks: `contextlib`/`dataclasses`/`json` at top (lines 9-12), then `logging`/`os`/`threading`/`time` and five `schwab_mcp.*` imports mid-file at lines 102-114.

4. **`src/schwab_mcp/transactions.py:1204` and `1212`** (report said 381-384, which is now the tail of `validate_history_query`) — confirmed pattern:

   ```python
   failed_accounts.append(TransactionAccountFailed(account_hash=account_hash, detail="transient"))
   ...
   failed_accounts.append(TransactionAccountFailed(account_hash=account_hash, detail="provider_error"))
   ```

   `TransactionAccountFailed` is an alias of `results.AccountFailed` (pydantic `BaseModel`, `results.py:55-66`) whose `detail` field is typed `AccountFailureDetail` (`results.py:44-52`, members `provider_error`, `transient`). The enum exists with exactly these values, so the raw strings are silently coerced — behavior is correct, but the construction bypasses the enum as the source of truth. The "post-hoc mutation (`positions.py:542-545`)" half is **stale**: current `positions.py:538-545` builds `accounts_failed_list` entries as raw dicts (a lesser sibling of the same nit), and the TD-007 comment at `positions.py:553-555` states the final result is built in one call with "no post-hoc mutation of a validated result" — that defect was already remediated. As the report itself notes, this row overlaps TD-002 (outcome taxonomy) and TD-007 (positions transform DRY).

5. **`src/schwab_mcp/options_chain.py:402-406`** (report said 367-386; `serialize_leg` is at 390-423) — confirmed. Inside the field loop:

   ```python
   source_key = _PROVIDER_KEY_MAP[name]
   raw = contract.get(source_key)
   if raw is None and name == "trade_time":
       raw = contract.get("tradeTimeInLong")
   ```

   `_PROVIDER_KEY_MAP` (`options_chain.py:82`) is a declarative `dict[str, str]` used only by `serialize_leg` (verified: two references in `src/` total, both here; graph inbound trace shows `serialize_leg` is called only by `_map_expirations`, `build_chain_result`, `get_option_chain` — all within `options_chain.py`). The `trade_time` alias branch is a special case bolted beside the map it should live in.

6. **`src/schwab_mcp_release/archive.py:71`** — confirmed: `data = payloads.get(spec.path, generated.get(spec.path))`. Reachability today: `member_specs` (`allowlist.py:76-89`) = all `content_members` (each guaranteed present in `payloads` — `archive.py:55-59` raises a clear `ReleaseError` for a missing source) + exactly `manifest.json` and `SHA256SUMS` (both keys of `generated`, `archive.py:62-65`). So every member is covered and the failure path is **unreachable today**. The hazard is latent: add a member to `member_specs` without adding it to either dict and `zf.writestr(info, None)` raises `TypeError: Bytes expected...` far from the actual mistake. Note this file is in the `schwab_mcp_release` packaging tooling, not the MCP server.

## Root Cause Hypothesis

This is an accumulation of tech debt, not a single defect, so there is no single root cause. Each finding is individually grounded in the code (confidence: high). The common thread is that several refactors (TD-002, TD-003, TD-007, TD-008) left small residues — a comment-documented test-only fallback, a docstring that stopped matching the module's scope, an alias special case beside the key map — plus two independent style issues (`__import__`, mid-file imports). The most consequential item in a maintenance sense is `archive.py:71` (cryptic failure on a plausible future edit); the least impactful is the `__import__("logging")` nit.

## Proposed Remediation

**Preferred**: fix as six small, independent changes in one pass (each is mechanical; none changes behavior):

1. `cli.py` — add `import logging` to the top-level stdio imports and replace both `__import__("logging")` calls with `logging` / `logging.getLogger("Schwabdev")`.
2. `cli.py:152-160` — keep the fallback but reframe it as deliberate hardening rather than dead code: sharpen the comment to state the invariant ("production `schwabdev.Client` always invokes the hook when the store is absent; this guards the URL flow if that timing ever changes") and add a focused unit test that exercises the fallback directly (stub client that never calls the hook, assert the URL is printed exactly once). Moving it wholesale into a test fixture is **not** recommended: it would remove real robustness against a schwabdev behavior change for the sake of tidiness, and the cost of keeping it is one `if` and three lines.
3. `renewal.py` — minimal fix (KISS): update the docstring to describe all three responsibilities ("value types (FR-003/FR-008), the `renew` orchestrator with per-store locks, and the store lifetime reader") and hoist the lines 102-114 imports to the top import block. Do **not** split the module in this pass — see Alternatives.
4. `transactions.py:1204,1212` — use the existing enum: `detail=AccountFailureDetail.transient` / `.provider_error`. Skip the `positions.py` half of this row: the post-hoc mutation is already fixed (TD-007), and the raw-dict construction of `accounts_failed_list` is TD-002/TD-007 territory — record it there if it isn't already, don't fix it twice here.
5. `options_chain.py` — change `_PROVIDER_KEY_MAP` to `dict[str, tuple[str, ...]]` of candidate keys, with `trade_time` mapped to `("tradeTime", "tradeTimeInLong")`, and have `serialize_leg` take the first candidate present (`next((contract.get(k) for k in keys if contract.get(k) is not None), None)`). Blast radius is contained: the map and `serialize_leg` are used only inside `options_chain.py` (verified by grep and graph inbound trace).
6. `archive.py:71` — replace the nested `.get` with an explicit merged lookup and a domain error:

   ```python
   data = payloads.get(spec.path) or generated.get(spec.path)
   if data is None:
       raise ReleaseError(f"no payload or generated artifact for member {spec.path}")
   ```

   (careful with `or` vs explicit `in` checks — a legitimately empty payload would be falsy; prefer `spec.path not in payloads and spec.path not in generated` for the error branch).

**Alternatives**:
- *Split `renewal.py` into `renewal_types.py` + `renewal.py`* (report's "split" option): cleaner separation but touches every importer (`cli.py` imports `AuthHealth`, `RenewalOutcome`, `read_store_lifetime`, `renew` from `schwab_mcp.renewal`; tests do the same). Higher blast radius for zero behavior gain — defer unless the module keeps growing.
- *Delete the `cli.py` auth-URL fallback entirely*: simplest code, but re-introduces a silent-no-URL failure mode if schwabdev changes when the hook fires; the fix in §2 is strictly better.

**Files likely to change**:
- `src/schwab_mcp/cli.py`
- `src/schwab_mcp/renewal.py`
- `src/schwab_mcp/transactions.py`
- `src/schwab_mcp/options_chain.py`
- `src/schwab_mcp_release/archive.py`
- `tests/unit/test_release_archive.py` (or equivalent — new error-path test)
- `tests/` for the `serialize_leg` alias and `AccountFailureDetail` construction, if not already covered

**Tests to add or update**:
- Unit test: fallback path in `_run_auth_command` — stub client that never invokes the hook with an absent store; assert `_build_auth_url` result reaches the hook exactly once (locks in §2's reframed invariant).
- Unit test: `serialize_leg` with a contract carrying only `tradeTimeInLong` (existing alias behavior preserved) and only `tradeTime` — guards the key-map change.
- Unit test: `TransactionAccountFailed` construction via enum still serializes `"transient"`/`"provider_error"` in output JSON (coercion equivalence).
- Unit test: `archive` build fails with `ReleaseError` (not `TypeError`) when a member spec has neither a payload nor a generated artifact.

## Risks & Considerations

- **No behavior change intended anywhere** — each fix is refactor-only. The enum change in `transactions.py` relies on pydantic's str-Enum coercion equivalence; the existing full suite should prove it with zero test edits.
- **Circular-import risk** when hoisting `renewal.py` imports: the mid-file block imports `schwab_mcp.tokens`, `provider`, `errors`, `log`. Verify hoisting to the top doesn't create an import cycle (run the suite; the import order was likely incidental, but confirm).
- **`_PROVIDER_KEY_MAP` type change** alters a module-level constant's contract — confirm no external/doc reference assumes `dict[str, str]` (only `docs/`-level mentions of the map, if any).
- **`archive.py` fix must distinguish "missing" from "empty"**: using truthiness (`or`) would misclassify a legitimately empty (0-byte) member source as missing. Use explicit membership checks.
- Item 4 overlaps TD-002/TD-007 — coordinate so the same pattern isn't fixed in two passes with conflicting shapes.
- All six fixes must land with docs updated in the same commit per the constitution (likely only `docs/CHANGELOG.md` is affected).

## Open Questions

- [NEEDS CLARIFICATION: does any test or doc reference the auth-URL fallback as a supported production behavior? If yes, §2's reframe must keep that contract.]
- [NEEDS CLARIFICATION: whether the `positions.py` raw-dict `accounts_failed_list` construction is already tracked under TD-002/TD-007 — if not, it should be added there rather than fixed here.]