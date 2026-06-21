"""
FTS decoupling migration (Phase 6D).

Migrates existing spaces from the coupled vector+FTS model (where FTS data
lives in ``_vec_`` tables) to the decoupled model (FTS in separate ``_fts_``
tables with shared ``search_mapping``).

Steps per space:

1. Copy ``vector_mapping`` rows to ``search_mapping`` (if not already present).
2. Copy ``vector_mapping_property`` rows to ``search_mapping_property``.
3. For each registered ``vector_index``:
   a. Register a matching ``fts_index`` entry (default: ``['english']``).
   b. Create the ``_fts_`` data table, indexes, and trigger.
   c. Copy ``(subject_uuid, context_uuid, search_text, tsv)`` from ``_vec_``
      to ``_fts_``, skipping rows without ``search_text``.
4. Drop ``search_text``, ``tsv`` columns and GIN FTS index from ``_vec_``
   tables (FTS now lives exclusively in ``_fts_`` tables).
5. Report summary statistics.

Idempotent — safe to re-run.  Uses ON CONFLICT DO NOTHING for all inserts.

Usage:
    python -m vitalgraph.db.migrations.migrate_fts_decoupling --database vitalgraph
    python -m vitalgraph.db.migrations.migrate_fts_decoupling --dsn "postgresql://..."
    python -m vitalgraph.db.migrations.migrate_fts_decoupling --database vitalgraph --dry-run
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import List, Optional

import asyncpg

from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────

async def _table_exists(conn: asyncpg.Connection, table_name: str) -> bool:
    """Check if a table exists."""
    result = await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = $1)",
        table_name,
    )
    return bool(result)


async def _column_exists(
    conn: asyncpg.Connection, table_name: str, column_name: str,
) -> bool:
    """Check if a column exists in a table."""
    result = await conn.fetchval(
        "SELECT EXISTS ("
        "  SELECT 1 FROM information_schema.columns "
        "  WHERE table_name = $1 AND column_name = $2"
        ")",
        table_name,
        column_name,
    )
    return bool(result)


async def _index_exists(conn: asyncpg.Connection, index_name: str) -> bool:
    """Check if a database index exists."""
    result = await conn.fetchval(
        "SELECT EXISTS ("
        "  SELECT 1 FROM pg_indexes WHERE indexname = $1"
        ")",
        index_name,
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
    """Migrate a single space to decoupled FTS.

    Returns a stats dict: {'mappings_copied', 'properties_copied',
    'fts_indexes_created', 'fts_rows_copied'}.
    """
    stats = {
        'mappings_copied': 0,
        'properties_copied': 0,
        'fts_indexes_created': 0,
        'fts_rows_copied': 0,
    }

    logger.info("  Migrating space: %s", space_id)

    # ── Step 1: Copy vector_mapping → search_mapping ──────────────

    vm_table = f"{space_id}_vector_mapping"
    sm_table = f"{space_id}_search_mapping"

    if not await _table_exists(conn, vm_table):
        logger.info("    No vector_mapping table — skipping mapping copy")
    elif not await _table_exists(conn, sm_table):
        logger.warning("    search_mapping table missing — run schema migration first")
    else:
        # Check which columns exist in vector_mapping to build column list
        vm_cols = [
            'mapping_type', 'type_uri', 'index_name',
        ]
        # Optional columns that may or may not exist in vector_mapping
        for col in ('enabled', 'source_type', 'separator',
                     'include_pred_name', 'include_type_desc'):
            if await _column_exists(conn, vm_table, col):
                vm_cols.append(col)

        cols_list = ', '.join(vm_cols)

        if dry_run:
            count = int(await conn.fetchval(f"SELECT COUNT(*) FROM {vm_table}") or 0)
            logger.info("    Would copy %d mapping rows: %s → %s", count, vm_table, sm_table)
            stats['mappings_copied'] = count
        else:
            # Insert only rows whose index_name doesn't already exist in search_mapping
            result = await conn.execute(f"""
                INSERT INTO {sm_table} ({cols_list})
                SELECT {cols_list} FROM {vm_table} vm
                WHERE NOT EXISTS (
                    SELECT 1 FROM {sm_table} sm
                    WHERE sm.index_name = vm.index_name
                    AND sm.mapping_type = vm.mapping_type
                    AND COALESCE(sm.type_uri, '') = COALESCE(vm.type_uri, '')
                )
            """)
            copied = int(result.split()[-1]) if result else 0
            stats['mappings_copied'] = copied
            if copied:
                logger.info("    Copied %d mapping rows → %s", copied, sm_table)
            else:
                logger.info("    search_mapping already populated — 0 new rows")

    # ── Step 2: Copy vector_mapping_property → search_mapping_property ─

    vmp_table = f"{space_id}_vector_mapping_property"
    smp_table = f"{space_id}_search_mapping_property"

    if (await _table_exists(conn, vmp_table)
            and await _table_exists(conn, smp_table)
            and await _table_exists(conn, vm_table)
            and await _table_exists(conn, sm_table)):

        if dry_run:
            count = int(await conn.fetchval(f"SELECT COUNT(*) FROM {vmp_table}") or 0)
            logger.info("    Would copy %d property rows: %s → %s", count, vmp_table, smp_table)
            stats['properties_copied'] = count
        else:
            # Map old mapping_ids to new ones by matching on index_name + mapping_type + type_uri
            result = await conn.execute(f"""
                INSERT INTO {smp_table} (mapping_id, property_uri, property_role, ordinal)
                SELECT sm.mapping_id, vmp.property_uri, vmp.property_role, vmp.ordinal
                FROM {vmp_table} vmp
                JOIN {vm_table} vm ON vmp.mapping_id = vm.mapping_id
                JOIN {sm_table} sm ON sm.index_name = vm.index_name
                    AND sm.mapping_type = vm.mapping_type
                    AND COALESCE(sm.type_uri, '') = COALESCE(vm.type_uri, '')
                ON CONFLICT (mapping_id, property_uri) DO NOTHING
            """)
            copied = int(result.split()[-1]) if result else 0
            stats['properties_copied'] = copied
            if copied:
                logger.info("    Copied %d property rows → %s", copied, smp_table)

    # ── Step 3: For each vector_index, create FTS index + copy data ─

    vi_table = f"{space_id}_vector_index"
    fi_table = f"{space_id}_fts_index"

    if not await _table_exists(conn, vi_table):
        logger.info("    No vector_index table — skipping FTS index creation")
        return stats
    if not await _table_exists(conn, fi_table):
        logger.warning("    fts_index table missing — run schema migration first")
        return stats

    indexes = await conn.fetch(
        f"SELECT index_name FROM {vi_table} ORDER BY index_name"
    )

    schema = SparqlSQLSchema()

    for row in indexes:
        index_name = row['index_name']
        vec_table = f"{space_id}_vec_{index_name}"
        fts_table = f"{space_id}_fts_{index_name}"
        languages = ['english']  # Default; can be updated later

        # 3a. Register FTS index
        existing = await conn.fetchval(
            f"SELECT index_name FROM {fi_table} WHERE index_name = $1",
            index_name,
        )
        if existing:
            logger.debug("    FTS index '%s' already registered", index_name)
        elif dry_run:
            logger.info("    Would register FTS index: %s", index_name)
            stats['fts_indexes_created'] += 1
        else:
            await conn.execute(
                f"INSERT INTO {fi_table} (index_name, languages) "
                f"VALUES ($1, $2) ON CONFLICT (index_name) DO NOTHING",
                index_name,
                languages,
            )
            stats['fts_indexes_created'] += 1
            logger.info("    Registered FTS index: %s", index_name)

        # 3b. Create FTS data table
        if await _table_exists(conn, fts_table):
            logger.debug("    FTS data table '%s' already exists", fts_table)
        elif dry_run:
            logger.info("    Would create FTS data table: %s", fts_table)
        else:
            for stmt in schema.create_fts_data_table_sql(space_id, index_name, languages):
                await conn.execute(stmt)
            logger.info("    Created FTS data table: %s", fts_table)

        # 3c. Copy search_text/tsv from vec table to fts table
        if not await _table_exists(conn, vec_table):
            logger.debug("    Vec table '%s' not found — skipping data copy", vec_table)
            continue

        # Check if vec table has search_text column
        if not await _column_exists(conn, vec_table, 'search_text'):
            logger.debug("    Vec table '%s' has no search_text — skipping", vec_table)
            continue

        if dry_run:
            count = int(await conn.fetchval(
                f"SELECT COUNT(*) FROM {vec_table} WHERE search_text IS NOT NULL"
            ) or 0)
            logger.info("    Would copy %d FTS rows: %s → %s", count, vec_table, fts_table)
            stats['fts_rows_copied'] += count
        else:
            # Disable trigger for bulk insert performance
            trigger_name = f"trg_{space_id}_fts_{index_name}_tsv"
            try:
                await conn.execute(
                    f"ALTER TABLE {fts_table} DISABLE TRIGGER {trigger_name}"
                )
            except Exception:
                pass  # Trigger may not exist yet

            # Copy data (ON CONFLICT to be idempotent)
            result = await conn.execute(f"""
                INSERT INTO {fts_table} (subject_uuid, context_uuid, search_text, tsv, updated_time)
                SELECT subject_uuid, context_uuid, search_text, tsv, updated_time
                FROM {vec_table}
                WHERE search_text IS NOT NULL
                ON CONFLICT (subject_uuid, context_uuid) DO NOTHING
            """)
            copied = int(result.split()[-1]) if result else 0
            stats['fts_rows_copied'] += copied

            # Re-enable trigger
            try:
                await conn.execute(
                    f"ALTER TABLE {fts_table} ENABLE TRIGGER {trigger_name}"
                )
            except Exception:
                pass

            if copied:
                logger.info("    Copied %d FTS rows: %s → %s", copied, vec_table, fts_table)
            else:
                logger.info("    FTS table '%s' already populated — 0 new rows", fts_table)

    # ── Step 4: Drop search_text/tsv columns and GIN FTS index from vec tables ─

    for row in indexes:
        index_name = row['index_name']
        vec_table = f"{space_id}_vec_{index_name}"

        if not await _table_exists(conn, vec_table):
            continue

        # Drop GIN FTS index
        fts_idx_name = f"idx_{space_id}_vec_{index_name}_fts"
        if dry_run:
            if await _index_exists(conn, fts_idx_name):
                logger.info("    Would drop GIN FTS index: %s", fts_idx_name)
                stats['vec_fts_indexes_dropped'] = stats.get('vec_fts_indexes_dropped', 0) + 1
        else:
            await conn.execute(f"DROP INDEX IF EXISTS {fts_idx_name}")

        # Drop tsv column first (depends on search_text via GENERATED ALWAYS)
        if await _column_exists(conn, vec_table, 'tsv'):
            if dry_run:
                logger.info("    Would drop column: %s.tsv", vec_table)
            else:
                await conn.execute(
                    f"ALTER TABLE {vec_table} DROP COLUMN IF EXISTS tsv"
                )
                logger.info("    Dropped column: %s.tsv", vec_table)

        # Drop search_text column
        if await _column_exists(conn, vec_table, 'search_text'):
            if dry_run:
                logger.info("    Would drop column: %s.search_text", vec_table)
            else:
                await conn.execute(
                    f"ALTER TABLE {vec_table} DROP COLUMN IF EXISTS search_text"
                )
                logger.info("    Dropped column: %s.search_text", vec_table)

    return stats


# ── Top-level migration ──────────────────────────────────────────────

async def migrate_fts_decoupling(
    conn: asyncpg.Connection,
    dry_run: bool = False,
) -> None:
    """Migrate all spaces to decoupled FTS.

    Prerequisite: run ``migrate_vector_geo_schema`` first to ensure the
    ``search_mapping``, ``search_mapping_property``, and ``fts_index``
    tables exist in every space.
    """
    mode = "DRY RUN" if dry_run else "LIVE"
    logger.info("Starting FTS decoupling migration (%s)...", mode)

    space_ids = await _get_all_space_ids(conn)
    logger.info("Found %d space(s) to migrate", len(space_ids))

    if not space_ids:
        logger.info("No spaces found. Nothing to migrate.")
        return

    total_stats = {
        'mappings_copied': 0,
        'properties_copied': 0,
        'fts_indexes_created': 0,
        'fts_rows_copied': 0,
    }

    for space_id in space_ids:
        space_stats = await _migrate_space(conn, space_id, dry_run=dry_run)
        for k in total_stats:
            total_stats[k] += space_stats[k]

    logger.info(
        "FTS decoupling migration %s complete. %d space(s) processed. "
        "mappings=%d, properties=%d, fts_indexes=%d, fts_rows=%d",
        mode,
        len(space_ids),
        total_stats['mappings_copied'],
        total_stats['properties_copied'],
        total_stats['fts_indexes_created'],
        total_stats['fts_rows_copied'],
    )


async def run_migration(
    dsn: Optional[str] = None,
    dry_run: bool = False,
    **kwargs,
) -> None:
    """Run migration using a DSN or connection parameters.

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
            await migrate_fts_decoupling(conn, dry_run=True)
        else:
            async with conn.transaction():
                await migrate_fts_decoupling(conn, dry_run=False)
    finally:
        await conn.close()


def main():
    """CLI entrypoint for running the migration standalone."""
    import argparse

    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(
        description="Migrate VitalGraph spaces to decoupled FTS (Phase 6D)"
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
