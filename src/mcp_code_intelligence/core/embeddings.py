"""Embedding generation for MCP Code Intelligence."""

import hashlib
import json
import multiprocessing
import os
from pathlib import Path


# Configure tokenizers parallelism based on process context
# Enable parallelism in main process for 2-4x speedup
# Disable in forked processes to avoid deadlock warnings
# See: https://github.com/huggingface/tokenizers/issues/1294
def _configure_tokenizers_parallelism() -> None:
    """Configure TOKENIZERS_PARALLELISM based on process context."""
    # Check if we're in the main process
    is_main_process = multiprocessing.current_process().name == "MainProcess"

    if is_main_process:
        # Enable parallelism in main process for better performance
        # This gives 2-4x speedup for embedding generation
        os.environ["TOKENIZERS_PARALLELISM"] = "true"
    else:
        # Disable in forked processes to avoid deadlock
        os.environ["TOKENIZERS_PARALLELISM"] = "false"


# Configure before importing sentence_transformers
_configure_tokenizers_parallelism()

import aiofiles
from loguru import logger
# Defer SentenceTransformer import to avoid NumPy circular import issues
# from sentence_transformers import SentenceTransformer

from .exceptions import EmbeddingError


class EmbeddingCache:
    """LRU cache for embeddings with disk persistence."""

    def __init__(self, cache_dir: Path, max_size: int = 1000) -> None:
        """Initialize embedding cache.

        Args:
            cache_dir: Directory to store cached embeddings
            max_size: Maximum number of embeddings to keep in memory
        """
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_size = max_size
        self._memory_cache: dict[str, list[float]] = {}
        self._access_order: list[str] = []  # For LRU eviction
        self._cache_hits = 0
        self._cache_misses = 0

    def _hash_content(self, content: str) -> str:
        """Generate cache key from content."""
        from mcp_code_intelligence.utils.hashing import calculate_id_hash
        return calculate_id_hash(content)

    async def get_embedding(self, content: str) -> list[float] | None:
        """Get cached embedding for content."""
        cache_key = self._hash_content(content)

        # Check memory cache first
        if cache_key in self._memory_cache:
            self._cache_hits += 1
            # Move to end for LRU
            self._access_order.remove(cache_key)
            self._access_order.append(cache_key)
            return self._memory_cache[cache_key]

        # Check disk cache
        cache_file = self.cache_dir / f"{cache_key}.json"
        if cache_file.exists():
            try:
                async with aiofiles.open(cache_file) as f:
                    content_str = await f.read()
                    embedding = json.loads(content_str)

                    # Add to memory cache with LRU management
                    self._add_to_memory_cache(cache_key, embedding)
                    self._cache_hits += 1
                    return embedding
            except Exception as e:
                logger.warning(f"Failed to load cached embedding: {e}")

        self._cache_misses += 1
        return None

    async def store_embedding(self, content: str, embedding: list[float]) -> None:
        """Store embedding in cache."""
        cache_key = self._hash_content(content)

        # Store in memory cache with LRU management
        self._add_to_memory_cache(cache_key, embedding)

        # Store in disk cache
        cache_file = self.cache_dir / f"{cache_key}.json"
        try:
            async with aiofiles.open(cache_file, "w") as f:
                await f.write(json.dumps(embedding))
        except Exception as e:
            logger.warning(f"Failed to cache embedding: {e}")

    def _add_to_memory_cache(self, cache_key: str, embedding: list[float]) -> None:
        """Add embedding to memory cache with LRU eviction.

        Args:
            cache_key: Cache key for the embedding
            embedding: Embedding vector to cache
        """
        # If already in cache, update and move to end
        if cache_key in self._memory_cache:
            self._access_order.remove(cache_key)
            self._access_order.append(cache_key)
            self._memory_cache[cache_key] = embedding
            return

        # If cache is full, evict least recently used
        if len(self._memory_cache) >= self.max_size:
            lru_key = self._access_order.pop(0)
            del self._memory_cache[lru_key]

        # Add new embedding
        self._memory_cache[cache_key] = embedding
        self._access_order.append(cache_key)

    def clear_memory_cache(self) -> None:
        """Clear the in-memory cache."""
        self._memory_cache.clear()
        self._access_order.clear()

    def get_cache_stats(self) -> dict[str, any]:
        """Get cache performance statistics.

        Returns:
            Dictionary with cache statistics
        """
        total_requests = self._cache_hits + self._cache_misses
        hit_rate = self._cache_hits / total_requests if total_requests > 0 else 0.0
        disk_files = (
            len(list(self.cache_dir.glob("*.json"))) if self.cache_dir.exists() else 0
        )

        return {
            "memory_cache_size": len(self._memory_cache),
            "memory_cached": len(self._memory_cache),  # Alias for compatibility
            "max_cache_size": self.max_size,
            "memory_limit": self.max_size,  # Alias for compatibility
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "hit_rate": round(hit_rate, 3),
            "disk_cache_files": disk_files,
            "disk_cached": disk_files,  # Alias for compatibility
        }


