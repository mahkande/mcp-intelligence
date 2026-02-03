import asyncio
import os
import sys
import json
import builtins
import logging
from pathlib import Path
from typing import Any

# --- CRITICAL: PROTOCOL INTEGRITY SECTION ---
# This must run before any other imports to catch their logs/prints.

# 1. HuggingFace / Transformers suppress (often leak to stdout)
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false" # Prevent fork warnings

# 2. Loguru cleanup
from loguru import logger
logger.remove()

# 3. Standard logging redirection
class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())

logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO)

# 4. Print hijacking to stderr
_orig_print = builtins.print
def mcp_print(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    _orig_print(*args, **kwargs)
builtins.print = mcp_print

# --- END PROTOCOL INTEGRITY SECTION ---

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequest,
    CallToolResult,
    ServerCapabilities,
    TextContent,
    Tool,
)

from mcp_code_intelligence.analysis import (
    ProjectMetrics,
    SmellDetector,
    SmellSeverity,
)
from mcp_code_intelligence.config.thresholds import ThresholdConfig
from mcp_code_intelligence.core.exceptions import ProjectNotFoundError
from mcp_code_intelligence.core.project import ProjectManager
from mcp_code_intelligence.core.lsp_proxy import get_manager, stop_proxies
from mcp_code_intelligence.core import formatters
from mcp_code_intelligence.parsers.registry import ParserRegistry

# Import new services
from mcp_code_intelligence.mcp_impl.services import SessionService, RoutingService, ProtocolService


