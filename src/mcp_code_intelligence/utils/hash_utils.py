"""Hash utilities for content hashing used in incremental indexing.

Provides an async MD5 content hash helper to avoid repeated sync I/O in
indexing pipelines. The hash algorithm is intentionally MD5 to keep the
value short and deterministic for quick lookups; collisions are unlikely
for individual chunk contents in this context.
"""
from __future__ import annotations

import asyncio
import hashlib
from typing import Any


async def get_content_hash(text: str) -> str:
    """Asynchronously compute MD5 hexdigest for the given text.

    The implementation uses asyncio.to_thread to avoid blocking the
    event loop for large inputs.
    """
    if text is None:
        return ""

    def _compute(s: str) -> str:
        m = hashlib.md5()
        m.update(s.encode("utf-8"))
        return m.hexdigest()

    return await asyncio.to_thread(_compute, text)
