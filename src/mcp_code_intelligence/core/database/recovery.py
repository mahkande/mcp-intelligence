"""Database corruption detection and recovery mechanisms."""

import shutil
import time
from pathlib import Path
from loguru import logger

from mcp_code_intelligence.core.exceptions import IndexCorruptionError


class DatabaseRecoveryMixin:
    """Mixin for detecting and recovering from database corruption.
    
    Requires the host class to have a 'persist_directory' attribute of type Path.
    """
    
    # Typed attribute for mypy
    persist_directory: Path

    async def _detect_and_recover_corruption(self) -> None:
        """Detect and recover from index corruption proactively.

        This method checks for:
        1. SQLite database corruption (LAYER 1: Pre-initialization check)
        2. HNSW pickle file corruption
        3. Metadata/data inconsistencies
        4. File size anomalies
        """
        # LAYER 1: Check SQLite database integrity FIRST (before ChromaDB initialization)
        chroma_db_path = self.persist_directory / "chroma.sqlite3"

        # If database doesn't exist yet, nothing to check
        if not chroma_db_path.exists():
            return

        # SQLite integrity check - catches corruption BEFORE Rust panic
        try:
            import sqlite3

            logger.debug("Running SQLite integrity check...")
            conn = sqlite3.connect(str(chroma_db_path))
            cursor = conn.execute("PRAGMA quick_check")
            result = cursor.fetchone()[0]
            conn.close()

            if result != "ok":
                logger.warning(f"SQLite database corruption detected: {result}")
                logger.info("Initiating automatic recovery from database corruption...")
                await self._recover_from_corruption()
                return

            logger.debug("SQLite integrity check passed")

        except sqlite3.Error as e:
            logger.warning(f"SQLite database error during integrity check: {e}")
            logger.info("Initiating automatic recovery from database corruption...")
            await self._recover_from_corruption()
            return

        # Check for HNSW index files that might be corrupted
        index_path = self.persist_directory / "index"

        if index_path.exists():
            # Look for pickle files in the index (HNSW metadata)
            pickle_files = list(index_path.glob("**/*.pkl"))
            pickle_files.extend(list(index_path.glob("**/*.pickle")))
            pickle_files.extend(list(index_path.glob("**/*.bin")))  # Binary HNSW files

            logger.debug(
                f"Checking {len(pickle_files)} HNSW index files for corruption..."
            )

            for pickle_file in pickle_files:
                try:
                    # Check file size - suspiciously small files might be corrupted
                    file_size = pickle_file.stat().st_size
                    if file_size == 0:
                        logger.warning(
                            f"Empty HNSW index file detected: {pickle_file} (0 bytes)"
                        )
                        await self._recover_from_corruption()
                        return

                    # Only validate pickle files (not binary .bin files)
                    if pickle_file.suffix in (".pkl", ".pickle"):
                        # Try to read the pickle file to detect corruption
                        import pickle  # nosec B403 # Trusted internal index files only

                        with open(pickle_file, "rb") as f:
                            data = pickle.load(f)  # nosec B301 # Trusted internal index files only

                            # Additional validation: check if data structure is valid
                            if data is None:
                                logger.warning(
                                    f"HNSW index file contains None data: {pickle_file}"
                                )
                                await self._recover_from_corruption()
                                return

                            # Check for metadata consistency (if it's a dict)
                            if isinstance(data, dict):
                                # Look for known metadata keys that should exist
                                if "space" in data and "dim" in data:
                                    # Validate dimensions are reasonable
                                    if data.get("dim", 0) <= 0:
                                        logger.warning(
                                            f"Invalid dimensions in HNSW index: {pickle_file} (dim={data.get('dim')})"
                                        )
                                        await self._recover_from_corruption()
                                        return

                except (EOFError, pickle.UnpicklingError) as e:
                    logger.warning(f"Pickle corruption detected in {pickle_file}: {e}")
                    await self._recover_from_corruption()
                    return
                except Exception as e:
                    # Check if this is a Rust panic pattern
                    error_msg = str(e).lower()
                    if "range start index" in error_msg and "out of range" in error_msg:
                        logger.warning(
                            f"Rust panic pattern detected in {pickle_file}: {e}"
                        )
                        await self._recover_from_corruption()
                        return
                    else:
                        logger.warning(
                            f"Error reading HNSW index file {pickle_file}: {e}"
                        )
                        # Continue checking other files before deciding to recover
                        continue

            logger.debug("HNSW index files validation passed")

    async def _recover_from_corruption(self) -> None:
        """Recover from index corruption by rebuilding the index.

        This method:
        1. Creates a timestamped backup of the corrupted index
        2. Clears the corrupted index directory
        3. Recreates the directory structure
        4. Logs detailed recovery steps and instructions
        """
        logger.warning("=" * 80)
        logger.warning("INDEX CORRUPTION DETECTED - Initiating recovery...")
        logger.warning("=" * 80)

        # Create backup directory
        backup_dir = (
            self.persist_directory.parent / f"{self.persist_directory.name}_backup"
        )
        backup_dir.mkdir(exist_ok=True)

        # Backup current state (in case we need it for debugging)
        timestamp = int(time.time())
        backup_path = backup_dir / f"backup_{timestamp}"

        if self.persist_directory.exists():
            try:
                shutil.copytree(self.persist_directory, backup_path)
                logger.info(f"✓ Created backup at {backup_path}")
            except Exception as e:
                logger.warning(f"⚠ Could not create backup: {e}")

        # Clear the corrupted index
        if self.persist_directory.exists():
            try:
                # Log what we're about to delete
                total_size = sum(
                    f.stat().st_size
                    for f in self.persist_directory.rglob("*")
                    if f.is_file()
                )
                logger.info(
                    f"Clearing corrupted index ({total_size / 1024 / 1024:.2f} MB)..."
                )

                shutil.rmtree(self.persist_directory)
                logger.info(f"✓ Cleared corrupted index at {self.persist_directory}")
            except Exception as e:
                logger.error(f"✗ Failed to clear corrupted index: {e}")
                raise IndexCorruptionError(
                    f"Could not clear corrupted index: {e}. "
                    f"Please manually delete {self.persist_directory} and try again."
                ) from e

        # Recreate the directory
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        logger.info("✓ Index directory recreated")

        logger.warning("=" * 80)
        logger.warning("RECOVERY COMPLETE - Next steps:")
        logger.warning("  1. Run 'mcp-code-intelligence index' to rebuild the index")
        logger.warning(f"  2. Backup saved to: {backup_path}")
        logger.warning("=" * 80)
