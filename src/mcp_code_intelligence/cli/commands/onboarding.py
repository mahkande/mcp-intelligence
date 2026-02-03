

# Standard library imports
import sys
import shutil
from pathlib import Path
from typing import List, Optional
import time
import subprocess
import os
import asyncio
import json

# Third-party imports
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.text import Text

# Internal imports
from mcp_code_intelligence.core.project import ProjectManager
from mcp_code_intelligence.config.defaults import get_language_from_extension

# Import from py-mcp-installer library
try:
    from py_mcp_installer import (
        MCPInstaller,
        MCPServerConfig,
        Platform,
        PlatformDetector,
        PlatformInfo,
    )
except ImportError:
    sys.exit("Error: py_mcp_installer not found. Run this within the installed environment.")

console = Console()
app = typer.Typer(help="Onboarding and setup for standard MCP servers")

def detect_platforms() -> List[PlatformInfo]:
    """Detect all available platforms on the system using py_mcp_installer."""
    detector = PlatformDetector()
    detected_platforms = []

    # Map of platform enums to their detection methods
    platform_detectors = {
        Platform.CLAUDE_CODE: detector.detect_claude_code,
        Platform.CLAUDE_DESKTOP: detector.detect_claude_desktop,
        Platform.CURSOR: detector.detect_cursor,
        Platform.AUGGIE: detector.detect_auggie,
        Platform.CODEX: detector.detect_codex,
        Platform.WINDSURF: detector.detect_windsurf,
        Platform.GEMINI_CLI: detector.detect_gemini_cli,
    }

    for platform_enum, detector_func in platform_detectors.items():
        try:
            confidence, config_path = detector_func()
            if confidence > 0.0 and config_path:
                 detected_platforms.append(
                    PlatformInfo(
                        platform=platform_enum,
                        confidence=confidence,
                        config_path=config_path,
                        cli_available=False
                    )
                )
        except Exception:
            continue



    return detected_platforms

def install_server(platform_info: PlatformInfo, config: MCPServerConfig) -> bool:
    """Install a generic server configuration to a platform."""
    installer = MCPInstaller(platform=platform_info.platform)
    try:
        console.print(f"[dim]  Installing {config.name} to {platform_info.platform.value}...[/dim]")
        result = installer.install_server(
            name=config.name,
            command=config.command,
            args=config.args,
            env=config.env,
            description=config.description
        )
        if result.success:
            console.print(f"  ✅ [green]{config.name}[/green] installed to {platform_info.platform.value}")
            return True
        else:
            console.print(f"  ❌ Failed to install {config.name}: {result.message}")
            return False
    except Exception as e:
        # Handle "already exists" gracefully if possible, or just report error
        if "already exists" in str(e).lower():
             console.print(f"  ✅ [green]{config.name}[/green] already exists in {platform_info.platform.value}")
             return True
        console.print(f"  ❌ Error installing {config.name}: {e}")
        return False

