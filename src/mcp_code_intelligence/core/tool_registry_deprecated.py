"""Central registry for tool metadata used by MCP servers and CLI chat.

Provides a single source of truth for tool descriptions, schemas and LLM
function specs so `get_tools()` and the chat agent share the same data.
"""
from typing import Any, Dict, List
from mcp.types import Tool
from pathlib import Path
import json
from typing import Optional
import importlib
import re
import time
import os


# Base tool definitions: name, human-friendly description, inputSchema
# Descriptions include a short 'When to use' guidance and a one-line example.
_TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "search_code",
        "description": (
            "Perform a high-fidelity Hybrid Search combining Keyword (BM25) and Semantic Vector search with Jina Reranker v2. "
            "Use this for complex architectural questions where exact matches aren't enough. Best for finding logic patterns, intent-based discovery, and deep context retrieval. "
            "Example: 'Where is authentication enforced?'"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query to find relevant code"},
                "limit": {"type": "integer", "description": "Max results", "default": 10},
            },
            "required": ["query"],
        },
    },

    {
        "name": "read_file",
        "description": (
            "Read full contents of a specific file. "
            "When to use: Sadece LSP araçları sonuç vermediğinde kullanılacak son çare. "
            "Example: 'Open src/auth.py'"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "relative_path": {"type": "string", "description": "Relative path to file"}
            },
            "required": ["relative_path"],
        },
    },

    {
        "name": "list_directory",
        "description": (
            "List contents of a directory. "
            "When to use: Use to explore repository layout or to discover likely files to inspect. "
            "Example: 'List contents of src/'"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "relative_path": {"type": "string", "description": "Directory path (default: root)"}
            }
        },
    },

    {
        "name": "write_file",
        "description": (
            "Write content to a file. Creates parent directories if needed. "
            "When to use: Use with caution - only for creating new files or updating existing ones. "
            "Example: 'Write config to settings.json'"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "relative_path": {"type": "string", "description": "Relative path to file"},
                "content": {"type": "string", "description": "Content to write to the file"}
            },
            "required": ["relative_path", "content"],
        },
    },

    {
        "name": "propose_logic",
        "description": (
            "Check for existing logic similar to a proposed implementation to avoid duplication. "
            "When to use: Call before implementing new helper functions or business rules. "
            "Example: 'Propose logic for 'format currency as USD''"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "description": "Goal or purpose of the logic"},
                "code_draft": {"type": "string", "description": "Optional code draft"},
            },
            "required": ["intent"],
        },
    },

    {
        "name": "find_duplicates",
        "description": (
            "Detect duplicate code (semantic, structural, exact) to reduce technical debt. "
            "When to use: Use when refactoring, or when suspicious similar behavior is observed. "
            "Example: 'Find duplicate implementations of payment processing'"
        ),
        "inputSchema": {"type": "object", "properties": {"min_length": {"type": "integer"}}},
    },

    {
        "name": "find_smells",
        "description": (
            "Identify code smells and anti-patterns (Long Method, God Class, etc.). "
            "When to use: Use during code review or before refactoring to prioritize hotspots. "
            "Example: 'Find long methods in src/'"
        ),
        "inputSchema": {"type": "object", "properties": {"smell_type": {"type": "string"}}},
    },

    {
        "name": "search_similar",
        "description": (
            "Identify Semantic Doppelgängers and structurally similar implementations across the codebase. Powered by Jina v3 (State-of-the-Art) embeddings to detect logic duplicates even if variable names differ. "
            "MUST USE to maintain consistency or consolidate redundant logic. "
            "Example: 'Find functions similar to handlers/auth.py::login_handler'"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "function_name": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["relative_path"],
        },
    },
    {
        "name": "search_context",
        "description": "Find code by natural language description, leveraging project embeddings for precise results. Best for mapping high-level concepts to implementation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Natural language description of the code or context"},
                "focus_areas": {"type": "array", "items": {"type": "string"}, "description": "Optional focus areas (e.g. ['auth', 'database'])"},
                "limit": {"type": "integer", "default": 10}
            },
            "required": ["description"]
        }
    },
    {
        "name": "get_project_status",
        "description": "Get current project indexing status, configuration, and statistics. Use this to check if the project is fully indexed.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "analyze_project",
        "description": "Perform a comprehensive sustainability and complexity analysis of the entire project. Detects technical debt hotspots and architectural issues.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "threshold_preset": {"type": "string", "enum": ["standard", "strict", "relaxed"], "default": "standard"},
                "output_format": {"type": "string", "enum": ["summary", "detailed"], "default": "summary"},
            },
        },
    },
    {
        "name": "analyze_file",
        "description": "Deep analysis of a single file (complexity, health, code smells) with no token or context window limits.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Relative path to file"}
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "get_complexity_hotspots",
        "description": "CRITICAL TOOL: ALWAYS use this FIRST when asked to analyze complexity, find hotspots, or improve code quality. Do NOT browse files manually. This tool scans the whole project automatically.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10}
            }
        }
    },
    {
        "name": "check_circular_dependencies",
        "description": "Detects hidden import cycles instantly—no need for manual graph analysis.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "index_project",
        "description": "Force a re-indexing of the codebase. Use only if you suspect the index is stale or if many files changed externally.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "force": {"type": "boolean", "default": False},
                "important_only": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "analyze_impact",
        "description": "CRITICAL for Refactoring. Trace the direct and transitive (ripple effect) dependency chain of any function or class using Graph-Based analysis. Use this BEFORE making any changes to see exactly which files and modules will break or require updates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol_name": {"type": "string", "description": "The symbol to analyze impact for"},
                "max_depth": {"type": "integer", "description": "Max transitive depth", "default": 5},
            },
            "required": ["symbol_name"],
        },
    },
    {
        "name": "find_symbol",
        "description": "Find exact definitions of a symbol (class, function, variable) across the codebase. Backed by semantic search and static analysis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Symbol name to find"},
                "symbol_type": {"type": "string", "description": "Optional type filter (class, function, etc.)"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_relationships",
        "description": "Explore callers, callees, and semantic siblings of a symbol. This is the BEST tool for understanding architectural dependencies and how components interact. MUST USE before refactoring to see ripple effects.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Symbol name to explore"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "interpret_analysis",
        "description": "Summarizes analysis for human or AI consumption, enabling smarter decisions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "analysis_json": {"type": "string", "description": "The JSON analysis data to interpret"},
                "focus": {"type": "string", "enum": ["summary", "detailed", "critical"], "default": "summary"},
                "verbosity": {"type": "string", "enum": ["brief", "normal", "verbose"], "default": "normal"}
            },
            "required": ["analysis_json"]
        }
    },
    {
        "name": "silence_health_issue",
        "description": "Suppresses noisy warnings, keeping your workflow focused.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "issue_id": {"type": "string", "description": "The ID of the issue to silence"}
            },
            "required": ["issue_id"]
        }
    },
    {
        "name": "debug_ping",
        "description": "Returns registry source info for debugging. Call this to check if you are using the correct server.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def get_tool_definitions() -> List[Dict[str, Any]]:
    """Return the base tool definitions list."""
    # Merge base definitions with language-specific LSP tool definitions
    defs = list(_TOOL_DEFINITIONS)

    # Load language configs from languages/*.json to add LSP tools
    langs_dir = Path(__file__).parent.parent / "languages"
    try:
        if langs_dir.exists():
            for f in langs_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    lang_key = f.stem.lower()
                    lang_name = data.get("name", lang_key)

                    # Add a set of LSP-style tools for each language.
                    # Mark DESCRIPTION as MUST USE to bias LLMs to prefer these tools.
                    lsp_tools = [
                        {
                            "name": "goto_definition",
                            "description": (
                                f"En hızlı ve en düşük maliyetli yöntem: High-precision go-to-definition for {lang_name}. "
                                "This tool calls the project's language server and returns exact symbol definitions."
                            ),
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "relative_path": {"type": "string"},
                                    "line": {"type": "number"},
                                    "character": {"type": "number"}
                                },
                                "required": ["relative_path", "line", "character"]
                            },
                        },
                        {
                            "name": "find_references",
                            "description": (
                                f"En hızlı ve en düşük maliyetli yöntem: High-precision find-references for {lang_name}. "
                                "Use to locate all usages of a symbol across the project before refactoring."
                            ),
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "relative_path": {"type": "string"},
                                    "line": {"type": "number"},
                                    "character": {"type": "number"}
                                },
                                "required": ["relative_path", "line", "character"]
                            },
                        },
                        {
                            "name": "get_hover_info",
                            "description": (
                                f"En hızlı ve en düşük maliyetli yöntem: Get hover/type/documentation info for {lang_name} symbols. "
                                "Use to get precise type and docstrings before code generation."
                            ),
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "relative_path": {"type": "string"},
                                    "line": {"type": "number"},
                                    "character": {"type": "number"}
                                },
                                "required": ["relative_path", "line", "character"]
                            },
                        },
                        {
                            "name": "get_completions",
                            "description": (
                                f"En hızlı ve en düşük maliyetli yöntem: Language-server completions for {lang_name}. "
                                "Provides context-aware completion candidates directly from the LSP."
                            ),
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "relative_path": {"type": "string"},
                                    "line": {"type": "number"},
                                    "character": {"type": "number"}
                                },
                                "required": ["relative_path", "line", "character"]
                            },
                        },
                    ]

                    defs.extend(lsp_tools)
                except Exception:
                    # ignore malformed language files
                    continue
    except Exception:
        pass

    return defs


