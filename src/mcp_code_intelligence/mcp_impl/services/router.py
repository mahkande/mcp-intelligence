"""RoutingService: Handles request routing to appropriate tool handlers."""

from typing import Any
from mcp.types import CallToolRequest, CallToolResult

from loguru import logger


class RoutingService:
    """Routes incoming MCP tool requests to appropriate handlers."""

    def __init__(self, handler_map: dict[str, Any] | None = None):
        """Initialize routing service.

        Args:
            handler_map: Dictionary mapping tool names to handler methods
        """
        self.handler_map = handler_map or {}

    def register_handler(self, tool_name: str, handler: Any) -> None:
        """Register a handler for a tool.

        Args:
            tool_name: Name of the tool
            handler: Async handler function
        """
        self.handler_map[tool_name] = handler
        logger.debug(f"Registered handler for tool: {tool_name}")

    async def route_tool_call(self, request: CallToolRequest) -> CallToolResult:
        """Route a tool call to the appropriate handler.

        Args:
            request: The MCP tool request

        Returns:
            CallToolResult with the result or error
        """
        tool_name = request.params.name
        args = request.params.arguments or {}

        # Log tool call start
        logger.info(f"🛠️  [Tool Call] {tool_name} matching activity...")
        if args:
            logger.debug(f"   Args: {args}")

        # Check if handler is registered
        if tool_name not in self.handler_map:
            logger.warning(f"❌ Unknown tool: {tool_name}")
            return CallToolResult(
                content=[{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                isError=True,
            )

        try:
            handler = self.handler_map[tool_name]
            result = await handler(args)
            
            # Log success
            if result.isError:
                logger.error(f"⚠️  [Tool Result] {tool_name} failed with error")
            else:
                logger.success(f"✅ [Tool Result] {tool_name} completed successfully")
            
            return result
        except Exception as e:
            logger.error(f"🔥 [Tool Handler Error] {tool_name}: {e}")
            return CallToolResult(
                content=[{"type": "text", "text": f"Tool execution failed: {str(e)}"}],
                isError=True,
            )

    def get_route_info(self) -> dict[str, str]:
        """Get information about registered routes.

        Returns:
            Dictionary of tool names and their handler status
        """
        return {
            tool_name: "registered"
            for tool_name in self.handler_map.keys()
        }

    def get_supported_tools(self) -> list[str]:
        """Get list of supported tools.

        Returns:
            List of tool names that have registered handlers
        """
        return list(self.handler_map.keys())
