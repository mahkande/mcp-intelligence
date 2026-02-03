"""Templates for visualization HTML generation.

This package contains modular template components for generating
the D3.js visualization HTML page.
"""

from mcp_code_intelligence.cli.commands.visualize.templates.base import generate_html_template, inject_data
from mcp_code_intelligence.cli.commands.visualize.templates.scripts import get_all_scripts
from mcp_code_intelligence.cli.commands.visualize.templates.styles import get_all_styles

__all__ = [
    "generate_html_template",
    "inject_data",
    "get_all_scripts",
    "get_all_styles",
]
