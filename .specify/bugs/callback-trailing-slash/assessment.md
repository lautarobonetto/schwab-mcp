# Bug Assessment: Callback URL rejects trailing "/" (schwabdev constraint)

- **Slug**: callback-trailing-slash
- **Created**: 2026-11-02
- **Source**: pasted text
- **Verdict**: likely valid, needs reproduction — root cause is real but appears **already fixed** in the current code (2026-10-23); report probably came from an older installed release
- **Severity**: low

## Report (verbatim or summarized)

> "El Callback no acepta un '/' al final y esto esta mal. Debe aceptarlo."
>
> (Translation: "The callback does not accept a trailing '/' and this is wrong. It must accept it.")

No URL was supplied; report is pasted freeform text.

## Symptom

When `SCHWAB_CALLBACK_URL` is set with a trailing slash (e.g. `https://127.0.0.1/`), the flow fails instead of accepting it. Expected: the trailing-slash form should be accepted, since the Schwab developer portal may **require** the trailing slash on the registered callback.

Observed failure mode (from the third-party library):
`ValueError: [Schwabdev] callback_url cannot be a path (endswith "/")`.

## Reproduction

1. Set `SCHWAB_CALLBACK_URL=https://127.0.0.1/` (with trailing slash).
2. Run `schwab-mcp auth` (on an affected version).
3. Client construction raises the schwabdev `ValueError` above instead of authorizing.

Verified against the **current** code (2026-11-02): step 3 does **not** reproduce —
`load_config()` strips the trailing slash before the client is built.

[NEEDS CLARIFICATION: exact version the reporter ran; current venv install is 0.7.0 which contains the fix.]

## Suspected Code Paths

- `.venv/lib/python3.11/site-packages/schwabdev/tokens.py:72-73` — the *actual* rejection: schwabdev's `Tokens.__init__` raises `ValueError` if `callback_url.endswith("/")`. Third-party; cannot be changed here.
- `src/schwab_mcp/config.py:104-107` — `load_config()` normalizes `SCHWAB_CALLBACK_URL` with `.rstrip("/")` before it ever reaches schwabdev. This is the workaround (landed 2026-10-23, commit `39f0fb7`).
- `src/schwab_mcp/cli.py:100-107` — `run_auth()` passes `config.callback_url` (already normalized) to `schwabdev.Client`; same in `src/schwab_mcp/cli.py:247-254` (`renew`) and `src/schwab_mcp/server.py:88-95` (`serve`).

## Root Cause Hypothesis

**Confidence: high.** The rejection comes from the schwabdev library itself, which validates that `callback_url` does not end in `/`. The Schwab developer portal, however, can require the trailing slash in the registered callback — so the "wrong" behavior the reporter perceives is the mismatch between portal requirements and the library's validation. This project already fixed it on 2026-10-23: `load_config()` strips trailing slashes so both spellings of `SCHWAB_CALLBACK_URL` work. The live check confirms `https://127.0.0.1/` normalizes to `https://127.0.0.1` and the client constructs successfully. The most probable explanation for the report is execution against an older installed release that predates commit `39f0fb7`.

## Proposed Remediation

**Preferred**: No code change — the fix already exists in the current codebase. Confirm the reporter's installed version (`schwab-mcp --help` prints the package version) and upgrade if it predates the fix. `docs/usage.md:190` already maps this exact error message to "old package version; update the code", and `docs/CHANGELOG.md:511-517` documents the fix; `docs/installation.md:41-46` documents that either form works.

**Alternatives** (if a code change is still wanted):
- Improve the `InvalidConfigError`-shaped guidance: catch schwabdev's `ValueError` in `run_auth()` / `run_serve()` and re-raise with a message pointing to the normalization already applied (only helps if the value reaches schwabdev un-normalized, which it no longer does).
- Defensive double-guard: validate/normalize the value again inside `server.py` / `cli.py` before constructing the client — redundant with `load_config()`, violates KISS/DRY; not recommended.

**Files likely to change**:
- None (code). Optionally `docs/usage.md` if the troubleshooting row needs a version-pin note.

**Tests to add or update**:
- None required; `tests/unit/test_config.py:95` (`test_callback_url_trailing_slash_normalized`) already locks the fix in.

## Risks & Considerations

- If the reporter is on an **older installed release**, the actual remediation is operational (upgrade), not a code change — make sure the report gets that answer.
- The normalization is intentionally one-way (strip). A callback that legitimately *needs* a path suffix (e.g. `https://host/oauth/callback`) is still rejected by schwabdev's blanket "ends with /" check — out of scope here, but a known library limitation.
- If a future schwabdev version changes validation, the `.rstrip("/")` workaround remains safe.

## Open Questions

- [NEEDS CLARIFICATION: which installed version produced the report — if it is ≥ the fix release, the symptom must be re-reproduced before reopening.]
