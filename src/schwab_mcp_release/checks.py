"""Build gates: completeness, dev-material exclusion, secret scan.

Contracts: ``specs/009-mcp-release-packaging/contracts/archive-layout.md``
(allowed members, forbidden content) and ``contracts/build-command.md``
(exit-code 1 message shapes).  All three checks are driven by the allowlist
module (single source of truth, DRY) and scan the FINAL archive members.
Failures are reported by member name only — never by content (FR-004).
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from schwab_mcp_release.allowlist import member_specs, wrap_dir


def check_completeness(zip_path: Path, version: str) -> list[str]:
    """Return ``MISSING: <path>``/``UNEXPECTED: <path>`` lines (empty = pass).

    Every required allowlist member must exist and be non-empty (a
    zero-byte required member counts as missing); no other entry may
    exist under the wrapping directory (FR-008).
    """
    wrap = wrap_dir(version)
    expected = {f"{wrap}/{spec.path}": spec for spec in member_specs(version)}
    problems: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        infos = {info.filename: info for info in zf.infolist()}
    for full_path, spec in expected.items():
        info = infos.get(full_path)
        if info is None or info.file_size == 0:
            problems.append(f"MISSING: {spec.path}")
    for name in infos:
        if name not in expected:
            relative = name[len(wrap) + 1 :] if name.startswith(f"{wrap}/") else name
            problems.append(f"UNEXPECTED: {relative}")
    return problems


def check_dev_material(zip_path: Path, version: str) -> list[str]:
    """Return ``DEV-MATERIAL: <path>`` lines for forbidden dev content (empty = pass)."""
    raise NotImplementedError("exclusion scan lands with T030 (US3)")


def check_secrets(zip_path: Path, version: str) -> list[str]:
    """Return ``SECRET: <path>`` lines for secret-bearing members (empty = pass)."""
    raise NotImplementedError("secret scan lands with T031 (US3)")
