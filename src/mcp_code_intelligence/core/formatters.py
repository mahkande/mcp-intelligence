"""Formatters to convert LSP responses into MCP TextContent blocks.

This module provides helpers to convert LSP JSON-RPC responses for
definition/references/hover/completion into human-readable MCP `TextContent`
objects so the Code AI receives clean, actionable content.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, List
from urllib.parse import urlparse, unquote

from mcp.types import TextContent
try:
    from mcp.types import EmbeddedResource
    HAS_EMBEDDED = True
except Exception:
    EmbeddedResource = None  # type: ignore
    HAS_EMBEDDED = False


def _uri_to_path(uri: str) -> str:
    try:
        parsed = urlparse(uri)
        # For file URI, parsed.path gives the absolute path; unquote to decode %20 etc.
        path = unquote(parsed.path)
        # On Windows file:///C:/..., path may start with /C:/, strip leading slash
        if path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path.lstrip("/")
        return str(Path(path))
    except Exception:
        return uri


def format_locations(locations: Iterable[Any]) -> List[TextContent]:
    """Format LSP Location or LocationLink or list into TextContent entries.

    Each entry becomes `File: {path}, Line: {line}, Char: {char}`.
    """
    out: List[TextContent] = []
    for loc in locations or []:
        # LocationLink has targetUri/targetRange, Location has uri/range
        uri = None
        rng = None
        if isinstance(loc, dict):
            uri = loc.get("targetUri") or loc.get("uri")
            rng = loc.get("targetRange") or loc.get("range")

        if not uri:
            continue

        path = _uri_to_path(uri)
        line = None
        char = None
        if isinstance(rng, dict):
            start = rng.get("start") or {}
            line = start.get("line")
            char = start.get("character")

        if line is None or char is None:
            header = f"File: {path}"
            out.append(TextContent(type="text", text=header))
            continue

        # Present as 1-based line/char for readability
        header = f"File: {path}, Line: {line + 1}, Char: {char + 1}"

        # Try to read a small excerpt from the file around the target line
        try:
            p = Path(path)
            if p.exists():
                with p.open("r", encoding="utf-8", errors="ignore") as fh:
                    all_lines = fh.readlines()
                start = max(0, (line or 0) - 3)
                end = min(len(all_lines), (line or 0) + 4)
                excerpt_lines = all_lines[start:end]
                # Detect language from suffix
                suffix = p.suffix.lstrip(".") or ""
                lang = {
                    "py": "python",
                    "js": "javascript",
                    "ts": "typescript",
                    "cpp": "cpp",
                    "c": "c",
                    "java": "java",
                    "go": "go",
                    "rs": "rust",
                }.get(suffix, suffix)

                # Add line numbers and mark the target line
                numbered = []
                for idx, l in enumerate(excerpt_lines, start=start + 1):
                    marker = ""
                    if idx - 1 == line:
                        marker = "  # <--- Target"
                    numbered.append(f"{idx:4d}: {l.rstrip()}" + marker + "\n")

                code_block = "```" + (lang or "") + "\n" + "".join(numbered) + "```"

                # Provide a header TextContent and a code block. Prefer EmbeddedResource if available
                out.append(TextContent(type="text", text=header))
                if HAS_EMBEDDED and EmbeddedResource is not None:
                    try:
                        out.append(EmbeddedResource(name=p.name, media_type="text/plain", data="".join(excerpt_lines)))
                    except Exception:
                        out.append(TextContent(type="text", text=code_block))
                else:
                    out.append(TextContent(type="text", text=code_block))
                continue
        except Exception:
            # Fall back to header only
            out.append(TextContent(type="text", text=header))
            continue

    if not out:
        out.append(TextContent(type="text", text="The symbol you are looking for was not found in this file."))

    return out


def format_definition_response(resp: Any) -> List[TextContent]:
    # LSP may return a single location or a list
    if resp is None:
        return [TextContent(type="text", text="The symbol you are looking for was not found in this file.")]
    if isinstance(resp, dict) and "result" in resp:
        payload = resp["result"]
    else:
        payload = resp
    if isinstance(payload, list):
        return format_locations(payload)
    return format_locations([payload])


def format_references_response(resp: Any) -> List[TextContent]:
    # Similar to definitions, but summarize if too many results
    if resp is None:
        return [TextContent(type="text", text="The symbol you are looking for was not found in this file.")]
    payload = resp.get("result") if isinstance(resp, dict) and "result" in resp else resp
    if not payload:
        return [TextContent(type="text", text="The symbol you are looking for was not found in this file.")]

    if isinstance(payload, list):
        total = len(payload)
        # If too many results, provide a short summary and first few examples
        if total > 20:
            summary = TextContent(type="text", text=f"Total {total} references found. Showing first 5. Would you like to see more? (yes/no)")
            first_few = format_locations(payload[:5])
            return [summary] + first_few
        return format_locations(payload)

    return format_locations([payload])


def _extract_hover_text(contents: Any) -> str:
    # Contents can be string, dict, or array
    if contents is None:
        return ""
    if isinstance(contents, str):
        return contents
    if isinstance(contents, dict):
        # {kind: 'markdown'|'plaintext', value: '...'}
        return contents.get("value", "")
    if isinstance(contents, list):
        parts = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("value", ""))
        return "\n\n".join(p for p in parts if p)
    return str(contents)


def format_hover_response(resp: Any) -> List[TextContent]:
    if resp is None:
        return [TextContent(type="text", text="No hover information available.")]
    payload = resp.get("result") if isinstance(resp, dict) and "result" in resp else resp
    # payload may be {contents: ...}
    contents = None
    if isinstance(payload, dict):
        contents = payload.get("contents")
    else:
        contents = payload

    text = _extract_hover_text(contents)
    if not text:
        text = "No hover information available."

    return [TextContent(type="text", text=text)]


def format_completions_response(resp: Any, limit: int = 10) -> List[TextContent]:
    if resp is None:
        return [TextContent(type="text", text="No completions available.")]
    payload = resp.get("result") if isinstance(resp, dict) and "result" in resp else resp
    items = []
    if isinstance(payload, dict) and "items" in payload:
        items = payload.get("items", [])
    elif isinstance(payload, list):
        items = payload

    if not items:
        return [TextContent(type="text", text="No completions available.")]

    lines = []
    for it in items[:limit]:
        if isinstance(it, dict):
            label = it.get("label", "")
            detail = it.get("detail") or (it.get("documentation") or "")
            if isinstance(detail, dict):
                detail = detail.get("value", "")
            line = f"- {label}"
            if detail:
                line += f": {detail}"
            lines.append(line)
        else:
            lines.append(f"- {str(it)}")

    return [TextContent(type="text", text="Completions:\n" + "\n".join(lines))]


def format_lsp_error(e: Exception) -> List[TextContent]:
    return [TextContent(type="text", text=f"LSP error: {str(e)}")]
