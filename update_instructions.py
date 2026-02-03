
from pathlib import Path
from mcp_code_intelligence.mcp_impl.fast_server import mcp, update_copilot_instructions, get_project_root

try:
    project_root = get_project_root()
    print(f"Updating instructions for project root: {project_root}")
    update_copilot_instructions(mcp, project_root)
    print("Successfully updated copilot-instructions.md")
except Exception as e:
    print(f"Error updating instructions: {e}")
