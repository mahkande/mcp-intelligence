"""Entry point for running the MCP server."""

import asyncio
import sys
from pathlib import Path

from mcp_code_intelligence.mcp_impl.fast_server import run_mcp_server


def main():
    """Main entry point for the MCP server."""
    # Priority: 1. Explicit Arg (if dir), 2. Env Var, 3. CWD
    project_root = None
    if len(sys.argv) > 1:
        potential_path = Path(sys.argv[1])
        if potential_path.is_dir():
            project_root = potential_path

    try:
        # run_mcp_server is synchronous and manages its own event loop via FastMCP
        run_mcp_server(project_root)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"MCP server error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
