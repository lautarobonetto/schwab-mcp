# Bug Assessment: `get_option_chain` silently ignores a requested `expiration_date` (no such parameter exists; unknown tool arguments are dropped)

- **Slug**: option-chain-dte-filter
- **Created**: 2026-11-03
- **Source**: pasted text (Issue 3 from a live review run; also pre-noted as deferred in `.specify/bugs/spx-delta-timeout/assessment.md` and its `fix.md` follow-ups)
- **Verdict**: valid — but the report's root-cause premise is corrected below
- **Severity**: medium

## Report (verbatim or summarized)

> Requesting a specific `expiration_date` with DTE > 60 (e.g. `{"symbol":"LLY",
> "expiration_date":"2027-01-15"}`, DTE 73) returns `outcome:"ok"` with the requested expiration
> **absent** from `expirations[]`. The only hint is `filters.dte_max_effective: 60`. For a caller
> who asked for that exact date, "ok + missing row" is indistinguishable from "no such expiration".
> Suggested fix: when a specific `expiration_date` was requested and got filtered out by the DTE
> ceiling, return `validation_error` with the effective ceiling (mirroring the `too_many_symbols`
> style), or at least a `"requested_expiration_filtered_out": true` flag.

## Symptom

A caller passes `expiration_date` to `get_option_chain` and gets `outcome:"ok"` back with only
expirations ≤ 60 DTE — the requested date is silently gone, and nothing in the response signals
that the parameter was never honored. Expected: either the requested expiration is honored, or the
call fails loudly / flags the discrepancy.

**Correction to the report's premise**: `get_option_chain` has **never accepted** an
`expiration_date` parameter (verified in source and in git history — the parameter has never
existed; the documented interface is `symbol`, `max_strikes`, `option_type`, `delta_target`,
`dte_max`, `extended`). The reported behavior is **not** "the DTE ceiling filtered out the
requested expiration" — it is "the MCP SDK silently drops unknown tool arguments". Had the
parameter existed and been ceiling-filtered, `build_chain_result` would return
`no_expirations_in_range` (all expirations > ceiling) or the date would simply not be in the
payload — not a silent `ok`.

The silent drop was **reproduced offline against the installed SDK** (`mcp` 2.3.0): registering a
tool whose signature has no `expiration_date` and calling it with
`{"symbol": "LLY", "expiration_date": "2027-01-15"}` returns `is_error=False` and the unknown
argument is discarded before the function is invoked. The SDK's
`mcp/server/mcpserver/utilities/func_metadata.py` validates arguments with a Pydantic model built
via `create_model(...)` with default config (`extra='ignore'`), and the advertised JSON schema does
not set `additionalProperties: false` — so any hallucinated or misspelled parameter on **any**
registered tool vanishes without a trace.

## Reproduction

Deterministic; verified at the SDK level (no live network call was made during this assessment).

1. Register the `get_option_chain` tool (as `server.py` does) — its signature has no
   `expiration_date` parameter.
2. Call `get_option_chain` with `{"symbol":"LLY","expiration_date":"2027-01-15"}`.
3. The SDK's argument model ignores the unknown key; the chain is fetched with the default
   60-DTE ceiling (`options_chain.py:308`, `toDate = today + dte_max_effective`), so the 73-DTE
   date is absent from the payload response and the result is `outcome:"ok"` with only
   `filters.dte_max_effective: 60` as a hint — exactly the reported symptom.

[NEEDS CLARIFICATION: a single live confirmation against a served instance was not performed
during assessment; the offline SDK experiment is deterministic and fully explains the report.]

## Suspected Code Paths

- `src/schwab_mcp/server.py:205-235` (`_get_option_chain_wrapper` + `add_tool`) — the tool
  signature genuinely has no `expiration_date`; there is no first-class way to request a specific
  expiration (`get_option_expiration_chain`, `server.py:300-324`, only takes `symbol`/`dte_max`).
- Installed dependency `mcp` 2.3.0, `mcp/server/mcpserver/utilities/func_metadata.py:146`
  (`arguments_parsed_model = self.arg_model.model_validate(...)`) — Pydantic default
  `extra='ignore'`; unknown arguments are dropped, not rejected. This is the **root cause** of the
  silence.
- `src/schwab_mcp/options_chain.py:613-617` (`_map_expirations`, `dte > dte_max_effective →
  continue`) — the ceiling logic the report blamed. It behaves correctly *given* the fetched
  payload; it never sees the requested date because the parameter is dropped upstream.
- `src/schwab_mcp/options_chain.py:718-728` (`build_chain_result` → `no_expirations_in_range`) —
  the outcome that *would* surface if all expirations exceeded the ceiling, i.e. the non-silent
  path the report assumed was being hit.
