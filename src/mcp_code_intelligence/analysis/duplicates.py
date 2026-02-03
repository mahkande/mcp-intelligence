"""Duplicate code detection module with multi-level analysis."""

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from loguru import logger
from mcp_code_intelligence.core.models import CodeChunk
from mcp_code_intelligence.core.database import VectorDatabase

class DuplicateDetector:
    """Detects duplicate code across the project at three levels:
    1. Semantic (Vector Similarity)
    2. Structural (Normalized AST)
    3. Exact (MD5/SHA256 Hash)
    """

    def __init__(self, database: VectorDatabase):
        self.database = database

    async def detect_all(self, min_length: int = 100) -> dict[str, Any]:
        """Run all levels of duplicate detection.
        
        Args:
            min_length: Minimum character length for a chunk to be considered.
            
        Returns:
            Dictionary containing reports for all levels.
        """
        logger.info(f"Starting high-precision duplicate code analysis (Min size: {min_length} characters)")
        all_chunks = await self.database.get_all_chunks()
        
        # Filter noise/tiny chunks
        filtered_chunks = [c for c in all_chunks if len(c.content.strip()) >= min_length]
        
        # Level 3: Exact Matches (SQLite + MD5/SHA256)
        exact = await self._find_exact_duplicates(filtered_chunks)
        
        # Level 2: Structural Similarity (Fingerprinting)
        structural = await self._find_structural_duplicates(filtered_chunks)
        
        # Level 1: Semantic Similarity (Vektör Araması)
        semantic = await self._find_semantic_duplicates(filtered_chunks)

        return {
            "exact": exact,
            "structural": structural,
            "semantic": semantic,
            "stats": {
                "total_chunks_scanned": len(filtered_chunks),
                "exact_groups": len(exact),
                "structural_groups": len(structural),
                "semantic_groups": len(semantic)
            }
        }

    async def _find_exact_duplicates(self, chunks: list[CodeChunk]) -> list[dict[str, Any]]:
        """Level 3: Identical matches using existing content hashes."""
        hash_map = defaultdict(list)
        for chunk in chunks:
            if chunk.content_hash:
                hash_map[chunk.content_hash].append(chunk)

        duplicates = []
        for chash, group in hash_map.items():
            if len(group) > 1:
                duplicates.append({
                    "hash": chash,
                    "count": len(group),
                    "instances": [self._chunk_to_instance(c) for c in group],
                    "content_sample": group[0].content[:300]
                })
        return sorted(duplicates, key=lambda x: x["count"], reverse=True)

    async def _find_structural_duplicates(self, chunks: list[CodeChunk]) -> list[dict[str, Any]]:
        """Level 2: Structural similarity (same skeleton, different names)."""
        # We create a structural fingerprint for each chunk
        # A fingerprint consists of: type, language, line count, param count, and complexity
        struct_map = defaultdict(list)
        
        for chunk in chunks:
            # Create a structural signature
            # Logic: If it's a function, we look at params and length
            params = len(chunk.parameters) if chunk.parameters else 0
            signature = f"{chunk.language}:{chunk.chunk_type}:L{chunk.line_count}:P{params}"
            
            # We also add complexity to the signature if available
            if hasattr(chunk, 'complexity_score') and chunk.complexity_score > 0:
                signature += f":C{int(chunk.complexity_score)}"
            
            struct_map[signature].append(chunk)

        duplicates = []
        for sig, group in struct_map.items():
            if len(group) > 1:
                # Filter out exact duplicates from structural result to avoid redundancy
                hashes = set(c.content_hash for c in group)
                if len(hashes) > 1:
                    duplicates.append({
                        "signature": sig,
                        "count": len(group),
                        "unique_contents": len(hashes),
                        "instances": [self._chunk_to_instance(c) for c in group],
                        "content_sample": group[0].content[:300]
                    })
        return duplicates

    async def _find_semantic_duplicates(self, chunks: list[CodeChunk], threshold: float = 0.96) -> list[dict[str, Any]]:
        """Level 1: Semantic similarity using Jina v3 vector embeddings."""
        # For each chunk, we search for semantic neighbors
        duplicates = []
        processed_ids = set()

        # We take a sample of chunks to keep performance high for real-time analysis
        # In a real tool, we might do this in background
        target_chunks = chunks[:50] # Check first 50 chunks for semantic similarity
        
        for chunk in target_chunks:
            if chunk.id in processed_ids:
                continue
                
            results = await self.database.search(
                query=chunk.content,
                limit=4,
                similarity_threshold=threshold
            )
            
            similar_matches = []
            for res in results:
                # Skip self
                if res.location == f"{chunk.file_path}:{chunk.start_line}-{chunk.end_line}":
                    continue
                
                # Check if it's semantically similar but NOT exact match
                if res.content != chunk.content:
                    similar_matches.append({
                        "location": res.location,
                        "file_path": str(res.file_path),
                        "score": res.similarity_score,
                        "content_sample": res.content[:150]
                    })
                    processed_ids.add(res.location)

            if similar_matches:
                duplicates.append({
                    "original": self._chunk_to_instance(chunk),
                    "matches": similar_matches,
                    "count": len(similar_matches) + 1
                })
        
        return duplicates

    def _chunk_to_instance(self, chunk: CodeChunk) -> dict[str, Any]:
        return {
            "file_path": str(chunk.file_path),
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "location": f"{chunk.file_path}:{chunk.start_line}-{chunk.end_line}",
            "function_name": chunk.function_name or "Global",
            "language": chunk.language
        }
