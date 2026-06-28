#!/usr/bin/env python3
"""
Test datasketch Redis Cluster integration against MemoryDB.

Requires VPN access to the MemoryDB cluster. Run with:

    python test_scripts/test_fuzzy_cluster.py

Uses the same env vars as the production service:
    ENTITY_FUZZY_REDIS_HOST, ENTITY_FUZZY_REDIS_PORT,
    ENTITY_FUZZY_REDIS_USERNAME, ENTITY_FUZZY_REDIS_PASSWORD,
    ENTITY_FUZZY_REDIS_SSL, ENTITY_FUZZY_REDIS_CLUSTER
"""

import os
import sys
import time

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# Use a test-specific namespace so cluster tests don't collide with prod keys
os.environ.setdefault('VITALGRAPH_ENVIRONMENT', 'test_cluster')

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
logger = logging.getLogger(__name__)

import random as _random

from datasketch import MinHash
from vitalgraph.entity_registry.datasketch_cluster import register_cluster_storage
from vitalgraph.entity_registry.entity_fuzzy import EntityFuzzyIndex

# Load dictionary words for realistic entity names
_WORDS = []
try:
    with open('/usr/share/dict/words') as f:
        _WORDS = [w.strip() for w in f if w.strip().isalpha() and len(w.strip()) > 3]
except FileNotFoundError:
    _WORDS = [f'word{i}' for i in range(5000)]


def _random_company_name(rng=None):
    """Generate a random company-like name from dictionary words."""
    r = rng or _random
    n_words = r.choice([2, 3, 3, 4])
    words = [r.choice(_WORDS).capitalize() for _ in range(n_words)]
    suffix = r.choice(['Corp', 'Inc', 'LLC', 'Ltd', 'Group', 'Holdings',
                       'Partners', 'Solutions', 'Industries', 'Technologies'])
    return ' '.join(words) + ' ' + suffix


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_entity(name, aliases=None, country=None, region=None, locality=None):
    """Build a minimal entity dict."""
    ent = {
        'primary_name': name,
        'type_key': 'organization',
        'country': country,
        'region': region,
        'locality': locality,
        'aliases': [{'alias_name': a} for a in (aliases or [])],
    }
    return ent


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_registration():
    """Verify the cluster storage type is registered."""
    import datasketch.lsh as lsh_mod
    # After registration, the factory should handle 'redis_cluster'
    register_cluster_storage()
    from vitalgraph.entity_registry.datasketch_cluster import _REGISTERED
    assert _REGISTERED, "Storage type not registered"
    print("  PASS: redis_cluster storage type registered")
    return True


def test_create_index():
    """Create an EntityFuzzyIndex with cluster config from env."""
    idx = EntityFuzzyIndex.from_env()
    assert idx.storage_config is not None, "Expected Redis storage config"
    assert idx.storage_config['type'] == 'redis_cluster', "Expected type=redis_cluster"
    # Clear any stale data from previous runs
    idx.clear_index()
    print(f"  PASS: Index created and cleared (basename={idx.storage_config['basename']})")
    return idx


def test_insert_and_query(idx):
    """Insert entities and verify fuzzy query finds candidates."""
    # Insert test entities
    idx.add_entity('test_e1', make_entity('Acme Corporation', aliases=['ACME Corp']))
    idx.add_entity('test_e2', make_entity('Acme Corp International'))
    idx.add_entity('test_e3', make_entity('Totally Different Company'))
    print("  PASS: 3 entities inserted into cluster")

    # Query for similar
    results = idx.find_similar_by_name('Acme Corp')
    found_ids = {r['entity_id'] for r in results}
    assert 'test_e1' in found_ids or 'test_e2' in found_ids, \
        f"Expected Acme match, got: {found_ids}"
    assert 'test_e3' not in found_ids, \
        f"Did not expect 'Totally Different Company' in results: {found_ids}"
    print(f"  PASS: Fuzzy query returned {len(results)} candidates: {found_ids}")
    return True


def test_remove(idx):
    """Remove entities and verify they're gone."""
    idx.remove_entity('test_e1')
    idx.remove_entity('test_e2')
    idx.remove_entity('test_e3')

    results = idx.find_similar_by_name('Acme Corporation')
    found_ids = {r['entity_id'] for r in results}
    assert 'test_e1' not in found_ids, "test_e1 should be removed"
    print("  PASS: Entities removed from cluster")
    return True


def test_batch_insert_unbuffered(idx, n=20):
    """Insert N entities WITHOUT pipelining (baseline)."""
    start = time.time()
    for i in range(n):
        idx.add_entity(f'unbuf_{i}', make_entity(f'Unbuffered Test Entity {i}'))
    elapsed = time.time() - start
    rate = n / elapsed
    print(f"  {n} entities (unbuffered): {elapsed:.1f}s ({rate:.1f} entities/s)")
    # Cleanup
    for i in range(n):
        idx.remove_entity(f'unbuf_{i}')
    return rate


def test_bulk_insert(idx, n=1000):
    """Insert N entities with random dict-word names via one pipeline flush."""
    rng = _random.Random(42)
    batch = []
    for i in range(n):
        name = _random_company_name(rng)
        alias = _random_company_name(rng)
        batch.append((f'bulk_{i}', make_entity(name, aliases=[alias])))

    # Remember one name for query verification
    query_name = batch[0][1]['primary_name']

    start = time.time()
    idx._bulk_insert_entities(batch)
    elapsed = time.time() - start
    rate = n / elapsed
    print(f"  {n} entities (bulk pipeline): {elapsed:.1f}s ({rate:.0f} entities/s)")
    print(f"  Projected 1M entities: {1_000_000 / rate / 60:.1f} minutes")

    # Verify a query works against bulk-inserted data
    results = idx.find_similar_by_name(query_name)
    found = {r['entity_id'] for r in results}
    print(f"  Query for '{query_name}':")
    for r in sorted(results, key=lambda x: x.get('score', 0), reverse=True):
        print(f"    {r['entity_id']:>12s}  score={r.get('score', 0):5.1f}  {r.get('primary_name', '?')}")
    assert 'bulk_0' in found, f"Expected bulk_0 in results, got {found}"
    print(f"  PASS: {len(found)} candidates found")

    # Cleanup
    idx.clear_index()
    return rate


def test_clear_index(idx):
    """Test clear_index with distributed lock."""
    idx.add_entity('clear_test_1', make_entity('Clear Test Entity'))
    idx.clear_index()
    assert not idx._initialized, "Should be uninitialized after clear"
    print("  PASS: clear_index completed with lock")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("datasketch Redis Cluster (MemoryDB) Integration Test")
    print("=" * 60)

    results = {}

    print("\n1. Registering cluster storage...")
    results['register'] = test_registration()

    print("\n2. Creating index from env...")
    idx = test_create_index()
    results['create'] = idx is not None

    print("\n3. Insert and query...")
    results['insert_query'] = test_insert_and_query(idx)

    print("\n4. Remove entities...")
    results['remove'] = test_remove(idx)

    print("\n5. Bulk insert (1000 entities, one pipeline flush)...")
    bulk_rate = test_bulk_insert(idx, n=1000)
    results['batch'] = bulk_rate > 0

    print("\n6. Clear index with lock...")
    results['clear'] = test_clear_index(idx)

    # Summary
    print("\n" + "=" * 60)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
    print("=" * 60)

    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
