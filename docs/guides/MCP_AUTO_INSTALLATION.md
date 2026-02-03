# MCP Auto-Installation Guide

**Simplified MCP installation with automatic project path detection**

## Overview

The `mcp-code-intelligence install mcp` command now features **automatic project path detection**, eliminating the need for manual configuration and ensuring the MCP server always points to the correct project.

## Key Features

✅ **Auto-detect project root** from current directory or git repository
✅ **Works from any subdirectory** - no need to be in project root
✅ **Supports monorepos** - detects per-project initialization
✅ **Multiple platform support** - Claude Code, Cursor, Auggie, etc.
✅ **Clear status reporting** - see which projects are configured

## Quick Start

### 1. Initialize Your Project

```bash
# From your project directory
cd /path/to/your/project
mcp-code-intelligence init
```

This creates a `.mcp-code-intelligence/` directory marking your project root.

### 2. Install MCP Integration

```bash
# Auto-detect and install (recommended)
mcp-code-intelligence install mcp

# Install to all detected platforms
mcp-code-intelligence install mcp --all

# Install to specific platform
mcp-code-intelligence install mcp --platform cursor
```

### 3. Check Status

```bash
# View current MCP configuration
mcp-code-intelligence install mcp-status
```

## How Auto-Detection Works

### Detection Priority

The system detects your project root using this priority order:

1. **`.mcp-code-intelligence/` directory** - Highest priority
   - Looks for this directory in current path
   - Preferred for monorepos with multiple projects

2. **Git repository root** - Secondary priority
   - Walks up directory tree to find `.git/`
   - Only used if `.mcp-code-intelligence/` exists at git root

3. **Current directory** - Fallback
   - Used when no other markers found
   - Ensures command always works

### Example: Monorepo Setup

```
monorepo/
├── .git/
├── project-a/
│   └── .mcp-code-intelligence/     # Project A root
└── project-b/
    └── .mcp-code-intelligence/     # Project B root
```

When you run `install mcp` from `project-a/`, it detects `project-a/` as the root (not `monorepo/`).

### Example: Standard Project

```
my-app/
├── .git/
├── .mcp-code-intelligence/
├── src/
│   └── components/
│       └── ui/
```

When you run `install mcp` from `my-app/src/components/ui/`, it detects `my-app/` as the root.

## Environment Variables

The MCP server respects these environment variables (in priority order):

1. **`MCP_PROJECT_ROOT`** - New standard (recommended)
2. **`PROJECT_ROOT`** - Legacy support
3. **Current working directory** - Fallback

Example MCP configuration:

```json
{
  "mcpServers": {
    "mcp-code-intelligence": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/project", "mcp-code-intelligence", "mcp"],
      "env": {
        "MCP_PROJECT_ROOT": "/path/to/project",
        "MCP_ENABLE_FILE_WATCHING": "true"
      }
    }
  }
}
```

## Usage Examples

### Basic Installation

```bash
# From project root
cd /Users/masa/Projects/my-app
mcp-code-intelligence install mcp

# Output:
# 🔍 Auto-detected project root: /Users/masa/Projects/my-app
#
# ╭─────────────────────────────────────╮
# │ Installing MCP Integration          │
# │ 📁 Project: /Users/masa/Projects... │
# ╰─────────────────────────────────────╯
```

### Installation from Subdirectory

```bash
# Works from any subdirectory
cd /Users/masa/Projects/my-app/src/components
mcp-code-intelligence install mcp

# Still detects: /Users/masa/Projects/my-app
```

### Installation Without Auto-Detection

```bash
# Use current directory as project root (no auto-detection)
mcp-code-intelligence install mcp --no-auto
```

### Dry Run (Preview Changes)

```bash
# See what would be installed without making changes
mcp-code-intelligence install mcp --dry-run
```

### Install to All Platforms

```bash
# Install to all detected platforms
mcp-code-intelligence install mcp --all
```

### Check Status

```bash
# View MCP integration status
mcp-code-intelligence install mcp-status

# Output shows:
# - Detected project root
# - Configured platforms
# - Project paths for each platform
# - Status (configured/not configured)
```

## Supported Platforms

