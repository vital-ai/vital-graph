#!/usr/bin/env python3
"""
Direct tests for Entity Registry near-duplicate detection.

Tests the EntityDedupIndex (datasketch MinHash LSH + RapidFuzz)
without the REST layer — uses asyncpg directly.

Usage:
    /opt/homebrew/anaconda3/envs/vital-graph/bin/python test_scripts/entity_registry/test_dedup.py
"""

import asyncio
import logging
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)


class DedupTestRunner:
    """Runs dedup index tests."""

    def __init__(self):
        self.tests_passed = 0
        self.tests_failed = 0
        self.registry = None
        self.created_entity_ids = []

    def check(self, name: str, passed: bool, detail: str = ""):
        if passed:
            self.tests_passed += 1
            logger.info(f"  ✅ {name}{' - ' + detail if detail else ''}")
        else:
            self.tests_failed += 1
            logger.error(f"  ❌ {name}{' - ' + detail if detail else ''}")

    async def setup(self):
        """Create registry with dedup index and seed test entities."""
        import asyncpg
        from vitalgraph.entity_registry.entity_registry_impl import EntityRegistryImpl
        from vitalgraph.entity_registry.entity_dedup import EntityDedupIndex

        pool = await asyncpg.create_pool(
            host='localhost', port=5432,
            user='postgres', password='',
            database='fuseki_sql_graph',
            min_size=2, max_size=5,
        )

        dedup_index = EntityDedupIndex(num_perm=128, threshold=0.3)
        self.registry = EntityRegistryImpl(pool, dedup_index=dedup_index)
        await self.registry.ensure_tables()
        logger.info("Registry with dedup index initialized")

    async def create_test_entity(self, name, type_key='business', country=None,
                                  region=None, aliases=None):
        """Helper to create a test entity and track it."""
        alias_dicts = None
        if aliases:
            alias_dicts = [{'alias_name': a, 'alias_type': 'aka'} for a in aliases]
        entity = await self.registry.create_entity(
            type_key=type_key, primary_name=name,
            country=country, region=region,
            aliases=alias_dicts, created_by='dedup_test',
        )
        self.created_entity_ids.append(entity['entity_id'])
        return entity

    async def cleanup(self):
        """Delete all test entities."""
        for eid in self.created_entity_ids:
            try:
                await self.registry.delete_entity(eid, deleted_by='dedup_test')
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    async def test_exact_name_match(self):
        logger.info("\n--- Exact Name Match ---")
        e1 = await self.create_test_entity("Acme Corporation", country='US')

        results = self.registry.find_similar("Acme Corporation")
        found_ids = [r['entity_id'] for r in results]
        self.check("Exact name found", e1['entity_id'] in found_ids, f"results={len(results)}")
        if results:
            match = next((r for r in results if r['entity_id'] == e1['entity_id']), None)
            if match:
                self.check("Score ~100 for exact match", match['score'] >= 95.0,
                           f"score={match['score']}")
                self.check("Match level is 'high'", match['match_level'] == 'high')

    async def test_similar_name(self):
        logger.info("\n--- Similar Name ---")
        e1 = await self.create_test_entity("Acme Corp", country='US')

        results = self.registry.find_similar("Acme Corporation")
        found_ids = [r['entity_id'] for r in results]
        self.check("Similar name found", e1['entity_id'] in found_ids, f"results={len(results)}")
        if results:
            match = next((r for r in results if r['entity_id'] == e1['entity_id']), None)
            if match:
                self.check("Score >= 70 for similar name", match['score'] >= 70.0,
                           f"score={match['score']}")

    async def test_alias_matching(self):
        logger.info("\n--- Alias Matching ---")
        e1 = await self.create_test_entity(
            "International Business Machines",
            aliases=["IBM", "Big Blue"],
            country='US',
        )

        # Short acronym matched via exact reverse name lookup (not LSH)
        results = self.registry.find_similar("IBM")
        found_ids = [r['entity_id'] for r in results]
        self.check("Alias 'IBM' matches via exact lookup", e1['entity_id'] in found_ids,
                    f"results={len(results)}")

        # Longer alias matched via LSH + exact lookup
        results = self.registry.find_similar("Big Blue")
        found_ids = [r['entity_id'] for r in results]
        self.check("Alias 'Big Blue' matches entity",
                    e1['entity_id'] in found_ids, f"results={len(results)}")

    async def test_different_entities(self):
        logger.info("\n--- Different Entities ---")
        await self.create_test_entity("Widget Manufacturing Inc", country='US')

        # "International" is a common word — may produce low-scoring candidates.
        # Verify no 'likely' or 'high' matches (score >= 70).
        results = self.registry.find_similar("Zebra Logistics International", min_score=70.0)
        for r in results:
            logger.info(f"    candidate: {r['primary_name']} score={r['score']}")
        self.check("No likely/high matches for unrelated name",
                   len(results) == 0, f"results={len(results)}")

    async def test_location_influence(self):
        logger.info("\n--- Location Influence ---")
        e1 = await self.create_test_entity("Smith & Associates", country='US', region='California')
        e2 = await self.create_test_entity("Smith & Associates", country='UK', region='London')

        results_us = self.registry.find_similar("Smith & Associates", country='US')
        results_uk = self.registry.find_similar("Smith & Associates", country='UK')

        self.check("US search finds results", len(results_us) >= 1, f"count={len(results_us)}")
        self.check("UK search finds results", len(results_uk) >= 1, f"count={len(results_uk)}")

        # Both entities should appear in both searches (name is identical)
        all_ids_us = [r['entity_id'] for r in results_us]
        all_ids_uk = [r['entity_id'] for r in results_uk]
        self.check("US entity in US results", e1['entity_id'] in all_ids_us)
        self.check("UK entity in UK results", e2['entity_id'] in all_ids_uk)

    async def test_index_add_remove(self):
        logger.info("\n--- Index Add/Remove ---")
        dedup = self.registry.dedup_index
        initial_count = dedup.entity_count

        e1 = await self.create_test_entity("Temporary Test Corp", country='US')
        self.check("Entity added to index", dedup.entity_count == initial_count + 1,
                    f"count={dedup.entity_count}")

        # Find it
        results = self.registry.find_similar("Temporary Test Corp")
        found_ids = [r['entity_id'] for r in results]
        self.check("Found in index after add", e1['entity_id'] in found_ids)

        # Delete it (soft-delete removes from index)
        await self.registry.delete_entity(e1['entity_id'], deleted_by='test')
        self.created_entity_ids.remove(e1['entity_id'])
        self.check("Entity removed from index", dedup.entity_count == initial_count,
                    f"count={dedup.entity_count}")

    async def test_min_score_filter(self):
        logger.info("\n--- Min Score Filter ---")
        await self.create_test_entity("Global Solutions Inc", country='US')

        # High threshold should return fewer results
        results_low = self.registry.find_similar("Global Solutions", min_score=30.0)
        results_high = self.registry.find_similar("Global Solutions", min_score=90.0)
        self.check("Lower threshold >= higher threshold results",
                    len(results_low) >= len(results_high),
                    f"low={len(results_low)}, high={len(results_high)}")

    async def test_empty_query(self):
        logger.info("\n--- Empty/Short Query ---")
        results = self.registry.find_similar("")
        self.check("Empty name returns no results", len(results) == 0)

    async def test_find_duplicates_for_entity(self):
        logger.info("\n--- Find Duplicates for Entity ---")
        e1 = await self.create_test_entity("National Bank of Commerce", country='US')
        e2 = await self.create_test_entity("National Bank of Commerce Inc", country='US')

        entity = await self.registry.get_entity(e1['entity_id'])
        results = self.registry.find_duplicates_for_entity(entity, limit=5)
        found_ids = [r['entity_id'] for r in results]
        self.check("Finds near-duplicate", e2['entity_id'] in found_ids,
                    f"results={len(results)}")
        self.check("Excludes self", e1['entity_id'] not in found_ids)

    async def test_dedup_index_stats(self):
        logger.info("\n--- Dedup Index Stats ---")
        dedup = self.registry.dedup_index
        self.check("Entity count > 0", dedup.entity_count > 0,
                    f"count={dedup.entity_count}")
        self.check("Index is initialized", dedup._initialized is True)

    async def run_all(self):
        logger.info("=" * 60)
        logger.info("Entity Dedup Index Tests")
        logger.info("=" * 60)

        await self.setup()

        try:
            await self.test_exact_name_match()
            await self.test_similar_name()
            await self.test_alias_matching()
            await self.test_different_entities()
            await self.test_location_influence()
            await self.test_index_add_remove()
            await self.test_min_score_filter()
            await self.test_empty_query()
            await self.test_find_duplicates_for_entity()
            await self.test_dedup_index_stats()
        finally:
            await self.cleanup()

        logger.info(f"\nResults: {self.tests_passed}/{self.tests_passed + self.tests_failed} passed, "
                     f"{self.tests_failed} failed")
        return self.tests_failed == 0


async def main():
    runner = DedupTestRunner()
    success = await runner.run_all()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    asyncio.run(main())