@app.command("setup")
def setup(
    allowed_path: Path = typer.Option(
        Path.cwd(),
        "--path",
        "-p",
        help="Absolute path for the project index"
    )
):
    """
    Interactive Setup Wizard: Guided configuration for your AI intelligence tools.
    """
    import os
    import json
    console.print(Panel.fit("🚀 [bold]MCP Intelligence Setup Wizard[/bold]\n[dim]I will help you configure your AI assistant correctly.[/dim]", border_style="cyan"))

    # 1. Ask for languages
    languages_str = typer.prompt("Which programming languages do you use? (comma separated)", default="python")
    languages = [l.strip().lower() for l in languages_str.split(",")]

    # 2. Optional features
    install_git = typer.confirm("Enable Git integration (requires git CLI)?", default=True)
    install_memory = typer.confirm("Enable Memory/Knowledge Graph (stores project info)?", default=True)
    global_install = typer.confirm("\nShould I automatically inject these into Claude, Cursor, and Windsurf global settings?", default=False)

    console.print("\n[bold yellow]⚙️ Initializing Setup...[/bold yellow]")

    # Dynamically find the 'src' directory for PYTHONPATH
    src_dir = Path(__file__).parent.parent.parent.parent.parent.resolve()
    
    python_cmd = sys.executable
    import subprocess

    servers_to_install = []

    # Main Intelligence Server (Always)
    servers_to_install.append(MCPServerConfig(
        name="mcp-code-intelligence",
        command=python_cmd,
        args=["-u", "-m", "mcp_code_intelligence.mcp_impl.server", "mcp"],
        env={
            "MCP_PROJECT_ROOT": str(allowed_path.resolve()), 
            "MCP_ENABLE_FILE_WATCHING": "true",
            "PYTHONPATH": str(src_dir),
            "PYTHONUNBUFFERED": "1"
        },
        description="Semantic Search (Jina v3)"
    ))

    # Python LSP (Prevent redundant starts)
    if "python" in languages:
        lsp_already_added = any(s.name == "python-lsp" for s in servers_to_install)
        if not lsp_already_added:
            try:
                import pylsp
            except ImportError:
                console.print("[dim]📦 Installing Python LSP...[/dim]")
                subprocess.run([python_cmd, "-m", "pip", "install", "python-lsp-server"], check=True, capture_output=True)
            servers_to_install.append(MCPServerConfig(
                name="python-lsp",
                command=python_cmd,
                args=["-u", "-m", "mcp_code_intelligence.servers.python_lsp_server", str(allowed_path.resolve())],
                env={
                    "PYTHONPATH": str(src_dir),
                    "PYTHONUNBUFFERED": "1"
                },
                description="LSP (Type Intel)"
            ))

    # Generic Filesystem (Always recommended)
    servers_to_install.append(MCPServerConfig(
        name="filesystem",
        command=python_cmd,
        args=["-u", "-m", "mcp_code_intelligence.servers.filesystem_server", str(allowed_path.resolve())],
        env={
            "PYTHONPATH": str(src_dir),
            "PYTHONUNBUFFERED": "1"
        },
        description="Filesystem Access"
    ))

    # Optional Git
    if install_git:
        try:
            import git
        except ImportError:
            console.print("[dim]📦 Installing GitPython...[/dim]")
            subprocess.run([python_cmd, "-m", "pip", "install", "gitpython"], check=True, capture_output=True)

        servers_to_install.append(MCPServerConfig(
            name="git",
            command=python_cmd,
            args=["-u", "-m", "mcp_code_intelligence.servers.git_server", str(allowed_path.resolve())],
            env={
                "PYTHONPATH": str(src_dir),
                "PYTHONUNBUFFERED": "1"
            },
            description="Git Operations"
        ))

    # Optional Memory
    if install_memory:
        servers_to_install.append(MCPServerConfig(
            name="memory",
            command=python_cmd,
            args=["-u", "-m", "mcp_code_intelligence.servers.memory_server"],
            env={
                "PYTHONPATH": str(src_dir),
                "PYTHONUNBUFFERED": "1"
            },
            description="Knowledge Memory"
        ))

    # --- ACTION: Writing local config ---
    console.print(f"\n[bold blue]Writing Workspace Configuration...[/bold blue]")
    local_mcp_path = allowed_path / ".mcp" / "mcp.json"
    local_mcp_path.parent.mkdir(parents=True, exist_ok=True)

    config_data = {"mcpServers": {}}
    for s in servers_to_install:
        config_data["mcpServers"][s.name] = {"command": s.command, "args": s.args, "env": s.env}

    with open(local_mcp_path, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=2)
    console.print(f"  ✅ [green]Updated .mcp/mcp.json[/green]")

    # --- ACTION: Global ---
    if global_install:
        # (Platform detection and global injection logic remains the same)
        console.print(f"\n[bold blue]2. Scanning for AI Clients (Claude, Cursor, Windsurf)...[/bold blue]")
        platforms = detect_platforms()
        if not platforms:
            console.print("  [yellow]No other global AI clients detected.[/yellow]")
        else:
            for p in platforms:
                console.print(f"  Configuring [cyan]{p.platform.value}[/cyan]...")
                for s in servers:
                     install_server(p, s)

        # Global AI client config handling (legacy Roo references removed)
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            roo_paths = [
                Path(appdata) / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "mcp_settings.json",
                Path(appdata) / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "mcp.json"
            ]
            for rp in roo_paths:
                if rp.exists():
                    try:
                        with open(rp, 'r') as f: data = json.load(f)
                        data.setdefault("mcpServers", {}).update({s.name: {"command": s.command, "args": s.args, "env": s.env} for s in servers})
                        with open(rp, 'w') as f: json.dump(data, f, indent=2)
                        console.print(f"  ✅ [green]Updated global MCP config[/green]")
                        break
                    except Exception: continue

    console.print(Panel("[bold green]✨ Universal Setup Complete![/bold green]\n\n[white]Restart your AI tools to apply changes.[/white]\n[dim]To watch background activity, run:[/dim]\n[cyan]mcp-code-intelligence logs[/cyan]"))

