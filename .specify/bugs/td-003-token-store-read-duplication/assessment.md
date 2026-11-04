# Bug Assessment: TD-003 — SQLite token-store read triplicated (DRY)

- **Slug**: td-003-token-store-read-duplication
- **Created**: 2026-11-04
- **Source**: pasted text
- **Verdict**: valid (tech-debt / DRY violation, not a runtime defect)
- **Severity**: low

## Report (verbatim or summarized)

> **TD-003 — SQLite token-store read triplicated (DRY)**
>
> **Area:** `src/schwab_mcp/tokens.py:75-98, 126-161`, `src/schwab_mcp/renewal.py:391-417`
>
> Three functions repeat the same block: `os.stat` → `st_size == 0` check →
> `sqlite3.connect(f"file:{path}?mode=ro", uri=True)` → query → `finally: con.close()`.
> Worse, `peek_store_status` and `read_store_lifetime` run the **exact same query**:
> `SELECT expires_in, access_token_issued, refresh_token_issued FROM schwabdev LIMIT 1`
> (`renewal.py:407-409` vs `tokens.py:142-144`; `read_store_lifetime`'s docstring even
> says it "uses the same pattern" — copy, not reuse). `peek_store` (bool) is subsumed
> by `peek_store_status(...) != "absent"`; its only src callers are `cli.py:157,169`.
>
> **Refactor:** one private helper in `tokens.py`, e.g.
> `_read_schwabdev_row(path) -> tuple | None` (distinguishing absent vs corrupted),
> consumed by `peek_store_status`, `read_store_lifetime`, and the store check in
> `run_auth`. Delete `peek_store` or keep it as a one-line alias.

## Symptom

No runtime misbehavior — this is maintainability debt: the "open read-only SQLite
store and read the schwabdev row" pattern is copy-pasted three times, with two of
the copies running an identical SQL query. A future change to the store-read
contract (e.g. schema evolution, corruption semantics) must be replicated in three
places or the copies silently diverge.

## Reproduction

Static-verification steps (confirmed by reading source):

1. Read `src/schwab_mcp/tokens.py:67-98` (`peek_store`) and `:126-161` (`peek_store_status`) — both contain the same `os.stat` → size check → `sqlite3.connect(..., mode=ro)` → query → `finally: con.close()` block.
2. Read `src/schwab_mcp/renewal.py:378-406` (`read_store_lifetime`) — same block again; query at `renewal.py:396-399` is textually identical to `tokens.py:142-145` (`SELECT expires_in, access_token_issued, refresh_token_issued FROM schwabdev LIMIT 1`).
3. `grep 'peek_store\b' src/` shows `peek_store`'s only source callers are `cli.py:157` and `cli.py:169` (the auth flow); `tokens.py:174` and `cli.py:122` reference it only in comments/docstrings. `server.py:105`, `cli.py:103,223,276` already use `peek_store_status`.

[NEEDS CLARIFICATION: none — fully verified statically.]

## Suspected Code Paths

- `src/schwab_mcp/tokens.py:67-98` — `peek_store`: bool-returning copy of the store-read block (`SELECT 1 FROM schwabdev LIMIT 1`).
- `src/schwab_mcp/tokens.py:126-161` — `peek_store_status`: tri-state copy; identical block plus ISO-timestamp validation on the fetched row.
- `src/schwab_mcp/renewal.py:365-416` — `read_store_lifetime`: third copy; identical block and query; docstring at `:368` explicitly says it "uses the same SQLite read pattern … (no schema duplication)" while actually duplicating the whole pattern.
- `src/schwab_mcp/cli.py:157,169` — the two `peek_store` call sites inside `run_auth`'s success-determination logic (consumers of the consolidated helper / alias).

## Root Cause Hypothesis

High confidence. `peek_store` was the original store probe; when bug
`store-unparseable-timestamps` required tri-state status, `peek_store_status` was
added alongside it (and `backup_token_store` at `tokens.py:183` and the corrupted
path at `tokens.py:266` migrated to it), leaving `peek_store` with only the two
`cli.py` callers. `read_store_lifetime` was then written in `renewal.py` copying
the pattern rather than sharing it. The duplication is real and the report's
line references are accurate (within a few lines; query spans 142-145/396-399).

