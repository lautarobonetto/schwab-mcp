# Bug Verification: `unrealized_pl` from `get_open_positions` ignores the option contract multiplier

- **Slug**: option-upl-multiplier
- **Tested**: 2026-11-03
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The bug no longer reproduces: the fixed pipeline returns the report's
"uPL correct" column exactly for the recorded payload (9/9 offline
checks), and a fresh **live** `get_open_positions` call returned all six
option legs with the correct dollarized scale and sign — including the
XSP 805C short leg that previously flipped sign (now +196.84 on a live
winning short). No regressions: full suite 1669 passed, 0 skipped.

## Checks Performed

| Check | Command / Action | Result | Notes |
|-------|------------------|--------|-------|
| Reproduction (post-fix, offline) | `uv run python tmp/verify-option-upl.py` — exact live payload from the report (6 legs) through `_transform_provider_payload` → `map_provider_positions`, asserted against the report's "uPL correct" column + 3 strategy leg-sums | pass | 9/9 PASS (6 legs + 3 strategy sums) |
| Reproduction (post-fix, live) | `uv run python tmp/live-verify-option-upl.py` — one-shot read-only call to the live API with stored tokens, run through the FIXED `get_open_positions` orchestration | pass | All 6 legs dollarized-correct; each value hand-checked as `MV − avg × qty × 100`; marks (`MV/|qty|/100`) are consistent quotes |
| New / updated tests | `uv run pytest tests/unit/test_positions.py::TestUnrealizedPlOptionMultiplier -q` | pass | 5 passed |
| Regression suite | `uv run pytest -q` | pass | 1669 passed, 0 skipped |
| Lint / type-check | — | skipped | Not part of the repo's commit gate (`ci.yml` runs `uv sync && uv run pytest` only) |

Note on the live check: the first attempt was blocked by a dead refresh
token in the local store (`outcome=reauth_required`, no positions — the
fixed code's error classification itself behaved correctly). After the
user re-ran `schwab-mcp auth` interactively, the live call succeeded.

## Output Excerpts

Offline reproduction (`tmp/verify-option-upl.py`):

```
PASS SPXW 261218P07705000  qty=-1  uPL=  -6616.29  expected=  -6616.29
PASS SPXW 261218P07695000  qty=+1  uPL=  +6473.71  expected=  +6473.71
PASS XSP 261218P00735000   qty=-1  uPL=   -334.66  expected=   -334.66
PASS XSP 261218C00805000   qty=-1  uPL=   +200.34  expected=   +200.34
PASS SPY 261218P00750000   qty=+1  uPL=   +178.84  expected=   +178.84
PASS SPY 261218P00760000   qty=-1  uPL=   -233.69  expected=   -233.69
PASS SPX put spread 7695/7705  sum=   -142.58  expected=   -142.58
PASS SPY put spread 760/750    sum=    -54.85  expected=    -54.85
PASS XSP strangle 735P/805C    sum=   -134.32  expected=   -134.32
ALL CHECKS PASS
```

Live call, 2026-11-03T18:25:51+00:00 (`outcome=ok`, `data_received`):

```
SPX   261218P07695000  +1  142.7129   20365.00   +6093.71
SPX   261218P07705000  -1  146.2371  -20855.00   -6231.29
XSP   261218P00735000  -1    6.3334    -946.50    -313.16
XSP   261218C00805000  -1    3.8734    -190.50    +196.84  ← sign correct (winning short)
SPY   261218P00750000  +1   12.5066    1400.50    +149.84
SPY   261218P00760000  -1   15.6331   -1765.00    -201.69
```

Live values differ from the report's 11:59 CT column only because the
market moved (~2.5 h later); scale and sign are now correct everywhere.
Strategy leg-sums from the live data: SPX −137.58, SPY −51.85,
XSP −116.32 — same sign and magnitude class as the report's real P/L
(−142.58 / −54.85 / −134.32), no ×100-scale poisoning.

## Residual Risks

- **Mini options** (multiplier 10, rare): still miscomputed — the
  provider positions payload does not expose a per-contract multiplier;
  `assetType == "OPTION" → 100` is an approximation (accepted in the
  assessment).
- **Mixed positions** with non-zero `longQuantity` **and**
  `shortQuantity` simultaneously remain ambiguous (pre-existing,
  unchanged by the fix; follow-up in fix.md).
- The live verification covers standard index/ETF options only (the
  account's current holdings); no MUTUAL_FUND / FIXED_INCOME /
  CASH_EQUIVALENT legs were live-verified (they take multiplier 1 and
  are covered by the equity test suite).

## Recommendation

Close the bug — verified end-to-end: offline reproduction with the exact
recorded payload (9/9), fresh live call through the fixed orchestration
(all legs dollarized-correct, sign-flip case fixed), and the full
regression suite green (1669 passed, 0 skipped). The two follow-ups in
`fix.md` (expose `multiplier`/`mark_price`, mixed-quantity handling) can
proceed as a separate spec.