- `src/schwab_mcp/quotes.py:128-131` — the established `validation_error` outcome pattern the
  report suggests mirroring.

## Root Cause Hypothesis

Two distinct defects combine to produce the symptom (confidence: **high**):

1. **Unknown tool arguments are silently ignored** at the MCP boundary. The SDK builds each
   tool's argument model with Pydantic's default `extra='ignore'` and advertises a JSON schema
   without `additionalProperties: false`, so any parameter a caller hallucinates or misspells
   (here `expiration_date`, which a caller reasonably extrapolates from Schwab's own
   `chains` API) is dropped without any signal. This is class-wide: it affects every tool
   registered through `mcp.add_tool`, not just `get_option_chain`.
2. **Interface gap**: there is no supported way to request a specific expiration date, so
   callers reaching for one land in defect 1 instead of an honest error.

## Proposed Remediation

**Preferred**: make unknown tool arguments fail loudly at the MCP boundary (strict argument
validation), fixing the *class* of bug rather than the instance. After the fix, the reported call
returns a validation error ("unexpected argument `expiration_date`") instead of a misleading
`ok` — which is precisely the distinguishability the report asks for. Mechanism to spike (small,
isolated): either (a) post-registration, set the SDK tool's `fn_metadata.arg_model` config to
`extra='forbid'` and `model_rebuild(force=True)`, plus `additionalProperties: false` in the
advertised schema; or (b) a thin `ToolManager`/`Tool` subclass that pre-validates argument names
against the function signature before delegation. Prefer whichever survives an `mcp` SDK upgrade
without monkey-patching private internals; wrap the chosen mechanism in one shared helper in
`server.py` applied to every registration site.

**Alternatives**:
- **Add `expiration_date: str | None = None` as a first-class parameter** to `get_option_chain`
  (and optionally `get_option_expiration_chain`), validating `YYYY-MM-DD` format up front and
  raising a `validation_error` (mirroring `too_many_symbols` style, `quotes.py:128-131`) when the
  date lies beyond `dte_max_effective`. This satisfies the report's letter but is a *feature*
  addition (roadmap-sized, deserves its own Spec Kit spec) and does not fix the general
  silent-drop defect for other hallucinated parameters. Good follow-up if there is real caller
  demand for per-expiration chains.
- **Documentation-only**: document in `docs/tools.md` that only listed parameters exist and
  unknown ones are ignored. Weakest — it does not remove the silence, only explains it.

Recommended sequence: strict unknown-argument rejection now (bug fix), `expiration_date`
parameter as a follow-up feature spec if needed.

**Files likely to change**:
- `src/schwab_mcp/server.py` — shared strict-argument registration helper applied to all
  `mcp.add_tool` call sites (or the tool-manager override).
- `docs/tools.md` — document strict argument validation (caller-visible behavior change).
- `docs/CHANGELOG.md`, `pyproject.toml` — patch bump per the project's release pattern.
- `tests/unit/…` / `tests/integration/…` — regression tests at the MCP boundary.

**Tests to add or update** (TDD — write the failing test first):
- Register a representative tool via the real SDK path, call it with an unknown argument, and
  assert the call fails with a validation error (regression test for this bug).
- Assert the advertised tool schema sets `additionalProperties: false` (if the schema-side half
  of the fix is implemented).
- Assert known arguments still validate unchanged (no false rejections), including `None`
  defaults and the `context`-injection path if the mechanism touches it.

## Risks & Considerations

- **Behavior change**: callers that today silently pass extra arguments will start receiving
  errors. That is the intended fix, but it is caller-visible — ship with a CHANGELOG entry.
- **SDK coupling**: option (a) mutates SDK-internal model config and may break on `mcp`
  upgrades; option (b) overrides tool-manager internals. Pin or isolate behind one helper and
  cover with the boundary regression test. Pydantic config mutation must be verified to actually
  take effect (`model_rebuild(force=True)`), or fall back to (b).
- **False rejections**: ensure the strict check does not reject SDK-injected arguments (e.g. the
  context kwarg) or per-tool `extended` flags — validate against every registered tool.
- **Scope discipline**: the `expiration_date` feature is deliberately *not* part of the minimal
  fix (constitution: KISS / reuse before creation); track it separately if wanted.

## Open Questions

- [NEEDS CLARIFICATION: does the reporter want the `expiration_date` parameter to become a
  supported feature, or is a loud "unknown argument" error sufficient?]
- [NEEDS CLARIFICATION: one live confirmation of the reported LLY call against a served instance
  (the offline SDK experiment already explains it deterministically).]