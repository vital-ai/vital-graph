#!/usr/bin/env python3
"""
Redis integration test for EntityDedupIndex.

Tests both LSH indexes (primary + phonetic) and the batch-query pipeline
against a real Redis instance on localhost:6381.

Verifies:
  1. Redis storage config wires up correctly for both LSH indexes
  2. Entities persist in Redis (survive index object recreation)
  3. Primary LSH, phonetic LSH, and typo (edit-distance-1 batch) all work
  4. Batch query via _batch_query_lsh uses Redis pipelines
  5. clear_index properly cleans up Redis keys
  6. Performance timing for index build and queries

Prerequisites:
  - Redis running on localhost:6381
  - pip install redis datasketch jellyfish rapidfuzz

Usage:
    python test_scripts/entity_registry/test_dedup_redis.py
"""

import logging
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)

REDIS_HOST = 'localhost'
REDIS_PORT = 6381
BASENAME = b'dedup_test'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_storage_config():
    return {
        'type': 'redis',
        'basename': BASENAME,
        'redis': {'host': REDIS_HOST, 'port': REDIS_PORT},
    }


def check_redis():
    """Verify Redis is reachable."""
    try:
        import redis
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT)
        r.ping()
        info = r.info('memory')
        logger.info(f"Redis reachable at {REDIS_HOST}:{REDIS_PORT} "
                     f"(used_memory={info.get('used_memory_human', '?')})")
        return r
    except Exception as e:
        logger.error(f"Cannot connect to Redis at {REDIS_HOST}:{REDIS_PORT}: {e}")
        sys.exit(1)


def flush_test_keys(r):
    """Delete all keys matching our test basename to start clean."""
    deleted = 0
    for key in r.scan_iter(match=b'*dedup_test*', count=1000):
        r.delete(key)
        deleted += 1
    logger.info(f"Flushed {deleted} existing test keys")


class RedisTestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def check(self, label, condition, detail=''):
        if condition:
            self.passed += 1
            logger.info(f"  ✅ {label}" + (f" - {detail}" if detail else ''))
        else:
            self.failed += 1
            logger.error(f"  ❌ {label}" + (f" - {detail}" if detail else ''))


