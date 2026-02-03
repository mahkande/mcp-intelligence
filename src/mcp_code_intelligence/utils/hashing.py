"""Centralized hashing utilities for MCP Code Intelligence."""

import hashlib
from pathlib import Path


def calculate_file_sha256(file_path: Path) -> str:
    """Calculate SHA-256 hash of a file for integrity tracking.
    
    Reads in binary mode (rb) in 64kb chunks to be memory efficient and 
    consistent across platforms.
    """
    sha256 = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except Exception:
        return ""


def calculate_content_md5(content: str) -> str:
    """Calculate MD5 hash of text content for chunk deduplication.
    
    Encodes content as UTF-8 before hashing. MD5 is chosen for its speed 
    in surgical updates/deduplication where cryptographic strength is less critical.
    """
    if not content:
        return ""
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def calculate_id_hash(data: str, length: int = 16) -> str:
    """Calculate a deterministic hash for identifiers or cache keys.
    
    Uses SHA-256 but slices the result to a specified length (default 16).
    """
    if not data:
        return ""
    full_hash = hashlib.sha256(data.encode("utf-8")).hexdigest()
    return full_hash[:length]
