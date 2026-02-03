"""Modular visualization package for code graphs.

This package provides D3.js-based interactive visualization of code relationships,
organized into modular components for maintainability.

Structure:
    - graph_builder.py: Graph data construction logic
    - server.py: HTTP server for serving visualization
    - templates/: HTML, CSS, and JavaScript generation
    - exporters/: Export functionality (JSON, HTML)
    - cli.py: Typer CLI commands (imported for backwards compatibility)
"""

from mcp_code_intelligence.cli.commands.visualize.cli import app
from mcp_code_intelligence.cli.commands.visualize.exporters import export_to_html, export_to_json
from mcp_code_intelligence.cli.commands.visualize.graph_builder import (
    build_graph_data,
    get_subproject_color,
    parse_project_dependencies,
)
from mcp_code_intelligence.cli.commands.visualize.server import find_free_port, start_visualization_server
from mcp_code_intelligence.cli.commands.visualize.templates import generate_html_template

__all__ = [
    # CLI
    "app",
    # Graph building
    "build_graph_data",
    "get_subproject_color",
    "parse_project_dependencies",
    # Server
    "find_free_port",
    "start_visualization_server",
    # Templates
    "generate_html_template",
    # Exporters
    "export_to_html",
    "export_to_json",
]
