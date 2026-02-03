"""ChromaDB implementation with connection pooling for improved performance."""

import asyncio
import json
from pathlib import Path
from typing import Any

from loguru import logger

from mcp_code_intelligence.core.connection_pool import ChromaConnectionPool
from mcp_code_intelligence.core.exceptions import (
    DatabaseError,
    DocumentAdditionError,
    IndexCorruptionError,
    SearchError,
)
from mcp_code_intelligence.core.models import CodeChunk, IndexStats, SearchResult
from mcp_code_intelligence.core.database.base import VectorDatabase, EmbeddingFunction
from mcp_code_intelligence.core.database.chroma import ChromaVectorDatabase


class PooledChromaVectorDatabase(ChromaVectorDatabase):
    """ChromaDB implementation with connection pooling for improved performance.

    Inherits from ChromaVectorDatabase to reuse helper methods like _metadata_to_chunk,
    but overrides main methods to use the connection pool.
    """

    def __init__(
        self,
        persist_directory: Path,
        embedding_function: EmbeddingFunction,
        collection_name: str = "code_search",
        max_connections: int = 10,
        min_connections: int = 2,
        max_idle_time: float = 300.0,
        max_connection_age: float = 3600.0,
    ) -> None:
        """Initialize pooled ChromaDB vector database.

        Args:
            persist_directory: Directory to persist database
            embedding_function: Function to generate embeddings
            collection_name: Name of the collection
            max_connections: Maximum number of connections in pool
            min_connections: Minimum number of connections to maintain
            max_idle_time: Maximum time a connection can be idle (seconds)
            max_connection_age: Maximum age of a connection (seconds)
        """
        # Call parent init to set attributes
        super().__init__(persist_directory, embedding_function, collection_name)

        self._pool = ChromaConnectionPool(
            persist_directory=persist_directory,
            embedding_function=embedding_function,
            collection_name=collection_name,
            max_connections=max_connections,
            min_connections=min_connections,
            max_idle_time=max_idle_time,
            max_connection_age=max_connection_age,
        )

    async def initialize(self) -> None:
        """Initialize the connection pool."""
        await self._pool.initialize()
        logger.debug(f"Pooled ChromaDB initialized at {self.persist_directory}")

    async def close(self) -> None:
        """Close the connection pool."""
        await self._pool.close()
        logger.debug("Pooled ChromaDB connections closed")

    async def add_chunks(
        self, chunks: list[CodeChunk], metrics: dict[str, Any] | None = None
    ) -> None:
        """Add code chunks to the database using pooled connection with optional metrics.

        Args:
            chunks: List of code chunks to add
            metrics: Optional dict mapping chunk IDs to ChunkMetrics.to_metadata() dicts
        """
        if not chunks:
            return

        # Ensure pool is initialized
        if not self._pool._initialized:
            await self._pool.initialize()

        try:
            async with self._pool.get_connection() as conn:
                # Prepare data for ChromaDB
                documents = []
                metadatas = []
                ids = []

                for chunk in chunks:
                    # Store original content in documents (no metadata appended)
                    documents.append(chunk.content)

                    metadata = {
                        "file_path": str(chunk.file_path),
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "language": chunk.language,
                        "chunk_type": chunk.chunk_type,
                        "function_name": chunk.function_name or "",
                        "class_name": chunk.class_name or "",
                        "docstring": chunk.docstring or "",
                        "complexity_score": chunk.complexity_score,
                        # Hierarchy fields (convert lists to JSON strings for ChromaDB)
                        "chunk_id": chunk.chunk_id or "",
                        "parent_chunk_id": chunk.parent_chunk_id or "",
                        "child_chunk_ids": json.dumps(chunk.child_chunk_ids or []),
                        "chunk_depth": chunk.chunk_depth,
                        # Additional metadata (convert lists/dicts to JSON strings)
                        "decorators": json.dumps(chunk.decorators or []),
                        "parameters": json.dumps(chunk.parameters or []),
                        "return_type": chunk.return_type or "",
                        "type_annotations": json.dumps(chunk.type_annotations or {}),
                        # Monorepo support
                        "subproject_name": chunk.subproject_name or "",
                        "subproject_path": chunk.subproject_path or "",
                    }

                    # Merge structural metrics if provided
                    if metrics and chunk.chunk_id and chunk.chunk_id in metrics:
                        chunk_metrics = metrics[chunk.chunk_id]
                        metadata.update(chunk_metrics)

                    metadatas.append(metadata)
                    ids.append(chunk.id)

                # Add to collection
                conn.collection.add(documents=documents, metadatas=metadatas, ids=ids)

                logger.debug(f"Added {len(chunks)} chunks to database")

        except Exception as e:
            logger.error(f"Failed to add chunks: {e}")
            raise DocumentAdditionError(f"Failed to add chunks: {e}") from e

    async def search(
        self,
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        similarity_threshold: float = 0.7,
    ) -> list[SearchResult]:
        """Search for similar code chunks using pooled connection."""
        # Ensure pool is initialized
        if not self._pool._initialized:
            await self._pool.initialize()

        try:
            async with self._pool.get_connection() as conn:
                # Build where clause
                where_clause = self._build_where_clause(filters) if filters else None

                # Perform search
                results = conn.collection.query(
                    query_texts=[query],
                    n_results=limit,
                    where=where_clause,
                    include=["documents", "metadatas", "distances"],
                )

                # Process results
                search_results = []

                if results["documents"] and results["documents"][0]:
                    for i, (doc, metadata, distance) in enumerate(
                        zip(
                            results["documents"][0],
                            results["metadatas"][0],
                            results["distances"][0],
                            strict=False,
                        )
                    ):
                        # Convert distance to similarity (ChromaDB uses cosine distance)
                        # For cosine distance, use a more permissive conversion that handles distances > 1.0
                        # Convert to a 0-1 similarity score where lower distances = higher similarity
                        similarity = max(0.0, 1.0 / (1.0 + distance))

                        if similarity >= similarity_threshold:
                            # Document contains the original content (no metadata appended)
                            chunk_type_val = metadata.get("chunk_type", "code")
                            if chunk_type_val in ("function", "method"):
                                symbol_ctx = "function"
                            elif chunk_type_val == "class":
                                symbol_ctx = "class"
                            else:
                                symbol_ctx = "global"

                            navigation_hint_val = f"{metadata.get('file_path')}:{metadata.get('start_line')}"
                            # Build suggested next action linking to LSP tools
                            suggested_action = None
                            file_for_tool = metadata.get("file_path")
                            line_for_tool = metadata.get("start_line")
                            func_name = metadata.get("function_name")
                            cls_name = metadata.get("class_name")

                            if symbol_ctx == "function" and func_name:
                                suggested_action = {
                                    "tool": "find_references",
                                    "input": {"relative_path": str(file_for_tool), "line": int(line_for_tool), "character": 1},
                                    "message": f"You can use the 'find_references' tool to see the references of this function (e.g. {file_for_tool}:{line_for_tool}).",
                                }
                            elif symbol_ctx == "class" and cls_name:
                                suggested_action = {
                                    "tool": "find_references",
                                    "input": {"relative_path": str(file_for_tool), "line": int(line_for_tool), "character": 1},
                                    "message": f"You can use the 'find_references' tool to see the references of this class (e.g. {file_for_tool}:{line_for_tool}).",
                                }
                            else:
                                suggested_action = {
                                    "tool": "get_hover_info",
                                    "input": {"relative_path": str(file_for_tool), "line": int(line_for_tool), "character": 1},
                                    "message": f"You can inspect this location with the 'get_hover_info' tool for more information (e.g. {file_for_tool}:{line_for_tool}).",
                                }

                            result = SearchResult(
                                content=doc,
                                file_path=Path(metadata["file_path"]),
                                start_line=metadata["start_line"],
                                end_line=metadata["end_line"],
                                language=metadata["language"],
                                similarity_score=similarity,
                                rank=i + 1,
                                chunk_type=chunk_type_val,
                                function_name=metadata.get("function_name") or None,
                                class_name=metadata.get("class_name") or None,
                                symbol_context=symbol_ctx,
                                navigation_hint=navigation_hint_val,
                                suggested_next_action=suggested_action,
                            )
                            search_results.append(result)

                logger.debug(f"Found {len(search_results)} results for query: {query}")
                return search_results

        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise SearchError(f"Search failed: {e}") from e

    async def delete_by_file(self, file_path: Path) -> int:
        # Delete all chunks for a specific file using pooled connection.
        try:
            async with self._pool.get_connection() as conn:
                # Get all chunks for this file
                results = conn.collection.get(
                    where={"file_path": str(file_path)}, include=["metadatas"]
                )

                if not results["ids"]:
                    return 0

                # Delete the chunks
                conn.collection.delete(ids=results["ids"])

                deleted_count = len(results["ids"])
                logger.debug(f"Deleted {deleted_count} chunks for file: {file_path}")
                return deleted_count

        except Exception as e:
            logger.error(f"Failed to delete chunks for file {file_path}: {e}")
            raise DatabaseError(f"Failed to delete chunks: {e}") from e

    async def get_stats(self) -> IndexStats:
        # Get database statistics with connection pooling and chunked queries.
        try:
            async with self._pool.get_connection() as conn:
                # Get total count (fast operation)
                count = conn.collection.count()

                if count == 0:
                    return IndexStats(
                        total_files=0,
                        total_chunks=0,
                        languages={},
                        file_types={},
                        index_size_mb=0.0,
                        last_updated="N/A",
                        embedding_model="unknown",
                    )

                # Process in chunks to avoid loading everything at once
                batch_size_limit = 1000

                files = set()
                language_counts: dict[str, int] = {}
                file_type_counts: dict[str, int] = {}

                offset = 0
                while offset < count:
                    # Fetch batch
                    batch_size = min(batch_size_limit, count - offset)
                    logger.debug(
                        f"Processing database stats: batch {offset // batch_size_limit + 1}, "
                        f"{offset}-{offset + batch_size} of {count} chunks"
                    )

                    results = conn.collection.get(
                        include=["metadatas"],
                        limit=batch_size,
                        offset=offset,
                    )

                    # Process batch metadata
                    for metadata in results.get("metadatas", []):
                        # Language stats
                        lang = metadata.get("language", "unknown")
                        language_counts[lang] = language_counts.get(lang, 0) + 1

                        # File stats
                        file_path = metadata.get("file_path", "")
                        if file_path:
                            files.add(file_path)
                            ext = Path(file_path).suffix or "no_extension"
                            file_type_counts[ext] = file_type_counts.get(ext, 0) + 1

                    offset += batch_size

                    # Yield to event loop periodically to prevent blocking
                    await asyncio.sleep(0)

                # Estimate index size (rough approximation: ~1KB per chunk)
                index_size_mb = count * 0.001

                return IndexStats(
                    total_files=len(files),
                    total_chunks=count,
                    languages=language_counts,
                    file_types=file_type_counts,
                    index_size_mb=index_size_mb,
                    last_updated="unknown",
                    embedding_model="unknown",
                )

        except Exception as e:
            logger.error(f"Failed to get database statistics: {e}")
            # Return empty stats instead of raising
            return IndexStats(
                total_files=0,
                total_chunks=0,
                languages={},
                file_types={},
                index_size_mb=0.0,
                last_updated="error",
                embedding_model="unknown",
            )

    async def remove_file_chunks(self, file_path: str) -> int:
        # Remove all chunks for a specific file using pooled connection.
        try:
            async with self._pool.get_connection() as conn:
                # Get all chunks for this file
                results = conn.collection.get(where={"file_path": file_path})

                if not results["ids"]:
                    return 0

                # Delete the chunks
                conn.collection.delete(ids=results["ids"])

                return len(results["ids"])

        except Exception as e:
            logger.error(f"Failed to remove chunks for file {file_path}: {e}")
            return 0

    async def reset(self) -> None:
        # Reset the database using pooled connection.
        try:
            async with self._pool.get_connection() as conn:
                conn.client.reset()
                # Reinitialize the pool after reset
                await self._pool.close()
                await self._pool.initialize()
                logger.info("Database reset successfully")
        except Exception as e:
            logger.error(f"Failed to reset database: {e}")
            raise DatabaseError(f"Failed to reset database: {e}") from e

    async def get_all_chunks(self) -> list[CodeChunk]:
        # Get all chunks from the database using pooled connection.
        try:
            async with self._pool.get_connection() as conn:
                # Get all documents from collection
                results = conn.collection.get(include=["metadatas", "documents"])

                chunks = []
                if results and results.get("ids"):
                    for i, _chunk_id in enumerate(results["ids"]):
                        metadata = results["metadatas"][i]
                        content = results["documents"][i]
                        chunks.append(self._metadata_to_chunk(metadata, content))

                logger.debug(f"Retrieved {len(chunks)} chunks from database")
                return chunks

        except Exception as e:
            logger.error(f"Failed to get all chunks: {e}")
            raise DatabaseError(f"Failed to get all chunks: {e}") from e

    def get_pool_stats(self) -> dict[str, Any]:
        # Get connection pool statistics.
        return self._pool.get_stats()

    async def health_check(self) -> bool:
        # Perform a health check on the database and connection pool.
        try:
            # Check pool health
            pool_healthy = await self._pool.health_check()
            if not pool_healthy:
                return False

            # Try a simple query to verify database integrity
            try:
                async with self._pool.get_connection() as conn:
                    # Test basic operations
                    conn.collection.count()
                    conn.collection.query(
                        query_texts=["test"], n_results=1, include=["metadatas"]
                    )
                return True
            except Exception as e:
                error_msg = str(e).lower()
                if any(
                    indicator in error_msg
                    for indicator in [
                        "pickle",
                        "unpickling",
                        "eof",
                        "ran out of input",
                        "hnsw",
                        "index",
                        "deserialize",
                        "corrupt",
                    ]
                ):
                    logger.error(f"Index corruption detected: {e}")
                    # Attempt recovery
                    await self._recover_from_corruption()
                    return False
                else:
                    logger.warning(f"Health check failed: {e}")
                    return False
        except Exception as e:
            logger.error(f"Health check error: {e}")
            return False

    async def _recover_from_corruption(self) -> None:
        # Recover from index corruption by rebuilding the index.
        logger.info("Attempting to recover from index corruption...")

        # Close the pool first
        await self._pool.close()

        # Create backup directory
        backup_dir = (
            self.persist_directory.parent / f"{self.persist_directory.name}_backup"
        )
        backup_dir.mkdir(exist_ok=True)

        # Backup current state
        import time
        import shutil

        timestamp = int(time.time())
        backup_path = backup_dir / f"backup_{timestamp}"

        if self.persist_directory.exists():
            try:
                shutil.copytree(self.persist_directory, backup_path)
                logger.info(f"Created backup at {backup_path}")
            except Exception as e:
                logger.warning(f"Could not create backup: {e}")

        # Clear the corrupted index
        if self.persist_directory.exists():
            try:
                shutil.rmtree(self.persist_directory)
                logger.info(f"Cleared corrupted index at {self.persist_directory}")
            except Exception as e:
                logger.error(f"Failed to clear corrupted index: {e}")
                raise IndexCorruptionError(
                    f"Could not clear corrupted index: {e}"
                ) from e

        # Recreate the directory
        self.persist_directory.mkdir(parents=True, exist_ok=True)

        # Reinitialize the pool
        await self._pool.initialize()
        logger.info("Index recovered. Please re-index your codebase.")

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
