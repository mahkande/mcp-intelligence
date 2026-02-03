
import json
import hashlib
import os
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, Set
from loguru import logger

class MetadataManager:
    """Manages file metadata (SHA-256 hashes, mtimes) for incremental indexing."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.metadata_file = project_root / ".mcp-code-intelligence" / "metadata.json"
        self.lock_file = project_root / ".mcp-code-intelligence" / "metadata.lock"
        self._data: Dict[str, Dict[str, Any]] = {}
        self.version = "1.0"
        self.load()

    def is_locked(self) -> bool:
        """Check if metadata is currently locked by another process."""
        return self.lock_file.exists()

    def acquire_lock(self) -> bool:
        """Try to acquire lock. Returns True if successful."""
        if self.is_locked():
            # Check if lock is stale (older than 10 minutes)
            try:
                if (datetime.now().timestamp() - self.lock_file.stat().st_mtime) > 600:
                    logger.warning("Stale metadata lock detected. Overriding.")
                    self.release_lock()
                else:
                    return False
            except OSError:
                return False

        try:
            self.lock_file.parent.mkdir(parents=True, exist_ok=True)
            self.lock_file.touch()
            return True
        except Exception as e:
            logger.error(f"Failed to acquire lock: {e}")
            return False

    def release_lock(self) -> None:
        """Release the lock."""
        try:
            if self.lock_file.exists():
                self.lock_file.unlink()
        except Exception as e:
            logger.error(f"Failed to release lock: {e}")

    def load(self) -> None:
        """Load metadata from disk."""
        if not self.metadata_file.exists():
            self._data = {}
            return

        try:
            with open(self.metadata_file, "r", encoding="utf-8") as f:
                content = json.load(f)
                self.version = content.get("version", "1.0")
                self._data = content.get("files", {})
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Metadata file corrupted or unreadable: {e}. Deleting and starting fresh.")
            try:
                if self.metadata_file.exists():
                    self.metadata_file.unlink()
            except Exception as del_e:
                logger.error(f"Failed to delete corrupted metadata file: {del_e}")
            self._data = {}

    def save(self) -> None:
        """Save metadata to disk."""
        try:
            self.metadata_file.parent.mkdir(parents=True, exist_ok=True)
            output = {
                "version": "1.0",
                "updated_at": datetime.now(UTC).isoformat(),
                "files": self._data
            }
            with open(self.metadata_file, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save metadata: {e}")

    def calculate_hash(self, file_path: Path) -> str:
        """Calculate hash using centralized utility."""
        from mcp_code_intelligence.utils.hashing import calculate_file_sha256
        return calculate_file_sha256(file_path)

    def needs_indexing(self, file_path: Path) -> bool:
        """Check if a file needs to be indexed (new or changed)."""
        str_path = str(file_path)
        
        # If not in metadata, it's new
        if str_path not in self._data:
            return True

        stored_info = self._data[str_path]
        
        # Quick check: Modification time
        try:
            current_mtime = os.path.getmtime(file_path)
            # If disk mtime is older or equal to stored, check hash strictly?
            # Actually, standard optimization is: if mtime <= stored_mtime, assume unchanged.
            # But let's be robust as requested: "Skip logic".
            # If mtime matches, we trust it. If diverse, verify hash.
            # Storing mtime allows skipping hash calc if timestamps match perfectly.
            if current_mtime == stored_info.get("mtime"):
                return False
        except OSError:
            # File might be gone
            return True

        # Mtime changed, verify hash content (content-based dedup)
        current_hash = self.calculate_hash(file_path)
        stored_hash = stored_info.get("hash")

        return current_hash != stored_hash

    def update_file(self, file_path: Path, additional_metrics: Dict[str, Any] | None = None) -> None:
        """Update metadata for a successfully indexed file.
        
        Args:
            file_path: Path to the indexed file
            additional_metrics: Optional dictionary of metrics (complexity, churn, etc.)
        """
        try:
            mtime = os.path.getmtime(file_path)
            file_hash = self.calculate_hash(file_path)
            
            entry = {
                "mtime": mtime,
                "hash": file_hash,
                "last_indexed": datetime.now(UTC).isoformat()
            }
            
            if additional_metrics:
                entry.update(additional_metrics)
                
            self._data[str(file_path)] = entry
        except Exception as e:
            logger.error(f"Failed to update metadata for {file_path}: {e}")

    def remove_file(self, file_path: Path) -> None:
        """Remove a file from metadata."""
        str_path = str(file_path)
        if str_path in self._data:
            del self._data[str_path]

    def get_tracked_files(self) -> Set[Path]:
        """Return a set of all files currently tracked in metadata."""
        return {Path(p) for p in self._data.keys()}
