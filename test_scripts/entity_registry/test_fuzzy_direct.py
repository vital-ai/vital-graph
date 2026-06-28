#!/usr/bin/env python3
"""
Direct diagnostic test for the entity fuzzy pipeline.

Connects directly to production PostgreSQL and MemoryDB (via SSH tunnel),
creates an EntityFuzzyIndex pointing at MemoryDB, samples real entities
from PG, and traces the full pipeline: LSH query → PG fetch → scoring.

This bypasses the REST layer entirely to isolate where results drop.

Usage:
    # Set env vars for prod connections (same as sync_fuzzy_index.py):
    export DATABASE_URL="postgresql://..."
    export ENTITY_FUZZY_BACKEND=redis
    export ENTITY_FUZZY_REDIS_HOST=...
    export ENTITY_FUZZY_REDIS_PORT=6379
    export ENTITY_FUZZY_REDIS_USERNAME=...
    export ENTITY_FUZZY_REDIS_PASSWORD=...
    export ENTITY_FUZZY_REDIS_SSL=true
    export ENTITY_FUZZY_REDIS_CLUSTER=true
    export VITALGRAPH_ENVIRONMENT=prod

    python test_scripts/entity_registry/test_fuzzy_direct.py
"""

import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

# Override VITALGRAPH_ENVIRONMENT so prod keys (bare 'fuzzy' prefix) are used
os.environ['VITALGRAPH_ENVIRONMENT'] = ''

import asyncpg
from rapidfuzz import fuzz

from vitalgraph.entity_registry.entity_fuzzy import EntityFuzzyIndex

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(name)s  %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('test_fuzzy_direct')


