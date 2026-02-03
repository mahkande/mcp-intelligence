from typing import Any, List, Optional, Dict
from pathlib import Path
from mcp_code_intelligence.core.search import SemanticSearchEngine as CoreSemanticSearchEngine
from mcp_code_intelligence.core.models import SearchResult
from mcp_code_intelligence.core.relationships import RelationshipStore
import json

class SemanticSearchEngine(CoreSemanticSearchEngine):
    """Enhanced Semantic Search Engine with discovery and relationship methods."""

    async def search_similar(
        self,
        file_path: Path,
        function_name: Optional[str] = None,
        limit: int = 10,
        similarity_threshold: Optional[float] = None,
    ) -> List[SearchResult]:
        """Delegate similarity search to discovery service."""
        return await self.discovery_service.search_similar(
            file_path=file_path,
            function_name=function_name,
            limit=limit,
            similarity_threshold=similarity_threshold
        )

    async def find_symbol(self, symbol_name: str, symbol_type: Optional[str] = None) -> List[SearchResult]:
        """Delegate symbol lookup to discovery service."""
        return await self.discovery_service.find_symbol(symbol_name, symbol_type)

    async def get_symbol_relationships(self, symbol_name: str) -> Dict[str, Any]:
        """Analyze callers and callees for a given symbol."""
        store = RelationshipStore(self.project_root)
        data = store.load()
        
        # Load chunks for metadata
        chunks_path = self.project_root / ".mcp-code-intelligence" / "chunks.json"
        all_chunks = []
        if chunks_path.exists():
            with open(chunks_path) as f:
                all_chunks = json.load(f)
        
        # Find defining chunk
        target_chunks = [c for c in all_chunks if c.get("function_name") == symbol_name or c.get("class_name") == symbol_name]
        if not target_chunks:
            return {"error": f"Symbol '{symbol_name}' not found."}
        
        target = target_chunks[0]
        chunk_id = target.get("chunk_id") or target.get("id")
        
        # Callers: Who calls this?
        callers = data.get("callers", {}).get(chunk_id, [])
        
        # Callees: What does this call?
        # We need to extract calls from target content
        from mcp_code_intelligence.core.relationships import extract_function_calls
        calls = extract_function_calls(target.get("content", ""), target.get("language", "python"))
        
        callees = []
        for call in calls:
            # Try to find what this call points to (best effort)
            callee_chunks = [c for c in all_chunks if c.get("function_name") == call or c.get("class_name") == call]
            if callee_chunks:
                callees.append({
                    "name": call,
                    "file": callee_chunks[0].get("file_path"),
                    "type": callee_chunks[0].get("chunk_type")
                })
        
        return {
            "definition": {
                "file": target.get("file_path"),
                "lines": f"{target.get('start_line')}-{target.get('end_line')}",
                "type": target.get("chunk_type")
            },
            "callers": callers,
            "callees": callees
        }

    async def code_intelligence_search_code(self, query: str, limit: int = 10, similarity_threshold: float = 0.3) -> List[SearchResult]:
        """Alias for standard search to match tool expectations if needed."""
        return await self.search(query=query, limit=limit, similarity_threshold=similarity_threshold)
