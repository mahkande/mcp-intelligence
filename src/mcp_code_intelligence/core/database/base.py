"""Base interfaces and protocols for vector database operations."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from mcp_code_intelligence.core.models import CodeChunk, IndexStats, SearchResult


@runtime_checkable
class EmbeddingFunction(Protocol):
    """Protocol for embedding functions."""

    def __call__(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for input texts."""
        ...


class VectorDatabase(ABC):
    """Abstract interface for vector database operations."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the database connection and collections."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close database connections and cleanup resources."""
        ...

    @abstractmethod
    async def add_chunks(
        self, chunks: list[CodeChunk], metrics: dict[str, Any] | None = None
    ) -> None:
        """Add code chunks to the database with optional structural metrics.

        Args:
            chunks: List of code chunks to add
            metrics: Optional dict mapping chunk IDs to ChunkMetrics.to_metadata() dicts
        """
        ...

    @abstractmethod
    async def search(
        self,
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        similarity_threshold: float = 0.7,
    ) -> list[SearchResult]:
        """Search for similar code chunks.

        Args:
            query: Search query
            limit: Maximum number of results
            filters: Optional filters to apply
            similarity_threshold: Minimum similarity score

        Returns:
            List of search results
        """
        ...

    @abstractmethod
    async def delete_by_file(self, file_path: Path) -> int:
        """Delete all chunks for a specific file.

        Args:
            file_path: Path to the file

        Returns:
            Number of deleted chunks
        """
        ...

    @abstractmethod
    async def get_chunks_for_file(self, file_path: Path) -> list[CodeChunk]:
        """Get all chunks for a specific file.

        Args:
            file_path: Path to the file

        Returns:
            List of code chunks with metadata (including hash)
        """
        ...

    @abstractmethod
    async def get_hashes_for_file(self, file_path: Path) -> dict[str, str]:
        """Get only chunk IDs and their content hashes for a file.

        Optimized for incremental indexing to avoid loading full content.

        Args:
            file_path: Path to the file

        Returns:
            Dictionary mapping chunk_id -> content_hash
        """
        ...

    @abstractmethod
    async def delete_chunks(self, chunk_ids: list[str]) -> int:
        """Delete specific chunks by ID.

        Args:
            chunk_ids: List of chunk IDs to delete

        Returns:
            Number of deleted chunks
        """
        ...

    @abstractmethod
    async def get_stats(self) -> IndexStats:
        """Get database statistics.

        Returns:
            Index statistics
        """
        ...

    @abstractmethod
    async def reset(self) -> None:
        """Reset the database (delete all data)."""
        ...

    @abstractmethod
    async def get_all_chunks(self) -> list[CodeChunk]:
        """Get all chunks from the database.

        Returns:
            List of all code chunks with metadata
        """
        ...

    @abstractmethod
    async def get_chunks_by_symbol(
        self, symbol_name: str, symbol_type: str | None = None
    ) -> list[CodeChunk]:
        """Get code chunks by exact symbol name (class or function).

        Args:
            symbol_name: Exact name of the function or class
            symbol_type: Optional filter for chunk type (class, function, etc.)

        Returns:
            List of matching code chunks
        """
        ...

    @abstractmethod
    async def get_chunks_by_hash(self, content_hash: str) -> list[CodeChunk]:
        """Get chunks matching a content hash.

        Args:
            content_hash: MD5 content hash to lookup

        Returns:
            List of CodeChunk instances that match the content hash
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check database health and integrity.

        Returns:
            True if database is healthy, False otherwise
        """
        ...

    async def __aenter__(self) -> "VectorDatabase":
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()
