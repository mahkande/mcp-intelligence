"""Index runner: orchestrates indexing, embedding setup, and database init."""
import asyncio
from pathlib import Path
from loguru import logger

from mcp_code_intelligence.config.defaults import get_default_cache_path
from mcp_code_intelligence.core.database import ChromaVectorDatabase
from mcp_code_intelligence.core.embeddings import create_embedding_function
from mcp_code_intelligence.core.exceptions import ProjectNotFoundError
from mcp_code_intelligence.core.indexer import SemanticIndexer
from mcp_code_intelligence.core.project import ProjectManager
from mcp_code_intelligence.cli.output import print_error, print_info

from mcp_code_intelligence.cli.commands.index_progress import _run_batch_indexing, _run_watch_mode


async def run_indexing(
    project_root: Path,
    watch: bool = False,
    incremental: bool = True,
    extensions: str | None = None,
    force_reindex: bool = False,
    batch_size: int = 32,
    show_progress: bool = True,
    debug: bool = False,
    skip_relationships: bool = False,
    workers: int | None = None,
    throttle: float = 0.0,
    max_size: int = 1024,
    important_only: bool = False,
    files: str | None = None,
    quiet: bool = False,
) -> None:
    """Run the indexing process."""
    if quiet:
        import logging
        # Reduce log level for quiet mode if needed, but primary impact is on print statements
        logging.getLogger("mcp_code_intelligence").setLevel(logging.ERROR)

    project_manager = ProjectManager(project_root)

    if not project_manager.is_initialized():
        raise ProjectNotFoundError(
            f"Project not initialized at {project_root}. Run 'mcp-code-intelligence init' first."
        )

    config = project_manager.load_config()

    if extensions:
        file_extensions = [ext.strip() for ext in extensions.split(",")]
        file_extensions = [ext if ext.startswith(".") else f".{ext}" for ext in file_extensions]
        config = config.model_copy(update={
            "file_extensions": file_extensions,
            "max_workers": workers,
            "throttle_delay": throttle,
            "max_file_size_kb": max_size,
            "index_important_only": important_only,
        })
    else:
        config = config.model_copy(update={
            "max_workers": workers,
            "throttle_delay": throttle,
            "max_file_size_kb": max_size,
            "index_important_only": important_only,
        })

    print_info(f"Indexing project: {project_root}")
    print_info(f"File extensions: {', '.join(config.file_extensions)}")
    print_info(f"Embedding model: {config.embedding_model}")

    cache_dir = (get_default_cache_path(project_root) if config.cache_embeddings else None)
    embedding_function, cache = create_embedding_function(
        model_name=config.embedding_model, cache_dir=cache_dir, cache_size=config.max_cache_size
    )

    # DEBUG: Inspect embedding_function type
    print_info(f"DEBUG INSP: embedding_function type: {type(embedding_function)}")
    print_info(f"DEBUG INSP: embedding_function repr: {repr(embedding_function)}")
    if isinstance(embedding_function, str):
        print_error("CRITICAL ERROR: embedding_function is a STRING! This will cause ChromaDB to fail.")

    # Handle force reindex by deleting old database if there's an embedding function conflict
    if force_reindex:
        import shutil
        chroma_dir = config.index_path
        if chroma_dir.exists():
            logger.info(f"Force reindex enabled - removing existing database at {chroma_dir}")
            print_info(f"🗑️  Removing existing database for fresh indexing...")
            try:
                shutil.rmtree(chroma_dir)
                logger.info("Successfully removed old database")
            except Exception as e:
                logger.warning(f"Failed to remove old database: {e}")
                print_info(f"⚠️  Could not remove old database: {e}")

    database = ChromaVectorDatabase(persist_directory=config.index_path, embedding_function=embedding_function)

    indexer = SemanticIndexer(database=database, project_root=project_root, config=config)

    try:
        async with database:
            if watch:
                await _run_watch_mode(indexer, show_progress and not quiet)
            else:
                if files:
                    # Convert comma-separated string to list of Paths
                    file_paths = [project_root / f.strip() for f in files.split(",")]
                    # Validate files exist and are within project root
                    valid_files = [f for f in file_paths if f.exists() and project_root in f.parents]
                    
                    if not quiet:
                        print_info(f"Indexing {len(valid_files)} specific files")
                    
                    await _run_batch_indexing(
                        indexer, 
                        force_reindex, 
                        show_progress and not quiet, 
                        skip_relationships,
                        files_to_index=valid_files
                    )
                else:
                    indexable_files = indexer.scanner_service.scan_files()
                    if not quiet:
                        print_info(f"Indexable files: {len(indexable_files)}")
                    await _run_batch_indexing(indexer, force_reindex, show_progress and not quiet, skip_relationships)

    except Exception as e:
        logger.error(f"Indexing error: {e}", exc_info=True)
        print_error(f"Indexing error: {e}")
        raise
