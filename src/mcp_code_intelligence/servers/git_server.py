"""Git MCP Server - Python implementation.

Provides Git repository operations via MCP protocol.
Uses GitPython library for Git interactions.
"""

import asyncio
import sys
from pathlib import Path
from typing import Any

from loguru import logger
logger.remove()

import logging
class InterceptHandler(logging.Handler):
    def emit(self, record):
        logger.opt(depth=6, exception=record.exc_info).log(record.levelname, record.getMessage())
logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO)

import builtins
_orig_print = builtins.print
def mcp_print(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    _orig_print(*args, **kwargs)
builtins.print = mcp_print

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from mcp_code_intelligence.core.llm_factory import wire_llm_to_server

try:
    import git
    from git import Repo, InvalidGitRepositoryError
except ImportError:
    git = None
    Repo = None
    InvalidGitRepositoryError = Exception


class GitServer:
    """MCP Server for Git operations."""

    def __init__(self, repository_path: Path | None = None):
        """Initialize Git server.

        Args:
            repository_path: Path to Git repository (default: current directory)
        """
        self.repo_path = Path(repository_path or Path.cwd()).resolve()
        self.server = Server("git")
        self._repo = None
        self._setup_handlers()

        # Setup activity logging
        try:
            from mcp_code_intelligence.core.logging_setup import setup_activity_logging
            setup_activity_logging(self.repo_path, "git")
        except Exception:
            pass

        # Wire LLM client if config has keys
        try:
            wire_llm_to_server(self, project_root=self.repo_path)
        except Exception:
            pass

    def _get_repo(self) -> Repo | None:
        """Get Git repository instance."""
        if git is None:
            return None

        if self._repo is None:
            try:
                self._repo = Repo(self.repo_path, search_parent_directories=True)
            except InvalidGitRepositoryError:
                return None
        return self._repo

    def _setup_handlers(self):
        """Setup MCP protocol handlers."""

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """List available Git tools."""
            return [
                Tool(
                    name="git_status",
                    description="Get Git repository status",
                    inputSchema={"type": "object", "properties": {}}
                ),
                Tool(
                    name="git_log",
                    description="Get Git commit history",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "max_count": {
                                "type": "number",
                                "description": "Maximum number of commits (default: 10)"
                            }
                        }
                    }
                ),
                Tool(
                    name="git_diff",
                    description="Show changes in working directory",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "cached": {
                                "type": "boolean",
                                "description": "Show staged changes (default: false)"
                            }
                        }
                    }
                ),
                Tool(
                    name="git_show",
                    description="Show commit details",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "commit": {
                                "type": "string",
                                "description": "Commit hash or reference (default: HEAD)"
                            }
                        }
                    }
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> list[TextContent]:
            """Handle tool calls."""
            from loguru import logger
            import json
            logger.info(f"🌿 [Git] {name} (Args: {json.dumps(arguments or {})[:100]}...)")

            if git is None:
                return [TextContent(
                    type="text",
                    text="Error: GitPython not installed. Run: pip install gitpython"
                )]

            repo = self._get_repo()
            if repo is None:
                return [TextContent(
                    type="text",
                    text=f"Error: Not a Git repository: {self.repo_path}"
                )]

            try:
                if name == "git_status":
                    # Get status
                    status_lines = []

                    # Changed files
                    changed = [item.a_path for item in repo.index.diff(None)]
                    if changed:
                        status_lines.append("Modified files:")
                        status_lines.extend(f"  M {f}" for f in changed)

                    # Staged files
                    staged = [item.a_path for item in repo.index.diff("HEAD")]
                    if staged:
                        status_lines.append("\nStaged files:")
                        status_lines.extend(f"  A {f}" for f in staged)

                    # Untracked files
                    untracked = repo.untracked_files
                    if untracked:
                        status_lines.append("\nUntracked files:")
                        status_lines.extend(f"  ? {f}" for f in untracked)

                    result = "\n".join(status_lines) if status_lines else "Working directory clean"
                    return [TextContent(type="text", text=result)]

                elif name == "git_log":
                    max_count = arguments.get("max_count", 10)
                    commits = list(repo.iter_commits(max_count=max_count))

                    log_lines = []
                    for commit in commits:
                        log_lines.append(f"commit {commit.hexsha[:8]}")
                        log_lines.append(f"Author: {commit.author.name} <{commit.author.email}>")
                        log_lines.append(f"Date:   {commit.committed_datetime}")
                        log_lines.append(f"\n    {commit.message.strip()}\n")

                    result = "\n".join(log_lines) if log_lines else "No commits"
                    return [TextContent(type="text", text=result)]

                elif name == "git_diff":
                    cached = arguments.get("cached", False)

                    if cached:
                        # Staged changes
                        diff = repo.index.diff("HEAD", create_patch=True)
                    else:
                        # Working directory changes
                        diff = repo.index.diff(None, create_patch=True)

                    if not diff:
                        return [TextContent(type="text", text="No changes")]

                    diff_text = "\n".join(str(d) for d in diff)
                    return [TextContent(type="text", text=diff_text)]

                elif name == "git_show":
                    commit_ref = arguments.get("commit", "HEAD")
                    commit = repo.commit(commit_ref)

                    show_lines = [
                        f"commit {commit.hexsha}",
                        f"Author: {commit.author.name} <{commit.author.email}>",
                        f"Date:   {commit.committed_datetime}",
                        f"\n    {commit.message.strip()}\n",
                        "\nChanges:",
                    ]

                    # Show changed files
                    if commit.parents:
                        diffs = commit.parents[0].diff(commit)
                        for diff in diffs:
                            change_type = diff.change_type
                            show_lines.append(f"  {change_type:6} {diff.a_path}")

                    result = "\n".join(show_lines)
                    return [TextContent(type="text", text=result)]

                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            except Exception as e:
                return [TextContent(type="text", text=f"Git error: {e}")]

    async def run(self):
        """Run the server using stdio transport."""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