async def main():
    logger.info("=" * 60)
    logger.info("Direct Fuzzy Pipeline Diagnostic")
    logger.info("=" * 60)

    # ---- Connect to prod PG ----
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        pool = await asyncpg.create_pool(database_url, min_size=1, max_size=2)
        logger.info("Connected to PostgreSQL via DATABASE_URL")
    else:
        host = os.environ.get('PROD_DB_HOST')
        if not host:
            logger.error("Neither DATABASE_URL nor PROD_DB_HOST set")
            sys.exit(1)
        pool = await asyncpg.create_pool(
            host=host,
            port=int(os.environ.get('PROD_DB_PORT', '5432')),
            database=os.environ.get('PROD_DB_NAME', 'vitalgraphdb'),
            user=os.environ.get('PROD_DB_USERNAME', 'postgres'),
            password=os.environ.get('PROD_DB_PASSWORD', '').strip('"'),
            min_size=1, max_size=2,
        )
        logger.info("Connected to PostgreSQL: %s", host)

    # ---- Create EntityFuzzyIndex pointing at prod MemoryDB ----
    idx = EntityFuzzyIndex.from_env()
    idx._initialized = True
    logger.info(f"EntityFuzzyIndex created: storage_config={'yes' if idx.storage_config else 'no'}, "
                f"num_perm={idx.num_perm}, threshold={idx.threshold}")

    # ---- Probe MemoryDB for keys ----
    logger.info("\n--- MemoryDB Key Probe ---")
    redis_client = idx._get_redis_client()
    if redis_client:
        # Check total key count
        try:
            info = redis_client.info('keyspace')
            logger.info(f"  Keyspace info: {info}")
        except Exception as e:
            logger.info(f"  Keyspace info failed: {e}")

        # Scan for any keys matching our basename
        basename = idx.storage_config.get('basename', b'')
        tag_prefix = idx.storage_config.get('hash_tag_prefix', '')
        logger.info(f"  basename={basename!r}, hash_tag_prefix={tag_prefix!r}")

        # Sample a few keys
        sample_keys = []
        try:
            for key in redis_client.scan_iter(match=b'*', count=20):
                sample_keys.append(key)
                if len(sample_keys) >= 10:
                    break
            logger.info(f"  Sample keys ({len(sample_keys)}): {sample_keys[:5]}")
        except Exception as e:
            logger.info(f"  scan_iter failed: {e}")

        # Check LSH hashtable structure
        logger.info(f"  LSH bands: {len(idx.lsh.hashtables)}, "
                     f"hashranges: {idx.lsh.hashranges[:3]}...")
        if idx.lsh.hashtables:
            ht0 = idx.lsh.hashtables[0]
            logger.info(f"  hashtable[0] type: {type(ht0).__name__}")
            # Try to get the Redis key name for band 0
            if hasattr(ht0, 'name'):
                logger.info(f"  hashtable[0].name: {ht0.name!r}")
            if hasattr(ht0, '_name'):
                logger.info(f"  hashtable[0]._name: {ht0._name!r}")
            # Check if band 0 has any entries
            try:
                ht0_size = ht0.size()
                logger.info(f"  hashtable[0].size(): {ht0_size}")
            except Exception as e:
                logger.info(f"  hashtable[0].size() failed: {e}")
            # Try keys() on band 0
            try:
                ht0_keys = list(ht0.keys())[:5]
                logger.info(f"  hashtable[0] sample keys: {ht0_keys}")
            except Exception as e:
                logger.info(f"  hashtable[0].keys() failed: {e}")
    else:
        logger.error("  Could not get Redis client!")

    # ---- Sample entities from PG ----
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT e.entity_id, e.primary_name, et.type_key, "
            "e.country, e.region, e.locality "
            "FROM entity e "
            "LEFT JOIN entity_type et ON et.type_id = e.entity_type_id "
            "WHERE e.status != 'deleted' AND LENGTH(e.primary_name) >= 5 "
            "ORDER BY e.entity_id "
            "LIMIT 10"
        )

    logger.info(f"\nSampled {len(rows)} entities from PG:")
    for r in rows:
        logger.info(f"  {r['entity_id'][:12]}... | {r['primary_name'][:50]} | "
                     f"type={r['type_key']} | country={r['country']}")

    # ---- Test each entity through the pipeline ----
    passed = 0
    failed = 0

    for row in rows:
        entity_id = row['entity_id']
        name = row['primary_name']
        country = row['country']
        logger.info(f"\n--- Testing: '{name}' ---")

        entity = {
            'primary_name': name,
            'country': country,
            'region': row['region'],
            'locality': row['locality'],
        }

        # Phase 1: LSH candidates
        t0 = time.time()
        candidate_ids = idx.get_candidate_ids(entity)
        t_lsh = time.time() - t0
        logger.info(f"  Phase 1 (LSH): {len(candidate_ids)} candidates in {t_lsh:.3f}s")

        if not candidate_ids:
            logger.error(f"  ❌ ZERO LSH candidates for '{name}'")
            failed += 1

            # Debug: try without location shingles
            entity_no_loc = {'primary_name': name}
            cids_no_loc = idx.get_candidate_ids(entity_no_loc)
            logger.info(f"  (retry without location: {len(cids_no_loc)} candidates)")
            if not cids_no_loc:
                # Debug: show the shingles and minhash
                shingles = idx._name_shingles(name, entity_no_loc)
                logger.info(f"  shingles ({len(shingles)}): {list(shingles)[:10]}...")
                mh = idx._build_minhash(shingles)
                logger.info(f"  minhash first 5 values: {mh.hashvalues[:5]}")
            continue

        self_found = entity_id in candidate_ids
        logger.info(f"  Self in candidates: {self_found}")
        if not self_found:
            logger.warning(f"  ⚠️  Entity {entity_id} NOT in its own LSH candidates")

        # Phase 1.5: PG fetch
        t0 = time.time()
        async with pool.acquire() as conn:
            fetch_rows = await conn.fetch(
                "SELECT e.entity_id, e.primary_name, et.type_key, "
                "e.country, e.region, e.locality, ea.alias_name "
                "FROM entity e "
                "LEFT JOIN entity_type et ON et.type_id = e.entity_type_id "
                "LEFT JOIN entity_alias ea ON ea.entity_id = e.entity_id "
                "AND ea.status != 'retracted' "
                "WHERE e.entity_id = ANY($1) AND e.status != 'deleted'",
                list(candidate_ids),
            )
        t_pg = time.time() - t0

        # Group by entity_id
        candidate_data = {}
        for fr in fetch_rows:
            eid = fr['entity_id']
            if eid not in candidate_data:
                candidate_data[eid] = {
                    'primary_name': fr['primary_name'],
                    'type_key': fr['type_key'],
                    'alias_names': [],
                    'country': fr['country'],
                    'region': fr['region'],
                    'locality': fr['locality'],
                }
            alias = fr['alias_name']
            if alias:
                candidate_data[eid]['alias_names'].append(alias)

        logger.info(f"  Phase 1.5 (PG): {len(candidate_data)} entities fetched in {t_pg:.3f}s")

        if len(candidate_data) == 0:
            logger.error(f"  ❌ PG returned 0 rows for {len(candidate_ids)} candidate IDs")
            logger.info(f"  Sample IDs: {list(candidate_ids)[:5]}")
            failed += 1
            continue

        # Phase 2: Score
        t0 = time.time()
        results = idx.score_candidates(
            entity, candidate_data,
            limit=10, min_score=40.0,
        )
        t_score = time.time() - t0
        logger.info(f"  Phase 2 (Score): {len(results)} results in {t_score:.3f}s")

        for r in results[:3]:
            logger.info(f"    → {r['primary_name'][:40]} score={r['score']} "
                         f"level={r['match_level']}")

        # Check self-match
        self_matched = any(r['entity_id'] == entity_id for r in results)
        if self_matched:
            logger.info(f"  ✅ Self-match found")
            passed += 1
        else:
            logger.error(f"  ❌ Self-match NOT found in results")
            # Debug: manually score self
            if entity_id in candidate_data:
                self_data = candidate_data[entity_id]
                query_names = idx._get_name_variants(entity)
                score_info = idx._score_pair(query_names, self_data)
                logger.info(f"  Manual self-score: {score_info['score']} "
                             f"(query={query_names}, candidate_name={self_data['primary_name']})")
            else:
                logger.error(f"  Entity {entity_id} not in PG fetch results!")
            failed += 1

    logger.info(f"\n{'=' * 60}")
    logger.info(f"Results: {passed}/{passed + failed} self-matches found")
    logger.info(f"{'=' * 60}")

    await pool.close()
    return passed > 0 and failed == 0


if __name__ == '__main__':
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
