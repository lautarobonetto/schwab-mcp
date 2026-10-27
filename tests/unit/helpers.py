"""Shared unit-test helpers (single source of truth — Constitution II)."""

from __future__ import annotations

import contextlib
import json
import shutil
import uuid
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator

import requests


def build_response(payload, status: int = 200) -> requests.Response:
    """Build a real ``requests.Response`` carrying a JSON *payload*.

    Mimics the objects the ``schwabdev`` client returns for every API call
    (the SDK does not pre-parse JSON bodies).
    """
    r = requests.Response()
    r.status_code = status
    if payload is not None:
        r._content = json.dumps(payload).encode()
    return r


# =============================================================================
# Option chain fixtures (feature 008 — single source of contract field names)
# =============================================================================


def build_contract(
    kind: str,
    strike: float,
    *,
    delta: float | None = None,
    expiration_date: str | None = None,
    **overrides,
) -> dict:
    """Build a provider option-contract dict (schwabdev ``option_chains`` shape).

    *kind* is ``"CALL"`` or ``"PUT"``.  All source fields from research R6 are
    present with plausible defaults; *overrides* replaces any of them
    (pass ``field=None`` to simulate a missing field for FR-007 tests).
    """
    base_delta = 0.5 if kind == "CALL" else -0.5
    contract = {
        "putCall": kind,
        "symbol": f"TEST  {expiration_date or '261030'}{kind[0]}{int(strike * 1000):08d}",
        "strikePrice": float(strike),
        "bid": round(10.0 + strike % 7, 2),
        "ask": round(10.2 + strike % 7, 2),
        "last": round(10.1 + strike % 7, 2),
        "mark": round(10.1 + strike % 7, 2),
        "markChange": round(0.1 + strike % 3, 2),
        "markPercentChange": round(0.5 + strike % 4, 2),
        "highPrice": round(11.0 + strike % 7, 2),
        "lowPrice": round(9.0 + strike % 7, 2),
        "openPrice": round(10.0 + strike % 7, 2),
        "closePrice": round(10.0 + strike % 7, 2),
        "totalVolume": int(100 + strike % 900),
        "openInterest": int(500 + strike % 4000),
        "volatility": round(0.2105 + (strike % 5) / 100, 4),
        "delta": round(base_delta - (strike % 3) / 100, 4),
        "gamma": round(0.0310 + (strike % 2) / 1000, 4),
        "theta": round(-0.0840 - (strike % 3) / 1000, 4),
        "vega": round(0.0620 + (strike % 2) / 1000, 4),
        "rho": round(-0.0118 - (strike % 2) / 1000, 4),
        "theoreticalOptionValue": round(10.1 + strike % 7, 2),
        "timeValue": round(2.5 + strike % 3, 2),
        "multiplier": 100,
        "tradeTime": 1792854000000,
        "deliverableNote": None,
    }
    if delta is not None:
        contract["delta"] = float(delta)
    contract.update(overrides)
    return contract


def build_expiration_map(
    expiration_date: str,
    kind: str,
    strikes: list[float],
    *,
    deltas: list[float] | None = None,
    missing_strikes: list[float] | None = None,
    overrides: dict | None = None,
) -> dict:
    """Build one ``callExpDateMap``/``putExpDateMap`` entry.

    Returns ``{expiration_date: {key: contract}}``.  *deltas* (same length as
    *strikes*) sets per-strike deltas.  *missing_strikes* are omitted entirely
    (a whole contract missing from the map).  *overrides* applies to every
    contract of the map.
    """
    contracts: dict[str, dict] = {}
    missing = set(missing_strikes or [])
    for i, strike in enumerate(strikes):
        if strike in missing:
            continue
        delta = deltas[i] if deltas is not None else None
        key = f"{expiration_date}:{'XX'}:{int(strike * 1000):08d}:{kind}"
        contracts[key] = build_contract(
            kind,
            strike,
            delta=delta,
            expiration_date=expiration_date,
            **(overrides or {}),
        )
    return {expiration_date: contracts}