## Proposed Remediation

**Preferred**: Introduce a single private helper in `tokens.py` that encapsulates
the open-and-read contract, e.g.:

```python
def _read_schwabdev_row(path) -> tuple[str, tuple | None]:
    """Return ("absent", None) | ("corrupted", None) | ("present", row)."""
```

(Either a `(status, row)` pair or a small named result; the report's bare
`tuple | None` signature cannot express the absent-vs-corrupted distinction both
consumers need.) Then:

- `peek_store_status` becomes: call helper; if corrupted → "corrupted"; if
  row None → "absent"; else run the existing ISO-timestamp validation →
  "present"/"corrupted".
- `read_store_lifetime` in `renewal.py` becomes: call helper; map
  absent/corrupted → `None`; else compute lifetimes from the row (keeping
  `tokens.issued_to_epoch` as the parse single source of truth per the note at
  `renewal.py:427-429`). Delete the duplicated `os`-import block and query.
- `peek_store`: delete it and replace the two `cli.py:157,169` call sites with
  `peek_store_status(config.token_db) != "absent"` (per the report, `peek_store`
  is subsumed by that check). Removing the function entirely is the cleaner DRY
  outcome; keeping it as a one-line alias is acceptable if test churn is a concern.
  Careful at `cli.py:157`: today `peek_store` returns False for a *corrupted*
  store, while `!= "absent"` would be True there. That is the correct semantic
  change (a corrupted store proves the client ran and wrote something), but the
  decision must be made consciously and covered by a test.

**Alternatives**:
- Keep `peek_store` as a one-line wrapper (`peek_store_status(path) != "absent"`)
  — least churn, but note it subtly changes `peek_store`'s bool for corrupted
  stores (False → True); the wrapper's docstring must state this.
- Leave as-is with a cross-reference comment only — rejected: violates
  Constitution II (DRY / one implementation per piece of knowledge) for a
  three-way copy of a schema-sensitive query.

**Files likely to change**:
- `src/schwab_mcp/tokens.py`
- `src/schwab_mcp/renewal.py`
- `src/schwab_mcp/cli.py`
- `tests/unit/test_tokens.py` (imports and exercises `peek_store` directly at lines 25, 65-107)
- `tests/unit/test_tokens_quarantine.py`, `tests/integration/test_serve.py` (only comment references; likely no change)

**Tests to add or update**:
- Characterization tests for `_read_schwabdev_row` tri-state: missing file, empty file, non-SQLite bytes, wrong schema, empty table, valid row.
- Equivalence tests: `peek_store_status` and `read_store_lifetime` results unchanged for all the above fixtures (corruption/absence mapping preserved).
- `run_auth` tests at the two former `peek_store` call sites, including the corrupted-store case (new behavior after the `!= "absent"` switch).
- Update `tests/unit/test_tokens.py` peek-store tests to the new surface (or delete them with the function).

## Risks & Considerations

- **Semantic drift at `cli.py:157,169`**: replacing `peek_store` with
  `peek_store_status(...) != "absent"` changes behavior for *corrupted* stores
  (bool flips). It is almost certainly an improvement, but it touches the
  `auth-false-success` success-gating logic — a regression test is mandatory.
- **Corruption mapping asymmetry**: `read_store_lifetime` currently maps
  `OSError/ValueError` on stat to `None` (same as absent), while
  `peek_store_status` maps it to "corrupted". The helper must pick one canonical
  mapping and both consumers must be audited against it (the stat-exception
  branch is the only place the copies disagree).
- **Import direction**: helper lives in `tokens.py`; `renewal.py` already imports
  from `tokens` (single-source-of-truth note at `renewal.py:427-429`), so no new
  cycle.
- **API surface**: `peek_store` is exported via `cli.py`'s import list; if
  deleted, check no doc references outside comments (`tokens.py:174`,
  `cli.py:122`, `tests/integration/test_serve.py:772` mention it in prose).
- **Docs**: `docs/tools.md` / changelog may reference `peek_store`; constitution
  requires affected docs updated in the same commit.

## Open Questions

- None blocking. The only design decision is delete-vs-alias for `peek_store`
  and the corrupted-store semantics at `cli.py:157` — both flagged above.