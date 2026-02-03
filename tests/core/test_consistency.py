import asyncio
import json
from pathlib import Path

import pytest
from unittest.mock import AsyncMock

from mcp_code_intelligence.utils.hash_utils import get_content_hash
from mcp_code_intelligence.core.models import CodeChunk, SearchResult
from mcp_code_intelligence.core.relationships import RelationshipStore
from mcp_code_intelligence.core.search import SemanticSearchEngine


@pytest.mark.asyncio
async def test_get_content_hash_deterministic():
    text = "def foo():\n    return 42"
    h1 = await get_content_hash(text)
    h2 = await get_content_hash(text)
    assert h1 == h2
    assert len(h1) == 32  # MD5 hex length

    other = "def bar():\n    return 1"
    h3 = await get_content_hash(other)
    assert h3 != h1


@pytest.mark.asyncio
async def test_relationship_store_skips_unchanged_chunks(tmp_path):
    # Prepare two chunks in different files
    f1 = tmp_path / "f1.py"
    f2 = tmp_path / "f2.py"
    f1.write_text("def a():\n    return 1")
    f2.write_text("def b():\n    return 2")

    chunk1 = CodeChunk(
        content=f1.read_text(),
        file_path=f1,
        start_line=1,
        end_line=1,
        language="python",
        chunk_type="function",
        function_name="a",
    )
    chunk2 = CodeChunk(
        content=f2.read_text(),
        file_path=f2,
        start_line=1,
        end_line=1,
        language="python",
        chunk_type="function",
        function_name="b",
    )

    store = RelationshipStore(tmp_path)

    # Mock database for first run: no hashes present, search will be called
    db1 = AsyncMock()
    async def search_side_effect(query, limit=10, filters=None, similarity_threshold=0.7):
        # Return the other chunk as similar
        if "def a" in query:
            return [
                SearchResult(
                    content=chunk2.content,
                    file_path=chunk2.file_path,
                    start_line=chunk2.start_line,
                    end_line=chunk2.end_line,
                    language=chunk2.language,
                    similarity_score=0.9,
                    rank=1,
                )
            ]
        else:
            return [
                SearchResult(
                    content=chunk1.content,
                    file_path=chunk1.file_path,
                    start_line=chunk1.start_line,
                    end_line=chunk1.end_line,
                    language=chunk1.language,
                    similarity_score=0.9,
                    rank=1,
                )
            ]

    db1.get_hashes_for_file = AsyncMock(return_value={})
    db1.search = AsyncMock(side_effect=search_side_effect)

    # First compute - should call search
    res1 = await store.compute_and_store([chunk1, chunk2], db1)
    assert db1.search.await_count >= 1
    assert Path(store.store_path).exists()

    # Prepare second mock database where hashes exist and match content_hash
    db2 = AsyncMock()
    # Build mapping file-> {chunk_id: hash}
    hashes_f1 = {chunk1.chunk_id or chunk1.id: chunk1.content_hash}
    hashes_f2 = {chunk2.chunk_id or chunk2.id: chunk2.content_hash}
    async def get_hashes(fp):
        return hashes_f1 if str(fp).endswith("f1.py") else hashes_f2

    db2.get_hashes_for_file = AsyncMock(side_effect=get_hashes)
    db2.search = AsyncMock()

    # Second compute - should skip expensive search calls
    res2 = await store.compute_and_store([chunk1, chunk2], db2)
    # Ensure search was not awaited
    db2.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_index_logging(tmp_path, monkeypatch):
    # Create a real file for engine to read
    f = tmp_path / "s.py"
    f.write_text("def s():\n    return 'x'\n")

    # Build a SearchResult that claims a content_hash but DB returns no matching chunks
    sr = SearchResult(
        content=f.read_text(),
        file_path=f,
        start_line=1,
        end_line=2,
        language="python",
        similarity_score=0.5,
        rank=1,
        content_hash="deadbeefdeadbeefdeadbeefdeadbeef",
    )

    db = AsyncMock()
    db.get_chunks_by_hash = AsyncMock(return_value=[])

    engine = SemanticSearchEngine(database=db, project_root=tmp_path)

    # Replace module logger with mock to capture loguru warnings
    import mcp_code_intelligence.core.search as search_mod
    from unittest.mock import Mock

    mock_logger = Mock()
    mock_logger.warning = Mock()
    monkeypatch.setattr(search_mod, "logger", mock_logger)

    await engine.context_service.get_context(sr, include_context=True)

    mock_logger.warning.assert_called()


def test_model_content_hash_roundtrip():
    # Ensure CodeChunk content_hash is preserved when placed into SearchResult
    content = "def z():\n    return 0"
    cc = CodeChunk(
        content=content,
        file_path=Path("/tmp/x.py"),
        start_line=1,
        end_line=2,
        language="python",
        chunk_type="function",
    )

    sr = SearchResult(
        content=cc.content,
        file_path=cc.file_path,
        start_line=cc.start_line,
        end_line=cc.end_line,
        language=cc.language,
        similarity_score=1.0,
        rank=1,
        content_hash=cc.content_hash,
    )

    assert sr.content_hash == cc.content_hash
