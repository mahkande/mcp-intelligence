# GitHub Copilot Instructions for MCP Code Intelligence
This project is equipped with MCP (Model Context Protocol) tools that provide deep semantic understanding and codebase intelligence.

## 🛠 Available MCP Tools
The following tools are available via the `mcp-code-intelligence` server:
- `search_code`: Perform a high-fidelity Hybrid Search combining Keyword and Semantic Vector search. Best for complex architectural questions.
- `search_similar`: Identify Semantic Doppelgängers and structurally similar implementations. MUST USE to consolidate redundant logic.
- `search_context`: Find code by natural language description leveraging project embeddings.
- `get_project_status`: Get current project indexing status, configuration, and statistics.
- `index_project`: Force a re-indexing of the codebase if the index is stale.
- `analyze_project`: Perform a comprehensive sustainability and complexity analysis of the entire project.
- `analyze_file`: Deep analysis of a single file (complexity, health, code smells).
- `find_smells`: Identify code smells and anti-patterns (Long Method, God Class, etc.).
- `get_complexity_hotspots`: Highlights the most complex files/functions for targeted refactoring.
- `check_circular_dependencies`: Detects hidden import cycles instantly.
- `interpret_analysis`: Summarizes large JSON analysis results for human or AI consumption.
- `find_duplicates`: Detect duplicate code (semantic or structural) to reduce technical debt.
- `silence_health_issue`: Suppresses noisy warnings to keep your workflow focused.
- `find_symbol`: Find exact definitions of a class, function, or variable across the codebase.
- `get_relationships`: Explore callers, callees, and semantic siblings of a symbol. MUST USE before refactoring.
- `analyze_impact`: Trace direct and transitive ripple effects of a change using graph analysis.
- `propose_logic`: Check if your proposed logic already exists in the codebase to avoid duplication.
- `debug_ping`: Diagnostic tool to verify connection and server version.
- `read_file`: Read full contents of a file (use as last resort).
- `write_file`: Write content to a file (use with caution).
- `list_directory`: List contents of a directory to explore layout.
- `list_files`: Alias for list_directory.
- `goto_definition/find_references`: High-precision navigation via LSP.

## 🔌 Physical Connection
If MCP tools are not automatically recognized, ensure your client is configured with:
```json
{
  "mcpServers": {
    "mcp-code-intelligence": {
      "command": "C:\\Users\\mahir\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
      "args": [
        "-u",
        "-m",
        "mcp_code_intelligence.mcp_impl"
      ],
      "env": {
        "MCP_PROJECT_ROOT": "C:\\Users\\mahir\\Desktop\\mcp-server\\mcp-vector-search",
        "MCP_ENABLE_FILE_WATCHING": "true",
        "PYTHONPATH": "C:\\Users\\mahir\\Desktop\\mcp-server\\mcp-vector-search\\src",
        "PYTHONUNBUFFERED": "1"
      }
    },
    "filesystem": {
      "command": "C:\\Users\\mahir\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
      "args": [
        "-u",
        "-m",
        "mcp_code_intelligence.servers.filesystem_server",
        "C:\\Users\\mahir\\Desktop\\mcp-server\\mcp-vector-search"
      ],
      "env": {
        "PYTHONPATH": "C:\\Users\\mahir\\Desktop\\mcp-server\\mcp-vector-search\\src",
        "PYTHONUNBUFFERED": "1"
      }
    },
    "git": {
      "command": "C:\\Users\\mahir\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
      "args": [
        "-u",
        "-m",
        "mcp_code_intelligence.servers.git_server",
        "C:\\Users\\mahir\\Desktop\\mcp-server\\mcp-vector-search"
      ],
      "env": {
        "PYTHONPATH": "C:\\Users\\mahir\\Desktop\\mcp-server\\mcp-vector-search\\src",
        "PYTHONUNBUFFERED": "1"
      }
    },
    "memory": {
      "command": "C:\\Users\\mahir\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
      "args": [
        "-u",
        "-m",
        "mcp_code_intelligence.servers.memory_server"
      ],
      "env": {
        "PYTHONPATH": "C:\\Users\\mahir\\Desktop\\mcp-server\\mcp-vector-search\\src",
        "PYTHONUNBUFFERED": "1"
      }
    },
    "python-lsp": {
      "command": "C:\\Users\\mahir\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
      "args": [
        "-m",
        "mcp_code_intelligence.servers.python_lsp_server",
        "C:\\Users\\mahir\\Desktop\\mcp-server\\mcp-vector-search"
      ],
      "env": {
        "PYTHONPATH": "C:\\Users\\mahir\\Desktop\\mcp-server\\mcp-vector-search\\src",
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

## 💡 Guidelines
- When I ask about the codebase, prioritize using `search_code` for semantic discovery.
- Before refactoring or changing symbols, use `analyze_impact` to understand the ripple effects.
- Use `analyze_file` or `analyze_project` to get a deep understanding of code health.
- If you need to find similar logic, use `search_similar` or `propose_logic`.
- All tools can be invoked via the standard MCP interface.

## 🔗 References
Detailed rules are maintained in [.mcp-rules.md](../../.mcp-rules.md).
