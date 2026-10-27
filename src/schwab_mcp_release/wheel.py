"""Wheel build via the existing toolchain (``uv build --wheel``).

Contract: ``specs/009-mcp-release-packaging/contracts/archive-layout.md``
(wheel contains ONLY the ``schwab_mcp`` runtime package, FR-003).
Reuse decision: research D2 — the shipped wheel is built by the project's
existing setuptools/uv toolchain, never re-implemented here.  The wheel
file name comes from the allowlist (single source of truth).
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from schwab_mcp_release import ReleaseError
from schwab_mcp_release.allowlist import wheel_name
from schwab_mcp_release.version import resolve_version

# Fixed epoch for wheel zip metadata (FR-011): without normalization the
# generated dist-info entries carry build-time timestamps and the wheel
# bytes — hence the archive digest — drift between builds.
_SOURCE_DATE_EPOCH = "1"


class WheelBuildError(ReleaseError):
    """The wheel build could not complete (tool error, missing output)."""


@dataclass(frozen=True)
class WheelBuild:
    """The produced wheel: *name* is the file name, *path* its location."""

    name: str
    path: Path


def build_wheel(project_root: Path, out_dir: Path) -> WheelBuild:
    """Build the runtime wheel with ``uv build --wheel`` into *out_dir*.

    Raises :class:`WheelBuildError` naming the tool error when the build
    fails or does not produce exactly the expected wheel.
    """
    expected = wheel_name(resolve_version(project_root))
    out_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "SOURCE_DATE_EPOCH": _SOURCE_DATE_EPOCH}
    try:
        proc = subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(out_dir)],
            cwd=project_root,
            capture_output=True,
            text=True,
            env=env,
        )
    except OSError as exc:
        raise WheelBuildError(f"wheel build failed: uv could not run: {exc}") from exc
    if proc.returncode != 0:
        detail = [line for line in (proc.stderr or proc.stdout).splitlines() if line.strip()]
        raise WheelBuildError(
            "wheel build failed: " + (detail[-1] if detail else f"uv exited {proc.returncode}")
        )
    found = sorted(path.name for path in out_dir.glob("*.whl"))
    if found != [expected]:
        raise WheelBuildError(
            f"wheel build failed: expected {expected}, found {found or 'nothing'}"
        )
    return WheelBuild(name=expected, path=out_dir / expected)
