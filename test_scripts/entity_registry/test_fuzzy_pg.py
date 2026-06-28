#!/usr/bin/env python3
"""
Test script for the PostgreSQL-backed entity fuzzy index (EntityFuzzyIndexPG).

Usage:
    python test_scripts/entity_registry/test_fuzzy_pg.py

Requires:
    - PostgreSQL running locally with entity registry tables created
    - ENTITY_FUZZY_BACKEND=postgresql (or defaults work fine)
"""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

# Ensure project root on path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import asyncpg

from vitalgraph.entity_registry.entity_fuzzy_pg import EntityFuzzyIndexPG, compute_entity_hash
from vitalgraph.entity_registry.entity_fuzzy_storage import (
    PostgreSQLFuzzyStorage,
    TABLE_PRIMARY,
    TABLE_PHONETIC,
    TABLE_HASH,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)

# Test entities
TEST_ENTITIES = [
    {
        'entity_id': 'test_ent_001',
        'primary_name': 'Acme Corporation',
        'type_key': 'business',
        'country': 'US',
        'region': 'CA',
        'locality': 'San Francisco',
        'aliases': [{'alias_name': 'ACME'}, {'alias_name': 'Acme Corp'}],
    },
    {
        'entity_id': 'test_ent_002',
        'primary_name': 'Acme Corp',
        'type_key': 'business',
        'country': 'US',
        'region': 'CA',
        'locality': 'San Francisco',
        'aliases': [],
    },
    {
        'entity_id': 'test_ent_003',
        'primary_name': 'Globex Industries',
        'type_key': 'business',
        'country': 'US',
        'region': 'NY',
        'locality': 'New York',
        'aliases': [{'alias_name': 'Globex'}],
    },
    {
        'entity_id': 'test_ent_004',
        'primary_name': 'John Smith',
        'type_key': 'person',
        'country': 'US',
        'region': 'TX',
        'locality': 'Austin',
        'aliases': [{'alias_name': 'Jon Smith'}],
    },
    {
        'entity_id': 'test_ent_005',
        'primary_name': 'Jon Smyth',
        'type_key': 'person',
        'country': 'US',
        'region': 'TX',
        'locality': 'Austin',
        'aliases': [],
    },
]


async def ensure_tables(pool):
    """Create fuzzy tables if they don't exist."""
    from vitalgraph.entity_registry.entity_registry_schema import EntityRegistrySchema
    schema = EntityRegistrySchema()

    async with pool.acquire() as conn:
        for table_name in ['entity_fuzzy_band', 'entity_fuzzy_phonetic_band', 'entity_fuzzy_hash']:
            if table_name in schema.TABLES:
                await conn.execute(schema.TABLES[table_name])

        # Create indexes
        for idx_sql in schema.INDEXES:
            if 'fuzzy' in idx_sql:
                await conn.execute(idx_sql)

    logger.info("Fuzzy tables ensured")


async def test_storage_basic(pool):
    """Test PostgreSQLFuzzyStorage basic operations."""
    print("\n=== Test: PostgreSQLFuzzyStorage basic ops ===")
    storage = PostgreSQLFuzzyStorage(pool)

    # Truncate
    await storage.truncate_all()
    count = await storage.get_band_count(TABLE_PRIMARY)
    assert count == 0, f"Expected 0 rows after truncate, got {count}"
    print("  PASS: truncate_all")

    # Insert bands
    entries = [
        (0, b'\x01\x02\x03', 'ent1::0'),
        (0, b'\x04\x05\x06', 'ent2::0'),
        (1, b'\x01\x02\x03', 'ent1::0'),
        (1, b'\x07\x08\x09', 'ent3::0'),
    ]
    await storage.insert_bands(TABLE_PRIMARY, entries)
    count = await storage.get_band_count(TABLE_PRIMARY)
    assert count == 4, f"Expected 4, got {count}"
    print(f"  PASS: insert_bands ({count} rows)")

    # Query bands
    hits = await storage.query_bands(TABLE_PRIMARY, [
        (0, [b'\x01\x02\x03', b'\x04\x05\x06']),
        (1, [b'\x01\x02\x03']),
    ])
    assert 'ent1::0' in hits and hits['ent1::0'] == 2, f"Expected ent1::0 with 2 hits, got {hits}"
    assert 'ent2::0' in hits and hits['ent2::0'] == 1, f"Expected ent2::0 with 1 hit"
    print(f"  PASS: query_bands ({len(hits)} keys, ent1 hits={hits.get('ent1::0')})")

    # Remove bands
    await storage.remove_entity_bands(TABLE_PRIMARY, ['ent1::0'])
    count = await storage.get_band_count(TABLE_PRIMARY)
    assert count == 2, f"Expected 2 after remove, got {count}"
    print(f"  PASS: remove_entity_bands ({count} remaining)")

    # Fuzzy hash operations
    await storage.set_fuzzy_hash('test_id', 'a' * 32)
    h = await storage.get_fuzzy_hash('test_id')
    assert h == 'a' * 32, f"Expected hash, got {h}"
    print("  PASS: set/get fuzzy_hash")

    await storage.delete_fuzzy_hash('test_id')
    h = await storage.get_fuzzy_hash('test_id')
    assert h is None, f"Expected None after delete, got {h}"
    print("  PASS: delete fuzzy_hash")

    # Advisory lock
    acquired = await storage.try_advisory_lock()
    assert acquired is True, "Expected lock acquisition"
    await storage.release_advisory_lock()
    print("  PASS: advisory lock acquire/release")

    await storage.truncate_all()
    print("  ALL STORAGE TESTS PASSED")
    return True