def build_chain_payload(
    call_map: dict | None = None,
    put_map: dict | None = None,
    *,
    symbol: str = "TEST",
    underlying_price: float | None = 251.31,
    is_delayed: bool = False,
    **overrides,
) -> dict:
    """Build a provider ``option_chains`` payload (research R1 shape).

    *call_map* / *put_map* are outputs of :func:`build_expiration_map`
    (multiple maps can be merged with ``{**a, **b}``).  Pass ``None`` (default)
    to simulate an entirely absent map; pass ``{}`` for an empty one.
    """
    payload = {
        "symbol": symbol,
        "status": "SUCCESS",
        "isDelayed": is_delayed,
        "underlyingPrice": underlying_price,
        "callExpDateMap": call_map,
        "putExpDateMap": put_map,
    }
    payload.update(overrides)
    return payload


def chain_expiry_date(days_ahead: int, today=None) -> str:
    """ISO date *days_ahead* calendar days from *today* (default today)."""
    base = today or date.today()
    return (base + timedelta(days=days_ahead)).isoformat()


# =============================================================================
# Release-packaging test infrastructure (feature 009)
# =============================================================================

REPO_ROOT = Path(__file__).resolve().parents[2]

RELEASE_SANDBOX_ROOT = REPO_ROOT / "tmp"


@contextlib.contextmanager
def release_sandbox(name: str = "release") -> Iterator[Path]:
    """Yield a fresh scratch directory under the repository ``tmp/``.

    Test sandboxes are scratch artifacts and therefore live in ``tmp/``
    per the constitution layout rules; the directory is removed on exit.
    """
    root = RELEASE_SANDBOX_ROOT / f"{name}-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def make_release_project(root: Path, version: str = "9.9.9") -> Path:
    """Scaffold a minimal release-build project skeleton under *root*.

    Creates ``pyproject.toml`` (*version*), the five ``docs/release/``
    manuals and ``src/schwab_mcp_release/install.sh`` — the on-disk source
    inputs the archive allowlist reads from.
    """
    (root / "pyproject.toml").write_text(
        '[project]\nname = "schwab-mcp"\n'
        f'version = "{version}"\n'
        'requires-python = ">=3.11"\n'
    )
    docs = root / "docs" / "release"
    docs.mkdir(parents=True, exist_ok=True)
    for manual in ("README", "installation", "first-run-authentication", "usage", "troubleshooting"):
        (docs / f"{manual}.md").write_text(f"# {manual}\n\nRecipient manual ({manual}).\n")
    script_dir = root / "src" / "schwab_mcp_release"
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "install.sh").write_text("#!/bin/sh\nset -eu\nexit 0\n")
    return root


def make_fake_wheel(out_dir: Path, version: str, extra_entries: tuple[str, ...] = ()) -> Path:
    """Build a minimal, valid, dependency-free wheel for release tests.

    The wheel carries only the ``schwab_mcp`` runtime package plus its
    ``dist-info`` — mirroring what ``uv build --wheel`` produces — unless
    *extra_entries* injects additional (possibly forbidden) zip entries.
    """
    dist_info = f"schwab_mcp-{version}.dist-info"
    name = f"schwab_mcp-{version}-py3-none-any.whl"
    out_dir.mkdir(parents=True, exist_ok=True)
    wheel_path = out_dir / name
    entries = {
        "schwab_mcp/__init__.py": b'"""Runtime package."""\n',
        "schwab_mcp/cli.py": (
            b'"""Fake CLI used by release tests."""\n'
            b"def main() -> None:\n"
            b'    print("schwab-mcp help")\n'
        ),
        f"{dist_info}/METADATA": (
            f"Metadata-Version: 2.1\nName: schwab-mcp\nVersion: {version}\n".encode()
        ),
        f"{dist_info}/WHEEL": b"Wheel-Version: 1.0\nGenerator: tests\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{dist_info}/top_level.txt": b"schwab_mcp\n",
        f"{dist_info}/entry_points.txt": b"[console_scripts]\nschwab-mcp = schwab_mcp.cli:main\n",
        f"{dist_info}/RECORD": b"",
    }
    for extra in extra_entries:
        entries[extra] = b"# injected entry\n"
    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for entry, data in entries.items():
            zf.writestr(entry, data)
    return wheel_path
