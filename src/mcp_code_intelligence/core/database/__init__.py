"""Database abstraction and ChromaDB implementation for MCP Code Intelligence."""

from mcp_code_intelligence.core.database.base import VectorDatabase, EmbeddingFunction
from mcp_code_intelligence.core.database.chroma import ChromaVectorDatabase
from mcp_code_intelligence.core.database.pooling import PooledChromaVectorDatabase

__all__ = [
    "VectorDatabase",
    "EmbeddingFunction",
    "ChromaVectorDatabase",
    "PooledChromaVectorDatabase",
]
