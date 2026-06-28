#!/usr/bin/env python3
"""
Standalone bulk sync of the entity fuzzy index to MemoryDB.

Run this locally (or from a bastion host) to populate the fuzzy index from
PostgreSQL. The VitalGraph service instances do NOT run bulk init at startup —
they rely on the data already present in MemoryDB and only apply incremental
updates. This script is the sole mechanism for full (re)population.

Usage:
    # Full sync (clears + rebuilds entire index):
    python scripts/sync_fuzzy_index.py --full

    # Full sync, rate-limited (0.1s pause between batches):
    python scripts/sync_fuzzy_index.py --full --batch-delay 0.1

    # Full sync with 4 parallel workers (best for multi-shard clusters):
    python scripts/sync_fuzzy_index.py --full --workers 4

    # Incremental sync (only entities updated since N hours ago):
    python scripts/sync_fuzzy_index.py --since-hours 24

    # Check current index stats without modifying anything:
    python scripts/sync_fuzzy_index.py --status

    # Compare PG fuzzy_hash vs Redis hashes (read-only check):
    python scripts/sync_fuzzy_index.py --check

    # Backfill NULL fuzzy_hash values in PostgreSQL:
    python scripts/sync_fuzzy_index.py --backfill

    # Clear index (delete all keys):
    python scripts/sync_fuzzy_index.py --clear

Environment variables (same as the service):
    ENTITY_FUZZY_REDIS_HOST          MemoryDB cluster endpoint
    ENTITY_FUZZY_REDIS_PORT          Port (default 6379)
    ENTITY_FUZZY_REDIS_USER          Redis ACL user
    ENTITY_FUZZY_REDIS_PASSWORD      Redis ACL password
    ENTITY_FUZZY_REDIS_CLUSTER       Set to 'true' for cluster mode
    ENTITY_FUZZY_REDIS_SSL           Set to 'true' for TLS
    VITALGRAPH_ENVIRONMENT           Environment name (e.g. 'prod')
    DATABASE_URL                     PostgreSQL connection string
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import asyncpg

from vitalgraph.entity_registry.datasketch_cluster import register_cluster_storage
from vitalgraph.entity_registry.entity_fuzzy import EntityFuzzyIndex, compute_fuzzy_hash

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(name)s  %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('sync_fuzzy_index')


async def get_pool() -> asyncpg.Pool:
    """Create asyncpg connection pool from DATABASE_URL or VitalGraphConfig."""
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        return await asyncpg.create_pool(database_url, min_size=1, max_size=2)
    # Fallback: use VitalGraphConfig (same as migrate.py / the service)
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
            min_size=1, max_size=2,
        )
    except Exception as e:
        logger.error(f"No DATABASE_URL and VitalGraphConfig failed: {e}")
        sys.exit(1)


async def get_entity_count(pool: asyncpg.Pool) -> int:
    """Get total active entity count from PostgreSQL."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM entity WHERE status != 'deleted'"
        )


async def get_redis_key_count(idx: EntityFuzzyIndex) -> int:
    """Count keys in MemoryDB for this index."""
    client = idx._get_redis_client()
    if not client:
        return 0
    tag_prefix = idx.storage_config.get('hash_tag_prefix', '')
    patterns = []
    basename = idx.storage_config.get('basename', b'fuzzy')
    if isinstance(basename, str):
        basename = basename.encode()
    patterns.append(basename + b'*')
    if tag_prefix:
        for pfx in [tag_prefix, tag_prefix + '_ph']:
            patterns.append(f'{{{pfx}_b*'.encode())
            patterns.append(f'{{{pfx}_keys}}*'.encode())
    total = 0
    for pattern in patterns:
        for _ in client.scan_iter(match=pattern, count=500):
            total += 1
    return total


async def cmd_status(idx: EntityFuzzyIndex, pool: asyncpg.Pool):
    """Print index status without modifying anything."""
    pg_count = await get_entity_count(pool)
    redis_keys = await get_redis_key_count(idx)
    logger.info(f"PostgreSQL: {pg_count:,} active entities")
    logger.info(f"MemoryDB:   {redis_keys:,} Redis keys")
    if redis_keys > 0:
        # Rough estimate: ~76 keys per entity variant, ~1.5 variants
        est_entities = redis_keys / (76 * 1.5 * 2)
        logger.info(f"  (estimated ~{est_entities:,.0f} entities indexed)")
    else:
        logger.info("  Index is empty — run --full to populate")


async def cmd_clear(idx: EntityFuzzyIndex):
    """Clear all index data from MemoryDB."""
    logger.info("Clearing fuzzy index...")
    idx.clear_index()
    logger.info("Done — index cleared")


