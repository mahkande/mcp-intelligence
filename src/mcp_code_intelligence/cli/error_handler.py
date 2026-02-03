"""Centralized error handling for CLI commands."""

import asyncio
import functools
import sys
from loguru import logger
from mcp_code_intelligence.cli.output import console

def handle_cli_errors(func):
    """Decorator to handle CLI errors with helpful hints.
    
    Catches all unhandled exceptions during command execution and displays
    a user-friendly error message followed by recovery suggestions.
    Supports both sync and async command functions.
    """
    if asyncio.iscoroutinefunction(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                _print_help_and_exit(e, func.__name__)
        return async_wrapper
    else:
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                _print_help_and_exit(e, func.__name__)
        return sync_wrapper

def _print_help_and_exit(e: Exception, func_name: str):
    """Print error message and recovery hints before exiting.
    
    Args:
        e: The caught exception
        func_name: Name of the command function where it occurred
    """
    error_msg = str(e) or e.__class__.__name__
    
    # 1. Print visual error header
    console.print(f"\n[bold red]❌ Error:[/bold red] {error_msg}")
    
    # 2. Check for Git-specific errors (look for 'git' as a word or in class name)
    is_git_error = (
        "git" in error_msg.lower().split() or 
        "git" in e.__class__.__name__.lower() or
        "fatal: not a git repository" in error_msg.lower()
    )
    
    if is_git_error:
        console.print("\n[bold yellow]💡 Hint: Make sure you are running this command inside a valid Git repository.[/bold yellow]")
    
    # 3. Always provide the general system/index fix hint
    console.print("\n[bold yellow]💡 Hint: If you think there is an issue with system files or the index, try: mcp-code-intelligence setup --force[/bold yellow]")
    
    # Log the full traceback to debug logs (not visible in terminal unless -v is used)
    logger.debug(f"CLI Error in '{func_name}': {e}", exc_info=True)
    
    # Exit with failure code
    sys.exit(1)