@app.command("logs")
def view_logs(
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        "-p",
        help="Project root directory to read logs from (defaults to nearest project)",
        exists=False,
        file_okay=False,
        dir_okay=True,
    )
):
    """🚀 Launch the Live MCP Control Center (HUD).

    The HUD will try to locate an active project's `activity.log` by using the
    provided `--project-root` or by searching upward from the current directory
    for a `.mcp-code-intelligence/logs/activity.log` file that contains data.
    If none is found, it falls back to the current working directory.
    """
    # Resolve project_root: prefer explicit, otherwise search upwards for a non-empty log
    def _find_active_log(start: Path) -> Path | None:
        # Walk up parent chain looking for .mcp-code-intelligence/logs/activity.log
        cur = start.resolve()
        for path in [cur] + list(cur.parents):
            candidate = path / ".mcp-code-intelligence" / "logs" / "activity.log"
            if candidate.exists():
                return candidate

        # If not found in parents, try siblings of the start directory (common when
        # running from a sibling project folder, e.g., running HUD from a tooling
        # repo while the real project is in a sibling folder like ../orm-drf)
        try:
            parent = cur.parent
            for sibling in parent.iterdir():
                if not sibling.is_dir() or sibling == cur:
                    continue
                candidate = sibling / ".mcp-code-intelligence" / "logs" / "activity.log"
                if candidate.exists():
                    return candidate
        except Exception:
            pass

        return None

    if project_root:
        log_file = Path(project_root) / ".mcp-code-intelligence" / "logs" / "activity.log"
    else:
        found = _find_active_log(Path.cwd())
        if found:
            log_file = found
        else:
            # Fallback to current cwd path (may be empty)
            log_file = Path.cwd() / ".mcp-code-intelligence" / "logs" / "activity.log"

    if not log_file.exists():
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.touch()

    layout = Layout()
    # Only keep body in Live; header will be printed once outside Live
    layout.split(
        Layout(name="body")
    )

    servers = [
        {"name": "mcp-code-intelligence", "pattern": ["mcp_code_intelligence.mcp_impl", "mcp-code-intelligence"]},
        {"name": "python-lsp", "pattern": "python_lsp_server"},
        {"name": "filesystem", "pattern": "filesystem_server"},
        {"name": "git", "pattern": "git_server"},
        {"name": "memory", "pattern": "memory_server"},
    ]

    def check_server_status():
        # Render a compact status table without a large title so the
        # header doesn't redraw big box-drawing characters repeatedly.
        table = Table(expand=True, box=None)
        table.add_column("Server Name", style="bold white")
        table.add_column("Status", justify="center")
        table.add_column("PID", justify="right", style="dim")
        table.add_column("Active Context", style="dim")

        # Attempt to detect running processes with best-effort method:
        # 1. Try psutil for reliable cmdline and pid access
        # 2. Fallback to tasklist/ps output search
        proc_cmdlines = []
        try:
            import psutil

            for p in psutil.process_iter(attrs=["pid", "name", "cmdline"]):
                try:
                    cmd = " ".join(p.info.get("cmdline") or [])
                except Exception:
                    cmd = ""
                proc_cmdlines.append((p.info.get("pid"), cmd))
        except Exception:
            try:
                if os.name == "nt":
                    raw = subprocess.check_output(["tasklist", "/v", "/fo", "csv"]).decode("cp1254", errors="ignore")
                    proc_cmdlines = []
                    for line in raw.splitlines():
                        proc_cmdlines.append((None, line))
                else:
                    raw = subprocess.check_output(["ps", "aux"]).decode("utf-8", errors="ignore")
                    proc_cmdlines = []
                    for line in raw.splitlines():
                        proc_cmdlines.append((None, line))
            except Exception:
                proc_cmdlines = []

        current_pid = os.getpid()
        for s in servers:
            found_pid = None
            is_running = False
            patterns = s["pattern"] if isinstance(s["pattern"], list) else [s["pattern"]]
            
            for pid, cmd in proc_cmdlines:
                if pid == current_pid:
                    continue
                
                cmd_lower = cmd.lower()
                # Special case for mcp-code-intelligence: must contain 'mcp' but NOT 'logs' or 'status'
                if s["name"] == "mcp-code-intelligence":
                    if ("mcp-code-intelligence" in cmd_lower or "mcp_code_intelligence.mcp_impl" in cmd_lower) and " mcp" in cmd_lower:
                        # Exclude if it's likely a logs/onboarding command
                        if " logs" not in cmd_lower and " status" not in cmd_lower and " setup" not in cmd_lower:
                            is_running = True
                else:
                    if cmd_lower and any(p.lower() in cmd_lower for p in patterns):
                        is_running = True
                
                if is_running:
                    if pid:
                        found_pid = pid
                        break

            status = "[bold green]● RUNNING[/bold green]" if is_running else "[bold red]○ STOPPED[/bold red]"
            pid_display = str(found_pid) if found_pid else ("ACTIVE" if is_running else "N/A")
            # Active context: show project root for running servers
            active_ctx = str(Path.cwd()) if is_running else "-"
            table.add_row(s["name"], status, pid_display, active_ctx)

        return table

    def _sanitize(text: str) -> str:
        # Remove common ANSI escape sequences and non-printable control chars
        import re

        # Strip ANSI color codes
        ansi_escape = re.compile(r"\x1B\[[0-9;]*[mK]")
        cleaned = ansi_escape.sub("", text)

        # Replace other control characters except newline and tab
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+", "", cleaned)
        return cleaned


    def get_logs(limit=20):
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                raw = "".join(lines[-limit:])
                return _sanitize(raw)
        except:
            return "Gathering log data..."

    # Use the current console and full-screen Live rendering. Avoid
    # console.clear() which can produce flicker on some terminals.
    # Use non-fullscreen Live to avoid excessive box redraws on Windows terminals
    # Print header once (outside Live) so it does not get re-rendered into the
    # terminal scrollback repeatedly. Live will only manage the activity stream.
    header_panel = Panel(
        check_server_status(),
        title="🛡️ MCP Code Intelligence - Live Control Center",
        border_style="blue",
        padding=(0, 1),
    )
    console.print(header_panel)

    with Live(layout, refresh_per_second=2, screen=False, console=console) as live:
        try:
            while True:
                # Update Body each loop
                log_data = get_logs(50)
                layout["body"].update(
                    Panel(
                        Text(log_data),
                        title="📝 Activity Stream",
                        subtitle="Press Ctrl+C to Exit",
                        border_style="dim",
                    )
                )

                time.sleep(0.5)
        except KeyboardInterrupt:
            pass

@app.command("install-standard-servers")
def install_standard_servers(allowed_path: Path = Path.cwd()):
    """DEPRECATED: Use 'setup' instead."""
    setup(allowed_path=allowed_path, global_install=False)
