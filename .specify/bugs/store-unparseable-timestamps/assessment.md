# Bug Assessment: structurally valid store with unparseable timestamps crashes `renew` (exit 1) and misleads `serve` (exit 2) instead of classifying `store_corrupted`

- **Slug**: store-unparseable-timestamps
- **Created**: 2026-11-03
- **Source**: pasted text (follow-up registered during the live verification of bug `renew-phantom-success`; observed in the user's terminal at ~19:21 CST)
- **Verdict**: valid
- **Severity**: low

## Report (verbatim or summarized)

While manually reproducing `renew-phantom-success`, the store's
`access_token_issued` was set to an epoch number (`1793726428`) that SQLite
stored as TEXT (column affinity) — a structurally valid store whose
timestamps are not ISO-8601 strings. Observed live:

```text
% uv run schwab-mcp renew; echo "exit=$?"
Unexpected error: Invalid isoformat string: '1793726428'
exit=1

% uv run schwab-mcp serve; echo "exit=$?"
Fix the values in your environment
exit=2
```

No URL supplied — no fetch performed, URL Trust Policy not applicable.

## Symptom

A token store that is valid SQLite with a populated `schwabdev` row but has
non-ISO-parseable timestamp values makes `renew` die with a raw library
exception (`Unexpected error: Invalid isoformat string: ...`, exit 1) and
`serve` exit 2 with the misleading message "Fix the values in your
environment" (a config error). Expected: both classify the store as
corrupted per the existing contracts — `renew` → exit 3 with
`detail: store_corrupted`, `serve` → exit 5 `TokenStoreCorruptedError`
("Store treated as absent; run `schwab-mcp auth`") — because FR-009
mandates corrupted stores are treated as absent, never a crash.

## Reproduction

1. Back up `~/.schwab-mcp/tokens.db`.
2. Corrupt only the timestamp format, keeping the store structurally valid:
   ```sh
   sqlite3 ~/.schwab-mcp/tokens.db \
     "UPDATE schwabdev SET access_token_issued = '1793726428';"
   ```
3. `uv run schwab-mcp renew` → `Unexpected error: Invalid isoformat
   string: '1793726428'`, exit 1.
4. `uv run schwab-mcp serve` → `Fix the values in your environment`, exit 2.
5. Restore the backup.

Observed live 2026-11-03 (~19:21 CST). `[NEEDS CLARIFICATION: whether the
same crash class also fires for a NULL/absent timestamp value, and for
`expires_in` of the wrong type — the same root cause makes that likely,
but only the timestamp-text variant was observed.]`

## Suspected Code Paths

- `.venv/.../schwabdev/tokens.py:166-169` (`Tokens._parse_dt`) —
  `datetime.fromisoformat(value)` with **no error handling**, called from
  `_load_tokens_from_db` (line 187-188) during `Client.__init__`. This is
  the actual raise site ("Invalid isoformat string: '1793726428'"); a
  third-party library, not modifiable in this repo.
- `src/schwab_mcp/tokens.py:54-85` (`peek_store_status`) — the tri-state
  classifier defines "corrupted" as *structural* validity only (SQLite
  opens + `SELECT 1 FROM schwabdev` returns a row). It never inspects the
  row's *content contract* (ISO-parseable `access_token_issued` /
  `refresh_token_issued`), so a value-uncorrupted-in-shape store is
  classified `"present"` and sent onward to client construction.
  **Primary root cause on our side.**
- `src/schwab_mcp/tokens.py:20-51` (`peek_store`) — same shape-only check
  (used by `auth` for fresh-write evidence); harmless there, but shares
  the assumption.
- `src/schwab_mcp/cli.py:301-334` (`_do_run_renew`) — builds
  `schwabdev.Client(...)` *after* the peek; the library's ValueError
  propagates to the generic handler (`cli.py` main dispatch) →
  "Unexpected error: ..." exit 1. No classification opportunity.
- `src/schwab_mcp/server.py:92-111` — same: client construction wrapped
  with `except ValueError → InvalidConfigError("Fix the values in your
  environment: ...")` → exit 2, actively misdiagnosing a store problem as
  a config problem.
- `src/schwab_mcp/renewal.py:385-405` (`_issued_to_epoch`) — our own
  reader is *more lenient* than the loader (accepts numeric epochs) and
  correctly swallows parse errors; it already models the contract the peek
  should enforce, but it runs too late to prevent the client-construction
  crash. Also note the leniency divergence: schwabdev requires ISO text,
  so numeric values must be classified corrupted even though our reader
  tolerates them.
- Recovery paths that already behave correctly (no change needed):
  `auth` (quarantine + forced fresh flow; observed working at 19:21) and
  `auth-status` (`read_store_lifetime` → None → `reauth_required` exit 3).

## Root Cause Hypothesis