async def test_index_add_query(pool):
    """Test EntityFuzzyIndexPG add + query flow."""
    print("\n=== Test: EntityFuzzyIndexPG add + query ===")
    idx = EntityFuzzyIndexPG(pool=pool, num_perm=64, threshold=0.3)

    # Clear
    await idx.storage.truncate_all()

    # Add test entities
    for ent in TEST_ENTITIES:
        await idx.add_entity(ent['entity_id'], ent)

    assert idx.entity_count == len(TEST_ENTITIES), (
        f"Expected {len(TEST_ENTITIES)} cached, got {idx.entity_count}")
    print(f"  PASS: added {idx.entity_count} entities")

    # Verify band rows exist
    primary_count = await idx.storage.get_band_count(TABLE_PRIMARY)
    phonetic_count = await idx.storage.get_band_count(TABLE_PHONETIC)
    hash_count = await idx.storage.get_entity_count()
    print(f"  Band rows: primary={primary_count}, phonetic={phonetic_count}, hashes={hash_count}")
    assert primary_count > 0, "No primary band rows"
    assert phonetic_count > 0, "No phonetic band rows"
    assert hash_count == len(TEST_ENTITIES), f"Expected {len(TEST_ENTITIES)} hashes, got {hash_count}"

    # Query for "Acme Corp" — should find test_ent_001 and test_ent_002
    candidates = await idx.get_candidate_ids({'primary_name': 'Acme Corp', 'country': 'US'})
    print(f"  Candidates for 'Acme Corp': {candidates}")
    assert 'test_ent_001' in candidates or 'test_ent_002' in candidates, (
        f"Expected Acme entities in candidates, got {candidates}")
    print(f"  PASS: get_candidate_ids found {len(candidates)} candidates")

    # Score candidates
    results = await idx.find_similar_by_name(
        'Acme Corp', country='US', region='CA', locality='San Francisco',
        limit=5, min_score=40.0,
    )
    print(f"  find_similar results:")
    for r in results:
        print(f"    {r['entity_id']}: {r['primary_name']} (score={r['score']})")
    assert len(results) > 0, "Expected at least one similar entity"
    # test_ent_001 or test_ent_002 should score highly
    top_ids = {r['entity_id'] for r in results}
    assert 'test_ent_001' in top_ids or 'test_ent_002' in top_ids
    print(f"  PASS: find_similar_by_name found {len(results)} results")

    # Query for "John Smith" — should find test_ent_004/005
    results = await idx.find_similar_by_name(
        'John Smith', country='US', limit=5, min_score=40.0,
    )
    print(f"  find_similar('John Smith') results:")
    for r in results:
        print(f"    {r['entity_id']}: {r['primary_name']} (score={r['score']})")
    person_ids = {r['entity_id'] for r in results}
    assert 'test_ent_004' in person_ids or 'test_ent_005' in person_ids
    print(f"  PASS: found person matches")

    print("  ALL INDEX TESTS PASSED")
    return True


