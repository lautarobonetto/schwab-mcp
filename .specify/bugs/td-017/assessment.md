# Bug Assessment: TD-017 — Unused imports and members

- **Slug**: td-017
- **Created**: 2026-11-04
- **Source**: pasted text (verbatim table from `docs/tech-debt.md` §TD-017, "Unused imports and members")
- **Verdict**: valid (6 of 9 rows confirmed against current code; 3 rows stale — see below)
- **Severity**: low

## Report (verbatim or summarized)

Pasted table (identical to `docs/tech-debt.md` lines 601–611) listing nine
unused imports / dead members:

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

## Symptom

No runtime misbehavior: this is a dead-code / hygiene tech-debt item. Unused
imports and unreachable members accumulate maintenance cost, can mislead
readers (`retry_once`, `Config.__getitem__` look like supported API surface),
and hand-maintained duplicates (`ALL_TRANSACTION_TYPES`) can silently drift
from the enum they mirror. Expected state: every import and public member in
`src/` has at least one consumer.

## Reproduction

Static-only; each claim is checkable by reading the code:

1. `grep -n "time\." src/schwab_mcp/positions.py` → no matches (only the
   `timespec=` kwarg at line 266, which is not the `time` module) →
   `import time` at line 10 unused. ✅
2. `grep -n "\bF\b" src/schwab_mcp/tokens.py` → only the definition at line 18;
   `retry_call` (line ~355) annotates `Callable[..., Any]`, never `F`. ✅
3. `grep -rn "retry_once" src tests` → no `src/` callers; only docstring
   mentions in `tests/integration/test_failures.py:736,782` and
   `tests/performance/test_startup_budget.py:28`. Knowledge-graph
   `trace_path(retry_once, inbound)` confirms `callers_total: 0`. ✅
4. `grep -n "datetime\|timezone" src/schwab_mcp/renewal.py` → only the import
   itself at line 106 (inside the mid-file "Store lifetime reader" import
   block, lines ~101–108). ✅
5. `grep -rn "__getitem__\|Config\[" src tests` → only the definition;
   graph shows `Config.__getitem__` (`config.py:36-37`) with in-degree 0. ✅
6. `src/schwab_mcp/transactions.py:241-247` — `ALL_TRANSACTION_TYPES` is a
   hardcoded string that repeats the 15 `ProviderTransactionType` values
   (character-for-character, same order). ✅
7. **Stale rows** (claims that no longer hold at HEAD):
   - `positions.py:13 List` — **used** at line 299
     (`accounts_failed: Optional[List[AccountFailed]] = None`). Only a style
     inconsistency remains (`list[...]` lowercase is used at line 138).
   - `renewal.py:102, 389 import os as _os` — the duplication existed before
     commit `e3e5466` (verified via `git show e3e5466^`, lines 102/389/392)
     and was removed by the v0.9.8 refactor. Current code has a single
     `import os` at line 103, used at line 365 (`os.PathLike`).
   - `transactions.py:1191-1205 dead partial_failure branch` — consolidated
     by TD-005 (fixed v0.9.8, 2026-11-04): the code at ~line 1253 now carries
     the comment "Single partial-failure branch (TD-005)" and the duplicated
     branch no longer exists. The tech-debt doc was committed *after* the
     fix but still lists the row.

## Suspected Code Paths

- `src/schwab_mcp/positions.py:10` — `import time` unused ✅
- `src/schwab_mcp/positions.py:13` — `List` claim incorrect (used at 299) ❌
- `src/schwab_mcp_release/allowlist.py:19` — `Mapping` imported, never used ✅
- `src/schwab_mcp/tokens.py:18` — `F = TypeVar(...)` never used ✅
- `src/schwab_mcp/tokens.py:380-385` — `retry_once()` wrapper, 0 callers ✅
- `src/schwab_mcp/renewal.py:106` — unused mid-file `datetime`/`timezone`
  import (whole block at 101–108 is a duplicated mid-file import section) ✅
- `src/schwab_mcp/renewal.py:102,389` — `_os` duplication no longer exists ❌
- `src/schwab_mcp/config.py:36-37` — `Config.__getitem__`, 0 callers ✅
- `src/schwab_mcp/transactions.py:241-247` — `ALL_TRANSACTION_TYPES` hardcoded
  duplicate of the enum (consumed once, at line 1082, as the upstream
  `types` filter argument) ✅
- `src/schwab_mcp/transactions.py:1191-1205` — dead branch already removed by
  TD-005 ❌

## Root Cause Hypothesis

