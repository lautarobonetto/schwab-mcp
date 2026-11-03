# Bug Assessment: `renew`/`serve` report phantom `renewal_success` on revoked tokens (unchecked HTTP status in tie-breaker probe and startup validation)

- **Slug**: renew-phantom-success
- **Created**: 2026-11-03
- **Source**: pasted text (live incident timeline, 2026-11-03, account `...5105`)
- **Verdict**: valid (Issue 1/3 code-verified; Issue 2 code-verified as "no protection/visibility", server-behavior claim plausible)
- **Severity**: high

## Report (verbatim or summarized)

Pasted report titled *"Three issues in the renewal/authorization layer: phantom
`renewal_success`, no protection against parallel OAuth authorizations, and
misclassified renewal failures"*. No URL supplied — no fetch performed, URL
Trust Policy not applicable.

Condensed claims, each checked against the code:

1. **Issue 1 — `_tie_breaker_probe` reports phantom `renewal_success`.**
   The probe assumes `linked_accounts()` raises on auth failure; schwabdev
   returns `requests.Response` and never raises on HTTP 401. During a live
   `schwab-mcp renew` with a revoked refresh token, `update_tokens()` returns
   `False`, the probe gets a 401 Response, raises nothing → `renewed` is
   reported, nothing is written to the store (mtime unchanged), and `renew`
   exits 0. Reproduced 3× on 2026-11-03. Same unchecked pattern in `serve`
   startup validation (`retry_call(client.linked_accounts, retries=1)`),
   which logs `renewal_success` even on a 401.
2. **Issue 2 — no protection/warning against parallel OAuth authorizations.**
   Two `schwab-mcp auth` flows ran concurrently (11:54, 11:59); Schwab
   appears to allow only one active token set per app key + user, so each
   completed authorization invalidates the previous one. Tokens issued at
   11:59:41 were revoked server-side by 12:32 with zero local use —
   consistent with another installation holding the same app key.
3. **Issue 3 — failed renewals misclassified.** The phantom path yields
   `{"outcome":"renewed","expires_in_seconds":null}` — internally
   inconsistent, since a renewed outcome should correspond to a store write;
   exit code 0 makes "renewed" indistinguishable from "phantom renewed" for
   automated callers.

## Symptom

With a server-side-revoked refresh token, `schwab-mcp renew` prints stderr
`invalid_grant` from the token endpoint, then logs
`auth_event=renewal_success outcome=ok`, prints
`{"outcome":"renewed","expires_in_seconds":null,"detail":"access_renewed"}`,
and exits 0 — while every real API call returns `reauth_required` and the
token store is never written. Expected: `renew` classifies the failure as
`reauth_required` (exit 3), and `serve` startup validation does not emit
`renewal_success` when the API returns 401.

## Reproduction

1. Obtain a token store whose refresh token is revoked server-side
   (`invalid_grant`); store timestamps must look recent enough that the
   margin short-circuit (61 s) does not skip renewal.
2. Run `schwab-mcp renew`.
3. Observe stderr `Could not get new access token; refresh_token likely
   invalid (invalid_grant)` followed by `auth_event=renewal_success
   outcome=ok` and stdout `{"outcome":"renewed",...}` (exit 0).
4. `stat ~/.schwab-mcp/tokens.db` — mtime unchanged; a real call
   (e.g. `get_open_positions`) still returns `reauth_required`.

Observed live 3× on 2026-11-03 (11:53, 12:32, 12:35 CST). `[NEEDS
CLARIFICATION: the exact app-key sharing topology — a second
installation/machine holding the same app key is inferred from the 12:32
revocation-with-no-local-reauth, not confirmed.]`

## Suspected Code Paths

- `src/schwab_mcp/renewal.py:140-163` (`_tie_breaker_probe`) — calls
  `client.linked_accounts()` and treats only *exceptions* as failure. A 401
  `requests.Response` raises nothing → returns
  `RenewalOutcome(outcome="renewed", expires_in_seconds=None, ...)` without
  any store write. **Primary root cause.**
- `src/schwab_mcp/server.py:120-131` (`serve` step 4) —
  `retry_call(client.linked_accounts, retries=1)`; `retry_call`
  (`src/schwab_mcp/tokens.py:261-306`) only catches exceptions, so a 401
  Response passes through and line 131 logs
  `auth_event=renewal_success outcome=ok` unconditionally.
- `src/schwab_mcp/tokens.py:261-306` (`retry_call`) — exception-only
  failure model; cannot detect non-2xx Responses.
