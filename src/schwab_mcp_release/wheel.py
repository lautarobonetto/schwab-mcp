"""Wheel build via the existing toolchain (``uv build --wheel``).

Contract: ``specs/009-mcp-release-packaging/contracts/archive-layout.md``
(wheel contains ONLY the ``schwab_mcp`` runtime package, FR-003).
Reuse decision: research D2 — the shipped wheel is built by the project's
existing setuptools/uv toolchain, never re-implemented here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from schwab_mcp_release import ReleaseError


class WheelBuildError(ReleaseError):
    """The wheel build could not complete (tool error, missing output)."""


@dataclass(frozen=True)
class WheelBuild:
    """The produced wheel: *name* is the file name, *path* its location."""

    name: str
    path: Path


def build_wheel(project_root: Path, out_dir: Path) -> WheelBuild:
    """Build the runtime wheel with ``uv build --wheel`` into *out_dir*."""
    raise NotImplementedError("wheel build lands with T017 (US1)")