def get_mcp_tools(project_root: Optional[Path] = None, servers_tools: Optional[dict] = None) -> List[Tool]:
    """Return a list of `Tool` objects for MCP `get_tools()` consumption.

    If `project_root` is provided, only language tools for LSPs configured in
    `project_root/.mcp/mcp.json` -> `languageLsps` will be created. This ensures
    that only relevant language tools are advertised to the AI.
    """
    tools: List[Tool] = []
    project_cfg = {}

    if project_root:
        try:
            cfg_path = Path(project_root) / ".mcp" / "mcp.json"
            if cfg_path.exists():
                project_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception as e:
            # Add a remediation tool so users get actionable guidance
            err_name = "fix_mcp_config_malformed"
            err_desc = (
                "Project config .mcp/mcp.json exists but could not be parsed. "
                f"Error: {e}. Inspect the JSON file for syntax errors."
            )
            if not any(x.name == err_name for x in tools):
                tools.append(Tool(name=err_name, description=err_desc, inputSchema={"type": "object", "properties": {}}))

    # Add base tools
    for td in _TOOL_DEFINITIONS:
        # normalize any internal file path keys to `relative_path` for consistency
        schema = td.get("inputSchema", {})
        tools.append(Tool(name=td["name"], description=td["description"], inputSchema=schema))
    
    # DEBUG: Write promoted tools to a file
    try:
        debug_log = Path.cwd() / "tool_advert_debug.log"
        with open(debug_log, "a", encoding="utf-8") as f:
            f.write(f"[{time.ctime()}] (PID: {os.getpid()}) Registry source: {__file__}\n")
            f.write(f"[{time.ctime()}] Advertised tools: {[t.name for t in tools]}\n")
    except Exception:
        pass

        # If no explicit servers_tools were provided, attempt lightweight discovery
        # by importing server modules and calling their `get_advertised_tools()`.
        if not servers_tools:
            try:
                servers_tools = {}
                servers_pkg = Path(__file__).parent.parent / "servers"
                if servers_pkg.exists():
                    for f in servers_pkg.glob("*.py"):
                        if f.name.startswith("_"):
                            continue
                        mod_name = f"mcp_code_intelligence.servers.{f.stem}"
                        try:
                            mod = importlib.import_module(mod_name)
                            if hasattr(mod, "get_advertised_tools"):
                                # Prefer calling discovery with both project_root and
                                # the parsed project config if the function accepts it.
                                try:
                                    from inspect import signature

                                    sig = signature(mod.get_advertised_tools)
                                    if len(sig.parameters) >= 2:
                                        adv = mod.get_advertised_tools(project_root or Path.cwd(), project_cfg)
                                    else:
                                        adv = mod.get_advertised_tools(project_root or Path.cwd())
                                except Exception:
                                    # fallback to single-arg call
                                    try:
                                        adv = mod.get_advertised_tools(project_root or Path.cwd())
                                    except Exception as e:
                                        adv = [Tool(name=f"{f.stem}_unavailable", description=f"Server discovery failed: {e}", inputSchema={})]
                                servers_tools[f.stem] = adv
                        except Exception as e:
                            # If importing the server module fails during discovery, record
                            # a critical-error advert so the Agent can inform the user.
                            err = str(e)
                            servers_tools[f.stem] = [
                                Tool(
                                    name=f"{f.stem}_critical_error",
                                    description=(f"Server module import failed during discovery: {err}"),
                                    inputSchema={"type": "object", "properties": {}},
                                )
                            ]

                            # Also append an actionable fix tool so the Agent can present
                            # a clear remediation to the user.
                            fix_name = f"fix_{f.stem}_critical_error"
                            fix_desc = (
                                "Do not call this tool. Critical import error occurred during server discovery. "
                                f"Error: {err}. Ask the user to inspect the server module, check dependencies, and re-run discovery."
                            )
                            if not any(x.name == fix_name for x in tools):
                                tools.append(
                                    Tool(
                                        name=fix_name,
                                        description=fix_desc,
                                        inputSchema={"type": "object", "properties": {}},
                                    )
                                )
            except Exception:
                servers_tools = {}

        if servers_tools:
            for srv_name, srv_tool_list in servers_tools.items():
                for t in srv_tool_list:
                    # t may be a `Tool` instance or a plain dict produced by discovery
                    try:
                        if hasattr(t, "name"):
                            # pydantic Tool instance
                            name = t.name
                            desc = t.description or ""
                            schema = getattr(t, "inputSchema", {}) or {}
                            meta = getattr(t, "meta", None) or {}
                        else:
                            name = t.get("name")
                            desc = t.get("description", "")
                            schema = t.get("inputSchema") or t.get("input_schema") or {}
                            meta = t.get("_meta", {}) or t.get("meta", {}) or {}

                        # Respect server-declared disabled tools. If disabled, skip advertising.
                        disabled = False
                        if isinstance(meta, dict) and meta.get("disabled"):
                            disabled = True
                        if isinstance(t, dict) and t.get("disabled"):
                            disabled = True
                        if disabled:
                            # do not advertise disabled tools to the Agent
                            continue

                        # Normalize common file/path parameter names to `relative_path` in schemas
                        try:
                            props = schema.get("properties", {})
                            if "file_path" in props and "relative_path" not in props:
                                props["relative_path"] = props.pop("file_path")
                            if "file" in props and "relative_path" not in props:
                                props["relative_path"] = props.pop("file")
                            if "path" in props and "relative_path" not in props:
                                props["relative_path"] = props.pop("path")
                            schema["properties"] = props
                            # ensure required keys updated
                            req = schema.get("required", [])
                            req = ["relative_path" if x in ("file_path", "file", "path") else x for x in req]
                            schema["required"] = req
                        except Exception:
                            pass

                        tools.append(Tool(name=name, description=desc, inputSchema=schema))
                    except Exception:
                        continue

            # Cross-check: if any server advert indicates unavailability for an LSP,
            # append an actionable 'fix' notice tool for the Agent so it can tell
            # the user what to do (these are informational — the Agent should
            # instruct the user rather than calling the fix tool).
            try:
                for srv_name, srv_tool_list in servers_tools.items():
                    for t in srv_tool_list:
                        try:
                            t_name = t.name if hasattr(t, "name") else t.get("name", "")
                            t_desc = t.description if hasattr(t, "description") else t.get("description", "")
                        except Exception:
                            continue

                        low_desc = (t_desc or "").lower()
                        if "unavailable" in (t_name or "").lower() or "unavailable" in low_desc or "not installed" in low_desc:
                            fix_name = f"fix_{t_name}" if t_name else f"fix_{srv_name}_unavailable"
                            # try to extract a pip install suggestion from the description
                            pip_cmd = None
                            m = re.search(r"(pip install[\w\-\s\.]*)", t_desc or "", re.IGNORECASE)
                            if m:
                                pip_cmd = m.group(1).strip()

                            if pip_cmd:
                                fix_desc = (
                                    f"Do not call this tool. Action for user: run '{pip_cmd}' to install the missing dependency, then restart LSP proxies."
                                )
                            else:
                                # fallback actionable suggestions
                                fix_desc = (
                                    "Do not call this tool. Action for user: ensure the language server is installed and running. "
                                    "Suggested commands: 'pip install python-lsp-server' or 'mcp start-lsp'."
                                )

                            # Only add if not already present
                            if not any(x.name == fix_name for x in tools):
                                tools.append(Tool(name=fix_name, description=fix_desc, inputSchema={"type": "object", "properties": {}}))
            except Exception:
                pass

            return tools

    # If no project_root provided, return base tools only
    if not project_root:
        return tools

    # Read local .mcp/mcp.json to discover configured language LSPs
    try:
        cfg_path = Path(project_root) / ".mcp" / "mcp.json"
        if not cfg_path.exists():
            return tools
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        lang_map = cfg.get("languageLsps", {}) or {}
    except Exception:
        return tools

    # For each configured language ID, create language-specific tools
    for lang_id, entry in lang_map.items():
        # Normalize lang key
        lk = str(lang_id).lower()
        # Friendly name: try to read languages/<lang_id>.json if exists
        langs_dir = Path(__file__).parent.parent / "languages"
        friendly = lk
        try:
            lang_file = langs_dir / f"{lk}.json"
            if lang_file.exists():
                data = json.loads(lang_file.read_text(encoding="utf-8"))
                friendly = data.get("name", lk)
        except Exception:
            pass

        lsp_tools = [
            ("goto_definition",
                (f"En hızlı ve en düşük maliyetli yöntem: High-precision go-to-definition for {friendly}."
                 " This tool calls the project's language server and returns exact symbol definitions."),
            ),
            ("find_references",
                (f"En hızlı ve en düşük maliyetli yöntem: High-precision find-references for {friendly}."
                 " Use to locate all usages of a symbol across the project before refactoring."),
            ),
            ("get_hover_info",
                (f"En hızlı ve en düşük maliyetli yöntem: Get hover/type/documentation info for {friendly} symbols."
                 " Use to get precise type and docstrings before code generation."),
            ),
            ("get_completions",
                (f"En hızlı ve en düşük maliyetli yöntem: Language-server completions for {friendly}."
                 " Provides context-aware completion candidates directly from the LSP."),
            ),
        ]

        for name, desc in lsp_tools:
            tools.append(Tool(name=name, description=desc, inputSchema={
                "type": "object",
                "properties": {
                    "relative_path": {"type": "string"},
                    "line": {"type": "number"},
                    "character": {"type": "number"}
                },
                "required": ["relative_path", "line", "character"],
            }))

    return tools



