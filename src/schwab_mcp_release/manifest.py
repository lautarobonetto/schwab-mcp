"""Manifest and checksum generation (stdlib ``hashlib`` only).

Contracts: ``specs/009-mcp-release-packaging/contracts/archive-layout.md``
(``manifest.json`` fields, ``SHA256SUMS`` format) and
``contracts/build-command.md`` (outer ``.zip.sha256``).  One hash pass over
the members feeds both inventories (DRY).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Member:
    """One content member of the distribution archive."""

    path: str
    size: int
    sha256: str


def inventory(sources: Mapping[str, Path]) -> list[Member]:
    """Hash every source file exactly once (allowlist order)."""
    raise NotImplementedError("inventory lands with T018 (US1)")


def render_manifest(version: str, build_dirty: bool, members: Sequence[Member]) -> bytes:
    """Render ``manifest.json`` bytes (fields per data-model.md)."""
    raise NotImplementedError("manifest lands with T018 (US1)")


def render_sha256sums(members: Sequence[Member]) -> bytes:
    """Render ``SHA256SUMS`` bytes: one sorted line per member."""
    raise NotImplementedError("checksums land with T018 (US1)")


def write_outer_checksum(archive_path: Path) -> Path:
    """Write ``<archive>.sha256`` containing ``<hex>  <archive name>``."""
    raise NotImplementedError("outer checksum lands with T018 (US1)")
