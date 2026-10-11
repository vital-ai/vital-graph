#!/usr/bin/env python3
"""
Build / manage the PostgreSQL fuzzy index.

The entity table in PostgreSQL is the source of truth. This script
computes MinHash band hashes from that data and writes them into the
PG fuzzy band tables. No data is transferred from Redis — we simply
re-index from the existing entity data.

Usage:
    # Build (or rebuild) the PG fuzzy index:
    python scripts/migrate_fuzzy_redis_to_pg.py --rebuild

    # Check status of PG fuzzy tables:
    python scripts/migrate_fuzzy_redis_to_pg.py --status

    # (Optional) Verify Redis and PG hashes match before cutover:
    python scripts/migrate_fuzzy_redis_to_pg.py --verify

    # (Optional) Compare query results between Redis and PG:
    python scripts/migrate_fuzzy_redis_to_pg.py --compare --name "Acme Corp"

Environment:
    DB_HOST, DB_PORT, DB_NAME, DB_USERNAME, DB_PASSWORD
    ENTITY_FUZZY_REDIS_HOST, ENTITY_FUZZY_REDIS_PORT (only for --verify/--compare)
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

# Ensure project root on path
# Three levels up, not two: this file is at <root>/apps/<group>/, so
# parent.parent is apps/ — which left `vitalgraph` unimportable unless it
# happened to be pip-installed, and `.env` unfound.
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)
logger = logging.getLogger('migrate_fuzzy')


async def get_pool():
    """Create asyncpg connection pool from environment."""
    from vitalgraph.config.config_loader import get_scoped_env
    return await asyncpg.create_pool(
        host=get_scoped_env('DB_HOST', 'localhost'),
        port=int(get_scoped_env('DB_PORT', '5432')),
        database=get_scoped_env('DB_NAME', 'sparql_sql_graph'),
        user=get_scoped_env('DB_USERNAME', 'postgres'),
        password=get_scoped_env('DB_PASSWORD', ''),
        min_size=2, max_size=10,
    )


async def ensure_tables(pool):
    """Ensure fuzzy tables exist."""
    from vitalgraph.entity_registry.entity_registry_schema import EntityRegistrySchema
    schema = EntityRegistrySchema()

    async with pool.acquire() as conn:
        for table_name in ['entity_fuzzy_band', 'entity_fuzzy_phonetic_band', 'entity_fuzzy_hash']:
            if table_name in schema.TABLES:
                await conn.execute(schema.TABLES[table_name])
        for idx_sql in schema.INDEXES:
            if 'fuzzy' in idx_sql:
                await conn.execute(idx_sql)

    logger.info("Fuzzy tables ensured")


async def cmd_status(pool):
    """Show status of PostgreSQL fuzzy tables."""
    from vitalgraph.entity_registry.entity_fuzzy_storage import (
        PostgreSQLFuzzyStorage, TABLE_PRIMARY, TABLE_PHONETIC, TABLE_HASH,
    )

    storage = PostgreSQLFuzzyStorage(pool)
    primary = await storage.get_band_count(TABLE_PRIMARY)
    phonetic = await storage.get_band_count(TABLE_PHONETIC)
    entities = await storage.get_entity_count()

    # Get entity count from source table
    async with pool.acquire() as conn:
        has_entity_table = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'entity')"
        )
        if has_entity_table:
            total_entities = await conn.fetchval(
                "SELECT COUNT(*) FROM entity WHERE status != 'deleted'"
            )
        else:
            total_entities = None

    print(f"\n{'='*60}")
    print("PostgreSQL Fuzzy Index Status")
    print(f"{'='*60}")
    if total_entities is not None:
        print(f"  Source entities (entity table):    {total_entities:>12,}")
    else:
        print(f"  Source entities (entity table):    {'N/A':>12} (table not found)")
    print(f"  Indexed entities (fuzzy_hash):     {entities:>12,}")
    print(f"  Primary band rows:                 {primary:>12,}")
    print(f"  Phonetic band rows:                {phonetic:>12,}")
    print(f"{'='*60}")

    if entities == 0:
        print("\n  ⚠️  Index is EMPTY — run --rebuild to populate")
    elif total_entities is not None and entities < total_entities:
        missing = total_entities - entities
        print(f"\n  ⚠️  {missing:,} entities NOT indexed — run --rebuild to fix")
    elif total_entities is not None:
        print(f"\n  ✅  Index is complete ({entities:,}/{total_entities:,} entities)")
    else:
        print(f"\n  ℹ️  {entities:,} entities indexed (entity table not available for comparison)")

    # Estimate band rows per entity
    if entities > 0:
        bands_per = primary / entities
        print(f"  Avg bands/entity: {bands_per:.1f}")


BAND_TABLES = ('entity_fuzzy_band', 'entity_fuzzy_phonetic_band')


async def _band_index_ddl(conn) -> list:
    """`(table, kind, name, ddl)` for every index on the band tables, read from the catalog.

    Read back rather than taken from `EntityRegistrySchema`, so the rebuild restores
    exactly what the database had, including indexes added outside the schema
    file (252's entity-id expression indexes were built by hand on production).
    """
    out = []
    for t in BAND_TABLES:
        pk = await conn.fetchrow(
            "SELECT conname, pg_get_constraintdef(oid) AS d FROM pg_constraint "
            "WHERE conrelid = $1::regclass AND contype = 'p'", t)
        if pk:
            out.append((t, 'pk', pk['conname'],
                        f"ALTER TABLE {t} ADD CONSTRAINT {pk['conname']} {pk['d']}"))
        for r in await conn.fetch(
                "SELECT c.relname, pg_get_indexdef(i.indexrelid) AS d FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE i.indrelid = $1::regclass AND NOT i.indisprimary "
                "ORDER BY c.relname", t):
            out.append((t, 'index', r['relname'], r['d']))
    return out


async def _drop_band_indexes(pool, ddl: list) -> None:
    async with pool.acquire() as conn:
        for t, kind, name, _ in ddl:
            if kind == 'pk':
                await conn.execute(f"ALTER TABLE {t} DROP CONSTRAINT {name}")
            else:
                await conn.execute(f"DROP INDEX {name}")


async def _restore_band_indexes(pool, ddl: list) -> None:
    """Recreate the band indexes, each in one transaction with no statement timeout.

    Building them on ~20M rows takes minutes, and production's parameter group
    caps statements at 60 s (`issues/136`), so the timeout is lifted per statement.

    A live writer can insert during the load. With no primary key, the same
    (band_id, band_hash, entity_key) can then arrive twice, once from the writer
    and once from the rebuild, and the key would refuse to build. So a refused key
    deduplicates that table and is retried; any other failure propagates.
    """
    async with pool.acquire() as conn:
        for t, kind, name, stmt in ddl:
            if await conn.fetchval(
                    "SELECT 1 FROM pg_class WHERE relname = $1", name):
                continue                      # already back: a re-run after a partial restore
            t0 = time.time()
            for attempt in (1, 2):
                try:
                    async with conn.transaction():
                        await conn.execute("SET LOCAL statement_timeout = 0")
                        await conn.execute("SET LOCAL maintenance_work_mem = '1GB'")
                        await conn.execute(stmt)
                    break
                except asyncpg.UniqueViolationError:
                    if kind != 'pk' or attempt == 2:
                        raise
                    async with conn.transaction():
                        await conn.execute("SET LOCAL statement_timeout = 0")
                        removed = await conn.execute(
                            f"DELETE FROM {t} WHERE ctid IN (SELECT ctid FROM ("
                            f"SELECT ctid, row_number() OVER (PARTITION BY band_id, "
                            f"band_hash, entity_key ORDER BY ctid) AS rn FROM {t}) d "
                            f"WHERE rn > 1)")
                    print(f"  {t}: duplicate rows from a concurrent writer removed "
                          f"({removed}); retrying {name}")
            print(f"  restored {name} in {time.time() - t0:.0f}s")


async def cmd_rebuild(pool, num_perm: int = 64, threshold: float = 0.3,
                      bulk: bool = True):
    """Full rebuild of the PG fuzzy index from entity table data.

    BULK BY DEFAULT: the band tables' primary keys and indexes are dropped for the
    load and recreated afterwards. Maintaining them row by row during the COPY made
    the rebuild run at ~250 entities/s falling to ~100/s on a 1.04M-entity registry
    (a 3+ hour window with fuzzy matching empty); dropped and recreated, the same
    rebuild took 710 s plus 131 s of index build (`issues/248`, measured
    2026-10-11). The recreated DDL is the catalog's own, printed and saved before
    anything is dropped, and restored even if the load fails.
    """
    from vitalgraph.entity_registry.entity_fuzzy_pg import EntityFuzzyIndexPG

    await ensure_tables(pool)

    idx = EntityFuzzyIndexPG(pool=pool, num_perm=num_perm, threshold=threshold)

    print(f"\nRebuilding PostgreSQL fuzzy index...")
    print(f"  num_perm={num_perm}, threshold={threshold}")
    print(f"  Bands: {len(idx.primary_band_ranges)} primary, "
          f"{len(idx.phonetic_band_ranges)} phonetic")
    print()

    ddl = []
    if bulk:
        async with pool.acquire() as conn:
            ddl = await _band_index_ddl(conn)
        # Written down before anything is dropped: if this process is killed
        # mid-load, these statements put the indexes back.
        saved = Path(f"fuzzy_band_indexes_{time.strftime('%Y%m%d_%H%M%S')}.sql")
        saved.write_text("".join(f"{stmt};\n" for *_, stmt in ddl))
        print(f"  bulk load: dropping {len(ddl)} band index(es); DDL saved to {saved.resolve()}")
        await _drop_band_indexes(pool, ddl)

    start = time.time()
    try:
        count = await idx.initialize(pool, skip_lock=True)
    finally:
        if ddl:
            print(f"  load done in {time.time() - start:.0f}s; restoring band indexes")
            await _restore_band_indexes(pool, ddl)
    duration = time.time() - start

    from vitalgraph.entity_registry.entity_fuzzy_storage import (
        PostgreSQLFuzzyStorage, TABLE_PRIMARY, TABLE_PHONETIC,
    )
    storage = PostgreSQLFuzzyStorage(pool)
    primary_rows = await storage.get_band_count(TABLE_PRIMARY)
    phonetic_rows = await storage.get_band_count(TABLE_PHONETIC)

    print(f"\n{'='*60}")
    print(f"Rebuild complete!")
    print(f"  Entities indexed:     {count:>10,}")
    print(f"  Primary band rows:    {primary_rows:>10,}")
    print(f"  Phonetic band rows:   {phonetic_rows:>10,}")
    print(f"  Duration:             {duration:>10.1f}s")
    if duration > 0:
        print(f"  Rate:                 {count/duration:>10.0f} entities/s")
    print(f"{'='*60}")


async def cmd_verify(pool):
    """Verify consistency between Redis and PG fuzzy hashes.

    Compares the fuzzy_hash stored in the entity table (PG) with
    the one stored in Redis. Reports mismatches.
    """
    try:
        from vitalgraph.entity_registry.entity_fuzzy import EntityFuzzyIndex
    except ImportError:
        print("ERROR: Redis dependencies not available")
        return

    # Create Redis-backed index to read its stored hashes
    idx = EntityFuzzyIndex.from_env()
    if not idx.storage_config:
        print("ERROR: Redis backend not configured (ENTITY_FUZZY_BACKEND != 'redis')")
        return

    client = idx._get_redis_client()
    if not client:
        print("ERROR: Could not connect to Redis")
        return

    # Read all fuzzy hashes from Redis
    hash_key = idx._fuzzy_hash_key()
    redis_hashes = client.hgetall(hash_key)
    print(f"Redis fuzzy hashes: {len(redis_hashes):,} entries")

    # Compare with entity table
    mismatches = 0
    missing_in_redis = 0
    missing_in_pg = 0
    PAGE = 10000

    from vitalgraph.entity_registry.entity_fuzzy import compute_entity_hash as compute_fuzzy_hash

    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM entity WHERE status != 'deleted'"
        )

    print(f"PostgreSQL entities: {total:,}")
    print("Comparing...")

    last_id = ''
    checked = 0
    while True:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT entity_id, fuzzy_hash FROM entity "
                "WHERE status != 'deleted' AND entity_id > $1 "
                "ORDER BY entity_id LIMIT $2",
                last_id, PAGE,
            )
        if not rows:
            break

        for row in rows:
            eid = row['entity_id']
            pg_hash = row['fuzzy_hash']
            redis_hash = redis_hashes.get(eid.encode())

            if redis_hash is None:
                missing_in_redis += 1
            elif pg_hash and redis_hash.decode() != pg_hash:
                mismatches += 1
                if mismatches <= 10:
                    print(f"  MISMATCH: {eid} pg={pg_hash} redis={redis_hash.decode()}")

            checked += 1

        last_id = rows[-1]['entity_id']
        if len(rows) < PAGE:
            break

    # Check for entities in Redis but not in PG
    pg_ids = set()
    last_id = ''
    while True:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT entity_id FROM entity WHERE status != 'deleted' "
                "AND entity_id > $1 ORDER BY entity_id LIMIT $2",
                last_id, PAGE,
            )
        if not rows:
            break
        for row in rows:
            pg_ids.add(row['entity_id'].encode())
        last_id = rows[-1]['entity_id']
        if len(rows) < PAGE:
            break

    for redis_key in redis_hashes:
        if redis_key not in pg_ids:
            missing_in_pg += 1

    print(f"\n{'='*60}")
    print(f"Verification Results")
    print(f"{'='*60}")
    print(f"  Checked:             {checked:>10,}")
    print(f"  Mismatches:          {mismatches:>10,}")
    print(f"  Missing in Redis:    {missing_in_redis:>10,}")
    print(f"  Missing in PG:       {missing_in_pg:>10,} (stale Redis entries)")
    print(f"{'='*60}")

    if mismatches == 0 and missing_in_redis == 0:
        print("  ✅  Redis and PG are consistent")
    else:
        print("  ⚠️  Inconsistencies found — run --rebuild to fix PG index")


async def cmd_compare(pool, name: str, country: str = ''):
    """Compare query results between Redis and PG backends."""
    from vitalgraph.entity_registry.entity_fuzzy import EntityFuzzyIndex
    from vitalgraph.entity_registry.entity_fuzzy_pg import EntityFuzzyIndexPG

    entity = {'primary_name': name, 'country': country}

    # Redis backend
    redis_idx = EntityFuzzyIndex.from_env()
    if not redis_idx.storage_config:
        print("ERROR: Redis backend not configured")
        return

    redis_candidates = redis_idx.get_candidate_ids(entity)
    print(f"\nRedis candidates for '{name}': {len(redis_candidates)}")
    if redis_candidates:
        for cid in sorted(redis_candidates)[:20]:
            print(f"  {cid}")

    # PG backend
    pg_idx = EntityFuzzyIndexPG(pool=pool, num_perm=64, threshold=0.3)
    # Need to load the scoring cache to do meaningful queries
    from vitalgraph.entity_registry.entity_fuzzy_storage import TABLE_PRIMARY
    band_count = await pg_idx.storage.get_band_count(TABLE_PRIMARY)
    if band_count == 0:
        print("\nPG index is empty — run --rebuild first")
        return

    pg_candidates = await pg_idx.get_candidate_ids(entity)
    print(f"\nPG candidates for '{name}': {len(pg_candidates)}")
    if pg_candidates:
        for cid in sorted(pg_candidates)[:20]:
            print(f"  {cid}")

    # Overlap
    overlap = redis_candidates & pg_candidates
    redis_only = redis_candidates - pg_candidates
    pg_only = pg_candidates - redis_candidates

    print(f"\n{'='*60}")
    print(f"Comparison for '{name}':")
    print(f"  Redis candidates:  {len(redis_candidates)}")
    print(f"  PG candidates:     {len(pg_candidates)}")
    print(f"  Overlap:           {len(overlap)}")
    print(f"  Redis only:        {len(redis_only)}")
    print(f"  PG only:           {len(pg_only)}")
    print(f"{'='*60}")

    if redis_only:
        print(f"\n  Redis-only (first 10):")
        for cid in sorted(redis_only)[:10]:
            print(f"    {cid}")
    if pg_only:
        print(f"\n  PG-only (first 10):")
        for cid in sorted(pg_only)[:10]:
            print(f"    {cid}")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate entity fuzzy index from Redis/MemoryDB to PostgreSQL"
    )
    parser.add_argument('--rebuild', action='store_true',
                        help='Full rebuild of PG fuzzy index from entity table')
    parser.add_argument('--no-bulk', action='store_true',
                        help='--rebuild with the band indexes kept in place during '
                             'the load (slow: maintained row by row)')
    parser.add_argument('--verify', action='store_true',
                        help='Verify consistency between Redis and PG fuzzy hashes')
    parser.add_argument('--status', action='store_true',
                        help='Show status of PG fuzzy tables')
    parser.add_argument('--compare', action='store_true',
                        help='Compare query results between Redis and PG')
    parser.add_argument('--name', type=str, default='Acme Corporation',
                        help='Entity name for --compare (default: Acme Corporation)')
    parser.add_argument('--country', type=str, default=None,
                        help='Country filter for --compare')
    parser.add_argument('--num-perm', type=int, default=64,
                        help='Number of MinHash permutations (default: 64)')
    parser.add_argument('--threshold', type=float, default=0.3,
                        help='LSH threshold (default: 0.3)')

    args = parser.parse_args()

    if not any([args.rebuild, args.verify, args.status, args.compare]):
        parser.print_help()
        sys.exit(1)

    async def run():
        pool = await get_pool()
        try:
            if args.status:
                await ensure_tables(pool)
                await cmd_status(pool)
            elif args.rebuild:
                await cmd_rebuild(pool, num_perm=args.num_perm, threshold=args.threshold,
                                  bulk=not args.no_bulk)
            elif args.verify:
                await cmd_verify(pool)
            elif args.compare:
                await cmd_compare(pool, name=args.name, country=args.country)
        finally:
            await pool.close()

    asyncio.run(run())


if __name__ == '__main__':
    main()
