"""MCP tool implementation for find_duplicates."""

from typing import Any, Dict
from mcp.types import CallToolResult, TextContent
from mcp_code_intelligence.analysis.duplicates import DuplicateDetector

async def handle_find_duplicates(search_engine, args: Dict[str, Any]) -> CallToolResult:
    """Handle find_duplicates tool call with three-level detection logic."""
    if not search_engine:
        return CallToolResult(
            content=[TextContent(type="text", text="Search engine not initialized")],
            isError=True,
        )

    min_length = args.get("min_length", 100)
    detector = DuplicateDetector(search_engine.database)
    report = await detector.detect_all(min_length=min_length)

    response_lines = ["### 🛡️ High-Precision Duplicate Code Analysis Report\n"]
    
    # EXACT MATCHES (Level 3)
    if report["exact"]:
        response_lines.append("#### 🔴 Level 3: Exact Matches (MD5/SHA256)")
        response_lines.append("> [!CAUTION]\n> These code blocks are identical across different files (Copy-Paste detected).\n")
        
        for i, dup in enumerate(report["exact"][:5], 1):
            response_lines.append(f"**Group {i}:** {dup['count']} Occurrences")
            response_lines.append("| Location | Detail |")
            response_lines.append("| :--- | :--- |")
            for inst in dup["instances"]:
                response_lines.append(f"| `{inst['location']}` | `{inst['function_name']}` |")
            
            response_lines.append(f"\n```python\n{dup['content_sample'][:200]}...\n```\n")

    # STRUCTURAL (Level 2)
    if report["structural"]:
        response_lines.append("#### 🟡 Level 2: Structural Similarity (AST / Tree-sitter)")
        response_lines.append("> [!WARNING]\n> These blocks have different names or minor changes but share the exact same 'skeleton' and algorithm flow.\n")
        
        for i, dup in enumerate(report["structural"][:5], 1):
            response_lines.append(f"**Group {i}:** {dup['count']} Similar Structures")
            locs = ", ".join([f"`{inst['location']}`" for inst in dup["instances"][:2]])
            response_lines.append(f"Example: {locs}...")
            response_lines.append("")

    # SEMANTIC (Level 1)
    if report["semantic"]:
        response_lines.append("#### 🟢 Level 1: Semantic Similarity (Jina v3 AI)")
        response_lines.append("> [!IMPORTANT]\n> These functions are written differently, but AI detected they perform the **exact same task**.\n")
        
        for i, dup in enumerate(report["semantic"][:3], 1):
            orig = dup["original"]
            response_lines.append(f"**Match {i}:** `{orig['function_name']}` ({orig['location']})")
            for m in dup["matches"]:
                response_lines.append(f"→ Similar: `{m['location']}` (Confidence Score: {m['score']:.3f})")
            response_lines.append("")

    stats = report["stats"]
    response_lines.append(f"\n---\n> [!TIP]\n> Analyzed **{stats['total_chunks_scanned']}** code chunks. You can reduce technical debt by moving these blocks to a common Utility or Base class.")

    return CallToolResult(content=[TextContent(type="text", text="\n".join(response_lines))])
