# Architecture: Hashing Strategy

This document explains the multi-layered hashing strategy used in MCP Code Intelligence to achieve both high-performance change detection and robust data deduplication.

## Dual-Layer Hashing

We use two different hashing algorithms for distinct purposes, balancing cryptographic integrity with computational speed.

| Layer | Algorithm | Purpose | Implementation | Standard |
|-------|-----------|---------|----------------|----------|
| **File Integrity** | **SHA-256** | Detect changes in source files (Incremental Indexing) | `MetadataManager` | Binary Read (rb) |
| **Data Deduplication** | **MD5** | Content-addressable chunk storage and surgical updates | `CodeChunk` | UTF-8 String |
| **Identifiers** | **SHA-256 (sliced)** | Deterministic IDs for directories and cache keys | `Directory`, `EmbeddingCache` | UTF-8 String |

## Why Two Algorithms?

### 1. SHA-256 for Integrity
SHA-256 is used as the "Gatekeeper". It ensures that even a single bit change in a large source file is detected reliably. Reading files in **binary mode** ensures that we are cross-platform compatible (handling line endings consistently).

### 2. MD5 for Deduplication
Once a file is confirmed to have changed, it is parsed into smaller chunks. We use MD5 for these chunks because:
- **Performance**: MD5 is significantly faster for hashing thousands of small code snippets.
- **Surgical Updates**: We compare chunk hashes against the Vector DB to skip re-embedding unchanged parts of a modified file.
- **Collision Risk**: In the context of small code chunks, the risk of a non-malicious collision that would break indexing is extremely low.

## Centralized Logic
All hashing operations must use the centralized utility module:
`src/mcp_code_intelligence/utils/hashing.py`

> [!WARNING]
> Never implement inline hashing logic. Always use the centralized functions to ensure consistent encoding (UTF-8) and file reading modes (Binary).
