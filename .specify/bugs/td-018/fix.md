# Bug Fix: TD-018 — Obscured imports and readability nits

- **Slug**: td-018
- **Fixed**: 2026-11-04
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Applied all six remediation items from the assessment: plain `import logging` in `cli.py`, reframed (kept) the auth-URL fallback with a pinning test, corrected the `renewal.py` docstring and hoisted mid-file imports, enum-based failure-detail construction in `transactions.py`, candidate-key alias handling in `options_chain.py`, and an explicit domain-error lookup in `archive.py`. TDD: the archive error-path test was written first and failed with the exact cryptic `TypeError` the assessment predicted, then went green with the fix; the other three new tests pin behavior that must not regress.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/cli.py` | modified | `import logging` added to top-level stdio imports; both `__import__("logging")` calls (main(), lines ~425-426) replaced; fallback comment reframed as deliberate hardening per the assessment (fallback kept, not moved to a fixture) |
| `src/schwab_mcp/renewal.py` | modified | Module docstring now describes all three responsibilities (value types, orchestrator + locks, store lifetime reader); the mid-file import block (old lines 102-114) hoisted to the top import section; misplaced "Store lifetime reader" banner renamed to "Renewal orchestrator and per-store-path single-flight locks" and a correct banner added before `StoreLifetime` |
| `src/schwab_mcp/transactions.py` | modified | `AccountFailureDetail` imported from `schwab_mcp.results`; the two `TransactionAccountFailed` constructions now pass `AccountFailureDetail.transient` / `.provider_error` instead of raw strings |
| `src/schwab_mcp/options_chain.py` | modified | `_PROVIDER_KEY_MAP` retyped to `dict[str, tuple[str, ...]]` with candidate keys in precedence order; `trade_time` maps to `("tradeTime", "tradeTimeInLong")`; `serialize_leg` takes the first candidate present via `next(...)`; the `trade_time` special-case branch removed |
| `src/schwab_mcp_release/archive.py` | modified | `archive.py:71` nested `.get` preceded by an explicit membership check raising `ReleaseError("no payload or generated artifact for archive member <path>")` instead of the cryptic `zipfile` `TypeError` |
| `tests/unit/test_release_archive.py` | added test | `TestMemberLookupRobustness::test_member_in_neither_dict_raises_release_error` (red before the fix: `TypeError: object of type 'NoneType' has no len()`) |
| `tests/unit/test_options_chain_mapping.py` | added tests | `test_trade_time_in_long_alias_only_is_converted`, `test_trade_time_takes_precedence_over_alias` |
| `tests/unit/test_results_shared_taxonomy.py` | added test | `test_enum_construction_serializes_canonical_values` |
| `tests/integration/test_auth.py` | added test | `TestAuthUrlFallbackForInertClient::test_fallback_prints_url_once_and_never_reports_success` |

## Diff Highlights

`options_chain.py` — the special case is now data in the map:

```python
"trade_time": ("tradeTime", "tradeTimeInLong"),
...
raw = next(
    (
        contract.get(key)
        for key in _PROVIDER_KEY_MAP[name]
        if contract.get(key) is not None
    ),
    None,
)
```

`archive.py` — domain error instead of a `zipfile` `TypeError`:

```python
if spec.path not in payloads and spec.path not in generated:
    raise ReleaseError(
        f"no payload or generated artifact for archive member {spec.path}"
    )
```

## Tests Added or Updated

- `tests/unit/test_release_archive.py::TestMemberLookupRobustness::test_member_in_neither_dict_raises_release_error` — a member spec covered by neither dict fails with `ReleaseError` naming the member (was: cryptic `TypeError`).
- `tests/unit/test_options_chain_mapping.py::TestSerializeLeg::test_trade_time_in_long_alias_only_is_converted` — alias-only contracts still convert to ISO-8601 after the key-map change.
- `tests/unit/test_options_chain_mapping.py::TestSerializeLeg::test_trade_time_takes_precedence_over_alias` — canonical `tradeTime` wins when both spellings are present.
- `tests/unit/test_results_shared_taxonomy.py::TestAccountFailedShared::test_enum_construction_serializes_canonical_values` — enum construction keeps the canonical serialized values `"transient"` / `"provider_error"`.
- `tests/integration/test_auth.py::TestAuthUrlFallbackForInertClient::test_fallback_prints_url_once_and_never_reports_success` — with a client that never invokes the hook and an absent store, the CLI fallback prints the URL exactly once and never reports success; locks in the fallback as deliberate hardening.

## Local Verification

- Commands run: `uv run pytest tests/unit/test_release_archive.py tests/unit/test_options_chain_mapping.py tests/unit/test_results_shared_taxonomy.py tests/integration/test_auth.py -q` → 111 passed (before the fix: the new archive test failed with the predicted `TypeError`, the three pinning tests passed).
- Commands run: `uv run pytest -q` → **1833 passed, 0 skipped, 0 failed** (full suite, commit-gate green).
- Circular-import check for the `renewal.py` import hoist: only `cli.py` imports `schwab_mcp.renewal` (verified by grep); hoisted imports (`errors`, `log`, `provider`, `tokens`) do not import `renewal` — no cycle, confirmed by the green suite.

## Deviations from Assessment

- `renewal.py`: in addition to the docstring fix and import hoist, the misplaced section banner ("Store lifetime reader" sitting above the orchestrator locks) was renamed to "Renewal orchestrator and per-store-path single-flight locks" and a correct banner added before `StoreLifetime`. Same item, same spirit — the banner was part of the "module holds more than the docstring says" confusion.
- Everything else followed the assessment's preferred remediation exactly, including keeping the auth-URL fallback (reframed, with a pinning test) rather than moving it to a test fixture.

## Follow-ups

- The `positions.py` raw-dict `accounts_failed_list` construction remains TD-002/TD-007 territory — confirm it is tracked there (see assessment Open Questions).
- When committing, update `docs/CHANGELOG.md` in the same commit per the constitution.
- Consider whether the `positions.py`/`transactions.py` taxonomy unification (TD-002) can reuse the now-enum-typed construction as its precedent.

## Open Questions (from assessment, carried forward)

- [NEEDS CLARIFICATION: does any test or doc reference the auth-URL fallback as a supported production behavior? The new pinning test now defines that contract explicitly.]
- [NEEDS CLARIFICATION: whether the `positions.py` raw-dict construction is already tracked under TD-002/TD-007.]