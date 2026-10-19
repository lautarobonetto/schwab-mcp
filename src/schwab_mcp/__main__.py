"""Allow `python -m schwab_mcp` to delegate to the CLI."""

from schwab_mcp.cli import main

if __name__ == "__main__":
    main()