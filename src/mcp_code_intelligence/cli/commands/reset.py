"""Reset and recovery commands for MCP Code Intelligence."""

import asyncio
import shutil
from pathlib import Path

import typer
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

from mcp_code_intelligence.core.exceptions import DatabaseError, IndexCorruptionError
from mcp_code_intelligence.core.project import ProjectManager
from mcp_code_intelligence.cli.error_handler import handle_cli_errors
from mcp_code_intelligence.cli.output import print_error, print_success, print_warning

console = Console()

# Create Typer app for reset commands
reset_app = typer.Typer(
    name="reset",
    help="Reset and recovery operations",
    rich_markup_mode="rich",
)


@reset_app.command("index")
def reset_index(
    project_root: Path = typer.Option(
        None,
        "--project-root",
        "-p",
        help="Project root directory",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompt",
    ),
    backup: bool = typer.Option(
        True,
        "--backup/--no-backup",
        help="Create backup before resetting",
    ),
) -> None:
    """Reset the vector search index (clear corrupted data).

    This command will:
    - Create a backup of the current index (unless --no-backup)
    - Clear the entire vector database
    - Preserve your configuration settings

    After reset, run 'mcp-code-intelligence index' to rebuild.
    """
    root = project_root or Path.cwd()

    try:
        # Check if project is initialized
        project_manager = ProjectManager(root)
        if not project_manager.is_initialized():
            print_error("Project not initialized. Run 'mcp-code-intelligence init' first.")
            raise typer.Exit(1)

        # Get confirmation unless forced
        if not force:
            console.print(f"\n[red]Index Reset Confirmation[/red]")
            console.print("-" * 30)
            console.print(
                "[yellow]⚠️  Warning: This will clear the entire search index![/yellow]\n\n"
                "The following will happen:\n"
                "• All indexed code chunks will be deleted\n"
                "• The vector database will be reset\n"
                "• Configuration settings will be preserved\n"
                f"• {'A backup will be created' if backup else 'No backup will be created'}\n\n"
                "You will need to run 'mcp-code-intelligence index' afterward to rebuild."
            )

            if not Confirm.ask("\nDo you want to proceed?", default=False):
                console.print("[yellow]Reset cancelled[/yellow]")
                raise typer.Exit(0)

        # Get the database directory from config
        config = project_manager.load_config()
        db_path = Path(config.index_path)

        # Check if index exists (look for chroma.sqlite3 or collection directories)
        has_index = (db_path / "chroma.sqlite3").exists()

        if not has_index:
            print_warning("No index found. Nothing to reset.")
            raise typer.Exit(0)

        # Files/dirs to remove (index data)
        index_files = [
            "chroma.sqlite3",
            "cache",
            "indexing_errors.log",
            "index_metadata.json",
            "directory_index.json",
        ]

        # Also remove any UUID-named directories (ChromaDB collections)
        if db_path.exists():
            for item in db_path.iterdir():
                if item.is_dir() and len(item.name) == 36 and "-" in item.name:
                    # Looks like a UUID directory
                    index_files.append(item.name)

        # Create backup if requested
        if backup:
            backup_dir = db_path / "backups"
            backup_dir.mkdir(exist_ok=True)

            import time

            timestamp = int(time.time())
            backup_path = backup_dir / f"index_backup_{timestamp}"
            backup_path.mkdir(exist_ok=True)

            try:
                backed_up = []
                for file in index_files:
                    src = db_path / file
                    if src.exists():
                        dest = backup_path / file
                        if src.is_dir():
                            shutil.copytree(src, dest)
                        else:
                            shutil.copy2(src, dest)
                        backed_up.append(file)

                if backed_up:
                    print_success(f"Created backup at: {backup_path.relative_to(root)}")
            except Exception as e:
                print_warning(f"Could not create backup: {e}")
                if not force:
                    if not Confirm.ask("Continue without backup?", default=False):
                        console.print("[yellow]Reset cancelled[/yellow]")
                        raise typer.Exit(0)

        # Clear the index files
        console.print("[cyan]Clearing index...[/cyan]")
        removed_count = 0
        try:
            for file in index_files:
                path = db_path / file
                if path.exists():
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                    removed_count += 1

            if removed_count > 0:
                print_success(
                    f"Index cleared successfully! ({removed_count} items removed)"
                )
            else:
                print_warning("No index files found to remove.")
        except Exception as e:
            print_error(f"Failed to clear index: {e}")
            raise typer.Exit(1)

        # Show next steps
        console.print(f"\n[green]✅ Index reset complete![/green]\n")
        console.print("Next steps:")
        console.print("1. Run [cyan]mcp-code-intelligence index[/cyan] to rebuild the search index")
        console.print("2. Or run [cyan]mcp-code-intelligence watch[/cyan] to start incremental indexing")

    except (DatabaseError, IndexCorruptionError) as e:
        print_error(f"Reset failed: {e}")
        raise typer.Exit(1)
    except Exception as e:
        logger.error(f"Unexpected error during reset: {e}")
        print_error(f"Unexpected error: {e}")
        raise typer.Exit(1)


