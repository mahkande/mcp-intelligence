"""MCP server implementation for MCP Code Intelligence."""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger
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
from mcp_code_intelligence.core.database import ChromaVectorDatabase
from mcp_code_intelligence.core.embeddings import create_embedding_function
from mcp_code_intelligence.core.exceptions import ProjectNotFoundError
from mcp_code_intelligence.core.indexer import SemanticIndexer
from mcp_code_intelligence.core.project import ProjectManager
from mcp_code_intelligence.core.search import SemanticSearchEngine
from mcp_code_intelligence.core.watcher import FileWatcher
from mcp_code_intelligence.core.llm_client import LLMClient
from mcp_code_intelligence.core.config_utils import (
    get_openai_api_key,
    get_openrouter_api_key,
    get_preferred_llm_provider,
)
from mcp_code_intelligence.parsers.registry import ParserRegistry
from mcp_code_intelligence.core.lsp_proxy import get_manager, stop_proxies
from mcp_code_intelligence.core import formatters


class MCPVectorSearchServer:
    """MCP server for vector search functionality."""

    def __init__(
        self,
        project_root: Path | None = None,
        enable_file_watching: bool | None = None,
    ):
        """Initialize the MCP server.

        Args:
            project_root: Project root directory. If None, will auto-detect from:
                         1. PROJECT_ROOT or MCP_PROJECT_ROOT environment variable
                         2. Current working directory
            enable_file_watching: Enable file watching for automatic reindexing.
                                  If None, checks MCP_ENABLE_FILE_WATCHING env var (default: True).
        """
        # Auto-detect project root from environment or current directory
        if project_root is None:
            # Priority 1: MCP_PROJECT_ROOT (new standard)
            # Priority 2: PROJECT_ROOT (legacy)
            # Priority 3: Current working directory
            env_project_root = os.getenv("MCP_PROJECT_ROOT") or os.getenv(
                "PROJECT_ROOT"
            )
            if env_project_root:
                project_root = Path(env_project_root).resolve()
                logger.info(f"Using project root from environment: {project_root}")
            else:
                project_root = Path.cwd()
                logger.info(f"Using current directory as project root: {project_root}")

        self.project_root = project_root
        self.project_manager = ProjectManager(self.project_root)

        # Setup activity logging
        self._setup_logging()

        self.search_engine: SemanticSearchEngine | None = None
        self.file_watcher: FileWatcher | None = None
        self.indexer: SemanticIndexer | None = None
        self.database: ChromaVectorDatabase | None = None
        self.llm_client: LLMClient | None = None
        self._initialized = False

        # Determine if file watching should be enabled
        if enable_file_watching is None:
            # Check environment variable, default to True
            env_value = os.getenv("MCP_ENABLE_FILE_WATCHING", "true").lower()
            self.enable_file_watching = env_value in ("true", "1", "yes", "on")
        else:
            self.enable_file_watching = enable_file_watching

    def _setup_logging(self) -> None:
        """Setup logging to file for background activity monitoring."""
        try:
            log_dir = self.project_root / ".mcp-code-intelligence" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "activity.log"

            # Add file logger (keep last 5MB of logs, rotation)
            logger.add(
                log_file,
                rotation="5 MB",
                retention="1 week",
                level="INFO",
                format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}"
            )
            logger.info("--- MCP Server Background Logging Started ---")
            logger.info(f"Project Root: {self.project_root}")
        except Exception as e:
            # Fallback to stdout if file logging fails (shouldn't happen)
            print(f"Warning: Could not setup file logging: {e}")

    async def initialize(self) -> None:
        """Initialize the search engine and database."""
        if self._initialized:
            return

        try:
            # Load project configuration
            config = self.project_manager.load_config()

            # Setup embedding function
            embedding_function, _ = create_embedding_function(
                model_name=config.embedding_model
            )

            # Setup database
            self.database = ChromaVectorDatabase(
                persist_directory=config.index_path,
                embedding_function=embedding_function,
            )

            # Initialize database
            await self.database.__aenter__()

            # Check if index is empty and auto-index if needed
            try:
                collection = self.database.get_collection()
                chunk_count = collection.count()

                if chunk_count == 0:
                    logger.info("Index is empty, starting automatic indexing...")
                    # Import indexing functionality
                    from mcp_code_intelligence.cli.commands.index import run_indexing

                    # Run indexing with conservative settings to prevent system freezes
                    await run_indexing(
                        project_root=self.project_root,
                        force_reindex=False,
                        show_progress=False,  # Disable progress for background indexing
                        workers=None,  # Auto-detect
                        throttle=0.5,  # Conservative throttling
                        max_size=10240,  # 10MB max
                        important_only=False,  # Index all files
                    )
                    logger.info(f"Automatic indexing completed: {collection.count()} chunks indexed")
                else:
                    logger.info(f"Index already contains {chunk_count} chunks")
            except Exception as e:
                logger.warning(f"Could not check/create index: {e}")
                logger.info("You can manually run 'mcp-code-intelligence index' to create the index")

            # Setup search engine
            self.search_engine = SemanticSearchEngine(
                database=self.database,
                project_root=self.project_root,
                reranker_model_name=config.reranker_model,
            )

            # Optionally create an LLM client and attach the search engine so server-side
            # components can use context injection when making LLM calls. Only create
            # the client if API keys are available in project config or environment.
            try:
                config_dir = self.project_root / ".mcp-code-intelligence"
                openai_key = get_openai_api_key(config_dir)
                openrouter_key = get_openrouter_api_key(config_dir)
                preferred = get_preferred_llm_provider(config_dir)

                if openai_key or openrouter_key:
                    self.llm_client = LLMClient(
                        openai_api_key=openai_key,
                        openrouter_api_key=openrouter_key,
                        provider=preferred if preferred in ("openai", "openrouter") else None,
                    )
                    # Attach search engine for context injection
                    try:
                        self.llm_client.search_engine = self.search_engine
                    except Exception:
                        pass
                    logger.info("LLM client initialized and attached to search engine for context injection")
                else:
                    logger.debug("No LLM API keys found; skipping LLM client initialization in MCP server")
            except Exception as e:
                logger.warning(f"Failed to initialize LLM client in server: {e}")

            # Initialize Guardian Manager for project health monitoring
            from mcp_code_intelligence.analysis.guardian import GuardianManager
            self.guardian = GuardianManager(self.database, self.project_root)
            self._enable_guardian = config.enable_guardian
            self._enable_logic_check = config.enable_logic_check

            # Setup indexer for file watching
            if self.enable_file_watching:
                self.indexer = SemanticIndexer(
                    database=self.database,
                    project_root=self.project_root,
                    config=config,
                )

                # Setup file watcher
                self.file_watcher = FileWatcher(
                    project_root=self.project_root,
                    config=config,
                    indexer=self.indexer,
                    database=self.database,
                )

                # Start file watching
                await self.file_watcher.start()
                logger.info("File watching enabled for automatic reindexing")
            else:
                logger.info("File watching disabled")

            self._initialized = True
            logger.info(f"MCP server initialized for project: {self.project_root}")

        except ProjectNotFoundError:
            logger.error(f"Project not initialized at {self.project_root}")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize MCP server: {e}")
            raise

    async def cleanup(self) -> None:
        """Cleanup resources."""
        # Stop file watcher if running
        if self.file_watcher and self.file_watcher.is_running:
            logger.info("Stopping file watcher...")
            await self.file_watcher.stop()
            self.file_watcher = None

        # Cleanup database connection
        if self.database and hasattr(self.database, "__aexit__"):
            await self.database.__aexit__(None, None, None)
            self.database = None

        # Clear references
        self.search_engine = None
        self.indexer = None
        self._initialized = False
        # Stop any running LSP proxies for this project
        try:
            await stop_proxies(self.project_root)
        except Exception:
            logger.debug("Failed to stop LSP proxies during cleanup")
        logger.info("MCP server cleanup completed")

    def get_tools(self) -> list[Tool]:
        """Get available MCP tools via central registry."""
        try:
            from mcp_code_intelligence.core.tool_registry import get_mcp_tools

            # Attempt to query local server classes for their advertised tools so
            # the registry uses server-provided metadata as the primary source.
            servers_tools: dict = {}
            try:
                from mcp_code_intelligence.servers.filesystem_server import FilesystemServer
                fs = FilesystemServer(self.project_root)
                servers_tools["filesystem"] = [
                    {"name": t.name, "description": t.description, "inputSchema": getattr(t, "inputSchema", {})}
                    for t in fs.advertised_tools()
                ]
            except Exception:
                # If instantiation fails, skip filesystem server discovery
                pass

            try:
                from mcp_code_intelligence.servers.python_lsp_server import PythonLSPServer
                py = PythonLSPServer(self.project_root)
                servers_tools["python_lsp"] = [
                    {"name": t.name, "description": t.description, "inputSchema": getattr(t, "inputSchema", {})}
                    for t in py.advertised_tools()
                ]
            except Exception:
                # Skip python lsp discovery on error
                pass

            if servers_tools:
                return get_mcp_tools(self.project_root, servers_tools=servers_tools)

            return get_mcp_tools(self.project_root)
        except Exception:
            # Fallback: empty list if registry unavailable
            return []

    def get_capabilities(self) -> ServerCapabilities:
        """Get server capabilities."""
        return ServerCapabilities(tools={"listChanged": True}, logging={})

    async def call_tool(self, request: CallToolRequest) -> CallToolResult:
        """Handle tool calls."""
        # Skip initialization for interpret_analysis (doesn't need project config)
        if request.params.name != "interpret_analysis" and not self._initialized:
            await self.initialize()

        try:
            # Execute the actual tool
            result: CallToolResult
            if request.params.name == "search_code":
                result = await self._search_code(request.params.arguments)
            elif request.params.name == "search_similar":
                result = await self._search_similar(request.params.arguments)
            elif request.params.name == "search_context":
                result = await self._search_context(request.params.arguments)
            elif request.params.name == "get_project_status":
                result = await self._get_project_status(request.params.arguments)
            elif request.params.name == "index_project":
                result = await self._index_project(request.params.arguments)
            elif request.params.name == "analyze_project":
                result = await self._analyze_project(request.params.arguments)
            elif request.params.name == "analyze_file":
                result = await self._analyze_file(request.params.arguments)
            elif request.params.name == "find_smells":
                result = await self._find_smells(request.params.arguments)
            elif request.params.name == "get_complexity_hotspots":
                result = await self._get_complexity_hotspots(request.params.arguments)
            elif request.params.name == "check_circular_dependencies":
                result = await self._check_circular_dependencies(request.params.arguments)
            elif request.params.name == "find_symbol":
                result = await self._find_symbol(request.params.arguments)
            elif request.params.name == "get_relationships":
                result = await self._get_relationships(request.params.arguments)
            elif request.params.name == "interpret_analysis":
                result = await self._interpret_analysis(request.params.arguments)
            elif request.params.name == "find_duplicates":
                from mcp_code_intelligence.mcp_impl.duplicates_tool import handle_find_duplicates
                result = await handle_find_duplicates(self.search_engine, request.params.arguments)
            elif request.params.name == "silence_health_issue":
                issue_id = request.params.arguments.get("issue_id")
                success = await self.guardian.silence_issue(issue_id)
                if success:
                    result = CallToolResult(content=[TextContent(type="text", text=f"✅ Issue '{issue_id}' has been silenced. It will no longer appear in Guardian notices.")])
                else:
                    result = CallToolResult(content=[TextContent(type="text", text=f"ℹ️ Issue '{issue_id}' was already silenced or could not be found.")])
            elif request.params.name == "propose_logic":
                return await self._handle_propose_logic(request.params.arguments)
            else:
                # Check for language LSP proxy tools like "cpp_goto_definition"
                import re

                m = re.match(r"(?P<lang>[a-z0-9_+-]+)_(?P<action>goto_definition|find_references|get_hover_info|get_completions)", request.params.name)
                if m:
                    lang = m.group("lang")
                    action = m.group("action")

                    # Map action to LSP method
                    mapping = {
                        "goto_definition": "textDocument/definition",
                        "find_references": "textDocument/references",
                        "get_hover_info": "textDocument/hover",
                        "get_completions": "textDocument/completion",
                    }

                    method = mapping.get(action)
                    args = request.params.arguments or {}
                    file = args.get("file")
                    line = args.get("line")
                    character = args.get("character")

                    if not file or line is None or character is None:
                        return CallToolResult(content=[TextContent(type="text", text="Invalid arguments for LSP tool: require file,line,character")], isError=True)

                    # Build LSP params
                    params = {
                        "textDocument": {"uri": f"file://{file}"},
                        "position": {"line": line, "character": character},
                    }

                    manager = get_manager(self.project_root)
                    try:
                        if not manager.is_available(lang):
                            return CallToolResult(content=[TextContent(type="text", text=f"LSP server for {lang} is not running. Please run setup or ensure the language server is installed and available.")], isError=True)

                        res = await manager.request(lang, method, params)

                        # Convert LSP response into clean MCP TextContent blocks
                        try:
                            if method == "textDocument/definition":
                                content = formatters.format_definition_response(res)
                            elif method == "textDocument/references":
                                content = formatters.format_references_response(res)
                            elif method == "textDocument/hover":
                                content = formatters.format_hover_response(res)
                            elif method == "textDocument/completion":
                                content = formatters.format_completions_response(res, limit=10)
                            else:
                                # Fallback: stringify
                                content = [TextContent(type="text", text=json.dumps(res))]

                            return CallToolResult(content=content)
                        except Exception as fe:
                            return CallToolResult(content=formatters.format_lsp_error(fe), isError=True)
                    except Exception as e:
                        return CallToolResult(content=[TextContent(type="text", text=f"LSP proxy error: {e}")], isError=True)

                return CallToolResult(
                    content=[
                        TextContent(
                            type="text", text=f"Unknown tool: {request.params.name}"
                        )
                    ],
                    isError=True,
                )

            # --- GUARDIAN SMART NOTIFICATION INJECTION ---
            # If the tool call was successful and it's a primary interaction tool, check for health notices
            if self._enable_guardian and not result.isError and request.params.name in ("search_code", "search_similar", "get_project_status"):
                try:
                    # Guardian check can be throttled or fast-scanned
                    health_notice = await self.guardian.get_health_notice()
                    if health_notice:
                        # Prepend the notice to the response content
                        notice_content = TextContent(type="text", text=health_notice + "\n\n---\n")
                        result.content.insert(0, notice_content)
                except Exception as g_err:
                    logger.debug(f"Guardian check failed: {g_err}")

            return result

        except Exception as e:
            logger.error(f"Tool call failed: {e}")
            return CallToolResult(
                content=[
                    TextContent(type="text", text=f"Tool execution failed: {str(e)}")
                ],
                isError=True,
            )

    async def _search_code(self, args: dict[str, Any]) -> CallToolResult:
        """Handle search_code tool call."""
        query = args.get("query", "")
        limit = args.get("limit", 10)
        similarity_threshold = args.get("similarity_threshold", 0.3)
        file_extensions = args.get("file_extensions")
        language = args.get("language")
        function_name = args.get("function_name")
        class_name = args.get("class_name")
        files = args.get("files")

        if not query:
            return CallToolResult(
                content=[TextContent(type="text", text="Query parameter is required")],
                isError=True,
            )

        # Build filters
        filters = {}
        if file_extensions:
            filters["file_extension"] = {"$in": file_extensions}
        if language:
            filters["language"] = language
        if function_name:
            filters["function_name"] = function_name
        if class_name:
            filters["class_name"] = class_name
        if files:
            # Convert file pattern to filter (simplified)
            filters["file_pattern"] = files

        # Perform search
        results = await self.search_engine.search(
            query=query,
            limit=limit,
            similarity_threshold=similarity_threshold,
            filters=filters,
        )

        # Format results
        if not results:
            response_text = f"No results found for query: '{query}'"
        else:
            response_lines = [f"Found {len(results)} results for query: '{query}'\n"]

            for i, result in enumerate(results, 1):
                response_lines.append(
                    f"## Result {i} (Score: {result.similarity_score:.3f})"
                )
                response_lines.append(f"**File:** {result.file_path}")
                if result.function_name:
                    response_lines.append(f"**Function:** {result.function_name}")
                if result.class_name:
                    response_lines.append(f"**Class:** {result.class_name}")
                response_lines.append(
                    f"**Lines:** {result.start_line}-{result.end_line}"
                )
                response_lines.append("**Code:**")
                response_lines.append("```" + (result.language or ""))
                response_lines.append(result.content)
                response_lines.append("```\n")

            response_text = "\n".join(response_lines)

        return CallToolResult(content=[TextContent(type="text", text=response_text)])

    async def _get_project_status(self, args: dict[str, Any]) -> CallToolResult:
        """Handle get_project_status tool call."""
        try:
            config = self.project_manager.load_config()

            # Get database stats
            if self.search_engine:
                stats = await self.search_engine.database.get_stats()

                status_info = {
                    "project_root": str(config.project_root),
                    "index_path": str(config.index_path),
                    "file_extensions": config.file_extensions,
                    "embedding_model": config.embedding_model,
                    "languages": config.languages,
                    "total_chunks": stats.total_chunks,
                    "total_files": stats.total_files,
                    "index_size": (
                        f"{stats.index_size_mb:.2f} MB"
                        if hasattr(stats, "index_size_mb")
                        else "Unknown"
                    ),
                }
            else:
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
            response_text += (
                f"**File Extensions:** {', '.join(status_info['file_extensions'])}\n"
            )
            response_text += f"**Embedding Model:** {status_info['embedding_model']}\n"
            response_text += f"**Languages:** {', '.join(status_info['languages'])}\n"

            if "total_chunks" in status_info:
                response_text += f"**Total Chunks:** {status_info['total_chunks']}\n"
                response_text += f"**Total Files:** {status_info['total_files']}\n"
                response_text += f"**Index Size:** {status_info['index_size']}\n"
            else:
                response_text += f"**Status:** {status_info['status']}\n"

            return CallToolResult(
                content=[TextContent(type="text", text=response_text)]
            )

        except ProjectNotFoundError:
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"Project not initialized at {self.project_root}. Run 'mcp-code-intelligence init' first.",
                    )
                ],
                isError=True,
            )

    async def _index_project(self, args: dict[str, Any]) -> CallToolResult:
        """Handle index_project tool call."""
        force = args.get("force", False)
        file_extensions = args.get("file_extensions")
        workers = args.get("workers")
        throttle = args.get("throttle")
        max_size = args.get("max_size")
        important_only = args.get("important_only")

        try:
            # Import indexing functionality
            from mcp_code_intelligence.cli.commands.index import run_indexing

            # Run indexing
            await run_indexing(
                project_root=self.project_root,
                force_reindex=force,
                extensions=file_extensions,
                show_progress=False,  # Disable progress for MCP
                workers=workers,
                throttle=throttle,
                max_size=max_size,
                important_only=important_only,
            )

            # Reinitialize search engine after indexing
            await self.cleanup()
            await self.initialize()

            return CallToolResult(
                content=[
                    TextContent(
                        type="text", text="Project indexing completed successfully!"
                    )
                ]
            )

        except Exception as e:
            return CallToolResult(
                content=[TextContent(type="text", text=f"Indexing failed: {str(e)}")],
                isError=True,
            )

    async def _find_symbol(self, args: dict[str, Any]) -> CallToolResult:
        """Handle find_symbol tool call."""
        name = args.get("name", "")
        symbol_type = args.get("symbol_type")

        if not name:
            return CallToolResult(
                content=[TextContent(type="text", text="Name parameter is required")],
                isError=True,
            )

        if not self.search_engine:
            return CallToolResult(
                content=[TextContent(type="text", text="Search engine not initialized")],
                isError=True,
            )

        results = await self.search_engine.find_symbol(name, symbol_type)

        if not results:
            response_text = f"Symbol '{name}' not found."
        else:
            response_lines = [f"Found {len(results)} definitions for '{name}':\n"]
            for i, result in enumerate(results, 1):
                response_lines.append(f"## Definition {i}")
                response_lines.append(f"File: {result.file_path}")
                response_lines.append(f"Lines: {result.start_line}-{result.end_line}")
                response_lines.append(f"Type: {result.chunk_type}")
                if result.class_name:
                    response_lines.append(f"Class: {result.class_name}")
                response_lines.append("\n```\n" + result.content + "\n```\n")

            response_text = "\n".join(response_lines)

        return CallToolResult(content=[TextContent(type="text", text=response_text)])

    async def _get_relationships(self, args: dict[str, Any]) -> CallToolResult:
        """Handle get_relationships tool call."""
        name = args.get("name", "")

        if not name:
            return CallToolResult(
                content=[TextContent(type="text", text="Name parameter is required")],
                isError=True,
            )

        if not self.search_engine:
            return CallToolResult(
                content=[TextContent(type="text", text="Search engine not initialized")],
                isError=True,
            )

        data = await self.search_engine.get_symbol_relationships(name)

        if "error" in data:
            return CallToolResult(content=[TextContent(type="text", text=data["error"])])

        response_lines = [f"# Relationships for '{name}'\n"]

        # Definition
        def_info = data["definition"]
        response_lines.append("## Definition")
        response_lines.append(f"- **File:** {def_info['file']}")
        response_lines.append(f"- **Lines:** {def_info['lines']}")
        response_lines.append(f"- **Type:** {def_info['type']}\n")

        # Callers
        response_lines.append("## Callers (Who calls this?)")
        if not data["callers"]:
            response_lines.append("- No external callers found.")
        else:
            for caller in data["callers"]:
                response_lines.append(f"- `{caller['name']}` ({caller['file']})")
        response_lines.append("")

        # Callees
        response_lines.append("## Callees (What does this call?)")
        if not data["callees"]:
            response_lines.append("- No internal calls found.")
        else:
            for callee in data["callees"]:
                response_lines.append(f"- `{callee['name']}` ({callee['file']})")
        response_lines.append("")

        # Semantic Siblings
        response_lines.append("## Semantic Siblings (Conceptually similar)")
        if not data["semantic_siblings"]:
            response_lines.append("- No similar patterns found.")
        else:
            for sibling in data["semantic_siblings"]:
                response_lines.append(f"- `{sibling['name']}` ({sibling['file']}) [Score: {sibling['similarity']}]")

        response_text = "\n".join(response_lines)
        return CallToolResult(content=[TextContent(type="text", text=response_text)])

    async def _search_similar(self, args: dict[str, Any]) -> CallToolResult:
        """Handle search_similar tool call."""
        file_path = args.get("file_path", "")
        function_name = args.get("function_name")
        limit = args.get("limit", 10)
        similarity_threshold = args.get("similarity_threshold", 0.3)

        if not file_path:
            return CallToolResult(
                content=[
                    TextContent(type="text", text="file_path parameter is required")
                ],
                isError=True,
            )

        try:
            from pathlib import Path

            # Convert to Path object
            file_path_obj = Path(file_path)
            if not file_path_obj.is_absolute():
                file_path_obj = self.project_root / file_path_obj

            if not file_path_obj.exists():
                return CallToolResult(
                    content=[
                        TextContent(type="text", text=f"File not found: {file_path}")
                    ],
                    isError=True,
                )

            # Run similar search
            results = await self.search_engine.search_similar(
                file_path=file_path_obj,
                function_name=function_name,
                limit=limit,
                similarity_threshold=similarity_threshold,
            )

            # Format results
            if not results:
                return CallToolResult(
                    content=[
                        TextContent(
                            type="text", text=f"No similar code found for {file_path}"
                        )
                    ]
                )

            response_lines = [
                f"Found {len(results)} similar code snippets for {file_path}\n"
            ]

            for i, result in enumerate(results, 1):
                response_lines.append(
                    f"## Result {i} (Score: {result.similarity_score:.3f})"
                )
                response_lines.append(f"**File:** {result.file_path}")
                if result.function_name:
                    response_lines.append(f"**Function:** {result.function_name}")
                if result.class_name:
                    response_lines.append(f"**Class:** {result.class_name}")
                response_lines.append(
                    f"**Lines:** {result.start_line}-{result.end_line}"
                )
                response_lines.append("**Code:**")
                response_lines.append("```" + (result.language or ""))
                # Show more of the content for similar search
                content_preview = (
                    result.content[:500]
                    if len(result.content) > 500
                    else result.content
                )
                response_lines.append(
                    content_preview + ("..." if len(result.content) > 500 else "")
                )
                response_lines.append("```\n")

            result_text = "\n".join(response_lines)

            return CallToolResult(content=[TextContent(type="text", text=result_text)])

        except Exception as e:
            return CallToolResult(
                content=[
                    TextContent(type="text", text=f"Similar search failed: {str(e)}")
                ],
                isError=True,
            )

    async def _search_context(self, args: dict[str, Any]) -> CallToolResult:
        """Handle search_context tool call."""
        description = args.get("description", "")
        focus_areas = args.get("focus_areas")
        limit = args.get("limit", 10)

        if not description:
            return CallToolResult(
                content=[
                    TextContent(type="text", text="description parameter is required")
                ],
                isError=True,
            )

        try:
            # Perform context search
            results = await self.search_engine.search_by_context(
                context_description=description, focus_areas=focus_areas, limit=limit
            )

            # Format results
            if not results:
                return CallToolResult(
                    content=[
                        TextContent(
                            type="text",
                            text=f"No contextually relevant code found for: {description}",
                        )
                    ]
                )

            response_lines = [
                f"Found {len(results)} contextually relevant code snippets"
            ]
            if focus_areas:
                response_lines[0] += f" (focus: {', '.join(focus_areas)})"
            response_lines[0] += f" for: {description}\n"

            for i, result in enumerate(results, 1):
                response_lines.append(
                    f"## Result {i} (Score: {result.similarity_score:.3f})"
                )
                response_lines.append(f"**File:** {result.file_path}")
                if result.function_name:
                    response_lines.append(f"**Function:** {result.function_name}")
                if result.class_name:
                    response_lines.append(f"**Class:** {result.class_name}")
                response_lines.append(
                    f"**Lines:** {result.start_line}-{result.end_line}"
                )
                response_lines.append("**Code:**")
                response_lines.append("```" + (result.language or ""))
                # Show more of the content for context search
                content_preview = (
                    result.content[:500]
                    if len(result.content) > 500
                    else result.content
                )
                response_lines.append(
                    content_preview + ("..." if len(result.content) > 500 else "")
                )
                response_lines.append("```\n")

            result_text = "\n".join(response_lines)

            return CallToolResult(content=[TextContent(type="text", text=result_text)])

        except Exception as e:
            return CallToolResult(
                content=[
                    TextContent(type="text", text=f"Context search failed: {str(e)}")
                ],
                isError=True,
            )

    async def _analyze_project(self, args: dict[str, Any]) -> CallToolResult:
        """Handle analyze_project tool call."""
        threshold_preset = args.get("threshold_preset", "standard")
        output_format = args.get("output_format", "summary")

        try:
            # Load threshold configuration based on preset
            threshold_config = self._get_threshold_config(threshold_preset)

            # Run analysis using CLI analyze logic
            from mcp_code_intelligence.cli.commands.analyze import _analyze_file, _find_analyzable_files

            parser_registry = ParserRegistry()
            files_to_analyze = _find_analyzable_files(
                self.project_root, None, None, parser_registry, None
            )

            if not files_to_analyze:
                return CallToolResult(
                    content=[
                        TextContent(
                            type="text",
                            text="No analyzable files found in project",
                        )
                    ],
                    isError=True,
                )

            # Analyze files
            from mcp_code_intelligence.analysis import (
                CognitiveComplexityCollector,
                CyclomaticComplexityCollector,
                MethodCountCollector,
                NestingDepthCollector,
                ParameterCountCollector,
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
                    file_metrics = await _analyze_file(
                        file_path, parser_registry, collectors
                    )
                    if file_metrics and file_metrics.chunks:
                        project_metrics.files[str(file_path)] = file_metrics
                except Exception as e:
                    logger.debug(f"Failed to analyze {file_path}: {e}")
                    continue

            project_metrics.compute_aggregates()

            # Detect code smells
            smell_detector = SmellDetector(thresholds=threshold_config)
            all_smells = []
            for file_path, file_metrics in project_metrics.files.items():
                file_smells = smell_detector.detect_all(file_metrics, file_path)
                all_smells.extend(file_smells)

            # Format response
            if output_format == "detailed":
                # Return full JSON output
                import json

                output = project_metrics.to_summary()
                output["smells"] = {
                    "total": len(all_smells),
                    "by_severity": {
                        "error": sum(
                            1 for s in all_smells if s.severity == SmellSeverity.ERROR
                        ),
                        "warning": sum(
                            1 for s in all_smells if s.severity == SmellSeverity.WARNING
                        ),
                        "info": sum(
                            1 for s in all_smells if s.severity == SmellSeverity.INFO
                        ),
                    },
                }
                response_text = json.dumps(output, indent=2)
            else:
                # Return summary
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

                response_lines.extend(
                    [
                        "\n## Health Metrics",
                        f"- Average Health Score: {summary['health_metrics']['avg_health_score']:.2f}",
                        f"- Files Needing Attention: {summary['health_metrics']['files_needing_attention']}",
                        "\n## Code Smells",
                        f"- Total: {len(all_smells)}",
                        f"- Errors: {sum(1 for s in all_smells if s.severity == SmellSeverity.ERROR)}",
                        f"- Warnings: {sum(1 for s in all_smells if s.severity == SmellSeverity.WARNING)}",
                        f"- Info: {sum(1 for s in all_smells if s.severity == SmellSeverity.INFO)}",
                    ]
                )

                response_text = "\n".join(response_lines)

            return CallToolResult(
                content=[TextContent(type="text", text=response_text)]
            )

        except Exception as e:
            logger.error(f"Project analysis failed: {e}")
            return CallToolResult(
                content=[
                    TextContent(type="text", text=f"Project analysis failed: {str(e)}")
                ],
                isError=True,
            )

    async def _analyze_file(self, args: dict[str, Any]) -> CallToolResult:
        """Handle analyze_file tool call."""
        file_path_str = args.get("file_path", "")

        if not file_path_str:
            return CallToolResult(
                content=[
                    TextContent(type="text", text="file_path parameter is required")
                ],
                isError=True,
            )

        try:
            file_path = Path(file_path_str)
            if not file_path.is_absolute():
                file_path = self.project_root / file_path

            if not file_path.exists():
                return CallToolResult(
                    content=[
                        TextContent(
                            type="text", text=f"File not found: {file_path_str}"
                        )
                    ],
                    isError=True,
                )

            # Analyze single file
            from mcp_code_intelligence.analysis import (
                CognitiveComplexityCollector,
                CyclomaticComplexityCollector,
                MethodCountCollector,
                NestingDepthCollector,
                ParameterCountCollector,
            )
            from mcp_code_intelligence.cli.commands.analyze import _analyze_file

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
                return CallToolResult(
                    content=[
                        TextContent(
                            type="text",
                            text=f"Unable to analyze file: {file_path_str}",
                        )
                    ],
                    isError=True,
                )

            # Detect smells
            smell_detector = SmellDetector()
            smells = smell_detector.detect_all(file_metrics, str(file_path))

            # Format response
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
                for smell in smells[:10]:  # Show top 10
                    response_lines.append(
                        f"- [{smell.severity.value.upper()}] {smell.name}: {smell.description}"
                    )
                if len(smells) > 10:
                    response_lines.append(f"\n... and {len(smells) - 10} more")
            else:
                response_lines.append("## Code Smells\n- None detected")

            response_text = "\n".join(response_lines)

            return CallToolResult(
                content=[TextContent(type="text", text=response_text)]
            )

        except Exception as e:
            logger.error(f"File analysis failed: {e}")
            return CallToolResult(
                content=[
                    TextContent(type="text", text=f"File analysis failed: {str(e)}")
                ],
                isError=True,
            )

    async def _find_smells(self, args: dict[str, Any]) -> CallToolResult:
        """Handle find_smells tool call."""
        smell_type_filter = args.get("smell_type")
        severity_filter = args.get("severity")

        try:
            # Run full project analysis
            from mcp_code_intelligence.analysis import (
                CognitiveComplexityCollector,
                CyclomaticComplexityCollector,
                MethodCountCollector,
                NestingDepthCollector,
                ParameterCountCollector,
            )
            from mcp_code_intelligence.cli.commands.analyze import _analyze_file, _find_analyzable_files

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
                    file_metrics = await _analyze_file(
                        file_path, parser_registry, collectors
                    )
                    if file_metrics and file_metrics.chunks:
                        project_metrics.files[str(file_path)] = file_metrics
                except Exception:  # nosec B112 - intentional skip of unparseable files
                    continue

            # Detect all smells
            smell_detector = SmellDetector()
            all_smells = []
            for file_path, file_metrics in project_metrics.files.items():
                file_smells = smell_detector.detect_all(file_metrics, file_path)
                all_smells.extend(file_smells)

            # Apply filters
            filtered_smells = all_smells

            if smell_type_filter:
                filtered_smells = [
                    s for s in filtered_smells if s.name == smell_type_filter
                ]

            if severity_filter:
                severity_enum = SmellSeverity(severity_filter)
                filtered_smells = [
                    s for s in filtered_smells if s.severity == severity_enum
                ]

            # Format response
            if not filtered_smells:
                filter_desc = []
                if smell_type_filter:
                    filter_desc.append(f"type={smell_type_filter}")
                if severity_filter:
                    filter_desc.append(f"severity={severity_filter}")
                filter_str = f" ({', '.join(filter_desc)})" if filter_desc else ""
                response_text = f"No code smells found{filter_str}"
            else:
                response_lines = [f"# Code Smells Found: {len(filtered_smells)}\n"]

                # Group by severity
                by_severity = {
                    "error": [
                        s for s in filtered_smells if s.severity == SmellSeverity.ERROR
                    ],
                    "warning": [
                        s
                        for s in filtered_smells
                        if s.severity == SmellSeverity.WARNING
                    ],
                    "info": [
                        s for s in filtered_smells if s.severity == SmellSeverity.INFO
                    ],
                }

                for severity_level in ["error", "warning", "info"]:
                    smells = by_severity[severity_level]
                    if smells:
                        response_lines.append(
                            f"## {severity_level.upper()} ({len(smells)})\n"
                        )
                        for smell in smells[:20]:  # Show top 20 per severity
                            response_lines.append(
                                f"- **{smell.name}** at `{smell.location}`"
                            )
                            response_lines.append(f"  {smell.description}")
                            if smell.suggestion:
                                response_lines.append(
                                    f"  *Suggestion: {smell.suggestion}*"
                                )
                            response_lines.append("")

                response_text = "\n".join(response_lines)

            return CallToolResult(
                content=[TextContent(type="text", text=response_text)]
            )

        except Exception as e:
            logger.error(f"Smell detection failed: {e}")
            return CallToolResult(
                content=[
                    TextContent(type="text", text=f"Smell detection failed: {str(e)}")
                ],
                isError=True,
            )

    async def _get_complexity_hotspots(self, args: dict[str, Any]) -> CallToolResult:
        """Handle get_complexity_hotspots tool call."""
        limit = args.get("limit", 10)

        try:
            # Run full project analysis
            from mcp_code_intelligence.analysis import (
                CognitiveComplexityCollector,
                CyclomaticComplexityCollector,
                MethodCountCollector,
                NestingDepthCollector,
                ParameterCountCollector,
            )
            from mcp_code_intelligence.cli.commands.analyze import _analyze_file, _find_analyzable_files

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
                    file_metrics = await _analyze_file(
                        file_path, parser_registry, collectors
                    )
                    if file_metrics and file_metrics.chunks:
                        project_metrics.files[str(file_path)] = file_metrics
                except Exception:  # nosec B112 - intentional skip of unparseable files
                    continue

            # Get top N complex files
            hotspots = project_metrics.get_hotspots(limit=limit)

            # Format response
            if not hotspots:
                response_text = "No complexity hotspots found"
            else:
                response_lines = [f"# Top {len(hotspots)} Complexity Hotspots\n"]

                for i, file_metrics in enumerate(hotspots, 1):
                    response_lines.extend(
                        [
                            f"## {i}. {Path(file_metrics.file_path).name}",
                            f"**Path:** `{file_metrics.file_path}`",
                            f"**Average Complexity:** {file_metrics.avg_complexity:.2f}",
                            f"**Max Complexity:** {file_metrics.max_complexity}",
                            f"**Total Complexity:** {file_metrics.total_complexity}",
                            f"**Functions:** {file_metrics.function_count}",
                            f"**Health Score:** {file_metrics.health_score:.2f}\n",
                        ]
                    )

                response_text = "\n".join(response_lines)

            return CallToolResult(
                content=[TextContent(type="text", text=response_text)]
            )

        except Exception as e:
            logger.error(f"Hotspot detection failed: {e}")
            return CallToolResult(
                content=[
                    TextContent(type="text", text=f"Hotspot detection failed: {str(e)}")
                ],
                isError=True,
            )

    async def _check_circular_dependencies(
        self, args: dict[str, Any]
    ) -> CallToolResult:
        """Handle check_circular_dependencies tool call."""
        try:
            # Find analyzable files to build import graph
            from mcp_code_intelligence.cli.commands.analyze import _find_analyzable_files

            parser_registry = ParserRegistry()
            files_to_analyze = _find_analyzable_files(
                self.project_root, None, None, parser_registry, None
            )

            if not files_to_analyze:
                return CallToolResult(
                    content=[
                        TextContent(
                            type="text",
                            text="No analyzable files found in project",
                        )
                    ],
                    isError=True,
                )

            # Import circular dependency detection
            from mcp_code_intelligence.analysis.collectors.coupling import build_import_graph

            # Build import graph for the project (reverse dependency graph)
            import_graph = build_import_graph(
                self.project_root, files_to_analyze, language="python"
            )

            # Convert to forward dependency graph for cycle detection
            # import_graph maps: module -> set of files that import it (reverse)
            # We need: file -> list of files it imports (forward)
            forward_graph: dict[str, list[str]] = {}

            # Build forward graph by reading imports from files
            for file_path in files_to_analyze:
                file_str = str(file_path.relative_to(self.project_root))
                if file_str not in forward_graph:
                    forward_graph[file_str] = []

                # For each module in import_graph, if this file imports it, add edge
                for module, importers in import_graph.items():
                    for importer in importers:
                        importer_str = str(
                            Path(importer).relative_to(self.project_root)
                            if Path(importer).is_absolute()
                            else importer
                        )
                        if importer_str == file_str:
                            # This file imports the module, add forward edge
                            if module not in forward_graph[file_str]:
                                forward_graph[file_str].append(module)

            # Detect circular dependencies using DFS
            def find_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
                """Find all cycles in the import graph using DFS."""
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
                            # Found a cycle
                            try:
                                cycle_start = path.index(neighbor)
                                cycle = path[cycle_start:] + [neighbor]
                                # Normalize cycle representation to avoid duplicates
                                cycle_tuple = tuple(sorted(cycle))
                                if not any(
                                    tuple(sorted(c)) == cycle_tuple for c in cycles
                                ):
                                    cycles.append(cycle)
                            except ValueError:
                                pass

                    rec_stack.remove(node)

                for node in graph:
                    if node not in visited:
                        dfs(node, [])

                return cycles

            cycles = find_cycles(forward_graph)

            # Format response
            if not cycles:
                response_text = "No circular dependencies detected"
            else:
                response_lines = [f"# Circular Dependencies Found: {len(cycles)}\n"]

                for i, cycle in enumerate(cycles, 1):
                    response_lines.append(f"## Cycle {i}")
                    response_lines.append("```")
                    for j, node in enumerate(cycle):
                        if j < len(cycle) - 1:
                            response_lines.append(f"{node}")
                            response_lines.append("  ↓")
                        else:
                            response_lines.append(f"{node} (back to {cycle[0]})")
                    response_lines.append("```\n")

                response_text = "\n".join(response_lines)

            return CallToolResult(
                content=[TextContent(type="text", text=response_text)]
            )

        except Exception as e:
            logger.error(f"Circular dependency check failed: {e}")
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"Circular dependency check failed: {str(e)}",
                    )
                ],
                isError=True,
            )

    async def _interpret_analysis(self, args: dict[str, Any]) -> CallToolResult:
        """Handle interpret_analysis tool call."""
        analysis_json_str = args.get("analysis_json", "")
        focus = args.get("focus", "summary")
        verbosity = args.get("verbosity", "normal")

        if not analysis_json_str:
            return CallToolResult(
                content=[
                    TextContent(type="text", text="analysis_json parameter is required")
                ],
                isError=True,
            )

        try:
            import json

            from mcp_code_intelligence.analysis.interpretation import AnalysisInterpreter, LLMContextExport

            # Parse JSON input
            analysis_data = json.loads(analysis_json_str)

            # Convert to LLMContextExport
            export = LLMContextExport(**analysis_data)

            # Create interpreter and generate interpretation
            interpreter = AnalysisInterpreter()
            interpretation = interpreter.interpret(
                export, focus=focus, verbosity=verbosity
            )

            return CallToolResult(
                content=[TextContent(type="text", text=interpretation)]
            )

        except json.JSONDecodeError as e:
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"Invalid JSON input: {str(e)}",
                    )
                ],
                isError=True,
            )
        except Exception as e:
            logger.error(f"Analysis interpretation failed: {e}")
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"Interpretation failed: {str(e)}",
                    )
                ],
                isError=True,
            )

    def _get_threshold_config(self, preset: str) -> ThresholdConfig:
        """Get threshold configuration based on preset.

        Args:
            preset: Threshold preset ('strict', 'standard', or 'relaxed')

        Returns:
            ThresholdConfig instance
        """
        if preset == "strict":
            # Stricter thresholds
            config = ThresholdConfig()
            config.complexity.cognitive_a = 3
            config.complexity.cognitive_b = 7
            config.complexity.cognitive_c = 15
            config.complexity.cognitive_d = 20
            config.smells.long_method_lines = 30
            config.smells.high_complexity = 10
            config.smells.too_many_parameters = 3
            config.smells.deep_nesting_depth = 3
            return config
        elif preset == "relaxed":
            # More relaxed thresholds
            config = ThresholdConfig()
            config.complexity.cognitive_a = 7
            config.complexity.cognitive_b = 15
            config.complexity.cognitive_c = 25
            config.complexity.cognitive_d = 40
            config.smells.long_method_lines = 75
            config.smells.high_complexity = 20
            config.smells.too_many_parameters = 7
            config.smells.deep_nesting_depth = 5
            return config
        else:
            # Standard (default)
            return ThresholdConfig()

    async def _handle_propose_logic(self, args: dict[str, Any]) -> CallToolResult:
        """Handle propose_logic tool call to prevent duplication."""
        if not self._enable_logic_check:
            return CallToolResult(
                content=[TextContent(type="text", text="ℹ️ Logic Check feature is currently disabled in project configuration.")]
            )

        intent = args.get("intent", "")
        code_draft = args.get("code_draft")

        if not intent:
            return CallToolResult(
                content=[TextContent(type="text", text="Intent is required.")],
                isError=True,
            )

        analysis = await self.guardian.check_intent_duplication(intent, code_draft)

        if not analysis["duplicate_found"]:
            return CallToolResult(
                content=[TextContent(type="text", text="✅ No similar logic found. You can proceed with the implementation.")]
            )

        # Format the Blocker Notice
        response_lines = [
            "### 🛑 STOP! LOGIC DUPLICATION DETECTED",
            "\n> [!CAUTION]",
            "> **Highly similar logic already exists in your codebase.**",
            "> Implementing this again would create technical debt. Please use the existing implementation below:\n"
        ]

        for i, match in enumerate(analysis["matches"], 1):
            func = match['function_name'] or "Global/Block"
            response_lines.append(f"#### 🔍 Match {i} (Confidence: {match['score']:.2f})")
            response_lines.append(f"- **File:** `{match['file_path']}`")
            response_lines.append(f"- **Symbol:** `{func}`")
            response_lines.append(f"- **Location:** `{match['location']}`")
            response_lines.append("\n**Existing Code Snippet:**")
            response_lines.append(f"```python\n{match['content'][:400]}...\n```\n")

        response_lines.append("\n---")
        response_lines.append("> [!TIP]")
        response_lines.append("> Instead of writing new code, please **import and reuse** the existing logic.")

        return CallToolResult(content=[TextContent(type="text", text="\n".join(response_lines))])


