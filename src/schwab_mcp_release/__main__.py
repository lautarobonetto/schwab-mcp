"""``python -m schwab_mcp_release`` entry point.

Equivalent to the ``schwab-mcp-release`` console script (see
``specs/009-mcp-release-packaging/contracts/build-command.md``).
"""

from __future__ import annotations

import sys

from schwab_mcp_release.cli import main

if __name__ == "__main__":
    sys.exit(main())
