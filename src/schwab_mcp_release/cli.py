"""Release build command: orchestrate build -> validate -> emit.

Contract: ``specs/009-mcp-release-packaging/contracts/build-command.md``.
Stdout is a stable, testable contract (emitted only on success); failure
messages go to stderr and name the offending/missing piece only — never
file content (credential safety, FR-004).

Flow (FR-001): version -> dirty-tree guard -> wheel -> archive ->
manifest/checksums -> completeness/exclusion/secret checks -> emit.
Staging happens under ``tmp/release-staging/`` and is cleaned up on every
outcome; on failure no archive is presented as valid and no checksum file
is written (FR-008/FR-009).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from schwab_mcp_release import ReleaseError
from schwab_mcp_release.allowlist import source_map
from schwab_mcp_release.archive import assemble_archive
from schwab_mcp_release.checks import check_completeness, check_dev_material, check_secrets
from schwab_mcp_release.manifest import write_outer_checksum
from schwab_mcp_release.version import VersionError, default_project_root, resolve_version
from schwab_mcp_release.wheel import WheelBuildError, build_wheel

_DIRTY_MESSAGE = "working tree has uncommitted changes; pass --allow-dirty to build anyway"


def _project_root() -> Path:
    """Nearest directory above ``cwd`` holding a ``pyproject.toml``."""
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return default_project_root()


def _tree_is_dirty(root: Path) -> bool:
    """True when *root* is a git working tree with uncommitted changes.

    Non-git project roots carry no tree state to guard and count as clean.
    """
    try:
        toplevel = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    if toplevel.returncode != 0 or Path(toplevel.stdout.strip()).resolve() != root.resolve():
        return False
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    return bool(status.stdout.strip())


def cmd_build(output_dir: Path, allow_dirty: bool) -> int:
    """Build one distribution package.  Returns the process exit code."""
    started = time.monotonic()
    root = _project_root()
    staging = root / "tmp" / "release-staging"
    try:
        try:
            version = resolve_version(root)
        except VersionError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 3

        build_dirty = _tree_is_dirty(root)
        if build_dirty and not allow_dirty:
            print(_DIRTY_MESSAGE, file=sys.stderr)
            return 2

        try:
            wheel = build_wheel(root, staging)
        except WheelBuildError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 3

        sources = source_map(root, version, wheel.path)
        for member_path, src in sources.items():
            if not src.is_file():
                print(f"error: missing source file for {member_path}: {src}", file=sys.stderr)
                return 3

        try:
            result = assemble_archive(
                version=version,
                build_dirty=build_dirty,
                sources=sources,
                out_zip=staging / f"schwab-mcp-{version}.zip",
            )
        except ReleaseError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 3

        problems = check_completeness(result.archive_path, version)
        problems += check_dev_material(result.archive_path, version)
        problems += check_secrets(result.archive_path, version)
        if problems:
            for line in problems:
                print(line, file=sys.stderr)
            return 1

        output_dir.mkdir(parents=True, exist_ok=True)
        archive_path = output_dir / f"schwab-mcp-{version}.zip"
        shutil.move(result.archive_path, archive_path)
        checksum_path = write_outer_checksum(archive_path)

        print(f"BUILD schwab-mcp {version}")
        print(f"WHEEL  {wheel.name}")
        print(f"ARCHIVE members={result.member_count} bytes={result.archive_size}")
        print("CHECKS completeness=PASS exclusion=PASS secrets=PASS")
        print(f"OUT    {archive_path}")
        print(f"OUT    {checksum_path}")
        print(f"OK     build complete in {time.monotonic() - started:.1f}s")
        return 0
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and dispatch the release commands.

    Returns the process exit code (0 success, 1 validation failure,
    2 dirty working tree, 3 build prerequisite failure).
    """
    parser = argparse.ArgumentParser(prog="schwab-mcp-release")
    subparsers = parser.add_subparsers(dest="command")
    build = subparsers.add_parser("build", help="Build the distribution archive")
    build.add_argument(
        "--allow-dirty",
        action="store_true",
        help="permit building from a working tree with uncommitted changes",
    )
    build.add_argument(
        "--output-dir",
        default="dist",
        help="directory that receives the archive and its checksum file (default: dist)",
    )
    args = parser.parse_args(argv)

    if args.command != "build":
        parser.print_help()
        return 0

    return cmd_build(Path(args.output_dir), args.allow_dirty)