async def cmd_full_sync(idx: EntityFuzzyIndex, pool: asyncpg.Pool,
                        batch_delay: float, batch_size: int,
                        num_workers: int, no_clear: bool = False):
    """Full sync: clear index and rebuild from all active entities."""
    pg_count = await get_entity_count(pool)
    logger.info(f"Full sync: {pg_count:,} entities in PostgreSQL")
    logger.info(f"  batch_size={batch_size}, batch_delay={batch_delay}s, workers={num_workers}")

    if no_clear:
        logger.info("Skipping clear (--no-clear): rebuilding on top of existing data")
    else:
        # Clear existing data
        logger.info("Clearing existing index data...")
        idx.clear_index()

    # Rebuild
    logger.info("Starting bulk sync...")
    start = time.time()
    count = await idx.initialize(pool, batch_delay=batch_delay,
                                 num_workers=num_workers)
    elapsed = time.time() - start
    rate = count / elapsed if elapsed > 0 else 0
    logger.info(f"Full sync complete: {count:,} entities in {elapsed:.1f}s ({rate:.0f}/s)")


async def cmd_check(idx: EntityFuzzyIndex, pool: asyncpg.Pool):
    """Compare PG fuzzy_hash values vs Redis HASH values.

    Reports:
    - Total entities in PG vs Redis
    - Missing from Redis (need insert)
    - Stale in Redis (need removal)
    - Hash mismatches (need re-index)
    - Entities with NULL hash in PG (need backfill)
    """
    logger.info("Comparing PostgreSQL fuzzy_hash vs MemoryDB...")
    start = time.time()

    # 1. Load PG hashes
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT e.entity_id, e.fuzzy_hash, et.type_key "
            "FROM entity e JOIN entity_type et ON e.entity_type_id = et.type_id "
            "WHERE e.status != 'deleted'"
        )
    pg_hashes = {}    # entity_id -> fuzzy_hash
    null_hash_count = 0
    for row in rows:
        eid = row['entity_id']
        h = row['fuzzy_hash']
        if h is None:
            null_hash_count += 1
        pg_hashes[eid] = h

    # 2. Load Redis hashes
    client = idx._get_redis_client()
    if not client:
        logger.error("No Redis client available")
        return
    hash_key = idx._fuzzy_hash_key()
    redis_raw = client.hgetall(hash_key)
    redis_hashes = {}
    for k, v in redis_raw.items():
        eid = k.decode() if isinstance(k, bytes) else k
        hval = v.decode() if isinstance(v, bytes) else v
        redis_hashes[eid] = hval

    # 3. Compute diff
    pg_ids = set(pg_hashes.keys())
    redis_ids = set(redis_hashes.keys())

    missing_from_redis = pg_ids - redis_ids
    stale_in_redis = redis_ids - pg_ids
    common = pg_ids & redis_ids
    mismatched = set()
    for eid in common:
        pg_h = pg_hashes[eid]
        if pg_h is None:
            continue  # can't compare if PG hash is NULL
        if pg_h != redis_hashes[eid]:
            mismatched.add(eid)

    elapsed = time.time() - start

    # 4. Report
    logger.info(f"Comparison complete in {elapsed:.1f}s")
    logger.info(f"  PostgreSQL:       {len(pg_hashes):>8,} active entities")
    logger.info(f"  Redis hash map:   {len(redis_hashes):>8,} entries")
    logger.info(f"  ─────────────────────────────────")
    if null_hash_count:
        logger.info(f"  PG NULL hashes:   {null_hash_count:>8,}  (need backfill)")
    logger.info(f"  Missing from Redis: {len(missing_from_redis):>6,}  (need insert)")
    logger.info(f"  Stale in Redis:     {len(stale_in_redis):>6,}  (need removal)")
    logger.info(f"  Hash mismatches:    {len(mismatched):>6,}  (need re-index)")

    total_issues = len(missing_from_redis) + len(stale_in_redis) + len(mismatched) + null_hash_count
    if total_issues == 0:
        logger.info("  ✅ All hashes match — PG and Redis are in sync")
    else:
        logger.info(f"  ⚠️  {total_issues:,} total issues found")
        if null_hash_count:
            logger.info("  Run --backfill to populate NULL fuzzy_hash values in PG")
        if missing_from_redis or mismatched:
            logger.info("  Run --full to rebuild the index")

    # Show a few sample entity IDs for each category
    for label, id_set in [
        ('Missing from Redis', missing_from_redis),
        ('Stale in Redis', stale_in_redis),
        ('Hash mismatch', mismatched),
    ]:
        if id_set:
            sample = sorted(id_set)[:5]
            logger.info(f"  {label} (sample): {', '.join(sample)}")


