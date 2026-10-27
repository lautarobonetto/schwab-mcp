"""Build gates: completeness, dev-material exclusion, secret scan.

Contracts: ``specs/009-mcp-release-packaging/contracts/archive-layout.md``
(allowed members, forbidden content) and ``contracts/build-command.md``
(exit-code 1 message shapes).  All three checks are driven by the allowlist
module (single source of truth, DRY) and scan the FINAL archive members.
Failures are reported by member name only — never by content (FR-004).
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from pathlib import Path

from schwab_mcp_release.allowlist import (
    FORBIDDEN_NAME_PATTERNS,
    FORBIDDEN_PATH_PATTERNS,
    SECRET_CONTENT_PATTERNS,
    member_specs,
    wrap_dir,
)


def _iter_entries(zip_path: Path, version: str) -> Iterator[tuple[str, bytes]]:
    """Yield ``(report name, content)`` for every file in the final archive.

    Entries under the wrapping directory are reported relative to it;
    members nested inside the shipped wheel are reported as
    ``<wheel>!<entry>`` so scan failures name the full location.
    """
    prefix = f"{wrap_dir(version)}/"
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename[len(prefix) :] if info.filename.startswith(prefix) else info.filename
            data = zf.read(info)
            yield name, data
            if name.endswith(".whl"):
                with zipfile.ZipFile(io.BytesIO(data)) as inner:
                    for inner_info in inner.infolist():
                        if inner_info.is_dir():
                            continue
                        yield f"{name}!{inner_info.filename}", inner.read(inner_info)


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


def _matches(patterns: tuple, name: str) -> bool:
    """True when any pattern hits the report name or its nested segment.

    Nested wheel entries are reported as ``<wheel>!<entry>``; patterns use
    path boundaries (``^``/``/``), so the segment after ``!`` is matched
    on its own as well.
    """
    targets = (name, name.rsplit("!", 1)[-1]) if "!" in name else (name,)
    return any(pattern.search(target) for target in targets for pattern in patterns)


def check_dev_material(zip_path: Path, version: str) -> list[str]:
    """Return ``DEV-MATERIAL: <path>`` lines for forbidden dev content (empty = pass).

    Rules come from the allowlist (single source of truth, FR-003).  The
    scan covers every final archive member — including entries nested
    inside the shipped wheel — and reports member names only.
    """
    problems: list[str] = []
    for name, _data in _iter_entries(zip_path, version):
        if _matches(FORBIDDEN_PATH_PATTERNS, name):
            problems.append(f"DEV-MATERIAL: {name}")
    return problems


def check_secrets(zip_path: Path, version: str) -> list[str]:
    """Return ``SECRET: <path>`` lines for secret-bearing members (empty = pass).

    Credential safety (FR-004): the failure output names the member only —
    the matched content is never emitted.  Rules come from the allowlist:
    secret-bearing file names plus credential-shaped content patterns.
    """
    problems: list[str] = []
    for name, data in _iter_entries(zip_path, version):
        if _matches(FORBIDDEN_NAME_PATTERNS, name):
            problems.append(f"SECRET: {name}")
            continue
        text = data.decode("utf-8", errors="ignore")
        if any(pattern.search(text) for pattern in SECRET_CONTENT_PATTERNS):
            problems.append(f"SECRET: {name}")
    return problems