**Confidence: high.** `peek_store_status`'s "corrupted" definition covers
structural validity (openable SQLite, `schwabdev` table, non-empty row)
but not the row's data contract, while the only real consumer of the row
(schwabdev's `Tokens._load_tokens_from_db`) requires `*_token_issued` to
be ISO-8601 text and parses it unguarded during `Client.__init__`. A store
that satisfies the structural check but violates the data contract passes
the peek, reaches client construction, and raises an unclassifiable
ValueError — which the CLI then maps to the wrong buckets (exit 1 raw
error for `renew`; exit 2 config error for `serve`). The classification
gap is on our side; the crash itself lives in the bundled library.

## Proposed Remediation

**Preferred**: strengthen `peek_store_status` (`src/schwab_mcp/tokens.py`)
so that a store whose `schwabdev` row cannot actually be loaded is
classified `"corrupted"`, before any client construction happens:

1. In `peek_store_status`, after confirming a row exists, read
   `expires_in, access_token_issued, refresh_token_issued` and require:
   the row to have all columns, and both `*_token_issued` values to parse
   as ISO-8601 via `datetime.fromisoformat` (mirroring schwabdev's
   `_parse_dt` semantics: ISO text, naive treated as UTC). Any
   parse/shape failure → `"corrupted"`.
2. Single source of truth: today the ISO-parse logic lives in
   `renewal._issued_to_epoch` (guarded, lenient). Move/extract the
   "parse an issued timestamp" helper into `tokens.py` (the store module)
   and have `renewal.py` import it, so the peek and the lifetime reader
   share one definition (Constitution II). Keep the helper's *lenient*
   numeric branch only if the caller needs it — the peek's criterion must
   be the **strict** one (ISO-parseable) because that is what the real
   loader accepts; numeric-epoch values are, per the observed behavior,
   corrupted for the client even though our reader tolerates them.
3. With the peek fixed, every existing consumer recovers correctly with
   zero extra changes: `run_renew` → `reauth_required`/
   `store_corrupted` exit 3; `run_serve` → `TokenStoreCorruptedError`
   exit 5; `run_auth` → quarantine (preserved for forensics, FR-009) +
   fresh authorization flow; `auth-status` → `reauth_required` exit 3.

**Alternatives:**

- Catch `ValueError` around `schwabdev.Client(...)` in
  `_do_run_renew`/`server.py` and re-raise as `TokenStoreCorruptedError`
  when the message looks like an isoformat failure. Rejected: string-
  matching library exception text is fragile and leaks library internals
  into our error mapping; also leaves `auth-status` and `auth` semantics
  untouched/inconsistent.
- Patch/vendor schwabdev's `_parse_dt` to be tolerant. Rejected: modifies
  the bundled dependency surface and merely postpones the crash to the
  first use of the bogus timestamp; classification should happen at the
  peek, where all five consumers already share one decision point.

**Files likely to change:**

- `src/schwab_mcp/tokens.py` (`peek_store_status`; new/moved strict
  timestamp-parse helper)
- `src/schwab_mcp/renewal.py` (`_issued_to_epoch` delegates to the shared
  helper — keep `read_store_lifetime` behavior unchanged)
- `docs/tools.md` / `specs/002-automated-token-renewal/contracts/cli.md`
  (clarify that `store_corrupted` also covers unparseable timestamp
  values, not only structural damage) + `docs/CHANGELOG.md`
- Tests: `tests/unit/test_tokens.py` (peek status), 
  `tests/unit/test_tokens_quarantine.py` (corrupted classification),
  `tests/unit/test_renewal.py` (lifetime reader unchanged),
  `tests/integration/test_failures.py` (renew/serve exit codes for this
  corruption shape)

**Tests to add or update:**

- `peek_store_status`: valid SQLite + schwabdev row with epoch-text
  `access_token_issued` → `"corrupted"`; with NULL `refresh_token_issued`
  → `"corrupted"`; with valid ISO strings → `"present"` (guard against
  over-classification).
- `renew` CLI integration: corrupted-timestamp store → exit 3, stdout
  `{"outcome":"reauth_required",...,"detail":"store_corrupted"}` — no
  raw exception text, no exit 1.
- `serve` CLI integration: corrupted-timestamp store → exit 5
  (`TokenStoreCorruptedError`), actionable message, no "Fix the values in
  your environment".
- `read_store_lifetime` on the same store → still `None` (behavior
  unchanged after the helper refactor).
- `auth` quarantine path: unparseable-timestamp store gets quarantined
  and the flow proceeds (mirrors the auth-corrupt-store-blocked bug's
  contract).

## Risks & Considerations

- **Over-classification risk**: a *legitimate* store written by a future
  schwabdev version with a different timestamp format would now read as
  corrupted and trigger quarantine on `auth` (FR-009 keeps the original
  file for forensics, so recovery is a re-auth — acceptable, and strictly
  better than the current exit-1 crash).
- **Leniency divergence**: `_issued_to_epoch` currently accepts numeric
  epochs while the strict peek will reject them; after the refactor the
  two criteria must be explicit (strict = loader contract, lenient =
  reader tolerance) or the peek may flag stores our own reader would
  accept. Decide during planning; document the chosen rule.
- **Contract surface**: `store_corrupted` semantics widening is covered by
  existing exit codes and details — no new enum values; only prose/doc
  updates needed.
- **Credential safety**: quarantine and error paths must continue to
  never log store contents (existing redaction filter stays in place).

## Open Questions

- [NEEDS CLARIFICATION: should NULL `expires_in` (present in the row but
  NULL) also classify as corrupted, or is it loadable by schwabdev?
  Needs a quick look at where schwabdev uses `expires_in` before
  deciding the strict rule's exact column set.]
- [NEEDS CLARIFICATION: was the epoch-text store produced only by the
  manual test, or could any real producer (older schwabdev version,
  external tool) write numeric epochs? If a real producer exists, the
  strict classification turns their stores into quarantine-on-auth —
  still safe, but worth knowing for the changelog note.]