async def cmd_backfill_hashes(pool: asyncpg.Pool, batch_size: int = 1000):
    """Backfill fuzzy_hash for entities that have NULL hash in PostgreSQL.

    Uses a single streaming query (entities LEFT JOIN aliases) and batched
    UPDATE statements for efficient bulk processing of 1M+ entities.
    """
    logger.info("Backfilling fuzzy_hash for entities with NULL hash...")
    start = time.time()
    count = 0

    # Single query: entities with NULL hash LEFT JOIN their aliases
    sql = (
        "SELECT e.entity_id, e.primary_name, e.country, e.region, e.locality, "
        "et.type_key, ea.alias_name "
        "FROM entity e "
        "JOIN entity_type et ON et.type_id = e.entity_type_id "
        "LEFT JOIN entity_alias ea ON ea.entity_id = e.entity_id "
        "AND ea.status != 'retracted' "
        "WHERE e.fuzzy_hash IS NULL AND e.status != 'deleted' "
        "ORDER BY e.entity_id"
    )

    update_batch = []  # [(hash, entity_id), ...]
    current_eid = None
    current_entity = None

    async with pool.acquire() as conn:
        async with conn.transaction():
            cursor = await conn.cursor(sql)

            while True:
                rows = await cursor.fetch(5000)
                if not rows:
                    break

                for row in rows:
                    eid = row['entity_id']
                    if eid != current_eid:
                        # Flush previous entity
                        if current_eid is not None:
                            h = compute_fuzzy_hash(current_entity)
                            update_batch.append((h, current_eid))
                            count += 1

                            # Flush batch
                            if len(update_batch) >= batch_size:
                                await conn.executemany(
                                    "UPDATE entity SET fuzzy_hash = $1 WHERE entity_id = $2",
                                    update_batch
                                )
                                update_batch.clear()
                                if count % 10000 == 0:
                                    elapsed = time.time() - start
                                    rate = count / elapsed if elapsed > 0 else 0
                                    logger.info(f"  Backfilled {count:,} entities ({rate:.0f}/s)")

                        current_eid = eid
                        current_entity = {
                            'type_key': row['type_key'],
                            'primary_name': row['primary_name'],
                            'country': row['country'],
                            'region': row['region'],
                            'locality': row['locality'],
                            'aliases': [],
                        }

                    alias_name = row['alias_name']
                    if alias_name:
                        current_entity['aliases'].append({'alias_name': alias_name})

            # Flush last entity + remaining batch
            if current_eid is not None:
                h = compute_fuzzy_hash(current_entity)
                update_batch.append((h, current_eid))
                count += 1
            if update_batch:
                await conn.executemany(
                    "UPDATE entity SET fuzzy_hash = $1 WHERE entity_id = $2",
                    update_batch
                )

    elapsed = time.time() - start
    rate = count / elapsed if elapsed > 0 else 0
    logger.info(f"Backfill complete: {count:,} entities in {elapsed:.1f}s ({rate:.0f}/s)")


async def cmd_incremental_sync(idx: EntityFuzzyIndex, pool: asyncpg.Pool,
                               since_hours: float, batch_delay: float,
                               num_workers: int):
    """Incremental sync: only entities updated since N hours ago."""
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    logger.info(f"Incremental sync: entities updated since {since.isoformat()}")

    start = time.time()
    count = await idx.initialize(pool, since=since, batch_delay=batch_delay,
                                 num_workers=num_workers)
    elapsed = time.time() - start
    rate = count / elapsed if elapsed > 0 else 0
    logger.info(f"Incremental sync complete: {count:,} entities in {elapsed:.1f}s ({rate:.0f}/s)")


async def main():
    parser = argparse.ArgumentParser(
        description='Sync entity fuzzy index to MemoryDB',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--full', action='store_true',
                       help='Full sync: clear + rebuild entire index')
    group.add_argument('--since-hours', type=float,
                       help='Incremental sync: only entities updated in last N hours')
    group.add_argument('--status', action='store_true',
                       help='Show index status without modifying')
    group.add_argument('--clear', action='store_true',
                       help='Clear all index data')
    group.add_argument('--check', action='store_true',
                       help='Compare PG fuzzy_hash vs Redis hashes (read-only)')
    group.add_argument('--backfill', action='store_true',
                       help='Backfill NULL fuzzy_hash values in PostgreSQL')

    parser.add_argument('--batch-delay', type=float, default=0.05,
                        help='Seconds to pause between batch flushes (default: 0.05)')
    parser.add_argument('--batch-size', type=int, default=1000,
                        help='Entities per pipeline flush (default: 1000)')
    parser.add_argument('--workers', type=int, default=4,
                        help='Parallel worker threads for batch processing (default: 4)')
    parser.add_argument('--no-clear', action='store_true',
                        help='Skip clearing index before --full sync (rebuild on top of existing data)')
    args = parser.parse_args()

    # Initialize fuzzy index from env
    from vitalgraph.config.config_loader import get_scoped_env
    use_cluster = get_scoped_env('ENTITY_FUZZY_REDIS_CLUSTER', 'false').lower() in ('true', '1', 'yes')
    if use_cluster:
        register_cluster_storage()

    idx = EntityFuzzyIndex.from_env()
    if not idx.storage_config:
        logger.error("No Redis/MemoryDB backend configured. Set ENTITY_FUZZY_BACKEND=redis")
        sys.exit(1)

    pool = await get_pool()

    try:
        if args.status:
            await cmd_status(idx, pool)
        elif args.check:
            await cmd_check(idx, pool)
        elif args.backfill:
            await cmd_backfill_hashes(pool)
        elif args.clear:
            await cmd_clear(idx)
        elif args.full:
            await cmd_full_sync(idx, pool, args.batch_delay, args.batch_size,
                                args.workers, no_clear=args.no_clear)
        elif args.since_hours is not None:
            await cmd_incremental_sync(idx, pool, args.since_hours,
                                       args.batch_delay, args.workers)
    finally:
        await pool.close()


if __name__ == '__main__':
    asyncio.run(main())
