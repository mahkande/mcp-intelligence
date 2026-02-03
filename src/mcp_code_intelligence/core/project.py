"""Project detection and management for MCP Code Intelligence."""

import json
from pathlib import Path

from loguru import logger

from mcp_code_intelligence.config.defaults import (
    DEFAULT_FILE_EXTENSIONS,
    DEFAULT_IGNORE_PATTERNS,
    get_default_config_path,
    get_default_index_path,
    get_language_from_extension,
)
from mcp_code_intelligence.config.settings import ProjectConfig
from mcp_code_intelligence.utils.gitignore import create_gitignore_parser
from mcp_code_intelligence.core.exceptions import (
    ConfigurationError,
    ProjectInitializationError,
    ProjectNotFoundError,
)
from mcp_code_intelligence.core.models import ProjectInfo


class ProjectManager:
    """Manages project detection, initialization, and configuration."""

    def __init__(self, project_root: Path | None = None) -> None:
        """Initialize project manager.

        Args:
            project_root: Project root directory. If None, will auto-detect.
        """
        self.project_root = project_root or self._detect_project_root()
        self._config: ProjectConfig | None = None

        # Initialize gitignore parser
        try:
            self.gitignore_parser = create_gitignore_parser(self.project_root)
        except Exception as e:
            logger.debug(f"Failed to load gitignore patterns: {e}")
            self.gitignore_parser = None

    def _detect_project_root(self) -> Path:
        """Auto-detect project root directory."""
        current = Path.cwd()

        # Look for common project indicators
        indicators = [
            ".git",
            ".mcp-code-intelligence",
            "pyproject.toml",
            "package.json",
            "Cargo.toml",
            "go.mod",
            "pom.xml",
            "build.gradle",
            ".project",
        ]

        # Walk up the directory tree
        for path in [current] + list(current.parents):
            for indicator in indicators:
                if (path / indicator).exists():
                    logger.debug(f"Detected project root: {path} (found {indicator})")
                    return path

        # Default to current directory
        logger.debug(f"Using current directory as project root: {current}")
        return current

    def is_initialized(self) -> bool:
        """Check if project is initialized for MCP Code Intelligence."""
        config_path = get_default_config_path(self.project_root)
        index_path = get_default_index_path(self.project_root)

        return config_path.exists() and index_path.exists()

    def initialize(
        self,
        file_extensions: list[str] | None = None,
        embedding_model: str = "microsoft/codebert-base",
        similarity_threshold: float = 0.5,
        force: bool = False,
    ) -> ProjectConfig:
        """Initialize project for MCP Code Intelligence.

        Args:
            file_extensions: File extensions to index
            embedding_model: Embedding model to use
            similarity_threshold: Similarity threshold for search
            force: Force re-initialization if already exists

        Returns:
            Project configuration

        Raises:
            ProjectInitializationError: If initialization fails
        """
        if self.is_initialized() and not force:
            raise ProjectInitializationError(
                f"Project already initialized at {self.project_root}. Use --force to re-initialize."
            )

        try:
            # Backup existing config if forcing re-initialization
            config_path = get_default_config_path(self.project_root)
            if force and config_path.exists():
                backup_path = config_path.with_suffix(".json.bak")
                import shutil

                shutil.copy2(config_path, backup_path)
                logger.info(f"Backed up existing config to {backup_path}")

            # Create index directory
            index_path = get_default_index_path(self.project_root)
            index_path.mkdir(parents=True, exist_ok=True)

            # Ensure .mcp-code-intelligence/ is in .gitignore
            # This is a non-critical operation - failures are logged but don't block initialization
            try:
                from mcp_code_intelligence.utils.gitignore_updater import ensure_gitignore_entry

                ensure_gitignore_entry(
                    self.project_root,
                    pattern=".mcp-code-intelligence/",
                    comment="MCP Code Intelligence index directory",
                )
            except Exception as e:
                # Log warning but continue initialization
                logger.warning(f"Could not update .gitignore: {e}")
                logger.info(
                    "Please manually add '.mcp-code-intelligence/' to your .gitignore file"
                )

            # When force=True, always use current defaults if no extensions specified
            # This ensures config regeneration picks up new file types
            resolved_extensions = (
                file_extensions
                if file_extensions is not None
                else DEFAULT_FILE_EXTENSIONS
            )

            # Detect languages and files
            detected_languages = self.detect_languages()
            file_count = self.count_indexable_files(resolved_extensions)

            # Create configuration
            config = ProjectConfig(
                project_root=self.project_root,
                index_path=index_path,
                file_extensions=resolved_extensions,
                embedding_model=embedding_model,
                similarity_threshold=similarity_threshold,
                languages=detected_languages,
            )

            # Save configuration
            self.save_config(config)

            action = "Re-initialized" if force else "Initialized"
            logger.info(
                f"{action} project at {self.project_root}",
                languages=detected_languages,
                file_count=file_count,
                extensions=config.file_extensions,
            )

            self._config = config
            return config

        except Exception as e:
            raise ProjectInitializationError(
                f"Failed to initialize project: {e}"
            ) from e

    def load_config(self) -> ProjectConfig:
        """Load project configuration.

        Returns:
            Project configuration

        Raises:
            ProjectNotFoundError: If project is not initialized
            ConfigurationError: If configuration is invalid
        """
        if not self.is_initialized():
            raise ProjectNotFoundError(
                f"Project not initialized at {self.project_root}. Run 'mcp-code-intelligence init' first."
            )

        config_path = get_default_config_path(self.project_root)

        try:
            with open(config_path) as f:
                config_data = json.load(f)

            # Convert paths back to Path objects
            config_data["project_root"] = Path(config_data["project_root"])
            config_data["index_path"] = Path(config_data["index_path"])

            config = ProjectConfig(**config_data)
            self._config = config
            return config

        except Exception as e:
            raise ConfigurationError(f"Failed to load configuration: {e}") from e

    def save_config(self, config: ProjectConfig) -> None:
        """Save project configuration.

        Args:
            config: Project configuration to save

        Raises:
            ConfigurationError: If saving fails
        """
        config_path = get_default_config_path(self.project_root)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Convert to JSON-serializable format
            config_data = config.model_dump()
            config_data["project_root"] = str(config.project_root)
            config_data["index_path"] = str(config.index_path)

            # Atomic write: Write to temp file first, then rename
            # This ensures config.json is never corrupted or left empty
            temp_path = config_path.with_suffix(".tmp")
            
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2)
                f.flush()
                # Ensure data is written to disk
                import os
                os.fsync(f.fileno())
            
            # Atomic replacement
            temp_path.replace(config_path)

            logger.debug(f"Saved configuration to {config_path}")

        except Exception as e:
            # Try to cleanup temp file
            if 'temp_path' in locals() and temp_path.exists():
                try:
                    temp_path.unlink()
                except:
                    pass
            raise ConfigurationError(f"Failed to save configuration: {e}") from e

    @property
    def config(self) -> ProjectConfig:
        """Get project configuration, loading if necessary."""
        if self._config is None:
            self._config = self.load_config()
        return self._config

    def detect_languages(self) -> list[str]:
        """Detect programming languages in the project.

        Returns:
            List of detected language names
        """
        languages: set[str] = set()

        for file_path in self._iter_source_files():
            language = get_language_from_extension(file_path.suffix)
            if language != "text":
                languages.add(language)

        return sorted(languages)

    def count_indexable_files(self, extensions: list[str]) -> int:
        """Count files that can be indexed.

        Args:
            extensions: File extensions to count

        Returns:
            Number of indexable files
        """
        count = 0
        for file_path in self._iter_source_files():
            if file_path.suffix in extensions:
                count += 1
        return count

    def get_project_info(self, file_count: int | None = None) -> ProjectInfo:
        """Get comprehensive project information.

        Args:
            file_count: Optional pre-computed file count (avoids expensive filesystem scan)

        Returns:
            Project information
        """
        config_path = get_default_config_path(self.project_root)
        index_path = get_default_index_path(self.project_root)

        is_initialized = self.is_initialized()
        languages = []
        computed_file_count = 0

        if is_initialized:
            try:
                config = self.config
                languages = config.languages
                # Use provided file_count if available to avoid filesystem scan
                if file_count is not None:
                    computed_file_count = file_count
                else:
                    computed_file_count = self.count_indexable_files(
                        config.file_extensions
                    )
            except Exception:
                # Ignore errors when getting detailed info
                pass

        return ProjectInfo(
            name=self.project_root.name,
            root_path=self.project_root,
            config_path=config_path,
            index_path=index_path,
            is_initialized=is_initialized,
            languages=languages,
            file_count=computed_file_count,
        )

    def _iter_source_files(self) -> list[Path]:
        """Iterate over source files in the project.

        Returns:
            List of source file paths
        """
        import os
        files = []

        for root, dirs, filenames in os.walk(self.project_root, topdown=True):
            # Optimization: Filter directories IN-PLACE to skip ignored ones
            dirs[:] = [
                d for d in dirs
                if not self._should_ignore_path(Path(root) / d, is_directory=True)
            ]

            for filename in filenames:
                path = Path(root) / filename
                # Files are already filtered by directory pruning, 
                # but we check the file itself just in case of file-specific ignore patterns
                if not self._should_ignore_path(path, is_directory=False):
                    files.append(path)

        return files

    def _should_ignore_path(self, path: Path, is_directory: bool | None = None) -> bool:
        """Check if a path should be ignored.

        Args:
            path: Path to check
            is_directory: Optional hint if path is a directory (avoids filesystem check)

        Returns:
            True if path should be ignored
        """
        # First check gitignore rules if available
        # PERFORMANCE: Pass is_directory hint to avoid redundant stat() calls
        if self.gitignore_parser and self.gitignore_parser.is_ignored(
            path, is_directory=is_directory
        ):
            return True

        # Check if any parent directory is in ignore patterns
        for part in path.parts:
            if part in DEFAULT_IGNORE_PATTERNS:
                return True

        # Check relative path from project root
        try:
            relative_path = path.relative_to(self.project_root)
            for part in relative_path.parts:
                if part in DEFAULT_IGNORE_PATTERNS:
                    return True
        except ValueError:
            # Path is not relative to project root
            return True

        return False