Confidence: high (directly verified by reads, greps, git history, and the
codebase knowledge graph). These are ordinary accumulation artifacts: APIs
generalized away (`retry_once` → `retry_call`), refactors that orphaned
imports (`_os`, partial_failure branch), and one speculative member
(`Config.__getitem__`) plus one hand-maintained constant duplicating an enum.
Three of the nine rows are stale because the v0.9.8 refactor (commit
`e3e5466`, same day) fixed them after the audit snapshot was taken.

## Proposed Remediation

**Preferred**: A single cleanup commit that deletes the six confirmed dead
items and derives `ALL_TRANSACTION_TYPES` from the enum, per row:

1. `positions.py`: delete `import time` (line 10). Leave `List` (used); the
   `Optional[List[AccountFailed]]` → `Optional[list[AccountFailed]]`
   normalization is a one-line style fix that may ride along.
2. `allowlist.py`: delete `from collections.abc import Mapping` (line 19).
3. `tokens.py`: delete the `F` TypeVar (line 18) — `retry_call` does not
   annotate with it; adding the annotation would be speculative (KISS).
4. `tokens.py`: delete `retry_once()` (lines 380–385). Its only references
   are docstrings — update those mentions (see tests below); no functional
   test changes are required since no test calls it directly.
5. `renewal.py`: delete `from datetime import datetime, timezone` (line 106);
   while there, the mid-file import block (101–108) duplicates module-top
   imports and can be merged upward — optional, keep minimal if desired.
6. `config.py`: delete `Config.__getitem__` (lines 36–37).
7. `transactions.py`: replace the hardcoded string with
   `ALL_TRANSACTION_TYPES = ",".join(t.value for t in ProviderTransactionType)`
   — verified to produce the identical 15-value, same-order string.
8. `docs/tech-debt.md`: mark the six confirmed TD-017 rows fixed (the doc's
   established `~~strikethrough~~ Fixed (TD-0xx, vX.Y.Z)` pattern) and
   correct/strike the three stale rows (`List`, `_os`, dead branch) with a
   note that they were already resolved by the v0.9.8 refactor.

**Alternatives** (optional):
- Instead of deleting the `F` TypeVar, annotate `retry_call` with
  `Callable[P, R]`-style generics — more typing rigor, but no current
  consumer needs it; contradicts KISS. Not recommended.
- Instead of deleting `retry_once`, mark it with a deprecation shim —
  unnecessary: it is internal-only with zero callers.
- Add a lint gate (e.g. `ruff check --select F401,F811,F841`) to CI to stop
  recurrence — worthwhile follow-up, but out of scope for this fix.

**Files likely to change**:
- `src/schwab_mcp/positions.py`
- `src/schwab_mcp_release/allowlist.py`
- `src/schwab_mcp/tokens.py`
- `src/schwab_mcp/renewal.py`
- `src/schwab_mcp/config.py`
- `src/schwab_mcp/transactions.py`
- `docs/tech-debt.md`
- `tests/integration/test_failures.py` (docstring mentions of `retry_once`)
- `tests/performance/test_startup_budget.py` (docstring mention)

**Tests to add or update**:
- No new functional tests needed (pure deletions + constant derivation);
  full suite must stay green (commit gate).
- Update docstring/comment references to `retry_once` in
  `tests/integration/test_failures.py` (lines 736, 782) and
  `tests/performance/test_startup_budget.py` (line 28) to name `retry_call`.
- Optional: a small unit test asserting `ALL_TRANSACTION_TYPES == ",".join(
  t.value for t in ProviderTransactionType)` and `len(...split(",")) == 15`
  to lock the derivation against future enum edits.

## Risks & Considerations

- **Low overall** — all targets are internal, with zero verified callers
  (graph + grep). `Config` and `retry_once` are not part of the MCP tool
  interface (`docs/tools.md`), so no external API breakage.
- `ALL_TRANSACTION_TYPES` derivation must preserve the exact 15-value order —
  verified identical to the current string; the optional unit test locks it.
- Historical references in `docs/CHANGELOG.md` and `specs/002-*` mention
  `retry_once` — leave them untouched (they document history, not current
  code).
- Constitution gates apply: TDD not applicable to deletions, but the full
  suite must be green, no skipped tests, and `docs/tech-debt.md` updated in
  the same commit.

## Open Questions

- None blocking. (Whether to also merge the duplicated mid-file import block
  in `renewal.py:101-108` upward is a style call for the fix phase; and
  whether to add the ruff F401 lint gate is a follow-up decision.)
