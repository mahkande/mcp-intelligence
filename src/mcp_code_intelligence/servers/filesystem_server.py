"""Filesystem MCP Server - Python implementation.

Provides file system access capabilities via MCP protocol.
Supports reading, writing, listing files and directories.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from loguru import logger
logger.remove()

import logging
class InterceptHandler(logging.Handler):
    def emit(self, record):
        logger.opt(depth=6, exception=record.exc_info).log(record.levelname, record.getMessage())
logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO)

import builtins
_orig_print = builtins.print
def mcp_print(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    _orig_print(*args, **kwargs)
builtins.print = mcp_print

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from mcp_code_intelligence.core.llm_factory import wire_llm_to_server


class FilesystemServer:
    """MCP Server for filesystem operations."""

    def __init__(self, allowed_directory: Path):
        """Initialize filesystem server.

        Args:
            allowed_directory: Root directory for file operations (security boundary)
        """
        self.allowed_directory = Path(allowed_directory).resolve()
        self.server = Server("filesystem")
        self._setup_handlers()

        # Setup activity logging
        try:
            from mcp_code_intelligence.core.logging_setup import setup_activity_logging
            setup_activity_logging(self.allowed_directory, "filesystem")
        except Exception:
            pass

        # Wire LLM client if config has keys
        try:
            wire_llm_to_server(self, project_root=self.allowed_directory)
        except Exception:
            pass

    def _is_path_allowed(self, path: Path) -> bool:
        """Check if path is within allowed directory."""
        try:
            resolved = path.resolve()
            return resolved.is_relative_to(self.allowed_directory)
        except (ValueError, OSError):
            return False

    def _setup_handlers(self):
        """Setup MCP protocol handlers."""
        # register the server's advertised tools
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            return self.advertised_tools()

    def advertised_tools(self) -> list[Tool]:
        """Return the list of Tool objects this server advertises (callable by registry)."""
        return [
            Tool(
                name="read_file",
                description="Read contents of a file (Last resort: use LSP tools first)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "relative_path": {
                            "type": "string",
                            "description": "Path to file (relative to allowed directory)"
                        }
                    },
                    "required": ["relative_path"]
                }
            ),
            Tool(
                name="write_file",
                description="Write content to a file",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "relative_path": {
                            "type": "string",
                            "description": "Path to file"
                        },
                        "content": {
                            "type": "string",
                            "description": "Content to write"
                        }
                    },
                    "required": ["relative_path", "content"]
                }
            ),
            Tool(
                name="list_directory",
                description="List contents of a directory",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "relative_path": {
                            "type": "string",
                            "description": "Directory path (default: root)"
                        }
                    }
                }
            ),
        ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> list[TextContent]:
            """Handle tool calls."""
            from loguru import logger
            logger.info(f"📁 [Filesystem] {name} (Args: {json.dumps(arguments or {})[:100]}...)")

            if name == "read_file":
                path = self.allowed_directory / arguments["relative_path"]
                if not self._is_path_allowed(path):
                    return [TextContent(
                        type="text",
                        text=f"Error: Access denied - path outside allowed directory"
                    )]

                try:
                    content = path.read_text(encoding="utf-8")
                    return [TextContent(type="text", text=content)]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error reading file: {e}")]

            elif name == "write_file":
                path = self.allowed_directory / arguments["relative_path"]
                if not self._is_path_allowed(path):
                    return [TextContent(
                        type="text",
                        text=f"Error: Access denied - path outside allowed directory"
                    )]

                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(arguments["content"], encoding="utf-8")
                    return [TextContent(type="text", text=f"Successfully wrote to {path.name}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error writing file: {e}")]

            elif name == "list_directory":
                dir_path = self.allowed_directory / arguments.get("relative_path", "")
                if not self._is_path_allowed(dir_path):
                    return [TextContent(
                        type="text",
                        text=f"Error: Access denied - path outside allowed directory"
                    )]

                try:
                    items = []
                    for item in sorted(dir_path.iterdir()):
                        item_type = "dir" if item.is_dir() else "file"
                        size = item.stat().st_size if item.is_file() else 0
                        items.append(f"{item_type:4} {size:>10} {item.name}")

                    result = "\n".join(items) if items else "(empty directory)"
                    return [TextContent(type="text", text=result)]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error listing directory: {e}")]

            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    async def run(self):
        """Run the server using stdio transport."""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


def main():
    """Entry point for filesystem server."""
    if len(sys.argv) < 2:
        print("Usage: python -m mcp_code_intelligence.servers.filesystem_server <allowed_directory>")
        sys.exit(1)

    allowed_dir = Path(sys.argv[1])
    if not allowed_dir.exists():
        print(f"Error: Directory does not exist: {allowed_dir}")
        sys.exit(1)

    server = FilesystemServer(allowed_dir)
    asyncio.run(server.run())


if __name__ == "__main__":
    main()


def get_advertised_tools(project_root: Path) -> list[Tool]:
    """Lightweight discovery: return the tools this module would advertise.

    This function is intentionally small and does not instantiate the server.
    """
    pr = Path(project_root) if project_root is not None else Path.cwd()

    # If the configured allowed directory doesn't exist, advertise a fix tool.
    if not pr.exists() or not pr.is_dir():
        return [
            Tool(
                name="filesystem_path_missing",
                description=(
                    "Filesystem tools unavailable: configured allowed directory does not exist. "
                    "Provide a valid directory or run the filesystem setup command."
                ),
                inputSchema={"type": "object", "properties": {}},
            )
        ]

    return [
        Tool(
            name="read_file",
            description="Read contents of a file (Last resort: use LSP tools first)",
            inputSchema={
                "type": "object",
                "properties": {
                    "relative_path": {
                        "type": "string",
                        "description": "Path to file (relative to allowed directory)"
                    }
                },
                "required": ["relative_path"]
            }
        ),
        Tool(
            name="write_file",
            description="Write content to a file",
            inputSchema={
                "type": "object",
                "properties": {
                    "relative_path": {
                        "type": "string",
                        "description": "Path to file"
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write"
                    }
                },
                "required": ["relative_path", "content"]
            }
        ),
        Tool(
            name="list_directory",
            description="List contents of a directory",
            inputSchema={"type": "object", "properties": {"relative_path": {"type": "string", "description": "Directory path (default: root)"}}}
        ),
    ]
