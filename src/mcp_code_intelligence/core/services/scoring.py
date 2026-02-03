
"""ScoringService: adaptive thresholding and small scoring helpers."""

from typing import Optional, List, Dict, Any
from pathlib import Path
from mcp_code_intelligence.core.models import SearchResult


class ScoringService:
    """Encapsulates scoring constants and adaptive threshold logic."""

    def __init__(self, base_threshold: float = 0.3) -> None:
        self.base_threshold = base_threshold

        # Tunable boosts / penalties
        self.boost_source_file = 0.05
        self.penalty_stale_index = 0.15
        
        # Static Type Boost Weights
        self.extension_weights = {
            # Primary Code Files
            ".py": 0.15, ".js": 0.15, ".ts": 0.15, ".tsx": 0.15, ".jsx": 0.15,
            ".go": 0.15, ".rs": 0.15, ".java": 0.15, ".cpp": 0.15, ".c": 0.15,
            ".h": 0.15, ".cs": 0.15, ".php": 0.15, ".rb": 0.15, ".swift": 0.15,
            ".kt": 0.15,
            # Config & Build
            ".json": 0.05, ".yaml": 0.05, ".yml": 0.05, ".toml": 0.05, ".sh": 0.05,
            # Documentation (Neutral)
            ".md": 0.0, ".txt": 0.0,
        }
        
        self.filename_weights = {
            "Dockerfile": 0.05,
            "Makefile": 0.05,
            "docker-compose.yml": 0.05,
            "package.json": 0.05,
        }
        
        self.chunk_type_weights = {
            "function": 0.05,
            "method": 0.05,
            "class": 0.05,
        }

    def adaptive_threshold(self, query: str, override: Optional[float] = None) -> float:
        """Return an adaptive similarity threshold for `query`."""
        if override is not None:
            return override

        length = len(query or "")
        if length < 20:
            return max(0.15, self.base_threshold - 0.05)
        if length > 200:
            return min(0.6, self.base_threshold + 0.1)
        return self.base_threshold

    def apply_boosts(self, results: List[SearchResult], query: str) -> List[SearchResult]:
        """Apply file type and chunk type boosts to search results.
        
        Includes 'smart override' for documentation queries.
        """
        query_lower = query.lower()
        
        # Smart Override: If user is looking for docs, don't penalize/boost code
        doc_keywords = {"readme", "install", "guide", "documentation", "docs", "help", "tutorial"}
        if any(kw in query_lower for kw in doc_keywords):
            return results
            
        for r in results:
            boost = 0.0
            
            # Store base score if not already set (e.g. by a previous boost layer or Jina)
            if r.base_score is None:
                r.base_score = r.similarity_score
            
            # 1. Extension Boost
            ext = r.file_path.suffix.lower()
            filename = r.file_path.name
            
            # Check if it's a test file (Penalty)
            is_test = (
                "test_" in filename or 
                "_test" in filename or 
                ".test." in filename or 
                ".spec." in filename or
                "tests/" in str(r.file_path).replace("\\", "/")
            )
            
            if is_test:
                boost -= 0.05
            else:
                # Apply static extension weights
                boost += self.extension_weights.get(ext, 0.0)
                # Apply filename weights (for Dockerfile etc)
                boost += self.filename_weights.get(filename, 0.0)
            
            # 2. Chunk Type Boost
            boost += self.chunk_type_weights.get(r.chunk_type, 0.0)
            
            # Update total boost score
            r.boost_score = (r.boost_score or 0.0) + boost
            
            # Apply and clamp
            r.similarity_score = max(0.0, min(1.0, r.similarity_score + boost))
            
        return results
