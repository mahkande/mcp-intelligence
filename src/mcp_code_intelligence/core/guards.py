"""Guardrails for RAG and indexing in MCP Code Intelligence.

This module provides filters and evaluators to ensure search results are high-quality,
secure, and contextually relevant by filtering out:
- Placeholder/Dummy code (TODO, FIXME)
- Test/Mock code in production searches
- Deprecated/Legacy code
- Generated/Automated code
- Secrets/Sensitive configuration
- Low-signal/Boilerplate code
- Out-of-scope frameworks/languages
- Stale/Inactive code
"""

import re
from pathlib import Path
from typing import Any, Final

from loguru import logger

from mcp_code_intelligence.core.models import CodeChunk, SearchResult


class RAGGuard:
    """Guardrails for indexing and search.

    Implements various filters to improve RAG quality and security.
    """

    # --- 1. TODO / Dummy Guard ---
    DUMMY_PATTERNS: Final[list[re.Pattern]] = [
        re.compile(r"TODO", re.I),
        re.compile(r"FIXME", re.I),
        re.compile(r"UnimplementedError", re.I),
        re.compile(r"NotImplementedError", re.I),
        re.compile(r"pass$|return true; // temp", re.M | re.I),
    ]

    # --- 2. Test / Mock Guard ---
    TEST_PATTERNS: Final[list[str]] = ["/test/", "/__tests__/", "/spec/", "/tests/"]
    MOCK_PATTERNS: Final[list[str]] = ["mock", "fake", "stub"]

    # --- 3. Deprecated / Legacy Guard ---
    DEPRECATED_PATTERNS: Final[list[re.Pattern]] = [
        re.compile(r"@deprecated", re.I),
        re.compile(r"// legacy", re.I),
        re.compile(r"\bOLD_", re.I),
    ]

    # --- 4. Generated Code Guard ---
    GENERATED_PATTERNS: Final[list[re.Pattern]] = [
        re.compile(r"// GENERATED", re.I),
        re.compile(r"do not edit", re.I),
        re.compile(r"build_runner", re.I),
        re.compile(r"protobuf", re.I),
        re.compile(r"swagger", re.I),
        re.compile(r"openapi", re.I),
    ]

    # --- 5. Config / Secret Guard ---
    SECRET_PATTERNS: Final[list[re.Pattern]] = [
        re.compile(r"(apiKey|secret|password|token)\s*=\s*['\"].*['\"]", re.I),
        re.compile(r"-----BEGIN RSA PRIVATE KEY-----"),
    ]

    def __init__(self, active_files: list[str] | None = None):
        self._boilerplate_names = frozenset({"get", "set", "Enum"})
        self.active_files = set(active_files or [])

    def set_active_files(self, active_files: list[str]):
        """Update the set of active (recently modified) files."""
        self.active_files = set(active_files)

    def should_index_path(self, path: Path) -> bool:
        """Check if a path should be indexed based on guards.

        Applied during indexing phase.
        """
        path_str = str(path).lower()

        # Config / Secret Guard (Filename check)
        if path.name == ".env" or path.name.endswith(".pem"):
            return False

        # Test Guard (Directory check)
        if any(p in path_str for p in self.TEST_PATTERNS):
            return False

        return True

    def should_index_content(self, content: str) -> bool:
        """Check if file content should be indexed.

        Applied before parsing.
        """
        # Generated Code Guard
        if any(p.search(content[:1000]) for p in self.GENERATED_PATTERNS):
            return False

        return True

    def is_low_signal_chunk(self, chunk: CodeChunk) -> bool:
        """Check if a code chunk has low signal.

        Applied during parsing/indexing.
        """
        content = chunk.content.strip()

        # Length check
        if len(content.split("\n")) < 3:
            return True

        # Getter/Setter check
        if chunk.chunk_type == "method" and any(content.startswith(p) for p in ["get ", "set "]):
            return True

        return False

    def apply_search_penalties(self, results: list[SearchResult], query: str) -> list[SearchResult]:
        """Apply penalties to search results based on guards.

        Applied during search/reranking phase.
        """
        query_lower = query.lower()

        for result in results:
            content = result.content
            score_adj = 0.0

            # 1. TODO / Dummy Guard Penalty
            if any(p.search(content) for p in self.DUMMY_PATTERNS):
                score_adj -= 0.15

            # 3. Deprecated Guard Penalty
            if any(p.search(content) for p in self.DEPRECATED_PATTERNS):
                score_adj -= 0.20

            # 5. Secret Guard (Scrubbing + Penalty)
            if any(p.search(content) for p in self.SECRET_PATTERNS):
                # We don't want to show secrets even if they matched
                result.content = "[REDACTED BY SECRET GUARD]"
                score_adj -= 0.50

            # Apply score adjustment
            result.similarity_score = max(0.0, result.similarity_score + score_adj)

            # 8. Recency / Active-Code Guard (Boost)
            if str(result.file_path) in self.active_files:
                result.similarity_score = min(1.0, result.similarity_score + 0.10)

        return results

    def filter_scope(self, results: list[SearchResult], query: str) -> list[SearchResult]:
        """Filter results that are out of language/framework scope.
        
        Example: If query has 'flutter', prioritize '.dart' files.
        """
        query_lower = query.lower()
        
        # Simple scope detection
        scope_dart = "flutter" in query_lower or "dart" in query_lower
        scope_python = "python" in query_lower or "django" in query_lower or "flask" in query_lower
        
        if scope_dart:
            for r in results:
                if r.file_path.suffix == ".dart":
                    r.similarity_score += 0.1
                else:
                    r.similarity_score -= 0.05

        if scope_python:
            for r in results:
                if r.file_path.suffix == ".py":
                    r.similarity_score += 0.1
                else:
                    r.similarity_score -= 0.05
                    
        return results

