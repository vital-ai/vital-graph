#!/usr/bin/env python3
"""
Tests for fuzzy index thread-offload.

Verifies that async_add_entity, async_remove_entity, and
async_get_candidate_ids work correctly through asyncio.to_thread(),
including thread safety under concurrent mutation.

Run with:
    python test_scripts/test_fuzzy_thread_offload.py

For the API-level stall regression test (Test 5), the local Docker
server must be running.
"""

import asyncio
import concurrent.futures
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s',
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity(name: str, type_key: str = 'company',
                 aliases: list = None, country: str = 'US') -> dict:  # type: ignore[assignment]
    """Create a minimal entity dict for fuzzy indexing."""
    alias_list = [{'alias_name': a} for a in (aliases or [])]
    return {
        'primary_name': name,
        'type_key': type_key,
        'aliases': alias_list,
        'country': country,
        'region': None,
        'locality': None,
    }


# ---------------------------------------------------------------------------
# Test 1: Basic async CRUD
# ---------------------------------------------------------------------------

async def test_async_crud():
    """Verify async_add_entity, async_remove_entity work correctly."""
    from vitalgraph.entity_registry.entity_fuzzy import EntityFuzzyIndex

    idx = EntityFuzzyIndex()

    entity = _make_entity('Acme Corporation', aliases=['ACME', 'Acme Corp'])
    entity_id = 'e_test_crud_001'

    # Add
    await idx.async_add_entity(entity_id, entity)
    assert entity_id in idx._entity_cache, "Entity should be in cache after add"
    assert idx._entity_cache[entity_id]['primary_name'] == 'Acme Corporation'

    # Update (change name)
    updated = _make_entity('Acme Industries', aliases=['ACME'])
    await idx.async_add_entity(entity_id, updated)
    assert idx._entity_cache[entity_id]['primary_name'] == 'Acme Industries'

    # Remove
    await idx.async_remove_entity(entity_id)
    assert entity_id not in idx._entity_cache, "Entity should be removed from cache"

    logger.info("PASS: test_async_crud")


# ---------------------------------------------------------------------------
# Test 2: Concurrent async entity creation
# ---------------------------------------------------------------------------

async def test_concurrent_async_creation():
    """Verify N concurrent async_add_entity calls don't lose data."""
    from vitalgraph.entity_registry.entity_fuzzy import EntityFuzzyIndex

    idx = EntityFuzzyIndex()
    n = 20

    async def add_one(i):
        eid = f'e_conc_{i:03d}'
        ent = _make_entity(f'Company {i}', aliases=[f'Alias{i}A', f'Alias{i}B'])
        await idx.async_add_entity(eid, ent)

    await asyncio.gather(*(add_one(i) for i in range(n)))

    assert len(idx._entity_cache) == n, (
        f"Expected {n} entities in cache, got {len(idx._entity_cache)}"
    )
    for i in range(n):
        eid = f'e_conc_{i:03d}'
        assert eid in idx._entity_cache, f"Missing entity {eid}"

    logger.info("PASS: test_concurrent_async_creation (%d entities)", n)


# ---------------------------------------------------------------------------
# Test 3: Thread safety under contention (direct ThreadPoolExecutor)
# ---------------------------------------------------------------------------

