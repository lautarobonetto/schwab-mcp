"""Build gates: completeness, dev-material exclusion, secret scan.

Contracts: ``specs/009-mcp-release-packaging/contracts/archive-layout.md``
(allowed members, forbidden content) and ``contracts/build-command.md``
(exit-code 1 message shapes).  All three checks are driven by the allowlist
module (single source of truth, DRY) and scan the FINAL archive members.
Failures are reported by member name only — never by content (FR-004).
"""

from __future__ import annotations

from pathlib import Path


def check_completeness(zip_path: Path, version: str) -> list[str]:
    """Return ``MISSING: <path>``/``UNEXPECTED: <path>`` lines (empty = pass)."""
    raise NotImplementedError("completeness check lands with T020 (US1)")


def check_dev_material(zip_path: Path, version: str) -> list[str]:
    """Return ``DEV-MATERIAL: <path>`` lines for forbidden dev content (empty = pass)."""
    raise NotImplementedError("exclusion scan lands with T030 (US3)")


def check_secrets(zip_path: Path, version: str) -> list[str]:
    """Return ``SECRET: <path>`` lines for secret-bearing members (empty = pass)."""
    raise NotImplementedError("secret scan lands with T031 (US3)")
