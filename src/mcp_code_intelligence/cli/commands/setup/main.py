import asyncio
import sys
import json
import os
import shutil
import time
from pathlib import Path
from loguru import logger
import typer
from rich.console import Console
from mcp_code_intelligence.core.languages import SUPPORTED_LANGUAGES as available_lsps

from mcp_code_intelligence.cli.commands.setup.discovery import DiscoveryManager
from mcp_code_intelligence.cli.commands.setup.intelligence import IntelligenceManager
from mcp_code_intelligence.cli.commands.setup.mcp_config import MCPConfigManager
from mcp_code_intelligence.cli.commands.setup.wizard import SetupWizard
from mcp_code_intelligence.core.exceptions import ProjectInitializationError
from mcp_code_intelligence.cli.output import print_error, print_info, print_success, print_warning
from collections import Counter
from mcp_code_intelligence.core.project import ProjectManager
from mcp_code_intelligence.config.defaults import get_language_from_extension

async def run_setup_workflow(ctx: typer.Context, force: bool, verbose: bool):
    # Pre-flight dependency check
    import importlib.util
    missing = []
    for pkg in ["einops", "torch", "sentence_transformers", "chromadb"]:
        if importlib.util.find_spec(pkg) is None:
            missing.append(pkg)
    if missing:
        print_warning(f"\n⚠️  Missing Python packages: {', '.join(missing)}\nRun this command before installation:\n    pip install {' '.join(missing)}\n")
        if not force:
            if not typer.confirm("Do you want to continue with missing packages? (Setup might fail)", default=False):
                print_info("Setup cancelled.")
                return

    """Orchestrates the modular setup process."""
    console = Console()
    project_root = ctx.obj.get("project_root") or Path.cwd()

    # Initialize Managers
    discovery = DiscoveryManager(project_root)
    intel = IntelligenceManager(project_root, console)
    mcp_man = MCPConfigManager(project_root, console)
    wizard = SetupWizard(console)

    wizard.show_header()

    # 1. Discovery
    print_info("\n🔍 Detecting project languages...")
    languages = discovery.detect_languages()
    extensions = discovery.scan_file_extensions()
    platforms = discovery.detect_ai_platforms()

    # Auto-detect the most common language in the project
    pm = ProjectManager(project_root)
    file_langs = []
    for file_path in pm._iter_source_files():
        lang = get_language_from_extension(file_path.suffix)
        if lang and lang != "text":
            file_langs.append(lang.lower())
    if not file_langs:
        main_lang = "python"
    else:
        main_lang = Counter(file_langs).most_common(1)[0][0]
    print_info(f"\nMain project language auto-detected: {main_lang}")
    selected_langs = [main_lang.capitalize() if main_lang == "python" else main_lang.title()]

    # Node.js and npm check (for JS/TS)
    import shutil as _shutil
    if any(l in ["JavaScript", "TypeScript"] for l in languages):
        if not _shutil.which("npm"):
            print_warning("\n⚠️  Node.js and npm not found for TypeScript/JavaScript support!\nPlease install Node.js from https://nodejs.org or continue with --force.\n")
            if not force:
                if not typer.confirm("Continue without Node.js/npm? (JS/TS LSP cannot be installed)", default=False):
                    print_info("Setup cancelled.")
                    return
    # Java check (for JDTLS)
    if "Java" in languages:
        if not _shutil.which("java"):
            print_warning("\n⚠️  Java JDK not found for Java support!\nPlease install JDK from https://adoptium.net/ or continue with --force.\n")
            if not force:
                if not typer.confirm("Continue without Java? (Java LSP cannot be installed)", default=False):
                    print_info("Setup cancelled.")
                    return

    # Filter platforms
    from py_mcp_installer import Platform
    EXCLUDED = {Platform.CLAUDE_DESKTOP}
    configurable = [p for p in platforms if p.platform not in EXCLUDED]

    # 2. Planning: Install only the main language
    available_langs = {}
    langs_dir = Path(__file__).parent.parent.parent.parent / "languages"
    if langs_dir.exists():
        for f in langs_dir.glob("*.json"):
            with open(f) as ld:
                data = json.load(ld)
                available_langs[data["name"].lower()] = data
    # Add only the main language data
    detected_lang_names = [main_lang.capitalize() if main_lang == "python" else main_lang.title()]
    if not selected_langs:
        print_warning("No languages selected, only Python will be installed.")
        selected_langs = ["Python"]

    # planned_lsp: Match selected languages against available language configs
    planned_lsp = []
    selected_langs_data = []

    # Normalize selected languages for matching
    normalized_selected = [s.lower() for s in selected_langs]

    for name_key, data in available_langs.items():
        config_name = data["name"].lower()
        # Check if config_name is in selected_langs or if any selected_lang is in config_name
        # (e.g., "javascript" should match "javascript/typescript")
        if any(s in config_name or config_name in s for s in normalized_selected):
            selected_langs_data.append(data)
            planned_lsp.append(data['name'])
            logger.debug(f"Matched language config: {data['name']} for selected: {selected_langs}")

    # Dynamically find the 'src' directory for PYTHONPATH
    src_dir = Path(__file__).parent.parent.parent.parent.parent.resolve()
    
    python_cmd = sys.executable
    # Prefer python -u -m for better stdio reliability (unbuffered)
    server_cmd = sys.executable
    server_args = ["-u", "-m", "mcp_code_intelligence.mcp_impl"]

    mcp_servers = {
        "mcp-code-intelligence": {
            "command": server_cmd,
            "args": server_args,
            "env": {
                "MCP_PROJECT_ROOT": str(project_root.resolve()),
                "MCP_ENABLE_FILE_WATCHING": "true",
                "PYTHONPATH": str(src_dir),
                "PYTHONUNBUFFERED": "1",
            }
        },
        "filesystem": {
            "command": python_cmd,
            "args": ["-u", "-m", "mcp_code_intelligence.servers.filesystem_server", str(project_root.resolve())],
            "env": {
                "PYTHONPATH": str(src_dir),
                "PYTHONUNBUFFERED": "1"
            }
        },
        "git": {
            "command": python_cmd,
            "args": ["-u", "-m", "mcp_code_intelligence.servers.git_server", str(project_root.resolve())],
            "env": {
                "PYTHONPATH": str(src_dir),
                "PYTHONUNBUFFERED": "1"
            }
        },
        "memory": {
            "command": python_cmd,
            "args": ["-u", "-m", "mcp_code_intelligence.servers.memory_server"],
            "env": {
                "PYTHONPATH": str(src_dir),
                "PYTHONUNBUFFERED": "1"
            }
        }
    }

    # Add dynamic LSPs (Prevent redundant starts)
    lsp_registry = intel.get_lsp_configs()
    for lp in planned_lsp:
        low = lp.lower()
        if low in lsp_registry:
            cfg = lsp_registry[low]
            lsp_id = cfg["id"]
            if lsp_id in mcp_servers:
                continue  # Skip if already added
            cmd = cfg.get("win_cmd", cfg["cmd"]) if os.name == 'nt' else cfg["cmd"]
            if shutil.which(cmd) or cfg["cmd"] == python_cmd:
                mcp_servers[lsp_id] = {
                    "command": cmd, 
                    "args": cfg["args"],
                    "env": {
                        "PYTHONPATH": str(src_dir),
                        "PYTHONUNBUFFERED": "1"
                    }
                }

    # 3. Present Summary
    planned_actions = [
        "Initialize vector index using [bold]Jina v3[/bold]",
        f"Enable Intelligence (LSP) for: {', '.join(planned_lsp) if planned_lsp else 'Generic mode'}",
        f"Configure {len(mcp_servers)} Python-based MCP servers",
        "Inject configuration into AI tools"
    ]

    wizard.show_discovery_summary(
        project_root.name,
        planned_lsp,
        [p.platform.value for p in configurable],
        planned_actions
    )

    if not wizard.confirm_execution():
        print_info("Setup cancelled.")
        return

    # 4. Execution
    print_info("\n⚙️  Processing dependencies...")
    for ld in selected_langs_data:
        intel.process_language_dependencies(ld)

    print_info("🚀 Initializing system...")
    embedding_model = "jinaai/jina-embeddings-v3"
    # Only use extensions from selected languages, not all discovered extensions
    selected_extensions = list(set([e for ld in selected_langs_data for e in ld.get("extensions", [])]))
    discovery.project_manager.initialize(
        file_extensions=selected_extensions,
        embedding_model=embedding_model,
        similarity_threshold=0.5,
        force=force
    )

    intel.download_model_weights(embedding_model)

    # Indexing
    print_info("\n🔍 Indexing codebase...")
    print_info("[dim]💡 This is a one-time process. Changes will be updated incrementally later.[/dim]")
    from mcp_code_intelligence.cli.commands.index import run_indexing
    try:
        await run_indexing(project_root=project_root, force_reindex=force, show_progress=True)
    except Exception as e:
        print_error(f"Indexing failed: {e}")

    # Config Injection
    print_info("\n🔗 Linking AI tools...")
    mcp_man.write_local_config(mcp_servers, available_lsps)
    mcp_man.inject_global_config(configurable, mcp_servers)

    # Universal Rule Injection (All AI assistants)
    mcp_man.inject_universal_rules(mcp_servers)

    # Google IDX / VS Code / Cursor specific injection
    is_idx = discovery.is_idx()
    is_vscode = discovery.is_vscode()
    
    if is_idx:
        print_info("   Detected Google IDX environment")
        mcp_man.inject_vscode_settings(mcp_servers)
        mcp_man.inject_cursor_rules(mcp_servers)
        mcp_man.inject_copilot_instructions(mcp_servers)
    elif is_vscode:
        print_info("   Detected VS Code / GitHub Copilot environment")
        mcp_man.inject_vscode_settings(mcp_servers)
        mcp_man.inject_cursor_rules(mcp_servers) # Still inject cursorrules as some users use Cursor with .vscode
        mcp_man.inject_copilot_instructions(mcp_servers)
    else:
        # Generic project, still inject rules for potential AI usage
        mcp_man.inject_cursor_rules(mcp_servers)
        mcp_man.inject_copilot_instructions(mcp_servers)

    # Start LSP proxies for any available external LSPs so MCP can route requests
    try:
        from mcp_code_intelligence.core.lsp_proxy import start_proxies
        # start_proxies is async; await it directly since we're in an async function
        await start_proxies(project_root)
    except Exception as e:
        logger.debug(f"Could not start LSP proxies: {e}")
    mcp_man.setup_git_hooks()

    # Finish
    wizard.show_completion([
        "mcp-code-intelligence search 'query'",
        "mcp-code-intelligence status"
    ])

    # Auto-start MCP servers
    print_info("\n🚦 Starting MCP servers...")
    import subprocess
    started_servers = []
    for server_name, server_cfg in mcp_servers.items():
        try:
            cmd = [server_cfg["command"]] + server_cfg["args"]
            env = os.environ.copy()
            env.update(server_cfg.get("env", {}))
            # Start server in background
            subprocess.Popen(cmd, env=env, cwd=str(project_root))
            started_servers.append(server_name)
            print_success(f"Started: {server_name}")
        except Exception as e:
            print_error(f"{server_name} failed to start: {e}")
    print_info(f"\nTotal servers started: {len(started_servers)} → {', '.join(started_servers)}")

async def main_setup_task(ctx: typer.Context, force: bool, verbose: bool):
    try:
        await run_setup_workflow(ctx, force, verbose)
    except Exception as e:
        logger.error(f"Setup error: {e}")
        print_error(f"Setup failed: {e}")
        raise typer.Exit(1)
