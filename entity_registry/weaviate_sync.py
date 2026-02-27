#!/usr/bin/env python3
"""
Weaviate Sync Script for Entity Registry.

Syncs entity data from PostgreSQL to the Weaviate EntityIndex collection.

Usage:
    python entity_registry/weaviate_sync.py --full
    python entity_registry/weaviate_sync.py --entity-id e_abc123
    python entity_registry/weaviate_sync.py --full --dry-run
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

from vitalgraph.entity_registry.entity_weaviate import EntityWeaviateIndex

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


async def full_sync(weaviate_index: EntityWeaviateIndex, pool: asyncpg.Pool,
                     dry_run: bool = False, batch_size: int = 100, since=None,
                     entity_vectors=None, location_vectors=None):
    """Full or incremental sync: PostgreSQL → Weaviate."""
    mode = 'incremental' if since else 'full'
    logger.info("=" * 60)
    logger.info(f"Weaviate {mode.title()} Sync")
    logger.info("=" * 60)

    if dry_run:
        logger.info("DRY RUN — no changes will be made")

    # Count entities in PostgreSQL
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

    # Get Weaviate status
    status = await weaviate_index.get_status()
    logger.info(f"Weaviate collection exists: {status.get('exists')}")
    logger.info(f"Weaviate object count: {status.get('object_count', 0):,}")

    if dry_run:
        logger.info(f"Would sync {pg_count:,} entities to Weaviate")
        return

    await weaviate_index.ensure_collection()

    if entity_vectors:
        logger.info(f"Using {len(entity_vectors):,} pre-computed entity vectors")
    upserted, deleted = await weaviate_index.full_sync(
        pool, batch_size=batch_size, since=since,
        entity_vectors=entity_vectors,
    )
    logger.info(f"Entities: {upserted:,} upserted, {deleted:,} deleted")

    if location_vectors:
        logger.info(f"Using {len(location_vectors):,} pre-computed location vectors")
    loc_upserted, loc_deleted = await weaviate_index.location_sync(
        pool, batch_size=batch_size * 2, since=since,
        location_vectors=location_vectors,
    )
    logger.info(f"Locations: {loc_upserted:,} upserted, {loc_deleted:,} deleted")

    logger.info("=" * 60)
    logger.info(f"Sync complete: {upserted + loc_upserted:,} upserted, "
                f"{deleted + loc_deleted:,} deleted")
    logger.info("=" * 60)


async def rebuild_sync(weaviate_index: EntityWeaviateIndex, pool: asyncpg.Pool,
                        dry_run: bool = False, batch_size: int = 100,
                        entity_vectors=None, location_vectors=None):
    """Rebuild: drop the collection and recreate from scratch.

    Faster than --full for large datasets because it skips per-object
    UUID lookups — every insert goes into an empty collection.
    """
    logger.info("=" * 60)
    logger.info("Weaviate REBUILD (drop collection + fresh load)")
    logger.info("=" * 60)

    async with pool.acquire() as conn:
        pg_count = await conn.fetchval(
            "SELECT COUNT(*) FROM entity WHERE status = 'active'"
        )
    logger.info(f"PostgreSQL active entities: {pg_count:,}")

    status = await weaviate_index.get_status()
    logger.info(f"Current Weaviate object count: {status.get('object_count', 0):,}")

    if dry_run:
        logger.info(f"DRY RUN — would drop collection and rebuild with {pg_count:,} entities")
        return

    # Drop and recreate
    if not await weaviate_index.rebuild_collection():
        logger.error("Failed to rebuild collection — aborting")
        return
    logger.info("Collection recreated — loading from scratch...")

    # Fresh load (no stale detection needed on empty collection)
    if entity_vectors:
        logger.info(f"Using {len(entity_vectors):,} pre-computed entity vectors")
    upserted, _ = await weaviate_index.full_sync(
        pool, batch_size=batch_size, entity_vectors=entity_vectors)

    if location_vectors:
        logger.info(f"Using {len(location_vectors):,} pre-computed location vectors")
    loc_upserted, _ = await weaviate_index.location_sync(
        pool, batch_size=batch_size * 2, location_vectors=location_vectors)

    logger.info("=" * 60)
    logger.info(f"Rebuild complete: {upserted:,} entities, {loc_upserted:,} locations loaded")
    logger.info("=" * 60)


async def single_entity_sync(weaviate_index: EntityWeaviateIndex, pool: asyncpg.Pool,
                              entity_id: str, dry_run: bool = False):
    """Sync a single entity to Weaviate."""
    logger.info(f"Syncing entity: {entity_id}")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT e.*, et.type_key, et.type_label, et.type_description "
            "FROM entity e "
            "JOIN entity_type et ON e.entity_type_id = et.type_id "
            "WHERE e.entity_id = $1",
            entity_id,
        )
        if not row:
            logger.error(f"Entity not found: {entity_id}")
            return

        entity = dict(row)

        # Fetch aliases
        alias_rows = await conn.fetch(
            "SELECT alias_name, alias_type FROM entity_alias "
            "WHERE entity_id = $1 AND status = 'active'",
            entity_id,
        )
        entity['aliases'] = [dict(a) for a in alias_rows]

        # Fetch categories
        cat_rows = await conn.fetch(
            "SELECT ec.category_key, ec.category_label "
            "FROM entity_category_map ecm "
            "JOIN entity_category ec ON ecm.category_id = ec.category_id "
            "WHERE ecm.entity_id = $1 AND ecm.status = 'active'",
            entity_id,
        )
        entity['categories'] = [dict(c) for c in cat_rows]

    if dry_run:
        from vitalgraph.entity_registry.entity_weaviate_schema import entity_to_weaviate_properties
        props = entity_to_weaviate_properties(entity)
        logger.info(f"DRY RUN — would upsert entity {entity_id}:")
        for k, v in props.items():
            logger.info(f"  {k}: {v}")
        return

    await weaviate_index.ensure_collection()

    if entity.get('status') == 'deleted':
        await weaviate_index.delete_entity(entity_id)
        logger.info(f"Deleted {entity_id} from Weaviate (entity is deleted)")
    else:
        await weaviate_index.upsert_entity(entity)
        logger.info(f"Upserted {entity_id} to Weaviate")


async def main():
    parser = argparse.ArgumentParser(
        prog='weaviate_sync',
        description='Sync Entity Registry to Weaviate',
    )
    parser.add_argument('--full', action='store_true', help='Full sync (upsert + stale cleanup)')
    parser.add_argument('--rebuild', action='store_true',
                        help='Drop collection and rebuild from scratch (fastest for large datasets)')
    parser.add_argument('--entity-id', help='Sync a single entity by ID')
    parser.add_argument('--since', help='Incremental sync: ISO datetime or relative like "1h", "30m", "7d"')
    parser.add_argument('--dry-run', action='store_true', help='Report what would change')
    parser.add_argument('--batch-size', type=int, default=100, help='Batch size for full sync')
    parser.add_argument('--entity-vectors', metavar='FILE',
                        help='Path to entity_vectors.jsonl (pre-computed vectors)')
    parser.add_argument('--location-vectors', metavar='FILE',
                        help='Path to location_vectors.jsonl (pre-computed vectors)')
    args = parser.parse_args()

    if not args.full and not args.rebuild and not args.entity_id and not args.since:
        parser.error("Must specify --full, --rebuild, --entity-id, or --since")

    # Connect to Weaviate
    weaviate_index = await EntityWeaviateIndex.from_env()
    if not weaviate_index:
        logger.error("Failed to connect to Weaviate. Check ENTITY_WEAVIATE_ENABLED and WEAVIATE_* env vars.")
        sys.exit(1)

    # Connect to PostgreSQL
    pool = await create_pool()

    try:
        # Load pre-computed vectors if provided
        entity_vectors = None
        location_vectors = None
        if args.entity_vectors:
            from vitalgraph.entity_registry.entity_vectorizer import load_vectors_from_jsonl
            vp = Path(args.entity_vectors)
            if vp.exists():
                entity_vectors = load_vectors_from_jsonl(vp, 'entity_id')
                logger.info(f"Loaded {len(entity_vectors):,} entity vectors from {vp.name}")
            else:
                logger.error(f"Entity vectors file not found: {vp}")
                sys.exit(1)
        if args.location_vectors:
            from vitalgraph.entity_registry.entity_vectorizer import load_vectors_from_jsonl
            vp = Path(args.location_vectors)
            if vp.exists():
                location_vectors = load_vectors_from_jsonl(vp, 'location_id')
                logger.info(f"Loaded {len(location_vectors):,} location vectors from {vp.name}")
            else:
                logger.error(f"Location vectors file not found: {vp}")
                sys.exit(1)

        since_dt = _parse_since(args.since) if args.since else None
        if args.rebuild:
            await rebuild_sync(weaviate_index, pool, dry_run=args.dry_run,
                               batch_size=args.batch_size,
                               entity_vectors=entity_vectors,
                               location_vectors=location_vectors)
        elif args.full or args.since:
            await full_sync(weaviate_index, pool, dry_run=args.dry_run,
                            batch_size=args.batch_size, since=since_dt,
                            entity_vectors=entity_vectors,
                            location_vectors=location_vectors)
        elif args.entity_id:
            await single_entity_sync(weaviate_index, pool, args.entity_id, dry_run=args.dry_run)
    finally:
        await pool.close()
        await weaviate_index.close()


if __name__ == '__main__':
    asyncio.run(main())
