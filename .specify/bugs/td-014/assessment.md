# Bug Assessment: Release — member list hardcoded twice in `allowlist.py` (DRY)

- **Slug**: td-014
- **Created**: 2026-11-04
- **Source**: pasted text (TD-014 — "Release: member list hardcoded twice (DRY)")
- **Verdict**: valid
- **Severity**: low

## Report (verbatim or summarized)

> **TD-014 — Release: member list hardcoded twice (DRY)**
> **Area:** `src/schwab_mcp_release/allowlist.py:44-60` vs `68-79`
>
> The same member set (`README.md`, `dist/<wheel>`, `manuals/*.md` x4, `install.sh`) exists once as `MemberSpec`s and once as the source map. Adding a manual requires editing two synchronized places; desync breaks the build silently. The module docstring proclaims "one authoritative member list, no duplication".
>
> **Refactor:** one table `(_MEMBER_PATH, _SOURCE_REL, _PROVENANCE)` from which both `member_specs()` and `source_map()` derive; generated members (`manifest.json`, `SHA256SUMS`) stay separate as today.

## Symptom

The 7 content members of the release archive are declared twice in
`src/schwab_mcp_release/allowlist.py`: once as `MemberSpec` tuples inside
`member_specs()` (lines 47–57) and once as dict keys inside `source_map()`
(lines 72–78). The two literals are currently in sync, but nothing enforces
that; the module docstring (line 5) claims "one authoritative member list, no
duplication" while the file itself duplicates the list. This is a
maintainability/latent-defect issue, not an active runtime failure — today
both literals match, so no archive is wrong.

## Reproduction

Not a runtime bug; reproduces as a code-reading finding:

1. Open `src/schwab_mcp_release/allowlist.py`.
2. Read `member_specs()` (lines 44–60): seven content `MemberSpec`s plus two
   generated (`manifest.json`, `SHA256SUMS`).
3. Read `source_map()` (lines 68–79): the same seven archive paths appear
   again as dict keys with their on-disk sources.
4. Observe that adding a manual (e.g. `manuals/quickstart.md`) requires
   editing both functions; forgetting one produces either a loud build error
   or a **silent omission** (see Root Cause Hypothesis).

## Suspected Code Paths

- `src/schwab_mcp_release/allowlist.py:44-60` — `member_specs()`: first copy of
  the member list (7 content members + 2 generated, fixed order).
- `src/schwab_mcp_release/allowlist.py:68-79` — `source_map()`: second copy of
  the same 7 paths, mapped to on-disk source files.
- `src/schwab_mcp_release/allowlist.py:1-14` — module docstring asserts the
  DRY contract the code violates.
- `src/schwab_mcp_release/archive.py:55-58` — `assemble_archive()` iterates
  `content_members()` and does `sources.get(spec.path)`; a content member
  missing from `source_map` raises `ReleaseError` (loud direction).
- `src/schwab_mcp_release/cli.py:91-103` — `cmd_build()` builds the source map
  and passes it to `assemble_archive()`; extra entries in `source_map` are
  never validated against the member list (silent direction).

Blast radius (graph-verified, 5 inbound callers of `member_specs`, 3 of
`source_map`): `allowlist.content_members`, `archive.assemble_archive`,
`checks.check_completeness`, `cli.cmd_build` (in `cli.py`). Public signatures
must stay unchanged so callers and the 5 test modules importing these
functions are untouched.

## Root Cause Hypothesis

The member list was authored twice — once as ordered `MemberSpec`s (which also
carry human-readable provenance strings quoted from
`specs/009-mcp-release-packaging/contracts/archive-layout.md`) and once as a
`path → Path` dict — because `MemberSpec.source` is a *description* while
`source_map()` needs an actual filesystem path. The report's proposed single
table `(_MEMBER_PATH, _SOURCE_REL, _PROVENANCE)` covers both derivations.
Confidence: **high** (duplication verified by direct read; failure modes
verified in `archive.py:56-58` and `cli.py:92-95`).

One precision on the report's claim "desync breaks the build silently": it is
asymmetric —

- member added to `member_specs()` but **not** to `source_map()`: build fails
  loudly (`ReleaseError: missing source file for member ...`, `cmd_build`
  exits 3).
- member added to `source_map()` but **not** to `member_specs()`: the extra
  source is silently ignored — the file is never shipped, and
  `check_completeness()` passes because its expected set is itself derived
  from `member_specs()`. **This** is the silent-breakage direction.

## Proposed Remediation

**Preferred**: Replace both literals with a single module-level table:

```python
# (archive-relative path, source-relative path or wheel sentinel, provenance)
_CONTENT_MEMBER_TABLE: tuple[tuple[str, str, str], ...] = (
    ("README.md", "docs/release/README.md", "docs/release/README.md (verbatim copy)"),
    ("dist/<wheel>", "<wheel>", "runtime wheel (only package schwab_mcp)"),
    ("manuals/installation.md", "docs/release/installation.md", "docs/release/installation.md"),
    # ... etc.
)
```

- `member_specs(version)` derives `MemberSpec`s from the table (order comes
  from the table, satisfying FR-011) and appends the two generated members
  (`manifest.json`, `SHA256SUMS`) exactly as today.
- `source_map(project_root, version, wheel_path)` derives the dict from the
  same table: relative source paths resolve against `project_root`; the wheel
  entry resolves to the `wheel_path` parameter (its archive path still uses
  `wheel_name(version)`).
- Keep `MemberSpec`, `member_specs`, `source_map`, and `content_members`
  signatures untouched — no caller changes needed.

**Alternatives**:
- Keep both literals and add a test asserting `set(source_map(...)) ==
  {spec.path for spec in content_members(...)}`. Cheaper, but keeps the
  duplication the docstring forbids and only converts the silent direction
  into a loud test failure.
- Move the wheel out of the table (dynamic anyway) and derive only the static
  files. Slightly less uniform; saves nothing meaningful.

**Files likely to change**:
- `src/schwab_mcp_release/allowlist.py` (only source file)
- `tests/unit/test_release_allowlist.py` (new invariant test)

**Tests to add or update**:
- Add an invariant test: for every content member path returned by
  `member_specs()`, `source_map()` yields exactly the same path set — and vice
  versa (`set(source_map(root, version, wheel)) == {spec.path for spec in
  content_members(version)}`). This locks the single-table derivation and
  turns any future desync in *either* direction into a loud test failure.
- Existing tests in `tests/unit/test_release_allowlist.py` (member set, order,
  per-path source mapping) and `tests/unit/test_release_archive.py` /
  `tests/unit/test_release_checks*.py` already pin behavior; they must stay
  green unchanged (signature stability).

## Risks & Considerations

- **Order sensitivity**: archive member order is fixed by FR-011; the table
  must preserve the current ordering exactly (tests pin it —
  `test_release_allowlist.py:66`).
- **Provenance strings are contractual**: `MemberSpec.source` strings are
  quoted from `contracts/archive-layout.md`; deriving them from `_SOURCE_REL`
  must not alter their wording (e.g. "(verbatim copy)" suffix, wheel text).
  Keep `_PROVENANCE` as an explicit column rather than generating text.
- **DRY**: archive ordering, mode, and generated-member handling stay where
  they are (`archive.py`); the refactor must not creep into them.
- No performance, security, or API impact — pure internal derivation.

## Open Questions

- None. The report's silent-failure nuance is resolved above (only the
  `source_map`-superset direction is silent).