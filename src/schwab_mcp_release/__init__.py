"""Maintainer-only release packaging for schwab-mcp (NOT shipped to recipients).

Implements the build command contract of
``specs/009-mcp-release-packaging/contracts/build-command.md``.  This package
is structurally excluded from the shipped wheel (``packages = ["schwab_mcp"]``
in ``pyproject.toml``; FR-003) so recipients never receive build tooling.
"""

from __future__ import annotations


class ReleaseError(Exception):
    """Base class for release-tooling failures.

    The message names the offending/missing piece only — never the content
    of any file (credential safety, FR-004).
    """
