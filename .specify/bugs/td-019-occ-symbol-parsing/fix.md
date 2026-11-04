# Bug Fix: TD-019 — OCC option symbol parsing triplicated (DRY)

- **Slug**: td-019-occ-symbol-parsing
- **Fixed**: 2026-11-04
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

The 15-character OCC tail grammar now lives once, in
`schwab_mcp.symbols.parse_occ_symbol()` (with the ISO expiry derivation it
previously lacked); `transactions._option_root` and
`positions._parse_occ_option_symbol` became thin wrappers over it and the
duplicated `_OCC_TAIL_RE` / hand-written tail checks were deleted.
Behavior-preserving, applied TDD-first (parity tests Red → Green) per the
constitution.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `src/schwab_mcp/symbols.py` | added | `OCC_TAIL_RE` (strict `\d{6}[CP]\d{8}` tail), frozen dataclass `OccSymbol` (root, ISO expiry, put_call, strike÷1000), `parse_occ_symbol()`; module docstring updated to extend the SSOT scope |
| `src/schwab_mcp/transactions.py` | modified | `_option_root` is now a thin wrapper over `parse_occ_symbol`; deleted `_OCC_TAIL_RE` and the now-unused `import re`; signature and all 5 call sites untouched |
| `src/schwab_mcp/positions.py` | modified | `_parse_occ_option_symbol` is now a thin wrapper over `parse_occ_symbol`; the hand-written tail checks and inline ISO-expiry derivation are deleted; signature and both call sites untouched |
| `tests/unit/test_occ_symbol_parity.py` | added test | Parity + shared-parser suite (Red first): 24 cases across three test classes |
| `docs/tech-debt.md` | modified | TD-019 row → `Fixed (v0.9.11, 2026-11-04)`; **Resolved** block appended to the TD-019 section |
| `docs/CHANGELOG.md` | modified | New `[0.9.11] - 2026-11-04` section documenting the consolidation |

## Diff Highlights

`src/schwab_mcp/symbols.py` (new, the SSOT):

```python
OCC_TAIL_RE = re.compile(r"^\d{6}[CP]\d{8}$")

@dataclass(frozen=True)
class OccSymbol:
    root: str
    expiry: str
    put_call: str
    strike: float

def parse_occ_symbol(symbol: str | None) -> OccSymbol | None:
    if not symbol:
        return None
    tail = symbol[-15:]
    if len(tail) < 15 or not OCC_TAIL_RE.match(tail):
        return None
    yymmdd, put_call, strike_millis = tail[:6], tail[6], tail[7:]
    return OccSymbol(
        root=symbol[:-15].strip(),
        expiry=f"20{yymmdd[:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}",
        put_call=put_call,
        strike=int(strike_millis) / 1000.0,
    )
```

`src/schwab_mcp/transactions.py` (wrapper, −30 lines):

```python
def _option_root(symbol: str | None) -> str | None:
    parsed = parse_occ_symbol(symbol)
    return parsed.root if parsed is not None else None
```

`src/schwab_mcp/positions.py` (wrapper):

```python
def _parse_occ_option_symbol(symbol: str) -> tuple[float | None, str | None]:
    parsed = parse_occ_symbol(symbol)
    if parsed is None:
        return None, None
    return parsed.strike, parsed.expiry
```

## Tests Added or Updated

- `tests/unit/test_occ_symbol_parity.py::TestParseOccSymbolShared` — shared parser decodes root/ISO-expiry/put_call/strike÷1000 over 7 valid fixtures (padded root, unseparated root, 1-char root, 4-char root, put and call, the live positions fixture `"AMD  261120P00090000"`, and the bare 15-char tail); `None` on 6 malformed inputs and on `None` input.
- `...::TestParseOccSymbolShared::test_literal_strike_tail_is_rejected` — pins the assessment's main risk: the permissive `OPTION_RE` accepts `"AMD   261120P63"` (literal strike) but the strict tail parser rejects it.
- `...::TestParityWithOptionRoot` — `transactions._option_root` agrees with the shared parser on every valid and invalid fixture.
- `...::TestParityWithPositionsParser` — `positions._parse_occ_option_symbol` agrees with the shared parser on every valid and invalid fixture.

No existing test file was modified — the pre-existing suites pin the old behavior and had to stay green unchanged, which they did.

## Local Verification

- TDD cycle: `uv run pytest tests/unit/test_occ_symbol_parity.py -x -q` → **Red** confirmed before implementation (`ImportError: cannot import name 'parse_occ_symbol'`); **Green** after implementation (226 passed across the six targeted suites).
- Two Red-phase fixture errors were caught by the tests themselves and corrected in the tests (strike arithmetic: `00630000` → 630.0, and a 16-char "bare tail" fixture replaced with the valid 15-char `"261120C00100000"`) — the implementation was byte-faithful to the old parsers all along.
- Full suite: `uv run pytest -q` → **1875 passed, 0 skipped** (commit gate).
- Manual check: `grep` confirms `_OCC_TAIL_RE` and the `import re` are gone from `transactions.py` (`re` had no other use); graph re-indexed (`index_repository` mode `fast`) and `trace_path(parse_occ_symbol, inbound)` confirms the two wrappers plus the parity tests now call the SSOT.

## Deviations from Assessment

None in substance. The assessment's preferred remediation was followed exactly (shared parser + thin wrappers, strict tail contract preserved, no YYMMDD range validation added, no behavioral change). Two clarifications from the assessment's Open Questions were resolved as anticipated:

- The dataclass-with-ignored-fields approach was chosen: `parse_occ_symbol` exposes all four fields; `_option_root` simply uses `.root`.
- Docs were updated beyond the assessment's "likely not needed" note: `docs/tech-debt.md` (TD-019 status + Resolved block) and `docs/CHANGELOG.md` ([0.9.11] entry), because the constitution's documentation-currency rule requires affected docs to move with the change — consistent with how TD-010's fix was recorded.

## Follow-ups

- Optional fast-follow (per assessment alternative): delete the two thin wrappers and call `parse_occ_symbol` directly at the 7 call sites.
- TD-030 (M3 documented but identical to M1) is adjacent to the same matching code and remains open.
- The `[0.9.11]` CHANGELOG section and the tech-debt status reference a version that becomes official at the next release commit (`🔖 chore(release): bump version to 0.9.11`), following the repo's existing commit flow.
