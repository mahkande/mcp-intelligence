"""Helper to create and attach an LLMClient to server instances.

This centralizes the logic for reading API keys from project config or
environment and wiring the `search_engine` (if present) into the LLM client
so context injection works consistently across MCP servers.
"""
from pathlib import Path
from typing import Any
from loguru import logger

from mcp_code_intelligence.core.llm_client import LLMClient
from mcp_code_intelligence.core.config_utils import (
    get_openai_api_key,
    get_openrouter_api_key,
    get_preferred_llm_provider,
)
from mcp_code_intelligence.core.project import ProjectManager



def wire_llm_to_server(server: Any, project_root: Path | None = None) -> None:
    """Create an LLMClient (if API keys present) and attach it to `server`.

    Args:
        server: The server instance (will receive attribute `llm_client`)
        project_root: Path used to find project config (defaults to cwd)
    """
    try:
        if project_root is None:
            project_root = Path.cwd()
        config_dir = Path(project_root) / ".mcp-code-intelligence"
        # If project is initialized and config explicitly disables server LLMs,
        # honor that setting regardless of API keys.
        try:
            pm = ProjectManager(project_root)
            if pm.is_initialized():
                cfg = pm.load_config()
                if getattr(cfg, "disable_server_llm", False):
                    logger.info("Project config requests server-side LLM disabled; skipping wiring")
                    return
        except Exception:
            # Ignore config load errors and continue to check env keys
            pass
        openai_key = get_openai_api_key(config_dir)
        openrouter_key = get_openrouter_api_key(config_dir)
        preferred = get_preferred_llm_provider(config_dir)

        if not (openai_key or openrouter_key):
            logger.debug("No LLM API keys found for project; skipping LLM wiring")
            return

        client = LLMClient(
            openai_api_key=openai_key,
            openrouter_api_key=openrouter_key,
            provider=preferred if preferred in ("openai", "openrouter") else None,
        )

        # Attach to server
        try:
            setattr(server, "llm_client", client)
        except Exception:
            logger.warning("Failed to set llm_client attribute on server instance")

        # If the server exposes a search_engine, attach it for context injection
        try:
            se = getattr(server, "search_engine", None)
            if se is not None:
                try:
                    client.search_engine = se
                except Exception:
                    logger.debug("Could not attach search_engine to LLM client")

        except Exception:
            pass

        logger.info("LLM client wired to server (if keys present)")

    except Exception as e:
        logger.warning(f"LLM wiring failed: {e}")
