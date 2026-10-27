"""Manifest and checksum generation (stdlib ``hashlib`` only).

Contracts: ``specs/009-mcp-release-packaging/contracts/archive-layout.md``
(``manifest.json`` fields, ``SHA256SUMS`` format) and
``contracts/build-command.md`` (outer ``.zip.sha256``).

Self-reference rule: ``manifest.json`` and ``SHA256SUMS`` are the
inventory artifacts themselves and therefore describe the *content*
members — they cannot list their own hash.  One hash pass over the
payloads feeds both inventories (DRY).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Member:
    """One content member of the distribution archive."""

    path: str
    size: int
    sha256: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inventory(payloads: Mapping[str, bytes]) -> list[Member]:
    """Hash every member payload exactly once (input order preserved)."""
    return [Member(path=path, size=len(data), sha256=_sha256(data)) for path, data in payloads.items()]


def render_manifest(version: str, build_dirty: bool, members: Sequence[Member]) -> bytes:
    """Render ``manifest.json`` bytes (fields per data-model.md)."""
    doc = {
        "version": version,
        "build_dirty": build_dirty,
        "members": [
            {"path": member.path, "size": member.size, "sha256": member.sha256}
            for member in members
        ],
    }
    return (json.dumps(doc, indent=2) + "\n").encode()


def render_sha256sums(members: Sequence[Member]) -> bytes:
    """Render ``SHA256SUMS`` bytes: one sorted line per member."""
    lines = [f"{member.sha256}  {member.path}" for member in sorted(members, key=lambda m: m.path)]
    return ("\n".join(lines) + "\n").encode()


def write_outer_checksum(archive_path: Path) -> Path:
    """Write ``<archive>.sha256`` containing ``<hex>  <archive name>``."""
    checksum_path = Path(str(archive_path) + ".sha256")
    checksum_path.write_text(f"{_sha256(archive_path.read_bytes())}  {archive_path.name}\n")
    return checksum_path