def main():
    """Entry point for Git server."""
    repo_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()

    server = GitServer(repo_path)
    asyncio.run(server.run())


if __name__ == "__main__":
    main()


def get_advertised_tools(project_root: Path) -> list[Tool]:
    """Return lightweight advertised tools for the Git server (no instantiation)."""
    # Normalize project_root
    pr = Path(project_root) if project_root is not None else Path.cwd()

    # 1) Dependency check: ensure GitPython is available
    if git is None or Repo is None:
        return [
            Tool(
                name="fix_git_dependency_missing",
                description=(
                    "Git tools are unavailable because GitPython is not installed. "
                    "Install with: pip install GitPython"
                ),
                inputSchema={"type": "object", "properties": {}},
            )
        ]

    # 2) Repository check: ensure the provided project_root is inside a git repo
    try:
        # This will raise if not a repository (or if Repo isn't usable for this path)
        Repo(pr, search_parent_directories=True)
    except Exception:
        return [
            Tool(
                name="git_init_needed",
                description=(
                    "Current directory is not a Git repository. Run 'git init' in the project root "
                    "or open the repository root so Git tools become available."
                ),
                inputSchema={"type": "object", "properties": {}},
            )
        ]

    # 3) If dependencies and repository are present, advertise normal git tools.
    return [
        Tool(
            name="git_status",
            description="Get Git repository status (Modified, Staged, Untracked files)",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="git_log",
            description="Get Git commit history",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_count": {"type": "number", "description": "Maximum number of commits (default: 10)"}
                }
            },
        ),
        Tool(
            name="git_diff",
            description="Show changes in working directory",
            inputSchema={
                "type": "object",
                "properties": {"cached": {"type": "boolean", "description": "Show staged changes (default: false)"}}
            },
        ),
        Tool(
            name="git_show",
            description="Show commit details",
            inputSchema={
                "type": "object",
                "properties": {"commit": {"type": "string", "description": "Commit hash or reference (default: HEAD)"}}
            },
        ),
    ]
