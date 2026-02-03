# CLI Commands Reference

Complete reference for all mcp-code-intelligence command-line interface commands.

## 📋 Table of Contents

- [Command Overview](#command-overview)
- [Setup Commands](#setup-commands)
- [Usage Commands](#usage-commands)
- [Maintenance Commands](#maintenance-commands)
- [Advanced Commands](#advanced-commands)
- [Global Options](#global-options)

---

## 🎯 Command Overview

### Core Operations

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `setup` | **Zero-config smart setup (recommended)** | First-time setup, team onboarding, quick setup |
| `install` | Complete project setup (advanced) | Fine-grained control, add MCP integration |
| `init` | Initialize project configuration | Manual setup, re-initialization |
| `index` | Index codebase for search | After code changes, initial indexing |
| `search` | Search code semantically | Find code by meaning or functionality |
| `status` | View project status | Check index health, configuration |

### Customization

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `config` | Manage configuration | Customize behavior, view settings |
| `auto-index` | Configure automatic reindexing | Set up continuous updates |

### Advanced

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `watch` | File watching and monitoring | Real-time index updates |
| `mcp` | MCP server integration | Advanced MCP configuration |
| `doctor` | Diagnose system issues | Troubleshoot problems |
| `version` | Show version info | Check installed version |

---

## 🚀 Setup Commands

### `setup` (Recommended)

**Zero-config smart setup** - The fastest way to get started with mcp-code-intelligence.

```bash
# One command does everything (recommended)
mcp-code-intelligence setup

# Force re-setup (reindex and reconfigure)
mcp-code-intelligence setup --force

# Verbose output for debugging
mcp-code-intelligence setup --verbose
```

**What it does automatically:**

1. **Detects Project Characteristics**
   - Scans for languages in use (Python, JavaScript, TypeScript, etc.)
   - Discovers file types present in your codebase
   - Detects installed MCP platforms (Claude Code, Cursor, Windsurf, VS Code)

2. **Smart Configuration**
   - Selects optimal embedding model based on detected languages
   - Chooses appropriate file extensions to index
   - Sets sensible defaults (similarity threshold, auto-indexing, etc.)

3. **Initialization**
   - Creates `.mcp-code-intelligence/` directory
   - Initializes ChromaDB vector database
   - Saves configuration to `config.json`

4. **Indexing**
   - Indexes entire codebase with progress reporting
   - Parses code into semantic chunks
   - Generates embeddings for searchability

5. **MCP Integration**
   - Configures all detected MCP platforms automatically
   - Creates `.mcp.json` for project-scoped configuration
   - Updates platform-specific config files for supported platforms
   - Enables file watching for automatic reindexing

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--force` / `-f` | Force re-initialization if already set up | `false` |
| `--verbose` / `-v` | Show detailed progress information | `false` |

**Key Features:**

- ✅ **Zero Configuration**: No user input required
- ✅ **Intelligent Detection**: Discovers languages, file types, and platforms
- ✅ **All-in-One**: Combines init + index + MCP setup
- ✅ **Idempotent**: Safe to run multiple times
- ✅ **Fast**: Timeout protection prevents hanging (2s scan limit)
- ✅ **Team-Friendly**: Creates `.mcp.json` for sharing with team

**When to use:**

- ✅ **First-time setup**: Getting started in any project
- ✅ **Team onboarding**: New developers joining your team
- ✅ **Quick testing**: Trying mcp-code-intelligence in a new codebase
- ✅ **Multi-platform setup**: Configuring multiple MCP tools at once

**Example output:**

```
🚀 Smart Setup for mcp-code-intelligence
🔍 Detecting project...
   ✅ Found 3 language(s): Python, JavaScript, TypeScript
   ✅ Detected 8 file type(s)
   ✅ Found 2 platform(s): claude-code, cursor
⚙️  Configuring...
   ✅ Embedding model: sentence-transformers/all-MiniLM-L6-v2
🚀 Initializing...
   ✅ Vector database created
   ✅ Configuration saved
🔍 Indexing codebase...
   ✅ Indexing completed in 12.3s
🔗 Configuring MCP integrations...
   ✅ Configured 2 platform(s)
🎉 Setup Complete!

What was set up:
  ✅ Vector database initialized
  ✅ Codebase indexed and searchable
  ✅ 2 MCP platform(s) configured
  ✅ File watching enabled

Ready to Use:
  • Open Claude Code in this directory to use MCP tools
  • mcp-code-intelligence search 'your query' - Search your code
  • mcp-code-intelligence status - Check project status

💡 Tip: Commit .mcp.json to share configuration with your team
```

**Comparison with other commands:**

| Command | Init | Index | MCP Config | Auto-detect | Recommended For |
|---------|------|-------|------------|-------------|-----------------|
| `setup` | ✅ | ✅ | ✅ All platforms | ✅ | **Everyone (recommended)** |
| `install` | ✅ | ✅ | ✅ Optional | ❌ | Advanced users needing control |
| `init` | ✅ | ❌ | ❌ | ❌ | Manual configuration |

**Next steps after setup:**

```bash
# Search your code
mcp-code-intelligence search "authentication logic"

# Check project status
mcp-code-intelligence status

# Start using MCP tools in Claude Code/Cursor/etc.
# (Already configured automatically!)
```

---

### `install` (Advanced)

Complete project setup with optional MCP integration.

**Hierarchy:** `install` → `init` → `index`

```bash
# Interactive setup (recommended)
mcp-code-intelligence install

# Setup with MCP integration
mcp-code-intelligence install --with-mcp

# Setup specific MCP platform
mcp-code-intelligence install claude-code
mcp-code-intelligence install cursor
mcp-code-intelligence install windsurf

# Custom configuration
mcp-code-intelligence install --extensions .py,.js,.ts
mcp-code-intelligence install --embedding-model sentence-transformers/all-mpnet-base-v2

# Skip auto-indexing
mcp-code-intelligence install --no-auto-index

# Force re-installation
mcp-code-intelligence install --force

# Specific directory
mcp-code-intelligence install /path/to/project
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--with-mcp` | Enable MCP integration | `false` |
| `--extensions TEXT` | File extensions to index | `.py,.js,.ts,.tsx,.jsx,.mjs` |
| `--embedding-model TEXT` | Embedding model to use | `sentence-transformers/all-MiniLM-L6-v2` |
| `--no-auto-index` | Skip automatic indexing | `false` |
| `--force` | Force re-installation | `false` |
| `path` | Project directory | Current directory |

**What it does:**

1. Initializes project configuration (`.mcp-code-intelligence/`)
2. Optionally configures MCP integration
3. Automatically indexes codebase
4. Provides next-step hints

**Platform-Specific MCP Installation:**

```bash
# Project-scoped (creates .mcp.json in project)
mcp-code-intelligence install claude-code

# Global (updates system-wide config)
mcp-code-intelligence install cursor
mcp-code-intelligence install windsurf
mcp-code-intelligence install vscode

# List available platforms
mcp-code-intelligence install list
```

### `init`

Initialize project configuration without indexing.

```bash
# Basic initialization
mcp-code-intelligence init

# Custom file extensions
mcp-code-intelligence init --extensions .py,.js,.ts,.dart

# Custom embedding model
mcp-code-intelligence init --embedding-model sentence-transformers/all-mpnet-base-v2

# Force re-initialization
mcp-code-intelligence init --force

# Specific directory
mcp-code-intelligence init /path/to/project
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--extensions TEXT` | File extensions to index | `.py,.js,.ts,.tsx,.jsx,.mjs` |
| `--embedding-model TEXT` | Embedding model to use | `sentence-transformers/all-MiniLM-L6-v2` |
| `--force` | Force re-initialization | `false` |
| `path` | Project directory | Current directory |

**What it does:**

1. Creates `.mcp-code-intelligence/` directory
2. Creates `config.json` with settings
3. Initializes ChromaDB vector database
4. Does NOT index files (use `index` command after)

**Next steps after `init`:**

```bash
mcp-code-intelligence index  # Index your codebase
```

### `uninstall`

Remove MCP integration from platforms.

```bash
# Remove from specific platform
mcp-code-intelligence uninstall claude-code
mcp-code-intelligence uninstall cursor

# Remove from all platforms
mcp-code-intelligence uninstall --all

# List configured integrations
mcp-code-intelligence uninstall list

# Skip backup creation
mcp-code-intelligence uninstall claude-code --no-backup

# Alias: remove
mcp-code-intelligence remove claude-code
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--all` | Remove from all platforms | `false` |
| `--no-backup` | Skip backup creation | `false` |
| `platform` | Platform to remove from | Required (unless --all) |

---

## 🔍 Usage Commands

### `search`

Search codebase semantically using natural language queries.

```bash
# Basic search
mcp-code-intelligence search "authentication logic"
mcp-code-intelligence search "database connection setup"

# With result limit
mcp-code-intelligence search "authentication" --limit 5

# Filter by language
mcp-code-intelligence search "authentication" --language python

# Filter by file extension
mcp-code-intelligence search "authentication" --file-extension .ts

# Set similarity threshold
mcp-code-intelligence search "authentication" --threshold 0.8

# Similar code search
mcp-code-intelligence search --similar /path/to/file.py
mcp-code-intelligence search --similar /path/to/file.py --function my_function

# Context-based search
mcp-code-intelligence search "authentication" --context "security,validation"

# Interactive mode
mcp-code-intelligence search interactive

# View search history
mcp-code-intelligence search history
mcp-code-intelligence search history --limit 10
mcp-code-intelligence search history --clear

# Manage favorites
mcp-code-intelligence search favorites
mcp-code-intelligence search favorites add "auth query"
mcp-code-intelligence search favorites remove "auth query"
mcp-code-intelligence search favorites run "auth query"
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `query` | Search query or file path | Required |
| `--limit INTEGER` | Number of results | `10` |
| `--language TEXT` | Filter by language | All |
| `--file-extension TEXT` | Filter by file extension | All |
| `--threshold FLOAT` | Minimum similarity score (0.0-1.0) | `0.0` |
| `--function-name TEXT` | Filter by function name pattern | None |
| `--class-name TEXT` | Filter by class name pattern | None |
| `--similar PATH` | Find similar code to file | None |
| `--context TEXT` | Focus areas (comma-separated) | None |

**Search Modes:**

```bash
# Standard semantic search
mcp-code-intelligence search "your query"

# Find similar code
mcp-code-intelligence search --similar /path/to/file.py

# Interactive session
mcp-code-intelligence search interactive

# Search history
mcp-code-intelligence search history

# Favorites management
mcp-code-intelligence search favorites
```

### `index`

Index codebase for semantic search.

```bash
# Index entire project
mcp-code-intelligence index

# Index specific directory
mcp-code-intelligence index /path/to/directory

# Force full reindex
mcp-code-intelligence index --force

# Incremental indexing (default)
mcp-code-intelligence index --incremental

# Verbose output
mcp-code-intelligence index --verbose

# Specific project root
mcp-code-intelligence index --project-root /path/to/project
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--force` | Force complete reindex | `false` |
| `--incremental` | Only index changed files | `true` |
| `--verbose` | Show detailed progress | `false` |
| `--project-root PATH` | Project root directory | Current directory |
| `path` | Directory to index | Project root |

**When to use:**

- **`index`**: Regular updates after code changes
- **`index --force`**: After config changes, version upgrades, corruption
- **`index --incremental`**: Fast updates (default behavior)

### `status`

View project status and index statistics.

```bash
# View project status
mcp-code-intelligence status

# Specific project
mcp-code-intelligence status /path/to/project
```

**Shows:**

- Project root path
- Index path
- Configured file extensions
- Embedding model
- Supported languages
- Total chunks indexed
- Total files indexed
- Index size
- Last index time (if available)

---

## ⚙️ Maintenance Commands

### `config`

Manage project configuration.

```bash
# Show all configuration
mcp-code-intelligence config show

# Get specific value
mcp-code-intelligence config get skip_dotfiles
mcp-code-intelligence config get file_extensions

# Set configuration value
mcp-code-intelligence config set skip_dotfiles true
mcp-code-intelligence config set respect_gitignore true
mcp-code-intelligence config set file_extensions '.py,.js,.ts'

# List all configuration keys
mcp-code-intelligence config list-keys

# Reset to defaults
mcp-code-intelligence config reset
```

**Common Settings:**

| Setting | Description | Default |
|---------|-------------|---------|
| `skip_dotfiles` | Skip dotfiles/directories | `true` |
| `respect_gitignore` | Respect .gitignore patterns | `true` |
| `file_extensions` | Extensions to index | `.py,.js,.ts,.tsx,.jsx,.mjs` |
| `embedding_model` | Embedding model name | `sentence-transformers/all-MiniLM-L6-v2` |
| `indexing.batch_size` | Batch size for indexing | `32` |
| `indexing.chunk_size` | Code chunk size | `1000` |
| `indexing.chunk_overlap` | Chunk overlap | `200` |
| `indexing.exclude_patterns` | Patterns to exclude | `[]` |
| `auto_index.enabled` | Enable auto-indexing | `false` |
| `auto_index.check_interval` | Checks between auto-index | `10` |

**Subcommands:**

- `show`: Display all configuration
- `get KEY`: Get specific value
- `set KEY VALUE`: Set configuration value
- `list-keys`: List all available keys
- `reset`: Reset to default configuration

### `auto-index`

Configure automatic reindexing.

```bash
# Interactive setup
mcp-code-intelligence auto-index setup

# Specific method
mcp-code-intelligence auto-index setup --method git-hooks
mcp-code-intelligence auto-index setup --method file-watching
mcp-code-intelligence auto-index setup --method search-triggered

# Check status
mcp-code-intelligence auto-index status

# Remove auto-indexing
mcp-code-intelligence auto-index teardown
mcp-code-intelligence auto-index teardown --method git-hooks
```

**Methods:**

1. **`git-hooks`**: Trigger after git operations
   - After commits, merges, checkouts
   - Non-blocking background updates

2. **`file-watching`**: Real-time file monitoring
   - Detects changes as they happen
   - Debounced updates (2s delay)

3. **`search-triggered`**: Automatic during searches
   - Checks every N searches
   - Threshold-based (only small changes)

**Options:**

| Option | Description |
|--------|-------------|
| `--method TEXT` | Auto-index method (git-hooks, file-watching, search-triggered) |
| `--project-root PATH` | Project directory |

**Subcommands:**

- `setup`: Enable auto-indexing
- `teardown`: Disable auto-indexing
- `status`: View current configuration
- `check`: Check if reindexing needed

---

## 🔧 Advanced Commands

### `watch`

File watching and real-time monitoring.

```bash
# Start watching
mcp-code-intelligence watch
mcp-code-intelligence watch /path/to/project

# Check status
mcp-code-intelligence watch status

# Enable watching
mcp-code-intelligence watch enable

# Disable watching
mcp-code-intelligence watch disable

# Verbose output
mcp-code-intelligence watch --verbose
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--verbose` | Show detailed output | `false` |
| `--debounce FLOAT` | Debounce delay (seconds) | `2.0` |
| `project_root` | Directory to watch | Current directory |

**Subcommands:**

- `main`: Start file watcher (default)
- `status`: Check watcher status
- `enable`: Enable watching
- `disable`: Disable watching

### `mcp`

MCP server integration and configuration.

```bash
# Install MCP integration
mcp-code-intelligence mcp install
mcp-code-intelligence mcp install --server-name custom-name

# Configure specific tools
mcp-code-intelligence mcp configure-auggie
mcp-code-intelligence mcp configure-claude-code
mcp-code-intelligence mcp configure-codex
mcp-code-intelligence mcp configure-gemini

# Start MCP server
mcp-code-intelligence mcp server

# Reset MCP configuration
mcp-code-intelligence mcp reset
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--server-name TEXT` | MCP server name | `mcp-code-intelligence` |
| `--project-root PATH` | Project directory | Current directory |

**Subcommands:**

- `install`: Add MCP integration
- `configure-auggie`: Configure Auggie integration
- `configure-claude-code`: Configure Claude Code integration
- `configure-codex`: Configure Codex integration
- `configure-gemini`: Configure Gemini integration
- `server`: Start MCP server
- `reset`: Reset MCP configuration

### `doctor`

Diagnose system dependencies and configuration.

```bash
# Run diagnostics
mcp-code-intelligence doctor
```

**Checks:**

- Python version (3.11+)
- Required dependencies installed
- ChromaDB connectivity
- Sentence Transformers availability
- Tree-sitter parsers available
- Configuration validity
- Index health

**Output:**

- ✅ Pass: Dependency/check successful
- ❌ Fail: Issue detected with recovery instructions
- ⚠️ Warning: Non-critical issue

### `version`

Show version information.

```bash
# Display version
mcp-code-intelligence version

# Shows:
# - Version number
# - Build number
```

### `help`

Display help information.

```bash
# General help
mcp-code-intelligence --help
mcp-code-intelligence help

# Command-specific help
mcp-code-intelligence search --help
mcp-code-intelligence index --help
mcp-code-intelligence install --help

# Get help for specific command
mcp-code-intelligence help search
mcp-code-intelligence help index
```

---

## 🌐 Global Options

Options available for all commands:

```bash
# Get help
mcp-code-intelligence COMMAND --help

# Version info
mcp-code-intelligence --version

# Verbose output (some commands)
mcp-code-intelligence COMMAND --verbose
```

---

## 📚 Command Categories

### Setup & Installation

```bash
mcp-code-intelligence setup                 # Zero-config smart setup (recommended)
mcp-code-intelligence install               # Manual setup with more control
mcp-code-intelligence install claude-code   # Add specific MCP platform
mcp-code-intelligence init                  # Just initialize (advanced)
mcp-code-intelligence uninstall claude-code # Remove MCP integration
```

### Daily Usage

```bash
mcp-code-intelligence search "query"        # Search code
mcp-code-intelligence index                 # Update index
mcp-code-intelligence status                # Check status
```

### Configuration

```bash
mcp-code-intelligence config show           # View settings
mcp-code-intelligence config set KEY VALUE  # Change setting
mcp-code-intelligence auto-index setup      # Enable auto-indexing
```

### Troubleshooting

```bash
mcp-code-intelligence doctor                # Diagnose issues
mcp-code-intelligence index --force         # Rebuild index
mcp-code-intelligence config reset          # Reset configuration
```

---

## 🎯 Common Workflows

### First-Time Setup

```bash
# Option 1: Zero-config smart setup (recommended)
mcp-code-intelligence setup

# Option 2: Manual setup with more control
mcp-code-intelligence install

# Option 3: Completely manual (advanced)
mcp-code-intelligence init
mcp-code-intelligence index
```

### Daily Development

```bash
# Search for code
mcp-code-intelligence search "authentication logic"

# Index after changes (automatic with git hooks)
mcp-code-intelligence index

# Check what's indexed
mcp-code-intelligence status
```

### Team Onboarding

```bash
# Clone repository
git clone <repo-url>
cd <repo>

# Zero-config setup (recommended)
mcp-code-intelligence setup

# Or manual setup with auto-indexing
mcp-code-intelligence install
mcp-code-intelligence auto-index setup --method git-hooks
```

### Troubleshooting Issues

```bash
# Check system
mcp-code-intelligence doctor

# Rebuild index
mcp-code-intelligence index --force

# Check configuration
mcp-code-intelligence config show

# Reset if needed
mcp-code-intelligence config reset
mcp-code-intelligence init --force
mcp-code-intelligence index
```

---

## 🔄 Deprecated Commands

These commands are deprecated but still work (redirected to new commands):

| Old Command | New Command |
|-------------|-------------|
| `find` | `search` |
| `search-similar` | `search --similar` |
| `search-context` | `search --context` |
| `interactive` | `search interactive` |
| `history` | `search history` |
| `favorites` | `search favorites` |
| `add-favorite` | `search favorites add` |
| `remove-favorite` | `search favorites remove` |
| `health` | `index health` |
| `watch` (top-level) | `index watch` or `auto-index setup --method file-watching` |
| `auto-index` (top-level) | `auto-index setup` |
| `reset` | `mcp reset` or `config reset` |
| `init-check` | `init check` |
| `init-mcp` | `mcp install` |
| `init-models` | `config models` |

---

## 📖 Examples

### Example 1: Find Authentication Code

```bash
# Search for auth logic
mcp-code-intelligence search "user authentication with JWT tokens" --limit 5

# Filter to Python only
mcp-code-intelligence search "user authentication" --language python

# High confidence only
mcp-code-intelligence search "user authentication" --threshold 0.85
```

### Example 2: Set Up New Project

```bash
# Zero-config setup (recommended)
mcp-code-intelligence setup

# Verify (already done by setup, but you can check)
mcp-code-intelligence status

# Test search
mcp-code-intelligence search "test query"

# Alternative: Manual setup with more control
mcp-code-intelligence install
mcp-code-intelligence auto-index setup --method git-hooks
```

### Example 3: Optimize for Large Codebase

```bash
# Configure exclusions
mcp-code-intelligence config set skip_dotfiles true
mcp-code-intelligence config set respect_gitignore true
mcp-code-intelligence config set indexing.exclude_patterns '["dist/", "build/", "node_modules/"]'

# Reduce batch size
mcp-code-intelligence config set indexing.batch_size 16

# Index
mcp-code-intelligence index --verbose
```

### Example 4: Find Similar Code

```bash
# Find similar implementations
mcp-code-intelligence search --similar src/utils/auth.py

# Similar to specific function
mcp-code-intelligence search --similar src/utils/auth.py --function validate_token

# Limit results
mcp-code-intelligence search --similar src/utils/auth.py --limit 5
```

---

## 💡 Tips

1. **Use `--help` liberally**: Every command has detailed help
2. **Start with `setup`**: Zero-config, fastest way to get started (recommended)
3. **Use `install` for control**: When you need specific extensions or models
4. **Enable auto-indexing**: File watching is set up by `setup` automatically
5. **Use interactive search**: Great for exploratory searches
6. **Configure exclusions**: Skip build directories and dependencies
7. **Check status regularly**: Know what's indexed
8. **Use `doctor` when troubleshooting**: First diagnostic step
9. **Leverage filters**: Language and threshold for precise results
10. **Commit `.mcp.json`**: Share MCP configuration with your team

---

## 📚 Next Steps

- **[Searching Guide](../guides/searching.md)** - Master semantic search
- **[Indexing Guide](../guides/indexing.md)** - Optimize indexing
- **[Configuration Guide](configuration.md)** - Advanced settings
- **[Troubleshooting Guide](../advanced/troubleshooting.md)** - Solve common issues