- `src/schwab_mcp/cli.py:301-334` (`_do_run_renew`) — maps `renewed` →
  exit 0, so the phantom outcome gives automated callers a green light.
- `src/schwab_mcp/tokens.py:221-258` (`AuthLock`) + `src/schwab_mcp/cli.py:89`
  (`run_auth`) — Issue 2: the lock coordinates concurrent flows on one
  machine only; there is no cross-installation coordination, no post-success
  warning that a new authorization invalidates other live token sets, and
  `docs/usage.md:114` documents the 7-day refresh lifetime but not the
  one-active-token-set-per-app-key behavior.
- `.venv/.../schwabdev/client.py` — `linked_accounts() -> requests.Response`
  is served by `_request()` → `self._session.request(...)`, which never
  calls `.raise_for_status()`; `Client.update_tokens()` returns `False`
  when schwabdev's internal refresh is rejected. Confirms the report's
  library-behavior premise.

**Test gap that allowed this:** `tests/unit/test_renewal.py:695`
(`test_renewed_via_tie_breaker_probe`) mocks `linked_accounts` to return a
plain dict; no test returns a 401-like `requests.Response`, so the
exception-only contract was never exercised against real schwabdev shapes.
Related prior bug assessed today: `.specify/bugs/auth-false-success/` (auth
reported success with dead tokens) — same family, different entry point.

## Root Cause Hypothesis

