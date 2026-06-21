"""
Drop deprecated ``include_type_desc`` column from search_mapping tables.

The ``source_type`` column now carries this information via its enum values:
- ``type_description`` and ``properties_type`` imply type description lookup
- ``properties`` and ``default`` do not

Before dropping, this migration upgrades existing rows where
``include_type_desc=True`` and ``source_type='default'`` to
``source_type='properties_type'`` (preserving the semantic of including
type descriptions alongside property text).

Steps per space:

1. Check if ``{space}_search_mapping`` table has an ``include_type_desc`` column.
2. If yes:
   a. Upgrade ``source_type`` for rows where include_type_desc was meaningful.
   b. Drop the column.
3. Report summary statistics.

Idempotent — safe to re-run.  If the column doesn't exist, skips that space.

Usage:
    python -m vitalgraph.db.migrations.migrate_drop_include_type_desc --database vitalgraph
    python -m vitalgraph.db.migrations.migrate_drop_include_type_desc --dsn "postgresql://..."
    python -m vitalgraph.db.migrations.migrate_drop_include_type_desc --database vitalgraph --dry-run
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


async def _column_exists(conn: asyncpg.Connection, table_name: str, column_name: str) -> bool:
    """Check if a column exists on a table."""
    result = await conn.fetchval(
        "SELECT EXISTS ("
        "  SELECT 1 FROM information_schema.columns "
        "  WHERE table_name = $1 AND column_name = $2"
        ")",
        table_name, column_name,
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
    """Migrate a single space: upgrade source_type values and drop column.

    Returns:
        Dict with migration stats for this space.
    """
    stats = {"space_id": space_id, "skipped": False, "upgraded": 0, "dropped": False}
    mapping_table = f"{space_id}_search_mapping"

    # Check table exists
    if not await _table_exists(conn, mapping_table):
        stats["skipped"] = True
        logger.debug("  %s: no search_mapping table, skipping", space_id)
        return stats

    # Check column exists
    if not await _column_exists(conn, mapping_table, "include_type_desc"):
        stats["skipped"] = True
        logger.info("  %s: include_type_desc already dropped, skipping", space_id)
        return stats

    # Step 1: Upgrade source_type for rows where include_type_desc=True
    # and source_type is still 'default' (they wanted type desc + default text)
    upgrade_sql = f"""
        UPDATE {mapping_table}
        SET source_type = 'properties_type'
        WHERE include_type_desc = TRUE
          AND source_type IN ('default', 'properties')
          AND source_type NOT IN ('type_description', 'properties_type')
    """

    if dry_run:
        # Count how many would be upgraded
        count_sql = f"""
            SELECT COUNT(*) FROM {mapping_table}
            WHERE include_type_desc = TRUE
              AND source_type IN ('default', 'properties')
              AND source_type NOT IN ('type_description', 'properties_type')
        """
        count = await conn.fetchval(count_sql)
        stats["upgraded"] = count
        logger.info("  %s: would upgrade %d rows, would drop column (dry-run)", space_id, count)
    else:
        result = await conn.execute(upgrade_sql)
        # Parse "UPDATE N"
        upgraded = int(result.split()[-1]) if result else 0
        stats["upgraded"] = upgraded

        if upgraded > 0:
            logger.info("  %s: upgraded %d rows (source_type → properties_type)", space_id, upgraded)

        # Step 2: Drop the column
        await conn.execute(f"ALTER TABLE {mapping_table} DROP COLUMN include_type_desc")
        stats["dropped"] = True
        logger.info("  %s: dropped include_type_desc column", space_id)

    return stats


# ── Main migration ────────────────────────────────────────────────────

async def migrate_drop_include_type_desc(
    conn: asyncpg.Connection,
    dry_run: bool = False,
) -> List[dict]:
    """Run the migration across all spaces.

    Args:
        conn: asyncpg connection.
        dry_run: If True, report only, make no changes.

    Returns:
        List of per-space stats dicts.
    """
    space_ids = await _get_all_space_ids(conn)
    logger.info("Found %d spaces to check", len(space_ids))

    all_stats = []
    for space_id in space_ids:
        stats = await _migrate_space(conn, space_id, dry_run=dry_run)
        all_stats.append(stats)

    # Summary
    migrated = [s for s in all_stats if not s["skipped"]]
    upgraded_total = sum(s["upgraded"] for s in all_stats)
    dropped_total = sum(1 for s in all_stats if s.get("dropped"))
    skipped_total = sum(1 for s in all_stats if s["skipped"])

    logger.info(
        "Migration complete: %d spaces migrated (%d rows upgraded, %d columns dropped), %d skipped",
        len(migrated), upgraded_total, dropped_total, skipped_total,
    )
    return all_stats


# ── Standalone runner ─────────────────────────────────────────────────

async def run_migration(
    dry_run: bool = False,
    dsn: str = None,
    **kwargs,
):
    """Connect and run the migration.

    Args:
        dry_run: If True, no changes applied.
        dsn: Optional full connection string.
        **kwargs: Connection params (host, port, database, user, password).
    """
    if dsn:
        conn = await asyncpg.connect(dsn)
    else:
        conn = await asyncpg.connect(**kwargs)

    try:
        if dry_run:
            await migrate_drop_include_type_desc(conn, dry_run=True)
        else:
            async with conn.transaction():
                await migrate_drop_include_type_desc(conn, dry_run=False)
    finally:
        await conn.close()


def main():
    """CLI entrypoint for running the migration standalone."""
    import argparse

    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(
        description="Drop deprecated include_type_desc column from search_mapping tables"
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
