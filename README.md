
# 🚀 MCP Code Intelligence

Stop Wasting Tokens. Start Coding Smarter.

Standard AI assistants are "token-hungry." When you ask a simple question, they often ingest thousands of lines of irrelevant code just to find a single reference, leading to massive token waste, high API costs, and slow responses.

**mcp-code-intelligence** fixes this by moving the heavy lifting to your local machine:

- **Precision Context:** Using Local Jina v3, we pinpoint only the exact code snippets needed. No more sending entire files to the cloud.
- **Zero-Waste Analysis:** Our system filters out the "noise," reducing prompt sizes by up to 80%.
- **Cost-Killer:** By providing the LLM with surgical precision instead of "brute-force" context, you save money on every single query while getting faster, more accurate answers.

---

## 💎 Why choose MCP Code Intelligence over standard AI chat?

<table>
<tr><td>🔍 <b>search_code</b></td><td>Fast semantic code search using local Jina V3 vector engine. No token limits, instant results, context-aware (unlike standard AI chat's slow, token-limited grep).</td></tr>
<tr><td>🧩 <b>search_similar</b></td><td>Detects duplicate or similar logic across your codebase, saving time and reducing technical debt.</td></tr>
<tr><td>💬 <b>search_context</b></td><td>Finds code by natural language description, leveraging project embeddings for precise results.</td></tr>
<tr><td>📊 <b>get_project_status</b></td><td>Instantly shows indexing, language, and health status—no manual inspection needed.</td></tr>
<tr><td>⚡ <b>index_project</b></td><td>Local, parallel indexing for large codebases. Much faster than cloud-based AI parsing.</td></tr>
<tr><td>🧠 <b>analyze_project / analyze_file</b></td><td>Deep analysis (complexity, health, code smells) with no token or context window limits. Results are project-wide and actionable.</td></tr>
<tr><td>🚨 <b>find_smells</b></td><td>Pinpoints anti-patterns and code smells, improving code quality and maintainability.</td></tr>
<tr><td>🔥 <b>get_complexity_hotspots</b></td><td>Highlights the most complex files/functions for targeted refactoring.</td></tr>
<tr><td>🔗 <b>check_circular_dependencies</b></td><td>Detects hidden import cycles instantly—no need for manual graph analysis.</td></tr>
<tr><td>🔎 <b>find_symbol / get_relationships</b></td><td>Symbol search and call graph mapping with full project context, not just open files.</td></tr>
<tr><td>📝 <b>interpret_analysis</b></td><td>Summarizes analysis for human or AI consumption, enabling smarter decisions.</td></tr>
<tr><td>🧬 <b>find_duplicates</b></td><td>Locates duplicate code blocks, reducing redundancy and improving maintainability.</td></tr>
<tr><td>🔕 <b>silence_health_issue</b></td><td>Suppresses noisy warnings, keeping your workflow focused.</td></tr>
<tr><td>🛑 <b>propose_logic</b></td><td>Prevents logic duplication before you code, saving tokens and review time.</td></tr>
<tr><td>📈 <b>analyze_impact</b></td><td>Predicts the effect of changes before you refactor, avoiding costly mistakes.</td></tr>
<tr><td>🛡️ <b>Guardian (health/logic checks)</b></td><td>Real-time health and duplication guard, ensuring codebase integrity.</td></tr>
<tr><td>📄 <b>read_file</b></td><td>Read full contents of a specific file (use as last resort when LSP tools don't suffice).</td></tr>
<tr><td>✍️ <b>write_file</b></td><td>Write content to a file, creating parent directories if needed (use with caution).</td></tr>
<tr><td>📂 <b>list_directory</b></td><td>List contents of a directory to explore repository layout and discover files.</td></tr>
<tr><td>📋 <b>list_files</b></td><td>Alias for list_directory - browse project structure efficiently.</td></tr>
<tr><td>🔧 <b>debug_ping</b></td><td>Diagnostic tool to verify MCP server connection and version information.</td></tr>
<tr><td>🎯 <b>goto_definition / find_references</b></td><td>High-precision LSP-powered navigation for exact symbol definitions and usage locations.</td></tr>
</table>

**Token & Speed Benefits:**
- All tools run locally, so there are no token limits or API rate restrictions.
- Results are instant, even for large projects (thanks to vector search and parallel analysis).
- No cloud latency—your data stays private and fast.

**Quality & Context Benefits:**
- Tools use your project's full graph and embeddings, not just file snippets.
- Results are always relevant, actionable, and tailored to your codebase.

---

## ✨ Cutting-Edge Features

- **🌍 Multi-Language Intelligence (LSP Integration):**
  - **Python:** Full type intelligence via `python-lsp-server`.
  - **JS/TS:** Smart navigation via `typescript-language-server`.
  - **Dart/Flutter:** Mobile development optimized intelligence.
  - **Rust / Go / C++:** Fully supported high-performance LSPs.
- **⚡ Smart Priority Indexing:** Large project? No problem. The system indexes your **Git changes**, **Entry Points**, and **READMEs** in the first 60 seconds, so you can start working while the rest finishes in the background.
- **🏠 100% Local Intelligence:** All vector operations and embeddings stay on your machine. No code ever leaves your project.
- **🛡️ Project Health Guardian (Smart Notifications):** The system continuously monitors your project for technical debt. It injects non-intrusive warnings into your AI chat when exact duplicates or empty placeholders (`pass`/`...`) are detected, helping you maintain a clean codebase in real-time.
- **🕵️ Three-Level Duplicate Detection:** Go beyond simple text matching with:
  - **Level 3 (Exact):** MD5/SHA256 hash matching for copy-paste detection.
  - **Level 2 (Structural):** AST-based skeleton analysis (different names, same algorithm).
  - **Level 1 (Semantic):** Jina v3 AI analysis to find different code performing the same task.

---

## 🚀 Quick Start (One-Command Setup)

Get up and running in any project in under a minute:

```bash
# 1. (Recommended) Create and activate a clean environment
# Windows:
python -m venv venv
.\venv\Scripts\activate

# Mac/Linux:
# python3 -m venv venv
# source venv/bin/activate

# 2. Clone the repository to your local machine
git clone https://github.com/mahkande/mcp-code-intelligence.git
cd mcp-code-intelligence

# 3. Install the package (This makes the 'mcp-code-intelligence' command available everywhere)
pip install .

# 4. Initialize & Connect to your AI Editor
# Run this once. It auto-detects your editors and configures them.
mcp-code-intelligence setup
```

The smart setup will:
1.  **Detect** your languages & platforms (Claude Desktop, Cursor, etc.)
2.  **Download** optimized Jina v3 weights.
3.  **Prioritize** and index your codebase.
4.  **Inject** configurations into your AI tools automatically.



---

## 📖 Command Reference

### 🧠 Intelligence & Search
- `mcp-code-intelligence setup`: The recommended way to start. Auto-detects everything and configures your environment.
- `mcp-code-intelligence search "query"`: Semantic search using natural language.
- `mcp-code-intelligence chat "question"`: Interactive LLM chat about your codebase (requires OpenRouter API key).
- `mcp-code-intelligence duplicates`: Run a high-precision, 3-level scan for duplicate code blocks.
- `mcp-code-intelligence analyze`: Run complexity and quality analysis (Cognitive/Cyclomatic complexity, Code Smells).

### 📊 Status & Visualization
- `mcp-code-intelligence status`: Check indexing progress, database health, and project statistics.
- `mcp-code-intelligence visualize serve`: Launch a local 3D interactive graph of your code structure in your browser.
- `mcp-code-intelligence doctor`: Diagnostic tool to check dependencies (Python, Node, Git) and path configurations.

### 🛠️ Maintenance & Advanced
- `mcp-code-intelligence index`: Manually trigger or force re-indexing of the codebase.
- `mcp-code-intelligence reset`: Clean slate. Deletes existing indexes and restores factory settings.
- `mcp-code-intelligence config`: Fine-tune settings like `similarity_threshold` or change embedding models.
- `mcp-code-intelligence silence_health_issue <ID>`: Manually mute a specific health warning by its ID.

### 🛡️ Managing the Health Guardian
The Guardian system is enabled by default to keep your codebase clean. You can manage it via CLI:

- **Disable Guardian:** `mcp-code-intelligence config set enable_guardian false`
- **Enable Guardian:** `mcp-code-intelligence config set enable_guardian true`
- **Toggle Logic Check:** `mcp-code-intelligence config set enable_logic_check false`
- **Ignore specific code:** Add `# guardian-ignore` as a comment inside any function or class to skip health checks for that block.

---
### 📺 Monitoring
- `mcp-code-intelligence onboarding logs`: **The Live Dashboard.** Monitor background activities, search logs, and AI tool interactions in real-time.

---

## 🗑️ Nasıl Kaldırılır? (Uninstall)

Eğer MCP Code Intelligence entegrasyonu editörünüzde sorun çıkarırsa veya kaldırmak isterseniz, aşağıdaki komutları kullanabilirsiniz:

- **Otomatik kaldırma (en çok tespit edilen platform):**
  ```sh
  mcp-code-intelligence uninstall mcp
  ```
- **Belirli bir editörden kaldırma:**
  ```sh
  mcp-code-intelligence uninstall mcp --platform cursor
  mcp-code-intelligence uninstall mcp --platform claude-desktop
  ```
- **Tüm platformlardan topluca kaldırma:**
  ```sh
  mcp-code-intelligence uninstall mcp --all
  ```
- **Mevcut entegrasyonları listele:**
  ```sh
  mcp-code-intelligence uninstall list
  ```

Kaldırma işlemi sonrası editörünüzü yeniden başlatmanız önerilir.

---

## 🛠️ Requirements
- **Python 3.10+**
- **Git** (for smart prioritization)
- **Node.js** (Optional, for JS/TS LSP support)
- **MCP-Code-Intelligence Extension** (Required for VS Code users)
  - **VS Code:** This project includes a packaged extension folder `mcp-vscode-extension`.
  - **Cursor:** Native MCP support.
  - **Claude Desktop/Code:** Native MCP support.
  
  > **Note:** VS Code requires proper configuration in `settings.json` (Copilot Chat) or a helping extension to bridge context gaps. This repository provides a helper extension for this purpose.

---

**Built by developers, for developers who value their context window (and their wallet).** 🛡️✨
