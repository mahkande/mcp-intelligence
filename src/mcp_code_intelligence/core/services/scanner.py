
"""ScannerService: Handles file scanning and ignore logic (migrated from indexer.py)."""

import os
import fnmatch
from pathlib import Path
from typing import Any
from loguru import logger

# Allowed dotfiles that should not be ignored by the indexer
ALLOWED_DOTFILES = {'.env', '.gitignore', '.gitattributes', '.dockerignore', '.editorconfig', '.prettierrc', '.eslintrc', '.pylintrc', '.flake8', '.coveragerc', '.pre-commit-config.yaml', '.pre-commit-hooks.yaml', '.mcp-code-intelligence'}

class ScannerService:
    def __init__(self, project_root, config=None):
        self.project_root = Path(project_root)
        self.config = config
        self._ignore_patterns = []
        self.file_extensions = {'.py'}
        self.max_file_size_kb = 10240
        try:
            from mcp_code_intelligence.core.utils.gitignore import GitignoreParser
            self.gitignore_parser = GitignoreParser(self.project_root)
        except ImportError:
            self.gitignore_parser = None
        class DummyRagGuard:
            def should_index_path(self, file_path):
                return True
        self.rag_guard = DummyRagGuard()
        self._indexable_files_cache = None
        self._cache_timestamp = 0
        self._cache_ttl = 60

    def scan_files(self, exts=None):
        if exts is not None:
            self.file_extensions = set(exts)
        return self._find_indexable_files()

    def _find_indexable_files(self) -> list[Path]:
        import time
        current_time = time.time()
        if (
            self._indexable_files_cache is not None
            and current_time - self._cache_timestamp < self._cache_ttl
        ):
            logger.debug(
                f"Using cached indexable files ({len(self._indexable_files_cache)} files)"
            )
            return self._indexable_files_cache
        logger.debug("Rebuilding indexable files cache...")
        indexable_files = self._scan_files_sync()
        self._indexable_files_cache = sorted(indexable_files)
        self._cache_timestamp = current_time
        logger.debug(f"Rebuilt indexable files cache ({len(indexable_files)} files)")
        return self._indexable_files_cache

    def _scan_files_sync(self) -> list[Path]:
        indexable_files = []
        for root, dirs, files in os.walk(self.project_root):
            root_path = Path(root)
            dirs[:] = [
                d for d in dirs if not self._should_ignore_path(root_path / d, is_directory=True)
            ]
            for filename in files:
                file_path = root_path / filename
                if self._should_index_file(file_path, skip_file_check=True):
                    indexable_files.append(file_path)
        return indexable_files

    def _should_index_file(self, file_path: Path, skip_file_check: bool = False) -> bool:
        if file_path.suffix.lower() not in self.file_extensions:
            return False
        if not skip_file_check and not file_path.is_file():
            return False
        if self._should_ignore_path(file_path, is_directory=False):
            return False
        try:
            max_size_bytes = self.max_file_size_kb * 1024
            file_size = file_path.stat().st_size
            if file_size > max_size_bytes:
                logger.warning(f"Skipping very large file: {file_path} ({file_size} bytes > {max_size_bytes} bytes limit)")
                return False
        except OSError:
            return False
        if file_path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx", ".css", ".json", ".html"}:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    sample = f.read(8192)
                    lines = sample.splitlines()
                    if any(len(line) > 1000 for line in lines[:10]):
                        logger.debug(f"Skipping likely minified file: {file_path}")
                        return False
                    if "\x00" in sample:
                        logger.debug(f"Skipping likely binary file: {file_path}")
                        return False
            except Exception:
                pass
        return True

    def _should_ignore_path(self, file_path: Path, is_directory: bool | None = None) -> bool:
        try:
            path_name = file_path.name.lower()
            if is_directory or (is_directory is None and file_path.is_dir()):
                if path_name in {"venv", ".venv", "env", ".env", "node_modules", "__pycache__", "site-packages", "dist", "build", ".git", ".hg", ".svn"}:
                    return True
            relative_path = file_path.relative_to(self.project_root)
            skip_dotfiles = self.config.skip_dotfiles if self.config else True
            if skip_dotfiles:
                for part in relative_path.parts:
                    if part.startswith(".") and part not in ALLOWED_DOTFILES:
                        logger.debug(
                            f"Path ignored by dotfile filter '{part}': {file_path}"
                        )
                        return True
            if self.config and getattr(self.config, 'respect_gitignore', False):
                if self.gitignore_parser and self.gitignore_parser.is_ignored(
                    file_path, is_directory=is_directory
                ):
                    logger.debug(f"Path ignored by .gitignore: {file_path}")
                    return True
            for part in relative_path.parts:
                for pattern in self._ignore_patterns:
                    if fnmatch.fnmatch(part, pattern):
                        logger.debug(
                            f"Path ignored by pattern '{pattern}' matching '{part}': {file_path}"
                        )
                        return True
            for parent in relative_path.parents:
                for part in parent.parts:
                    for pattern in self._ignore_patterns:
                        if fnmatch.fnmatch(part, pattern):
                            logger.debug(
                                f"Path ignored by parent pattern '{pattern}' matching '{part}': {file_path}"
                            )
                            return True
            if not self.rag_guard.should_index_path(file_path):
                logger.debug(f"Path ignored by RAG Guard: {file_path}")
                return True
            return False
        except ValueError:
            return True
