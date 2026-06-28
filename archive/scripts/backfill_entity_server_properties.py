#!/usr/bin/env python3
"""
Backfill missing server-managed properties on KG entities.

Connects directly to PostgreSQL (same pattern as vitalgraphadmin /
sync_fuzzy_index.py) and operates on the rdf_quad / term tables
without requiring the Jena sidecar.

Fills in default values for entities that are missing any of:
  - hasObjectCreationTime        (→ epoch sentinel 1970-01-01T00:00:00Z)
  - hasObjectModificationDateTime (→ now)
  - hasObjectStatusType           (→ ObjectStatusType_ACTIVE)
  - hasKGEntityType               (→ KGEntityType_KGEntity)

Only inserts quads that are actually missing — never overwrites existing
values.  Safe to run multiple times (idempotent).

Usage:
    # Backfill all graphs in a specific space:
    python scripts/backfill_entity_server_properties.py --space space_production

    # Backfill a specific graph in a space:
    python scripts/backfill_entity_server_properties.py --space space_production --graph urn:my_graph

    # Backfill all graphs in all spaces:
    python scripts/backfill_entity_server_properties.py --all-spaces

    # Dry run (count entities needing backfill without modifying):
    python scripts/backfill_entity_server_properties.py --space space_production --dry-run

    # Adjust batch size and delay:
    python scripts/backfill_entity_server_properties.py --space space_production --batch-size 500 --batch-delay 0.05

Environment variables (same as the service):
    DATABASE_URL                     PostgreSQL connection string (optional)
    VITALGRAPH_ENVIRONMENT           Environment name
    (or any VitalGraphConfig-compatible env vars)
"""

import argparse
import asyncio
import logging
import os
import sys
import time

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.kg_impl.kg_server_properties import (
    BackfillResult,
    backfill_entity_server_properties_sql,
    count_entities_needing_backfill_sql,
    discover_graphs_sql,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(name)s  %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('backfill_server_properties')


# ======================================================================
# Bootstrap — connect to PostgreSQL, list spaces from admin table
# ======================================================================

async def get_pool():
    """Create asyncpg pool from DATABASE_URL or VitalGraphConfig."""
    import asyncpg

    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        return await asyncpg.create_pool(database_url, min_size=1, max_size=4)

    try:
        from vitalgraph.config.config_loader import VitalGraphConfig
        config = VitalGraphConfig()
        db_config = config.get_database_config()
        return await asyncpg.create_pool(
            host=db_config.get('host', 'localhost'),
            port=int(db_config.get('port', 5432)),
            database=db_config.get('database', 'vitalgraph'),
            user=db_config.get('username', 'postgres'),
            password=db_config.get('password', ''),
            min_size=1, max_size=4,
        )
    except Exception as e:
        logger.error("No DATABASE_URL and VitalGraphConfig failed: %s", e)
        sys.exit(1)


async def list_space_ids(pool) -> list[str]:
    """Return all space_ids from the admin space table."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT space_id FROM space ORDER BY space_id")
    return [r['space_id'] for r in rows]


async def space_exists(pool, space_id: str) -> bool:
    """Check if a space exists."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM space WHERE space_id = $1)", space_id
        )


# ======================================================================
# Commands
# ======================================================================

async def cmd_dry_run(pool, space_ids, graph_id):
    """Count entities needing backfill without modifying anything."""
    grand_total = 0

    for sid in space_ids:
        if graph_id:
            graphs = [graph_id]
        else:
            graphs = await discover_graphs_sql(pool, sid)

        if not graphs:
            logger.info("  [%s] No graphs with KGEntity instances", sid)
            continue

        space_total = 0
        for gid in sorted(graphs):
            count = await count_entities_needing_backfill_sql(pool, sid, gid)
            if count > 0:
                logger.info("  [%s] %s — %d entities need backfill", sid, gid, count)
            space_total += count

        logger.info("  [%s] Total: %d entities need backfill", sid, space_total)
        grand_total += space_total

    logger.info("Grand total: %d entities need backfill across %d space(s)",
                grand_total, len(space_ids))


async def cmd_backfill(pool, space_ids, graph_id, batch_size, batch_delay):
    """Run the backfill."""
    all_results: list[BackfillResult] = []
    t0 = time.monotonic()

    for sid in space_ids:
        if graph_id:
            graphs = [graph_id]
        else:
            graphs = await discover_graphs_sql(pool, sid)

        if not graphs:
            logger.info("  [%s] No graphs with KGEntity instances", sid)
            continue

        for gid in sorted(graphs):
            count = await count_entities_needing_backfill_sql(pool, sid, gid)
            if count == 0:
                logger.info("  [%s] %s — already complete", sid, gid)
                continue

            logger.info("  [%s] %s — %d entities to backfill ...", sid, gid, count)
            result = await backfill_entity_server_properties_sql(
                pool, sid, gid,
                batch_size=batch_size,
                batch_delay=batch_delay,
            )
            all_results.append(result)
            logger.info("  [%s] %s — patched %d entities (%d errors)",
                        sid, gid, result.entities_patched, result.errors)

    elapsed = time.monotonic() - t0
    total_patched = sum(r.entities_patched for r in all_results)
    total_errors = sum(r.errors for r in all_results)

    logger.info("=" * 60)
    logger.info("Backfill complete in %.1fs", elapsed)
    logger.info("  Spaces processed:   %d", len(space_ids))
    logger.info("  Graphs processed:   %d", len(all_results))
    logger.info("  Entities patched:   %d", total_patched)
    logger.info("  Errors:             %d", total_errors)
    logger.info("=" * 60)

    if total_errors > 0:
        sys.exit(1)


# ======================================================================
# Main
# ======================================================================

async def main():
    parser = argparse.ArgumentParser(
        description='Backfill missing server-managed properties on KG entities.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--space', type=str, default=None,
                        help='Space ID to backfill')
    parser.add_argument('--graph', type=str, default=None,
                        help='Specific graph ID to backfill (default: all graphs in space)')
    parser.add_argument('--all-spaces', action='store_true',
                        help='Iterate over all spaces')
    parser.add_argument('--dry-run', action='store_true',
                        help='Count entities needing backfill without modifying')
    parser.add_argument('--batch-size', type=int, default=200,
                        help='Entities per batch (default: 200)')
    parser.add_argument('--batch-delay', type=float, default=0.1,
                        help='Seconds between batches (default: 0.1)')
    args = parser.parse_args()

    if not args.space and not args.all_spaces:
        parser.error("Either --space or --all-spaces is required")

    pool = await get_pool()
    logger.info("Connected to PostgreSQL (pool size: %d)", pool.get_size())

    try:
        # Resolve space_ids
        if args.all_spaces:
            space_ids = await list_space_ids(pool)
            logger.info("Found %d space(s)", len(space_ids))
        else:
            if not await space_exists(pool, args.space):
                logger.error("Space '%s' not found", args.space)
                sys.exit(1)
            space_ids = [args.space]

        if args.dry_run:
            await cmd_dry_run(pool, space_ids, args.graph)
        else:
            await cmd_backfill(pool, space_ids, args.graph,
                               args.batch_size, args.batch_delay)
    finally:
        await pool.close()


if __name__ == '__main__':
    asyncio.run(main())
