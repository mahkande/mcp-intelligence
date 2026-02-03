"""Python LSP discovery helpers for MCP registry.

This module exposes a lightweight, discovery-safe `get_advertised_tools(project_root)`
that the registry uses to learn about available Python/LSP capabilities without
starting any server processes or importing heavyweight runtime dependencies.

The implementation below is intentionally conservative: imports that may fail
in minimal environments are guarded and discovery only performs non-invasive
checks. If the LSP is missing or not configured for the project, the function
returns a single `python_lsp_unavailable` Tool with actionable instructions.
"""

import json
import asyncio
import sys
from pathlib import Path
from typing import List, Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Import the LSP proxy manager lazily; absence is tolerated during discovery.
try:
    from mcp_code_intelligence.core.lsp_proxy import get_manager  # type: ignore
except Exception:  # pragma: no cover - handled at runtime
    get_manager = None  # type: ignore


# Lightweight check for python-lsp-server (pylsp). We don't rely on it being
# present at import time; discovery will inspect availability and advertise
# an actionable fix if missing.
try:
    import pylsp  # type: ignore
    PYLSP_AVAILABLE = True
except Exception:
    PYLSP_AVAILABLE = False


class PythonLSPServer:  # pragma: no cover - small compatibility stub
    """Compatibility stub so `from ... import PythonLSPServer` continues to work.

    The real server implementation lives in the runtime code; this stub keeps
    package imports safe during discovery.
    """
    pass


def get_advertised_tools(project_root: Path) -> List[Tool]:
    """Return discovery-only `Tool` descriptors for Python LSP support.

    This function performs only lightweight checks and never starts or manages
    server processes. The returned `Tool` objects are safe for the registry
    to inspect and present to the Agent.
    """
    # If the language server package isn't available, advertise an unavailable tool.
    if not PYLSP_AVAILABLE:
        return [
            Tool(
                name="python_lsp_unavailable",
                description=(
                    "LSP unavailable: python-lsp-server (pylsp) is not installed. "
                    "Install with: pip install python-lsp-server"
                ),
                inputSchema={"type": "object", "properties": {}},
            )
        ]

    # Try to inspect per-project manager configuration; treat failures as
    # non-fatal and fall back to advertising the LSP tools.
    try:
        if get_manager is not None:
            mgr = get_manager(project_root)
            try:
                cfg = mgr._load_config() if hasattr(mgr, "_load_config") else {}
            except Exception:
                cfg = {}
            if not cfg:
                return [
                    Tool(
                        name="python_lsp_unavailable",
                        description=(
                            "LSP unavailable: no language LSPs configured for this project. "
                            "Add .mcp/mcp.json languageLsps entries or run `mcp start-lsp`."
                        ),
                        inputSchema={"type": "object", "properties": {}},
                    )
                ]
    except Exception:
        # Non-fatal: continue to advertise tools below.
        pass

    # Discovery-only tool descriptors (do not start servers here).
    return [
        Tool(
            name="goto_definition",
            description="Find definition of a symbol at given position (via LSP)",
            inputSchema={
                "type": "object",
                "properties": {
                    "relative_path": {"type": "string"},
                    "line": {"type": "number"},
                    "character": {"type": "number"},
                },
                "required": ["relative_path", "line", "character"],
            },
        ),
        Tool(
            name="find_references",
            description="Find all references to a symbol (via LSP)",
            inputSchema={
                "type": "object",
                "properties": {
                    "relative_path": {"type": "string"},
                    "line": {"type": "number"},
                    "character": {"type": "number"},
                },
                "required": ["relative_path", "line", "character"],
            },
        ),
        Tool(
            name="get_hover_info",
            description="Get type and documentation for symbol at position (via LSP)",
            inputSchema={
                "type": "object",
                "properties": {
                    "relative_path": {"type": "string"},
                    "line": {"type": "number"},
                    "character": {"type": "number"},
                },
                "required": ["relative_path", "line", "character"],
            },
        ),
        Tool(
            name="get_completions",
            description="Get code completion suggestions (via LSP)",
            inputSchema={
                "type": "object",
                "properties": {
                    "relative_path": {"type": "string"},
                    "line": {"type": "number"},
                    "character": {"type": "number"},
                },
                "required": ["relative_path", "line", "character"],
            },
        ),
    ]


class PythonLSPServerInstance:
    """Real MCP server instance for Python LSP."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.server = Server("python-lsp")
        self._setup_handlers()
        
        # Setup activity logging
        try:
            from mcp_code_intelligence.core.logging_setup import setup_activity_logging
            setup_activity_logging(self.project_root, "python-lsp")
        except Exception:
            pass

    def _setup_handlers(self):
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            return get_advertised_tools(self.project_root)

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> list[TextContent]:
            from loguru import logger
            logger.info(f"🐍 [Python LSP] {name} (Args: {json.dumps(arguments or {})[:100]}...)")
            from mcp_code_intelligence.core.lsp_proxy import get_manager
            mgr = get_manager(self.project_root)
            
            # Map MCP tool calls to LSP requests
            method_map = {
                "goto_definition": "textDocument/definition",
                "find_references": "textDocument/references",
                "get_hover_info": "textDocument/hover",
                "get_completions": "textDocument/completion"
            }
            
            if name not in method_map:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]
                
            try:
                # Basic LSP request via proxy
                lsp_method = method_map[name]
                # Note: This is a simplified proxy call. 
                # Real implementation would need to convert relative_path to URI and back.
                res = await mgr.request("python", lsp_method, arguments)
                return [TextContent(type="text", text=json.dumps(res, indent=2))]
            except Exception as e:
                return [TextContent(type="text", text=f"LSP Error: {e}")]

    async def run(self):
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


def main():
    """Main entry point for Python LSP server."""
    project_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    server = PythonLSPServerInstance(project_root)
    asyncio.run(server.run())


if __name__ == "__main__":
    import json
    main()
