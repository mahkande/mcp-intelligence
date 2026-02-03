"""Async interfaces (protocols) for core services.

Defines lightweight async Protocols used to break apart the large
SemanticSearchEngine responsibilities into testable services.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable, Callable, Awaitable, Any

from mcp_code_intelligence.core.models import SearchResult


@runtime_checkable
class QueryProcessor(Protocol):
    """Preprocess and expand queries before they are sent to the DB."""

    async def process(self, query: str) -> str:
        """Return a normalized/expanded query string."""


@runtime_checkable
class RerankerService(Protocol):
    """Re-rank search results (neural or heuristic).

    Implementations should be safe to construct cheaply; heavy model
    loading should be done lazily inside the implementation.
    """

    async def rerank(self, results: list[SearchResult], query: str) -> list[SearchResult]:
        """Return a re-ordered list of `SearchResult` instances."""


@runtime_checkable
class ResilienceManager(Protocol):
    """Encapsulates retry / backoff / circuit-breaker logic for fragile ops."""

    async def execute(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> Any:
        """Execute `func(*args, **kwargs)` with resilience policies applied.

        Should raise the original exception if retries exhausted and the
        error is non-recoverable.
        """


@runtime_checkable
class ContextService(Protocol):
    """Provides file context enrichment and caching for search results."""

    async def get_context(self, result: SearchResult, include_context: bool) -> SearchResult:
        """Return an enhanced `SearchResult` with context_before/after and file_missing flags."""

    def clear_cache(self) -> None:
        """Clear any internal file caches held by the service."""

    def get_cache_info(self) -> dict[str, Any]:
        """Return cache statistics (hits, misses, size, maxsize, hit_rate)."""

