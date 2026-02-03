"""CLI command for duplicate code detection."""

import asyncio
from pathlib import Path
from typing import Optional

import typer
from loguru import logger
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from mcp_code_intelligence.core.project import ProjectManager
from mcp_code_intelligence.core.database import ChromaVectorDatabase
from mcp_code_intelligence.core.embeddings import create_embedding_function
from mcp_code_intelligence.analysis.duplicates import DuplicateDetector

app = typer.Typer(help="🕵️ Detect duplicate code across the project")
console = Console()

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    project_root: Optional[Path] = typer.Option(None, "--project-root", "-p", help="Project root directory"),
    min_length: int = typer.Option(100, "--min-length", "-l", help="Minimum code block length"),
):
    """Scan project for duplicate code at semantic, structural, and exact levels."""
    if ctx.invoked_subcommand is not None:
        return

    async def run_analysis():
        pm = ProjectManager(project_root or Path.cwd())
        config = pm.load_config()
        
        # Setup DB
        embedding_function, _ = create_embedding_function(model_name=config.embedding_model)
        database = ChromaVectorDatabase(
            persist_directory=config.index_path,
            embedding_function=embedding_function
        )
        
        async with database:
            detector = DuplicateDetector(database)
            report = await detector.detect_all(min_length=min_length)
            
            _render_report(report)

    asyncio.run(run_analysis())

def _render_report(report: dict):
    console.print("\n[bold cyan]🛡️ Duplicate Code Analysis Report[/bold cyan]\n")
    
    # EXACT MATCHES
    if report["exact"]:
        table = Table(title="Level 3: Exact Matches (MD5/SHA256)", show_header=True, header_style="bold magenta")
        table.add_column("Group", style="dim")
        table.add_column("Count", justify="right")
        table.add_column("Files / Locations")
        
        for i, dup in enumerate(report["exact"], 1):
            locations = "\n".join([f"• {inst['location']}" for inst in dup["instances"]])
            table.add_row(str(i), f"[red]{dup['count']}[/red]", locations)
        console.print(table)
        console.print("")

    # STRUCTURAL
    if report["structural"]:
        table = Table(title="Level 2: Structural Similarity (Same skeleton)", show_header=True, header_style="bold yellow")
        table.add_column("Signature", style="dim")
        table.add_column("Count", justify="right")
        table.add_column("Unique Content", justify="right")
        table.add_column("Locations")
        
        for dup in report["structural"]:
            locations = ", ".join([inst["location"].split(":")[-1] for inst in dup["instances"][:3]])
            table.add_row(dup["signature"], f"{dup['count']}", f"{dup['unique_contents']}", f"{locations}...")
        console.print(table)
        console.print("")

    # SEMANTIC
    if report["semantic"]:
        console.print("[bold green]Level 1: Semantic Similarity (Vector Analysis)[/bold green]")
        for dup in report["semantic"]:
            orig = dup["original"]
            console.print(Panel(
                f"Original: [cyan]{orig['location']}[/cyan]\n" + 
                "\n".join([f"→ Similar: [yellow]{m['location']}[/yellow] (Score: {m['score']:.3f})" for m in dup["matches"]]),
                title=f"Possible Duplicate: {orig['function_name']}"
            ))

    # STATS
    stats = report["stats"]
    console.print(f"\n[dim]Scan complete: {stats['total_chunks_scanned']} code chunks analyzed.[/dim]")
    if not (report["exact"] or report["structural"] or report["semantic"]):
        console.print("[green]✅ Excellent! No significant code duplication found in your project.[/green]")

if __name__ == "__main__":
    app()
