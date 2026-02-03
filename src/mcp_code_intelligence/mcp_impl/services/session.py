"""SessionService: Handles connection, session management, and authentication."""

import asyncio
import os
from pathlib import Path
from loguru import logger
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_code_intelligence.core.database import ChromaVectorDatabase
    from mcp_code_intelligence.core.indexer import SemanticIndexer
    from mcp_code_intelligence.analysis.semantic import SemanticSearchEngine
    from mcp_code_intelligence.core.watcher import FileWatcher
    from mcp_code_intelligence.core.llm_client import LLMClient

from mcp_code_intelligence.core.embeddings import create_embedding_function
from mcp_code_intelligence.core.database import ChromaVectorDatabase
from mcp_code_intelligence.core.project import ProjectManager
from mcp_code_intelligence.core.config_utils import (
    get_openai_api_key,
    get_openrouter_api_key,
    get_preferred_llm_provider,
)
from mcp_code_intelligence.core.lsp_proxy import stop_proxies


class SessionService:
    """Manages MCP server sessions, connections, and authentication."""

    def __init__(self, project_root: Path, enable_file_watching: bool = True):
        logger.info(f"DEBUG: SessionService.__init__ START for {project_root}")
        self.project_root = project_root
        
        logger.info("DEBUG: Initializing ProjectManager...")
        self.project_manager = ProjectManager(self.project_root)
        logger.info("DEBUG: ProjectManager initialized.")

        # Session state
        self.search_engine: "SemanticSearchEngine | None" = None
        self.file_watcher: "FileWatcher | None" = None
        self.indexer: "SemanticIndexer | None" = None
        self.database: "ChromaVectorDatabase | None" = None
        self.llm_client: "LLMClient | None" = None
        self.guardian = None

        self.enable_file_watching = enable_file_watching
        self._initialized = False
        self._enable_guardian = False
        self._enable_logic_check = False
        self._heavy_init_complete = False
        self._heavy_init_error = None

        logger.info("DEBUG: Setting up activity logging...")
        self._setup_logging()
        logger.info("DEBUG: SessionService.__init__ END")

    def _setup_logging(self) -> None:
        """Setup logging to file for background activity monitoring."""
        from mcp_code_intelligence.core.logging_setup import setup_activity_logging
        setup_activity_logging(self.project_root, "mcp-server")

    def _setup_database(self, config) -> None:
        logger.info("DEBUG: _setup_database - Using top-level imports. Creating embedding function...")
        
        import time
        start_time = time.time()
        embedding_function, _ = create_embedding_function(
            model_name=config.embedding_model
        )
        elapsed = time.time() - start_time
        logger.info(f"DEBUG: _setup_database - Embedding function created in {elapsed:.2f}s")

        logger.info("DEBUG: _setup_database - Initializing ChromaVectorDatabase...")
        self.database = ChromaVectorDatabase(
            persist_directory=config.index_path,
            embedding_function=embedding_function,
        )
        logger.info("DEBUG: _setup_database - ChromaVectorDatabase initialized.")

    def _setup_search_engine(self, config) -> None:
        from mcp_code_intelligence.analysis.semantic import SemanticSearchEngine
        
        if not self.database:
            raise RuntimeError("Database not initialized")

        self.search_engine = SemanticSearchEngine(
            database=self.database,
            project_root=self.project_root,
            reranker_model_name=config.reranker_model,
        )

    def _setup_llm_client(self) -> None:
        try:
            from mcp_code_intelligence.core.llm_client import LLMClient
            
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
                try:
                    self.llm_client.search_engine = self.search_engine
                except Exception:
                    pass
                logger.info("LLM client initialized for context injection")
            else:
                logger.debug("No LLM API keys found; skipping LLM client initialization")
        except Exception as e:
            logger.warning(f"Failed to initialize LLM client: {e}")

    def _setup_guardian(self) -> None:
        try:
            from mcp_code_intelligence.analysis.guardian import GuardianManager
            if not self.database:
                raise RuntimeError("Database not initialized")
            self.guardian = GuardianManager(self.database, self.project_root)
        except Exception as e:
            logger.warning(f"Failed to initialize Guardian: {e}")

    def _setup_file_watcher(self, config) -> None:
        if not self.enable_file_watching:
            logger.info("File watching disabled")
            return

        if not self.database:
            raise RuntimeError("Database not initialized")

        from mcp_code_intelligence.core.indexer import SemanticIndexer
        from mcp_code_intelligence.core.watcher import FileWatcher

        self.indexer = SemanticIndexer(
            database=self.database,
            project_root=self.project_root,
            config=config,
        )

        self.file_watcher = FileWatcher(
            project_root=self.project_root,
            config=config,
            indexer=self.indexer,
            database=self.database,
        )

    async def _perform_heavy_initialization(self, config):
        """Perform heavy initialization (DB, Models) in background."""
        try:
            logger.info("DEBUG: [Background] Starting heavy initialization...")
            
            logger.info("DEBUG: [Background] Example 1/5: Setting up Database (Running in Thread)...")
            await asyncio.to_thread(self._setup_database, config)
            
            logger.info("DEBUG: [Background] Database setup complete. Connecting...")
            await self.database.__aenter__()
            logger.info("DEBUG: [Background] Database connected.")

            try:
                # Check directly using stats which is safer
                stats = await self.database.get_stats(skip_stats=True)
                chunk_count = stats.total_chunks

                if chunk_count == 0:
                    logger.warning("Index is empty. Tools will return 'Symbol not found' until indexing completes.")
                    logger.info("You can run 'mcp-code-intelligence index' manually or wait for auto-indexing.")
                else:
                    logger.info(f"[Background] Index already contains {chunk_count} chunks")
            except Exception as e:
                logger.warning(f"Could not check index stats: {e}")

            logger.info("DEBUG: [Background] Example 2/5: Setting up Search Engine...")
            self._setup_search_engine(config)
            
            logger.info("DEBUG: [Background] Example 3/5: Setting up LLM Client...")
            self._setup_llm_client()
            
            logger.info("DEBUG: [Background] Example 4/5: Setting up Guardian...")
            self._setup_guardian()
            self._enable_guardian = config.enable_guardian
            self._enable_logic_check = config.enable_logic_check

            logger.info("DEBUG: [Background] Example 5/5: Starting File Watcher...")
            await self._setup_file_watcher_async(config)
            
            self._heavy_init_complete = True
            logger.info("✅ [Background] Heavy initialization COMPLETE.")
            
        except Exception as e:
            self._heavy_init_error = str(e)
            logger.error(f"❌ [Background] Heavy initialization failed: {e}", exc_info=True)
            # Also print to stderr so it's visible even if logging fails
            import sys
            print(f"\n❌ CRITICAL: Background initialization failed: {e}\n", file=sys.stderr)

    async def initialize(self) -> None:
        """Initialize the session and all components."""
        if self._initialized:
            return

        try:
            logger.info("DEBUG: Loading project config...")
            config = self.project_manager.load_config()
            logger.info("DEBUG: Config loaded.")

            # Mark as initialized immediately so server can respond to basic requests
            self._initialized = True
            logger.info(f"Session marked as initialized for: {self.project_root}")
            
            # Start heavy tasks in background with explicit wrapper
            logger.info("DEBUG: Launching heavy initialization task...")
            
            async def _safe_heavy_init():
                try:
                    await self._perform_heavy_initialization(config)
                except Exception as e:
                    logger.critical(f"UNHANDLED BACKGROUND ERROR: {e}", exc_info=True)
            
            asyncio.create_task(_safe_heavy_init())

        except Exception as e: 
            logger.error(f"Failed to initialize session: {e}")
            raise

    async def _setup_file_watcher_async(self, config) -> None:
        self._setup_file_watcher(config)
        if self.file_watcher:
            await self.file_watcher.start()
            logger.info("File watching enabled for automatic reindexing")

    async def cleanup(self) -> None:
        if self.file_watcher and self.file_watcher.is_running:
            logger.info("Stopping file watcher...")
            await self.file_watcher.stop()
            self.file_watcher = None

        if self.database and hasattr(self.database, "__aexit__"):
            await self.database.__aexit__(None, None, None)
            self.database = None

        self.search_engine = None
        self.indexer = None
        self._initialized = False

        try:
            from mcp_code_intelligence.core.lsp_proxy import stop_proxies
            await stop_proxies(self.project_root)
        except Exception:
            logger.debug("Failed to stop LSP proxies during cleanup")

        logger.info("Session cleanup completed")

    @property
    def is_initialized(self) -> bool:
        return self._initialized
