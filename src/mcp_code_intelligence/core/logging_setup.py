import os
from pathlib import Path
from loguru import logger
import sys

def setup_activity_logging(project_root: Path, server_name: str) -> None:
    """Setup logging to activity.log for HUD monitoring.
    
    Args:
        project_root: Project root directory
        server_name: Name of the server for log identification
    """
    try:
        # CRITICAL FIX: Do NOT remove existing handlers. The main server process (fast_server.py)
        # has already configured stderr logging and file logging. Removing them here causes
        # a deadlock or race condition.
        
        # logger.remove()  <-- THIS WAS THE CAUSE OF THE HANG
        
        log_dir = Path(project_root) / ".mcp-code-intelligence" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "activity.log"

        # Check if we already have a file handler for this file to avoid duplication
        # (This is a simplified check; loguru dedups nicely usually, but safety first)
        
        # Add file logger (keep last 5MB of logs, rotation)
        logger.add(
            log_file,
            rotation="5 MB",
            retention="1 week",
            level="INFO",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | [" + server_name + "] {message}",
            enqueue=True # Safe for multi-process
        )
        
        # We generally do not need to add stderr again as fast_server.py does it.
        # Adding it again might cause double logging, but is safer than removing everything.
        
        logger.info(f"--- {server_name} Activity Logging Initialized ---")
    except Exception as e:
        # Fallback to stderr if file logging fails
        # Use sys.stderr.write directly to avoid recursion issues if logger is broken
        sys.stderr.write(f"Critical: Could not setup activity logging for {server_name}: {str(e)}\n")