async def test_index_remove(pool):
    """Test EntityFuzzyIndexPG remove entity."""
    print("\n=== Test: EntityFuzzyIndexPG remove ===")
    idx = EntityFuzzyIndexPG(pool=pool, num_perm=64, threshold=0.3)
    await idx.storage.truncate_all()

    # Add one entity
    ent = TEST_ENTITIES[0]
    await idx.add_entity(ent['entity_id'], ent)
    assert idx.entity_count == 1
    band_count_before = await idx.storage.get_band_count(TABLE_PRIMARY)
    print(f"  After add: {band_count_before} band rows")

    # Remove it
    await idx.remove_entity(ent['entity_id'])
    assert idx.entity_count == 0
    band_count_after = await idx.storage.get_band_count(TABLE_PRIMARY)
    hash_count = await idx.storage.get_entity_count()
    print(f"  After remove: {band_count_after} band rows, {hash_count} hashes")
    assert band_count_after == 0, f"Expected 0 bands, got {band_count_after}"
    assert hash_count == 0, f"Expected 0 hashes, got {hash_count}"
    print("  PASS: remove_entity clears all data")
    return True


async def test_index_initialize(pool):
    """Test EntityFuzzyIndexPG bulk initialize (requires entity table with data)."""
    print("\n=== Test: EntityFuzzyIndexPG initialize ===")
    idx = EntityFuzzyIndexPG(pool=pool, num_perm=64, threshold=0.3)

    # Check if entity table exists and has data
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'entity')"
        )
        if not exists:
            print("  SKIP: entity table not found (run migrate first)")
            return True
        count = await conn.fetchval("SELECT COUNT(*) FROM entity WHERE status != 'deleted'")
        if count == 0:
            print("  SKIP: no entities in table (need test data)")
            return True

    start = time.time()
    indexed = await idx.initialize(pool, skip_lock=True)
    duration = time.time() - start
    print(f"  Indexed {indexed:,} entities in {duration:.1f}s "
          f"({indexed/duration:.0f}/s)" if duration > 0 else f"  Indexed {indexed}")

    primary_count = await idx.storage.get_band_count(TABLE_PRIMARY)
    print(f"  Band rows: primary={primary_count:,}")
    assert indexed > 0
    assert idx.entity_count == indexed
    print(f"  PASS: initialize loaded {indexed} entities")
    return True


async def test_compute_entity_hash():
    """Test compute_entity_hash determinism."""
    print("\n=== Test: compute_entity_hash ===")
    ent = TEST_ENTITIES[0]
    h1 = compute_entity_hash(ent)
    h2 = compute_entity_hash(ent)
    assert h1 == h2, "Hash not deterministic"
    assert len(h1) == 32, f"Expected 32 chars, got {len(h1)}"

    # Different entity should have different hash
    h3 = compute_entity_hash(TEST_ENTITIES[2])
    assert h3 != h1, "Different entities should have different hashes"
    print(f"  PASS: deterministic 32-char hex hash ({h1[:8]}...)")
    return True


async def main():
    db_host = os.environ.get('DB_HOST', 'localhost')
    db_port = int(os.environ.get('DB_PORT', '5432'))
    db_name = os.environ.get('DB_NAME', 'sparql_sql_graph')
    db_user = os.environ.get('DB_USERNAME', 'postgres')
    db_pass = os.environ.get('DB_PASSWORD', '')

    pool = await asyncpg.create_pool(
        host=db_host, port=db_port,
        database=db_name, user=db_user, password=db_pass,
        min_size=2, max_size=5,
    )

    try:
        await ensure_tables(pool)

        results = []
        results.append(await test_compute_entity_hash())
        results.append(await test_storage_basic(pool))
        results.append(await test_index_add_query(pool))
        results.append(await test_index_remove(pool))
        results.append(await test_index_initialize(pool))

        print(f"\n{'='*60}")
        passed = sum(1 for r in results if r)
        total = len(results)
        print(f"Results: {passed}/{total} tests passed")
        if passed == total:
            print("ALL TESTS PASSED")
        else:
            print("SOME TESTS FAILED")
            sys.exit(1)
    finally:
        await pool.close()


if __name__ == '__main__':
    asyncio.run(main())
