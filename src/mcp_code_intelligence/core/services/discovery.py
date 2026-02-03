"""DiscoveryService: symbol and similarity helpers extracted from search engine.

This service contains methods for symbol lookup, similarity-by-file and
context-based searches. It is intentionally small and delegates to the main
engine search pipeline where appropriate to avoid duplicating ranking logic.
"""

import re
from pathlib import Path
from typing import Any, List, Optional

from loguru import logger

from mcp_code_intelligence.core.models import SearchResult


class DiscoveryService:
    def __init__(self, engine: Any) -> None:
        self.engine = engine

    async def search_similar(
        self,
        file_path: Path,
        function_name: Optional[str] = None,
        limit: int = 10,
        similarity_threshold: Optional[float] = None,
    ) -> List[SearchResult]:
        """Find code similar to a file or function by delegating to engine.search.

        This reuses the main search pipeline for consistent ranking and
        enrichment.
        """
        try:
            # Try to use ContextService read (cached) if available
            try:
                lines = await self.engine.context_service._read_file_lines_cached(file_path)  # type: ignore[attr-defined]
                content = "".join(lines)
            except Exception:
                async with __import__("aiofiles").open(file_path, encoding="utf-8") as f:
                    content = await f.read()

            if function_name:
                function_content = self._extract_function_content(content, function_name)
                if function_content:
                    content = function_content

            return await self.engine.search(
                query=content,
                limit=limit,
                similarity_threshold=similarity_threshold,
                include_context=True,
            )

        except Exception as e:
            logger.error(f"search_similar failed for {file_path}: {e}")
            raise

    async def find_symbol(self, symbol_name: str, symbol_type: Optional[str] = None) -> List[SearchResult]:
        """Exact symbol lookup in the vector DB, returned as SearchResult list."""
        chunks = await self.engine.database.get_chunks_by_symbol(symbol_name, symbol_type)

        results: List[SearchResult] = []
        for i, chunk in enumerate(chunks):
            ct = chunk.chunk_type or "code"
            if ct in ("function", "method"):
                sym_ctx = "function"
            elif ct == "class":
                sym_ctx = "class"
            else:
                sym_ctx = "global"

            nav_hint = f"{chunk.file_path}:{chunk.start_line}"

            results.append(
                SearchResult(
                    content=chunk.content,
                    file_path=chunk.file_path,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    language=chunk.language,
                    similarity_score=1.0,
                    rank=i + 1,
                    chunk_type=ct,
                    function_name=chunk.function_name,
                    class_name=chunk.class_name,
                    quality_score=100,
                    symbol_context=sym_ctx,
                    navigation_hint=nav_hint,
                )
            )

        return results

    def _extract_function_content(self, content: str, function_name: str) -> Optional[str]:
        pattern = rf"^\s*def\s+{re.escape(function_name)}\s*\("  # simple python-only heuristic
        lines = content.splitlines()

        for i, line in enumerate(lines):
            if re.match(pattern, line):
                start_line = i
                indent_level = len(line) - len(line.lstrip())
                end_line = len(lines)
                for j in range(i + 1, len(lines)):
                    if lines[j].strip():
                        current_indent = len(lines[j]) - len(lines[j].lstrip())
                        if current_indent <= indent_level:
                            end_line = j
                            break

                return "\n".join(lines[start_line:end_line])

        return None