| Platform       | Config Location                      | Status |
|---------------|--------------------------------------|--------|
| Claude Code   | `.mcp.json` (project-scoped)        | ✅      |
| Claude Desktop| `~/Library/Application Support/...` | ✅      |
| Cursor        | Platform-specific config            | ✅      |
| Auggie        | `~/.augment/settings.json`          | ✅      |
| Codex         | `~/.codex/config.toml`              | ✅      |
| Windsurf      | Platform-specific config            | ✅      |
| Gemini CLI    | `~/.gemini/mcp.json`                | ✅      |

## Troubleshooting

### Problem: Wrong Project Detected

**Solution**: Ensure your project has `.mcp-code-intelligence/` directory

```bash
# Re-initialize if needed
mcp-code-intelligence init --force
```

### Problem: MCP Server Points to Different Project

**Symptom**: `mcp-code-intelligence install mcp-status` shows different path

**Solution**: Reinstall MCP integration

```bash
# Uninstall old configuration
mcp-code-intelligence uninstall mcp --platform <platform>

# Reinstall with correct project
cd /path/to/correct/project
mcp-code-intelligence install mcp
```

### Problem: No Platforms Detected

**Symptom**: `mcp-code-intelligence install mcp` shows "No MCP platforms detected"

**Solution**: Install a supported platform first

```bash
# Check which platforms are available
mcp-code-intelligence install list-platforms

# Install Claude Code, Cursor, or another supported platform
# Then run install again
```

### Problem: Auto-Detection Not Working

**Debug Steps**:

1. Check for `.mcp-code-intelligence/` directory:
   ```bash
   ls -la .mcp-code-intelligence
   ```

2. Check git repository:
   ```bash
   git rev-parse --show-toplevel
   ```

3. Use `--no-auto` flag to bypass auto-detection:
   ```bash
   mcp-code-intelligence install mcp --no-auto
   ```

## Migration from Old Configuration

If you were using the old `mcp install` or manual configuration:

### Step 1: Remove Old Configuration

```bash
# For Claude Code
rm .mcp.json

# For other platforms, use uninstall command
mcp-code-intelligence uninstall mcp --platform <platform>
```

### Step 2: Install with New Auto-Detection

```bash
mcp-code-intelligence install mcp
```

### Step 3: Verify Configuration

```bash
mcp-code-intelligence install mcp-status
```

## Best Practices

### ✅ DO

- Run `mcp-code-intelligence init` in each project before MCP installation
- Use `install mcp-status` to verify configuration
- Use `--dry-run` to preview changes before installation
- Keep `.mcp-code-intelligence/` in version control

### ❌ DON'T

- Don't manually edit MCP configuration files (use commands instead)
- Don't rely on current directory being project root (auto-detection handles this)
- Don't use `--no-auto` unless you have specific reasons

## Advanced: Multiple Projects on Same Machine

### Scenario: Working on Multiple Projects

```bash
# Project 1
cd ~/Projects/project-a
mcp-code-intelligence init
mcp-code-intelligence install mcp --platform cursor

# Project 2
cd ~/Projects/project-b
mcp-code-intelligence init
mcp-code-intelligence install mcp --platform cursor

# Both projects configured separately!
```

### Scenario: Switching Between Projects

The MCP server automatically uses the correct project based on:
1. Environment variables set during installation
2. Current working directory when server starts

No manual configuration needed!

## Testing Your Installation

### Quick Test

```bash
# 1. Check status
mcp-code-intelligence install mcp-status

# 2. Verify from subdirectory
cd src/
mcp-code-intelligence install mcp-status

# Should show same project root
```

### Full Integration Test

```bash
# Run automated test suite
./tests/manual/test_mcp_auto_install.sh
```

## Summary

The new auto-installation feature makes MCP setup **simple and foolproof**:

1. ✅ No more manual path configuration
2. ✅ Works from any directory in your project
3. ✅ Supports complex setups (monorepos, multiple projects)
4. ✅ Clear status reporting
5. ✅ Easy troubleshooting

**Recommendation**: Always use `install mcp` with auto-detection (default behavior) for the best experience.

## See Also

- [MCP Integration Guide](./MCP_INTEGRATION.md)
- [Installation Guide](./INSTALLATION.md)
- [Troubleshooting](./TROUBLESHOOTING.md)

---

**Last Updated**: December 6, 2025
**Version**: 0.14.9+

