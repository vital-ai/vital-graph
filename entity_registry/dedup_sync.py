#!/usr/bin/env python3
"""
Dedup Index Sync Script for Entity Registry.

Syncs entity data from PostgreSQL to the persistent dedup index
(Redis / AWS MemoryDB). For the in-memory backend this is a no-op
since that index rebuilds automatically on service startup.

Usage:
    python entity_registry/dedup_sync.py --full
    python entity_registry/dedup_sync.py --entity-id e_abc123
    python entity_registry/dedup_sync.py --full --dry-run
    python entity_registry/dedup_sync.py --status
    python entity_registry/dedup_sync.py --check
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

import asyncpg

from vitalgraph.entity_registry.entity_dedup import EntityDedupIndex

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)


async def create_pool() -> asyncpg.Pool:
    """Create an asyncpg connection pool from env vars."""
    return await asyncpg.create_pool(
        host=os.getenv('DATABASE_HOST', 'localhost'),
        port=int(os.getenv('DATABASE_PORT', '5432')),
        database=os.getenv('DATABASE_NAME', 'vitalgraph'),
        user=os.getenv('DATABASE_USERNAME', 'vitalgraph_user'),
        password=os.getenv('DATABASE_PASSWORD', 'vitalgraph_pass'),
        min_size=1,
        max_size=5,
    )


def _parse_since(value: str):
    """Parse a --since value into a datetime.

    Accepts:
        - Relative: '1h', '30m', '7d', '2w' (hours, minutes, days, weeks)
        - ISO 8601: '2025-01-15T00:00:00'
    """
    from datetime import datetime, timedelta, timezone
    import re

    # Relative time patterns
    match = re.fullmatch(r'(\d+)([mhdw])', value.strip().lower())
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        delta = {
            'm': timedelta(minutes=amount),
            'h': timedelta(hours=amount),
            'd': timedelta(days=amount),
            'w': timedelta(weeks=amount),
        }[unit]
        return datetime.now(timezone.utc) - delta

    # Try ISO format
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        raise ValueError(f"Cannot parse --since value: {value!r}. "
                         f"Use relative (e.g. '1h', '7d') or ISO 8601.")


async def show_status(dedup_index: EntityDedupIndex, pool: asyncpg.Pool):
    """Show current dedup index status."""
    async with pool.acquire() as conn:
        pg_count = await conn.fetchval(
            "SELECT COUNT(*) FROM entity WHERE status = 'active'"
        )

    backend = 'redis' if dedup_index.storage_config else 'memory'
    print("=" * 60)
    print("Dedup Index Status")
    print("=" * 60)
    print(f"  Backend:           {backend}")
    print(f"  Entities indexed:  {dedup_index.entity_count:,}")
    print(f"  PostgreSQL active: {pg_count:,}")
    print(f"  Initialized:       {dedup_index._initialized}")
    print(f"  Num permutations:  {dedup_index.num_perm}")
    print(f"  LSH threshold:     {dedup_index.threshold}")
    print(f"  Shingle k:         {dedup_index.shingle_k}")

    if backend == 'memory':
        print()
        print("  ℹ️  In-memory backend — index rebuilds on every service start.")
        print("     Use ENTITY_DEDUP_BACKEND=redis for persistent storage.")


async def check_consistency(dedup_index: EntityDedupIndex, pool: asyncpg.Pool):
    """Verify dedup index matches PostgreSQL."""
    async with pool.acquire() as conn:
        pg_count = await conn.fetchval(
            "SELECT COUNT(*) FROM entity WHERE status = 'active'"
        )

    dedup_count = dedup_index.entity_count

    print("=" * 60)
    print("Dedup Index Consistency Check")
    print("=" * 60)
    print(f"  PostgreSQL active entities: {pg_count:,}")
    print(f"  Dedup index entities:       {dedup_count:,}")
    if pg_count == dedup_count:
        print("  ✅ Counts match")
    else:
        diff = abs(pg_count - dedup_count)
        print(f"  ⚠️  Mismatch: {diff:,} difference")
        print("  Run with --full to re-sync")


async def full_sync(dedup_index: EntityDedupIndex, pool: asyncpg.Pool,
                     dry_run: bool = False, since=None):
    """Full or incremental sync: PostgreSQL → dedup index."""
    mode = 'incremental' if since else 'full'
    logger.info("=" * 60)
    logger.info(f"Dedup Index {mode.title()} Sync")
    logger.info("=" * 60)

    backend = 'redis' if dedup_index.storage_config else 'memory'
    logger.info(f"Backend: {backend}")

    if dry_run:
        logger.info("DRY RUN — no changes will be made")

    async with pool.acquire() as conn:
        if since:
            pg_count = await conn.fetchval(
                "SELECT COUNT(*) FROM entity WHERE status = 'active' AND updated_time >= $1",
                since
            )
        else:
            pg_count = await conn.fetchval(
                "SELECT COUNT(*) FROM entity WHERE status = 'active'"
            )
    logger.info(f"PostgreSQL entities to sync: {pg_count:,}")
    if since:
        logger.info(f"Since: {since}")
    logger.info(f"Current index count: {dedup_index.entity_count:,}")

    if dry_run:
        logger.info(f"Would sync {pg_count:,} entities to dedup index")
        return

    count = await dedup_index.initialize(pool, since=since)

    logger.info("=" * 60)
    logger.info(f"Sync complete: {count:,} entities indexed")
    logger.info("=" * 60)


async def rebuild_sync(dedup_index: EntityDedupIndex, pool: asyncpg.Pool,
                        dry_run: bool = False):
    """Rebuild: wipe the index completely, then populate from PostgreSQL.

    Faster than --full for large datasets because it skips per-entity
    remove-then-insert — every insert goes into a clean index.
    """
    logger.info("=" * 60)
    logger.info("Dedup Index REBUILD (wipe + fresh load)")
    logger.info("=" * 60)

    backend = 'redis' if dedup_index.storage_config else 'memory'
    logger.info(f"Backend: {backend}")

    async with pool.acquire() as conn:
        pg_count = await conn.fetchval(
            "SELECT COUNT(*) FROM entity WHERE status = 'active'"
        )
    logger.info(f"PostgreSQL active entities: {pg_count:,}")
    logger.info(f"Current index count: {dedup_index.entity_count:,}")

    if dry_run:
        logger.info(f"DRY RUN — would wipe index and rebuild with {pg_count:,} entities")
        return

    # Wipe
    dedup_index.clear_index()
    logger.info("Index cleared — rebuilding from scratch...")

    # Fresh load (since=None, no stale detection needed on empty index)
    count = await dedup_index.initialize(pool)

    logger.info("=" * 60)
    logger.info(f"Rebuild complete: {count:,} entities indexed")
    logger.info("=" * 60)


async def single_entity_sync(dedup_index: EntityDedupIndex, pool: asyncpg.Pool,
                              entity_id: str, dry_run: bool = False):
    """Sync a single entity to the dedup index."""
    logger.info(f"Syncing entity: {entity_id}")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT e.entity_id, e.primary_name, e.country, e.region, "
            "e.locality, e.status "
            "FROM entity e WHERE e.entity_id = $1",
            entity_id,
        )
        if not row:
            logger.error(f"Entity not found: {entity_id}")
            return

        entity = dict(row)

        # Fetch aliases
        alias_rows = await conn.fetch(
            "SELECT alias_name FROM entity_alias "
            "WHERE entity_id = $1 AND status != 'retracted'",
            entity_id,
        )
        entity['aliases'] = [{'alias_name': r['alias_name']} for r in alias_rows]

    if dry_run:
        logger.info(f"DRY RUN — would sync entity {entity_id}:")
        logger.info(f"  primary_name: {entity['primary_name']}")
        logger.info(f"  country: {entity.get('country')}")
        logger.info(f"  aliases: {len(entity['aliases'])}")
        return

    if entity.get('status') == 'deleted':
        dedup_index.remove_entity(entity_id)
        logger.info(f"Removed {entity_id} from dedup index (entity is deleted)")
    else:
        dedup_index.add_entity(entity_id, entity)
        logger.info(f"Upserted {entity_id} to dedup index")


async def main():
    parser = argparse.ArgumentParser(
        prog='dedup_sync',
        description='Sync Entity Registry dedup index (Redis / MemoryDB)',
    )
    parser.add_argument('--full', action='store_true',
                        help='Full sync (upsert + stale cleanup)')
    parser.add_argument('--rebuild', action='store_true',
                        help='Wipe index and rebuild from scratch (fastest for large datasets)')
    parser.add_argument('--entity-id',
                        help='Sync a single entity by ID')
    parser.add_argument('--since',
                        help='Incremental sync: ISO datetime or relative like "1h", "30m", "7d"')
    parser.add_argument('--status', action='store_true',
                        help='Show dedup index status')
    parser.add_argument('--check', action='store_true',
                        help='Check consistency between PostgreSQL and index')
    parser.add_argument('--dry-run', action='store_true',
                        help='Report what would change without modifying')
    args = parser.parse_args()

    if not any([args.full, args.rebuild, args.entity_id, args.since, args.status, args.check]):
        parser.error("Must specify --full, --rebuild, --entity-id, --since, --status, or --check")

    # Create dedup index
    dedup_index = EntityDedupIndex.from_env()
    backend = 'redis' if dedup_index.storage_config else 'memory'

    if backend == 'memory' and (args.full or args.rebuild or args.entity_id):
        logger.warning(
            "Running with in-memory backend. Changes will not persist "
            "after this script exits. Set ENTITY_DEDUP_BACKEND=redis "
            "for persistent storage."
        )

    # Connect to PostgreSQL
    pool = await create_pool()

    try:
        # For status/check, initialize the index first to load current state
        since_dt = _parse_since(args.since) if args.since else None

        if args.status or args.check:
            await dedup_index.initialize(pool)

            if args.status:
                await show_status(dedup_index, pool)
            if args.check:
                await check_consistency(dedup_index, pool)
        elif args.rebuild:
            await rebuild_sync(dedup_index, pool, dry_run=args.dry_run)
        elif args.full or args.since:
            await full_sync(dedup_index, pool, dry_run=args.dry_run,
                            since=since_dt)
        elif args.entity_id:
            # Initialize first so we can update incrementally
            await dedup_index.initialize(pool)
            await single_entity_sync(dedup_index, pool, args.entity_id,
                                      dry_run=args.dry_run)
    finally:
        await pool.close()


if __name__ == '__main__':
    asyncio.run(main())
