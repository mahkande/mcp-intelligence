"""Status and cancel commands for background indexing."""
import json
import os
import signal
import sys
import time
from pathlib import Path
import typer
from loguru import logger

from mcp_code_intelligence.cli.commands.index import index_app
from mcp_code_intelligence.cli.output import console, print_error, print_info, print_warning, print_success


@index_app.command("status")
def status_cmd(ctx: typer.Context) -> None:
    try:
        project_root = ctx.obj.get("project_root") or Path.cwd()
        _show_background_status(project_root)
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        print_error(f"Status check failed: {e}")
        raise typer.Exit(1)


@index_app.command("cancel")
def cancel_cmd(ctx: typer.Context, force: bool = typer.Option(False, "--force", "-f", help="Force termination without confirmation")) -> None:
    try:
        project_root = ctx.obj.get("project_root") or Path.cwd()
        _cancel_background_indexer(project_root, force)
    except Exception as e:
        logger.error(f"Cancel failed: {e}")
        print_error(f"Cancel failed: {e}")
        raise typer.Exit(1)


def _show_background_status(project_root: Path) -> None:
    progress_file = project_root / ".mcp-code-intelligence" / "indexing_progress.json"

    if not progress_file.exists():
        print_info("No background indexing in progress")
        return

    try:
        with open(progress_file) as f:
            progress = json.load(f)
    except Exception as e:
        print_error(f"Failed to read progress file: {e}")
        return

    pid = progress.get("pid")
    is_alive = _is_process_alive(pid) if pid else False

    if not is_alive:
        print_warning(f"Process {pid} is no longer running")
        print_info("The background indexing process has stopped")
        print_info("Run [cyan]mcp-code-intelligence index --background[/cyan] to restart")
        return

    from rich.table import Table

    status = progress.get("status", "unknown")
    status_colors = {"initializing": "yellow", "scanning": "cyan", "running": "green", "computing_relationships": "cyan", "completed": "green", "failed": "red", "cancelled": "yellow"}
    status_color = status_colors.get(status, "white")

    table = Table(title="Background Indexing Status", show_header=True)
    table.add_column("Metric", style="cyan", width=20)
    table.add_column("Value", style="green")
    table.add_row("PID", str(pid))
    table.add_row("Status", f"[{status_color}]{status}[/{status_color}]")

    total = progress.get("total_files", 0)
    processed = progress.get("processed_files", 0)
    if total > 0:
        percentage = (processed / total) * 100
        table.add_row("Progress", f"{processed}/{total} files ({percentage:.1f}%)")
    else:
        table.add_row("Progress", f"{processed} files")

    current_file = progress.get("current_file")
    if current_file:
        table.add_row("Current File", current_file)

    table.add_row("Chunks Created", str(progress.get("chunks_created", 0)))
    table.add_row("Errors", str(progress.get("errors", 0)))

    eta_seconds = progress.get("eta_seconds", 0)
    if eta_seconds > 0:
        eta_minutes = eta_seconds / 60
        if eta_minutes < 1:
            table.add_row("ETA", f"{eta_seconds} seconds")
        else:
            table.add_row("ETA", f"{eta_minutes:.1f} minutes")

    last_updated = progress.get("last_updated")
    if last_updated:
        table.add_row("Last Updated", last_updated)

    console.print(table)

    log_file = project_root / ".mcp-code-intelligence" / "indexing_background.log"
    if log_file.exists():
        print_info(f"\nLog file: {log_file}")


def _is_process_alive(pid: int) -> bool:
    try:
        if sys.platform == "win32":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            process_query_information = 0x0400
            handle = kernel32.OpenProcess(process_query_information, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False


def _cancel_background_indexer(project_root: Path, force: bool = False) -> None:
    progress_file = project_root / ".mcp-code-intelligence" / "indexing_progress.json"

    if not progress_file.exists():
        print_info("No background indexing in progress")
        return

    try:
        with open(progress_file) as f:
            progress = json.load(f)
    except Exception as e:
        print_error(f"Failed to read progress file: {e}")
        return

    pid = progress.get("pid")
    if not pid:
        print_error("No PID found in progress file")
        return

    if not _is_process_alive(pid):
        print_warning(f"Process {pid} is not running (already completed?)")
        try:
            progress_file.unlink()
            print_info("Cleaned up stale progress file")
        except Exception as e:
            logger.error(f"Failed to clean up progress file: {e}")
        return

    if not force:
        from mcp_code_intelligence.cli.output import confirm_action

        if not confirm_action(f"Cancel background indexing process (PID: {pid})?", default=False):
            print_info("Cancellation aborted")
            return

    try:
        if sys.platform == "win32":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            process_terminate = 0x0001
            handle = kernel32.OpenProcess(process_terminate, False, pid)
            if handle:
                kernel32.TerminateProcess(handle, 0)
                kernel32.CloseHandle(handle)
                print_success(f"Cancelled indexing process {pid}")
            else:
                print_error(f"Failed to open process {pid}")
                return
        else:
            os.kill(pid, signal.SIGTERM)
            print_success(f"Cancelled indexing process {pid}")

        time.sleep(0.5)
        if progress_file.exists():
            progress_file.unlink()
            print_info("Cleaned up progress file")

    except ProcessLookupError:
        print_warning(f"Process {pid} not found (already completed?)")
        if progress_file.exists():
            progress_file.unlink()
    except PermissionError:
        print_error(f"Permission denied to cancel process {pid}")
    except Exception as e:
        logger.error(f"Failed to cancel process: {e}")
        print_error(f"Failed to cancel process: {e}")
