import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_code_intelligence.core.search import SemanticSearchEngine
from mcp_code_intelligence.core.services.resilience import (
    ServiceUnavailableError,
    SimpleResilienceManager,
)
from mcp_code_intelligence.core.models import SearchResult


@pytest.mark.asyncio
async def test_pipeline_calls_order_and_args():
    # Mocks
    db = MagicMock()
    # db.search must be awaitable
    sample_result = SearchResult(
        content="def foo(): pass",
        file_path=Path("/tmp/file.py"),
        start_line=1,
        end_line=1,
        language="python",
        similarity_score=0.5,
        rank=1,
    )
    db.search = AsyncMock(return_value=[sample_result])

    qp = AsyncMock()
    qp.process = AsyncMock(return_value="processed query")

    resilience = AsyncMock()

    async def _exec_side(fn, *a, **kw):
        # Execute the passed DB callable to simulate real flow
        return await fn()

    resilience.execute.side_effect = _exec_side

    reranker = AsyncMock()
    # Reranker should be called with the list of SearchResult and original query
    reranked = [sample_result]
    reranker.rerank = AsyncMock(return_value=reranked)

    engine = SemanticSearchEngine(database=db, project_root=Path("."),
                                  resilience_manager=resilience,
                                  reranker_service=reranker,
                                  query_processor=qp)

    results = await engine.search("my query", include_context=False)

    # Verify query processor called with original query
    qp.process.assert_awaited_once_with("my query")

    # Resilience manager executed once and was passed a callable
    resilience.execute.assert_awaited_once()
    called_arg = resilience.execute.call_args[0][0]
    assert callable(called_arg)

    # Reranker called with enhanced (unmodified) results and original query
    reranker.rerank.assert_awaited_once_with([sample_result], "my query")
    assert results == reranked


@pytest.mark.asyncio
async def test_resilience_service_unavailable_returns_empty():
    db = MagicMock()
    db.search = AsyncMock()

    qp = AsyncMock()
    qp.process = AsyncMock(return_value="p")

    resilience = AsyncMock()
    resilience.execute = AsyncMock(side_effect=ServiceUnavailableError("open"))

    reranker = AsyncMock()
    reranker.rerank = AsyncMock()

    engine = SemanticSearchEngine(database=db, project_root=Path("."),
                                  resilience_manager=resilience,
                                  reranker_service=reranker,
                                  query_processor=qp)

    results = await engine.search("q", include_context=False)
    assert results == []


@pytest.mark.asyncio
async def test_reranker_fallback_on_exception_returns_unranked():
    db = MagicMock()
    sample_result = SearchResult(
        content="x",
        file_path=Path("/tmp/a.py"),
        start_line=1,
        end_line=1,
        language="python",
        similarity_score=0.2,
        rank=1,
    )
    db.search = AsyncMock(return_value=[sample_result])

    qp = AsyncMock()
    qp.process = AsyncMock(return_value="p")

    async def _exec_side(fn, *a, **kw):
        return await fn()

    resilience = AsyncMock()
    resilience.execute.side_effect = _exec_side

    reranker = AsyncMock()
    reranker.rerank = AsyncMock(side_effect=Exception("boom"))

    engine = SemanticSearchEngine(database=db, project_root=Path("."),
                                  resilience_manager=resilience,
                                  reranker_service=reranker,
                                  query_processor=qp)

    results = await engine.search("q", include_context=False)
    # Should return the unranked/enhanced results (same as DB results here)
    assert isinstance(results, list)
    assert len(results) == 1
    assert results[0].content == sample_result.content


@pytest.mark.asyncio
async def test_default_constructor_initializes_defaults():
    db = MagicMock()
    db.search = AsyncMock(return_value=[])

    engine = SemanticSearchEngine(database=db, project_root=Path("."))

    # Defaults should be present
    assert hasattr(engine, "resilience_manager")
    assert isinstance(engine.resilience_manager, SimpleResilienceManager)
    assert hasattr(engine, "reranker_service")
    assert callable(getattr(engine.reranker_service, "rerank", None))
