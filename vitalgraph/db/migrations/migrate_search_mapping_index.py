"""
Search Mapping Index junction table migration.

Creates the ``{space}_search_mapping_index`` junction table for all spaces
and backfills it from existing ``search_mapping.index_name`` values by
checking which concrete ``_vec_`` and ``_fts_`` data tables exist.

Steps per space:

1. Create ``{space}_search_mapping_index`` table if not exists.
2. For each search_mapping row:
   a. Check if ``{space}_vec_{index_name}`` table exists → insert ('vector', index_name).
   b. Check if ``{space}_fts_{index_name}`` table exists → insert ('fts', index_name).
3. Report summary statistics.

Idempotent — safe to re-run.  Uses ON CONFLICT DO NOTHING for all inserts.

Usage:
    python -m vitalgraph.db.migrations.migrate_search_mapping_index --database vitalgraph
    python -m vitalgraph.db.migrations.migrate_search_mapping_index --dsn "postgresql://..."
    python -m vitalgraph.db.migrations.migrate_search_mapping_index --database vitalgraph --dry-run
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import List

import asyncpg

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────

async def _table_exists(conn: asyncpg.Connection, table_name: str) -> bool:
    """Check if a table exists."""
    result = await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = $1)",
        table_name,
    )
    return bool(result)


async def _get_all_space_ids(conn: asyncpg.Connection) -> List[str]:
    """Get all space_ids from the space table."""
    rows = await conn.fetch("SELECT space_id FROM space ORDER BY space_id")
    return [r['space_id'] for r in rows]


# ── Per-space migration ───────────────────────────────────────────────

async def _migrate_space(
    conn: asyncpg.Connection,
    space_id: str,
    dry_run: bool = False,
) -> dict:
    """Migrate a single space: create junction table and backfill.

    Returns a stats dict.
    """
    stats = {
        'table_created': False,
        'vector_associations': 0,
        'fts_associations': 0,
    }

    sm_table = f"{space_id}_search_mapping"
    smi_table = f"{space_id}_search_mapping_index"

    # Check if search_mapping table exists
    if not await _table_exists(conn, sm_table):
        logger.info("  [%s] No search_mapping table — skipping", space_id)
        return stats

    # Step 1: Create junction table
    if not await _table_exists(conn, smi_table):
        if dry_run:
            logger.info("  [%s] Would create table: %s", space_id, smi_table)
        else:
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {smi_table} (
                    id              SERIAL PRIMARY KEY,
                    mapping_id      INTEGER NOT NULL,
                    index_type      VARCHAR(10) NOT NULL CHECK (index_type IN ('vector', 'fts')),
                    index_name      VARCHAR(255) NOT NULL,
                    created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (mapping_id, index_type, index_name),
                    FOREIGN KEY (mapping_id) REFERENCES {sm_table}(mapping_id) ON DELETE CASCADE
                )
            """)
            logger.info("  [%s] Created table: %s", space_id, smi_table)
        stats['table_created'] = True
    else:
        logger.info("  [%s] Junction table already exists: %s", space_id, smi_table)

    # Step 2: Backfill from existing index_name values
    mappings = await conn.fetch(
        f"SELECT mapping_id, index_name FROM {sm_table}"
    )

    for row in mappings:
        mapping_id = row['mapping_id']
        index_name = row['index_name']

        # Check if vector data table exists
        vec_table = f"{space_id}_vec_{index_name}"
        if await _table_exists(conn, vec_table):
            if dry_run:
                logger.info("    [%s] Would associate mapping %d → vector/%s",
                            space_id, mapping_id, index_name)
            else:
                await conn.execute(f"""
                    INSERT INTO {smi_table} (mapping_id, index_type, index_name)
                    VALUES ($1, 'vector', $2)
                    ON CONFLICT (mapping_id, index_type, index_name) DO NOTHING
                """, mapping_id, index_name)
            stats['vector_associations'] += 1

        # Check if FTS data table exists
        fts_table = f"{space_id}_fts_{index_name}"
        if await _table_exists(conn, fts_table):
            if dry_run:
                logger.info("    [%s] Would associate mapping %d → fts/%s",
                            space_id, mapping_id, index_name)
            else:
                await conn.execute(f"""
                    INSERT INTO {smi_table} (mapping_id, index_type, index_name)
                    VALUES ($1, 'fts', $2)
                    ON CONFLICT (mapping_id, index_type, index_name) DO NOTHING
                """, mapping_id, index_name)
            stats['fts_associations'] += 1

    return stats


# ── Main migration ────────────────────────────────────────────────────

async def migrate_search_mapping_index(
    conn: asyncpg.Connection,
    dry_run: bool = False,
) -> dict:
    """Run the search_mapping_index migration for all spaces.

    Returns a summary dict.
    """
    space_ids = await _get_all_space_ids(conn)
    logger.info("Found %d space(s) to migrate", len(space_ids))

    summary = {
        'spaces_processed': 0,
        'tables_created': 0,
        'vector_associations': 0,
        'fts_associations': 0,
    }

    for space_id in space_ids:
        stats = await _migrate_space(conn, space_id, dry_run=dry_run)
        summary['spaces_processed'] += 1
        if stats['table_created']:
            summary['tables_created'] += 1
        summary['vector_associations'] += stats['vector_associations']
        summary['fts_associations'] += stats['fts_associations']

    mode = "DRY RUN" if dry_run else "COMPLETE"
    logger.info(
        "\n── Migration %s ──\n"
        "  Spaces processed:      %d\n"
        "  Junction tables created: %d\n"
        "  Vector associations:    %d\n"
        "  FTS associations:       %d",
        mode,
        summary['spaces_processed'],
        summary['tables_created'],
        summary['vector_associations'],
        summary['fts_associations'],
    )
    return summary


# ── Runner ────────────────────────────────────────────────────────────

async def run_migration(
    dsn: str | None = None,
    dry_run: bool = False,
    **kwargs,
):
    """Connect to the database and run the migration.

    Args:
        dsn: PostgreSQL DSN string. If None, uses kwargs for connection params.
        dry_run: If True, only report what would be done.
        **kwargs: Connection params (host, port, database, user, password).
    """
    if dsn:
        conn = await asyncpg.connect(dsn)
    else:
        conn = await asyncpg.connect(**kwargs)

    try:
        if dry_run:
            await migrate_search_mapping_index(conn, dry_run=True)
        else:
            async with conn.transaction():
                await migrate_search_mapping_index(conn, dry_run=False)
    finally:
        await conn.close()


def main():
    """CLI entrypoint for running the migration standalone."""
    import argparse

    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(
        description="Migrate search_mapping_index junction table for all spaces"
    )
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--database", default="vitalgraph")
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--password", default="")
    parser.add_argument("--dsn", default=None, help="Full DSN (overrides other params)")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would be done without making changes",
    )
    args = parser.parse_args()

    if args.dsn:
        asyncio.run(run_migration(dsn=args.dsn, dry_run=args.dry_run))
    else:
        asyncio.run(run_migration(
            host=args.host,
            port=args.port,
            database=args.database,
            user=args.user,
            password=args.password,
            dry_run=args.dry_run,
        ))


if __name__ == "__main__":
    main()
