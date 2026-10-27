"""Version resolution from ``pyproject.toml`` (single source of truth).

Contract: ``specs/009-mcp-release-packaging/contracts/build-command.md``
(FR-005) and research D4 — the version is read, never re-derived or
duplicated.  Failures name ``pyproject.toml`` explicitly.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from schwab_mcp_release import ReleaseError

_PYPROJECT = "pyproject.toml"


class VersionError(ReleaseError):
    """``pyproject.toml`` is missing, malformed, or has no ``project.version``."""


def default_project_root() -> Path:
    """Repository root as seen from this source tree (``src/`` layout)."""
    return Path(__file__).resolve().parents[2]


def resolve_version(project_root: Path | None = None) -> str:
    """Return exactly the ``[project].version`` string of ``pyproject.toml``."""
    root = project_root if project_root is not None else default_project_root()
    pyproject = root / _PYPROJECT
    try:
        raw = pyproject.read_text()
    except OSError as exc:
        raise VersionError(f"{_PYPROJECT} not readable at {pyproject}: {exc}") from exc
    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise VersionError(f"{_PYPROJECT} is malformed at {pyproject}: {exc}") from exc
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise VersionError(f"{_PYPROJECT} has no [project] version at {pyproject}")
    return version
