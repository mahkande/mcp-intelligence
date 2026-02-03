import json
import os
from pathlib import Path
from rich.console import Console
from mcp_code_intelligence.setup.git_hooks import install_hooks

class MCPConfigManager:
    """Manages MCP server registration and tool injection."""

    def __init__(self, project_root: Path, console: Console):
        self.project_root = project_root
        self.console = console

    def write_local_config(self, mcp_servers: dict, language_lsps: dict | None = None) -> Path:
        """Create or update local .vscode/mcp.json following official VS Code standards.

        If `language_lsps` is provided, include it as metadata.
        """
        local_mcp_path = self.project_root / ".vscode" / "mcp.json"
        local_mcp_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Match VS Code's expected structure: {"servers": {"name": {"type": "stdio", ...}}}
        formatted_servers = {}
        for name, cfg in mcp_servers.items():
            formatted_cfg = cfg.copy()
            if "type" not in formatted_cfg:
                formatted_cfg["type"] = "stdio"
            formatted_servers[name] = formatted_cfg

        out = {"servers": formatted_servers}
        if language_lsps:
            out["languageLsps"] = language_lsps
            
        with open(local_mcp_path, 'w', encoding='utf-8') as f:
            json.dump(out, f, indent=2)
        return local_mcp_path

    def inject_global_config(self, platforms, mcp_servers: dict):
        """Inject server configurations into detected AI tools."""
        for platform_info in platforms:
            try:
                if not platform_info.config_path or not platform_info.config_path.exists():
                    continue

                with open(platform_info.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                config.setdefault("mcpServers", {}).update(mcp_servers)

                with open(platform_info.config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2)

                self.console.print(f"   ✅ Configured {platform_info.platform.value}")
            except Exception as e:
                self.console.print(f"   ⚠️  Failed to configure {platform_info.platform.value}: {e}")

    def setup_git_hooks(self) -> bool:
        """Install git hooks for auto-indexing."""
        return install_hooks(self.project_root)

    def inject_vscode_settings(self, mcp_servers: dict):
        """Inject MCP server configurations into .vscode/settings.json."""
        vscode_dir = self.project_root / ".vscode"
        vscode_dir.mkdir(exist_ok=True)
        settings_path = vscode_dir / "settings.json"

        settings = {}
        if settings_path.exists():
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    settings = json.load(f)
            except Exception as e:
                # Assuming 'logger' is defined elsewhere or should be 'self.console.print'
                # For now, keeping it as is, but noting the potential undefined 'logger'
                # If 'logger' is not defined, this would cause a NameError.
                # Given the context, it's likely intended to be self.console.print
                # However, the instruction did not ask to change this line, only to use 'mcpServers'
                # which is already being done.
                self.console.print(f"   ⚠️  Failed to load existing VS Code settings: {e}")

        # Update mcpServers (Legacy/Cursor key)
        current_servers = settings.get("mcpServers", {})
        current_servers.update(mcp_servers)
        settings["mcpServers"] = current_servers

        # Official GitHub Copilot MCP configuration path
        # Note: VS Code is moving towards .vscode/mcp.json, 
        # but settings.json is still supported for older versions.
        copilot_mcp = settings.get("github.copilot.chat.mcpServers", {})
        
        # Ensure 'type': 'stdio' is in the settings.json version too
        formatted_mcp = {}
        for name, cfg in mcp_servers.items():
            f_cfg = cfg.copy()
            f_cfg.setdefault("type", "stdio")
            formatted_mcp[name] = f_cfg
            
        copilot_mcp.update(formatted_mcp)
        settings["github.copilot.chat.mcpServers"] = copilot_mcp

        try:
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2)
            self.console.print("   ✅ Configured .vscode/settings.json (github.copilot.chat.mcpServers)")
        except Exception as e:
            self.console.print(f"   ⚠️  Failed to configure .vscode/settings.json: {e}")

    def inject_copilot_instructions(self, mcp_servers: dict):
        """Generate .github/copilot-instructions.md for GitHub Copilot."""
        copilot_dir = self.project_root / ".github"
        copilot_dir.mkdir(exist_ok=True)
        instructions_path = copilot_dir / "copilot-instructions.md"

        # Note: In a real scenario, we might want to fetch these from tool_registry.py
        # but for instructions, we provide clear, human-readable summaries.
        tool_descriptions = [
            "- `search_code`: Perform a high-fidelity Hybrid Search combining Keyword and Semantic Vector search. Best for complex architectural questions.",
            "- `search_similar`: Identify Semantic Doppelgängers and structurally similar implementations. MUST USE to consolidate redundant logic.",
            "- `search_context`: Find code by natural language description leveraging project embeddings.",
            "- `get_project_status`: Get current project indexing status, configuration, and statistics.",
            "- `index_project`: Force a re-indexing of the codebase if the index is stale.",
            "- `analyze_project`: Perform a comprehensive sustainability and complexity analysis of the entire project.",
            "- `analyze_file`: Deep analysis of a single file (complexity, health, code smells).",
            "- `find_smells`: Identify code smells and anti-patterns (Long Method, God Class, etc.).",
            "- `get_complexity_hotspots`: Highlights the most complex files/functions for targeted refactoring.",
            "- `check_circular_dependencies`: Detects hidden import cycles instantly.",
            "- `interpret_analysis`: Summarizes large JSON analysis results for human or AI consumption.",
            "- `find_duplicates`: Detect duplicate code (semantic or structural) to reduce technical debt.",
            "- `silence_health_issue`: Suppresses noisy warnings to keep your workflow focused.",
            "- `find_symbol`: Find exact definitions of a class, function, or variable across the codebase.",
            "- `get_relationships`: Explore callers, callees, and semantic siblings of a symbol. MUST USE before refactoring.",
            "- `analyze_impact`: Trace direct and transitive ripple effects of a change using graph analysis.",
            "- `propose_logic`: Check if your proposed logic already exists in the codebase to avoid duplication.",
            "- `debug_ping`: Diagnostic tool to verify connection and server version.",
            "- `read_file`: Read full contents of a file (use as last resort).",
            "- `write_file`: Write content to a file (use with caution).",
            "- `list_directory`: List contents of a directory to explore layout.",
            "- `list_files`: Alias for list_directory.",
            "- `goto_definition/find_references`: High-precision navigation via LSP."
        ]
        
        tool_list = "\n".join(tool_descriptions)
        connection_info = json.dumps({"mcpServers": mcp_servers}, indent=2)
        
        content = f"""# GitHub Copilot Instructions for MCP Code Intelligence
This project is equipped with MCP (Model Context Protocol) tools that provide deep semantic understanding and codebase intelligence.

## 🛠 Available MCP Tools
The following tools are available via the `mcp-code-intelligence` server:
{tool_list}

## 🔌 Physical Connection
If MCP tools are not automatically recognized, ensure your client is configured with:
```json
{connection_info}
```

## 💡 Guidelines
- When I ask about the codebase, prioritize using `search_code` for semantic discovery.
- Before refactoring or changing symbols, use `analyze_impact` to understand the ripple effects.
- Use `analyze_file` or `analyze_project` to get a deep understanding of code health.
- If you need to find similar logic, use `search_similar` or `propose_logic`.
- All tools can be invoked via the standard MCP interface.

## 🔗 References
Detailed rules are maintained in [.mcp-rules.md](../../.mcp-rules.md).
"""
        try:
            with open(instructions_path, "w", encoding="utf-8") as f:
                f.write(content)
            self.console.print("   ✅ Created Copilot Instructions (.github/copilot-instructions.md)")
        except Exception as e:
            self.console.print(f"   ⚠️  Failed to create Copilot instructions: {e}")

    def inject_universal_rules(self, mcp_servers: dict):
        """Generate a universal .mcp-rules.md file in the project root."""
        rules_path = self.project_root / ".mcp-rules.md"
        
        content = f"""# 🧠 MCP Code Intelligence: Universal Rules
This file defines the interaction protocols for all AI assistants (Gemini, Claude, Cursor, Copilot) in this project.

## 🛠 Active MCP Servers
This project uses the following MCP servers for deep code analysis:
{chr(10).join([f"- **{name}**" for name in mcp_servers.keys()])}

## 📜 Core Instructions
1. **Semantic Awareness**: Do not rely solely on filename matching. Always use `search_code` or `search_context` for intent-based discovery.
2. **Impact First**: Refactoring is high-risk. Always trace dependencies using `analyze_impact` and `get_relationships` before proposing changes.
3. **Consistency**: Use `search_similar` or `propose_logic` to ensure new code follows existing project patterns.
4. **Health Protocols**: Check for long methods and high complexity using `find_smells`, `analyze_file`, and `analyze_project`.
5. **Architectural Integrity**: Use `check_circular_dependencies` to ensure the module graph remains clean.
6. **Diagnostics**: If tools are behaving unexpectedly, use `debug_ping` to verify the server is alive and responding.
7. **Data Interpretation**: Use `interpret_analysis` to turn large JSON analysis outputs into concise summaries.

## 📂 Configuration Sources
Individual assistants may use specific files which reference these rules:
- **Cursor/IDX**: [`.cursorrules`](.cursorrules)
- **GitHub Copilot**: [`.github/copilot-instructions.md`](.github/copilot-instructions.md)
- **VS Code**: [`.vscode/settings.json`](.vscode/settings.json)
"""
        try:
            with open(rules_path, "w", encoding="utf-8") as f:
                f.write(content)
            self.console.print("   ✅ Created Universal Rules (.mcp-rules.md)")
        except Exception as e:
            self.console.print(f"   ⚠️  Failed to create universal rules: {e}")

    def inject_cursor_rules(self, mcp_servers: dict):
        """Generate .cursorrules file with tool definitions and instructions."""
        rules_path = self.project_root / ".cursorrules"
        
        # Tool summaries for the LLM
        tool_descriptions = [
            "- `search_code`: Hybrid Search (Keyword + Semantic) with Reranker. Use for deep intent discovery.",
            "- `search_similar`: Find logic clones and structurally similar code across the codebase.",
            "- `search_context`: concept-to-implementation mapping using natural language.",
            "- `get_project_status`: Check if the codebase is fully indexed and ready.",
            "- `index_project`: Manually trigger a codebase scan.",
            "- `analyze_project`: Full project health and complexity deep-dive.",
            "- `analyze_file`: Multi-dimensional analysis of a specific file.",
            "- `find_smells`: Detect technical debt like God Classes or Long Methods.",
            "- `get_complexity_hotspots`: Target specific files for refactoring efforts.",
            "- `check_circular_dependencies`: Instant detection of module import cycles.",
            "- `interpret_analysis`: AI-friendly summaries of complex JSON tool exports.",
            "- `find_duplicates`: Multi-level duplication detection (structural & exact).",
            "- `silence_health_issue`: Ignore specific warnings to reduce noise.",
            "- * LSP Tools (`goto_definition`, `find_references`, `get_hover_info`, `get_completions`) for high-precision navigation.",
            "- * Filesystem Tools (`read_file`, `write_file`, `list_directory`, `list_files`)."
        ]

        rules_content = f"""# MCP Code Intelligence Rules
You are an AI assistant equipped with powerful MCP tools to explore, analyze, and refactor this codebase.

## 🛠 Available Tools
These tools are provided by the `mcp-code-intelligence` server:
{chr(10).join(tool_descriptions)}

## 💡 Best Practices
1. **Search Before You Leap**: Use `search_code` or `search_context` to understand existing patterns before implementing new features.
2. **Trace Ripple Effects**: Use `analyze_impact` and `get_relationships` before any symbol refactoring.
3. **Keep it Healthy**: Regularly use `analyze_file` and `check_circular_dependencies` to prevent technical debt.
4. **Debug if Needed**: If tools seem slow or unresponsive, run `debug_ping` once to verify connectivity.
2. **Refactor Safely**: Always run `analyze_impact` and `check_circular_dependencies` before changing widely used components.
3. **Deep Analysis**: Use `analyze_file` or `analyze_project` to get a deep health check without token limits.
4. **Avoid Duplication**: Use `search_similar` or `propose_logic` if you suspect the logic might already exist.
5. **Health Check**: Periodically run `find_smells` or `get_complexity_hotspots` to keep the code clean.
6. **Precision Navigation**: Prefer `goto_definition` and `find_references` for navigating symbols.

## 🚀 How to Use
Simply ask for what you need:
- "Find the most complex parts of this project."
- "What is the impact of changing the 'Auth' service?"
- "Are there any circular dependencies between my modules?"
- "Do a deep analysis of my database models."

## 🔗 Universal Reference
See [.mcp-rules.md](.mcp-rules.md) for core protocol definitions.
"""
        try:
            with open(rules_path, "w", encoding="utf-8") as f:
                f.write(rules_content)
            self.console.print("   ✅ Created .cursorrules for AI guidance")
        except Exception as e:
            self.console.print(f"   ⚠️  Failed to create .cursorrules: {e}")
