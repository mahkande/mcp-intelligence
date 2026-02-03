"""Reindex-related CLI commands extracted from index.py."""
import asyncio
from pathlib import Path
import typer
from loguru import logger

from mcp_code_intelligence.cli.commands.index import index_app
from mcp_code_intelligence.cli.output import print_error, print_info
from mcp_code_intelligence.core.project import ProjectManager
from mcp_code_intelligence.core.database import ChromaVectorDatabase
from mcp_code_intelligence.config.defaults import get_default_cache_path
from mcp_code_intelligence.core.embeddings import create_embedding_function
from mcp_code_intelligence.core.exceptions import ProjectNotFoundError


@index_app.command("reindex")
def reindex_file(
    ctx: typer.Context,
    file_path: Path | None = typer.Argument(None, exists=True, file_okay=True, dir_okay=False, readable=True),
    all: bool = typer.Option(False, "--all", "-a", help="Explicitly reindex entire project"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt when reindexing entire project"),
) -> None:
    try:
        project_root = ctx.obj.get("project_root") or Path.cwd()

        if file_path is not None and all:
            print_error("Cannot specify both a file path and --all flag")
            raise typer.Exit(1)

        if file_path is not None:
            asyncio.run(_reindex_single_file(project_root, file_path))
        else:
            if not force and not all:
                from mcp_code_intelligence.cli.output import confirm_action

                if not confirm_action("This will reindex the entire project. Continue?", default=False):
                    print_info("Reindex operation cancelled")
                    raise typer.Exit(0)

            asyncio.run(_reindex_entire_project(project_root))

    except typer.Exit:
        raise
    except Exception as e:
        logger.error(f"Reindexing failed: {e}")
        print_error(f"Reindexing failed: {e}")
        raise typer.Exit(1)


async def _reindex_entire_project(project_root: Path) -> None:
    print_info("Starting full project reindex...")
    project_manager = ProjectManager(project_root)
    if not project_manager.is_initialized():
        raise ProjectNotFoundError(f"Project not initialized at {project_root}. Run 'mcp-code-intelligence init' first.")

    config = project_manager.load_config()

    print_info(f"Project: {project_root}")
    print_info(f"File extensions: {', '.join(config.file_extensions)}")
    print_info(f"Embedding model: {config.embedding_model}")

    cache_dir = (get_default_cache_path(project_root) if config.cache_embeddings else None)
    embedding_function, cache = create_embedding_function(model_name=config.embedding_model, cache_dir=cache_dir, cache_size=config.max_cache_size)

    database = ChromaVectorDatabase(persist_directory=config.index_path, embedding_function=embedding_function)

    # Use SemanticIndexer to reindex entire project
    from mcp_code_intelligence.core.indexer import SemanticIndexer

    indexer = SemanticIndexer(database=database, project_root=project_root, config=config)

    try:
        async with database:
            await indexer.index_project(force_reindex=True, show_progress=True)
    except Exception as e:
        logger.error(f"Reindex error: {e}")
        raise


async def _reindex_single_file(project_root: Path, file_path: Path) -> None:
    project_manager = ProjectManager(project_root)
    if not project_manager.is_initialized():
        raise ProjectNotFoundError(f"Project not initialized at {project_root}. Run 'mcp-code-intelligence init' first.")

    config = project_manager.load_config()
    cache_dir = (get_default_cache_path(project_root) if config.cache_embeddings else None)
    embedding_function, cache = create_embedding_function(model_name=config.embedding_model, cache_dir=cache_dir, cache_size=config.max_cache_size)
    database = ChromaVectorDatabase(persist_directory=config.index_path, embedding_function=embedding_function)
    from mcp_code_intelligence.core.indexer import SemanticIndexer
    indexer = SemanticIndexer(database=database, project_root=project_root, config=config)

    try:
        async with database:
            await indexer.reindex_file(file_path)
            print_info(f"Reindexed: {file_path}")
    except Exception as e:
        logger.error(f"Reindex single file error: {e}")
        raise
