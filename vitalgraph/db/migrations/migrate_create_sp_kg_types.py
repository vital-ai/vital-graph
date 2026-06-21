"""
Create the centralized ``sp_kg_types`` system space.

This migration bootstraps the system space used for centralized KG Type
definitions.  All KG Type objects (KGEntityType, KGFrameType, KGSlotType,
KGRelationType) are stored in this single space rather than per-space.

Steps:

1. Check if ``sp_kg_types`` already exists in the ``space`` table.
2. If not:
   a. Insert the space row.
   b. Create all per-space tables via ``SparqlSQLSchema.create_space()``.
   c. Run ``setup_kgtype_search()`` to create vector index, FTS index,
      and search mappings for KG Type search.
3. Report result.

Idempotent — safe to re-run.  If the space already exists, skips.

Usage:
    python -m vitalgraph.db.migrations.migrate_create_sp_kg_types --database sparql_sql_graph
    python -m vitalgraph.db.migrations.migrate_create_sp_kg_types --dsn "postgresql://..."
    python -m vitalgraph.db.migrations.migrate_create_sp_kg_types --database sparql_sql_graph --dry-run
"""

from __future__ import annotations

import asyncio
import logging
import sys

import asyncpg

logger = logging.getLogger(__name__)

SP_KG_TYPES = "sp_kg_types"


# ── Core migration ────────────────────────────────────────────────────

async def migrate_create_sp_kg_types(
    conn: asyncpg.Connection,
    *,
    dry_run: bool = False,
) -> dict:
    """Create the sp_kg_types system space if it doesn't exist.

    Returns a dict with keys: space_id, created, skipped.
    """
    # Check if space already exists
    exists = await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM space WHERE space_id = $1)",
        SP_KG_TYPES,
    )

    if exists:
        logger.info("Space '%s' already exists — skipping", SP_KG_TYPES)
        return {"space_id": SP_KG_TYPES, "created": False, "skipped": True}

    if dry_run:
        logger.info("[DRY RUN] Would create space '%s' with tables and search infra", SP_KG_TYPES)
        return {"space_id": SP_KG_TYPES, "created": False, "skipped": False}

    # 1. Insert space row
    await conn.execute(
        """INSERT INTO space (space_id, space_name, space_description, update_time)
           VALUES ($1, $2, $3, NOW())
           ON CONFLICT (space_id) DO NOTHING""",
        SP_KG_TYPES,
        "KG Types",
        "System space for centralized KG Type definitions",
    )
    logger.info("Inserted space row: %s", SP_KG_TYPES)

    # 2. Create per-space tables (quads, terms, indexes, etc.)
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    await SparqlSQLSchema.create_space(conn, SP_KG_TYPES)
    logger.info("Created per-space tables for: %s", SP_KG_TYPES)

    # 3. Bootstrap KG Type search infrastructure (vector index + FTS + mappings)
    from vitalgraph.kg_impl.kgtype_index_setup import setup_kgtype_search
    ok = await setup_kgtype_search(conn, SP_KG_TYPES)
    if ok:
        logger.info("KG Type search infra created for: %s", SP_KG_TYPES)
    else:
        logger.warning("KG Type search infra setup returned False for: %s", SP_KG_TYPES)

    logger.info("✅ System space '%s' created successfully", SP_KG_TYPES)
    return {"space_id": SP_KG_TYPES, "created": True, "skipped": False}


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
            await migrate_create_sp_kg_types(conn, dry_run=True)
        else:
            async with conn.transaction():
                await migrate_create_sp_kg_types(conn, dry_run=False)
    finally:
        await conn.close()


def main():
    """CLI entrypoint for running the migration standalone."""
    import argparse

    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(
        description="Create the centralized sp_kg_types system space"
    )
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--database", default="sparql_sql_graph")
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
