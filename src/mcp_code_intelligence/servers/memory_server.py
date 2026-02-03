"""Memory MCP Server - Python implementation.

Provides persistent key-value storage via MCP protocol.
Uses SQLite for reliable storage.
"""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from loguru import logger
logger.remove()

import logging
class InterceptHandler(logging.Handler):
    def emit(self, record):
        logger.opt(depth=6, exception=record.exc_info).log(record.levelname, record.getMessage())
logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO)

import builtins
_orig_print = builtins.print
def mcp_print(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    _orig_print(*args, **kwargs)
builtins.print = mcp_print

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from mcp_code_intelligence.core.llm_factory import wire_llm_to_server

# Optional dependency for relationship graphs; discovery-time safe import
try:
    import networkx as nx  # type: ignore
    NX_AVAILABLE = True
except Exception:
    nx = None
    NX_AVAILABLE = False


class MemoryServer:
    """MCP Server for persistent memory/knowledge graph."""

    def __init__(self, db_path: Path | None = None):
        """Initialize memory server.

        Args:
            db_path: Path to SQLite database (default: ~/.mcp_memory.db)
        """
        if db_path is None:
            db_path = Path.home() / ".mcp_memory.db"

        self.db_path = Path(db_path)
        self.server = Server("memory")
        self._init_database()
        self._setup_handlers()

        # Setup activity logging
        try:
            # Memory DB usually in project root .mcp-code-intelligence/memory.db
            # but default is home dir. Let's try to detect project root.
            project_root = self.db_path.parent.parent if ".mcp-code-intelligence" in str(self.db_path) else Path.cwd()
            from mcp_code_intelligence.core.logging_setup import setup_activity_logging
            setup_activity_logging(project_root, "memory")
        except Exception:
            pass

        # Attempt to wire an LLM client if API keys are available
        try:
            wire_llm_to_server(self, project_root=self.db_path.parent)
        except Exception:
            pass

    def _init_database(self):
        """Initialize SQLite database."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Dedicated relationships table for fast queries (Option B)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS relationships (
                key TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                source_id TEXT,
                target_id TEXT,
                relationship_type TEXT,
                note TEXT,
                navigation_hint TEXT,
                content_hash TEXT,
                symbol_type TEXT,
                vector_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Indexes to speed up lookups by content_hash, navigation_hint and vector_id
        conn.execute("CREATE INDEX IF NOT EXISTS idx_relationships_content_hash ON relationships(content_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_relationships_navigation ON relationships(navigation_hint)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_relationships_vector_id ON relationships(vector_id)")
        conn.commit()
        conn.close()

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        return sqlite3.connect(self.db_path)

    def _setup_handlers(self):
        """Setup MCP protocol handlers."""

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """List available memory tools."""
            return [
                Tool(
                    name="store",
                    description="Store a value with a key",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "Key to store value under"
                            },
                            "value": {
                                "type": "string",
                                "description": "Value to store (will be JSON stringified)"
                            }
                        },
                        "required": ["key", "value"]
                    }
                ),
                Tool(
                    name="retrieve",
                    description="Retrieve a value by key",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "Key to retrieve"
                            }
                        },
                        "required": ["key"]
                    }
                ),
                Tool(
                    name="delete",
                    description="Delete a key-value pair",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "Key to delete"
                            }
                        },
                        "required": ["key"]
                    }
                ),
                Tool(
                    name="list_keys",
                    description="List all stored keys",
                    inputSchema={"type": "object", "properties": {}}
                ),
            ]

        # Extended tools for Memory server (entity relationships and recalls)
        @self.server.list_tools()
        async def extended_tools() -> list[Tool]:
            # Discovery-safe: if networkx is missing, advertise fix tool instead
            if not NX_AVAILABLE:
                return [
                    Tool(
                        name="fix_memory_package_missing",
                        description=(
                            "Optional memory relationship features unavailable: networkx not installed. "
                            "Install with: pip install networkx"
                        ),
                        inputSchema={"type": "object", "properties": {}},
                    )
                ]

            return [
                Tool(
                    name="store_thought",
                    description="Store a thought or short note in memory",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "value": {"type": "string"},
                            "tags": {"type": "array", "items": {"type": "string"}},
                            "content_hash": {"type": "string", "description": "Optional MD5/sha hash of the content for content-addressable recall"},
                        },
                        "required": ["key", "value"],
                    },
                ),
                Tool(
                    name="create_entity_relationship",
                    description="Create an entity relationship (optionally tied to a navigation_hint)",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "source": {"type": "string"},
                            "target": {"type": "string"},
                            "note": {"type": "string"},
                            "navigation_hint": {"type": "string", "description": "Optional file:line hint to tie this relation to code"},
                            "content_hash": {"type": "string", "description": "Optional MD5/sha hash of the code this relation refers to"},
                            "symbol_type": {"type": "string", "description": "Optional symbol type from LSP (function, class, method)"},
                            "vector_id": {"type": "string", "description": "Optional vector database id/reference to associate this relationship with a vector result"},
                        },
                        "required": ["source", "target"],
                    },
                ),
                Tool(
                    name="recall_memories",
                    description="Recall memories by query, navigation hint, or content_hash",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "navigation_hint": {"type": "string"},
                            "content_hash": {"type": "string", "description": "Optional content hash to find content-addressable memories"},
                            "limit": {"type": "number"},
                        },
                    },
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> list[TextContent]:
            """Handle tool calls."""
            from loguru import logger
            import json
            logger.info(f"🧠 [Memory] {name} (Args: {json.dumps(arguments or {})[:100]}...)")

            try:
                conn = self._get_connection()

                if name == "store":
                    key = arguments["key"]
                    value = arguments["value"]

                    # Store as JSON string
                    if not isinstance(value, str):
                        value = json.dumps(value)

                    conn.execute("""
                        INSERT OR REPLACE INTO memory (key, value, updated_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                    """, (key, value))
                    conn.commit()
                    conn.close()

                    return [TextContent(type="text", text=f"Stored: {key}")]

                elif name == "retrieve":
                    key = arguments["key"]

                    cursor = conn.execute(
                        "SELECT value FROM memory WHERE key = ?",
                        (key,)
                    )
                    row = cursor.fetchone()
                    conn.close()

                    if row is None:
                        return [TextContent(type="text", text=f"Key not found: {key}")]

                    return [TextContent(type="text", text=row[0])]

                elif name == "delete":
                    key = arguments["key"]

                    cursor = conn.execute(
                        "DELETE FROM memory WHERE key = ?",
                        (key,)
                    )
                    conn.commit()
                    deleted = cursor.rowcount
                    conn.close()

                    if deleted == 0:
                        return [TextContent(type="text", text=f"Key not found: {key}")]

                    return [TextContent(type="text", text=f"Deleted: {key}")]

                elif name == "list_keys":
                    cursor = conn.execute(
                        "SELECT key, created_at FROM memory ORDER BY key"
                    )
                    rows = cursor.fetchall()
                    conn.close()

                    if not rows:
                        return [TextContent(type="text", text="No keys stored")]

                    keys_list = "\n".join(f"{key} (created: {created})" for key, created in rows)
                    return [TextContent(type="text", text=keys_list)]

                elif name == "store_thought":
                    key = arguments["key"]
                    value = arguments["value"]
                    tags = arguments.get("tags", [])
                    content_hash = arguments.get("content_hash")
                    # If a raw content block was provided, compute MD5 as content_hash when not supplied
                    raw_content = arguments.get("content")
                    if not content_hash and raw_content:
                        try:
                            import hashlib

                            content_hash = hashlib.md5(raw_content.encode("utf-8")).hexdigest()
                        except Exception:
                            content_hash = None
                    if not isinstance(value, str):
                        value = json.dumps(value)
                    payload_obj = {"type": "thought", "value": value, "tags": tags}
                    if content_hash:
                        payload_obj["content_hash"] = content_hash
                    payload = json.dumps(payload_obj)
                    conn.execute("""
                        INSERT OR REPLACE INTO memory (key, value, updated_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                    """, (key, payload))
                    conn.commit()
                    conn.close()
                    return [TextContent(type="text", text=f"Thought stored: {key}")]

                elif name == "create_entity_relationship":
                    # Create a simple relationship record and store as JSON
                    source = arguments.get("source")
                    target = arguments.get("target")
                    note = arguments.get("note", "")
                    nav = arguments.get("navigation_hint")
                    content_hash = arguments.get("content_hash")

                    # Compute MD5 if raw content provided and content_hash not supplied
                    raw_content = arguments.get("content")
                    if not content_hash and raw_content:
                        try:
                            import hashlib

                            content_hash = hashlib.md5(raw_content.encode("utf-8")).hexdigest()
                        except Exception:
                            content_hash = None

                    rel = {
                        "type": "relationship",
                        "source": source,
                        "target": target,
                        "note": note,
                        "navigation_hint": nav,
                    }
                    if content_hash:
                        rel["content_hash"] = content_hash
                    # Optional LSP/vector integration fields
                    symbol_type = arguments.get("symbol_type")
                    vector_id = arguments.get("vector_id")
                    source_id = arguments.get("source_id")
                    target_id = arguments.get("target_id")
                    relationship_type = arguments.get("relationship_type")
                    if symbol_type:
                        rel["symbol_type"] = symbol_type
                    if vector_id:
                        rel["vector_id"] = vector_id
                    if source_id:
                        rel["source_id"] = source_id
                    if target_id:
                        rel["target_id"] = target_id
                    if relationship_type:
                        rel["relationship_type"] = relationship_type
                    import uuid

                    rel_id = f"rel:{uuid.uuid4().hex[:8]}"
                    # Insert structured relationship for fast queries
                    conn.execute("""
                        INSERT OR REPLACE INTO relationships
                        (key, source, target, source_id, target_id, relationship_type, note, navigation_hint, content_hash, symbol_type, vector_id, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, (rel_id, source, target, source_id, target_id, relationship_type, note, nav, content_hash, symbol_type, vector_id))
                    # Also keep legacy JSON representation in memory table for compatibility
                    conn.execute("""
                        INSERT OR REPLACE INTO memory (key, value, updated_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                    """, (rel_id, json.dumps(rel)))
                    conn.commit()
                    conn.close()
                    return [TextContent(type="text", text=f"Relationship created: {rel_id}")]

                elif name == "recall_memories":
                    # If navigation_hint provided, search relationships tied to that hint
                    nav = arguments.get("navigation_hint")
                    query = arguments.get("query")
                    content_hash_q = arguments.get("content_hash")
                    limit = int(arguments.get("limit", 10))

                    # First: query structured relationships table for fast, indexed lookups
                    q_params = []
                    where_clauses = []
                    if content_hash_q:
                        where_clauses.append("content_hash = ?")
                        q_params.append(content_hash_q)
                    if arguments.get("vector_id"):
                        where_clauses.append("vector_id = ?")
                        q_params.append(arguments.get("vector_id"))
                    if nav:
                        # navigation_hint prefix match
                        where_clauses.append("navigation_hint LIKE ?")
                        q_params.append(f"%{nav}%")

                    relationships = []
                    if where_clauses:
                        sql = "SELECT key, source, target, note, navigation_hint, content_hash FROM relationships WHERE " + " OR ".join(where_clauses) + " ORDER BY updated_at DESC LIMIT ?"
                        q_params.append(limit)
                        cursor = conn.execute(sql, tuple(q_params))
                        relationships = cursor.fetchall()

                    # If no structured relationships matched, fallback to legacy memory JSON scan (best-effort)
                    legacy_matches = []
                    if not relationships:
                        cursor = conn.execute("SELECT key, value FROM memory ORDER BY updated_at DESC")
                        rows = cursor.fetchall()
                        for k, v in rows:
                            try:
                                obj = json.loads(v)
                            except Exception:
                                continue
                            # content_hash match
                            if content_hash_q and isinstance(obj, dict) and obj.get("content_hash") and obj.get("content_hash") == content_hash_q:
                                legacy_matches.append((k, obj))
                                continue
                            # vector id match
                            if arguments.get("vector_id") and isinstance(obj, dict) and obj.get("vector_id") and str(obj.get("vector_id")) == str(arguments.get("vector_id")):
                                legacy_matches.append((k, obj))
                                continue
                            # navigation_hint prefix
                            if nav and isinstance(obj, dict) and obj.get("navigation_hint"):
                                if nav.startswith(obj.get("navigation_hint")) or obj.get("navigation_hint").startswith(nav):
                                    legacy_matches.append((k, obj))
                                    continue
                            # free-text
                            if query and isinstance(obj, dict) and query.lower() in json.dumps(obj).lower():
                                legacy_matches.append((k, obj))

                    # Build human-friendly summary from structured relationships first, else legacy matches
                    lines = []
                    if relationships:
                        for key, source, target, note, nav_hint, ch in relationships[:limit]:
                            extra = f" ch:{ch}" if ch else ""
                            lines.append(f"Relation {key}: {source} -> {target} (note: {note}) nav:{nav_hint}{extra}")
                    elif legacy_matches:
                        for k, obj in legacy_matches[:limit]:
                            if obj.get("type") == "relationship":
                                note = obj.get("note", "")
                                nav_hint = obj.get("navigation_hint")
                                ch = obj.get("content_hash")
                                extra = f" ch:{ch}" if ch else ""
                                lines.append(f"Relation {k}: {obj.get('source')} -> {obj.get('target')} (note: {note}) nav:{nav_hint}{extra}")
                            elif obj.get("type") == "thought":
                                ch = obj.get("content_hash")
                                extra = f" ch:{ch}" if ch else ""
                                lines.append(f"Thought {k}: {obj.get('value')}{extra}")

                    if not lines:
                        return [TextContent(type="text", text="No related memories found.")]

                    return [TextContent(type="text", text="\n".join(lines))]

                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            except Exception as e:
                return [TextContent(type="text", text=f"Memory error: {e}")]

    async def run(self):
        """Run the server using stdio transport."""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


def main():
    """Entry point for memory server."""
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None

    server = MemoryServer(db_path)
    asyncio.run(server.run())


if __name__ == "__main__":
    main()


def get_advertised_tools(project_root: Path) -> list[Tool]:
    """Return lightweight advertised tools for the Memory server (no instantiation)."""
    # Choose discovery-time storage parent: prefer project_root if provided,
    # otherwise fall back to the user's home directory.
    base_dir = Path(project_root) if project_root is not None else Path.home()

    # If the chosen directory doesn't exist, advertise a fix tool instead of
    # the normal memory tools so the registry can surface a remediation action.
    if not base_dir.exists() or not base_dir.is_dir():
        return [
            Tool(
                name="memory_storage_unavailable",
                description=(
                    "Memory storage unavailable: configured storage directory does not exist. "
                    "Create the directory or provide a writable path."
                ),
                inputSchema={"type": "object", "properties": {}},
            )
        ]

    # If networkx (optional relationship features) is missing, advertise a remediation
    if not NX_AVAILABLE:
        return [
            Tool(
                name="fix_memory_package_missing",
                description=(
                    "Optional memory relationship features unavailable: networkx not installed. "
                    "Install with: pip install networkx"
                ),
                inputSchema={"type": "object", "properties": {}},
            )
        ]

    # Advertise relationship-aware memory tools
    return [
        Tool(
            name="store_thought",
            description="Store a thought or short note in memory",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "content_hash": {"type": "string", "description": "Optional MD5/sha hash of the content for content-addressable recall"},
                },
                "required": ["key", "value"],
            },
        ),
        Tool(
            name="create_entity_relationship",
            description="Create an entity relationship (optionally tied to a navigation_hint)",
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "note": {"type": "string"},
                    "navigation_hint": {"type": "string", "description": "Optional file:line hint to tie this relation to code"},
                    "content_hash": {"type": "string", "description": "Optional MD5/sha hash of the code this relation refers to"},
                },
                "required": ["source", "target"],
            },
        ),
        Tool(
            name="recall_memories",
            description="Recall memories by query or navigation hint",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "navigation_hint": {"type": "string"},
                    "content_hash": {"type": "string", "description": "Optional content hash to find content-addressable memories"},
                    "limit": {"type": "number"},
                },
            },
        ),
    ]
