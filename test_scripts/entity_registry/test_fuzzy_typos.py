#!/usr/bin/env python3
"""
Typo resilience test for the progressive fuzzy pipeline.

Queries MemoryDB with intentional typos and checks whether the correct
entity ("David Harrington") is found in candidates + scored results.

Tests the full progressive cascade: primary LSH → phonetic → typo variants.
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
from vitalgraph.entity_registry.entity_fuzzy import EntityFuzzyIndex

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)-8s %(name)s  %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('test_typos')


# Typo test cases: (query_name, description)
TYPO_CASES = [
    ("David Harrington",   "exact match"),
    ("Dvid Harrington",    "deletion: 'a' removed from David"),
    ("David Harington",    "deletion: 'r' removed from Harrington"),
    ("David Harringtn",    "deletion: 'o' removed from Harrington"),
    ("Davdi Harrington",   "transposition: 'id' → 'di'"),
    ("David Harringotn",   "transposition: 'to' → 'ot'"),
    ("Davod Harrington",   "substitution: 'i' → 'o'"),
    ("David Herrington",   "substitution: 'a' → 'e'"),
    ("Davi Harrington",    "truncation: last char of David"),
    ("David Harringto",    "truncation: last char of Harrington"),
]


async def main():
    logger.info("=" * 60)
    logger.info("Typo Resilience Test")
    logger.info("=" * 60)

    # Connect to prod PG
    host = os.environ.get('PROD_DB_HOST')
    if not host:
        logger.error("PROD_DB_HOST not set")
        sys.exit(1)
    pool = await asyncpg.create_pool(
        host=host,
        port=int(os.environ.get('PROD_DB_PORT', '5432')),
        database=os.environ.get('PROD_DB_NAME', 'vitalgraphdb'),
        user=os.environ.get('PROD_DB_USERNAME', 'postgres'),
        password=os.environ.get('PROD_DB_PASSWORD', '').strip('"'),
        min_size=1, max_size=2,
    )

    # Find the real "David Harrington" entity_id
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT entity_id FROM entity "
            "WHERE primary_name = 'David Harrington' "
            "AND status != 'deleted' LIMIT 1"
        )
    if not row:
        logger.error("No 'David Harrington' entity found in PG")
        sys.exit(1)
    target_id = row['entity_id']
    logger.info(f"Target entity: {target_id} ('David Harrington')")

    # Create index
    idx = EntityFuzzyIndex.from_env()
    idx._initialized = True

    passed = 0
    total = len(TYPO_CASES)

    for query_name, desc in TYPO_CASES:
        logger.info(f"\n--- Query: '{query_name}' ({desc}) ---")

        entity = {'primary_name': query_name}

        # Phase 1: get candidates
        t0 = time.time()
        candidate_ids = idx.get_candidate_ids(entity)
        t_lsh = time.time() - t0

        in_candidates = target_id in candidate_ids
        logger.info(f"  Candidates: {len(candidate_ids)} in {t_lsh:.3f}s | "
                     f"target in candidates: {in_candidates}")

        if not candidate_ids:
            logger.error(f"  ❌ ZERO candidates")
            continue

        # Phase 2: PG fetch + score
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

        results = idx.score_candidates(entity, candidate_data,
                                        limit=10, min_score=30.0)

        target_result = next((r for r in results if r['entity_id'] == target_id), None)
        if target_result:
            logger.info(f"  ✅ Found 'David Harrington' — score={target_result['score']}, "
                         f"level={target_result['match_level']}")
            passed += 1
        else:
            logger.error(f"  ❌ 'David Harrington' NOT in scored results")
            if results:
                logger.info(f"  Top result: {results[0]['primary_name']} "
                             f"score={results[0]['score']}")

    logger.info(f"\n{'=' * 60}")
    logger.info(f"Typo results: {passed}/{total} found 'David Harrington'")
    logger.info(f"{'=' * 60}")

    await pool.close()
    return passed == total


if __name__ == '__main__':
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