@reset_app.command("all")
def reset_all(
    project_root: Path = typer.Option(
        None,
        "--project-root",
        "-p",
        help="Project root directory",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompt",
    ),
) -> None:
    """Reset everything (index and configuration).

    This will completely remove all MCP Code Intelligence data,
    requiring re-initialization with 'mcp-code-intelligence init'.
    """
    root = project_root or Path.cwd()

    # Get confirmation unless forced
    if not force:
        console.print(f"\n[red]Complete Reset Confirmation[/red]")
        console.print("-" * 30)
        console.print(
            "[red]⚠️  DANGER: This will remove ALL MCP Code Intelligence data![/red]\n\n"
            "The following will be deleted:\n"
            "• All indexed code chunks\n"
            "• The vector database\n"
            "• All configuration settings\n"
            "• All project metadata\n\n"
            "You will need to run 'mcp-code-intelligence init' to start over."
        )

        if not Confirm.ask("\nAre you absolutely sure?", default=False):
            console.print("[yellow]Reset cancelled[/yellow]")
            raise typer.Exit(0)

        # Double confirmation for destructive action
        if not Confirm.ask("Type 'yes' to confirm complete reset", default=False):
            console.print("[yellow]Reset cancelled[/yellow]")
            raise typer.Exit(0)

    # Remove entire .mcp_code_intelligence directory
    mcp_dir = root / ".mcp_code_intelligence"

    if not mcp_dir.exists():
        print_warning("No MCP Code Intelligence data found. Nothing to reset.")
        raise typer.Exit(0)

    console.print("[cyan]Removing all MCP Code Intelligence data...[/cyan]")
    try:
        shutil.rmtree(mcp_dir)
        print_success("All data removed successfully!")

        console.print(f"\n[green]✅ Complete reset done![/green]\n")
        console.print("To start using MCP Code Intelligence again:")
        console.print("1. Run [cyan]mcp-code-intelligence init[/cyan] to initialize the project")
        console.print("2. Run [cyan]mcp-code-intelligence index[/cyan] to index your codebase")
    except Exception as e:
        print_error(f"Failed to remove data: {e}")
        raise typer.Exit(1)


