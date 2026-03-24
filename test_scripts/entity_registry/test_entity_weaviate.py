#!/usr/bin/env python3
"""
Direct test script for Entity Registry Weaviate integration.

Tests schema creation, entity upsert/delete, and topic search against a live Weaviate instance.
Requires ENTITY_WEAVIATE_ENABLED=true and valid WEAVIATE_* env vars.

Usage:
    ENTITY_WEAVIATE_ENABLED=true python test_scripts/entity_registry/test_entity_weaviate.py
"""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

from vitalgraph.entity_registry.entity_weaviate import EntityWeaviateIndex
from vitalgraph.entity_registry.entity_weaviate_schema import (
    get_collection_name,
    build_search_text,
    entity_id_to_weaviate_uuid,
    entity_to_weaviate_properties,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)


class WeaviateTestRunner:
    """Runs Weaviate integration tests."""

    def __init__(self):
        self.tests_passed = 0
        self.tests_failed = 0
        self.index = None

    def _report(self, test_name: str, passed: bool, detail: str = ""):
        if passed:
            self.tests_passed += 1
            logger.info(f"  ✅ PASS: {test_name}{' - ' + detail if detail else ''}")
        else:
            self.tests_failed += 1
            logger.info(f"  ❌ FAIL: {test_name}{' - ' + detail if detail else ''}")

    async def run_all(self):
        logger.info("=" * 60)
        logger.info("Entity Weaviate Integration Tests")
        logger.info("=" * 60)

        # Test schema utilities first (no Weaviate needed)
        self.test_schema_utilities()

        # Connect to Weaviate
        self.index = EntityWeaviateIndex.from_env()
        if not self.index:
            logger.error("Cannot connect to Weaviate. Set ENTITY_WEAVIATE_ENABLED=true and WEAVIATE_* env vars.")
            return

        try:
            self.test_ensure_collection()
            self.test_upsert_entity()
            self.test_search_topic()
            self.test_search_with_filters()
            self.test_search_with_category_filter()
            self.test_delete_entity()
            self.test_status()
        finally:
            self.index.close()

        logger.info("=" * 60)
        total = self.tests_passed + self.tests_failed
        logger.info(f"Results: {self.tests_passed}/{total} passed, {self.tests_failed} failed")
        logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Schema utility tests (no Weaviate required)
    # ------------------------------------------------------------------

    def test_schema_utilities(self):
        logger.info("\n--- Test: Schema Utilities ---")

        # UUID determinism
        uuid1 = entity_id_to_weaviate_uuid("e_test123")
        uuid2 = entity_id_to_weaviate_uuid("e_test123")
        uuid3 = entity_id_to_weaviate_uuid("e_other456")
        self._report("UUID deterministic", uuid1 == uuid2)
        self._report("UUID unique per entity", uuid1 != uuid3)

        # search_text construction
        entity = {
            'primary_name': 'ABC Plumbing LLC',
            'type_label': 'Business',
            'type_description': 'A business or company',
            'description': 'Licensed plumbing contractor',
            'category_labels': 'Customer|Vendor',
            'country': 'US',
            'region': 'NJ',
            'locality': 'Newark',
        }
        text = build_search_text(entity)
        self._report("search_text contains name", 'ABC Plumbing LLC' in text)
        self._report("search_text contains type", 'Business' in text)
        self._report("search_text contains description", 'plumbing contractor' in text)
        self._report("search_text contains categories", 'Customer|Vendor' in text)
        self._report("search_text contains location", 'Newark' in text and 'NJ' in text)

        # entity_to_weaviate_properties
        full_entity = {
            'entity_id': 'e_test123',
            'primary_name': 'Test Corp',
            'description': 'A test corporation',
            'notes': 'Some notes',
            'type_key': 'business',
            'type_label': 'Business',
            'type_description': 'A business',
            'country': 'US',
            'region': 'CA',
            'locality': 'LA',
            'website': 'https://test.com',
            'status': 'active',
            'aliases': [
                {'alias_name': 'TC'},
                {'alias_name': 'TestCo'},
            ],
            'categories': [
                {'category_key': 'customer', 'category_label': 'Customer'},
                {'category_key': 'vendor', 'category_label': 'Vendor'},
            ],
        }
        props = entity_to_weaviate_properties(full_entity)
        self._report("Props has entity_id", props['entity_id'] == 'e_test123')
        self._report("Props has aliases", props['aliases'] == 'TC|TestCo')
        self._report("Props has category_keys", props['category_keys'] == ['customer', 'vendor'])
        self._report("Props has category_labels", props['category_labels'] == 'Customer|Vendor')
        self._report("Props has search_text", len(props['search_text']) > 0)

    # ------------------------------------------------------------------
    # Weaviate integration tests
    # ------------------------------------------------------------------

    def test_ensure_collection(self):
        logger.info("\n--- Test: Ensure Collection ---")
        result = self.index.ensure_collection()
        self._report("ensure_collection succeeds", result is True)

    def test_upsert_entity(self):
        logger.info("\n--- Test: Upsert Entity ---")

        # Upsert test entities
        entities = [
            {
                'entity_id': 'e_wv_test_001',
                'primary_name': 'ABC Plumbing LLC',
                'description': 'Licensed plumbing contractor serving residential and commercial clients in Newark NJ area',
                'type_key': 'business', 'type_label': 'Business', 'type_description': 'A business or company',
                'country': 'US', 'region': 'NJ', 'locality': 'Newark',
                'website': 'https://abcplumbing.com', 'status': 'active', 'notes': '',
                'aliases': [{'alias_name': 'ABC Plumbing'}, {'alias_name': 'ABC P LLC'}],
                'categories': [{'category_key': 'customer', 'category_label': 'Customer'}],
            },
            {
                'entity_id': 'e_wv_test_002',
                'primary_name': 'Garden State Electric',
                'description': 'Full-service electrical contractor specializing in residential wiring and panel upgrades',
                'type_key': 'business', 'type_label': 'Business', 'type_description': 'A business or company',
                'country': 'US', 'region': 'NJ', 'locality': 'Trenton',
                'website': '', 'status': 'active', 'notes': '',
                'aliases': [{'alias_name': 'GS Electric'}],
                'categories': [{'category_key': 'vendor', 'category_label': 'Vendor'}],
            },
            {
                'entity_id': 'e_wv_test_003',
                'primary_name': 'Environmental Protection Agency',
                'description': 'Federal government agency responsible for environmental regulation and enforcement',
                'type_key': 'government', 'type_label': 'Government', 'type_description': 'A government entity',
                'country': 'US', 'region': '', 'locality': 'Washington DC',
                'website': 'https://epa.gov', 'status': 'active', 'notes': '',
                'aliases': [{'alias_name': 'EPA'}],
                'categories': [{'category_key': 'regulator', 'category_label': 'Regulator'}],
            },
            {
                'entity_id': 'e_wv_test_004',
                'primary_name': 'TechVenture Software Consulting',
                'description': 'Software consulting firm specializing in cloud architecture and DevOps transformation',
                'type_key': 'business', 'type_label': 'Business', 'type_description': 'A business or company',
                'country': 'US', 'region': 'CA', 'locality': 'San Francisco',
                'website': '', 'status': 'active', 'notes': '',
                'aliases': [{'alias_name': 'TechVenture'}, {'alias_name': 'TV Consulting'}],
                'categories': [
                    {'category_key': 'vendor', 'category_label': 'Vendor'},
                    {'category_key': 'partner', 'category_label': 'Partner'},
                ],
            },
        ]

        for entity in entities:
            result = self.index.upsert_entity(entity)
            self._report(f"Upsert {entity['entity_id']}", result is True)

        # Re-upsert (idempotent)
        result = self.index.upsert_entity(entities[0])
        self._report("Re-upsert is idempotent", result is True)

        # Batch upsert
        count = self.index.upsert_entities_batch(entities)
        self._report("Batch upsert", count == len(entities), f"count={count}")

    def test_search_topic(self):
        logger.info("\n--- Test: Topic Search ---")

        # Wait briefly for vectorization
        time.sleep(2)

        # Search for plumbing
        results = self.index.search_topic("plumbing contractor", limit=5)
        self._report("Search 'plumbing' returns results", len(results) > 0, f"count={len(results)}")
        if results:
            top = results[0]
            self._report("Top result is ABC Plumbing",
                         top['entity_id'] == 'e_wv_test_001',
                         f"got={top['entity_id']} name={top['primary_name']}")
            self._report("Result has score", top['score'] > 0, f"score={top['score']}")
            self._report("Result has distance", 'distance' in top)

        # Search for environmental regulation
        results2 = self.index.search_topic("environmental regulation agency", limit=5)
        self._report("Search 'environmental regulation' returns results", len(results2) > 0)
        if results2:
            self._report("EPA in results",
                         any(r['entity_id'] == 'e_wv_test_003' for r in results2))

        # Search for software consulting
        results3 = self.index.search_topic("software consulting cloud", limit=5)
        self._report("Search 'software consulting' returns results", len(results3) > 0)
        if results3:
            self._report("TechVenture in results",
                         any(r['entity_id'] == 'e_wv_test_004' for r in results3))

    def test_search_with_filters(self):
        logger.info("\n--- Test: Search with Filters ---")

        # Filter by type
        results = self.index.search_topic("contractor", type_key="business", limit=5)
        self._report("Type filter returns results", len(results) > 0)
        if results:
            all_business = all(r['type_key'] == 'business' for r in results)
            self._report("All results are businesses", all_business)

        # Filter by location
        results2 = self.index.search_topic("contractor", region="NJ", limit=5)
        self._report("Region filter returns results", len(results2) > 0)
        if results2:
            all_nj = all(r['region'] == 'NJ' for r in results2)
            self._report("All results in NJ", all_nj)

        # Filter by type + location
        results3 = self.index.search_topic("contractor", type_key="government", region="NJ", limit=5)
        self._report("Type+region filter (no matches)", len(results3) == 0)

    def test_search_with_category_filter(self):
        logger.info("\n--- Test: Search with Category Filter ---")

        # Filter by category: vendor
        results = self.index.search_topic("contractor", category_key="vendor", limit=5)
        self._report("Category vendor filter returns results", len(results) > 0)
        if results:
            all_vendor = all('vendor' in r.get('category_keys', []) for r in results)
            self._report("All results have vendor category", all_vendor,
                         f"categories={[r.get('category_keys') for r in results]}")

        # Filter by category: customer (lower certainty — combined filter is narrow)
        results2 = self.index.search_topic("plumbing", category_key="customer", min_certainty=0.5, limit=5)
        self._report("Category customer + plumbing returns results", len(results2) > 0)
        if results2:
            self._report("ABC Plumbing in customer results",
                         any(r['entity_id'] == 'e_wv_test_001' for r in results2))

    def test_delete_entity(self):
        logger.info("\n--- Test: Delete Entity ---")

        result = self.index.delete_entity('e_wv_test_002')
        self._report("Delete entity", result is True)

        # Verify deleted — search should not find it
        time.sleep(1)
        results = self.index.search_topic("Garden State Electric", min_certainty=0.5, limit=5)
        found = any(r['entity_id'] == 'e_wv_test_002' for r in results)
        self._report("Deleted entity not in results", not found)

        # Clean up remaining test entities
        for eid in ['e_wv_test_001', 'e_wv_test_003', 'e_wv_test_004']:
            self.index.delete_entity(eid)
        logger.info("  Cleaned up test entities")

    def test_status(self):
        logger.info("\n--- Test: Status ---")
        status = self.index.get_status()
        self._report("Status has 'exists'", 'exists' in status)
        self._report("Collection exists", status.get('exists') is True)
        self._report("Status has object_count", 'object_count' in status,
                     f"count={status.get('object_count')}")


if __name__ == '__main__':
    runner = WeaviateTestRunner()
    asyncio.run(runner.run_all())
