"""Inspector for detecting functions with empty bodies."""

import re
from typing import List, dict
from mcp_code_intelligence.analysis.inspectors.base import BaseInspector
from mcp_code_intelligence.core.models import CodeChunk

class EmptyBodyInspector(BaseInspector):
    """Detects functions/methods that are empty or only contain 'pass'/'...'."""

    @property
    def name(self) -> str:
        return "EmptyBody"

    async def inspect(self, chunks: List[CodeChunk]) -> List[dict]:
        issues = []
        
        # Patterns that indicate an empty or placeholder-only body
        # This matches: optional docstring, followed by pass or ... or nothing
        empty_func_patterns = [
            r"^\s*(?:async\s+)?def\s+\w+\s*\(.*?\)\s*(?:->\s*.*?)?:\s*(?:['\"].*?['\"]\s*)?(?:pass|\.\.\.)?\s*$",
            r"^\s*(?:async\s+)?def\s+\w+\s*\(.*?\)\s*(?:->\s*.*?)?:\s*$",
        ]
        
        empty_class_patterns = [
            r"^\s*class\s+\w+\s*(?:\(.*?\))?:\s*(?:['\"].*?['\"]\s*)?(?:pass|\.\.\.)?\s*$",
            r"^\s*class\s+\w+\s*(?:\(.*?\))?:\s*$",
        ]
        
        for chunk in chunks:
            # Level 0: Inline Ignore
            if "# guardian-ignore" in chunk.content or "# mcp-ignore" in chunk.content:
                continue

            if chunk.chunk_type in ("function", "method"):
                content = chunk.content.strip()
                is_empty = False
                for pattern in empty_func_patterns:
                    if re.match(pattern, content, re.DOTALL):
                        is_empty = True
                        break
                
                if not is_empty:
                    lines = [l.strip() for l in content.splitlines()]
                    if len(lines) <= 4:
                        code_lines = [l for l in lines if l and not l.startswith("#") and not l.startswith('"""') and not l.startswith("'''")]
                        if len(code_lines) <= 2:
                            if not any(keyword in content for keyword in ("return ", "yield ", "print(", "=")):
                                is_empty = True

                if is_empty:
                    issues.append({
                        "id": f"{self.name}:func:{chunk.chunk_id}",
                        "title": f"Empty Function: {chunk.function_name or 'Unknown'}",
                        "location": f"{chunk.file_path}:{chunk.start_line}",
                        "file_path": str(chunk.file_path),
                        "severity": "warning",
                        "description": f"The function '{chunk.function_name}' appears to be empty or contains only a placeholder.",
                        "chunk_id": chunk.chunk_id
                    })
            
            elif chunk.chunk_type == "class":
                content = chunk.content.strip()
                # Level 0: Inline Ignore
                if "# guardian-ignore" in content or "# mcp-ignore" in content:
                    continue
                    
                is_empty = False
                for pattern in empty_class_patterns:
                    if re.match(pattern, content, re.DOTALL):
                        is_empty = True
                        break
                
                if is_empty:
                    issues.append({
                        "id": f"{self.name}:class:{chunk.chunk_id}",
                        "title": f"Empty Class: {chunk.class_name or 'Unknown'}",
                        "location": f"{chunk.file_path}:{chunk.start_line}",
                        "file_path": str(chunk.file_path),
                        "severity": "warning",
                        "description": f"The class '{chunk.class_name}' appears to be empty or contains only a placeholder.",
                        "chunk_id": chunk.chunk_id
                    })
                    
        return issues