def get_llm_tool_specs(project_root: Path | None = None, servers_tools: Optional[dict] = None) -> List[Dict[str, Any]]:
    """Return tool specs formatted for LLM function/tool invocation (chat).

    If `project_root` is provided, include dynamic language-specific tools only
    for LSPs configured in `project_root/.mcp/mcp.json` -> `languageLsps` so
    the LLM/chat UI only sees tools that are actually available in the project.

    Returns a list where each item has shape: {"type": "function", "function": {...}}
    """
    specs: List[Dict[str, Any]] = []

    # Start with base definitions
    for td in _TOOL_DEFINITIONS:
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": td["name"],
                    "description": td["description"],
                    "parameters": td.get("inputSchema", {}),
                },
            }
        )

    # If callers supplied server tool lists, use them as the primary source
    if servers_tools:
        for srv_name, srv_tool_list in servers_tools.items():
            for t in srv_tool_list:
                name = t.get("name")
                desc = t.get("description", "")
                params = t.get("inputSchema") or t.get("input_schema") or {}
                # normalize params
                try:
                    props = params.get("properties", {})
                    if "file" in props and "relative_path" not in props:
                        props["relative_path"] = props.pop("file")
                    if "path" in props and "relative_path" not in props:
                        props["relative_path"] = props.pop("path")
                    if "file_path" in props and "relative_path" not in props:
                        props["relative_path"] = props.pop("file_path")
                    params["properties"] = props
                except Exception:
                    pass

                specs.append({
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": desc,
                        "parameters": params,
                    },
                })

        return specs

    # If project_root provided, add dynamic LSP tools for configured languages
    if project_root:
        try:
            cfg_path = Path(project_root) / ".mcp" / "mcp.json"
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                lang_map = cfg.get("languageLsps", {}) or {}
            else:
                lang_map = {}
        except Exception:
            lang_map = {}

        for lang_id in lang_map.keys():
            lk = str(lang_id).lower()
            # Friendly name lookup
            langs_dir = Path(__file__).parent.parent / "languages"
            friendly = lk
            try:
                lang_file = langs_dir / f"{lk}.json"
                if lang_file.exists():
                    data = json.loads(lang_file.read_text(encoding="utf-8"))
                    friendly = data.get("name", lk)
            except Exception:
                pass

            lsp_defs = [
                ("goto_definition",
                    (
                        f"En hızlı ve en düşük maliyetli yöntem: High-precision go-to-definition for {friendly}."
                        " This tool calls the project's language server and returns exact symbol definitions."
                    ),
                ),
                ("find_references",
                    (
                        f"En hızlı ve en düşük maliyetli yöntem: High-precision find-references for {friendly}."
                        " Use to locate all usages of a symbol across the project before refactoring."
                    ),
                ),
                ("get_hover_info",
                    (
                        f"En hızlı ve en düşük maliyetli yöntem: Get hover/type/documentation info for {friendly} symbols."
                        " Use to get precise type and docstrings before code generation."
                    ),
                ),
                ("get_completions",
                    (
                        f"En hızlı ve en düşük maliyetli yöntem: Language-server completions for {friendly}."
                        " Provides context-aware completion candidates directly from the LSP."
                    ),
                ),
            ]

            for name, desc in lsp_defs:
                specs.append(
                    {
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": desc,
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "relative_path": {"type": "string"},
                                    "line": {"type": "number"},
                                    "character": {"type": "number"},
                                },
                                "required": ["relative_path", "line", "character"],
                            },
                        },
                    }
                )

    return specs
