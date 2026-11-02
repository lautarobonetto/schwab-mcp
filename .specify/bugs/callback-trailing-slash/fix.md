# Bug Fix: Callback URL preserves the exact configured value (trailing "/")

- **Slug**: callback-trailing-slash
- **Fixed**: 2026-11-02
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Reversed the 2026-10-23 trailing-slash normalization: `load_config()` now preserves `SCHWAB_CALLBACK_URL` verbatim (whitespace-stripped only), because Schwab compares the `redirect_uri` **character for character** against the developer-portal registration and the portal may require the trailing slash. To keep the value reaching authorize/exchange unchanged, a runtime compatibility shim relaxes schwabdev 4.0.0's `endswith("/")` rejection — durable across `uv sync`, unlike the site-packages sed patch the reporter used.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/config.py` | modified | Removed `.rstrip("/")`; whitespace strip + default fallback only. Comment documents the literal `redirect_uri` comparison |
| `src/schwab_mcp/schwabdev_compat.py` | added | Runtime shim: wraps `schwabdev.tokens.Tokens.__init__` — validates with the stripped spelling, restores the exact value on the instance afterwards. Idempotent; fails loudly (`RuntimeError`) if upstream internals change; `//` still rejected |
| `src/schwab_mcp/cli.py` | modified | `install_trailing_slash_callback_support()` called in `run_auth` and `_do_run_renew` before `schwabdev.Client` |
| `src/schwab_mcp/server.py` | modified | Same install call in `run_serve` before `schwabdev.Client` |
| `tests/unit/test_config.py` | modified | `test_callback_url_trailing_slash_normalized` → `test_callback_url_trailing_slash_preserved` (asserts preservation); added `test_callback_url_whitespace_stripped` |
| `tests/unit/test_schwabdev_compat.py` | added | 5 tests: accepted+preserved, plain untouched, `//` rejected, idempotent install, loud failure on upstream change |
| `docs/installation.md` | modified | Portal registration + exact-value rule; env-var table row updated |
| `docs/usage.md` | modified | Troubleshooting row: `endswith "/"` now means `//` or old version without the shim |
| `docs/release/first-run-authentication.md` | modified | Callback registration guidance |
| `docs/release/usage.md` | modified | Env-var row: copied exactly, trailing slash included |
| `docs/CHANGELOG.md` | modified | New `Unreleased → Fixed` entry; 0.7.0 normalization entry annotated as reversed |

## Diff Highlights (optional)

`config.py` — the core reversal:

```python
# before
callback_url = (raw_callback.strip() if raw_callback else _DEFAULT_CALLBACK_URL
               ).rstrip("/") or _DEFAULT_CALLBACK_URL
# after
callback_url = (raw_callback.strip() if raw_callback else "") or _DEFAULT_CALLBACK_URL
```

`schwabdev_compat.py` — the narrow wrap:

```python
workable = callback_url[:-1]  # only if endswith("/") and not endswith("//")
original_init(self, ..., workable, ...)
if workable != callback_url:
    if "_callback_url" not in vars(self):
        raise RuntimeError("schwabdev internals changed: ...")
    self._callback_url = callback_url
```

## Tests Added or Updated

- `tests/unit/test_config.py::TestOptionalVars::test_callback_url_trailing_slash_preserved` — pins that `https://127.0.0.1/` survives `load_config()` verbatim (was: asserted stripping — inverted per the corrected diagnosis).
- `tests/unit/test_config.py::TestOptionalVars::test_callback_url_whitespace_stripped` — whitespace cleaned, URL preserved.
- `tests/unit/test_schwabdev_compat.py::test_single_trailing_slash_accepted_and_preserved` — shim lets `Tokens` validate and stores the exact value.
- `tests/unit/test_schwabdev_compat.py::test_plain_callback_untouched` — no-slash behavior identical to upstream.
- `tests/unit/test_schwabdev_compat.py::test_double_trailing_slash_still_rejected` — `//` still raises `ValueError`.
- `tests/unit/test_schwabdev_compat.py::test_install_is_idempotent` — no double wrap.
- `tests/unit/test_schwabdev_compat.py::test_shim_fails_loudly_if_internals_change` — simulated upstream change → clear `RuntimeError`, not a silent mismatch.

## Local Verification

- Commands run:
  - `uv run pytest tests/unit/test_config.py -k "trailing_slash or whitespace_stripped" -q` → RED before the config change (2 failed), GREEN after.
  - `uv run pytest tests/unit/test_schwabdev_compat.py -q` → RED (ImportError, module missing), GREEN after implementation (5 passed).
  - `uv run pytest -q` → **1269 passed, 0 skipped** (commit gate).
- Manual smoke (live python, shim installed): `SCHWAB_CALLBACK_URL=https://127.0.0.1/` → config yields `https://127.0.0.1/`; `schwabdev.Client` constructs; `client.tokens._callback_url == 'https://127.0.0.1/'`; `_build_auth_url` emits `redirect_uri=https%3A//127.0.0.1/` (slash present, as registered); `//` still rejected with the upstream `ValueError`.

## Deviations from Assessment

- **The assessment's core hypothesis was wrong and is hereby corrected**: it concluded "already fixed / no code change — stripping is safe". New evidence supplied by the reporter (patch description from `/home/openclaw/projects/schwab-mcp`, v0.7.0) plus independent confirmation (LumiBot, msts-trader, Medium: Schwab matches the callback "character for character, trailing slash included") shows the `.rstrip("/")` itself was the defect: it silently rewrote a portal-required `redirect_uri`. The verdict effectively moves to **valid**; severity **high** (blocks first-run authorization with confusing errors for affected registrations).
- **Scope expanded beyond the assessment's "Files likely to change" (which listed none)**: `cli.py` and `server.py` gained the shim install call (they were listed only as suspected code paths), and `schwabdev_compat.py` is a new module. Justification: preserving the slash without relaxing schwabdev's validation would break every `auth` with the portal-required form — the two changes are one atomic fix.
- The reporter's own remediation (venv `sed` patch on `schwabdev/tokens.py`, re-applied after every `uv sync`) was deliberately NOT replicated — fragile by their own admission; the runtime shim achieves the same effect durably from inside the package.
- `assessment.md` was left untouched per guardrails; the correction lives here.

## Follow-ups

- Upstream: consider a PR to `schwabdev` relaxing the check (or accepting a path-bearing callback); then the shim becomes a no-op and can be retired.
- The reporter's repo (`/home/openclaw/projects/schwab-mcp`) still carries the fragile venv patch: recommend they adopt this shim approach on their next sync.
- CI runs on red from 26/10 (per reporter's notes): unrelated to this repo's tests (they use slash-free callbacks); verify their CI separately if it is the same project.
- If a future schwabdev release changes `Tokens.__init__`, the shim's loud `RuntimeError` (covered by test) is the trigger to update the wrap — not a silent redirect_uri mismatch.

## Open Questions

- [NEEDS CLARIFICATION: whether Schwab's token-exchange endpoint also compares `redirect_uri` literally — assumed yes per OAuth RFC 6749 §3.1.2.3 and the reporter's end-to-end success; no live exchange was performed here.]
