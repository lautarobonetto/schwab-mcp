"""Archive allowlist — the single source of truth of shipped members.

Contract: ``specs/009-mcp-release-packaging/contracts/archive-layout.md``.
This module drives BOTH archive assembly (FR-002) and the completeness
check (FR-008) — one authoritative member list, no duplication (DRY,
research D5).  It also centralizes the forbidden-content rules consumed by
the dev-material and secret scans (FR-003, FR-004).

Every member lives under the single wrapping top-level directory
``schwab-mcp-<version>/`` and is assembled in the fixed order below
(FR-011).  ``manifest.json`` and ``SHA256SUMS`` are generated inventory
artifacts: they are required archive members but not *content* members
(they cannot list their own hash).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MemberSpec:
    """One allowlist entry (path relative to the wrapping directory)."""

    path: str
    required: bool
    generated: bool
    source: str  # human-readable provenance, quoted from archive-layout.md


def wrap_dir(version: str) -> str:
    """Name of the single top-level wrapping directory inside the zip."""
    return f"schwab-mcp-{version}"


def wheel_name(version: str) -> str:
    """File name of the shipped runtime wheel (only package: ``schwab_mcp``)."""
    return f"schwab_mcp-{version}-py3-none-any.whl"


# Single authoritative table of the content members (TD-014): both
# ``member_specs()`` and ``source_map()`` derive from it, so adding a member
# is a one-place edit.  Columns: (archive path, source path relative to the
# project root, provenance quoted from contracts/archive-layout.md).  The
# wheel is the one dynamic entry — ``_WHEEL`` resolves via ``wheel_name()``
# in the archive and to the built wheel file on disk.
_WHEEL = "<wheel>"

_CONTENT_MEMBER_TABLE: tuple[tuple[str, str, str], ...] = (
    ("README.md", "docs/release/README.md", "docs/release/README.md (verbatim copy)"),
    (_WHEEL, _WHEEL, "runtime wheel (only package schwab_mcp)"),
    ("manuals/installation.md", "docs/release/installation.md", "docs/release/installation.md"),
    (
        "manuals/first-run-authentication.md",
        "docs/release/first-run-authentication.md",
        "docs/release/first-run-authentication.md",
    ),
    ("manuals/usage.md", "docs/release/usage.md", "docs/release/usage.md"),
    ("manuals/troubleshooting.md", "docs/release/troubleshooting.md", "docs/release/troubleshooting.md"),
    ("install.sh", "src/schwab_mcp_release/install.sh", "src/schwab_mcp_release/install.sh"),
)


def _member_path(table_path: str, version: str) -> str:
    """Resolve a table path to its archive-relative member path."""
    return f"dist/{wheel_name(version)}" if table_path == _WHEEL else table_path


def _member_source(table_source: str, project_root: Path, wheel_path: Path) -> Path:
    """Resolve a table source to its on-disk source file."""
    return wheel_path if table_source == _WHEEL else project_root / table_source


def member_specs(version: str) -> tuple[MemberSpec, ...]:
    """The exact member set of ``contracts/archive-layout.md``, fixed order.

    Content members derive from ``_CONTENT_MEMBER_TABLE``; the generated
    inventory artifacts follow (they cannot list their own hash).
    """
    content = tuple(
        MemberSpec(_member_path(path, version), True, False, provenance)
        for path, _source_rel, provenance in _CONTENT_MEMBER_TABLE
    )
    return content + (
        MemberSpec("manifest.json", True, True, "generated: version, build_dirty, member inventory"),
        MemberSpec("SHA256SUMS", True, True, "generated: one sorted line per member"),
    )


def content_members(version: str) -> tuple[MemberSpec, ...]:
    """Members copied from disk (excludes the generated inventory artifacts)."""
    return tuple(spec for spec in member_specs(version) if not spec.generated)


def source_map(project_root: Path, version: str, wheel_path: Path) -> dict[str, Path]:
    """Map every content-member archive path to its on-disk source file.

    Derived from ``_CONTENT_MEMBER_TABLE`` — same list as ``member_specs``.
    """
    return {
        _member_path(path, version): _member_source(source_rel, project_root, wheel_path)
        for path, source_rel, _provenance in _CONTENT_MEMBER_TABLE
    }


# ---------------------------------------------------------------------------
# Forbidden content rules (verbatim from contracts/archive-layout.md)
# ---------------------------------------------------------------------------

# Paths matching: ``tests/``, ``specs/``, ``plans/``, ``.git*``,
# ``__pycache__/``, ``*.egg-info/``, dev config (``pyproject.toml`` itself,
# dev scripts) and editable source trees (``src/``).
FORBIDDEN_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|/)tests/"),
    re.compile(r"(^|/)specs/"),
    re.compile(r"(^|/)plans/"),
    re.compile(r"(^|/)\.git[^/]*(/|$)"),
    re.compile(r"(^|/)__pycache__/"),
    re.compile(r"(^|/)[^/]*\.egg-info(/|$)"),
    re.compile(r"(^|/)pyproject\.toml$"),
    re.compile(r"(^|/)src/"),
)

# File names: ``.env``, ``*.pem``, ``*token*db*``, ``*secret*``,
# ``*credential*`` (dev-material + secret-bearing names).
FORBIDDEN_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|/)\.env(\.[^/]*)?$"),
    re.compile(r"\.pem$"),
    re.compile(r"token[^/]*db", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
)

# Text patterns in members (reported by member name only — never content):
# OAuth token/key shapes, ``api_key =``, ``app_key =``, bearer token
# literals.  Values must be quoted literals so runtime code that merely
# *handles* credentials is never flagged.
SECRET_CONTENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)(?<![\w-])(api[_-]?key|app[_-]?key|client[_-]?secret|secret[_-]?key"
        r"|refresh[_-]?token|access[_-]?token|id[_-]?token)\s*[:=]\s*[\"'][^\"']{8,}[\"']"
    ),
    re.compile(r"(?i)\bbearer\s+[a-z0-9\-._~+/]{20,}={0,2}"),
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
)