class CodeBERTEmbeddingFunction:
    """ChromaDB-compatible embedding function using CodeBERT."""

    def __init__(
        self,
        model_name: str = "jinaai/jina-embeddings-v3",
        timeout: float = 300.0,  # 5 minutes default timeout
        **kwargs
    ) -> None:
        """Initialize embedding function.

        Args:
            model_name: Name of the sentence transformer model
            timeout: Timeout in seconds for embedding generation (default: 300s)
            **kwargs: Additional arguments passed to SentenceTransformer
        """
        try:
            import time
            logger.info(f"🔄 [INIT] Starting CodeBERTEmbeddingFunction init for: {model_name}")
            init_start = time.time()
            
            # Import here to avoid NumPy circular import issues during module load
            logger.info("📦 [INIT] Importing SentenceTransformer...")
            from sentence_transformers import SentenceTransformer
            import_elapsed = time.time() - init_start
            logger.info(f"✅ [INIT] SentenceTransformer imported in {import_elapsed:.2f}s")
            
            # Jina and other modern models require trust_remote_code
            trust_remote = "jina" in model_name.lower() or "bge" in model_name.lower()
            
            # Merge trust_remote_code into kwargs if not present
            if "trust_remote_code" not in kwargs:
                kwargs["trust_remote_code"] = trust_remote
            
            logger.info(f"⏳ [INIT] Loading model {model_name} with kwargs: {kwargs}")
            model_start = time.time()
            self.model = SentenceTransformer(model_name, **kwargs)
            model_elapsed = time.time() - model_start
            logger.info(f"✅ [INIT] Model loaded in {model_elapsed:.2f}s")
            
            self.model_name = model_name
            self._name = model_name.replace("/", "_")  # Internal name storage
            self.timeout = timeout
            
            total_elapsed = time.time() - init_start
            logger.info(f"🎉 [INIT] CodeBERTEmbeddingFunction ready in {total_elapsed:.2f}s (timeout: {timeout}s)")
        except Exception as e:
            logger.error(f"❌ [INIT] Failed to load embedding model {model_name}: {e}")
            raise EmbeddingError(f"Failed to load embedding model: {e}") from e

    # @property removed to satisfy chromadb interface which calls name()
    def name(self) -> str:
        """Return the model name for ChromaDB compatibility."""
        return self._name

    def __call__(self, input: list[str]) -> list[list[float]]:
        """Generate embeddings for input texts (ChromaDB interface)."""
        try:
            # Use ThreadPoolExecutor with timeout for embedding generation
            from concurrent.futures import ThreadPoolExecutor, TimeoutError

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self._generate_embeddings, input)
                try:
                    embeddings = future.result(timeout=self.timeout)
                    return embeddings
                except TimeoutError:
                    logger.error(
                        f"Embedding generation timed out after {self.timeout}s for batch of {len(input)} texts"
                    )
                    raise EmbeddingError(
                        f"Embedding generation timed out after {self.timeout}s"
                    )
        except EmbeddingError:
            raise
        except Exception as e:
            logger.error(f"Failed to generate embeddings: {e}")
            raise EmbeddingError(f"Failed to generate embeddings: {e}") from e

    def _generate_embeddings(self, input: list[str]) -> list[list[float]]:
        """Internal method to generate embeddings (runs in thread pool)."""
        # BGE models recommend normalization for better performance
        normalize = "bge" in self.model_name.lower()
        embeddings = self.model.encode(input, convert_to_numpy=True, normalize_embeddings=normalize)
        return embeddings.tolist()

    def embed_query(self, query: str) -> list[float]:
        """Embed a single query string (ChromaDB interface for search queries)."""
        # ChromaDB expects a single embedding vector for queries
        result = self.__call__([query])
        return result[0] if result else []


