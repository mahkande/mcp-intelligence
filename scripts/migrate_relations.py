"""Migrate legacy 'rel:' JSON entries from `memory` table into structured `relationships` table.

Usage:
    python scripts/migrate_relations.py [--db PATH] [--delete-legacy]

If --delete-legacy is passed, legacy JSON rows will be removed after successful migration.
"""
import argparse
import json
import sqlite3
from pathlib import Path


def migrate(db_path: Path, delete_legacy: bool = False) -> None:
    db_path = Path(db_path)
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Ensure relationships table exists (schema compatible with server)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS relationships (
            key TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            target TEXT NOT NULL,
            source_id TEXT,
            target_id TEXT,
            relationship_type TEXT,
            note TEXT,
            navigation_hint TEXT,
            content_hash TEXT,
            symbol_type TEXT,
            vector_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    # Ensure legacy memory table exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memory'")
    if cur.fetchone() is None:
        print("No legacy 'memory' table found; nothing to migrate.")
        conn.close()
        return

    # Find legacy rel: keys in memory table
    cur.execute("SELECT key, value FROM memory WHERE key LIKE 'rel:%'")
    rows = cur.fetchall()
    total = len(rows)
    migrated = 0
    skipped = 0

    for key, value in rows:
        try:
            obj = json.loads(value)
        except Exception as e:
            print(f"Skipping {key}: invalid JSON ({e})")
            skipped += 1
            continue

        if not isinstance(obj, dict):
            print(f"Skipping {key}: payload not an object")
            skipped += 1
            continue

        # Accept either explicit type 'relationship' or presence of source/target
        if obj.get("type") != "relationship" and not (obj.get("source") and obj.get("target")):
            print(f"Skipping {key}: not a relationship payload")
            skipped += 1
            continue

        source = obj.get("source")
        target = obj.get("target")
        note = obj.get("note")
        nav = obj.get("navigation_hint")
        ch = obj.get("content_hash")
        sym = obj.get("symbol_type")
        vid = obj.get("vector_id")
        src_id = obj.get("source_id")
        tgt_id = obj.get("target_id")
        rel_type = obj.get("relationship_type")

        try:
            cur.execute(
                """
                INSERT OR REPLACE INTO relationships
                (key, source, target, source_id, target_id, relationship_type, note, navigation_hint, content_hash, symbol_type, vector_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
                (key, source, target, src_id, tgt_id, rel_type, note, nav, ch, sym, vid),
            )
            migrated += 1
        except Exception as e:
            print(f"Failed to insert {key} into relationships: {e}")
            skipped += 1
            continue

    conn.commit()

    if delete_legacy and migrated > 0:
        # Delete the migrated legacy rows
        cur.execute("DELETE FROM memory WHERE key LIKE 'rel:%'")
        conn.commit()
        print(f"Deleted {total - skipped - migrated} legacy rows (if any).")

    print(f"Migration complete: total_found={total}, migrated={migrated}, skipped={skipped}")
    conn.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument("--db", help="Path to SQLite DB (default: ~/.mcp_memory.db)", default=str(Path.home() / ".mcp_memory.db"))
    p.add_argument("--delete-legacy", help="Delete legacy rel: rows after successful migration", action="store_true")
    args = p.parse_args()
    migrate(Path(args.db), delete_legacy=args.delete_legacy)