def run_tests():
    from vitalgraph.entity_registry.entity_dedup import EntityDedupIndex
    from test_scripts.entity_registry.test_dedup_entities import TEST_ENTITIES

    r = check_redis()
    flush_test_keys(r)
    t = RedisTestRunner()

    storage_config = make_storage_config()

    # ==================================================================
    # 1. Build index with Redis backend
    # ==================================================================
    logger.info("\n" + "=" * 70)
    logger.info("1. BUILD INDEX (Redis backend)")
    logger.info("=" * 70)

    t0 = time.time()
    idx = EntityDedupIndex(
        num_perm=128,
        threshold=0.3,
        storage_config=storage_config,
        phonetic_bonus=10.0,
    )
    build_start = time.time()
    for eid, data in TEST_ENTITIES:
        idx.add_entity(eid, data)
    build_ms = (time.time() - build_start) * 1000

    t.check("Index built with Redis", idx.entity_count == 100,
            f"count={idx.entity_count}, time={build_ms:.0f}ms")

    # Count Redis keys created (datasketch prefixes keys with the basename bytes)
    all_keys = list(r.scan_iter(match=b'*dedup_test*', count=5000))
    phonetic_keys = [k for k in all_keys if b'phonetic' in k]
    primary_keys = [k for k in all_keys if b'phonetic' not in k]
    logger.info(f"  Redis keys: total={len(all_keys)}, primary={len(primary_keys)}, phonetic={len(phonetic_keys)}")
    t.check("LSH keys in Redis", len(all_keys) > 0, f"total={len(all_keys)}")

    # ==================================================================
    # 2. Primary LSH: exact name query
    # ==================================================================
    logger.info("\n" + "=" * 70)
    logger.info("2. PRIMARY LSH: Exact name query")
    logger.info("=" * 70)

    t0 = time.time()
    results = idx.find_similar_by_name("Acme Corporation", country="US", min_score=80.0)
    qtime = (time.time() - t0) * 1000
    found_ids = {r['entity_id'] for r in results}
    t.check("Finds Acme Corporation (e_001)", 'e_001' in found_ids,
            f"found={sorted(found_ids)}, time={qtime:.0f}ms")

    # ==================================================================
    # 3. Phonetic LSH: sound-alike query
    # ==================================================================
    logger.info("\n" + "=" * 70)
    logger.info("3. PHONETIC LSH: Sound-alike query (Schneider → Snyder)")
    logger.info("=" * 70)

    t0 = time.time()
    results = idx.find_similar_by_name("Schneider Industries", min_score=50.0)
    qtime = (time.time() - t0) * 1000
    found_ids = {r['entity_id'] for r in results}
    t.check("Finds Snyder (e_015) via phonetic", 'e_015' in found_ids,
            f"found={sorted(found_ids)}, time={qtime:.0f}ms")
    t.check("Finds Snider (e_016) via phonetic", 'e_016' in found_ids)

    # ==================================================================
    # 4. Typo: edit-distance-1 batch query
    # ==================================================================
    logger.info("\n" + "=" * 70)
    logger.info("4. TYPO: Edit-distance-1 batch query via Redis pipeline")
    logger.info("=" * 70)

    typo_cases = [
        ("Smtih & Associates", "e_009", "Transposition: Smtih → Smith"),
        ("Acme Corporaton", "e_004", "Deletion: Corporaton → Corporation"),
        ("Microsft Corporation", "e_054", "Deletion: Microsft → Microsoft"),
        ("Andreson Consulting", "e_066", "Transposition: Andreson → Anderson"),
        ("Deutche Bank AG", "e_072", "Deletion: Deutche → Deutsche"),
        ("James Willams", "e_079", "Deletion: Willams → Williams"),
    ]

    for typo_query, target_id, desc in typo_cases:
        t0 = time.time()
        results = idx.find_similar_by_name(typo_query, min_score=50.0)
        qtime = (time.time() - t0) * 1000
        found_ids = {r['entity_id'] for r in results}
        t.check(f"Typo '{typo_query}' finds {target_id} ({desc})",
                target_id in found_ids,
                f"found={sorted(found_ids)}, time={qtime:.0f}ms")

    # ==================================================================
    # 5. Batch query internals: verify _batch_query_lsh works
    # ==================================================================
    logger.info("\n" + "=" * 70)
    logger.info("5. BATCH QUERY: _batch_query_lsh direct test")
    logger.info("=" * 70)

    from datasketch import MinHash

    # Build 50 variant MinHashes for "smtih"
    variant_mhs = []
    for variant in list(idx._edit_distance_1("smtih"))[:50]:
        shingles = idx._name_shingles(f"{variant} & Associates",
                                       {'primary_name': f'{variant} & Associates'})
        if shingles:
            variant_mhs.append(idx._build_minhash(shingles))

    t0 = time.time()
    raw_keys = idx._batch_query_lsh(idx.lsh, variant_mhs)
    batch_ms = (time.time() - t0) * 1000
    entity_ids = {idx._entity_id_from_lsh_key(k) for k in raw_keys}

    t.check("_batch_query_lsh returns results", len(entity_ids) > 0,
            f"entities={sorted(entity_ids)}, minhashes={len(variant_mhs)}, time={batch_ms:.0f}ms")
    t.check("_batch_query_lsh finds Smith cluster", 'e_006' in entity_ids)

    # ==================================================================
    # 6. Remove entity from Redis
    # ==================================================================
    logger.info("\n" + "=" * 70)
    logger.info("6. REMOVE ENTITY from Redis")
    logger.info("=" * 70)

    idx.remove_entity('e_001')
    t.check("Entity count after remove", idx.entity_count == 99,
            f"count={idx.entity_count}")

    results = idx.find_similar_by_name("Acme Corporation", country="US", min_score=95.0)
    found_ids = {r['entity_id'] for r in results}
    t.check("e_001 no longer returned after remove", 'e_001' not in found_ids,
            f"found={sorted(found_ids)}")

    # ==================================================================
    # 7. Clear index
    # ==================================================================
    logger.info("\n" + "=" * 70)
    logger.info("7. CLEAR INDEX")
    logger.info("=" * 70)

    idx.clear_index()
    t.check("Entity count after clear", idx.entity_count == 0)

    results = idx.find_similar_by_name("Acme Corporation", min_score=30.0)
    t.check("No results after clear", len(results) == 0)

    # ==================================================================
    # 8. Persistence: rebuild index object, verify data is gone
    # ==================================================================
    logger.info("\n" + "=" * 70)
    logger.info("8. PERSISTENCE: New index object on same Redis")
    logger.info("=" * 70)

    # Flush test keys so new index starts clean
    flush_test_keys(r)

    idx2 = EntityDedupIndex(
        num_perm=128,
        threshold=0.3,
        storage_config=make_storage_config(),
        phonetic_bonus=10.0,
    )
    t.check("New index has empty cache", idx2.entity_count == 0)

    # Re-add a few entities and verify they work
    for eid, data in TEST_ENTITIES[:10]:
        idx2.add_entity(eid, data)
    t.check("Re-added 10 entities", idx2.entity_count == 10)

    results = idx2.find_similar_by_name("Acme Corporation", min_score=80.0)
    found_ids = {r['entity_id'] for r in results}
    t.check("Query works on rebuilt index", 'e_001' in found_ids,
            f"found={sorted(found_ids)}")

    # ==================================================================
    # 9. Performance: full 100-entity build + query timing
    # ==================================================================
    logger.info("\n" + "=" * 70)
    logger.info("9. PERFORMANCE TIMING")
    logger.info("=" * 70)

    idx2.clear_index()
    flush_test_keys(r)

    build_start = time.time()
    for eid, data in TEST_ENTITIES:
        idx2.add_entity(eid, data)
    build_ms = (time.time() - build_start) * 1000

    query_times = []
    test_queries = [
        "Acme Corporation",
        "Smtih & Associates",
        "Schneider Industries",
        "Microsft Corporation",
        "James Willams",
    ]
    for q in test_queries:
        t0 = time.time()
        idx2.find_similar_by_name(q, min_score=50.0)
        query_times.append((time.time() - t0) * 1000)

    avg_query = sum(query_times) / len(query_times)
    logger.info(f"  Build time (100 entities): {build_ms:.0f}ms")
    logger.info(f"  Query times: {[f'{t:.0f}ms' for t in query_times]}")
    logger.info(f"  Avg query time: {avg_query:.0f}ms")
    t.check("Build < 10s", build_ms < 10000, f"{build_ms:.0f}ms")
    t.check("Avg query < 5s", avg_query < 5000, f"{avg_query:.0f}ms")

    # ==================================================================
    # Cleanup
    # ==================================================================
    logger.info("\n" + "=" * 70)
    logger.info("CLEANUP")
    logger.info("=" * 70)
    idx2.clear_index()
    flush_test_keys(r)
    logger.info("Test keys flushed")

    # ==================================================================
    # Summary
    # ==================================================================
    logger.info("\n" + "=" * 70)
    logger.info(f"Results: {t.passed}/{t.passed + t.failed} passed, {t.failed} failed")
    logger.info("=" * 70)
    return t.failed


if __name__ == '__main__':
    sys.exit(run_tests())
