import sys
import os
import shutil
import subprocess
import shlex
from pathlib import Path
from loguru import logger
from rich.console import Console
from mcp_code_intelligence.config.defaults import DEFAULT_EMBEDDING_MODELS

class IntelligenceManager:
    """Manages LSPs, Embedding models, and language-specific tools."""

    def __init__(self, project_root: Path, console: Console):
        self.project_root = project_root
        self.console = console
        self.python_cmd = sys.executable

    def get_lsp_configs(self) -> dict:
        """Returns the supported LSP configurations."""
        return {
            "python": {
                "id": "python-lsp",
                "cmd": self.python_cmd,
                "args": ["-m", "mcp_code_intelligence.servers.python_lsp_server", str(self.project_root.resolve())]
            },
            "javascript/typescript": {
                "id": "js-ts-lsp",
                "cmd": "typescript-language-server",
                "args": ["--stdio"],
                "win_cmd": "typescript-language-server.cmd"
            },
            "dart/flutter": {
                "id": "dart-lsp",
                "cmd": "dart",
                "args": ["language-server", "--stdio"]
            },
            "rust": {
                "id": "rust-lsp",
                "cmd": "rust-analyzer",
                "args": []
            },
            "go": {
                "id": "go-lsp",
                "cmd": "gopls",
                "args": ["serve"]
            },
            "c/c++": {
                "id": "cpp-lsp",
                "cmd": "clangd",
                "args": []
            }
        }

    def process_language_dependencies(self, lang_data: dict) -> None:
        """Install language-specific dependencies defined in language JSON."""
        dependencies = lang_data.get("dependencies", [])
        if not dependencies:
            return

        name = lang_data.get("name", "Unknown")
        self.console.print(f"   [dim]Checking additional tools for {name}...[/dim]")
        
        for dep in dependencies:
            dep_name = dep.get("name", "Unknown tool")
            check_cmd = dep.get("check_cmd")
            install_cmd = dep.get("install_cmd")
            
            is_installed = False
            if check_cmd:
                try:
                    parts = shlex.split(check_cmd)
                    if shutil.which(parts[0]):
                         subprocess.run(parts, capture_output=True, check=False)
                         is_installed = True
                except Exception: pass
                    
            if not is_installed and install_cmd:
                self.console.print(f"   📦 Installing {dep_name}...")
                try:
                    subprocess.run(shlex.split(install_cmd), check=True, capture_output=False)
                    self.console.print(f"      ✅ Installed {dep_name}")
                except Exception as e:
                    self.console.print(f"      ❌ Failed to install {dep_name}: {e}")
                    logger.warning(f"Failed to install dependency {dep_name}: {e}")

    def download_model_weights(self, model_name: str) -> bool:
        """Pre-download the embedding model."""
        try:
            self.console.print(f"   [dim]📥 Readying model weights for {model_name}...[/dim]")
            from mcp_code_intelligence.core.embeddings import create_embedding_function
            create_embedding_function(model_name=model_name, cache_dir=self.project_root / ".mcp-code-intelligence" / "cache")
            return True
        except Exception as e:
            logger.warning(f"Failed to pre-download model: {e}")
            return False

    def download_reranker(self) -> bool:
        """Pre-download the neural reranker model."""
        try:
            model_name = "jinaai/jina-reranker-v2-base-multilingual"
            self.console.print(f"   [dim]📥 Downloading neural reranker: {model_name}...[/dim]")
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
            AutoModelForSequenceClassification.from_pretrained(model_name, trust_remote_code=True)
            return True
        except Exception as e:
            logger.debug(f"Failed to download reranker: {e}")
            return False
