"""Core functionality for MCP Code Intelligence."""

from mcp_code_intelligence.core.git import (
    GitError,
    GitManager,
    GitNotAvailableError,
    GitNotRepoError,
    GitReferenceError,
)

__all__ = [
    "GitError",
    "GitManager",
    "GitNotAvailableError",
    "GitNotRepoError",
    "GitReferenceError",
]


