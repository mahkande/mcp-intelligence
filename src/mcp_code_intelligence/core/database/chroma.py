"""ChromaDB implementation of vector database."""

import asyncio
import json
from pathlib import Path
from typing import Any

import chromadb
from loguru import logger

from mcp_code_intelligence.core.exceptions import (
    DatabaseError,
    DatabaseInitializationError,
    DatabaseNotInitializedError,
    DocumentAdditionError,
    SearchError,
)
from mcp_code_intelligence.core.models import CodeChunk, IndexStats, SearchResult
from mcp_code_intelligence.core.database.base import VectorDatabase, EmbeddingFunction
from mcp_code_intelligence.core.database.recovery import DatabaseRecoveryMixin


class ChromaVectorDatabase(VectorDatabase, DatabaseRecoveryMixin):
    """ChromaDB implementation of vector database."""

    def __init__(
        self,
        persist_directory: Path,
        embedding_function: EmbeddingFunction,
        collection_name: str = "code_search",
    ) -> None:
        """Initialize ChromaDB vector database.

        Args:
            persist_directory: Directory to persist database
            embedding_function: Function to generate embeddings
            collection_name: Name of the collection
        """
        self.persist_directory = persist_directory
        self.embedding_function = embedding_function
        self.collection_name = collection_name
        self._client = None
        self._collection = None
        self._recovery_attempted = False  # Guard against infinite recursion

    async def initialize(self) -> None:
        """Initialize ChromaDB client and collection with corruption recovery."""
        try:
            # Ensure directory exists
            self.persist_directory.mkdir(parents=True, exist_ok=True)

            # LAYER 1: Check for corruption before initializing (SQLite + HNSW checks)
            await self._detect_and_recover_corruption()

            # LAYER 2: Wrap ChromaDB initialization with Rust panic detection
            try:
                # Create client with new API
                self._client = chromadb.PersistentClient(
                    path=str(self.persist_directory),
                    settings=chromadb.Settings(
                        anonymized_telemetry=False,
                        allow_reset=True,
                    ),
                )

                # Configure SQLite busy_timeout to prevent indefinite waits on locked database
                try:
                    chroma_db_path = self.persist_directory / "chroma.sqlite3"
                    if chroma_db_path.exists():
                        import sqlite3

                        temp_conn = sqlite3.connect(str(chroma_db_path))
                        temp_conn.execute("PRAGMA busy_timeout = 30000")  # 30 seconds
                        temp_conn.close()
                        logger.debug("Configured SQLite busy_timeout=30000ms")
                except Exception as e:
                    logger.warning(f"Failed to configure SQLite busy_timeout: {e}")

                # DEBUG: Inspect embedding_function before usage
                logger.info(f"DEBUG: embedding_function type: {type(self.embedding_function)}")
                logger.info(f"DEBUG: embedding_function is callable? {callable(self.embedding_function)}")
                
                # Create or get collection
                self._collection = self._client.get_or_create_collection(
                    name=self.collection_name,
                    embedding_function=self.embedding_function,
                    metadata={
                        "description": "Semantic code search collection",
                    },
                )

                # Reset recovery flag on successful initialization
                self._recovery_attempted = False

                logger.debug(f"ChromaDB initialized at {self.persist_directory}")

            except BaseException as init_error:
                # Re-raise system exceptions we should never catch
                if isinstance(
                    init_error, KeyboardInterrupt | SystemExit | GeneratorExit
                ):
                    raise

                # LAYER 2: Detect Rust panic patterns during initialization
                error_msg = str(init_error).lower()

                # Rust panic patterns (common ChromaDB Rust panics)
                rust_panic_patterns = [
                    "range start index",
                    "out of range",
                    "panic",
                    "thread panicked",
                    "slice of length",
                    "index out of bounds",
                ]

                if any(pattern in error_msg for pattern in rust_panic_patterns):
                    logger.warning(
                        f"Rust panic detected during ChromaDB initialization: {init_error}"
                    )
                    logger.info(
                        "Attempting automatic recovery from database corruption..."
                    )
                    await self._recover_from_corruption()

                    # Retry initialization ONCE after recovery
                    try:
                        logger.info(
                            "Retrying ChromaDB initialization after recovery..."
                        )
                        self._client = chromadb.PersistentClient(
                            path=str(self.persist_directory),
                            settings=chromadb.Settings(
                                anonymized_telemetry=False,
                                allow_reset=True,
                            ),
                        )

                        self._collection = self._client.get_or_create_collection(
                            name=self.collection_name,
                            embedding_function=self.embedding_function,
                            metadata={
                                "description": "Semantic code search collection",
                            },
                        )

                        logger.info("ChromaDB successfully initialized after recovery")

                    except BaseException as retry_error:
                        # Re-raise system exceptions
                        if isinstance(
                            retry_error, KeyboardInterrupt | SystemExit | GeneratorExit
                        ):
                            raise

                        logger.error(
                            f"Failed to recover from database corruption: {retry_error}"
                        )
                        # Mark recovery as attempted to prevent infinite loops
                        self._recovery_attempted = True
                        raise DatabaseError(
                            f"Failed to recover from database corruption. "
                            f"Please run 'mcp-code-intelligence reset index' to clear the database. "
                            f"Error: {retry_error}"
                        ) from retry_error
                else:
                    # Not a Rust panic, re-raise original exception
                    raise

        except (DatabaseError, DatabaseInitializationError):
            # Re-raise our own errors without re-processing
            raise
        except Exception as e:
            # Check if this is a corruption error (legacy detection for backward compatibility)
            error_msg = str(e).lower()
            corruption_indicators = [
                "pickle",
                "unpickling",
                "eof",
                "ran out of input",
                "hnsw",
                "index",
                "deserialize",
                "corrupt",
                "file is not a database",  # SQLite corruption
                "database error",  # ChromaDB database errors
            ]

            if any(indicator in error_msg for indicator in corruption_indicators):
                # Prevent infinite recursion - only attempt recovery once
                if self._recovery_attempted:
                    logger.error(
                        f"Recovery already attempted but corruption persists: {e}"
                    )
                    raise DatabaseInitializationError(
                        f"Failed to recover from database corruption. "
                        f"Please run 'mcp-code-intelligence reset index' to clear and rebuild the database. Error: {e}"
                    ) from e

                logger.warning(f"Detected index corruption: {e}")
                self._recovery_attempted = True

                # Try to recover
                await self._recover_from_corruption()

                # Retry initialization ONE TIME
                await self.initialize()
            else:
                logger.error(f"Failed to initialize ChromaDB: {e}")
                raise DatabaseInitializationError(
                    f"ChromaDB initialization failed: {e}"
                ) from e

    async def close(self) -> None:
        """Close database connections."""
        if self._client:
            # ChromaDB doesn't require explicit closing
            self._client = None
            self._collection = None
            logger.debug("ChromaDB connections closed")

    async def add_chunks(
        self, chunks: list[CodeChunk], metrics: dict[str, Any] | None = None
    ) -> None:
        """Add code chunks to the database with optional structural metrics.

        Args:
            chunks: List of code chunks to add
            metrics: Optional dict mapping chunk IDs to ChunkMetrics.to_metadata() dicts
                    Example: {"chunk_id_1": {"cognitive_complexity": 5, ...}, ...}
        """
        if not self._collection:
            raise DatabaseNotInitializedError("Database not initialized")

        if not chunks:
            return

        try:
            documents = []
            metadatas = []
            ids = []

            for chunk in chunks:
                # Store original content directly in documents (no metadata appended)
                # The embedding will be created from the original content
                documents.append(chunk.content)

                # Create metadata (searchable fields as metadata, not appended to content)
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
                    # Incremental indexing
                    "content_hash": chunk.content_hash or "",
                    # Contextual chunking fields
                    "parent_context": chunk.parent_context or "",
                    "breadcrumb": chunk.breadcrumb or "",
                    "context_prefix": chunk.context_prefix or "",
                    "nesting_level": chunk.nesting_level,
                }

                # Merge structural metrics if provided
                if metrics and chunk.chunk_id and chunk.chunk_id in metrics:
                    chunk_metrics = metrics[chunk.chunk_id]
                    metadata.update(chunk_metrics)

                metadatas.append(metadata)

                # Use chunk ID
                ids.append(chunk.id)

            # Upsert to collection (ensures overwriting if ID exists)
            self._collection.upsert(
                documents=documents,
                metadatas=metadatas,
                ids=ids,
            )

            logger.debug(f"Added {len(chunks)} chunks to database")

        except Exception as e:
            logger.error(f"Failed to add chunks: {e}")
            raise DocumentAdditionError(f"Failed to add chunks: {e}") from e

    def _build_where_clause(self, filters: dict[str, Any]) -> dict[str, Any] | None:
        """Build ChromaDB where clause from filters."""
        if not filters:
            return None

        # If filters already contain ChromaDB operators ($and, $or), pass through
        if "$and" in filters or "$or" in filters:
            return filters

        where = {}

        for key, value in filters.items():
            if isinstance(value, list):
                where[key] = {"$in": value}
            elif isinstance(value, str) and value.startswith("!"):
                where[key] = {"$ne": value[1:]}
            elif isinstance(value, dict):
                # Support operator queries like {"$gte": 10}
                where[key] = value
            else:
                where[key] = value

        return where

    async def search(
        self,
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        similarity_threshold: float = 0.7,
    ) -> list[SearchResult]:
        """Search for similar code chunks."""
        if not self._collection:
            raise DatabaseNotInitializedError("Database not initialized")

        try:
            # Build where clause
            where_clause = self._build_where_clause(filters) if filters else None

            # Perform search
            results = self._collection.query(
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
                        # Parse code smells from JSON if present
                        code_smells = []
                        if "code_smells" in metadata:
                            try:
                                code_smells = json.loads(metadata["code_smells"])
                            except (json.JSONDecodeError, TypeError):
                                code_smells = []

                        # Calculate quality score from metrics (0-100 scale)
                        quality_score = None
                        if (
                            "cognitive_complexity" in metadata
                            and "smell_count" in metadata
                        ):
                            # Simple quality score: penalize complexity and smells
                            complexity = metadata["cognitive_complexity"]
                            smells = metadata["smell_count"]

                            # Start with 100, penalize for complexity and smells
                            score = 100
                            # Complexity penalty: -2 points per complexity unit
                            score -= min(50, complexity * 2)
                            # Smell penalty: -10 points per smell
                            score -= min(30, smells * 10)

                            quality_score = max(0, score)

                        # Determine symbol context and editor navigation hint
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
                                "input": {
                                    "relative_path": str(file_for_tool),
                                    "line": int(line_for_tool),
                                    "character": 1,
                                },
                                "message": f"You can use the 'find_references' tool to see the references of this function (e.g. {file_for_tool}:{line_for_tool}).",
                            }
                        elif symbol_ctx == "class" and cls_name:
                            suggested_action = {
                                "tool": "find_references",
                                "input": {
                                    "relative_path": str(file_for_tool),
                                    "line": int(line_for_tool),
                                    "character": 1,
                                },
                                "message": f"You can use the 'find_references' tool to see the references of this class (e.g. {file_for_tool}:{line_for_tool}).",
                            }
                        else:
                            suggested_action = {
                                "tool": "get_hover_info",
                                "input": {
                                    "relative_path": str(file_for_tool),
                                    "line": int(line_for_tool),
                                    "character": 1,
                                },
                                "message": f"You can inspect this location with the 'get_hover_info' tool for more information (e.g. {file_for_tool}:{line_for_tool}).",
                            }

                        result = SearchResult(
                            content=doc,
                            file_path=Path(metadata["file_path"]),
                            start_line=metadata["start_line"],
                            end_line=metadata["end_line"],
                            language=metadata["language"],
                            content_hash=metadata.get("content_hash"),
                            similarity_score=similarity,
                            rank=i + 1,
                            chunk_type=chunk_type_val,
                            function_name=metadata.get("function_name") or None,
                            class_name=metadata.get("class_name") or None,
                            suggested_next_action=suggested_action,
                            symbol_context=symbol_ctx,
                            navigation_hint=navigation_hint_val,
                            # Quality metrics from structural analysis
                            cognitive_complexity=metadata.get("cognitive_complexity"),
                            cyclomatic_complexity=metadata.get("cyclomatic_complexity"),
                            max_nesting_depth=metadata.get("max_nesting_depth"),
                            parameter_count=metadata.get("parameter_count"),
                            lines_of_code=metadata.get("lines_of_code"),
                            complexity_grade=metadata.get("complexity_grade"),
                            code_smells=code_smells,
                            smell_count=metadata.get("smell_count"),
                            quality_score=quality_score,
                            # Contextual chunking fields
                            parent_context=metadata.get("parent_context"),
                            breadcrumb=metadata.get("breadcrumb"),
                            nesting_level=metadata.get("nesting_level", 0),
                        )
                        search_results.append(result)

            logger.debug(f"Found {len(search_results)} results for query: {query}")
            return search_results

        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise SearchError(f"Search failed: {e}") from e

    async def delete_by_file(self, file_path: Path) -> int:
        """Delete all chunks for a specific file."""
        if not self._collection:
            raise DatabaseNotInitializedError("Database not initialized")

        try:
            # Get all chunks for this file
            results = self._collection.get(
                where={"file_path": str(file_path)},
                include=["metadatas"],
            )

            if results["ids"]:
                self._collection.delete(ids=results["ids"])
                count = len(results["ids"])
                logger.debug(f"Deleted {count} chunks for {file_path}")
                return count

            return 0

        except Exception as e:
            logger.error(f"Failed to delete chunks for {file_path}: {e}")
            raise DatabaseError(f"Failed to delete chunks: {e}") from e

    async def get_chunks_for_file(self, file_path: Path) -> list[CodeChunk]:
        """Get all chunks for a specific file."""
        if not self._collection:
            raise DatabaseNotInitializedError("Database not initialized")

        try:
            results = self._collection.get(
                where={"file_path": str(file_path)},
                include=["metadatas", "documents"],
            )

            chunks = []
            if results and results.get("ids"):
                for i, _ in enumerate(results["ids"]):
                    metadata = results["metadatas"][i]
                    content = results["documents"][i]
                    chunks.append(self._metadata_to_chunk(metadata, content))

            return chunks

        except Exception as e:
            logger.error(f"Failed to get chunks for file {file_path}: {e}")
            return []

    async def get_hashes_for_file(self, file_path: Path) -> dict[str, str]:
        """Get only chunk IDs and their content hashes for a file."""
        if not self._collection:
            raise DatabaseNotInitializedError("Database not initialized")

        try:
            # Only fetch metadatas, skip heavy documents
            results = self._collection.get(
                where={"file_path": str(file_path)},
                include=["metadatas"],
            )

            hashes = {}
            if results and results.get("ids"):
                for i, chunk_id in enumerate(results["ids"]):
                    metadata = results["metadatas"][i] or {}
                    # If content_hash is missing (legacy chunk), use empty string
                    # This ensures it's captured in old_hash_map and will be updated/deleted
                    hashes[chunk_id] = metadata.get("content_hash", "")

            return hashes

        except Exception as e:
            logger.error(f"Failed to get hashes for file {file_path}: {e}")
            return {}

    async def delete_chunks(self, chunk_ids: list[str]) -> int:
        """Delete specific chunks by ID."""
        if not self._collection:
            raise DatabaseNotInitializedError("Database not initialized")

        if not chunk_ids:
            return 0

        try:
            self._collection.delete(ids=chunk_ids)
            logger.debug(f"Deleted {len(chunk_ids)} chunks")
            return len(chunk_ids)
        except Exception as e:
            logger.error(f"Failed to delete chunks: {e}")
            # Don't raise, just log error and return 0
            return 0

    async def get_stats(self, skip_stats: bool = False) -> IndexStats:
        """Get database statistics with optimized chunked queries.

        Args:
            skip_stats: If True, skip detailed stats on large DBs to prevent crashes.
        """
        if not self._collection:
            raise DatabaseNotInitializedError("Database not initialized")

        try:
            # SAFETY CHECK: Detect large databases before calling count()
            # ChromaDB's Rust backend can segfault on large databases (>500MB)
            chroma_db_path = self.persist_directory / "chroma.sqlite3"
            db_size_mb = 0.0
            db_size_bytes = 0

            if chroma_db_path.exists():
                db_size_bytes = chroma_db_path.stat().st_size
                db_size_mb = db_size_bytes / (1024 * 1024)

                # Automatically enable safe mode for large databases
                if db_size_mb > 500 and not skip_stats:
                    logger.warning(
                        f"Large database detected ({db_size_mb:.1f} MB). "
                        "Skipping detailed statistics to prevent potential crashes."
                    )
                    skip_stats = True

            # If skip_stats is enabled, return minimal safe stats
            if skip_stats:
                return IndexStats(
                    total_files=0,
                    total_chunks=0, # Changed from string to int 0 to match type hint if needed, or update type hint. Models probably expects int.
                    languages={},
                    file_types={},
                    index_size_mb=db_size_mb,
                    last_updated="Skipped (large database)",
                    embedding_model="unknown",
                    database_size_bytes=db_size_bytes,
                )

            # Get total count (fast operation, but can crash on large DBs)
            count = self._collection.count()

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

                results = self._collection.get(
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

    async def get_chunks_by_symbol(
        self, symbol_name: str, symbol_type: str | None = None
    ) -> list[CodeChunk]:
        """Get chunks by exact symbol name using ChromaDB filtering."""
        if not self._collection:
            raise DatabaseNotInitializedError("Database not initialized")

        try:
            # Build where clause for symbol lookup
            where = {
                "$or": [{"function_name": symbol_name}, {"class_name": symbol_name}]
            }

            if symbol_type:
                where = {"$and": [where, {"chunk_type": symbol_type}]}

            results = self._collection.get(
                where=where, include=["metadatas", "documents"]
            )

            chunks = []
            if results and results.get("ids"):
                for i, _ in enumerate(results["ids"]):
                    metadata = results["metadatas"][i]
                    content = results["documents"][i]
                    chunks.append(self._metadata_to_chunk(metadata, content))

            return chunks
        except Exception as e:
            logger.error(f"Symbol lookup failed for {symbol_name}: {e}")
            return []

    async def get_chunks_by_hash(self, content_hash: str) -> list[CodeChunk]:
        """Return chunks that match the provided content_hash."""
        if not self._collection:
            raise DatabaseNotInitializedError("Database not initialized")

        try:
            results = self._collection.get(
                where={"content_hash": content_hash}, include=["metadatas", "documents"]
            )

            chunks: list[CodeChunk] = []
            if results and results.get("ids"):
                for i, _ in enumerate(results["ids"]):
                    metadata = results["metadatas"][i]
                    content = results["documents"][i]
                    chunks.append(self._metadata_to_chunk(metadata, content))

            return chunks

        except Exception as e:
            logger.error(f"Failed to lookup chunks by hash {content_hash}: {e}")
            return []

    def _metadata_to_chunk(self, metadata: dict, content: str) -> CodeChunk:
        """Helper to convert ChromaDB metadata back to CodeChunk."""
        # Parse JSON strings back to lists/dicts
        child_chunk_ids = metadata.get("child_chunk_ids", "[]")
        if isinstance(child_chunk_ids, str):
            try:
                child_chunk_ids = json.loads(child_chunk_ids)
            except json.JSONDecodeError:
                child_chunk_ids = []

        decorators = metadata.get("decorators", "[]")
        if isinstance(decorators, str):
            try:
                decorators = json.loads(decorators)
            except json.JSONDecodeError:
                decorators = []

        parameters = metadata.get("parameters", "[]")
        if isinstance(parameters, str):
            try:
                parameters = json.loads(parameters)
            except json.JSONDecodeError:
                parameters = []

        type_annotations = metadata.get("type_annotations", "{}")
        if isinstance(type_annotations, str):
            try:
                type_annotations = json.loads(type_annotations)
            except json.JSONDecodeError:
                type_annotations = {}

        return CodeChunk(
            content=content,
            file_path=Path(metadata["file_path"]),
            start_line=metadata["start_line"],
            end_line=metadata["end_line"],
            language=metadata["language"],
            chunk_type=metadata.get("chunk_type", "code"),
            function_name=metadata.get("function_name") or None,
            class_name=metadata.get("class_name") or None,
            docstring=metadata.get("docstring") or None,
            complexity_score=metadata.get("complexity_score", 0.0),
            chunk_id=metadata.get("chunk_id"),
            parent_chunk_id=metadata.get("parent_chunk_id"),
            child_chunk_ids=child_chunk_ids,
            chunk_depth=metadata.get("chunk_depth", 0),
            decorators=decorators,
            parameters=parameters,
            return_type=metadata.get("return_type"),
            type_annotations=type_annotations,
            subproject_name=metadata.get("subproject_name"),
            subproject_path=metadata.get("subproject_path"),
            content_hash=metadata.get("content_hash"),
        )

    async def reset(self) -> None:
        """Reset the database."""
        if self._client:
            try:
                self._client.reset()
                # Recreate collection
                await self.initialize()
                logger.info("Database reset successfully")
            except Exception as e:
                logger.error(f"Failed to reset database: {e}")
                raise DatabaseError(f"Failed to reset database: {e}") from e

    async def get_all_chunks(self) -> list[CodeChunk]:
        """Get all chunks from the database.

        Returns:
            List of all code chunks with metadata
        """
        if not self._collection:
            raise DatabaseNotInitializedError("Database not initialized")

        try:
            # Get all documents from collection
            results = self._collection.get(include=["metadatas", "documents"])

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

    async def health_check(self) -> bool:
        """Check database health and integrity."""
        try:
            # First check if client is initialized
            if not self._client or not self._collection:
                logger.warning("Database not initialized")
                return False

            # Try a simple operation to test the connection
            try:
                # Attempt to get count - this will fail if index is corrupted
                count = self._collection.count()
                logger.debug(f"Health check passed: {count} chunks in database")

                # Try a minimal query to ensure search works
                self._collection.query(
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
                    logger.error(f"Index corruption detected during health check: {e}")
                    return False
                else:
                    # Some other error
                    logger.warning(f"Health check failed: {e}")
                    return False

        except Exception as e:
            logger.error(f"Health check error: {e}")
            return False
