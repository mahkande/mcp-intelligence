import os
import json
from pathlib import Path
from unittest.mock import Mock, patch
import pytest
from mcp_code_intelligence.cli.commands.setup.discovery import DiscoveryManager
from mcp_code_intelligence.cli.commands.setup.mcp_config import MCPConfigManager
from rich.console import Console

def test_is_idx_env_var(tmp_path):
    dm = DiscoveryManager(tmp_path)
    with patch.dict(os.environ, {"IDX_WORKSPACE_ID": "test-id"}):
        assert dm.is_idx() is True

def test_is_idx_directory(tmp_path):
    dm = DiscoveryManager(tmp_path)
    (tmp_path / ".idx").mkdir()
    assert dm.is_idx() is True

def test_is_not_idx(tmp_path):
    dm = DiscoveryManager(tmp_path)
    with patch.dict(os.environ, {}, clear=True):
        assert dm.is_idx() is False

def test_inject_vscode_settings(tmp_path):
    console = Console()
    manager = MCPConfigManager(tmp_path, console)
    mcp_servers = {"test-server": {"command": "test"}}
    
    manager.inject_vscode_settings(mcp_servers)
    
    settings_path = tmp_path / ".vscode" / "settings.json"
    assert settings_path.exists()
    
    with open(settings_path, "r") as f:
        settings = json.load(f)
    
    assert "mcp.servers" in settings
    assert settings["mcp.servers"]["test-server"]["command"] == "test"

def test_inject_copilot_instructions(tmp_path):
    console = Console()
    manager = MCPConfigManager(tmp_path, console)
    mcp_servers = {"test-server": {"description": "test description"}}
    
    manager.inject_copilot_instructions(mcp_servers)
    
    instructions_path = tmp_path / ".github" / "copilot-instructions.md"
    assert instructions_path.exists()
    
    content = instructions_path.read_text()
    assert "GitHub Copilot Instructions" in content
    assert "test-server" in content

def test_inject_universal_rules(tmp_path):
    console = Console()
    manager = MCPConfigManager(tmp_path, console)
    mcp_servers = {"test-server": {}}
    
    manager.inject_universal_rules(mcp_servers)
    
    rules_path = tmp_path / ".mcp-rules.md"
    assert rules_path.exists()
    
    content = rules_path.read_text()
    assert "Universal Rules" in content
    assert "test-server" in content

def test_inject_cursor_rules(tmp_path):
    console = Console()
    manager = MCPConfigManager(tmp_path, console)
    mcp_servers = {"test-server": {}}
    
    manager.inject_cursor_rules(mcp_servers)
    
    rules_path = tmp_path / ".cursorrules"
    assert rules_path.exists()
    
    content = rules_path.read_text()
    assert "# MCP Code Intelligence Rules" in content
    assert "search_code" in content
    assert "analyze_impact" in content