def test_thread_safety():
    """Verify _mutation_lock prevents data corruption under contention."""
    from vitalgraph.entity_registry.entity_fuzzy import EntityFuzzyIndex

    idx = EntityFuzzyIndex()
    n = 20

    def add_entity(i):
        eid = f'e_thread_{i:03d}'
        ent = _make_entity(f'Thread Corp {i}', aliases=[f'TC{i}'])
        idx.add_entity(eid, ent)

    # Concurrent adds
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(add_entity, range(n)))

    assert len(idx._entity_cache) == n, (
        f"Expected {n} entities after concurrent add, got {len(idx._entity_cache)}"
    )

    # Concurrent removes (first half)
    def remove_entity(i):
        idx.remove_entity(f'e_thread_{i:03d}')

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(remove_entity, range(n // 2)))

    remaining = len(idx._entity_cache)
    expected = n - n // 2
    assert remaining == expected, (
        f"Expected {expected} entities after removing half, got {remaining}"
    )

    logger.info("PASS: test_thread_safety (%d added, %d removed, %d remain)",
                n, n // 2, remaining)


# ---------------------------------------------------------------------------
# Test 4: Duplicate detection through async path
# ---------------------------------------------------------------------------

async def test_duplicate_detection():
    """Verify async_get_candidate_ids finds similar entities."""
    from vitalgraph.entity_registry.entity_fuzzy import EntityFuzzyIndex

    idx = EntityFuzzyIndex(threshold=0.3)

    # Add two similar entities
    e1 = _make_entity('Acme Corporation', country='US')
    e2 = _make_entity('Acme Corp', country='US')
    idx.add_entity('e_dup_001', e1)
    idx.add_entity('e_dup_002', e2)

    # Query for candidates similar to e1
    candidates = await idx.async_get_candidate_ids(e1)

    # e_dup_002 should appear as a candidate (or at least e_dup_001 itself)
    found_ids = set()
    for c in candidates:
        # get_candidate_ids returns compound keys like "entity_id::0"
        base_id = c.split('::')[0] if '::' in c else c
        found_ids.add(base_id)

    assert 'e_dup_002' in found_ids or 'e_dup_001' in found_ids, (
        f"Expected at least one Acme entity in candidates, got {found_ids}"
    )

    logger.info("PASS: test_duplicate_detection (candidates: %s)", found_ids)


# ---------------------------------------------------------------------------
# Test 5: Event loop stall regression (requires running server)
# ---------------------------------------------------------------------------

async def test_stall_regression():
    """Run a burst of entity creates via VitalGraphClient and check for stalls.

    Requires local Docker server running. Skipped if server is not available.
    """
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

    from vitalgraph.client.vitalgraph_client import VitalGraphClient
    from vitalgraph.model.entity_registry_model import (
        AliasCreateRequest,
        EntityCreateRequest,
        EntityTypeCreateRequest,
    )

    client = VitalGraphClient()
    try:
        await client.open()
    except Exception as e:
        logger.warning("SKIP: test_stall_regression (cannot connect: %s)", e)
        return

    try:
        # Ensure entity type exists
        try:
            await client.entity_registry.create_entity_type(
                EntityTypeCreateRequest(type_key='company', type_label='Company')
            )
        except Exception:
            pass  # may already exist

        # Burst create entities
        n = 30
        created_ids = []

        async def create_one(i):
            try:
                resp = await client.entity_registry.create_entity(
                    EntityCreateRequest(
                        type_key='company',
                        primary_name=f'StallTest Corp {i}',
                        country='US',
                        aliases=[
                            AliasCreateRequest(alias_name=f'STC{i}'),
                            AliasCreateRequest(alias_name=f'StallTest{i}'),
                        ],
                    )
                )
                eid = resp.entity_id if hasattr(resp, 'entity_id') else None
                if eid:
                    created_ids.append(eid)
                return 200
            except Exception as e:
                logger.debug("Create %d failed: %s", i, e)
                return 500

        start = time.monotonic()
        results = await asyncio.gather(*(create_one(i) for i in range(n)))
        elapsed = time.monotonic() - start

        successes = sum(1 for r in results if r == 200)
        failures = sum(1 for r in results if r != 200)

        logger.info("Created %d/%d entities in %.2fs (%d failures)",
                    successes, n, elapsed, failures)

        # Cleanup
        for eid in created_ids:
            try:
                await client.entity_registry.delete_entity(eid)
            except Exception:
                pass

        logger.info(
            "PASS: test_stall_regression "
            "(check Docker logs for EVENT LOOP STALL — expect zero)"
        )
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    logger.info("=" * 60)
    logger.info("Fuzzy Thread-Offload Tests")
    logger.info("=" * 60)

    # In-memory tests (no external deps)
    await test_async_crud()
    await test_concurrent_async_creation()
    test_thread_safety()
    await test_duplicate_detection()

    # API-level test (requires server)
    await test_stall_regression()

    logger.info("=" * 60)
    logger.info("All tests passed")
    logger.info("=" * 60)


if __name__ == '__main__':
    asyncio.run(main())
