"""Progress and batch indexing helpers extracted from index.py."""
import asyncio
import os
from pathlib import Path
from loguru import logger

from mcp_code_intelligence.cli.output import console, print_info, print_success, print_tip


async def _run_batch_indexing(
    indexer,
    force_reindex: bool,
    show_progress: bool,
    skip_relationships: bool = False,
    files_to_index: list[Path] | None = None,
):
    """Run batch indexing of all files with progress UI."""
    if files_to_index is None:
        # If force_reindex is True, scan all files without hash check
        if force_reindex:
            indexable_files = indexer.scanner_service.scan_files()
        else:
            indexable_files = indexer.get_files_to_index(force_reindex=False)
    else:
        # If specific files are provided, we still check if they need indexing unless forced
        if force_reindex:
            indexable_files = files_to_index
        else:
            indexable_files = [f for f in files_to_index if indexer.metadata_manager.needs_indexing(f)]

    if show_progress:
        from rich.layout import Layout
        from rich.live import Live
        from rich.panel import Panel
        from rich.progress import (
            BarColumn,
            Progress,
            SpinnerColumn,
            TextColumn,
            TimeRemainingColumn,
        )
        total_files = len(indexable_files)

        if total_files == 0:
            console.print("[yellow]No files need indexing[/yellow]")
            indexed_count = 0
        else:
            if force_reindex:
                console.print("[bold cyan][INTELLIGENT FORCE][/bold cyan] [yellow]Skipping re-embedding for unchanged files. Recalculating architectural metrics...[/yellow]\n")
            
            console.print(f"[dim]Found {total_files} files to index[/dim]\n")

            recent_files = []
            current_file_name = ""
            indexed_count = 0
            failed_count = 0

            progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(bar_width=40),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TextColumn("({task.completed}/{task.total} files)"),
                TimeRemainingColumn(),
                console=console,
            )

            task = progress.add_task("Indexing files...", total=total_files)

            with Live(progress, console=console, refresh_per_second=4) as live:
                async for (file_path, chunks_added, success,) in indexer.index_files_with_progress(
                    indexable_files, force_reindex
                ):
                    if success:
                        indexed_count += 1
                    else:
                        failed_count += 1

                    progress.update(task, advance=1)
                    current_file_name = file_path.name
                    progress.update(
                        task, description=f"Indexing: [cyan]{current_file_name[:30]}...[/cyan]"
                    )

            # Try to update directory index
            try:
                chunk_stats = {}
                for file_path in indexable_files:
                    try:
                        mtime = os.path.getmtime(file_path)
                        chunk_stats[str(file_path)] = {"modified": mtime, "chunks": 1}
                    except OSError:
                        pass

                indexer.directory_index.rebuild_from_files(
                    indexable_files, indexer.project_root, chunk_stats=chunk_stats
                )
                indexer.directory_index.save()
            except Exception as e:
                logger.error(f"Failed to update directory index: {e}")

            if not skip_relationships and indexed_count > 0:
                try:
                    console.print("\n[cyan]Marking relationships for background computation...[/cyan]")
                    all_chunks = await indexer.database.get_all_chunks()

                    if len(all_chunks) > 0:
                        await indexer.relationship_store.compute_and_store(
                            all_chunks, indexer.database, background=True
                        )
                        console.print("[green]✓[/green] Relationships marked for background computation")
                        console.print(
                            "[dim]  → Use 'mcp-code-intelligence index relationships' to compute now[/dim]"
                        )
                except Exception as e:
                    logger.warning(f"Failed to mark relationships: {e}")
                    console.print(
                        "[yellow]⚠ Relationships not marked (visualization will compute on demand)[/yellow]"
                    )

            console.print()
            if failed_count > 0:
                console.print(f"[yellow]⚠ {failed_count} files failed to index[/yellow]")
                error_log_path = indexer.project_root / ".mcp-code-intelligence" / "indexing_errors.log"
                if error_log_path.exists():
                    _prune_error_log(error_log_path, max_lines=1000)
                    console.print(f"[dim]  → See details in: {error_log_path}[/dim]")
    else:
        indexed_count = await indexer.index_files(
            indexable_files, force_reindex=force_reindex, show_progress=False, skip_relationships=skip_relationships
        )

    stats = await indexer.get_indexing_stats()
    total_chunks = stats.get("total_chunks", 0)
    print_success(f"Processed {indexed_count} files ({total_chunks} searchable chunks created)")
    print_info("")
    return indexed_count, stats


async def _run_watch_mode(indexer, show_progress: bool) -> None:
    """Run indexing in watch mode."""
    print_info("Starting watch mode - press Ctrl+C to stop")
    print_info("Watch mode not yet implemented")
    raise NotImplementedError("Watch mode will be implemented in Phase 1B")


def _prune_error_log(log_path: Path, max_lines: int = 1000) -> None:
    try:
        with open(log_path) as f:
            lines = f.readlines()

        if len(lines) > max_lines:
            pruned_lines = lines[-max_lines:]
            with open(log_path, "w") as f:
                f.writelines(pruned_lines)

    except Exception as e:
        logger.warning(f"Failed to prune error log: {e}")
