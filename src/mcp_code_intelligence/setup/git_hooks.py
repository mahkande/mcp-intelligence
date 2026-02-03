"""Git hook management for MCP Code Intelligence."""

import os
import stat
from pathlib import Path
from loguru import logger

HOOK_CONTENT = """#!/bin/sh
# MCP Code Intelligence Pre-commit Hook
# Auto-indexes changed files in the background

# Get staged files
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep -E '\\.(py|js|ts|jsx|tsx|java|rs|php|rb)$' | tr '\\n' ',')

if [ -n "$STAGED_FILES" ]; then
    # Remove trailing comma
    STAGED_FILES=${STAGED_FILES%,}
    
    # Run indexing in background, suppressing output
    # Non-blocking: will exit 0 even if indexing fails or is locked
    (mcp-code-intelligence index --files "$STAGED_FILES" --quiet || true) &
fi

exit 0
"""

def install_hooks(project_root: Path) -> bool:
    """Install or update git pre-commit hook.
    
    If an existing hook exists, it appends the MCP hook logic.
    """
    git_dir = project_root / ".git"
    if not git_dir.exists():
        try:
            from mcp_code_intelligence.cli.output import print_info, is_interactive
            if is_interactive:
                print_info("Git not detected, skipping automatic hook setup. You can still use manual indexing.")
            else:
                print("ℹ Git not detected, skipping automatic hook setup. You can still use manual indexing.")
        except ImportError:
            # Fallback to standard print if cli.output is not available for some reason
            print("ℹ Git not detected, skipping automatic hook setup. You can still use manual indexing.")
            
        logger.debug(f"Not a git repository: {project_root}")
        return False
        
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    
    pre_commit_path = hooks_dir / "pre-commit"
    
    try:
        if pre_commit_path.exists():
            with open(pre_commit_path, "r", encoding="utf-8") as f:
                content = f.read()
                
            if "MCP Code Intelligence Pre-commit Hook" in content:
                logger.debug("Git hook already installed and up to date.")
                return True
                
            # Append to existing hook
            logger.info(f"Appending MCP hook logic to existing {pre_commit_path}")
            header = "\n\n# --- MCP Code Intelligence Start ---\n"
            footer = "\n# --- MCP Code Intelligence End ---\n"
            # Strip shebang from HOOK_CONTENT for appending
            append_content = HOOK_CONTENT.split("\n", 1)[1] if HOOK_CONTENT.startswith("#!") else HOOK_CONTENT
            
            with open(pre_commit_path, "a", encoding="utf-8") as f:
                f.write(header + append_content + footer)
        else:
            # Create new hook
            logger.info(f"Creating new git hook at {pre_commit_path}")
            with open(pre_commit_path, "w", encoding="utf-8") as f:
                f.write(HOOK_CONTENT)
                
        # Make executable
        st = os.stat(pre_commit_path)
        os.chmod(pre_commit_path, st.st_mode | stat.S_IEXEC)
        return True
        
    except Exception as e:
        logger.error(f"Failed to install git hook: {e}")
        return False

if __name__ == "__main__":
    # For testing
    install_hooks(Path.cwd())
