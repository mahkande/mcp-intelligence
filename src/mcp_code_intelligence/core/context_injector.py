"""Context injection helper: generate targeted queries, run semantic search, and assemble context.

This module creates a compact, attributed context string by:
- Generating targeted search queries via the LLM
- Running semantic searches
- Optionally asking the LLM to rank results
- Assembling sanitized, attributed snippets with truncation
"""
from typing import Any
from loguru import logger
import re


async def gather_context_from_search(
    llm_client: Any,
    search_engine: Any,
    original_query: str,
    limit: int = 5,
    per_query: int = 5,
    max_chars: int = 20_000,
):
    """Generate context for LLM by running multiple targeted searches.

    Returns a string suitable for prepending to LLM messages. Snippets are
    sanitized to redact likely secrets and truncated to stay under `max_chars`.
    """
    try:
        # 1) Generate targeted search queries via LLM
        queries = await llm_client.generate_search_queries(original_query, limit=3)
        if not queries:
            queries = [original_query]

        # 2) Run searches for each query
        all_results: dict[str, list[Any]] = {}
        for q in queries:
            try:
                results = await search_engine.search(
                    query=q, limit=per_query, include_context=True
                )
                all_results[q] = results or []
            except Exception as e:
                logger.debug(f"Search failed for query '{q}': {e}")
                all_results[q] = []

        # 3) Let LLM analyze and rank results (if available)
        try:
            ranked = await llm_client.analyze_and_rank_results(
                original_query, all_results, top_n=limit
            )
        except Exception as e:
            logger.debug(f"Ranking failed: {e}")
            # Fallback: flatten top results
            ranked = []
            for q, res in all_results.items():
                for r in (res or [])[:per_query]:
                    ranked.append({"result": r})

        # 4) Assemble context text from ranked entries or fallback
        parts: list[str] = []
        chars = 0

        def sanitize(s: str) -> str:
            # Remove common secret patterns and long token-like strings
            s = re.sub(r"(?i)\b(api[_-]?key|secret|token|password)\b\s*[:=]\s*[^\n\r]+", "<REDACTED>", s)
            s = re.sub(r"[A-Za-z0-9_-]{40,}", "<REDACTED>", s)
            return s

        def append_snippet(file_path: str, start: int, end: int, lang: str, content: str, similarity: float | None = None, explanation: str | None = None) -> bool:
            nonlocal chars
            safe_content = sanitize(content or "")

            header_parts = [f"File: {file_path}", f"Lines: {start}-{end}"]
            if similarity is not None:
                header_parts.append(f"Similarity: {similarity:.3f}")
            if explanation:
                header_parts.append(f"Note: {explanation}")

            header = " | ".join(header_parts)
            snippet = f"{header}\n```{lang}\n{safe_content}\n```\n\n"

            if chars + len(snippet) > max_chars:
                return False
            parts.append(snippet)
            chars += len(snippet)
            return True

        if ranked:
            for item in ranked:
                # item may be {'result': SearchResult, 'query': ..., 'relevance':.., 'explanation':..}
                r = item.get("result") if isinstance(item, dict) and item.get("result") else item
                explanation = item.get("explanation") if isinstance(item, dict) else None
                try:
                    fp = getattr(r, "file_path", None) or (r.get("file_path") if isinstance(r, dict) else "")
                    start = getattr(r, "start_line", None) or (r.get("start_line") if isinstance(r, dict) else 0)
                    end = getattr(r, "end_line", None) or (r.get("end_line") if isinstance(r, dict) else 0)
                    lang = getattr(r, "language", None) or (r.get("language") if isinstance(r, dict) else "")
                    content = getattr(r, "content", None) or (r.get("content") if isinstance(r, dict) else "")
                    similarity = getattr(r, "similarity_score", None) or (r.get("similarity") if isinstance(r, dict) else None)
                except Exception:
                    continue

                if not append_snippet(str(fp), int(start or 0), int(end or 0), str(lang or ""), str(content or ""), similarity, explanation):
                    break
        else:
            # No ranking — flatten best results
            for q, res in all_results.items():
                for r in (res or [])[:per_query]:
                    try:
                        fp = getattr(r, "file_path", None) or (r.get("file_path") if isinstance(r, dict) else "")
                        start = getattr(r, "start_line", None) or (r.get("start_line") if isinstance(r, dict) else 0)
                        end = getattr(r, "end_line", None) or (r.get("end_line") if isinstance(r, dict) else 0)
                        lang = getattr(r, "language", None) or (r.get("language") if isinstance(r, dict) else "")
                        content = getattr(r, "content", None) or (r.get("content") if isinstance(r, dict) else "")
                        similarity = getattr(r, "similarity_score", None) or (r.get("similarity") if isinstance(r, dict) else None)
                    except Exception:
                        continue
                    if not append_snippet(str(fp), int(start or 0), int(end or 0), str(lang or ""), str(content or ""), similarity, None):
                        break

        context_text = "\n---\n".join(parts)
        return context_text

    except Exception as e:
        logger.error(f"Context gathering failed: {e}")
        return ""
