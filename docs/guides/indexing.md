# Indexing Guide

Complete guide to indexing your codebase for semantic search with mcp-code-intelligence.

## 📋 Table of Contents

- [What is Indexing?](#what-is-indexing)
- [When to Index](#when-to-index)
- [Basic Indexing](#basic-indexing)
- [Indexing Strategies](#indexing-strategies)
- [Auto-Indexing](#auto-indexing)
- [Configuration](#configuration)
- [Performance Optimization](#performance-optimization)
- [Troubleshooting](#troubleshooting)

---

## 🔍 What is Indexing?

Indexing is the process of analyzing your codebase and creating a searchable vector database. It involves:

### The Indexing Process

1. **File Discovery**
   - Scan project for supported file types
   - Respect `.gitignore` patterns (configurable)
   - Skip dotfiles and directories (configurable)
   - Filter by configured extensions

2. **AST Parsing (Tree-sitter)**
   - Parse code into Abstract Syntax Tree (AST)
   - Extract functions, classes, methods
   - Capture docstrings and comments
   - Preserve code structure and context

3. **Chunking**
   - Split code into meaningful chunks
   - Maintain context within chunks
   - Associate metadata (file, line numbers, type)
   - Optimize chunk size for search

4. **Embedding Generation**
   - Convert code chunks to vector embeddings
   - Use sentence-transformers model (default: all-MiniLM-L6-v2)
   - Create semantic representation
   - Enable similarity search

5. **Storage**
   - Store embeddings in ChromaDB
   - Index for fast retrieval
   - Track file modification times
   - Maintain metadata for filtering

### What Gets Indexed

- **Code structures**: Functions, classes, methods
- **Documentation**: Docstrings, comments
- **Implementations**: Function bodies, class definitions
- **Metadata**: File paths, languages, types, line numbers

### Supported Languages

- Python (`.py`, `.pyw`)
- JavaScript (`.js`, `.jsx`, `.mjs`)
- TypeScript (`.ts`, `.tsx`)
- Dart (`.dart`)
- PHP (`.php`, `.phtml`)
- Ruby (`.rb`, `.rake`, `.gemspec`)
- HTML (`.html`, `.htm`)
- Markdown/Text (`.md`, `.txt`, `.markdown`)

---

## ⏰ When to Index

### Initial Setup

Always index when you first set up mcp-code-intelligence:

```bash
# First time setup
mcp-code-intelligence install  # Initializes and auto-indexes

# Or manually
mcp-code-intelligence init && mcp-code-intelligence index
```

### After Code Changes

Reindex when you've made significant changes:

```bash
# After adding new files
mcp-code-intelligence index

# After refactoring
mcp-code-intelligence index --force

# After pulling changes
git pull && mcp-code-intelligence index
```

### Scheduled Maintenance

Regular reindexing ensures search accuracy:

```bash
# Daily via cron
0 2 * * * cd /path/to/project && mcp-code-intelligence index

# Weekly full reindex
0 2 * * 0 cd /path/to/project && mcp-code-intelligence index --force
```

### Auto-Indexing Triggers

Set up automatic indexing for continuous updates:

- **Git hooks**: After commits, merges, checkouts
- **File watching**: Real-time monitoring
- **Search-triggered**: Automatic during searches
- **Scheduled tasks**: Cron jobs or Windows tasks
- **CI/CD integration**: After deployments

See [Auto-Indexing](#auto-indexing) section for details.

---

## 🚀 Basic Indexing

### Index Entire Project

```bash
# Index from current directory
mcp-code-intelligence index

# Index specific directory
mcp-code-intelligence index /path/to/project

# Verbose output
mcp-code-intelligence index --verbose
```

### Force Full Reindex

Rebuild the entire index from scratch:

```bash
# Force complete reindex
mcp-code-intelligence index --force

# Useful when:
# - Upgrading mcp-code-intelligence versions
# - Changing embedding models
# - Index appears corrupted
# - Configuration changed significantly
```

### Incremental Indexing

Update only changed files (default behavior):

```bash
# Incremental update
mcp-code-intelligence index

# How it works:
# - Checks file modification times
# - Only reprocesses changed files
# - Adds newly created files
# - Removes deleted files
# - Much faster than full reindex
```

### Check Index Status

See what's indexed:

```bash
# Project status
mcp-code-intelligence status

# Shows:
# - Total files indexed
# - Total code chunks
# - Index size
# - Last index time
# - Configured languages
# - File extensions
```

---

## 🎯 Indexing Strategies

### Development Workflow

**For active development:**

```bash
# Option 1: Git hooks (recommended)
mcp-code-intelligence auto-index setup --method git-hooks

# Option 2: File watching
mcp-code-intelligence auto-index setup --method file-watching

# Option 3: Manual after commits
git commit && mcp-code-intelligence index
```

### Large Codebases

**For projects with 10,000+ files:**

```bash
# 1. Configure exclusions
mcp-code-intelligence config set skip_dotfiles true
mcp-code-intelligence config set respect_gitignore true

# 2. Reduce batch size for memory
mcp-code-intelligence config set indexing.batch_size 16

# 3. Index incrementally
mcp-code-intelligence index --incremental

# 4. Monitor progress
mcp-code-intelligence index --verbose
```

### Team Environments

**For collaborative projects:**

```bash
# 1. Share configuration
git add .mcp-code-intelligence/config.json
git commit -m "Add mcp-code-intelligence config"

# 2. Team members initialize
mcp-code-intelligence init
mcp-code-intelligence index

# 3. Set up auto-indexing
mcp-code-intelligence auto-index setup --method git-hooks

# 4. Add to .gitignore
echo ".mcp-code-intelligence/chroma_data/" >> .gitignore
```

### CI/CD Integration

**For continuous integration:**

```yaml
# .github/workflows/search-index.yml
name: Update Search Index
on:
  push:
    branches: [main]

jobs:
  update-index:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v4
        with:
          python-version: '3.12'

      - name: Install mcp-code-intelligence
        run: pip install mcp-code-intelligence

      - name: Update search index
        run: |
          mcp-code-intelligence init
          mcp-code-intelligence index

      - name: Cache index
        uses: actions/cache@v3
        with:
          path: .mcp-code-intelligence/
          key: search-index-${{ github.sha }}
```

### Monorepo Handling

**For monorepos with multiple projects:**

```bash
# Index specific subdirectories
mcp-code-intelligence index ./frontend
mcp-code-intelligence index ./backend
mcp-code-intelligence index ./shared

# Or configure exclusions
mcp-code-intelligence config set indexing.exclude_patterns '["build/", "dist/", "node_modules/"]'

# Then index everything
mcp-code-intelligence index
```

---

## ⚡ Auto-Indexing

Automatic reindexing keeps your search index current without manual intervention.

### Quick Setup

```bash
# Interactive setup (recommended)
mcp-code-intelligence auto-index setup

# Specific method
mcp-code-intelligence auto-index setup --method git-hooks
mcp-code-intelligence auto-index setup --method file-watching
mcp-code-intelligence auto-index setup --method search-triggered
```

### Method 1: Git Hooks

**Best for development workflows**

```bash
# Set up Git hooks
mcp-code-intelligence auto-index setup --method git-hooks

# Triggers after:
# - git commit
# - git merge
# - git checkout
# - git pull
# - git rebase
```

**How it works:**
- Installs hooks in `.git/hooks/`
- Non-blocking (runs in background)
- Only reindexes changed files
- Cross-platform compatible

**Remove Git hooks:**
```bash
mcp-code-intelligence auto-index teardown --method git-hooks
```

### Method 2: File Watching

**Best for real-time updates**

```bash
# Start file watcher
mcp-code-intelligence auto-index setup --method file-watching

# Or use watch command directly
mcp-code-intelligence watch

# Check status
mcp-code-intelligence watch status
```

**How it works:**
- Monitors file system for changes
- Debounces rapid changes (waits 2 seconds)
- Only reindexes affected files
- Runs in background

**Stop watching:**
```bash
# Disable auto-indexing
mcp-code-intelligence auto-index teardown --method file-watching

# Or stop watch
mcp-code-intelligence watch disable
```

### Method 3: Search-Triggered

**Best for low-maintenance setups**

```bash
# Enable search-triggered indexing
mcp-code-intelligence auto-index setup --method search-triggered

# Or configure manually
mcp-code-intelligence config set auto_index.enabled true
mcp-code-intelligence config set auto_index.check_interval 10
```

**How it works:**
- Checks for changes every N searches (default: 10)
- Non-blocking (never slows down searches)
- Threshold-based (only auto-reindexes small changes)
- Zero maintenance

**Configuration:**
```bash
# Check every 5 searches
mcp-code-intelligence config set auto_index.check_interval 5

# Only auto-index if < 50 files changed
mcp-code-intelligence config set auto_index.max_files 50
```

### Method 4: Scheduled Tasks

**Best for production environments**

```bash
# Linux/macOS (crontab)
crontab -e

# Add line for hourly indexing:
0 * * * * cd /path/to/project && mcp-code-intelligence index

# Daily full reindex:
0 2 * * * cd /path/to/project && mcp-code-intelligence index --force
```

```powershell
# Windows (Task Scheduler)
schtasks /create /tn "MCP Code Intelligence Index" /tr "mcp-code-intelligence index" /sc hourly
```

### Method 5: CI/CD Integration

**Best for team environments**

See [CI/CD Integration](#cicd-integration) in Indexing Strategies.

### Check Auto-Index Status

```bash
# View current setup
mcp-code-intelligence auto-index status

# Shows:
# - Enabled methods
# - Configuration
# - Last auto-index time
# - Statistics
```

---

## ⚙️ Configuration

### Indexing Behavior

```bash
# Skip dotfiles (default: true)
mcp-code-intelligence config set skip_dotfiles true

# Respect .gitignore (default: true)
mcp-code-intelligence config set respect_gitignore true

# File extensions to index
mcp-code-intelligence config set file_extensions '.py,.js,.ts,.tsx,.jsx'

# Exclude patterns
mcp-code-intelligence config set indexing.exclude_patterns '["*.min.js", "dist/", "build/"]'
```

### Performance Tuning

```bash
# Batch size (default: 32)
mcp-code-intelligence config set indexing.batch_size 16  # Lower for less memory

# Chunk size (default: 1000 characters)
mcp-code-intelligence config set indexing.chunk_size 2000

# Chunk overlap (default: 200 characters)
mcp-code-intelligence config set indexing.chunk_overlap 100
```

### Embedding Model

```bash
# View current model
mcp-code-intelligence config get embedding_model

# Change model (requires full reindex)
mcp-code-intelligence config set embedding_model 'sentence-transformers/all-mpnet-base-v2'
mcp-code-intelligence index --force
```

**Available models:**
- `sentence-transformers/all-MiniLM-L6-v2` (default, fast, 384 dims)
- `sentence-transformers/all-mpnet-base-v2` (better quality, slower, 768 dims)
- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (multilingual)

### View All Configuration

```bash
# Show all settings
mcp-code-intelligence config show

# Get specific value
mcp-code-intelligence config get skip_dotfiles

# Reset to defaults
mcp-code-intelligence config reset
```

---

## 🚀 Performance Optimization

### For Large Codebases

#### 1. Enable Gitignore and Dotfile Skipping

```bash
mcp-code-intelligence config set skip_dotfiles true
mcp-code-intelligence config set respect_gitignore true
```

**Impact:** 50-80% reduction in files indexed

#### 2. Exclude Unnecessary Directories

```bash
# Common exclusions
mcp-code-intelligence config set indexing.exclude_patterns '[
  "node_modules/",
  "venv/",
  ".venv/",
  "dist/",
  "build/",
  "*.min.js",
  "*.bundle.js",
  "coverage/",
  ".git/",
  "__pycache__/"
]'
```

#### 3. Reduce Batch Size

```bash
# Lower memory usage
mcp-code-intelligence config set indexing.batch_size 16
```

**Impact:** Lower peak memory usage, slightly slower indexing

#### 4. Use Incremental Indexing

```bash
# Default behavior - only changed files
mcp-code-intelligence index
```

**Impact:** 10-100x faster than full reindex

### For Fast Machines

#### Increase Batch Size

```bash
# Higher throughput
mcp-code-intelligence config set indexing.batch_size 64
```

**Impact:** Faster indexing, higher memory usage

### Monitoring Performance

```bash
# Time indexing
time mcp-code-intelligence index

# Verbose output
mcp-code-intelligence index --verbose

# Check index stats
mcp-code-intelligence status
```

### Benchmark Results

Typical performance (16-core CPU, 32GB RAM):

| Codebase Size | Full Index | Incremental | Memory |
|---------------|------------|-------------|--------|
| 100 files | 10s | 2s | 200MB |
| 1,000 files | 1m 30s | 10s | 500MB |
| 10,000 files | 15m | 1m | 2GB |
| 100,000 files | 2h 30m | 10m | 8GB |

---

## 🔧 Troubleshooting

### Indexing Fails

#### Error: "Tree-sitter parser not found"

```bash
# Solution: Reinstall mcp-code-intelligence
pip install --force-reinstall mcp-code-intelligence

# Or install from source
git clone https://github.com/bobmatnyc/mcp-code-intelligence.git
cd mcp-code-intelligence
uv sync && uv pip install -e .
```

#### Error: "Permission denied"

```bash
# Check directory permissions
ls -la .mcp-code-intelligence/

# Fix permissions
chmod -R u+w .mcp-code-intelligence/

# Or remove and reinit
rm -rf .mcp-code-intelligence/
mcp-code-intelligence init
```

#### Error: "Out of memory"

```bash
# Reduce batch size
mcp-code-intelligence config set indexing.batch_size 8

# Or index in smaller chunks
mcp-code-intelligence index ./src/module1
mcp-code-intelligence index ./src/module2
```

### Indexing Is Slow

#### Optimize Configuration

```bash
# Enable gitignore
mcp-code-intelligence config set respect_gitignore true

# Skip dotfiles
mcp-code-intelligence config set skip_dotfiles true

# Exclude build directories
mcp-code-intelligence config set indexing.exclude_patterns '["dist/", "build/", "node_modules/"]'
```

#### Check What's Being Indexed

```bash
# Dry run (if available)
mcp-code-intelligence index --verbose

# Check file count
find . -name "*.py" -not -path "*/\.*" | wc -l
```

### Missing Files in Index

#### Check File Extensions

```bash
# View configured extensions
mcp-code-intelligence config get file_extensions

# Add missing extension
mcp-code-intelligence config set file_extensions '.py,.js,.ts,.dart,.php,.rb'

# Reindex
mcp-code-intelligence index --force
```

#### Check Exclusions

```bash
# View exclusions
mcp-code-intelligence config get indexing.exclude_patterns

# Remove overly broad exclusion
mcp-code-intelligence config set indexing.exclude_patterns '["dist/", "build/"]'
```

#### Check Gitignore

```bash
# Temporarily disable gitignore
mcp-code-intelligence config set respect_gitignore false
mcp-code-intelligence index --force

# Re-enable
mcp-code-intelligence config set respect_gitignore true
```

### Index Appears Corrupted

#### Rebuild from Scratch

```bash
# Full reindex
mcp-code-intelligence index --force

# Or delete and recreate
rm -rf .mcp-code-intelligence/
mcp-code-intelligence init
mcp-code-intelligence index
```

#### Verify Index Health

```bash
# Check status
mcp-code-intelligence status

# Test search
mcp-code-intelligence search "test query"

# Check file count matches
find . -name "*.py" | wc -l
```

### Auto-Indexing Not Working

#### Check Auto-Index Status

```bash
mcp-code-intelligence auto-index status
```

#### Git Hooks Not Triggering

```bash
# Check hooks exist
ls -la .git/hooks/

# Reinstall hooks
mcp-code-intelligence auto-index teardown --method git-hooks
mcp-code-intelligence auto-index setup --method git-hooks

# Make executable
chmod +x .git/hooks/post-commit
chmod +x .git/hooks/post-merge
```

#### File Watching Not Working

```bash
# Check watcher status
mcp-code-intelligence watch status

# Restart watcher
mcp-code-intelligence watch disable
mcp-code-intelligence watch enable

# Check for errors
mcp-code-intelligence watch --verbose
```

---

## 📚 Next Steps

- **[Searching Guide](searching.md)** - Learn how to search effectively
- **[CLI Commands Reference](../reference/cli-commands.md)** - Complete command reference
- **[Configuration Guide](configuration.md)** - Advanced configuration
- **[Performance Guide](../advanced/performance.md)** - Optimization techniques

---

## 💡 Best Practices

1. **Use incremental indexing**: Default behavior is usually sufficient
2. **Enable gitignore**: Respect .gitignore to exclude build artifacts
3. **Set up auto-indexing**: Choose method that fits your workflow
4. **Exclude generated code**: Don't index build outputs, dependencies
5. **Monitor index size**: Large indexes may need optimization
6. **Reindex after upgrades**: Full reindex after version updates
7. **Share configuration**: Commit config.json for team consistency
8. **Regular maintenance**: Periodic full reindex keeps index healthy



