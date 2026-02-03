"""Index command module — lightweight entrypoint that registers submodules.

This file is intentionally small: it exposes `index_app` and delegates
work to the split modules in the same folder so each file stays under
~200-300 lines for maintainability.
"""

from pathlib import Path
import asyncio
import typer
from mcp_code_intelligence.cli.error_handler import handle_cli_errors
from mcp_code_intelligence.cli.commands.index_runner import run_indexing

# CLI app for `mcp-code-intelligence index`
index_app = typer.Typer(help="Index codebase for semantic search", invoke_without_command=True)


@index_app.callback(invoke_without_command=True)
@handle_cli_errors
def main(
    ctx: typer.Context,
    watch: bool = typer.Option(False, help="Watch for file changes and reindex live"),
    incremental: bool = typer.Option(True, help="Incremental indexing (default: True)"),
    extensions: str = typer.Option(None, help="Comma-separated list of file extensions to index"),
    force_reindex: bool = typer.Option(False, help="Force full reindexing"),
    batch_size: int = typer.Option(32, help="Batch size for indexing"),
    show_progress: bool = typer.Option(True, help="Show progress bar"),
    debug: bool = typer.Option(False, help="Enable debug output"),
    skip_relationships: bool = typer.Option(False, help="Skip relationship indexing"),
    workers: int = typer.Option(None, help="Number of worker processes"),
    throttle: float = typer.Option(0.0, help="Throttle delay between batches"),
    max_size: int = typer.Option(1024, help="Max file size in KB"),
    important_only: bool = typer.Option(False, help="Index only important files"),
    files: str = typer.Option(None, "--files", help="Comma-separated list of specific files to index"),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress non-error output"),
) -> None:
    """Entrypoint for `mcp-code-intelligence index`.

    Delegates to `index_runner` or spawns a background indexer.
    """
    if ctx.invoked_subcommand is not None:
        return

    # Lazy imports to avoid heavy module loads during CLI discovery
    from mcp_code_intelligence.cli.commands.index_runner import run_indexing
    from mcp_code_intelligence.cli.commands.index_background import _spawn_background_indexer

    project_root = (ctx.obj.get("project_root") if ctx.obj else None) or Path.cwd()
    background = False  # Optionally add a CLI flag if needed

    if background:
        _spawn_background_indexer(
            project_root,
            force=force_reindex,
            extensions=extensions,
            workers=workers,
            throttle=throttle,
            max_size=max_size,
            important_only=important_only,
        )
        return

    asyncio.run(
        run_indexing(
            project_root=project_root,
            watch=watch,
            incremental=incremental,
            extensions=extensions,
            force_reindex=force_reindex,
            batch_size=batch_size,
            show_progress=show_progress,
            debug=debug,
            skip_relationships=skip_relationships,
            workers=workers,
            throttle=throttle,
            max_size=max_size,
            important_only=important_only,
            files=files,
            quiet=quiet,
        )
    )


# Import submodules to register CLI subcommands (they import `index_app` from this file)
from mcp_code_intelligence.cli.commands import index_progress, index_background, index_runner, index_reindex, index_status



