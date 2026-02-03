"""Vector Search MCP Server - discovery-safe adverts.

This module exposes a lightweight `get_advertised_tools(project_root)` function
that the registry can import during discovery without initializing heavy
vector-database clients. Heavy dependencies are imported lazily inside
try/except blocks to avoid import-time crashes when the optional packages are
not installed.
"""
from pathlib import Path
from typing import List

from mcp.types import Tool

# Attempt to import heavy vector DB dependencies; keep import-time safe.
try:
    import chromadb  # type: ignore
    CHROMADB_AVAILABLE = True
except Exception:
    chromadb = None
    CHROMADB_AVAILABLE = False


def _check_onnxruntime_available():
    try:
        import onnxruntime  # type: ignore
        return True
    except ImportError:
        return False
    except Exception:
        return False


def get_advertised_tools(project_root: Path) -> List[Tool]:
    """Return discovery-safe adverts for vector search capabilities.

    - If `chromadb` is missing, return a `fix_chromadb_missing` tool recommending
      installation.
    - If `onnxruntime` is required but missing, return a `fix_onnxruntime_missing`.
    - Otherwise advertise the normal vector search tools.
    """
    pr = Path(project_root) if project_root is not None else Path.cwd()

    # Dependency checks
    if not CHROMADB_AVAILABLE:
        return [
            Tool(
                name="fix_chromadb_missing",
                description=(
                    "Vector search unavailable: chromadb package is not installed."
                    " Install with: pip install chromadb"
                ),
                inputSchema={"type": "object", "properties": {}},
            )
        ]


    # If ONNX is optional for certain embedding models, advertise a fix if absent
    if not _check_onnxruntime_available():
        # Not fatal for all Chromadb setups, but surface a remediation option.
        return [
            Tool(
                name="fix_onnxruntime_missing",
                description=(
                    "Optional acceleration missing: onnxruntime not installed. "
                    "Install with: pip install onnxruntime (or onnxruntime-gpu)"
                ),
                inputSchema={"type": "object", "properties": {}},
            )
        ]

    # If dependencies exist, advertise vector tools (lightweight schema only).
    return [
        Tool(
            name="index_documents",
            description="Index a batch of documents into the vector database",
            inputSchema={
                "type": "object",
                "properties": {
                    "documents": {"type": "array", "items": {"type": "object"}},
                    "collection": {"type": "string"}
                },
                "required": ["documents"]
            }
        ),
        Tool(
            name="query_vectors",
                description="Query the vector database for nearest neighbors",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query text"},
                        "top_k": {"type": "number", "description": "Max results to return (alias for limit)"},
                        "limit": {"type": "number", "description": "Max results to return (alias for top_k)"},
                        "filters": {
                            "type": "object",
                            "description": "Metadata filters (e.g. {\"file_path\": [\"*.py\"], \"function_name\": [\"init\"]})"
                        },
                        "similarity_threshold": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                            "description": "Minimum similarity (0.0-1.0) to include results"
                        },
                        "include_context": {"type": "boolean", "description": "Whether to include surrounding context lines (pre/post)"}
                    },
                    "required": ["query"]
                }
        ),
        Tool(
            name="delete_index",
            description="Delete a collection or index",
            inputSchema={"type": "object", "properties": {"collection": {"type": "string"}}}
        ),
        Tool(
            name="list_collections",
            description="List collections in the vector database",
            inputSchema={"type": "object", "properties": {}}
        ),
    ]
