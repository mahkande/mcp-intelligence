"""ProtocolService: Handles JSON-RPC and MCP protocol details."""

import json
import re
from typing import Any
from pathlib import Path

from mcp.types import CallToolResult, TextContent
from loguru import logger


class ProtocolService:
    """Manages JSON-RPC and MCP protocol details and transformations."""

    @staticmethod
    def build_text_response(text: str) -> CallToolResult:
        """Build a text response and log preview/length."""
        preview = text[:100].replace('\n', ' ')
        logger.info(f"[ProtocolService] build_text_response: First 100 characters: '{preview}' | Total size: {len(text)}")
        return CallToolResult(
            content=[TextContent(type="text", text=text)]
        )

    @staticmethod
    def build_error_response(error_text: str) -> CallToolResult:
        """Build an error response.

        Args:
            error_text: Error message

        Returns:
            CallToolResult marked as error
        """
        return CallToolResult(
            content=[TextContent(type="text", text=error_text)],
            isError=True,
        )

    @staticmethod
    def extract_lsp_tool_params(tool_name: str, arguments: dict[str, Any]) -> tuple[str, str, dict[str, Any]] | None:
        """Extract LSP tool parameters from tool name and arguments.

        Args:
            tool_name: MCP tool name
            arguments: Tool arguments

        Returns:
            Tuple of (language, method, params) or None if not an LSP tool
        """
        m = re.match(
            r"(?P<lang>[a-z0-9_+-]+)_(?P<action>goto_definition|find_references|get_hover_info|get_completions)",
            tool_name
        )

        if not m:
            return None

        lang = m.group("lang")
        action = m.group("action")

        # Map action to LSP method
        action_to_method = {
            "goto_definition": "textDocument/definition",
            "find_references": "textDocument/references",
            "get_hover_info": "textDocument/hover",
            "get_completions": "textDocument/completion",
        }

        method = action_to_method.get(action)
        if not method:
            return None

        # Extract LSP parameters
        file = arguments.get("file")
        line = arguments.get("line")
        character = arguments.get("character")

        if not file or line is None or character is None:
            return None

        # Build LSP params
        params = {
            "textDocument": {"uri": f"file://{file}"},
            "position": {"line": line, "character": character},
        }

        return lang, method, params

    @staticmethod
    def validate_tool_arguments(tool_name: str, arguments: dict[str, Any]) -> tuple[bool, str | None]:
        """Validate tool arguments.

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Required arguments by tool
        required_args = {
            "search_code": ["query"],
            "search_similar": ["file_path"],
            "search_context": ["symbol_name"],
            "find_symbol": ["name"],
            "get_relationships": ["name"],
            "analyze_file": ["file_path"],
        }

        if tool_name in required_args:
            missing = [arg for arg in required_args[tool_name] if arg not in arguments]
            if missing:
                return False, f"Missing required arguments: {', '.join(missing)}"

        return True, None

    @staticmethod
    def build_search_filters(args: dict[str, Any]) -> dict[str, Any]:
        """Build search filters from tool arguments.

        Args:
            args: Tool arguments containing filter options

        Returns:
            Dictionary of search filters
        """
        filters = {}

        if file_extensions := args.get("file_extensions"):
            filters["file_extension"] = {"$in": file_extensions}

        if language := args.get("language"):
            filters["language"] = language

        if function_name := args.get("function_name"):
            filters["function_name"] = function_name

        if class_name := args.get("class_name"):
            filters["class_name"] = class_name

        if files := args.get("files"):
            filters["file_pattern"] = files

        return filters

    @staticmethod
    def format_search_result(result: Any, index: int) -> list[str]:
        """Format a search result for output.

        Args:
            result: Search result object
            index: Result index (1-based)

        Returns:
            List of formatted text lines
        """
        lines = [f"## Result {index} (Score: {result.similarity_score:.3f})"]
        lines.append(f"**File:** {result.file_path}")

        if result.function_name:
            lines.append(f"**Function:** {result.function_name}")

        if result.class_name:
            lines.append(f"**Class:** {result.class_name}")

        lines.append(f"**Lines:** {result.start_line}-{result.end_line}")
        lines.append("**Code:**")
        lines.append("```" + (result.language or ""))

        # Truncate content for display
        content_preview = (
            result.content[:500]
            if len(result.content) > 500
            else result.content
        )
        lines.append(content_preview + ("..." if len(result.content) > 500 else ""))
        lines.append("```\n")

        return lines

    @staticmethod
    def resolve_file_path(file_path_str: str, project_root: Path) -> Path | None:
        """Resolve a file path relative to project root.

        Args:
            file_path_str: File path string (absolute or relative)
            project_root: Project root directory

        Returns:
            Resolved Path object or None if file doesn't exist
        """
        file_path = Path(file_path_str)

        if not file_path.is_absolute():
            file_path = project_root / file_path

        if file_path.exists():
            return file_path

        return None

    @staticmethod
    def parse_json_safely(json_str: str) -> dict[str, Any] | None:
        """Safely parse JSON string.

        Args:
            json_str: JSON string to parse

        Returns:
            Parsed dictionary or None if invalid
        """
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error: {e}")
            return None