def create_mcp_server(
    project_root: Path | None = None, enable_file_watching: bool | None = None
) -> Server:
    """Create and configure the MCP server.

    Args:
        project_root: Project root directory. If None, will auto-detect.
        enable_file_watching: Enable file watching for automatic reindexing.
                              If None, checks MCP_ENABLE_FILE_WATCHING env var (default: True).
    """
    server = Server("mcp-code-intelligence")
    mcp_server = MCPVectorSearchServer(project_root, enable_file_watching)

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        """List available tools."""
        return mcp_server.get_tools()

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict | None):
        """Handle tool calls."""
        # Create a mock request object for compatibility
        from types import SimpleNamespace

        mock_request = SimpleNamespace()
        mock_request.params = SimpleNamespace()
        mock_request.params.name = name
        mock_request.params.arguments = arguments or {}

        result = await mcp_server.call_tool(mock_request)

        # Return the content from the result
        return result.content

    # Store reference for cleanup
    server._mcp_server = mcp_server

    return server


async def run_mcp_server(
    project_root: Path | None = None, enable_file_watching: bool | None = None
) -> None:
    """Run the MCP server using stdio transport.

    Args:
        project_root: Project root directory. If None, will auto-detect.
        enable_file_watching: Enable file watching for automatic reindexing.
                              If None, checks MCP_ENABLE_FILE_WATCHING env var (default: True).
    """
    server = create_mcp_server(project_root, enable_file_watching)

    # Create initialization options with proper capabilities
    init_options = InitializationOptions(
        server_name="mcp-code-intelligence",
        server_version="0.4.0",
        capabilities=ServerCapabilities(tools={"listChanged": True}, logging={}),
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
        # Cleanup
        if hasattr(server, "_mcp_server"):
            logger.info("Performing server cleanup...")
            await server._mcp_server.cleanup()


if __name__ == "__main__":
    # Allow specifying project root as command line argument
    project_root = Path(sys.argv[1]) if len(sys.argv) > 1 else None

    # Check for file watching flag in command line args
    enable_file_watching = None
    if "--no-watch" in sys.argv:
        enable_file_watching = False
        sys.argv.remove("--no-watch")
    elif "--watch" in sys.argv:
        enable_file_watching = True
        sys.argv.remove("--watch")

    asyncio.run(run_mcp_server(project_root, enable_file_watching))


