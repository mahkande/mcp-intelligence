import shutil
import time
from pathlib import Path
from loguru import logger
from mcp_code_intelligence.core.project import ProjectManager
from mcp_code_intelligence.config.defaults import get_language_from_extension
from mcp_code_intelligence.cli.commands.install import detect_all_platforms

class DiscoveryManager:
    """Manages project analysis and environment discovery."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.project_manager = ProjectManager(project_root)

    def detect_languages(self) -> list[str]:
        """Detect project languages using ProjectManager."""
        return self.project_manager.detect_languages()

    def scan_file_extensions(self, timeout: float = 5.0) -> list[str] | None:
        """Scan project for unique file extensions with timeout.

        Optimized to skip ignored directories (node_modules, venv, etc.)
        to avoid timeouts on large projects.
        """
        import os
        extensions: set[str] = set()
        start_time = time.time()
        file_count = 0

        logger.debug(f"Starting optimized file scan in {self.project_root}")

        try:
            for root, dirs, files in os.walk(self.project_root, topdown=True):
                # Check timeout
                if time.time() - start_time > timeout:
                    logger.warning(f"File extension scan timed out after {timeout}s")
                    if extensions:
                        logger.info(f"Returning partial results: {len(extensions)} extensions found")
                        return sorted(extensions)
                    return None

                # Optimization: Filter directories IN-PLACE to skip ignored ones
                # This prevents os.walk from even entering these directories
                dirs[:] = [
                    d for d in dirs
                    if not self.project_manager._should_ignore_path(Path(root) / d, is_directory=True)
                ]

                for file in files:
                    file_path = Path(root) / file
                    
                    # Extension check
                    ext = file_path.suffix
                    if ext:
                        language = get_language_from_extension(ext)
                        if language != "text" or ext in [".txt", ".md", ".rst"]:
                            extensions.add(ext)
                    
                    file_count += 1
                    if file_count % 1000 == 0:
                        # Periodic timeout check for very large directories of files
                        if time.time() - start_time > timeout:
                            break

            logger.debug(f"Scan complete: {file_count} files searched, {len(extensions)} extensions found")
            return sorted(extensions) if extensions else None
        except Exception as e:
            logger.error(f"File extension scan failed: {e}")
            return None

    def detect_ai_platforms(self):
        """Detect installed MCP platforms."""
        return detect_all_platforms()

    def check_claude_cli(self) -> bool:
        """Check if Claude CLI is available."""
        return shutil.which("claude") is not None

    def check_uv(self) -> bool:
        """Check if uv is available."""
        return shutil.which("uv") is not None

    def is_idx(self) -> bool:
        """Detect if running in Google IDX environment."""
        import os
        return bool(os.getenv("IDX_WORKSPACE_ID") or (self.project_root / ".idx").exists())

    def is_vscode(self) -> bool:
        """Detect if proejct seems to be a VS Code/Copilot environment."""
        return (self.project_root / ".vscode").exists() or (self.project_root / ".github").exists()
