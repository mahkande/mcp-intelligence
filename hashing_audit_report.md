# Hashing Audit & Conflict Analysis Report

## Executive Summary
The hashing logic in the "MCP Code Intelligence" project is multi-layered and consistently implemented. The new `MetadataManager` (SHA-256) and the existing `CodeChunk` tracking (MD5) operate at different granularities and do not conflict.

## 1. Current Hashing Landscape

| Component | Scope | Algorithm | Purpose | Storage / Variable |
|-----------|-------|-----------|---------|---------------------|
| **MetadataManager** | File-level | **SHA-256** | Change detection (Incremental Indexing) | `metadata.json` / `"hash"` |
| **CodeChunk** | Chunk-level | **MD5** | Content-addressable recall, deduplication | ChromaDB / `"content_hash"` |
| **Directory Index** | Path-level | **SHA-256 (Sliced)** | Unique ID generation for directories | `directory.json` / `"id"` |
| **Embedding Cache** | Content-level | **SHA-256 (Sliced)** | Cache key for vector embeddings | `.cache/` / filename |

## 2. Compatibility & Interaction
The two main systems (File-level vs. Chunk-level) are highly compatible:

1.  **Gatekeeper Mode**: `MetadataManager` (SHA-256) first checks if a file has changed. If the hash matches, the system skips all subsequent work (LSP parsing, chunking, embedding).
2.  **Surgical Update**: If the file hash differs, the `Indexer` parses the file. Each chunk's **MD5** `content_hash` is then compared against existing chunks in the database to perform surgical updates.

## 3. Conflict Analysis (Variable Names)
I have checked for naming collisions in the following files:
- `src/mcp_code_intelligence/core/metadata_manager.py`
- `src/mcp_code_intelligence/core/models.py`
- `src/mcp_code_intelligence/core/database/chroma.py`

**Key Findings:**
- **No Overwriting**: `MetadataManager` stores its data separately in `metadata.json`. It does not write to the Vector DB directly.
- **Distinct Names**: The file-level hash is stored as `hash` in the JSON, while the chunk-level hash is `content_hash` in the database.
- **Independent Life-cycles**: Deleting a record in `metadata.json` triggers a file-level re-scan, but the database's `content_hash` remains the source of truth for chunk integrity.

## 4. Conclusion
The implementation of SHA-256 in `MetadataManager` follows best practices and is technically isolated from the MD5 logical layer used for fine-grained chunk tracking. They work in tandem to provide a robust, dual-layered incremental indexing system.
