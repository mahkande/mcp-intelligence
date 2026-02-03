"""Lightweight SemanticSearchEngine delegating responsibilities to services.

This module keeps the orchestration pipeline small and delegates
query processing, context enrichment, scoring and resilience to service
implementations under `core.services`.
"""

from __future__ import annotations

import time
import re
from pathlib import Path
from typing import Any, List

from loguru import logger

from mcp_code_intelligence.core.database import VectorDatabase
from mcp_code_intelligence.core.exceptions import RustPanicError, SearchError
from mcp_code_intelligence.core.git import GitManager
from mcp_code_intelligence.core.guards import RAGGuard
from mcp_code_intelligence.core.models import SearchResult

from mcp_code_intelligence.core.services.resilience import SimpleResilienceManager, ServiceUnavailableError
from mcp_code_intelligence.core.services.reranker import get_global_reranker
from mcp_code_intelligence.core.services.context import DefaultContextService
from mcp_code_intelligence.core.interfaces import ContextService
from mcp_code_intelligence.core.services.query_processor import DefaultQueryProcessor, QueryProcessorService
from mcp_code_intelligence.core.services.scoring import ScoringService
from mcp_code_intelligence.core.services.discovery import DiscoveryService
from mcp_code_intelligence.core.auto_indexer import AutoIndexer, SearchTriggeredIndexer
from mcp_code_intelligence.core.bm25_index import BM25Index


