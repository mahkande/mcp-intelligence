#!/usr/bin/env python3
"""Register an architectural relationship into the Memory SQLite DB.

This script mirrors the `create_entity_relationship` behavior from the Memory server
and can be pointed at a specific `.mcp_memory.db` file (defaults to user's home).

Usage:
  python scripts/register_architectural_relationship.py \
    --source SemanticSearchEngine --target VectorDatabase \
    --note "SemanticSearchEngine depends on VectorDatabase for vector search" \
    [--db-path /path/to/.mcp_memory.db]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
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


def relationship_exists(conn: sqlite3.Connection, source: str, target: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM relationships WHERE source = ? AND target = ? LIMIT 1",
        (source, target),
    )
    return cur.fetchone() is not None


def create_relationship(
    conn: sqlite3.Connection,
    source: str,
    target: str,
    note: str | None = None,
    navigation_hint: str | None = None,
    content_hash: str | None = None,
) -> str:
    import uuid

    rel_id = f"rel:{uuid.uuid4().hex[:8]}"
    rel = {
        "type": "relationship",
        "source": source,
        "target": target,
        "note": note or "",
        "navigation_hint": navigation_hint,
    }
    if content_hash:
        rel["content_hash"] = content_hash

    conn.execute(
        """
        INSERT OR REPLACE INTO relationships
        (key, source, target, source_id, target_id, relationship_type, note, navigation_hint, content_hash, symbol_type, vector_id, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """,
        (rel_id, source, target, None, None, "architectural", note or "", navigation_hint, content_hash, None, None),
    )

    conn.execute(
        """
        INSERT OR REPLACE INTO memory (key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
    """,
        (rel_id, json.dumps(rel)),
    )

    conn.commit()
    return rel_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--note", default="")
    parser.add_argument("--navigation-hint", dest="navigation_hint")
    parser.add_argument("--content-hash", dest="content_hash")
    parser.add_argument("--db-path", dest="db_path")

    args = parser.parse_args(argv)

    db_path = Path(args.db_path) if args.db_path else (Path.home() / ".mcp_memory.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        ensure_tables(conn)

        if relationship_exists(conn, args.source, args.target):
            print(f"Relationship already exists: {args.source} -> {args.target}")
            return 0

        rel_id = create_relationship(
            conn,
            args.source,
            args.target,
            note=args.note,
            navigation_hint=args.navigation_hint,
            content_hash=args.content_hash,
        )
        print(f"Created relationship {rel_id}: {args.source} -> {args.target}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
