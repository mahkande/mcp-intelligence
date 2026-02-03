"""Inspector for detecting TODO comments in the codebase."""

import re
from typing import List, Dict
from mcp_code_intelligence.analysis.inspectors.base import BaseInspector
from mcp_code_intelligence.core.models import CodeChunk

class TodoInspector(BaseInspector):
    """Detects TODO, FIXME, and XXX comments in code chunks."""

    @property
    def name(self) -> str:
        return "TodoTracker"

    async def inspect(self, chunks: List[CodeChunk]) -> List[dict]:
        issues = []
        
        # Pattern to match TODO style comments
        todo_pattern = re.compile(r"#(?:.*)(TODO|FIXME|XXX)[:\s]*(.*)", re.IGNORECASE)
        
        for chunk in chunks:
            # Level 0: Inline Ignore
            if "# guardian-ignore" in chunk.content or "# mcp-ignore" in chunk.content:
                continue

            # We also check docstrings as they might contains TODOs
            content = chunk.content
            
            matches = todo_pattern.finditer(content)
            for match in matches:
                tag = match.group(1).upper()
                comment = match.group(2).strip()
                
                # Check line number relative to chunk start
                pre_match_content = content[:match.start()]
                line_offset = pre_match_content.count("\n")
                actual_line = chunk.start_line + line_offset
                
                issues.append({
                    "id": f"{self.name}:{chunk.chunk_id}:{actual_line}",
                    "title": f"Unresolved {tag}",
                    "location": f"{chunk.file_path}:{actual_line}",
                    "file_path": str(chunk.file_path),
                    "severity": "info" if tag == "TODO" else "warning",
                    "description": f"Found a {tag} comment: '{comment}'",
                    "chunk_id": chunk.chunk_id
                })
                    
        return issues