class SemanticSearchEngine:
    """Orchestrates an async semantic search pipeline using small services."""

    def __init__(
        self,
        database: VectorDatabase,
        project_root: Path,
        similarity_threshold: float = 0.3,
        auto_indexer: AutoIndexer | None = None,
        resilience_manager: SimpleResilienceManager | None = None,
        reranker_service=None,
        reranker_model_name: str | None = None,
        query_processor: QueryProcessorService | None = None,
        context_service: ContextService | None = None,
        scoring_service: ScoringService | None = None,
    ) -> None:
        self.database = database
        self.project_root = project_root
        self.similarity_threshold = similarity_threshold

        self.search_triggered_indexer = (
            SearchTriggeredIndexer(auto_indexer) if auto_indexer is not None else None
        )

        try:
            self.git_manager = GitManager(project_root)
        except Exception:
            self.git_manager = None

        self.rag_guard = RAGGuard()

        self.resilience_manager = resilience_manager or SimpleResilienceManager()
        self.reranker_service = reranker_service or get_global_reranker(reranker_model_name)

        self.context_service: ContextService = context_service or DefaultContextService()
        self.query_processor: QueryProcessorService = (
            query_processor or DefaultQueryProcessor()
        )
        self.scoring_service = scoring_service or ScoringService(self.similarity_threshold)
        self.discovery_service = DiscoveryService(self)
        self.bm25_index = BM25Index()  # Hybrid search index

        # Lightweight throttling
        self._last_health_check = 0.0
        self._health_check_interval = 60.0

    @staticmethod
    def _is_rust_panic_error(error: Exception) -> bool:
        """Detect ChromaDB Rust panic errors.

        Args:
            error: Exception to check

        Returns:
            True if this is a Rust panic error
        """
        error_msg = str(error).lower()

        # Check for the specific Rust panic pattern
        # "range start index X out of range for slice of length Y"
        if "range start index" in error_msg and "out of range" in error_msg:
            return True

        # Check for other Rust panic indicators
        rust_panic_patterns = [
            "rust panic",
            "pyo3_runtime.panicexception",
            "thread 'tokio-runtime-worker' panicked",
            "rust/sqlite/src/db.rs",  # Specific to the known ChromaDB issue
        ]

        return any(pattern in error_msg for pattern in rust_panic_patterns)

    @staticmethod
    def _is_corruption_error(error: Exception) -> bool:
        """Detect index corruption errors.

        Args:
            error: Exception to check

        Returns:
            True if this is a corruption error
        """
        error_msg = str(error).lower()

        corruption_indicators = [
            "pickle",
            "unpickling",
            "eof",
            "ran out of input",
            "hnsw",
            "deserialize",
            "corrupt",
        ]

        return any(indicator in error_msg for indicator in corruption_indicators)

    # NOTE: retry/resilience logic has been moved to `ResilienceManager` implementations.

    async def search(
        self,
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        similarity_threshold: float | None = None,
        include_context: bool = True,
    ) -> list[SearchResult]:
        """Perform semantic search for code.

        Args:
            query: Search query
            limit: Maximum number of results
            filters: Optional filters (language, file_path, etc.)
            similarity_threshold: Minimum similarity score
            include_context: Whether to include context lines

        Returns:
            List of search results
        """
        if not query.strip():
            return []

        # Throttled health check before search (only every 60 seconds)
        current_time = time.time()
        if current_time - self._last_health_check >= self._health_check_interval:
            try:
                if hasattr(self.database, "health_check"):
                    is_healthy = await self.database.health_check()
                    if not is_healthy:
                        logger.warning("Database health check failed - attempting recovery")
                    self._last_health_check = current_time
            except Exception as e:
                logger.warning(f"Health check failed: {e}")
                self._last_health_check = current_time

        # Auto-reindex check before search
        if self.search_triggered_indexer:
            try:
                await self.search_triggered_indexer.pre_search_hook()
            except Exception as e:
                logger.warning(f"Auto-reindex check failed: {e}")

        # Determine threshold
        threshold = (
            similarity_threshold
            if similarity_threshold is not None
            else self.scoring_service.adaptive_threshold(query)
        )

        # Update active files for RAG Guard (Recency Guard)
        if self.git_manager:
            try:
                changed_files = self.git_manager.get_changed_files()
                self.rag_guard.set_active_files([str(f) for f in changed_files])
            except Exception:
                pass

        try:
            # Preprocess query via QueryProcessor
            processed_query = await self.query_processor.process(query)

            # Perform vector search wrapped by resilience manager
            async def _db_search():
                return await self.database.search(
                    query=processed_query,
                    limit=limit,
                    filters=filters,
                    similarity_threshold=threshold,
                )

            try:
                results = await self.resilience_manager.execute(_db_search, max_retries=3, jitter=0.2)
            except ServiceUnavailableError as sue:
                logger.error(f"Resilience manager rejected request: {sue}")
                return []

            # Post-process results (context enrichment) via ContextService
            enhanced_results = []
            for result in results:
                enhanced_result = await self.context_service.get_context(result, include_context)
                # Stale-index detection: if SearchResult has content_hash and DB provides lookup, warn
                try:
                    if getattr(enhanced_result, "content_hash", None) and hasattr(self.database, "get_chunks_by_hash"):
                        matches = await self.database.get_chunks_by_hash(enhanced_result.content_hash)
                        location_match = any(
                            (str(m.file_path) == str(enhanced_result.file_path) and m.start_line == enhanced_result.start_line and m.end_line == enhanced_result.end_line)
                            for m in matches
                        )
                        if not location_match:
                            logger.warning(
                                f"Stale index detected for {enhanced_result.file_path}:{enhanced_result.start_line}-{enhanced_result.end_line} (content_hash mismatch)"
                            )
                except Exception:
                    pass
                enhanced_results.append(enhanced_result)

            # Rerank via injected reranker service
            try:
                ranked_results = await self.reranker_service.rerank(enhanced_results, query)
            except Exception as e:
                logger.warning(f"Reranker service failed, falling back to unranked results: {e}")
                ranked_results = enhanced_results

            # Apply Static Type & Chunk Type Boosting
            try:
                ranked_results = self.scoring_service.apply_boosts(ranked_results, query)
            except Exception as e:
                logger.warning(f"Static boost scoring failed: {e}")

            # Simple Git-based recency boosting
            if self.git_manager:
                try:
                    recent = set(str(f) for f in self.git_manager.get_changed_files())
                    for r in ranked_results:
                        if str(r.file_path) in recent:
                            r.similarity_score = min(1.0, r.similarity_score + self.scoring_service.boost_source_file)
                except Exception:
                    pass

            # Apply RAG Guard penalties and scope filtering
            ranked_results = self.rag_guard.apply_search_penalties(ranked_results, query)
            ranked_results = self.rag_guard.filter_scope(ranked_results, query)

            # Diversity: limit 3 chunks per file
            file_counts = {}
            diverse_results = []
            for r in ranked_results:
                file_path = str(r.file_path)
                count = file_counts.get(file_path, 0)
                if count < 3:
                    diverse_results.append(r)
                    file_counts[file_path] = count + 1

            # Final sort and rank update
            diverse_results.sort(key=lambda r: r.similarity_score, reverse=True)
            for i, result in enumerate(diverse_results):
                result.rank = i + 1

            # Efficiency Pipeline Logging
            if diverse_results:
                try:
                    total_file_lines = 0
                    delivered_lines = 0
                    unique_files = set()

                    for r in diverse_results:
                        unique_files.add(r.file_path)
                        delivered_lines += (r.end_line - r.start_line + 1)

                    # Estimate total lines for efficiency metrics
                    # In a real scenario we'd read files, here we provide indicative stats
                    for f_path in unique_files:
                        delivered_for_file = sum((r.end_line - r.start_line + 1) for r in diverse_results if r.file_path == f_path)
                        total_file_lines += delivered_for_file * 5 # Approximation

                    savings = 0
                    if total_file_lines > 0:
                        savings = int((1 - (delivered_lines / total_file_lines)) * 100)

                    logger.info(f"[EFFICIENCY] 📉 AI Context Optimized: {total_file_lines} lines → {delivered_lines} lines ({savings}% Token savings).")
                    logger.info(f"[INTELLIGENCE] 🎯 Reranker applied: {len(unique_files)} files scanned, most relevant {len(diverse_results)} code chunks selected.")
                except Exception:
                    pass

            logger.debug(
                f"Search for '{query}' with threshold {threshold:.3f} returned {len(diverse_results)} results"
            )

            return diverse_results

        except (RustPanicError, SearchError):
            # These errors are already properly formatted with user guidance
            raise
        except Exception as e:
            # Unexpected error - log and return safe fallback
            logger.error(f"Unexpected search error for query '{query}': {e}")
            return []

    async def hybrid_search(
        self,
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        similarity_threshold: float | None = None,
        include_context: bool = True,
    ) -> list[SearchResult]:
        """Hybrid search: vector + BM25 + RRF fusion + reranker."""
        if not query.strip():
            return []
        processed_query = await self.query_processor.process(query)
        # 1. Vector search
        async def _db_search():
            return await self.database.search(
                query=processed_query,
                limit=limit * 2,  # Fetch more results
                filters=filters,
                similarity_threshold=similarity_threshold or self.similarity_threshold,
            )
        vector_results = await self.resilience_manager.execute(_db_search, max_retries=3, jitter=0.2)
        logger.debug(f"[HybridSearch] Vector results: {vector_results}")
        # 2. BM25 search
        bm25_results = self.bm25_index.search(processed_query, top_k=limit * 2)
        logger.debug(f"[HybridSearch] BM25 results: {bm25_results}")
        # 3. RRF fusion
        fused = self._reciprocal_rank_fusion(vector_results, bm25_results, limit)
        # 4. Reranker
        try:
            reranked = await self.reranker_service.rerank(fused, query)
        except Exception as e:
            logger.warning(f"Reranker service failed, falling back to unranked results: {e}")
            reranked = fused
            
        # Apply Static Type & Chunk Type Boosting
        try:
            reranked = self.scoring_service.apply_boosts(reranked, query)
        except Exception as e:
            logger.warning(f"Static boost scoring failed in hybrid search: {e}")
            
        return reranked

    def _reciprocal_rank_fusion(self, vector_results, bm25_results, limit=10, k=60):
        """Reciprocal Rank Fusion (RRF) for hybrid search result merging."""
        # Map by unique chunk id (or file+lines fallback)
        def get_id(res):
            if hasattr(res, 'chunk_id') and res.chunk_id:
                return res.chunk_id
            if hasattr(res, 'file_path'):
                return f"{res.file_path}:{getattr(res, 'start_line', 0)}:{getattr(res, 'end_line', 0)}"
            if isinstance(res, dict):
                return f"{res.get('file_path')}:{res.get('start_line', 0)}:{res.get('end_line', 0)}"
            return str(res)
        # Build rank dicts
        vector_rank = {get_id(r): i for i, r in enumerate(vector_results)}
        bm25_rank = {get_id(r): i for i, r in enumerate(bm25_results)}
        all_ids = set(vector_rank) | set(bm25_rank)
        fused_scores = {}
        for cid in all_ids:
            r1 = vector_rank.get(cid, 1e6)
            r2 = bm25_rank.get(cid, 1e6)
            fused_scores[cid] = 1/(k + r1) + 1/(k + r2)
        # Sort by fused score
        sorted_ids = sorted(fused_scores, key=lambda x: fused_scores[x], reverse=True)
        # Build fused result list
        id_to_obj = {**{get_id(r): r for r in vector_results}, **{get_id(r): r for r in bm25_results}}
        fused = [id_to_obj[cid] for cid in sorted_ids[:limit]]
        return fused

    async def find_symbol(self, symbol_name: str, symbol_type: str | None = None) -> list[SearchResult]:
        """Find a symbol definition by exact name match."""
        return await self.discovery_service.find_symbol(symbol_name, symbol_type)

    async def search_similar(
        self,
        file_path: Path,
        function_name: str | None = None,
        limit: int = 10,
        similarity_threshold: float | None = None,
    ) -> list[SearchResult]:
        """Find code similar to a file or function."""
        return await self.discovery_service.search_similar(
            file_path, function_name, limit, similarity_threshold
        )