**Issue 1/3 (confidence: high).** `_tie_breaker_probe` (and the `serve`
startup validation) inherit an exception-only failure model from
`retry_call`, but schwabdev API methods signal HTTP failures through the
returned `requests.Response` (`status_code` 401), not through exceptions.
The codebase's own `provider.response_json`
(`src/schwab_mcp/provider.py:17-58`) already knows this and classifies
401/403 → `ReauthorizationRequiredError` — the probe and startup validation
simply never pass responses through it. When `update_tokens()` returns
`False` and the probe gets a silent 401, the "another process already
renewed" branch is taken, producing a `renewed` outcome that corresponds to
no store write (Issue 3's inconsistency) and an exit-0 result.

**Issue 2 (confidence: high that no protection/visibility exists; medium
that Schwab's server revokes prior token sets per app key).** The observed
33-minute death of an unused token set with no local re-auth is consistent
with an out-of-band authorization by another client of the same app key,
but that server behavior cannot be confirmed from this codebase — it must
be treated as operational knowledge to document and surface, not as a
verified invariant.

## Proposed Remediation

**Preferred** (reuse-first per Constitution II — one implementation per
piece of knowledge):

1. **Route the probe through the shared response unwrapper.** In
   `_tie_breaker_probe` (`renewal.py:140-163`), replace the bare
   `client.linked_accounts()` with
   `provider.response_json(client.linked_accounts())`. This reuses the
   existing shared status taxonomy: a 401/403 Response raises
   `ReauthorizationRequiredError`, which the existing `except Exception`
   arm maps to `reauth_required / refresh_rejected` — no new
   classification logic needed. `response_json` already passes dicts/lists
   through untouched, so existing test doubles and the
   `test_renewed_via_tie_breaker_probe` mock keep working.
2. **Fix `serve` startup validation the same way**
   (`server.py:120-131`): wrap the call as
   `retry_call(response_json, retries=1, response=client.linked_accounts())`
   (or an equivalent small closure), so 401/403 raises
   `ReauthorizationRequiredError` and the pre-outcome `renewal_success` at
   line 131 is only emitted for a genuinely 2xx validation. Keep the
   `ConnectivityError` retry arm unchanged. Note `retry_call` wraps *any*
   exception in `ConnectivityError` after retries — the code must catch
   `ReauthorizationRequiredError` *before* treating `ConnectivityError` as
   connectivity, matching the precedence already documented in
   `provider.py`'s docstring.
3. **Consistency guard for Issue 3** (cheap, in `_do_renew` /
   `_tie_breaker_probe`): a `renewed` outcome must correspond to a store
   write. When the probe claims "another process renewed", re-read
   `read_store_lifetime(store_path)` and only report `renewed` with
   `expires_in_seconds` from the store if the access token is actually
   fresh (> ACCESS_MARGIN); otherwise report `reauth_required` (or a
   conservative classification) rather than asserting a renewal that never
   happened.
4. **Issue 2 — visibility, not coordination** (can't lock out a second
   machine; can make the failure mode legible):
   - After a successful `auth`, emit an explicit `auth_event` (e.g.
     `auth_event("auth_success", "ok", detail="other installations using
     this app key are now revoked")`) and echo the warning on stderr.
   - When renewal is rejected (`invalid_grant`) while the store was
     recently written and healthy, surface
     `detail="refresh_rejected_but_access_valid"`-style context in the
     failure event — the signature of an out-of-band re-authorization.
     This requires extending `_VALID_DETAILS` (`renewal.py:17-27`).
   - Document in `docs/usage.md` (§ Refresh token): one active token set
     per app key; concurrent installations sharing credentials revoke each
     other.

**Alternatives:**

- Teach `retry_call` to treat non-2xx `requests.Response` results as
  failures centrally. More thorough but mutates a widely used primitive
  (callers pass mutating operations and non-Response callables); higher
  blast radius for the same benefit. The targeted `response_json` reuse is
  KISS.
- Replace the probe with a real store mtime check ("did anyone write the
  store during this renewal?") instead of an API call. Removes the network
  dependency but changes semantics for genuinely concurrent local renewals
  via schwabdev's SQLite coordination; keep as a future refinement, not
  part of this fix.

**Files likely to change:**

- `src/schwab_mcp/renewal.py` (`_tie_breaker_probe`, `_do_renew`, possibly
  `_VALID_DETAILS`)
- `src/schwab_mcp/server.py` (step 4 startup validation)
- `docs/usage.md` (one-token-set-per-app-key documentation; auth-status
  caveat)
- `docs/CHANGELOG.md` (same commit, per constitution)
- Tests: `tests/unit/test_renewal.py`, `tests/integration/test_renew.py`,
  `tests/integration/test_failures.py` or `test_serve.py` (startup
  validation), `tests/integration/test_auth.py` (post-success event)

**Tests to add or update:**

- Probe given a fake `requests.Response` with `status_code=401` (and one
  with 403) → `reauth_required / refresh_rejected`, exit path 3.
- Probe given a 5xx Response → `reauth_required` is wrong; expect the
  connectivity/transient classification (per `response_json`'s
  `ConnectivityError`) — decide and lock the mapping in tests.
- Probe given a legacy dict payload (existing mock shape) → still
  `renewed` (back-compat with test doubles).
- Phantom-path consistency: `update_tokens()==False`, probe "succeeds"
  against a store that was never written → outcome is NOT
  `renewed/null-lifetime`; assert store mtime or lifetime read drives it.
- `serve` startup: `linked_accounts` returns 401 Response →
  `renewal_failure` (not `renewal_success`) and non-ready exit; 200 →
  unchanged behavior.
- `auth` success emits the "other token sets now invalid" event.

## Risks & Considerations

- **Behavior change for legitimate concurrency**: the probe's `renewed`
  branch is how genuine cross-process renewals are detected. Wrapping with
  `response_json` preserves that (2xx → dict → `renewed`) but the new
  store-consistency guard could misclassify a race where the other process
  renewed *after* the probe's store read. Keep the guard's tolerance window
  generous and test the race.
- **`retry_call` wrapping**: after retries, `retry_call` converts *any*
  exception to `ConnectivityError`. Startup validation must distinguish
  `ReauthorizationRequiredError` from connectivity before that wrap or
  catch it appropriately — ordering bugs here would misclassify 401 as
  exit-7 connectivity.
- **Outcome-vocabulary change** (new `detail` value for Issue 2) touches
  `contracts/`-governed event/outcome vocab; update `docs/tools.md` /
  contracts in the same commit.
- **Exit-code semantics**: `renew` moving phantom cases from exit 0 → exit
  3 changes automated callers' behavior — intentional, but note it in the
  changelog so downstream automation owners aren't surprised.
- **Credential safety**: the new auth/renewal events must describe the
  situation without ever logging tokens or error payloads containing
  secrets (constitution gate).

## Open Questions

- [NEEDS CLARIFICATION: Is a second installation/machine holding the same
  app key confirmed? The 12:32 revocation implies it, but the fix for
  Issues 1/3 is independent of the answer.]
- [NEEDS CLARIFICATION: Should a 5xx probe response map to
  `transient_failure` (retryable) rather than `reauth_required`?
  `response_json` raises `ConnectivityError` for 5xx; the probe's current
  `except Exception` maps everything to `reauth_required`, which would be
  wrong for transient outages — pick the intended mapping during planning.]
- [NEEDS CLARIFICATION: Whether `auth-status` should gain a probe-based
  "live check" mode, or remain store-lifetime-only with a documented
  caveat (the report only requires that it not be the sole green signal).]