class MCPVectorSearchServer:
    """MCP server for vector search - service-oriented architecture."""

    def __init__(
        self,
        project_root: Path | None = None,
        enable_file_watching: bool | None = None,
    ):
        """Initialize MCP server with auto-detection and service wiring.

        Args:
            project_root: Project root directory (auto-detected if None)
            enable_file_watching: Enable file watching (from env var if None)
        """
        # --- Startup logging: env keys and interpreter ---
        critical_envs = [k for k in os.environ if any(x in k for x in ["JINA", "OPENAI", "MCP", "API_KEY", "TOKEN"])]
        masked = {k: (v[:2] + "****" if v else "****") for k, v in os.environ.items() if k in critical_envs}
        logger.info(f"[Startup] Kritik env anahtarları: {masked}")
        logger.info(f"[Startup] Aktif Python: {sys.executable}")

        # Auto-detect project root
        if project_root is None:
            env_project_root = os.getenv("MCP_PROJECT_ROOT") or os.getenv("PROJECT_ROOT")
            if env_project_root:
                project_root = Path(env_project_root).resolve()
                logger.info(f"Using project root from environment: {project_root}")
            else:
                project_root = Path.cwd()
                logger.info(f"Using current directory as project root: {project_root}")

        self.project_root = project_root
        self.project_manager = ProjectManager(self.project_root)

        # Determine file watching setting
        if enable_file_watching is None:
            env_value = os.getenv("MCP_ENABLE_FILE_WATCHING", "true").lower()
            enable_file_watching = env_value in ("true", "1", "yes", "on")

        # Wire services
        self.session_service = SessionService(project_root, enable_file_watching)
        self.routing_service = RoutingService()
        self.protocol_service = ProtocolService()

        # Register tool handlers
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Register all tool handlers with routing service."""
        handlers = {
            "search_code": self._search_code,
            "search_similar": self._search_similar,
            "search_context": self._search_context,
            "get_project_status": self._get_project_status,
            "index_project": self._index_project,
            "analyze_project": self._analyze_project,
            "analyze_file": self._analyze_file,
            "find_smells": self._find_smells,
            "get_complexity_hotspots": self._get_complexity_hotspots,
            "check_circular_dependencies": self._check_circular_dependencies,
            "find_symbol": self._find_symbol,
            "get_relationships": self._get_relationships,
            "interpret_analysis": self._interpret_analysis,
            "find_duplicates": self._find_duplicates,
            "silence_health_issue": self._silence_health_issue,
            "propose_logic": self._handle_propose_logic,
            "analyze_impact": self._impact_analysis,
            "read_file": self._read_file,
            "write_file": self._write_file,
            "list_directory": self._list_directory,
            "list_files": self._list_directory,
            "debug_ping": self._handle_debug_ping,
            # Aliases for compatibility
            "mcp_filesystem_list_directory": self._list_directory,
            "mcp_filesystem_read_file": self._read_file,
            "mcp_filesystem_write_file": self._write_file,
        }
        for tool_name, handler in handlers.items():
            self.routing_service.register_handler(tool_name, handler)

    def get_tools(self) -> list:
        """Return list of available MCP tools."""
        from mcp_code_intelligence.core.tool_registry import get_mcp_tools
        return get_mcp_tools(project_root=self.project_root)

    async def _handle_debug_ping(self, args: dict) -> CallToolResult:
        import os
        from mcp_code_intelligence.core import tool_registry
        msg = (
            f"🏓 Pong! \n"
            f"PID: {os.getpid()}\n"
            f"Registry Source: {tool_registry.__file__}\n"
            f"Package Root: {Path(__file__).parent.parent}\n"
            f"Python: {sys.executable}"
        )
        logger.warning(f"🏓 [Ping] Debug info: {msg}")
        return self.protocol_service.build_text_response(msg)

    async def _read_file(self, args: dict) -> CallToolResult:
        """Handle read_file tool call."""
        rel_path = args.get("relative_path")
        if not rel_path:
            return self.protocol_service.build_error_response("relative_path parameter is required")
        
        path = (self.project_root / rel_path).resolve()
        try:
            if not str(path).startswith(str(self.project_root.resolve())):
                return self.protocol_service.build_error_response(f"Access denied: {rel_path} is outside project root")
            
            if not path.exists():
                return self.protocol_service.build_error_response(f"File not found: {rel_path}")
            
            content = path.read_text(encoding="utf-8", errors="replace")
            logger.info(f"📖 [Filesystem] Read file: {rel_path} ({len(content)} chars)")
            return self.protocol_service.build_text_response(content)
        except Exception as e:
            logger.error(f"Read file failed: {e}")
            return self.protocol_service.build_error_response(f"Error reading file: {str(e)}")

    async def _write_file(self, args: dict) -> CallToolResult:
        """Handle write_file tool call."""
        rel_path = args.get("relative_path")
        content = args.get("content", "")
        if not rel_path:
            return self.protocol_service.build_error_response("relative_path parameter is required")
        
        path = (self.project_root / rel_path).resolve()
        try:
            if not str(path).startswith(str(self.project_root.resolve())):
                return self.protocol_service.build_error_response(f"Access denied: {rel_path} is outside project root")
            
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            logger.success(f"💾 [Filesystem] Wrote file: {rel_path}")
            return self.protocol_service.build_text_response(f"Successfully wrote to {rel_path}")
        except Exception as e:
            logger.error(f"Write file failed: {e}")
            return self.protocol_service.build_error_response(f"Error writing file: {str(e)}")

    async def _list_directory(self, args: dict) -> CallToolResult:
        """Handle list_directory and list_files tool calls."""
        rel_path = args.get("relative_path", "")
        pattern = args.get("pattern")
        
        try:
            if pattern:
                logger.info(f"📂 [Filesystem] Listing files with pattern: {pattern}")
                files = list(self.project_root.glob(pattern))
                if not files:
                    return self.protocol_service.build_text_response(f"No files matching pattern: {pattern}")
                
                items = [str(f.relative_to(self.project_root)) for f in sorted(files)]
                return self.protocol_service.build_text_response("\n".join(items))
            
            dir_path = (self.project_root / rel_path).resolve()
            if not str(dir_path).startswith(str(self.project_root.resolve())):
                return self.protocol_service.build_error_response(f"Access denied: {rel_path} is outside project root")
            
            if not dir_path.exists() or not dir_path.is_dir():
                return self.protocol_service.build_error_response(f"Directory not found: {rel_path}")
            
            logger.info(f"📂 [Filesystem] Listing directory: {rel_path or '.'}")
            items = []
            for item in sorted(dir_path.iterdir()):
                prefix = "[DIR] " if item.is_dir() else "[FILE]"
                items.append(f"{prefix} {item.name}")
            
            result = "\n".join(items) if items else "(empty directory)"
            return self.protocol_service.build_text_response(result)
        except Exception as e:
            logger.error(f"List directory failed: {e}")
            return self.protocol_service.build_error_response(f"Error listing directory: {str(e)}")

    async def _impact_analysis(self, args: dict[str, Any]) -> CallToolResult:
        """Handle impact_analysis tool call."""
        symbol_name = args.get("symbol_name", "")
        max_depth = args.get("max_depth", 5)
        if not symbol_name:
            return self.protocol_service.build_error_response("symbol_name parameter is required")
        try:
            logger.info(f"💥 [Impact] Analyzing ripple effect for symbol: '{symbol_name}' (Depth: {max_depth})")
            from mcp_code_intelligence.core.relationships import analyze_impact
            result = analyze_impact(self.project_root, symbol_name, max_depth)
            if "error" in result:
                return self.protocol_service.build_error_response(result["error"])
            response_lines = [f"# Impact Analysis for '{symbol_name}'\n"]
            response_lines.append(f"**Origin:** {result['origin']}")
            response_lines.append(f"**Complexity Score:** {result['complexity_score']}")
            response_lines.append("\n## Immediate Impact (Directly Affected Files):")
            if result["immediate_impact"]:
                for f in result["immediate_impact"]:
                    response_lines.append(f"- {f}")
            else:
                response_lines.append("- None")
            response_lines.append("\n## Deep Impact (Transitive):")
            if result["deep_impact"]:
                for f in result["deep_impact"]:
                    response_lines.append(f"- {f}")
            else:
                response_lines.append("- None")
            return self.protocol_service.build_text_response("\n".join(response_lines))
        except Exception as e:
            logger.error(f"Impact analysis failed: {e}")
            return self.protocol_service.build_error_response(f"Impact analysis failed: {str(e)}")

    def get_tools(self) -> list[Tool]:
        """Get available MCP tools via central registry."""
        try:
            from mcp_code_intelligence.core.tool_registry import get_mcp_tools

            servers_tools: dict = {}
            try:
                from mcp_code_intelligence.servers.filesystem_server import FilesystemServer
                fs = FilesystemServer(self.project_root)
                servers_tools["filesystem"] = [
                    {"name": t.name, "description": t.description, "inputSchema": getattr(t, "inputSchema", {})}
                    for t in fs.advertised_tools()
                ]
            except Exception:
                pass

            try:
                from mcp_code_intelligence.servers.python_lsp_server import get_advertised_tools as get_py_lsp_tools
                py_tools = get_py_lsp_tools(self.project_root)
                servers_tools["python_lsp"] = [
                    {"name": t.name, "description": t.description, "inputSchema": getattr(t, "inputSchema", {})}
                    for t in py_tools
                ]
            except Exception as e:
                logger.warning(f"Failed to load Python LSP tools: {e}")

            if servers_tools:
                tools = get_mcp_tools(self.project_root, servers_tools=servers_tools)
            else:
                tools = get_mcp_tools(self.project_root)

            # --- ALIAS EXPOSURE ---
            # Explicitly add aliases so SDK accepts them
            from mcp.types import Tool
            aliases = [
                ("mcp_filesystem_list_directory", "Alias for list_directory"),
                ("mcp_filesystem_read_file", "Alias for read_file"),
                ("mcp_filesystem_write_file", "Alias for write_file"),
            ]
            for alias_name, alias_desc in aliases:
                # Find original tool schema
                orig_name = alias_name.replace("mcp_filesystem_", "")
                orig_tool = next((t for t in tools if t.name == orig_name), None)
                if orig_tool:
                     tools.append(Tool(
                         name=alias_name, 
                         description=alias_desc, 
                         inputSchema=orig_tool.inputSchema
                     ))
            
            return tools
        except Exception as e:
            logger.error(f"❌ Failed to load tools in handle_list_tools: {e}", exc_info=True)
            return []

    def get_capabilities(self) -> ServerCapabilities:
        """Get server capabilities."""
        return ServerCapabilities(tools={"listChanged": True}, logging={})

    # ========== Proxy Properties to SessionService ==========

    @property
    def _initialized(self) -> bool:
        """Check if session is initialized."""
        return self.session_service._initialized

    @property
    def search_engine(self):
        """Get search engine from session service."""
        return self.session_service.search_engine

    async def initialize(self) -> None:
        """Initialize server and session."""
        await self.session_service.initialize()

    async def call_tool(self, request: CallToolRequest) -> CallToolResult:
        """Handle tool calls via routing service."""
        name = request.params.name
        
        # --- ROBUST DISPATCHER ---
        # Normalize tool names to handle various client prefixes
        def normalize_name(n: str) -> str:
            if n in self.routing_service.handler_map:
                return n

            # Generic suffix matching: Try to match by stripping prefix parts
            # e.g. mcp_filesystem_list_directory -> list_directory
            parts = n.split("_")
            # Try all possible suffixes (from longest to shortest)
            # We skip i=0 because that's the full name checked above
            for i in range(1, len(parts)):
                candidate = "_".join(parts[i:])
                if candidate in self.routing_service.handler_map:
                    return candidate

        normalized_name = normalize_name(name)
        if normalized_name != name:
            logger.warning(f"🔀 [Routing] Normalized '{name}' -> '{normalized_name}'")
            name = normalized_name
            request.params.name = name
        
        args = request.params.arguments or {}
        logger.info(f"🚀 [Tool Call] {name} (Args: {json.dumps(args)[:100]}{'...' if len(json.dumps(args)) > 100 else ''})")

        # Initialize session if needed
        if request.params.name != "interpret_analysis" and not self.session_service.is_initialized:
            await self.session_service.initialize()

        try:
            # Route to appropriate handler
            result = await self.routing_service.route_tool_call(request)
            
            if result.isError:
                 logger.error(f"🔥 [Tool Error] {name} failed with error content.")
            else:
                 logger.success(f"✅ [Tool Success] {name} completed.")

            # Inject Guardian health notice if enabled
            if self.session_service._enable_guardian and not result.isError and request.params.name in ("search_code", "search_similar", "get_project_status"):
                try:
                    health_notice = await self.session_service.guardian.get_health_notice()
                    if health_notice:
                        notice_content = TextContent(type="text", text=health_notice + "\n\n---\n")
                        result.content.insert(0, notice_content)
                except Exception as g_err:
                    logger.debug(f"Guardian check failed: {g_err}")

            return result

        except Exception as e:
            logger.error(f"Tool call exception: {e}")
            return self.protocol_service.build_error_response(f"Tool execution failed: {str(e)}")

    async def cleanup(self) -> None:
        """Cleanup resources through session service."""
        await self.session_service.cleanup()

    # ========== Tool Handlers ==========

    async def _search_code(self, args: dict[str, Any]) -> CallToolResult:
        """Handle search_code tool call."""
        query = args.get("query", "")
        limit = args.get("limit", 10)
        similarity_threshold = args.get("similarity_threshold", 0.3)

        if not query:
            return self.protocol_service.build_error_response("Query parameter is required")

        if not self.session_service.search_engine:
            return self.protocol_service.build_error_response("Search engine not initialized")

        filters = self.protocol_service.build_search_filters(args)

        try:
            results = await self.session_service.search_engine.search(
                query=query,
                limit=limit,
                similarity_threshold=similarity_threshold,
                filters=filters,
            )

            logger.info(f"🔍 [Search] '{query}' query produced {len(results)} results")

            if not results:
                return self.protocol_service.build_text_response(f"No results found for query: '{query}'")

            response_lines = [f"Found {len(results)} results for query: '{query}'\n"]
            for i, result in enumerate(results, 1):
                response_lines.extend(self.protocol_service.format_search_result(result, i))

            return self.protocol_service.build_text_response("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return self.protocol_service.build_error_response(f"Search failed: {str(e)}")

    async def _search_similar(self, args: dict[str, Any]) -> CallToolResult:
        """Handle search_similar tool call."""
        file_path_str = args.get("file_path", "")
        if not file_path_str:
            return self.protocol_service.build_error_response("file_path parameter is required")

        file_path = self.protocol_service.resolve_file_path(file_path_str, self.project_root)
        if not file_path:
            return self.protocol_service.build_error_response(f"File not found: {file_path_str}")

        try:
            results = await self.session_service.search_engine.search_similar(
                file_path=file_path,
                function_name=args.get("function_name"),
                limit=args.get("limit", 10),
                similarity_threshold=args.get("similarity_threshold", 0.3),
            )

            logger.info(f"👯 [Similar] Found {len(results)} snippets similar to {file_path.name}")

            if not results:
                return self.protocol_service.build_text_response(f"No similar code found for {file_path_str}")

            response_lines = [f"Found {len(results)} similar code snippets for {file_path_str}\n"]
            for i, result in enumerate(results, 1):
                response_lines.extend(self.protocol_service.format_search_result(result, i))

            return self.protocol_service.build_text_response("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Similar search failed: {e}")
            return self.protocol_service.build_error_response(f"Similar search failed: {str(e)}")

    async def _search_context(self, args: dict[str, Any]) -> CallToolResult:
        """Handle search_context tool call."""
        description = args.get("description", "")
        if not description:
            return self.protocol_service.build_error_response("description parameter is required")

        try:
            results = await self.session_service.search_engine.search_by_context(
                context_description=description,
                focus_areas=args.get("focus_areas"),
                limit=args.get("limit", 10)
            )

            if not results:
                return self.protocol_service.build_text_response(f"No contextually relevant code found for: {description}")

            response_lines = [f"Found {len(results)} contextually relevant code snippets for: {description}\n"]
            for i, result in enumerate(results, 1):
                response_lines.extend(self.protocol_service.format_search_result(result, i))

            return self.protocol_service.build_text_response("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Context search failed: {e}")
            return self.protocol_service.build_error_response(f"Context search failed: {str(e)}")

    async def _get_project_status(self, args: dict[str, Any]) -> CallToolResult:
        """Handle get_project_status tool call."""
        try:
            config = self.project_manager.load_config()

            if self.session_service.search_engine:
                stats = await self.session_service.database.get_stats()
                logger.info(f"📊 [Status] Project is ready. Index contains {stats.total_files} files.")
                status_info = {
                    "project_root": str(config.project_root),
                    "index_path": str(config.index_path),
                    "file_extensions": config.file_extensions,
                    "embedding_model": config.embedding_model,
                    "languages": config.languages,
                    "total_chunks": stats.total_chunks,
                    "total_files": stats.total_files,
                    "index_size": f"{stats.index_size_mb:.2f} MB" if hasattr(stats, "index_size_mb") else "Unknown",
                }
            else:
                logger.info(f"📊 [Status] Project is not yet indexed.")
                status_info = {
                    "project_root": str(config.project_root),
                    "index_path": str(config.index_path),
                    "file_extensions": config.file_extensions,
                    "embedding_model": config.embedding_model,
                    "languages": config.languages,
                    "status": "Not indexed",
                }

            response_text = "# Project Status\n\n"
            response_text += f"**Project Root:** {status_info['project_root']}\n"
            response_text += f"**Index Path:** {status_info['index_path']}\n"
            response_text += f"**File Extensions:** {', '.join(status_info['file_extensions'])}\n"
            response_text += f"**Embedding Model:** {status_info['embedding_model']}\n"
            response_text += f"**Languages:** {', '.join(status_info['languages'])}\n"

            if "total_chunks" in status_info:
                response_text += f"**Total Chunks:** {status_info['total_chunks']}\n"
                response_text += f"**Total Files:** {status_info['total_files']}\n"
                response_text += f"**Index Size:** {status_info['index_size']}\n"
            else:
                response_text += f"**Status:** {status_info['status']}\n"

            return self.protocol_service.build_text_response(response_text)

        except ProjectNotFoundError:
            return self.protocol_service.build_error_response(f"Project not initialized at {self.project_root}")
        except Exception as e:
            logger.error(f"Project status failed: {e}")
            return self.protocol_service.build_error_response(f"Project status failed: {str(e)}")

    async def _index_project(self, args: dict[str, Any]) -> CallToolResult:
        """Handle index_project tool call."""
        try:
            from mcp_code_intelligence.cli.commands.index_runner import run_indexing
            
            logger.info("🏗️  [Indexing] Starting background project indexing...")

            await run_indexing(
                project_root=self.project_root,
                force_reindex=args.get("force", False),
                extensions=args.get("file_extensions"),
                show_progress=False,
                workers=args.get("workers"),
                throttle=args.get("throttle"),
                max_size=args.get("max_size"),
                important_only=args.get("important_only"),
            )

            await self.cleanup()
            await self.session_service.initialize()
            
            logger.success("🏗️  [Indexing] Project indexing completed!")

            return self.protocol_service.build_text_response("Project indexing completed successfully!")

        except Exception as e:
            logger.error(f"Indexing failed: {e}")
            return self.protocol_service.build_error_response(f"Indexing failed: {str(e)}")

    async def _find_symbol(self, args: dict[str, Any]) -> CallToolResult:
        """Handle find_symbol tool call."""
        name = args.get("name", "")
        if not name:
            return self.protocol_service.build_error_response("Name parameter is required")

        if not self.session_service.search_engine:
            return self.protocol_service.build_error_response("Search engine not initialized")

        try:
            logger.info(f"🎯 [Symbol] Finding definition for '{name}' (Type: {args.get('symbol_type', 'Any')})")
            results = await self.session_service.search_engine.find_symbol(name, args.get("symbol_type"))

            if not results:
                return self.protocol_service.build_text_response(f"Symbol '{name}' not found.")

            response_lines = [f"Found {len(results)} definitions for '{name}':\n"]
            for i, result in enumerate(results, 1):
                response_lines.extend([
                    f"## Definition {i}",
                    f"File: {result.file_path}",
                    f"Lines: {result.start_line}-{result.end_line}",
                    f"Type: {result.chunk_type}",
                ])
                if result.class_name:
                    response_lines.append(f"Class: {result.class_name}")
                response_lines.extend(["\n```\n" + result.content + "\n```\n"])

            return self.protocol_service.build_text_response("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Find symbol failed: {e}")
            return self.protocol_service.build_error_response(f"Find symbol failed: {str(e)}")

    async def _get_relationships(self, args: dict[str, Any]) -> CallToolResult:
        """Handle get_relationships tool call."""
        name = args.get("name", "")
        if not name:
            return self.protocol_service.build_error_response("Name parameter is required")

        if not self.session_service.search_engine:
            return self.protocol_service.build_error_response("Search engine not initialized")

        try:
            logger.info(f"🔗 [Relationships] Tracing connections for symbol: '{name}'")
            data = await self.session_service.search_engine.get_symbol_relationships(name)

            if "error" in data:
                return self.protocol_service.build_text_response(data["error"])

            response_lines = [f"# Relationships for '{name}'\n"]

            def_info = data["definition"]
            response_lines.extend([
                "## Definition",
                f"- **File:** {def_info['file']}",
                f"- **Lines:** {def_info['lines']}",
                f"- **Type:** {def_info['type']}\n",
                "## Callers (Who calls this?)",
            ])

            if not data["callers"]:
                response_lines.append("- No external callers found.")
            else:
                for caller in data["callers"]:
                    response_lines.append(f"- `{caller['name']}` ({caller['file']})")

            response_lines.extend([
                "",
                "## Callees (What does this call?)",
            ])

            if not data["callees"]:
                response_lines.append("- No internal calls found.")
            else:
                for callee in data["callees"]:
                    response_lines.append(f"- `{callee['name']}` ({callee['file']})")

            response_lines.extend([
                "",
                "## Semantic Siblings (Conceptually similar)",
            ])

            if not data["semantic_siblings"]:
                response_lines.append("- No similar patterns found.")
            else:
                for sibling in data["semantic_siblings"]:
                    response_lines.append(f"- `{sibling['name']}` ({sibling['file']}) [Score: {sibling['similarity']}]")

            return self.protocol_service.build_text_response("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Get relationships failed: {e}")
            return self.protocol_service.build_error_response(f"Get relationships failed: {str(e)}")

    async def _analyze_project(self, args: dict[str, Any]) -> CallToolResult:
        """Handle analyze_project tool call."""
        threshold_preset = args.get("threshold_preset", "standard")
        output_format = args.get("output_format", "summary")

        try:
            from mcp_code_intelligence.cli.commands.analyze import _analyze_file, _find_analyzable_files
            from mcp_code_intelligence.analysis import (
                CognitiveComplexityCollector,
                CyclomaticComplexityCollector,
                MethodCountCollector,
                NestingDepthCollector,
                ParameterCountCollector,
            )

            parser_registry = ParserRegistry()
            files_to_analyze = _find_analyzable_files(
                self.project_root, None, None, parser_registry, None
            )

            if not files_to_analyze:
                return self.protocol_service.build_error_response("No analyzable files found in project")

            collectors = [
                CognitiveComplexityCollector(),
                CyclomaticComplexityCollector(),
                NestingDepthCollector(),
                ParameterCountCollector(),
                MethodCountCollector(),
            ]

            project_metrics = ProjectMetrics(project_root=str(self.project_root))

            logger.info(f"🧪 [Analysis] Analyzing {len(files_to_analyze)} files in project...")

            for file_path in files_to_analyze:
                try:
                    file_metrics = await _analyze_file(file_path, parser_registry, collectors)
                    if file_metrics and file_metrics.chunks:
                        project_metrics.files[str(file_path)] = file_metrics
                except Exception:
                    continue

            project_metrics.compute_aggregates()

            smell_detector = SmellDetector()
            all_smells = []
            for file_path, file_metrics in project_metrics.files.items():
                file_smells = smell_detector.detect_all(file_metrics, file_path)
                all_smells.extend(file_smells)

            if output_format == "detailed":
                output = project_metrics.to_summary()
                output["smells"] = {
                    "total": len(all_smells),
                    "by_severity": {
                        "error": sum(1 for s in all_smells if s.severity == SmellSeverity.ERROR),
                        "warning": sum(1 for s in all_smells if s.severity == SmellSeverity.WARNING),
                        "info": sum(1 for s in all_smells if s.severity == SmellSeverity.INFO),
                    },
                }
                response_text = json.dumps(output, indent=2)
            else:
                summary = project_metrics.to_summary()
                response_lines = [
                    "# Project Analysis Summary\n",
                    f"**Project Root:** {summary['project_root']}",
                    f"**Total Files:** {summary['total_files']}",
                    f"**Total Functions:** {summary['total_functions']}",
                    f"**Total Classes:** {summary['total_classes']}",
                    f"**Average File Complexity:** {summary['avg_file_complexity']}\n",
                    "## Complexity Distribution",
                ]

                dist = summary["complexity_distribution"]
                for grade in ["A", "B", "C", "D", "F"]:
                    response_lines.append(f"- Grade {grade}: {dist[grade]} chunks")

                response_lines.extend([
                    "\n## Health Metrics",
                    f"- Average Health Score: {summary['health_metrics']['avg_health_score']:.2f}",
                    f"- Files Needing Attention: {summary['health_metrics']['files_needing_attention']}",
                    "\n## Code Smells",
                    f"- Total: {len(all_smells)}",
                    f"- Errors: {sum(1 for s in all_smells if s.severity == SmellSeverity.ERROR)}",
                    f"- Warnings: {sum(1 for s in all_smells if s.severity == SmellSeverity.WARNING)}",
                    f"- Info: {sum(1 for s in all_smells if s.severity == SmellSeverity.INFO)}",
                ])

                response_text = "\n".join(response_lines)

            return self.protocol_service.build_text_response(response_text)

        except Exception as e:
            logger.error(f"Project analysis failed: {e}")
            return self.protocol_service.build_error_response(f"Project analysis failed: {str(e)}")

    async def _analyze_file(self, args: dict[str, Any]) -> CallToolResult:
        """Handle analyze_file tool call."""
        file_path_str = args.get("file_path", "")
        if not file_path_str:
            return self.protocol_service.build_error_response("file_path parameter is required")

        file_path = self.protocol_service.resolve_file_path(file_path_str, self.project_root)
        if not file_path:
            return self.protocol_service.build_error_response(f"File not found: {file_path_str}")

        try:
            from mcp_code_intelligence.cli.commands.analyze import _analyze_file
            from mcp_code_intelligence.analysis import (
                CognitiveComplexityCollector,
                CyclomaticComplexityCollector,
                MethodCountCollector,
                NestingDepthCollector,
                ParameterCountCollector,
            )

            parser_registry = ParserRegistry()
            collectors = [
                CognitiveComplexityCollector(),
                CyclomaticComplexityCollector(),
                NestingDepthCollector(),
                ParameterCountCollector(),
                MethodCountCollector(),
            ]

            file_metrics = await _analyze_file(file_path, parser_registry, collectors)

            if not file_metrics:
                return self.protocol_service.build_error_response(f"Unable to analyze file: {file_path_str}")

            smell_detector = SmellDetector()
            smells = smell_detector.detect_all(file_metrics, str(file_path))

            response_lines = [
                f"# File Analysis: {file_path.name}\n",
                f"**Path:** {file_path}",
                f"**Total Lines:** {file_metrics.total_lines}",
                f"**Code Lines:** {file_metrics.code_lines}",
                f"**Comment Lines:** {file_metrics.comment_lines}",
                f"**Functions:** {file_metrics.function_count}",
                f"**Classes:** {file_metrics.class_count}",
                f"**Methods:** {file_metrics.method_count}\n",
                "## Complexity Metrics",
                f"- Total Complexity: {file_metrics.total_complexity}",
                f"- Average Complexity: {file_metrics.avg_complexity:.2f}",
                f"- Max Complexity: {file_metrics.max_complexity}",
                f"- Health Score: {file_metrics.health_score:.2f}\n",
            ]

            if smells:
                response_lines.append(f"## Code Smells ({len(smells)})\n")
                for smell in smells[:10]:
                    response_lines.append(f"- [{smell.severity.value.upper()}] {smell.name}: {smell.description}")
                if len(smells) > 10:
                    response_lines.append(f"\n... and {len(smells) - 10} more")
            else:
                response_lines.append("## Code Smells\n- None detected")

            return self.protocol_service.build_text_response("\n".join(response_lines))

        except Exception as e:
            logger.error(f"File analysis failed: {e}")
            return self.protocol_service.build_error_response(f"File analysis failed: {str(e)}")

    async def _find_smells(self, args: dict[str, Any]) -> CallToolResult:
        """Handle find_smells tool call."""
        from mcp_code_intelligence.cli.commands.analyze import _analyze_file, _find_analyzable_files
        from mcp_code_intelligence.analysis import (
            CognitiveComplexityCollector,
            CyclomaticComplexityCollector,
            MethodCountCollector,
            NestingDepthCollector,
            ParameterCountCollector,
        )

        try:
            parser_registry = ParserRegistry()
            files_to_analyze = _find_analyzable_files(
                self.project_root, None, None, parser_registry, None
            )

            collectors = [
                CognitiveComplexityCollector(),
                CyclomaticComplexityCollector(),
                NestingDepthCollector(),
                ParameterCountCollector(),
                MethodCountCollector(),
            ]

            project_metrics = ProjectMetrics(project_root=str(self.project_root))

            for file_path in files_to_analyze:
                try:
                    file_metrics = await _analyze_file(file_path, parser_registry, collectors)
                    if file_metrics and file_metrics.chunks:
                        project_metrics.files[str(file_path)] = file_metrics
                except Exception:
                    continue

            smell_detector = SmellDetector()
            all_smells = []
            for file_path, file_metrics in project_metrics.files.items():
                file_smells = smell_detector.detect_all(file_metrics, file_path)
                all_smells.extend(file_smells)

            smell_type_filter = args.get("smell_type")
            severity_filter = args.get("severity")

            filtered_smells = all_smells

            if smell_type_filter:
                filtered_smells = [s for s in filtered_smells if s.name == smell_type_filter]

            if severity_filter:
                severity_enum = SmellSeverity(severity_filter)
                filtered_smells = [s for s in filtered_smells if s.severity == severity_enum]

            if not filtered_smells:
                return self.protocol_service.build_text_response("No code smells found")

            response_lines = [f"# Code Smells Found: {len(filtered_smells)}\n"]

            by_severity = {
                "error": [s for s in filtered_smells if s.severity == SmellSeverity.ERROR],
                "warning": [s for s in filtered_smells if s.severity == SmellSeverity.WARNING],
                "info": [s for s in filtered_smells if s.severity == SmellSeverity.INFO],
            }

            for severity_level in ["error", "warning", "info"]:
                smells = by_severity[severity_level]
                if smells:
                    response_lines.append(f"## {severity_level.upper()} ({len(smells)})\n")
                    for smell in smells[:20]:
                        response_lines.append(f"- **{smell.name}** at `{smell.location}`")
                        response_lines.append(f"  {smell.description}")
                        if smell.suggestion:
                            response_lines.append(f"  *Suggestion: {smell.suggestion}*")
                        response_lines.append("")

            return self.protocol_service.build_text_response("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Smell detection failed: {e}")
            return self.protocol_service.build_error_response(f"Smell detection failed: {str(e)}")

    async def _get_complexity_hotspots(self, args: dict[str, Any]) -> CallToolResult:
        """Handle get_complexity_hotspots tool call."""
        
        try:
            from mcp_code_intelligence.cli.commands.analyze import _analyze_file, _find_analyzable_files
            from mcp_code_intelligence.analysis import (
                CognitiveComplexityCollector,
                CyclomaticComplexityCollector,
                MethodCountCollector,
                NestingDepthCollector,
                ParameterCountCollector,
            )

            logger.info(f"[Hotspots] Starting analysis for project: {self.project_root}")
            parser_registry = ParserRegistry()
            files_to_analyze = _find_analyzable_files(
                self.project_root, None, None, parser_registry, None
            )
            
            logger.info(f"[Hotspots] Found {len(files_to_analyze)} files to analyze")
            
            if not files_to_analyze:
                return self.protocol_service.build_text_response(
                    "⚠️ No analyzable files found in project. "
                    "Make sure the project contains Python files and is properly initialized."
                )

            collectors = [
                CognitiveComplexityCollector(),
                CyclomaticComplexityCollector(),
                NestingDepthCollector(),
                ParameterCountCollector(),
                MethodCountCollector(),
            ]

            project_metrics = ProjectMetrics(project_root=str(self.project_root))
            analyzed_count = 0

            for file_path in files_to_analyze:
                try:
                    file_metrics = await _analyze_file(file_path, parser_registry, collectors)
                    if file_metrics and file_metrics.chunks:
                        project_metrics.files[str(file_path)] = file_metrics
                        analyzed_count += 1
                except Exception as e:
                    logger.debug(f"[Hotspots] Failed to analyze {file_path}: {e}")
                    continue

            logger.info(f"[Hotspots] Successfully analyzed {analyzed_count}/{len(files_to_analyze)} files")

            # CRITICAL FIX: Must compute aggregates before getting hotspots
            project_metrics.compute_aggregates()

            hotspots = project_metrics.get_hotspots(limit=args.get("limit", 10))
            
            logger.info(f"[Hotspots] Found {len(hotspots)} hotspots")

            if not hotspots:
                return self.protocol_service.build_text_response(
                    f"✅ No significant complexity hotspots found!\n\n"
                    f"Analyzed {analyzed_count} files. Your codebase appears to be well-maintained. "
                    f"All files have acceptable complexity levels."
                )

            response_lines = [f"# Top {len(hotspots)} Complexity Hotspots\n"]

            for i, file_metrics in enumerate(hotspots, 1):
                response_lines.extend([
                    f"## {i}. {Path(file_metrics.file_path).name}",
                    f"**Path:** `{file_metrics.file_path}`",
                    f"**Average Complexity:** {file_metrics.avg_complexity:.2f}",
                    f"**Max Complexity:** {file_metrics.max_complexity}",
                    f"**Total Complexity:** {file_metrics.total_complexity}",
                    f"**Functions:** {file_metrics.function_count}",
                    f"**Health Score:** {file_metrics.health_score:.2f}\n",
                ])

            return self.protocol_service.build_text_response("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Hotspot detection failed: {e}", exc_info=True)
            return self.protocol_service.build_error_response(f"Hotspot detection failed: {str(e)}")

    async def _check_circular_dependencies(self, args: dict[str, Any]) -> CallToolResult:
        """Handle check_circular_dependencies tool call."""
        from mcp_code_intelligence.cli.commands.analyze import _find_analyzable_files
        from mcp_code_intelligence.analysis.collectors.coupling import build_import_graph

        try:
            parser_registry = ParserRegistry()
            files_to_analyze = _find_analyzable_files(
                self.project_root, None, None, parser_registry, None
            )

            if not files_to_analyze:
                return self.protocol_service.build_error_response("No analyzable files found in project")

            import_graph = build_import_graph(self.project_root, files_to_analyze, language="python")

            forward_graph: dict[str, list[str]] = {}

            for file_path in files_to_analyze:
                file_str = str(file_path.relative_to(self.project_root))
                if file_str not in forward_graph:
                    forward_graph[file_str] = []

                for module, importers in import_graph.items():
                    for importer in importers:
                        importer_str = str(
                            Path(importer).relative_to(self.project_root)
                            if Path(importer).is_absolute()
                            else importer
                        )
                        if importer_str == file_str:
                            if module not in forward_graph[file_str]:
                                forward_graph[file_str].append(module)

            def find_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
                """Find all cycles in import graph using DFS."""
                cycles = []
                visited = set()
                rec_stack = set()

                def dfs(node: str, path: list[str]) -> None:
                    visited.add(node)
                    rec_stack.add(node)
                    path.append(node)

                    for neighbor in graph.get(node, []):
                        if neighbor not in visited:
                            dfs(neighbor, path.copy())
                        elif neighbor in rec_stack:
                            try:
                                cycle_start = path.index(neighbor)
                                cycle = path[cycle_start:] + [neighbor]
                                cycle_tuple = tuple(sorted(cycle))
                                if not any(tuple(sorted(c)) == cycle_tuple for c in cycles):
                                    cycles.append(cycle)
                            except ValueError:
                                pass

                    rec_stack.remove(node)

                for node in graph:
                    if node not in visited:
                        dfs(node, [])

                return cycles

            cycles = find_cycles(forward_graph)

            if not cycles:
                return self.protocol_service.build_text_response("No circular dependencies detected")

            response_lines = [f"# Circular Dependencies Found: {len(cycles)}\n"]

            for i, cycle in enumerate(cycles, 1):
                response_lines.append(f"## Cycle {i}")
                response_lines.append("```")
                for j, node in enumerate(cycle):
                    if j < len(cycle) - 1:
                        response_lines.extend([f"{node}", "  ↓"])
                    else:
                        response_lines.append(f"{node} (back to {cycle[0]})")
                response_lines.append("```\n")

            return self.protocol_service.build_text_response("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Circular dependency check failed: {e}")
            return self.protocol_service.build_error_response(f"Circular dependency check failed: {str(e)}")

    async def _interpret_analysis(self, args: dict[str, Any]) -> CallToolResult:
        """Handle interpret_analysis tool call."""
        analysis_json_str = args.get("analysis_json", "")
        if not analysis_json_str:
            return self.protocol_service.build_error_response("analysis_json parameter is required")

        try:
            from mcp_code_intelligence.analysis.interpretation import AnalysisInterpreter, LLMContextExport

            analysis_data = self.protocol_service.parse_json_safely(analysis_json_str)
            if not analysis_data:
                return self.protocol_service.build_error_response("Invalid JSON input")

            export = LLMContextExport(**analysis_data)
            interpreter = AnalysisInterpreter()
            interpretation = interpreter.interpret(
                export,
                focus=args.get("focus", "summary"),
                verbosity=args.get("verbosity", "normal")
            )

            return self.protocol_service.build_text_response(interpretation)

        except Exception as e:
            logger.error(f"Analysis interpretation failed: {e}")
            return self.protocol_service.build_error_response(f"Interpretation failed: {str(e)}")

    async def _find_duplicates(self, args: dict[str, Any]) -> CallToolResult:
        """Handle find_duplicates tool call."""
        try:
            from mcp_code_intelligence.mcp_impl.duplicates_tool import handle_find_duplicates
            return await handle_find_duplicates(self.session_service.search_engine, args)
        except Exception as e:
            logger.error(f"Find duplicates failed: {e}")
            return self.protocol_service.build_error_response(f"Find duplicates failed: {str(e)}")

    async def _silence_health_issue(self, args: dict[str, Any]) -> CallToolResult:
        """Handle silence_health_issue tool call."""
        issue_id = args.get("issue_id")
        try:
            success = await self.session_service.guardian.silence_issue(issue_id)
            if success:
                msg = f"✅ Issue '{issue_id}' has been silenced. It will no longer appear in Guardian notices."
            else:
                msg = f"ℹ️ Issue '{issue_id}' was already silenced or could not be found."
            return self.protocol_service.build_text_response(msg)
        except Exception as e:
            logger.error(f"Silence health issue failed: {e}")
            return self.protocol_service.build_error_response(f"Silence health issue failed: {str(e)}")

    async def _handle_propose_logic(self, args: dict[str, Any]) -> CallToolResult:
        """Handle propose_logic tool call."""
        if not self.session_service._enable_logic_check:
            return self.protocol_service.build_text_response(
                "ℹ️ Logic Check feature is currently disabled in project configuration."
            )

        intent = args.get("intent", "")
        if not intent:
            return self.protocol_service.build_error_response("Intent is required.")

        try:
            analysis = await self.session_service.guardian.check_intent_duplication(intent, args.get("code_draft"))

            if not analysis["duplicate_found"]:
                return self.protocol_service.build_text_response(
                    "✅ No similar logic found. You can proceed with the implementation."
                )

            response_lines = [
                "### 🛑 STOP! LOGIC DUPLICATION DETECTED",
                "\n> [!CAUTION]",
                "> **Highly similar logic already exists in your codebase.**",
                "> Implementing this again would create technical debt. Please use the existing implementation below:\n"
            ]

            for i, match in enumerate(analysis["matches"], 1):
                func = match['function_name'] or "Global/Block"
                response_lines.extend([
                    f"#### 🔍 Match {i} (Confidence: {match['score']:.2f})",
                    f"- **File:** `{match['file_path']}`",
                    f"- **Symbol:** `{func}`",
                    f"- **Location:** `{match['location']}`",
                    "\n**Existing Code Snippet:**",
                    f"```python\n{match['content'][:400]}...\n```\n",
                ])

            response_lines.extend([
                "\n---",
                "> [!TIP]",
                "> Instead of writing new code, please **import and reuse** the existing logic.",
            ])

            return self.protocol_service.build_text_response("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Propose logic failed: {e}")
            return self.protocol_service.build_error_response(f"Propose logic failed: {str(e)}")


def create_mcp_server(
    project_root: Path | None = None, enable_file_watching: bool | None = None
) -> Server:
    """Create and configure the MCP server."""
    server = Server("mcp-code-intelligence")
    mcp_server = MCPVectorSearchServer(project_root, enable_file_watching)

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        """List available tools."""
        return mcp_server.get_tools()

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict | None):
        """Handle tool calls."""
        logger.info(f"⚡ [Gateway] Use tool request received: {name}")
        from types import SimpleNamespace

        mock_request = SimpleNamespace()
        mock_request.params = SimpleNamespace()
        mock_request.params.name = name
        mock_request.params.arguments = arguments or {}

        result = await mcp_server.call_tool(mock_request)
        return result.content

    server._mcp_server = mcp_server
    return server


async def run_mcp_server(
    project_root: Path | None = None, enable_file_watching: bool | None = None
) -> None:
    """Run the MCP server using stdio transport."""
    # Force UTF-8 for stdio on Windows
    if sys.platform == "win32":
        import io
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding='utf-8')
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding='utf-8')

    server = create_mcp_server(project_root, enable_file_watching)

    init_options = InitializationOptions(
        server_name="mcp-code-intelligence",
        server_version="0.6.0",
        capabilities=ServerCapabilities(
            tools={"listChanged": True}, 
            logging={},
            resources={}
        ),
    )

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, init_options)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
    except Exception as e:
        logger.error(f"MCP server error: {e}")
        raise
    finally:
        if hasattr(server, "_mcp_server"):
            logger.info("Performing server cleanup...")
            await server._mcp_server.cleanup()


if __name__ == "__main__":
    project_root = Path(sys.argv[1]) if len(sys.argv) > 1 else None

    enable_file_watching = None
    if "--no-watch" in sys.argv:
        enable_file_watching = False
        sys.argv.remove("--no-watch")
    elif "--watch" in sys.argv:
        enable_file_watching = True
        sys.argv.remove("--watch")

    asyncio.run(run_mcp_server(project_root, enable_file_watching))
