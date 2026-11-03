# Bug Assessment: Undocumented settlement_type values in get_option_expiration_chain (A/B)

- **Slug**: settlement-type-a
- **Created**: 2026-11-03
- **Source**: pasted text
- **Verdict**: valid — but the report misidentifies the gap: `A` is already documented and tested; the genuinely undocumented live value is **`B`**
- **Severity**: low

## Report (verbatim or summarized)

> Issue 4 — `settlement_type` has a third live value `A`, undocumented.
> `get_option_expiration_chain` on `$SPX` (dte_max=365) returns settlement types `P` (35), `B` (5)
> and **`A` (7)** — the far quarterly expirations 2027-04-16 … 2027-10-15. The code passes
> `settlementType` through unmodified (`options_chain.py:883`), so this is provider data, but the
> documented contract (and downstream consumers) only know P=PM / B=AM. Please document what `A`
> means (AM-settled quarterlies?) or normalize it.

## Symptom

`get_option_expiration_chain` on `$SPX` returns `settlement_type` values beyond the documented
enumeration. Expected: the documented contract covers every live value. Observed: the docs
enumerate `C` close-settled, `P`/`A` PM/AM index settlement — while the live payload also carries
`B` (5 entries), which no doc, spec, or test mentions. The report's specific claim ("`A`
undocumented") is stale: `A` is already documented as AM index settlement
(`docs/tools.md:1061`, `specs/012-option-expiration-list/data-model.md:60`) and covered by a
passthrough unit test (`tests/unit/test_option_expirations.py:73-76`).

## Reproduction

Reproduced live on 2026-11-03:

1. Call `get_option_expiration_chain` with `symbol: "$SPX"`, `dte_max: 365`.
2. Group `expirations[]` by `settlement_type`.

Result (`outcome: ok`, 47 expirations) matches the report:

| `settlement_type` | count | dates |
|---|---|---|
| `P` | 35 | non-third-Friday weeklies + month-end quarterlies (SPXW, PM-settled) |
| `B` | 5 | third-Friday standard monthlies 2026-11-20 … 2027-03-19 |
| `A` | 7 | third-Friday standard monthlies 2027-04-16 … 2027-10-15 |

Raw provider payload (`extended=true`) for representative entries adds decisive context —
the fields the curated shape deliberately excludes:

| expirationDate | settlementType | expirationType | optionRoots |
|---|---|---|---|
| 2026-11-06 | `P` | `W` (weekly) | `SPXW` |
| 2026-11-20 | `B` | `S` (standard) | `SPX, SPXW` |
| 2027-04-16 | `A` | `S` (standard) | `SPX` |
| 2027-10-15 | `A` | `S` (standard) | `SPX` |

## Suspected Code Paths

- `src/schwab_mcp/options_chain.py:946` (`_expiration_entry`) — passes
  provider `settlementType` through unmodified (the report's `options_chain.py:883` points at
  the `get_option_chain` wrapper, which is unrelated to the expiration list; the actual passthrough
  for the expiration tool is line 946). By design (research R6, "values are never invented").
- `docs/tools.md:1061-1064` — the documented value enumeration (`C` close-settled,
  `P`/`A` PM/AM index settlement) omits `B`. This is the real gap.
- `specs/012-option-expiration-list/data-model.md:60` and `specs/012-option-expiration-list/research.md:33`
  — the spec-side enumerations share the same omission (`"C"`/`"P"`/`"A"`).
- `tests/unit/test_option_expirations.py:73-76` — passthrough test exercises `"A"`; `"B"` is untested.

## Root Cause Hypothesis

Confidence: **high** (that the gap is documentation-only), **low** (on what `B` semantically means).

There is no code defect: the tool is designed to pass `settlementType` through verbatim and never
invent values, and it does. The defect is that the documentation presents a closed value set
(`C`/`P`/`A`) while the provider emits at least one more live value (`B`). The live data shows
`B` and `A` both appear on third-Friday standard monthly expirations — i.e. both plausibly denote
AM (open) settlement for index options — split at the Mar/Apr 2027 boundary. The raw payload
correlates `B` with `optionRoots: "SPX, SPXW"` and `A` with `optionRoots: "SPX"`, but whether `B`
is a provider labeling quirk, a "both roots co-listed" artifact, or a genuinely distinct settlement
kind is not authoritative from this evidence. The report's premise that the docs say
"P=PM / B=AM" is not supported by the current tree.

## Proposed Remediation

**Preferred**: documentation-first fix, consistent with the passthrough design.

1. Update the `settlement_type` bullet in `docs/tools.md` (`get_option_expiration_chain` section,
   ~line 1061) to enumerate the full observed set — `C` close-settled (equities),
   `P` PM index settlement, `A`/`B` AM (open) index settlement — and explicitly state that the
   enumeration is **non-exhaustive**: `settlement_type` is a provider pass-through and consumers
   must not branch on a closed enum; unknown letters surface verbatim.
2. Mirror the same wording in `specs/012-option-expiration-list/data-model.md:60`,
   `specs/012-option-expiration-list/research.md:33`, and `quickstart.md:71`.
3. Add an agent-guidance note: same-date AM/PM entries are already handled by the
   identity rule (`expiration_date`, `settlement_type`) — treat `A`/`B` alike as AM-settled
   unless the provider documents otherwise.

**Alternatives** (optional):

- *Normalize/annotate in code* (map provider letters to a documented enum, e.g. add a
  `settlement_kind: "AM" | "PM" | "close"` derived field). Rejected: violates the spec's
  "values are never invented" contract (research R6), breaks the pass-through guarantee tested in
  `test_settlement_type_passes_through_unmodified`, and `B`'s semantics are not authoritative
  enough to encode.
- *Emit a warning/sidecar for unmapped values*. Rejected as over-engineering: a low-frequency,
  informational-only condition does not justify a new response field and its token cost.

**Files likely to change**:

- `docs/tools.md`
- `specs/012-option-expiration-list/data-model.md`
- `specs/012-option-expiration-list/research.md`
- `specs/012-option-expiration-list/quickstart.md`
- `tests/unit/test_option_expirations.py` (or its fixture `tests/unit/fixtures/expiration_chain_payloads.py`)
- `docs/CHANGELOG.md` (per constitution: affected docs in the same commit)

**Tests to add or update**:

- Unit test mirroring `test_settlement_type_passes_through_unmodified` with `settlementType: "B"`,
  asserting it passes through verbatim and is not dropped or rewritten (locks in that unknown
  values are preserved).

## Risks & Considerations

- Semantics of `B` are inferred from date/roots patterns, not provider documentation — the docs
  should describe the observed value without asserting unverified meaning as fact.
- Docs-only change: no API breakage, migration, or performance risk; the code stays untouched.
- Constitution gate: docs and tests must land in the same commit, full suite green.
- If `B` later proves to be a transient provider artifact (e.g. relabeling), the non-exhaustive
  wording keeps the contract future-proof without another round of doc churn.

## Open Questions

- [NEEDS CLARIFICATION: what exactly does the provider encode as `B`? Candidates: AM settlement
  variant for near-term standard monthlies; artifact of `optionRoots: "SPX, SPXW"` co-listing on
  the same date. Confirm against Schwab developer docs or CBOE contract specs if available.]
- [NEEDS CLARIFICATION: why the `B`→`A` split at the 2027-03/2027-04 monthly boundary — provider
  labeling transition, or different contract generations listed per tenor?]