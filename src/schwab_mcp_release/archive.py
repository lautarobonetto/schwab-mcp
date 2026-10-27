"""Archive assembly: allowlist members -> deterministic ``.zip``.

Contract: ``specs/009-mcp-release-packaging/contracts/archive-layout.md``.
Every member is written under the single wrapping top-level directory
``schwab-mcp-<version>/`` with normalized timestamps and in fixed allowlist
order (FR-002, FR-011).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ArchiveResult:
    """Outcome of one assembly run."""

    archive_path: Path
    member_count: int
    archive_size: int
    sha256: str


def assemble_archive(
    *,
    version: str,
    build_dirty: bool,
    sources: Mapping[str, Path],
    out_zip: Path,
) -> ArchiveResult:
    """Assemble the archive at *out_zip* from *sources* (allowlist path -> file).

    ``manifest.json`` and ``SHA256SUMS`` are generated from the member
    inventory; all other members are copied verbatim from *sources*.
    """
    raise NotImplementedError("archive assembly lands with T019 (US1)")
