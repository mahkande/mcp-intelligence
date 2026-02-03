# Configuration Guide

This document provides comprehensive information about configuring MCP Code Intelligence for your project.

## Table of Contents

- [Configuration File](#configuration-file)
- [Configuration Management](#configuration-management)
- [Core Settings](#core-settings)
- [Indexing Behavior Settings](#indexing-behavior-settings)
- [Use Cases and Examples](#use-cases-and-examples)
- [Advanced Configuration](#advanced-configuration)

## Configuration File

MCP Code Intelligence stores project configuration in `.mcp-code-intelligence/config.json` within your project root.

### Default Configuration

```json
{
  "project_root": "/path/to/project",
  "file_extensions": [".py", ".js", ".ts", ".jsx", ".tsx", ".dart", ".php", ".rb", ".html", ".md", ".txt"],
  "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
  "similarity_threshold": 0.75,
  "languages": ["python", "javascript", "typescript"],
  "watch_files": false,
  "cache_embeddings": true,
  "max_cache_size": 1000,
  "max_chunk_size": 512,
  "skip_dotfiles": true,
  "respect_gitignore": true,
  "auto_reindex_on_upgrade": true
}
```

## Configuration Management

### View Configuration

```bash
# Show all configuration settings
mcp-code-intelligence config show

# Show configuration in JSON format
mcp-code-intelligence config show --json

# Get specific configuration value
mcp-code-intelligence config get skip_dotfiles
mcp-code-intelligence config get respect_gitignore
```

### Update Configuration

```bash
# Set a configuration value
mcp-code-intelligence config set <key> <value>

# Examples
mcp-code-intelligence config set similarity_threshold 0.8
mcp-code-intelligence config set skip_dotfiles false
mcp-code-intelligence config set respect_gitignore true
```

### List Available Keys

```bash
# Show all available configuration keys
mcp-code-intelligence config list-keys
```

### Reset Configuration

```bash
# Reset specific key to default
mcp-code-intelligence config reset skip_dotfiles

# Reset all configuration to defaults
mcp-code-intelligence config reset

# Skip confirmation prompt
mcp-code-intelligence config reset --yes
```

## Core Settings

### `project_root` (string/path)
- **Description**: Root directory of your project
- **Default**: Current working directory
- **Usage**: Automatically set during initialization

### `file_extensions` (list)
- **Description**: List of file extensions to index
- **Default**: `[".py", ".js", ".ts", ".jsx", ".tsx", ".dart", ".php", ".rb", ".html", ".md", ".txt"]`
- **Example**:
  ```bash
  mcp-code-intelligence config set file_extensions .py,.js,.ts
  ```

### `embedding_model` (string)
- **Description**: Sentence transformer model for generating embeddings
- **Default**: `sentence-transformers/all-MiniLM-L6-v2`
- **Options**: Any HuggingFace sentence-transformers model
- **Example**:
  ```bash
  mcp-code-intelligence config set embedding_model microsoft/codebert-base

  # List available models
  mcp-code-intelligence config models
  ```

### `similarity_threshold` (float, 0.0-1.0)
- **Description**: Minimum similarity score for search results
- **Default**: `0.75`
- **Example**:
  ```bash
  mcp-code-intelligence config set similarity_threshold 0.6
  ```

### `watch_files` (boolean)
- **Description**: Enable automatic file watching and reindexing
- **Default**: `false`
- **Example**:
  ```bash
  mcp-code-intelligence config set watch_files true
  ```

### `cache_embeddings` (boolean)
- **Description**: Enable LRU caching of embeddings for better performance
- **Default**: `true`
- **Example**:
  ```bash
  mcp-code-intelligence config set cache_embeddings false
  ```

### `max_cache_size` (integer)
- **Description**: Maximum number of embeddings to cache
- **Default**: `1000`
- **Example**:
  ```bash
  mcp-code-intelligence config set max_cache_size 2000
  ```

### `max_chunk_size` (integer)
- **Description**: Maximum size of code chunks in tokens
- **Default**: `512`
- **Example**:
  ```bash
  mcp-code-intelligence config set max_chunk_size 1024
  ```

### `auto_reindex_on_upgrade` (boolean)
- **Description**: Automatically reindex when tool version is upgraded (major/minor versions)
- **Default**: `true`
- **Example**:
  ```bash
  mcp-code-intelligence config set auto_reindex_on_upgrade false
  ```

## Indexing Behavior Settings

### `skip_dotfiles` (boolean)
- **Description**: Controls whether files and directories starting with "." are skipped during indexing
- **Default**: `true` (recommended for most projects)
- **Whitelisted Directories**: These directories are **always indexed** regardless of this setting:
  - `.github/` - GitHub workflows, actions, and configurations
  - `.gitlab-ci/` - GitLab CI/CD configurations
  - `.circleci/` - CircleCI configurations
- **When `true`** (default):
  - Skips all dotfiles and dot-directories except whitelisted ones
  - Improves indexing performance by avoiding hidden system files
  - Prevents indexing of IDE configurations, cache files, etc.
- **When `false`**:
  - Indexes all dotfiles and dot-directories
  - Subject to `.gitignore` patterns if `respect_gitignore` is `true`
  - Useful for projects that have important configuration in dotfiles
- **Example**:
  ```bash
  # Skip dotfiles (default)
  mcp-code-intelligence config set skip_dotfiles true

  # Index all dotfiles
  mcp-code-intelligence config set skip_dotfiles false

  # Check current setting
  mcp-code-intelligence config get skip_dotfiles
  ```

### `respect_gitignore` (boolean)
- **Description**: Controls whether `.gitignore` patterns are respected during indexing
- **Default**: `true` (recommended for most projects)
- **When `true`** (default):
  - Respects all patterns in `.gitignore` file
  - Prevents indexing of build artifacts, dependencies, etc.
  - Reduces index size and improves search relevance
- **When `false`**:
  - Ignores `.gitignore` patterns
  - Indexes all files (subject to `skip_dotfiles` if enabled)
  - Useful for analyzing dependencies or generated code
- **Example**:
  ```bash
  # Respect .gitignore (default)
  mcp-code-intelligence config set respect_gitignore true

  # Ignore .gitignore patterns
  mcp-code-intelligence config set respect_gitignore false

  # Check current setting
  mcp-code-intelligence config get respect_gitignore
  ```

## Use Cases and Examples

### Use Case 1: Default Behavior (Recommended)

**Scenario**: Standard project with typical file structure

**Configuration**:
```bash
mcp-code-intelligence config set skip_dotfiles true
mcp-code-intelligence config set respect_gitignore true
```

**What gets indexed**:
- ✅ All source code files
- ✅ Whitelisted CI/CD configurations (`.github/`, `.gitlab-ci/`, `.circleci/`)
- ❌ Hidden configuration files (`.env`, `.vscode/`, etc.)
- ❌ Files in `.gitignore` (node_modules, build artifacts, etc.)

**Benefits**:
- Fast indexing
- Relevant search results
- Excludes temporary and generated files

### Use Case 2: Index Everything

**Scenario**: Deep code analysis, including dependencies and build artifacts

**Configuration**:
```bash
mcp-code-intelligence config set skip_dotfiles false
mcp-code-intelligence config set respect_gitignore false
```

**What gets indexed**:
- ✅ All source code files
- ✅ All dotfiles and dot-directories
- ✅ Files in `.gitignore` (node_modules, build/, etc.)
- ✅ All configuration files

**Benefits**:
- Complete codebase coverage
- Useful for analyzing dependencies
- Good for understanding generated code

**Drawbacks**:
- Slower indexing
- Larger index size
- More noise in search results

### Use Case 3: Index Dotfiles but Respect .gitignore

**Scenario**: Want to search configuration files but skip build artifacts

**Configuration**:
```bash
mcp-code-intelligence config set skip_dotfiles false
mcp-code-intelligence config set respect_gitignore true
```

**What gets indexed**:
- ✅ All source code files
- ✅ All dotfiles (`.env.example`, `.eslintrc.js`, etc.)
- ✅ Whitelisted CI/CD configurations
- ❌ Files in `.gitignore`

**Benefits**:
- Search through configuration files
- Excludes build artifacts and dependencies
- Good balance between coverage and relevance

### Use Case 4: Skip Dotfiles but Ignore .gitignore

**Scenario**: Index files in `.gitignore` but skip hidden system files

**Configuration**:
```bash
mcp-code-intelligence config set skip_dotfiles true
mcp-code-intelligence config set respect_gitignore false
```

**What gets indexed**:
- ✅ All source code files
- ✅ Files in `.gitignore` (dependencies, build artifacts)
- ✅ Whitelisted CI/CD configurations
- ❌ Other dotfiles and dot-directories

**Benefits**:
- Index generated code and dependencies
- Avoid hidden system files
- Useful for analyzing build output

## Advanced Configuration

### Interaction Between Settings

The `skip_dotfiles` and `respect_gitignore` settings work together:

| skip_dotfiles | respect_gitignore | Behavior |
|---------------|-------------------|----------|
| `true` | `true` | Skip dotfiles (except whitelisted), respect .gitignore (DEFAULT) |
| `true` | `false` | Skip dotfiles (except whitelisted), ignore .gitignore |
| `false` | `true` | Index all dotfiles, respect .gitignore |
| `false` | `false` | Index everything |

### Whitelisted Dotfile Directories

These directories are **always indexed** regardless of `skip_dotfiles` setting:

1. **`.github/`** - GitHub-specific configurations
   - Workflows (`.github/workflows/`)
   - Actions (`.github/actions/`)
   - Issue templates, PR templates, etc.

2. **`.gitlab-ci/`** - GitLab CI/CD configurations
   - Pipeline definitions
   - Job templates

3. **`.circleci/`** - CircleCI configurations
   - Config files (`.circleci/config.yml`)

**Rationale**: CI/CD configurations are important for understanding project automation and should be searchable by default.

### Performance Considerations

**Indexing Performance**:
- Enabling `skip_dotfiles=true` improves indexing speed by 20-30%
- Enabling `respect_gitignore=true` can improve speed by 40-60% for large projects with many dependencies

**Index Size**:
- Default settings typically result in 50-80% smaller indexes
- Smaller indexes mean faster searches and lower memory usage

**Search Relevance**:
- Default settings improve search relevance by excluding noise
- Generated code and dependencies can dilute search results

### Environment-Specific Configuration

Different configurations for different environments:

**Development Environment**:
```bash
# Fast indexing, exclude dependencies
mcp-code-intelligence config set skip_dotfiles true
mcp-code-intelligence config set respect_gitignore true
```

**Code Review/Analysis**:
```bash
# Include configuration files
mcp-code-intelligence config set skip_dotfiles false
mcp-code-intelligence config set respect_gitignore true
```

**Dependency Analysis**:
```bash
# Include everything
mcp-code-intelligence config set skip_dotfiles false
mcp-code-intelligence config set respect_gitignore false
```

## Troubleshooting

### Files Not Being Indexed

**Problem**: Expected files are not showing up in search results

**Solutions**:
1. Check if files are dotfiles:
   ```bash
   mcp-code-intelligence config get skip_dotfiles
   # If true, dotfiles are skipped (except whitelisted)
   ```

2. Check if files are in `.gitignore`:
   ```bash
   mcp-code-intelligence config get respect_gitignore
   # If true, files in .gitignore are skipped
   ```

3. Reindex after changing settings:
   ```bash
   mcp-code-intelligence index --force
   ```

### Too Many Files Being Indexed

**Problem**: Indexing is slow and search results include irrelevant files

**Solutions**:
1. Enable default settings:
   ```bash
   mcp-code-intelligence config set skip_dotfiles true
   mcp-code-intelligence config set respect_gitignore true
   ```

2. Update `.gitignore` to exclude unwanted directories

3. Reindex:
   ```bash
   mcp-code-intelligence index --force
   ```

### Checking What Will Be Indexed

```bash
# View current configuration
mcp-code-intelligence config show

# Check project status before indexing
mcp-code-intelligence status

# Reindex with current settings
mcp-code-intelligence index --force
```

## See Also

- [CLI Commands](../README.md#-documentation) - Complete CLI reference
- [Installation Guide](DEPLOY.md) - Setup and deployment
- [Developer Guide](developer/DEVELOPER.md) - Advanced usage


