# Bug Fix: Release — member list hardcoded twice in `allowlist.py` (DRY)

- **Slug**: td-014
- **Fixed**: 2026-11-04
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Replaced the duplicated member list in `src/schwab_mcp_release/allowlist.py`
with a single `_CONTENT_MEMBER_TABLE` from which both `member_specs()` and
`source_map()` derive, and added an invariant test locking
`source_map()`'s key set to `content_members()`'s path set so any future
one-sided member addition fails loudly in the suite.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp_release/allowlist.py` | modified | Added `_WHEEL` sentinel + `_CONTENT_MEMBER_TABLE` (path, source_rel, provenance) and two private resolvers `_member_path()` / `_member_source()`; `member_specs()` and `source_map()` now derive from the table. Public signatures and provenance wording unchanged. |
| `tests/unit/test_release_allowlist.py` | added test | `TestSources.test_source_map_covers_exactly_the_content_members` — pins the single-table invariant (TD-014). |

## Diff Highlights

The table (7 rows, wheel as the one dynamic entry):

```python
_WHEEL = "<wheel>"

_CONTENT_MEMBER_TABLE: tuple[tuple[str, str, str], ...] = (
    ("README.md", "docs/release/README.md", "docs/release/README.md (verbatim copy)"),
    (_WHEEL, _WHEEL, "runtime wheel (only package schwab_mcp)"),
    ("manuals/installation.md", "docs/release/installation.md", "docs/release/installation.md"),
    ...
    ("install.sh", "src/schwab_mcp_release/install.sh", "src/schwab_mcp_release/install.sh"),
)
```

Both public functions now derive from it:

```python
def member_specs(version):
    content = tuple(
        MemberSpec(_member_path(path, version), True, False, provenance)
        for path, _source_rel, provenance in _CONTENT_MEMBER_TABLE
    )
    return content + (  # generated inventory artifacts, unchanged
        MemberSpec("manifest.json", True, True, "generated: version, build_dirty, member inventory"),
        MemberSpec("SHA256SUMS", True, True, "generated: one sorted line per member"),
    )

def source_map(project_root, version, wheel_path):
    return {
        _member_path(path, version): _member_source(source_rel, project_root, wheel_path)
        for path, source_rel, _provenance in _CONTENT_MEMBER_TABLE
    }
```

## Tests Added or Updated

- `tests/unit/test_release_allowlist.py::TestSources::test_source_map_covers_exactly_the_content_members` — asserts `set(source_map(...)) == {spec.path for spec in content_members(VERSION)}`; converts both desync directions (member added to only one side) into a loud test failure.

## Local Verification

- Commands run:
  - `uv run pytest tests/unit/test_release_allowlist.py -q` (pre-refactor, test-first) → 43 passed — invariant holds before the refactor too, confirming no active desync existed (the test is a regression lock, not a red-first reproduction; the defect is the duplication itself, not a behavioral bug).
  - `uv run pytest tests/unit/test_release_allowlist.py tests/unit/test_release_archive.py tests/unit/test_release_checks.py tests/unit/test_release_checks_dev_material.py tests/unit/test_release_checks_secrets.py -q` (post-refactor) → 80 passed.
  - `uv run pytest -q` (full suite, commit gate) → **1821 passed, 0 skipped**.
- Manual checks: confirmed member order (FR-011) and every `MemberSpec.source` provenance string are byte-identical to the pre-refactor literals (pinned by the existing `test_member_order_is_fixed` and per-source tests).

## Deviations from Assessment

None. The assessment's silent-failure nuance (only the `source_map`-superset
direction is silent) was already documented in the assessment and did not
change the fix. Test-first note: the new invariant test is green before and
after the refactor — expected for a behavior-preserving DRY refactor; the
existing suite (order, provenance, per-path sources) served as the red/green
contract.

## Follow-ups

- Commit with the full suite green and no skipped tests (constitution gate); affected docs updated in the same commit (none required — the module docstring's DRY claim is now accurate as written).
- `/speckit.bug.test slug=td-014` to verify the fix independently.