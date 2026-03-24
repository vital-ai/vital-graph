#!/usr/bin/env python3
"""
Isolated test script for Weaviate LocationIndex + Entity↔Location cross-references.

Creates temporary test collections, populates them with entities and locations,
runs geo search queries (locations-near, topic-near, entities-near),
and cleans up by deleting the test collections.

Requires ENTITY_WEAVIATE_ENABLED=true and valid WEAVIATE_* env vars.

Usage:
    ENTITY_WEAVIATE_ENABLED=true python test_scripts/entity_registry/test_entity_weaviate_location.py
"""

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

# Override env to use isolated test collections
os.environ['ENTITY_WEAVIATE_ENV'] = 'wvloctest'

from vitalgraph.entity_registry.entity_weaviate import EntityWeaviateIndex
from vitalgraph.entity_registry.entity_weaviate_schema import (
    get_collection_name,
    get_location_collection_name,
    entity_id_to_weaviate_uuid,
    location_id_to_weaviate_uuid,
    entity_to_weaviate_properties,
    location_to_weaviate_properties,
    build_location_search_text,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

TEST_ENTITIES = [
    {
        'entity_id': 'e_loctest_001',
        'primary_name': 'Ace Plumbing & Heating',
        'description': 'Licensed plumbing and heating contractor serving residential and commercial clients',
        'type_key': 'business', 'type_label': 'Business', 'type_description': 'A business or company',
        'country': 'US', 'region': 'California', 'locality': 'San Francisco',
        'latitude': 37.7749, 'longitude': -122.4194,
        'website': '', 'status': 'active', 'notes': '',
        'aliases': [{'alias_name': 'Ace Plumbing'}],
        'categories': [{'category_key': 'vendor', 'category_label': 'Vendor'}],
    },
    {
        'entity_id': 'e_loctest_002',
        'primary_name': 'Bay Area Electric',
        'description': 'Full-service electrical contractor specializing in commercial wiring',
        'type_key': 'business', 'type_label': 'Business', 'type_description': 'A business or company',
        'country': 'US', 'region': 'California', 'locality': 'Oakland',
        'latitude': 37.8044, 'longitude': -122.2712,
        'website': '', 'status': 'active', 'notes': '',
        'aliases': [{'alias_name': 'BA Electric'}],
        'categories': [{'category_key': 'vendor', 'category_label': 'Vendor'}],
    },
    {
        'entity_id': 'e_loctest_003',
        'primary_name': 'NYC Plumbing Solutions',
        'description': 'Emergency plumbing repair and installation services across New York City',
        'type_key': 'business', 'type_label': 'Business', 'type_description': 'A business or company',
        'country': 'US', 'region': 'New York', 'locality': 'New York',
        'latitude': 40.7128, 'longitude': -74.0060,
        'website': '', 'status': 'active', 'notes': '',
        'aliases': [{'alias_name': 'NYC Plumbing'}],
        'categories': [{'category_key': 'vendor', 'category_label': 'Vendor'}],
    },
    {
        'entity_id': 'e_loctest_004',
        'primary_name': 'GreenTech Environmental Consulting',
        'description': 'Environmental consulting and sustainability advisory services',
        'type_key': 'business', 'type_label': 'Business', 'type_description': 'A business or company',
        'country': 'US', 'region': 'California', 'locality': 'San Jose',
        'latitude': 37.3382, 'longitude': -121.8863,
        'website': '', 'status': 'active', 'notes': '',
        'aliases': [],
        'categories': [{'category_key': 'partner', 'category_label': 'Partner'}],
    },
]

# Locations with geo coordinates — keyed by entity
TEST_LOCATIONS = [
    # Ace Plumbing — HQ in SF, branch in Oakland
    {
        'location_id': 90001,
        'entity_id': 'e_loctest_001',
        'location_type_key': 'headquarters',
        'location_type_label': 'Headquarters',
        'location_name': 'Ace Plumbing SF HQ',
        'description': 'Main office and dispatch center',
        'address_line_1': '100 Market Street',
        'locality': 'San Francisco',
        'admin_area_1': 'California',
        'country': 'United States',
        'country_code': 'US',
        'postal_code': '94105',
        'formatted_address': '100 Market St, San Francisco, CA 94105, US',
        'latitude': 37.7936,
        'longitude': -122.3958,
        'is_primary': True,
        'status': 'active',
    },
    {
        'location_id': 90002,
        'entity_id': 'e_loctest_001',
        'location_type_key': 'branch',
        'location_type_label': 'Branch',
        'location_name': 'Ace Plumbing Oakland Branch',
        'description': 'East Bay service center',
        'address_line_1': '500 Broadway',
        'locality': 'Oakland',
        'admin_area_1': 'California',
        'country': 'United States',
        'country_code': 'US',
        'postal_code': '94607',
        'formatted_address': '500 Broadway, Oakland, CA 94607, US',
        'latitude': 37.8050,
        'longitude': -122.2740,
        'is_primary': False,
        'status': 'active',
    },
    # Bay Area Electric — one location in Oakland
    {
        'location_id': 90003,
        'entity_id': 'e_loctest_002',
        'location_type_key': 'headquarters',
        'location_type_label': 'Headquarters',
        'location_name': 'BA Electric HQ',
        'description': 'Main office',
        'address_line_1': '1200 Broadway',
        'locality': 'Oakland',
        'admin_area_1': 'California',
        'country': 'United States',
        'country_code': 'US',
        'postal_code': '94612',
        'formatted_address': '1200 Broadway, Oakland, CA 94612, US',
        'latitude': 37.8030,
        'longitude': -122.2715,
        'is_primary': True,
        'status': 'active',
    },
    # NYC Plumbing — Manhattan and Brooklyn
    {
        'location_id': 90004,
        'entity_id': 'e_loctest_003',
        'location_type_key': 'headquarters',
        'location_type_label': 'Headquarters',
        'location_name': 'NYC Plumbing Manhattan',
        'description': 'Manhattan headquarters',
        'address_line_1': '350 5th Avenue',
        'locality': 'New York',
        'admin_area_1': 'New York',
        'country': 'United States',
        'country_code': 'US',
        'postal_code': '10118',
        'formatted_address': '350 5th Ave, New York, NY 10118, US',
        'latitude': 40.7484,
        'longitude': -73.9857,
        'is_primary': True,
        'status': 'active',
    },
    {
        'location_id': 90005,
        'entity_id': 'e_loctest_003',
        'location_type_key': 'branch',
        'location_type_label': 'Branch',
        'location_name': 'NYC Plumbing Brooklyn',
        'description': 'Brooklyn service center',
        'address_line_1': '100 Flatbush Avenue',
        'locality': 'Brooklyn',
        'admin_area_1': 'New York',
        'country': 'United States',
        'country_code': 'US',
        'postal_code': '11217',
        'formatted_address': '100 Flatbush Ave, Brooklyn, NY 11217, US',
        'latitude': 40.6831,
        'longitude': -73.9712,
        'is_primary': False,
        'status': 'active',
    },
    # GreenTech — San Jose
    {
        'location_id': 90006,
        'entity_id': 'e_loctest_004',
        'location_type_key': 'headquarters',
        'location_type_label': 'Headquarters',
        'location_name': 'GreenTech SJ Office',
        'description': 'Main consulting office',
        'address_line_1': '200 Park Avenue',
        'locality': 'San Jose',
        'admin_area_1': 'California',
        'country': 'United States',
        'country_code': 'US',
        'postal_code': '95113',
        'formatted_address': '200 Park Ave, San Jose, CA 95113, US',
        'latitude': 37.3361,
        'longitude': -121.8906,
        'is_primary': True,
        'status': 'active',
    },
]


class WeaviateLocationTestRunner:
    """Runs Weaviate location + cross-ref integration tests."""

    def __init__(self):
        self.tests_passed = 0
        self.tests_failed = 0
        self.index = None

    def _report(self, test_name: str, passed: bool, detail: str = ""):
        if passed:
            self.tests_passed += 1
            logger.info(f"  PASS: {test_name}{' - ' + detail if detail else ''}")
        else:
            self.tests_failed += 1
            logger.error(f"  FAIL: {test_name}{' - ' + detail if detail else ''}")

    def run_all(self):
        logger.info("=" * 70)
        logger.info("Weaviate LocationIndex + Cross-Reference Tests")
        logger.info(f"  EntityIndex:   {get_collection_name()}")
        logger.info(f"  LocationIndex: {get_location_collection_name()}")
        logger.info("=" * 70)

        # Schema utility tests (no Weaviate needed)
        self.test_schema_utilities()

        # Connect to Weaviate
        self.index = EntityWeaviateIndex.from_env()
        if not self.index:
            logger.error("Cannot connect to Weaviate. Set ENTITY_WEAVIATE_ENABLED=true and WEAVIATE_* env vars.")
            return

        try:
            self.test_create_collections()
            self.test_upsert_entities()
            self.test_upsert_locations()
            self.test_set_cross_references()

            # Allow time for vectorization
            logger.info("\nWaiting 3s for Weaviate vectorization...")
            time.sleep(3)

            self.test_search_locations_near()
            self.test_search_topic_near()
            self.test_search_entities_near()
            self.test_status()
        finally:
            self.cleanup()
            self.index.close()

        logger.info("=" * 70)
        total = self.tests_passed + self.tests_failed
        logger.info(f"Results: {self.tests_passed}/{total} passed, {self.tests_failed} failed")
        logger.info("=" * 70)
        if self.tests_failed > 0:
            sys.exit(1)

    # ------------------------------------------------------------------
    # Schema utility tests
    # ------------------------------------------------------------------

    def test_schema_utilities(self):
        logger.info("\n--- Schema Utilities ---")

        # Collection names use test env prefix
        ename = get_collection_name()
        lname = get_location_collection_name()
        self._report("Entity collection name has test prefix",
                     ename.startswith('wvloctest'), f"name={ename}")
        self._report("Location collection name has test prefix",
                     lname.startswith('wvloctest'), f"name={lname}")

        # UUID determinism
        uuid1 = location_id_to_weaviate_uuid(12345)
        uuid2 = location_id_to_weaviate_uuid(12345)
        uuid3 = location_id_to_weaviate_uuid(99999)
        self._report("Location UUID deterministic", uuid1 == uuid2)
        self._report("Location UUID unique per id", uuid1 != uuid3)

        # Entity→Location UUID namespace separation
        entity_uuid = entity_id_to_weaviate_uuid("e_test")
        loc_uuid = location_id_to_weaviate_uuid(1)
        self._report("Entity and location UUIDs differ", entity_uuid != loc_uuid)

        # build_location_search_text
        loc = {
            'location_name': 'Ace HQ',
            'location_type_label': 'Headquarters',
            'description': 'Main office',
            'formatted_address': '100 Market St, San Francisco, CA',
        }
        text = build_location_search_text(loc)
        self._report("Location search_text has name", 'Ace HQ' in text)
        self._report("Location search_text has type", 'Headquarters' in text)
        self._report("Location search_text has address", 'Market St' in text)

        # location_to_weaviate_properties
        props = location_to_weaviate_properties(TEST_LOCATIONS[0])
        self._report("Location props has location_id", props['location_id'] == '90001')
        self._report("Location props has entity_id", props['entity_id'] == 'e_loctest_001')
        self._report("Location props has geo_location", 'geo_location' in props)
        self._report("Location props has search_text", len(props['search_text']) > 0)

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    def test_create_collections(self):
        logger.info("\n--- Create Test Collections ---")

        # Clean slate: delete if they exist from a previous failed run
        ename = self.index.collection_name
        lname = self.index.location_collection_name
        if self.index.client.collections.exists(ename):
            self.index.client.collections.delete(ename)
            logger.info(f"  Deleted pre-existing {ename}")
        if self.index.client.collections.exists(lname):
            self.index.client.collections.delete(lname)
            logger.info(f"  Deleted pre-existing {lname}")

        result = self.index.ensure_collection()
        self._report("ensure_collection creates both", result is True)
        self._report("EntityIndex exists",
                     self.index.client.collections.exists(ename))
        self._report("LocationIndex exists",
                     self.index.client.collections.exists(lname))

    # ------------------------------------------------------------------
    # Entity upsert
    # ------------------------------------------------------------------

    def test_upsert_entities(self):
        logger.info("\n--- Upsert Entities ---")

        count = self.index.upsert_entities_batch(TEST_ENTITIES)
        self._report("Batch upsert entities", count == len(TEST_ENTITIES),
                     f"upserted={count}/{len(TEST_ENTITIES)}")

    # ------------------------------------------------------------------
    # Location upsert
    # ------------------------------------------------------------------

    def test_upsert_locations(self):
        logger.info("\n--- Upsert Locations ---")

        count = self.index.upsert_locations_batch(TEST_LOCATIONS)
        self._report("Batch upsert locations", count == len(TEST_LOCATIONS),
                     f"upserted={count}/{len(TEST_LOCATIONS)}")

        # Verify a single location can be fetched
        loc_uuid = location_id_to_weaviate_uuid(90001)
        obj = self.index.location_collection.query.fetch_object_by_id(loc_uuid)
        self._report("Location 90001 fetchable", obj is not None)
        if obj:
            self._report("Location props correct",
                         obj.properties.get('location_name') == 'Ace Plumbing SF HQ',
                         f"name={obj.properties.get('location_name')}")

    # ------------------------------------------------------------------
    # Cross-references
    # ------------------------------------------------------------------

    def test_set_cross_references(self):
        logger.info("\n--- Set Entity->Location Cross-References ---")

        # Build entity_id -> [location_id] map
        entity_loc_map = {}
        for loc in TEST_LOCATIONS:
            entity_loc_map.setdefault(loc['entity_id'], []).append(loc['location_id'])

        for eid, loc_ids in entity_loc_map.items():
            self.index.set_entity_location_refs(eid, loc_ids)

        self._report("Cross-refs set for all entities", True,
                     f"entities={len(entity_loc_map)}")

        # Verify cross-ref on entity e_loctest_001 (should have 2 locations)
        from weaviate.classes.query import QueryReference
        eid_uuid = entity_id_to_weaviate_uuid('e_loctest_001')
        obj = self.index.collection.query.fetch_object_by_id(
            eid_uuid,
            return_references=[QueryReference(
                link_on="locations",
                return_properties=["location_id", "location_name"],
            )],
        )
        loc_count = 0
        if obj and obj.references and "locations" in obj.references:
            loc_count = len(obj.references["locations"].objects)
        self._report("e_loctest_001 has 2 location refs", loc_count == 2,
                     f"count={loc_count}")

    # ------------------------------------------------------------------
    # search_locations_near
    # ------------------------------------------------------------------

    def test_search_locations_near(self):
        logger.info("\n--- Search: Locations Near ---")

        # Near SF (37.79, -122.40) within 15 km — should find SF + Oakland locations
        results = self.index.search_locations_near(
            latitude=37.79, longitude=-122.40, radius_km=15, limit=10,
        )
        self._report("Locations near SF returns results", len(results) > 0,
                     f"count={len(results)}")

        loc_ids = {r['location_id'] for r in results}
        self._report("SF HQ (90001) found", 90001 in loc_ids)
        self._report("Oakland branch (90002) found", 90002 in loc_ids)
        self._report("BA Electric HQ (90003) found", 90003 in loc_ids)
        self._report("NYC locations NOT found", 90004 not in loc_ids and 90005 not in loc_ids)

        # Near NYC (40.74, -73.99) within 20 km
        results_nyc = self.index.search_locations_near(
            latitude=40.74, longitude=-73.99, radius_km=20, limit=10,
        )
        self._report("Locations near NYC returns results", len(results_nyc) > 0,
                     f"count={len(results_nyc)}")
        nyc_loc_ids = {r['location_id'] for r in results_nyc}
        self._report("Manhattan (90004) found", 90004 in nyc_loc_ids)
        self._report("Brooklyn (90005) found", 90005 in nyc_loc_ids)
        self._report("SF locations NOT in NYC results", 90001 not in nyc_loc_ids)

        # Filter by location_type_key
        results_hq = self.index.search_locations_near(
            latitude=37.79, longitude=-122.40, radius_km=15,
            location_type_key='headquarters', limit=10,
        )
        all_hq = all(r['location_type_key'] == 'headquarters' for r in results_hq)
        self._report("HQ filter returns only HQs", all_hq and len(results_hq) > 0,
                     f"count={len(results_hq)}")

        # Very tight radius — should find nothing far away
        results_tight = self.index.search_locations_near(
            latitude=40.74, longitude=-73.99, radius_km=0.1, limit=10,
        )
        self._report("Tight radius (100m NYC) returns few/no results",
                     len(results_tight) <= 1, f"count={len(results_tight)}")

    # ------------------------------------------------------------------
    # search_topic_near (the key cross-ref query)
    # ------------------------------------------------------------------

    def test_search_topic_near(self):
        logger.info("\n--- Search: Topic + Near (Cross-Reference) ---")

        # "plumbing" near SF — should find Ace Plumbing (SF), not NYC Plumbing
        results = self.index.search_topic_near(
            query="plumbing contractor",
            latitude=37.79, longitude=-122.40, radius_km=20,
            min_certainty=0.5, limit=10,
        )
        self._report("Topic-near 'plumbing' near SF returns results",
                     len(results) > 0, f"count={len(results)}")

        entity_ids = [r['entity_id'] for r in results]
        self._report("Ace Plumbing (SF) in results", 'e_loctest_001' in entity_ids)
        self._report("NYC Plumbing NOT in results", 'e_loctest_003' not in entity_ids)

        # Check that locations are returned inline
        if results:
            ace = next((r for r in results if r['entity_id'] == 'e_loctest_001'), None)
            if ace:
                self._report("Ace Plumbing has locations in response",
                             len(ace.get('locations', [])) > 0,
                             f"count={len(ace.get('locations', []))}")
                self._report("Ace Plumbing has score", ace.get('score', 0) > 0,
                             f"score={ace.get('score')}")
            else:
                self._report("Ace Plumbing in results for detail check", False)

        # "plumbing" near NYC — should find NYC Plumbing, not Ace
        results_nyc = self.index.search_topic_near(
            query="plumbing repair",
            latitude=40.74, longitude=-73.99, radius_km=20,
            min_certainty=0.5, limit=10,
        )
        self._report("Topic-near 'plumbing' near NYC returns results",
                     len(results_nyc) > 0, f"count={len(results_nyc)}")
        nyc_ids = [r['entity_id'] for r in results_nyc]
        self._report("NYC Plumbing in NYC results", 'e_loctest_003' in nyc_ids)
        self._report("Ace Plumbing NOT in NYC results", 'e_loctest_001' not in nyc_ids)

        # "environmental consulting" near SF Bay Area — should find GreenTech
        results_env = self.index.search_topic_near(
            query="environmental consulting sustainability",
            latitude=37.40, longitude=-122.00, radius_km=50,
            min_certainty=0.5, limit=10,
        )
        self._report("Topic-near 'environmental' near Bay Area returns results",
                     len(results_env) > 0, f"count={len(results_env)}")
        env_ids = [r['entity_id'] for r in results_env]
        self._report("GreenTech in results", 'e_loctest_004' in env_ids)

        # Type filter: "contractor" near SF, type_key=business
        results_typed = self.index.search_topic_near(
            query="contractor",
            latitude=37.79, longitude=-122.40, radius_km=20,
            type_key='business', min_certainty=0.5, limit=10,
        )
        if results_typed:
            all_biz = all(r.get('type_key') == 'business' for r in results_typed)
            self._report("Type filter returns only businesses", all_biz)

    # ------------------------------------------------------------------
    # search_entities_near (geo only, no vector)
    # ------------------------------------------------------------------

    def test_search_entities_near(self):
        logger.info("\n--- Search: Entities Near (Geo Only) ---")

        # Entities with a location near SF
        results = self.index.search_entities_near(
            latitude=37.79, longitude=-122.40, radius_km=20, limit=10,
        )
        self._report("Entities near SF returns results", len(results) > 0,
                     f"count={len(results)}")
        entity_ids = {r['entity_id'] for r in results}
        self._report("Ace Plumbing found (has SF + Oakland locs)",
                     'e_loctest_001' in entity_ids)
        self._report("Bay Area Electric found (Oakland loc)",
                     'e_loctest_002' in entity_ids)
        self._report("NYC Plumbing NOT found",
                     'e_loctest_003' not in entity_ids)

        # Entities near San Jose (50 km) — should include GreenTech + possibly SF entities
        results_sj = self.index.search_entities_near(
            latitude=37.34, longitude=-121.89, radius_km=10, limit=10,
        )
        sj_ids = {r['entity_id'] for r in results_sj}
        self._report("GreenTech found near San Jose", 'e_loctest_004' in sj_ids)

        # Check locations are included in response
        if results:
            first = results[0]
            self._report("Response includes locations list",
                         'locations' in first and isinstance(first['locations'], list))

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def test_status(self):
        logger.info("\n--- Status ---")
        st = self.index.get_status()
        self._report("Status has entity_index", 'entity_index' in st)
        self._report("Status has location_index", 'location_index' in st)
        entity_count = st.get('entity_index', {}).get('object_count', 0)
        location_count = st.get('location_index', {}).get('object_count', 0)
        self._report("Entity count matches",
                     entity_count == len(TEST_ENTITIES),
                     f"expected={len(TEST_ENTITIES)}, got={entity_count}")
        self._report("Location count matches",
                     location_count == len(TEST_LOCATIONS),
                     f"expected={len(TEST_LOCATIONS)}, got={location_count}")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup(self):
        logger.info("\n--- Cleanup: Deleting Test Collections ---")
        try:
            ename = self.index.collection_name
            lname = self.index.location_collection_name

            # Delete EntityIndex first (it references LocationIndex)
            if self.index.client.collections.exists(ename):
                self.index.client.collections.delete(ename)
                logger.info(f"  Deleted {ename}")
            if self.index.client.collections.exists(lname):
                self.index.client.collections.delete(lname)
                logger.info(f"  Deleted {lname}")
            logger.info("  Cleanup complete")
        except Exception as e:
            logger.error(f"  Cleanup failed: {e}")


if __name__ == '__main__':
    runner = WeaviateLocationTestRunner()
    runner.run_all()