class BatchEmbeddingProcessor:
    """Batch processing for efficient embedding generation with caching."""

    def __init__(
        self,
        embedding_function: CodeBERTEmbeddingFunction,
        cache: EmbeddingCache | None = None,
        batch_size: int = 32,
    ) -> None:
        """Initialize batch embedding processor.

        Args:
            embedding_function: Function to generate embeddings
            cache: Optional embedding cache
            batch_size: Size of batches for processing
        """
        self.embedding_function = embedding_function
        self.cache = cache
        self.batch_size = batch_size

    async def process_batch(self, contents: list[str]) -> list[list[float]]:
        """Process a batch of content for embeddings.

        Args:
            contents: List of text content to embed

        Returns:
            List of embeddings
        """
        if not contents:
            return []

        embeddings = []
        uncached_contents = []
        uncached_indices = []

        # Check cache for each content if cache is available
        if self.cache:
            for i, content in enumerate(contents):
                cached_embedding = await self.cache.get_embedding(content)
                if cached_embedding:
                    embeddings.append(cached_embedding)
                else:
                    embeddings.append(None)  # Placeholder
                    uncached_contents.append(content)
                    uncached_indices.append(i)
        else:
            # No cache, process all content
            uncached_contents = contents
            uncached_indices = list(range(len(contents)))
            embeddings = [None] * len(contents)

        # Generate embeddings for uncached content
        if uncached_contents:
            logger.debug(f"Generating {len(uncached_contents)} new embeddings")

            try:
                new_embeddings = []
                for i in range(0, len(uncached_contents), self.batch_size):
                    batch = uncached_contents[i : i + self.batch_size]
                    batch_embeddings = self.embedding_function(batch)
                    new_embeddings.extend(batch_embeddings)

                # Cache new embeddings and fill placeholders
                for i, (content, embedding) in enumerate(
                    zip(uncached_contents, new_embeddings, strict=False)
                ):
                    if self.cache:
                        await self.cache.store_embedding(content, embedding)
                    embeddings[uncached_indices[i]] = embedding

            except Exception as e:
                logger.error(f"Failed to generate embeddings: {e}")
                raise EmbeddingError(f"Failed to generate embeddings: {e}") from e

        return embeddings

    def get_stats(self) -> dict[str, any]:
        """Get processor statistics."""
        stats = {
            "model_name": self.embedding_function.model_name,
            "batch_size": self.batch_size,
            "cache_enabled": self.cache is not None,
        }

        if self.cache:
            stats.update(self.cache.get_cache_stats())

        return stats


def create_embedding_function(
    model_name: str = "jinaai/jina-embeddings-v3",
    cache_dir: Path | None = None,
    cache_size: int = 1000,
):
    """Create embedding function and cache.

    Args:
        model_name: Name of the embedding model (default: jinaai/jina-embeddings-v3)
        cache_dir: Directory for caching embeddings
        cache_size: Maximum cache size

    Returns:
        Tuple of (embedding_function, cache)
    """
    
    # Inner function to attempt loading a specific model
    def _try_load_model(name: str):
        # Specific fix for Jina V3 on Windows/CPU
        if "jina" in name.lower() or "codebert" in name.lower():
             logger.info(f"Detected complex model '{name}'. Using custom loader with Windows/CPU fix.")
             # low_cpu_mem_usage=False prevents "meta tensor" error with accelerate
             return CodeBERTEmbeddingFunction(
                 name, 
                 device="cpu",
                 model_kwargs={
                     "low_cpu_mem_usage": False,
                     "trust_remote_code": True
                 }
             )

        # For other models, try consistent ChromaDB wrapper if possible
        from chromadb.utils import embedding_functions

        # Map legacy model names to working alternatives
        model_mapping = {
            "microsoft/codebert-base": "sentence-transformers/all-MiniLM-L6-v2",
            "microsoft/unixcoder-base": "sentence-transformers/all-MiniLM-L6-v2",
        }

        actual_model = model_mapping.get(name, name)
        trust_remote = "jina" in actual_model.lower() or "bge" in actual_model.lower()
        
        logger.info(f"Attempting to load embedding model: {actual_model}")
        
        # For BGE models, ChromaDB's SentenceTransformer will use the model's
        # default config which includes normalization
        return embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=actual_model,
            trust_remote_code=trust_remote,
            device="cpu" 
        )

    embedding_function = None
    try:
        embedding_function = _try_load_model(model_name)
        logger.debug(f"Created ChromaDB embedding function with model: {model_name}")

    except Exception as e:
        logger.warning(f"Failed to create ChromaDB embedding function with {model_name}: {e}")
        
        # Fallback to the most stable model known
        fallback_model = "sentence-transformers/all-MiniLM-L6-v2"
        if model_name != fallback_model:
            try:
                logger.info(f"Falling back to stable model: {fallback_model}")
                embedding_function = _try_load_model(fallback_model)
            except Exception as e2:
                logger.error(f"Fallback model also failed: {e2}")
                # Last resort custom implementation
                embedding_function = CodeBERTEmbeddingFunction(fallback_model) 

    if embedding_function is None:
        # If everything failed, try custom implementation with SAFE model
        logger.warning("All ChromaDB attempts failed. Using custom implementation with SAFE model.")
        embedding_function = CodeBERTEmbeddingFunction("sentence-transformers/all-MiniLM-L6-v2")


    cache = None
    if cache_dir:
        cache = EmbeddingCache(cache_dir, cache_size)

    return embedding_function, cache

