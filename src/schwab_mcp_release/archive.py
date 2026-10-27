"""Archive assembly: allowlist members -> deterministic ``.zip``.

Contract: ``specs/009-mcp-release-packaging/contracts/archive-layout.md``.
Every member is written under the single wrapping top-level directory
``schwab-mcp-<version>/`` with normalized timestamps, fixed permissions
and fixed allowlist order (FR-002, FR-011).  ``manifest.json`` and
``SHA256SUMS`` are generated from the member inventory (one hash pass).
"""

from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from schwab_mcp_release import ReleaseError
from schwab_mcp_release.allowlist import content_members, member_specs, wrap_dir
from schwab_mcp_release.manifest import inventory, render_manifest, render_sha256sums

# Normalized member timestamp: zip epoch (FR-011 reproducibility).
FIXED_DATE_TIME = (1980, 1, 1, 0, 0, 0)
_MODE_EXECUTABLE = 0o755
_MODE_PLAIN = 0o644


@dataclass(frozen=True)
class ArchiveResult:
    """Outcome of one assembly run.

    *member_count* counts the content members (the generated inventory
    files ``manifest.json``/``SHA256SUMS`` are not members).
    """

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
    payloads: dict[str, bytes] = {}
    for spec in content_members(version):
        src = sources.get(spec.path)
        if src is None or not Path(src).is_file():
            raise ReleaseError(f"missing source file for member {spec.path}: {src}")
        payloads[spec.path] = Path(src).read_bytes()

    members = inventory(payloads)
    generated = {
        "manifest.json": render_manifest(version, build_dirty, members),
        "SHA256SUMS": render_sha256sums(members),
    }

    wrap = wrap_dir(version)
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for spec in member_specs(version):
            data = payloads.get(spec.path, generated.get(spec.path))
            info = zipfile.ZipInfo(f"{wrap}/{spec.path}", date_time=FIXED_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = _MODE_EXECUTABLE if spec.path == "install.sh" else _MODE_PLAIN
            info.external_attr = mode << 16
            zf.writestr(info, data)

    raw = out_zip.read_bytes()
    return ArchiveResult(
        archive_path=out_zip,
        member_count=len(payloads),
        archive_size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )
