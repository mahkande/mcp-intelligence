"""Pre-computed relationship storage for instant visualization.

This module handles computing and storing code chunk relationships at index time,
eliminating the expensive computation during visualization startup.

Relationships stored:
- Semantic relationships: Which chunks are similar (based on embeddings)
- Caller relationships: Which chunks call which (based on AST analysis)
"""

import ast
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
import re
from typing import Any

from loguru import logger
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

from mcp_code_intelligence.core.models import CodeChunk

console = Console()


def extract_function_calls(code: str, language: str = "python") -> set[str]:
    """Extract actual function calls from code.

    Uses AST for Python for high precision, and regex fallback for other languages (Dart, JS, etc.).
    """
    calls = set()

    # 1. Python specific AST analysis
    if language.lower() == "python":
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        calls.add(node.func.id)
                    elif isinstance(node.func, ast.Attribute):
                        calls.add(node.func.attr)
            return calls
        except SyntaxError:
            pass # Fall back to regex if AST fails

    # 2. Universal Regex fallback (handles Dart, JS, etc.)
    # Matches patterns like funcName(), obj.methodName(), but avoids keywords
    # Excludes common control flow keywords
    keywords = {'if', 'for', 'while', 'switch', 'catch', 'return', 'yield', 'await', 'async'}

    # Pattern explanation:
    # [a-zA-Z_]\w* : Identifier
    # (?=\s*\()    : Lookahead for opening parenthesis (means it's a call)
    matches = re.findall(r'\b([a-zA-Z_]\w*)\s*(?=\()', code)

    for match in matches:
        if match not in keywords:
            calls.add(match)

    return calls


def extract_chunk_name(content: str, fallback: str = "chunk") -> str:
    """Extract first meaningful word from chunk content for labeling.

    Args:
        content: The chunk's code content
        fallback: Fallback name if no meaningful word found

    Returns:
        First meaningful identifier found in the content
    """
    import re

    # Skip common keywords that aren't meaningful as chunk labels
    skip_words = {
        "def",
        "class",
        "function",
        "const",
        "let",
        "var",
        "import",
        "from",
        "return",
        "if",
        "else",
        "elif",
        "for",
        "while",
        "try",
        "except",
        "finally",
        "with",
        "as",
        "async",
        "await",
        "yield",
        "self",
        "this",
        "true",
        "false",
        "none",
        "null",
        "undefined",
        "public",
        "private",
        "protected",
        "static",
        "export",
        "default",
    }

    # Find all words (alphanumeric + underscore, at least 2 chars)
    words = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]+\b", content)

    for word in words:
        if word.lower() not in skip_words:
            return word

    return fallback


class RelationshipStore:
    """Store and load pre-computed chunk relationships.

    Relationships are stored in .mcp-code-intelligence/relationships.json and include:
    - Semantic links (similar chunks based on embeddings)
    - Caller links (which chunks call which)
    - Metadata (chunk count, computation time, version)
    """

    def __init__(self, project_root: Path):
        """Initialize relationship store.

        Args:
            project_root: Root directory of the project
        """
        self.project_root = project_root
        self.store_path = project_root / ".mcp-code-intelligence" / "relationships.json"

    async def compute_and_store(
        self,
        chunks: list[CodeChunk],
        database: Any,
        max_concurrent_queries: int = 50,
        background: bool = False,
    ) -> dict[str, Any]:
        """Compute relationships and save to disk.

        This is called during indexing to pre-compute expensive relationships.
        NOTE: Caller relationships are now lazy-loaded via /api/callers/{chunk_id}
        to avoid the expensive O(n²) computation at startup.

        Args:
            chunks: List of all code chunks
            database: Vector database instance for semantic search
            max_concurrent_queries: Maximum number of concurrent database queries (default: 50)
            background: If True, skip computation and return immediately (for background processing)

        Returns:
            Dictionary with relationship statistics
        """
        logger.info("Computing relationships for visualization...")
        start_time = time.time()

        # Filter to code chunks only
        code_chunks = [
            c for c in chunks if c.chunk_type in ["function", "method", "class"]
        ]

        # If background mode, create empty relationships file and return
        # Actual computation will happen in background task
        if background:
            relationships = {
                "version": "1.1",
                "computed_at": datetime.now(UTC).isoformat(),
                "chunk_count": len(chunks),
                "code_chunk_count": len(code_chunks),
                "computation_time_seconds": 0,
                "semantic": [],
                "callers": {},
                "status": "pending",  # Mark as pending background computation
            }

            # Save empty file
            self.store_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.store_path, "w") as f:
                json.dump(relationships, f, indent=2)

            logger.info("✓ Relationships marked for background computation")
            return {
                "semantic_links": 0,
                "caller_relationships": 0,
                "computation_time": 0,
                "background": True,
            }

        # Compute semantic relationships only
        # Caller relationships are lazy-loaded on-demand via API
        logger.info(
            f"Computing semantic relationships for {len(code_chunks)} chunks "
            f"(max {max_concurrent_queries} concurrent queries)..."
        )

        # Load existing relationships if present so we can skip recomputation
        existing_relationships = {}
        if self.store_path.exists():
            try:
                with open(self.store_path) as f:
                    existing = json.load(f)
                    for link in existing.get("semantic", []):
                        src = link.get("source")
                        if src:
                            existing_relationships.setdefault(src, []).append(link)
            except Exception:
                existing_relationships = {}

        # Group chunks by file to fetch stored hashes efficiently
        from collections import defaultdict

        file_to_chunks: dict[str, list[CodeChunk]] = defaultdict(list)
        for c in code_chunks:
            file_to_chunks[str(c.file_path)].append(c)

        # Determine which chunks actually changed by comparing DB hashes
        chunks_to_compute: list[CodeChunk] = []
        reused_links: list[dict[str, Any]] = []

        for file_path, chunks_in_file in file_to_chunks.items():
            try:
                db_hash_map = await database.get_hashes_for_file(Path(file_path))
            except Exception:
                db_hash_map = {}

            for c in chunks_in_file:
                chunk_id = c.chunk_id or c.id
                db_hash = db_hash_map.get(chunk_id, "")

                # If hashes match, reuse existing semantic links for this chunk
                if db_hash and c.content_hash and db_hash == c.content_hash:
                    links = existing_relationships.get(chunk_id, [])
                    if links:
                        reused_links.extend(links)
                        continue

                # Otherwise mark for recomputation
                chunks_to_compute.append(c)

        # Compute semantic links only for changed chunks
        semantic_links_new = []
        if chunks_to_compute:
            semantic_links_new = await self._compute_semantic_relationships(
                chunks_to_compute, database, max_concurrent_queries
            )

        # Merge reused links and newly computed links
        semantic_links = reused_links + semantic_links_new

        elapsed = time.time() - start_time

        # Build relationship data (no caller_map - it's lazy loaded)
        relationships = {
            "version": "1.1",  # Version bump for lazy callers
            "computed_at": datetime.now(UTC).isoformat(),
            "chunk_count": len(chunks),
            "code_chunk_count": len(code_chunks),
            "computation_time_seconds": elapsed,
            "semantic": semantic_links,
            "callers": {},  # Empty - loaded on-demand via /api/callers/{chunk_id}
            "status": "complete",
        }

        # Save to disk
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.store_path, "w") as f:
            json.dump(relationships, f, indent=2)

        logger.info(
            f"✓ Computed {len(semantic_links)} semantic links in {elapsed:.1f}s "
            "(callers lazy-loaded on-demand)"
        )

        return {
            "semantic_links": len(semantic_links),
            "caller_relationships": 0,  # Now lazy-loaded
            "computation_time": elapsed,
        }

    async def _compute_semantic_relationships(
        self,
        code_chunks: list[CodeChunk],
        database: Any,
        max_concurrent_queries: int = 50,
    ) -> list[dict[str, Any]]:
        """Compute semantic similarity relationships between chunks using async parallel processing.

        Args:
            code_chunks: List of code chunks (functions, methods, classes)
            database: Vector database for similarity search
            max_concurrent_queries: Maximum number of concurrent database queries (default: 50)

        Returns:
            List of semantic link dictionaries
        """
        semantic_links = []
        semaphore = asyncio.Semaphore(max_concurrent_queries)
        completed_count = 0
        total_chunks = len(code_chunks)

        # Use Rich progress bar
        with Progress(
            SpinnerColumn(),
            TextColumn("[cyan]Computing semantic relationships...[/cyan]"),
            BarColumn(bar_width=40),
            TaskProgressColumn(),
            TextColumn("[dim]{task.completed}/{task.total} chunks[/dim]"),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task("semantic", total=total_chunks)

            async def process_chunk(chunk: CodeChunk) -> list[dict[str, Any]]:
                """Process a single chunk and return its semantic links."""
                nonlocal completed_count

                async with semaphore:
                    try:
                        # Search for similar chunks
                        similar_results = await database.search(
                            query=chunk.content[:500],  # First 500 chars
                            limit=6,  # Get 6 (exclude self = 5)
                            similarity_threshold=0.3,
                        )

                        chunk_links = []
                        source_chunk_id = chunk.chunk_id or chunk.id

                        # Filter out self and create links
                        for result in similar_results:
                            target_chunk = next(
                                (
                                    c
                                    for c in code_chunks
                                    if str(c.file_path) == str(result.file_path)
                                    and c.start_line == result.start_line
                                    and c.end_line == result.end_line
                                ),
                                None,
                            )

                            if not target_chunk:
                                continue

                            target_chunk_id = target_chunk.chunk_id or target_chunk.id

                            # Skip self-references
                            if target_chunk_id == source_chunk_id:
                                continue

                            # Add semantic link
                            if result.similarity_score >= 0.2:
                                chunk_links.append(
                                    {
                                        "source": source_chunk_id,
                                        "target": target_chunk_id,
                                        "type": "semantic",
                                        "similarity": result.similarity_score,
                                    }
                                )

                                # Only keep top 5 per chunk
                                if len(chunk_links) >= 5:
                                    break

                        # Update progress
                        completed_count += 1
                        progress.update(task, completed=completed_count)

                        return chunk_links

                    except Exception as e:
                        logger.debug(
                            f"Failed to compute semantic for {chunk.chunk_id}: {e}"
                        )
                        completed_count += 1
                        progress.update(task, completed=completed_count)
                        return []

            # Process all chunks in parallel
            tasks = [process_chunk(chunk) for chunk in code_chunks]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Flatten results and handle exceptions
            for result in results:
                if isinstance(result, Exception):
                    logger.debug(f"Task failed with exception: {result}")
                    continue
                semantic_links.extend(result)

        return semantic_links

    def _compute_caller_relationships(
        self, chunks: list[CodeChunk]
    ) -> dict[str, list[dict[str, Any]]]:
        """Compute which chunks call which other chunks, with fuzzy matching for qualified names."""
        caller_map = {}
        code_chunks = [
            c for c in chunks if c.chunk_type in ["function", "method", "class"]
        ]
        logger.debug(f"Processing {len(code_chunks)} code chunks for callers...")
        for chunk_idx, chunk in enumerate(code_chunks):
            if chunk_idx % 50 == 0:
                logger.debug(f"Callers: {chunk_idx}/{len(code_chunks)} chunks")
            chunk_id = chunk.chunk_id or chunk.id
            file_path = str(chunk.file_path)
            function_name = chunk.function_name or chunk.class_name
            qualified_name = None
            if chunk.class_name and chunk.function_name:
                qualified_name = f"{chunk.class_name}.{chunk.function_name}"
            elif chunk.function_name:
                qualified_name = chunk.function_name
            elif chunk.class_name:
                qualified_name = chunk.class_name
            else:
                qualified_name = None
            if not function_name:
                continue
            for other_chunk in chunks:
                other_file_path = str(other_chunk.file_path)
                if other_file_path == file_path:
                    continue
                actual_calls = extract_function_calls(other_chunk.content)
                # Fuzzy match: check both function_name and qualified_name
                match_found = False
                if function_name in actual_calls:
                    match_found = True
                elif qualified_name and qualified_name in actual_calls:
                    match_found = True
                if not match_found:
                    # Try even more fuzzy: look for any call that endswith function_name
                    for call in actual_calls:
                        if call.endswith(f".{function_name}") or call == function_name:
                            match_found = True
                            break
                if match_found:
                    other_chunk_id = other_chunk.chunk_id or other_chunk.id
                    other_name = other_chunk.function_name or other_chunk.class_name
                    if not other_name:
                        other_name = extract_chunk_name(
                            other_chunk.content,
                            fallback=f"chunk_{other_chunk.start_line}",
                        )
                    if other_name == "__init__":
                        continue
                    if chunk_id not in caller_map:
                        caller_map[chunk_id] = []
                    caller_map[chunk_id].append(
                        {
                            "file": other_file_path,
                            "chunk_id": other_chunk_id,
                            "name": other_name,
                            "type": other_chunk.chunk_type,
                        }
                    )
                    logger.debug(
                        f"Found call: {other_name} ({other_file_path}) -> "
                        f"{qualified_name or function_name} ({file_path})"
                    )
        return caller_map

    def load(self) -> dict[str, Any]:
        """Load pre-computed relationships from disk.

        Returns:
            Dictionary with semantic and caller relationships, or empty structure if not found
        """
        if not self.store_path.exists():
            logger.warning(
                f"No pre-computed relationships found at {self.store_path}. "
                "Run 'mcp-code-intelligence index' to compute relationships."
            )
            return {"semantic": [], "callers": {}}

        try:
            with open(self.store_path) as f:
                data = json.load(f)

            logger.info(
                f"✓ Loaded {len(data.get('semantic', []))} semantic links and "
                f"{sum(len(callers) for callers in data.get('callers', {}).values())} "
                f"caller relationships (computed {data.get('computed_at', 'unknown')})"
            )

            return data
        except Exception as e:
            logger.error(f"Failed to load relationships: {e}")
            return {"semantic": [], "callers": {}}

    def exists(self) -> bool:
        """Check if pre-computed relationships exist.

        Returns:
            True if relationships file exists
        """
        return self.store_path.exists()

    def invalidate(self) -> None:
        """Delete stored relationships (called when index changes).

        This forces re-computation on next full index.
        """
        if self.store_path.exists():
            self.store_path.unlink()
            logger.debug("Invalidated pre-computed relationships")

def analyze_impact(project_root: Path, symbol_name: str, max_depth: int = 5) -> dict:
    """Impact Analysis: Finds the direct and chained effects of a symbol.
    Args:
        project_root: Project root directory
        symbol_name: Function or class name
        max_depth: Chain depth limit
    Returns:
        {
            'origin': ...,
            'immediate_impact': [...],
            'deep_impact': [...],
            'complexity_score': ...,
        }
    """
    store = RelationshipStore(project_root)
    data = store.load()
    # 1. Chunk id'yi bul
    all_chunks = []
    # Load chunks from chunks.json or index file (example: .mcp-code-intelligence/chunks.json)
    chunks_path = project_root / ".mcp-code-intelligence" / "chunks.json"
    if chunks_path.exists():
        with open(chunks_path) as f:
            all_chunks = json.load(f)
    # Find symbol
    target_chunks = [c for c in all_chunks if c.get("function_name") == symbol_name or c.get("class_name") == symbol_name]
    if not target_chunks:
        return {"error": f"Symbol not found: {symbol_name}"}
    target_chunk = target_chunks[0]
    chunk_id = target_chunk.get("chunk_id") or target_chunk.get("id")
    origin = target_chunk.get("file_path")
    # 2. Immediate impact: callers and semantic outgoing
    callers = data.get("callers", {}).get(chunk_id, [])
    semantic_links = [l for l in data.get("semantic", []) if l.get("source") == chunk_id]
    immediate_impact = set()
    for c in callers:
        immediate_impact.add(c["file"])
    for l in semantic_links:
        # find semantic link target
        target = l.get("target")
        for c in all_chunks:
            if c.get("chunk_id") == target:
                immediate_impact.add(c.get("file_path"))
    # 3. Derin etki (deep impact): zincirleme traversal
    deep_impact = set()
    visited = set()
    def traverse(cid, depth):
        if depth > max_depth or cid in visited:
            return
        visited.add(cid)
        # Callers
        for c in data.get("callers", {}).get(cid, []):
            deep_impact.add(c["file"])
            traverse(c["chunk_id"], depth+1)
        # Semantic outgoing
        for l in [l for l in data.get("semantic", []) if l.get("source") == cid]:
            target = l.get("target")
            for c2 in all_chunks:
                if c2.get("chunk_id") == target:
                    deep_impact.add(c2.get("file_path"))
                    traverse(target, depth+1)
    traverse(chunk_id, 1)
    # 4. Complexity score: how many different chunks and files are affected?
    complexity_score = len(immediate_impact) + len(deep_impact)
    return {
        "origin": origin,
        "immediate_impact": list(immediate_impact),
        "deep_impact": list(deep_impact),
        "complexity_score": complexity_score,
    }

