#!/usr/bin/env python3
"""Migrate term_text indexes from btree to hash for all VitalGraph spaces.

Standalone script that connects directly to PostgreSQL and replaces the
btree composite index on (term_text, term_type) with a hash index on
term_text.  Btree indexes have a ~2704 byte row-size limit which causes
silent insert failures for large literals (e.g. document content).
Hash indexes have no such limit and support the equality-only lookups
used on term_text.

Usage:
    python apps/migrate_term_index_to_hash.py

Environment variables (or .env file):
    DB_HOST      PostgreSQL host       (default: localhost)
    DB_PORT      PostgreSQL port       (default: 5432)
    DB_NAME      Database name         (default: vitalgraph)
    DB_USERNAME  Database user         (default: postgres)
    DB_PASSWORD  Database password     (default: postgres)
    DRY_RUN      Set to 'true' to only report what would change
"""

import asyncio
import os
import sys

import asyncpg


async def migrate_space(conn: asyncpg.Connection, space_id: str, dry_run: bool) -> bool:
    """Migrate a single space's term_text index from btree to hash.

    Returns True if the index was migrated (or would be in dry-run mode).
    """
    idx_name = f"idx_{space_id}_term_tt"
    term_table = f"{space_id}_term"

    # Check current index type
    row = await conn.fetchrow(
        "SELECT am.amname AS index_type "
        "FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indexrelid "
        "JOIN pg_am am ON am.oid = c.relam "
        "WHERE c.relname = $1",
        idx_name,
    )

    if row is None:
        # Index missing — create as hash
        if dry_run:
            print(f"  [DRY RUN] {idx_name}: MISSING → would create hash index")
            return True
        await conn.execute(
            f"CREATE INDEX {idx_name} ON {term_table} USING hash (term_text)"
        )
        print(f"  ✅ {idx_name}: created (hash)")
        return True

    if row["index_type"] == "hash":
        print(f"  ⏭️  {idx_name}: already hash — skip")
        return False

    # It's btree (or other) — replace with hash
    if dry_run:
        print(f"  [DRY RUN] {idx_name}: {row['index_type']} → would replace with hash")
        return True

    await conn.execute(f"DROP INDEX IF EXISTS {idx_name}")
    await conn.execute(
        f"CREATE INDEX {idx_name} ON {term_table} USING hash (term_text)"
    )
    print(f"  ✅ {idx_name}: {row['index_type']} → hash")
    return True


async def main():
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = int(os.getenv("DB_PORT", "5432"))
    db_name = os.getenv("DB_NAME", "vitalgraph")
    db_user = os.getenv("DB_USERNAME", "postgres")
    db_pass = os.getenv("DB_PASSWORD", "postgres")
    dry_run = os.getenv("DRY_RUN", "").lower() == "true"

    if dry_run:
        print("=== DRY RUN MODE — no changes will be made ===\n")

    print(f"Connecting to {db_user}@{db_host}:{db_port}/{db_name} ...")
    conn = await asyncpg.connect(
        host=db_host, port=db_port, database=db_name,
        user=db_user, password=db_pass,
    )

    try:
        # Discover all *_term tables → derive space IDs
        rows = await conn.fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' "
            "  AND table_name LIKE '%\\_term' ESCAPE '\\' "
            "ORDER BY table_name"
        )

        spaces = []
        for row in rows:
            table_name = row["table_name"]
            if not table_name.endswith("_term"):
                continue
            space_id = table_name[:-5]  # strip '_term'
            spaces.append(space_id)

        print(f"Found {len(spaces)} space(s) with term tables.\n")

        migrated = 0
        failed = 0
        for space_id in spaces:
            print(f"Space: {space_id}")
            try:
                if await migrate_space(conn, space_id, dry_run):
                    migrated += 1
            except Exception as e:
                print(f"  ❌ FAILED: {e}")
                failed += 1

        print(f"\nDone. Migrated: {migrated}, Skipped: {len(spaces) - migrated - failed}, Failed: {failed}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
