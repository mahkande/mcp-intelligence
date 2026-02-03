"""Context service: file caching and result enrichment.

This isolates file I/O and enrichment logic from `SemanticSearchEngine`.
"""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

import aiofiles
from loguru import logger

from mcp_code_intelligence.config.constants import DEFAULT_CACHE_SIZE
from mcp_code_intelligence.core.models import SearchResult


class DefaultContextService:
    """Default implementation of `ContextService`.

    Responsibilities moved from `SemanticSearchEngine`:
    - `_file_cache` LRU using OrderedDict
    - `_read_file_lines_cached`
    - `_enhance_result` -> `get_context`
    """

    def __init__(self, cache_maxsize: int | None = None) -> None:
        self._file_cache: OrderedDict[Path, list[str]] = OrderedDict()
        self._cache_maxsize = cache_maxsize or DEFAULT_CACHE_SIZE
        self._cache_hits = 0
        self._cache_misses = 0

    async def _read_file_lines_cached(self, file_path: Path) -> list[str]:
        if file_path in self._file_cache:
            self._cache_hits += 1
            self._file_cache.move_to_end(file_path)
            return self._file_cache[file_path]

        self._cache_misses += 1
        try:
            async with aiofiles.open(file_path, encoding="utf-8") as f:
                content = await f.read()
                lines = content.splitlines(keepends=True)

            if len(self._file_cache) >= self._cache_maxsize:
                self._file_cache.popitem(last=False)

            self._file_cache[file_path] = lines
            return lines
        except FileNotFoundError:
            if len(self._file_cache) >= self._cache_maxsize:
                self._file_cache.popitem(last=False)
            self._file_cache[file_path] = []
            raise

    async def get_context(self, result: SearchResult, include_context: bool) -> SearchResult:
        if not include_context:
            return result

        try:
            lines = await self._read_file_lines_cached(result.file_path)

            if not lines:
                return result

            context_size = 3
            start_idx = max(0, result.start_line - 1 - context_size)
            end_idx = min(len(lines), result.end_line + context_size)

            context_before = [line.rstrip() for line in lines[start_idx : result.start_line - 1]]
            context_after = [line.rstrip() for line in lines[result.end_line : end_idx]]

            result.context_before = context_before
            result.context_after = context_after

            # Stale index detection (non-fatal) — DB lookup lives in search engine; keep this hook minimal.
            # Higher-level code may call database.get_chunks_by_hash externally when needed.

        except FileNotFoundError:
            logger.debug(f"File no longer exists (stale index): {result.file_path}")
            result.file_missing = True
        except Exception as e:
            logger.warning(f"Failed to get context for {result.file_path}: {e}")

        return result

    def clear_cache(self) -> None:
        self._file_cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0

    def get_cache_info(self) -> dict[str, Any]:
        total = self._cache_hits + self._cache_misses
        hit_rate = self._cache_hits / total if total > 0 else 0.0
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "size": len(self._file_cache),
            "maxsize": self._cache_maxsize,
            "hit_rate": f"{hit_rate:.2%}",
        }


__all__ = ["DefaultContextService"]
