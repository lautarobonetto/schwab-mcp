"""Release build command: orchestrate build -> validate -> emit.

Contract: ``specs/009-mcp-release-packaging/contracts/build-command.md``.
Stdout is a stable, testable contract; failure messages go to stderr and
name the offending/missing piece only (never file content).
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence


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

    raise NotImplementedError("build orchestration lands with T021 (US1)")
