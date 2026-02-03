"""Modular setup command for MCP Code Intelligence CLI."""

import asyncio
import typer
from mcp_code_intelligence.cli.didyoumean import create_enhanced_typer
from mcp_code_intelligence.cli.error_handler import handle_cli_errors
from mcp_code_intelligence.cli.commands.setup.main import main_setup_task

setup_app = create_enhanced_typer(
    help="🚀 Smart setup for mcp-code-intelligence",
    invoke_without_command=True,
    no_args_is_help=False,
)

@setup_app.callback()
@handle_cli_errors
def main(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", "-f", help="Force re-initialization"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed progress"),
) -> None:
    """Smart setup with auto-detection and modular structure."""
    if ctx.invoked_subcommand is not None:
        return

    asyncio.run(main_setup_task(ctx, force, verbose))

@setup_app.command("doctor")
def doctor():
    """Diagnose system requirements."""
    # We can move doctor to modular structure later if needed
    from mcp_code_intelligence.cli.commands.setup.discovery import DiscoveryManager
    from pathlib import Path
    dm = DiscoveryManager(Path.cwd())
    # ... existing doctor logic can be simplified and added here
    pass

if __name__ == "__main__":
    setup_app()