async def check_health(
    project_root: Path,
    fix: bool,
) -> None:
    """Check the health of the search index.

    This command will:
    - Verify database connectivity
    - Check for index corruption
    - Validate collection integrity
    - Optionally attempt repairs with --fix
    """
    root = project_root or Path.cwd()

    try:
        # Check if project is initialized
        project_manager = ProjectManager(root)
        if not project_manager.is_initialized():
            print_error("Project not initialized. Run 'mcp-code-intelligence init' first.")
            raise typer.Exit(1)

        console.print("[cyan]Performing health check...[/cyan]\n")

        # Initialize database
        from mcp_code_intelligence.config.defaults import get_default_cache_path
        from mcp_code_intelligence.core.database import ChromaVectorDatabase
        from mcp_code_intelligence.core.embeddings import create_embedding_function

        config = project_manager.load_config()
        db_path = Path(config.index_path)

        # Setup embedding function and cache
        cache_dir = get_default_cache_path(root) if config.cache_embeddings else None
        embedding_function, _ = create_embedding_function(
            model_name=config.embedding_model,
            cache_dir=cache_dir,
            cache_size=config.max_cache_size,
        )

        # Create database instance
        db = ChromaVectorDatabase(
            persist_directory=db_path,
            embedding_function=embedding_function,
        )

        # Initialize and check health
        try:
            await db.initialize()
            is_healthy = await db.health_check()

            if is_healthy:
                # Get stats for additional info
                stats = await db.get_stats()

                console.print(f"\n[green]Health Check Passed[/green]")
                console.print("-" * 30)
                console.print(
                    f"[green]✅ Index is healthy![/green]\n\n"
                    f"Statistics:\n"
                    f"• Total chunks: {stats.total_chunks:,}\n"
                    f"• Total files: {stats.total_files:,}\n"
                    f"• Languages: {', '.join(stats.languages.keys()) if stats.languages else 'None'}\n"
                    f"• Index size: {stats.index_size_mb:.2f} MB"
                )
            else:
                console.print(f"\n[red]Health Check Failed[/red]")
                console.print("-" * 30)
                console.print(
                    "[red]❌ Index health check failed![/red]\n\n"
                    "Detected issues:\n"
                    "• Index may be corrupted\n"
                    "• Database operations failing\n\n"
                    f"{'Run with --fix to attempt automatic repair' if not fix else 'Attempting to fix...'}"
                )

                if fix:
                    console.print("\n[cyan]Attempting to repair index...[/cyan]")
                    # The health check already attempts recovery
                    # Try to reinitialize
                    await db.close()
                    await db.initialize()

                    # Check again
                    is_healthy = await db.health_check()
                    if is_healthy:
                        print_success("Index repaired successfully!")
                    else:
                        print_error(
                            "Automatic repair failed. "
                            "Please run 'mcp-code-intelligence reset index' followed by 'mcp-code-intelligence index'"
                        )
                        raise typer.Exit(1)
                else:
                    print_warning(
                        "Run 'mcp-code-intelligence reset health --fix' to attempt automatic repair,\n"
                        "or 'mcp-code-intelligence reset index' to clear and rebuild."
                    )
                    raise typer.Exit(1)

        except IndexCorruptionError as e:
            console.print(f"\n[red]Corruption Detected[/red]")
            console.print("-" * 30)
            console.print(
                f"[red]❌ Index corruption detected![/red]\n\n"
                f"Error: {e}\n\n"
                "Recommended actions:\n"
                "1. Run [cyan]mcp-code-intelligence reset index[/cyan] to clear the corrupted index\n"
                "2. Run [cyan]mcp-code-intelligence index[/cyan] to rebuild"
            )
            raise typer.Exit(1)

        finally:
            await db.close()

    except Exception as e:
        logger.error(f"Health check error: {e}")
        print_error(f"Health check failed: {e}")
        raise typer.Exit(1)


# Main reset command that shows subcommands
@reset_app.callback(invoke_without_command=True)
@handle_cli_errors
def reset_main(ctx: typer.Context) -> None:
    """Reset and recovery operations for MCP Code Intelligence."""
    if ctx.invoked_subcommand is None:
        console.print(f"\n[cyan]Reset Commands[/cyan]")
        console.print("-" * 30)
        console.print(
            "Available reset commands:\n\n"
            "[cyan]mcp-code-intelligence reset index[/cyan]\n"
            "  Reset the search index (preserves config)\n\n"
            "[cyan]mcp-code-intelligence reset health[/cyan]\n"
            "  Check index health and optionally repair\n\n"
            "[cyan]mcp-code-intelligence reset all[/cyan]\n"
            "  Complete reset (removes everything)\n"
        )


# Export for backwards compatibility
main = reset_main


# Make health check synchronous for CLI
@reset_app.command("health")
def health_main(
    project_root: Path = typer.Option(
        None,
        "--project-root",
        "-p",
        help="Project root directory",
    ),
    fix: bool = typer.Option(
        False,
        "--fix",
        help="Attempt to fix issues if found",
    ),
) -> None:
    """Check the health of the search index.

    This command will:
    - Verify database connectivity
    - Check for index corruption
    - Validate collection integrity
    - Optionally attempt repairs with --fix
    """
    asyncio.run(check_health(project_root, fix))



