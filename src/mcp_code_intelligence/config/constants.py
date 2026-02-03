"""Project-wide constants for MCP Code Intelligence.

This module contains all magic numbers and configuration constants
used throughout the application to improve maintainability and clarity.
"""

# Timeout Constants (in seconds)
SUBPROCESS_INSTALL_TIMEOUT = 120  # Timeout for package installation commands
SUBPROCESS_SHORT_TIMEOUT = 10  # Short timeout for quick commands (version checks, etc.)
SUBPROCESS_MCP_TIMEOUT = 30  # Timeout for MCP server operations
SUBPROCESS_TEST_TIMEOUT = 5  # Timeout for server test operations
CONNECTION_POOL_TIMEOUT = 30.0  # Connection pool acquisition timeout

# Chunking Constants
DEFAULT_CHUNK_SIZE = 50  # Default number of lines per code chunk
TEXT_CHUNK_SIZE = 30  # Number of lines per text/markdown chunk
SEARCH_RESULT_LIMIT = 20  # Default number of search results to return

# Threshold Constants
DEFAULT_SIMILARITY_THRESHOLD = 0.5  # Default similarity threshold for search (0.0-1.0)
HIGH_SIMILARITY_THRESHOLD = 0.75  # Higher threshold for more precise matches

# Cache Constants
DEFAULT_CACHE_SIZE = 256  # Default LRU cache size for file reads
# Default reranker model (optional). If set to a Jina model id, the engine
# will attempt to use Jina's reranker path when available, otherwise it will
# safely fall back to the HF `transformers` cross-encoder or heuristic reranking.
# Set to None to disable automatic neural reranker by default.
DEFAULT_RERANKER_MODEL = "jinaai/jina-reranker-v2-base-multilingual"

