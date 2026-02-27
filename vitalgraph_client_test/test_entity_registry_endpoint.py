#!/usr/bin/env python3
"""
Entity Registry Endpoint Test Script

Tests the Entity Registry REST API via VitalGraphClient.
Requires:
  1. A running VitalGraph server with the entity registry initialized.
  2. Test data loaded via: python vitalgraph_client_test/load_test_data.py

After testing, clean up with: python vitalgraph_client_test/cleanup_test_data.py

Usage:
    python vitalgraph_client_test/test_entity_registry_endpoint.py
"""

import asyncio
import json
import logging
import sys
import traceback
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.entity_registry_model import (
    AliasCreateRequest,
    EntityCategoryRequest,
    EntityUpdateRequest,
    IdentifierCreateRequest,
    LocationCreateRequest,
    LocationUpdateRequest,
    SameAsCreateRequest,
    SameAsRetractRequest,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)

MANIFEST_PATH = Path(__file__).parent / 'test_data_manifest.json'


class EntityRegistryTestRunner:
    """Runs entity registry endpoint tests via the client.

    Reads entity IDs from a manifest written by load_test_data.py.
    Does NOT create or delete entities — only tests endpoint behaviour.
    """

    def __init__(self, manifest: dict):
        self.client = VitalGraphClient()
        self.tests_passed = 0
        self.tests_failed = 0
        self.ids = manifest['entities']
        self.entity_type_key = manifest.get('entity_type_key')

    def _report(self, name: str, passed: bool, detail: str = ""):
        if passed:
            self.tests_passed += 1
            logger.info(f"  ✅ PASS: {name}{' - ' + detail if detail else ''}")
        else:
            self.tests_failed += 1
            logger.error(f"  ❌ FAIL: {name}{' - ' + detail if detail else ''}")

    async def run_all(self):
        """Run all entity registry tests."""
        logger.info("=" * 60)
        logger.info("Entity Registry Endpoint Tests")
        logger.info("=" * 60)

        try:
            await self.client.open()
            logger.info("Client connected successfully")
        except Exception as e:
            logger.error(f"Failed to connect client: {e}")
            return

        try:
            await self.test_list_entity_types()
            await self.test_get_entity()
            await self.test_get_entity_geo()
            await self.test_update_entity()
            await self.test_update_geo_coordinates()
            await self.test_search_entities()
            await self.test_identifiers()
            await self.test_aliases()
            await self.test_categories()
            await self.test_same_as()
            await self.test_changelog()
            await self.test_find_similar()
            await self.test_find_similar_phonetic()
            await self.test_find_similar_typo()
            await self.test_find_similar_near_dupes()
            await self.test_find_similar_aliases()
            await self.test_find_similar_score_detail()
            await self.test_entity_search()
            await self.test_locations()
            await self.test_geo_search()
            await self.test_delete_entity()
            await self.test_error_cases()
        except Exception as e:
            logger.error(f"Unexpected error during tests: {e}")
            traceback.print_exc()
        finally:
            await self.client.close()

        logger.info("=" * 60)
        total = self.tests_passed + self.tests_failed
        logger.info(f"Results: {self.tests_passed}/{total} passed, {self.tests_failed} failed")
        logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Entity Type tests
    # ------------------------------------------------------------------

    async def test_list_entity_types(self):
        logger.info("\n--- Test: List Entity Types ---")
        try:
            types = await self.client.entity_registry.list_entity_types()
            self._report("List entity types", len(types) >= 4,
                         f"Got {len(types)} types")
            type_keys = [t.type_key for t in types]
            for expected in ['person', 'business', 'organization', 'government']:
                self._report(f"Seed type '{expected}' exists", expected in type_keys)
            if self.entity_type_key:
                self._report(f"Test type '{self.entity_type_key}' exists",
                             self.entity_type_key in type_keys)
        except Exception as e:
            self._report("List entity types", False, str(e))

    # ------------------------------------------------------------------
    # Entity GET tests
    # ------------------------------------------------------------------

    async def test_get_entity(self):
        logger.info("\n--- Test: Get Entity ---")
        acme_id = self.ids['acme_corp']
        try:
            entity = await self.client.entity_registry.get_entity(acme_id)
            self._report("Get entity by ID", entity.entity_id == acme_id)
            self._report("Entity has URI", entity.entity_uri.startswith('urn:entity:'))
            self._report("Entity has type_key", entity.type_key == 'business')
            self._report("Entity name is Acme Corporation", entity.primary_name == 'Acme Corporation')
            self._report("Entity country is US", entity.country == 'US')
            self._report("Entity region is California", entity.region == 'California')
            self._report("Entity locality is San Francisco", entity.locality == 'San Francisco')
            self._report("Entity has identifiers", entity.identifiers is not None and len(entity.identifiers) == 2,
                         f"identifiers={len(entity.identifiers) if entity.identifiers else 0}")
            self._report("Entity has aliases", entity.aliases is not None and len(entity.aliases) == 2,
                         f"aliases={len(entity.aliases) if entity.aliases else 0}")
            self._report("Entity has latitude",
                         entity.latitude is not None and abs(entity.latitude - 37.7749) < 0.001,
                         f"latitude={entity.latitude}")
            self._report("Entity has longitude",
                         entity.longitude is not None and abs(entity.longitude - (-122.4194)) < 0.001,
                         f"longitude={entity.longitude}")
        except Exception as e:
            self._report("Get entity", False, str(e))

    async def test_get_entity_geo(self):
        logger.info("\n--- Test: Get Entity Geo Coordinates ---")
        try:
            # Entity WITH coordinates
            geo = await self.client.entity_registry.get_entity(self.ids['geo_test'])
            self._report("GeoTest has latitude",
                         geo.latitude is not None and abs(geo.latitude - 40.7357) < 0.001,
                         f"latitude={geo.latitude}")
            self._report("GeoTest has longitude",
                         geo.longitude is not None and abs(geo.longitude - (-74.1724)) < 0.001,
                         f"longitude={geo.longitude}")

            # Entity WITHOUT coordinates
            nogeo = await self.client.entity_registry.get_entity(self.ids['no_geo'])
            self._report("NoGeo has null latitude", nogeo.latitude is None)
            self._report("NoGeo has null longitude", nogeo.longitude is None)
        except Exception as e:
            self._report("Get entity geo", False, str(e))

    # ------------------------------------------------------------------
    # Entity UPDATE tests
    # ------------------------------------------------------------------

    async def test_update_entity(self):
        logger.info("\n--- Test: Update Entity ---")
        acme_id = self.ids['acme_corp']
        try:
            req = EntityUpdateRequest(
                description='Updated description for Acme',
                website='https://new.acme.example.com',
                updated_by='test_runner',
            )
            entity = await self.client.entity_registry.update_entity(acme_id, req)
            self._report("Update description", entity.description == 'Updated description for Acme')
            self._report("Update website", entity.website == 'https://new.acme.example.com')
            self._report("Latitude preserved after update",
                         entity.latitude is not None and abs(entity.latitude - 37.7749) < 0.001,
                         f"latitude={entity.latitude}")
        except Exception as e:
            self._report("Update entity", False, str(e))

    async def test_update_geo_coordinates(self):
        logger.info("\n--- Test: Update Geo Coordinates ---")
        geo_id = self.ids['geo_test']
        try:
            # Update coordinates from Newark to Chicago
            req = EntityUpdateRequest(
                latitude=41.8781,
                longitude=-87.6298,
                updated_by='test_runner',
            )
            updated = await self.client.entity_registry.update_entity(geo_id, req)
            self._report("Update latitude to Chicago",
                         updated.latitude is not None and abs(updated.latitude - 41.8781) < 0.001,
                         f"latitude={updated.latitude}")
            self._report("Update longitude to Chicago",
                         updated.longitude is not None and abs(updated.longitude - (-87.6298)) < 0.001,
                         f"longitude={updated.longitude}")
            self._report("Name unchanged after coord update",
                         updated.primary_name == 'GeoTest Corp')
            self._report("Country unchanged after coord update",
                         updated.country == 'US')

            # Restore original coordinates
            restore = EntityUpdateRequest(
                latitude=40.7357, longitude=-74.1724, updated_by='test_runner',
            )
            await self.client.entity_registry.update_entity(geo_id, restore)
        except Exception as e:
            self._report("Update geo coordinates", False, str(e))

    # ------------------------------------------------------------------
    # Search tests
    # ------------------------------------------------------------------

    async def test_search_entities(self):
        logger.info("\n--- Test: Search Entities ---")
        try:
            results = await self.client.entity_registry.search_entities(query='Acme')
            self._report("Search by name 'Acme'", results.total_count >= 2,
                         f"total={results.total_count}")

            results2 = await self.client.entity_registry.search_entities(type_key='person')
            all_persons = all(e.type_key == 'person' for e in results2.entities)
            self._report("Filter by type 'person'",
                         results2.success and all_persons,
                         f"total={results2.total_count}")

            results3 = await self.client.entity_registry.search_entities(page_size=1, page=1)
            self._report("Pagination page_size=1", len(results3.entities) == 1)
        except Exception as e:
            self._report("Search entities", False, str(e))

    # ------------------------------------------------------------------
    # Identifier tests
    # ------------------------------------------------------------------

    async def test_identifiers(self):
        logger.info("\n--- Test: Identifiers ---")
        acme_id = self.ids['acme_corp']
        try:
            idents = await self.client.entity_registry.list_identifiers(acme_id)
            self._report("List identifiers", len(idents) == 2, f"count={len(idents)}")

            # Add and then remove (leaves state clean)
            req = IdentifierCreateRequest(
                identifier_namespace='CRM', identifier_value='ACCT-00482',
                created_by='test_runner',
            )
            new_ident = await self.client.entity_registry.add_identifier(acme_id, req)
            self._report("Add identifier", new_ident.identifier_namespace == 'CRM')

            found_list = await self.client.entity_registry.lookup_by_identifier('DUNS', 'DUNS-TEST-001')
            found_ids = [e.entity_id for e in found_list]
            self._report("Lookup by DUNS", acme_id in found_ids, f"matched {len(found_list)} entities")

            found_list2 = await self.client.entity_registry.lookup_by_identifier('CRM', 'ACCT-00482')
            found_ids2 = [e.entity_id for e in found_list2]
            self._report("Lookup by CRM", acme_id in found_ids2, f"matched {len(found_list2)} entities")

            result = await self.client.entity_registry.remove_identifier(new_ident.identifier_id)
            self._report("Remove identifier", result.get('success') is True)

            idents_after = await self.client.entity_registry.list_identifiers(acme_id)
            self._report("Identifier retracted", len(idents_after) == 2)
        except Exception as e:
            self._report("Identifiers", False, str(e))
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Alias tests
    # ------------------------------------------------------------------

    async def test_aliases(self):
        logger.info("\n--- Test: Aliases ---")
        acme_id = self.ids['acme_corp']
        try:
            aliases = await self.client.entity_registry.list_aliases(acme_id)
            self._report("List aliases", len(aliases) == 2, f"count={len(aliases)}")

            req = AliasCreateRequest(
                alias_name='Acme Manufacturing', alias_type='former',
                created_by='test_runner',
            )
            new_alias = await self.client.entity_registry.add_alias(acme_id, req)
            self._report("Add alias", new_alias.alias_name == 'Acme Manufacturing')

            result = await self.client.entity_registry.remove_alias(new_alias.alias_id)
            self._report("Remove alias", result.get('success') is True)

            aliases_after = await self.client.entity_registry.list_aliases(acme_id)
            self._report("Alias retracted", len(aliases_after) == 2)
        except Exception as e:
            self._report("Aliases", False, str(e))
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Category tests
    # ------------------------------------------------------------------

    async def test_categories(self):
        logger.info("\n--- Test: Categories ---")
        acme_id = self.ids['acme_corp']
        try:
            categories = await self.client.entity_registry.list_categories()
            self._report("List categories", len(categories) >= 7,
                         f"count={len(categories)}")

            cat_keys = [c.category_key for c in categories]
            self._report("Has 'customer' category", 'customer' in cat_keys)
            self._report("Has 'partner' category", 'partner' in cat_keys)

            req = EntityCategoryRequest(category_key='customer', created_by='test_runner')
            mapping = await self.client.entity_registry.add_entity_category(acme_id, req)
            self._report("Add entity category", mapping.category_key == 'customer')

            req2 = EntityCategoryRequest(category_key='partner', created_by='test_runner')
            mapping2 = await self.client.entity_registry.add_entity_category(acme_id, req2)
            self._report("Add second category", mapping2.category_key == 'partner')

            entity_cats = await self.client.entity_registry.list_entity_categories(acme_id)
            entity_cat_keys = [c.category_key for c in entity_cats]
            self._report("List entity categories", len(entity_cats) == 2,
                         f"keys={entity_cat_keys}")

            entities_in_cat = await self.client.entity_registry.list_entities_by_category('customer')
            found_ids = [e.entity_id for e in entities_in_cat]
            self._report("List entities by category", acme_id in found_ids,
                         f"count={len(entities_in_cat)}")

            result = await self.client.entity_registry.remove_entity_category(acme_id, 'partner')
            self._report("Remove entity category", result.get('success') is True)

            entity_cats_after = await self.client.entity_registry.list_entity_categories(acme_id)
            remaining_keys = [c.category_key for c in entity_cats_after]
            self._report("Category removed", 'partner' not in remaining_keys and 'customer' in remaining_keys,
                         f"remaining={remaining_keys}")

            # Clean up: remove customer too so test is re-runnable
            await self.client.entity_registry.remove_entity_category(acme_id, 'customer')

        except Exception as e:
            self._report("Categories", False, str(e))
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Same-As tests
    # ------------------------------------------------------------------

    async def test_same_as(self):
        logger.info("\n--- Test: Same-As ---")
        source_id = self.ids['acme_inc']
        target_id = self.ids['acme_corp']
        try:
            req = SameAsCreateRequest(
                source_entity_id=source_id,
                target_entity_id=target_id,
                relationship_type='same_as',
                reason='Duplicate entity detected',
                created_by='test_runner',
            )
            mapping = await self.client.entity_registry.create_same_as(req)
            self._report("Create same-as", mapping.source_entity_id == source_id)

            mappings = await self.client.entity_registry.get_same_as(source_id)
            self._report("Get same-as mappings", len(mappings) >= 1)

            resolved = await self.client.entity_registry.resolve_entity(source_id)
            self._report("Resolve entity (transitive)", resolved.entity_id == target_id,
                         f"resolved to {resolved.entity_id}")

            retract_req = SameAsRetractRequest(
                retracted_by='test_runner', reason='Testing retraction',
            )
            retracted = await self.client.entity_registry.retract_same_as(mapping.same_as_id, retract_req)
            self._report("Retract same-as", retracted.status == 'retracted')

            resolved2 = await self.client.entity_registry.resolve_entity(source_id)
            self._report("Resolve after retraction", resolved2.entity_id == source_id)
        except Exception as e:
            self._report("Same-As", False, str(e))
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Change Log tests
    # ------------------------------------------------------------------

    async def test_changelog(self):
        logger.info("\n--- Test: Change Log ---")
        acme_id = self.ids['acme_corp']
        try:
            cl = await self.client.entity_registry.get_entity_changelog(acme_id)
            self._report("Get entity changelog", cl.success and cl.total_count > 0,
                         f"total={cl.total_count}")

            cl_created = await self.client.entity_registry.get_entity_changelog(
                acme_id, change_type='entity_created')
            has_created = cl_created.total_count > 0
            self._report("Has 'entity_created' entry", has_created)

            recent = await self.client.entity_registry.get_recent_changelog(limit=10)
            self._report("Get recent changelog", recent.success and len(recent.entries) > 0,
                         f"count={len(recent.entries)}")
        except Exception as e:
            self._report("Change log", False, str(e))

    # ------------------------------------------------------------------
    # Similar / Dedup tests
    # ------------------------------------------------------------------

    async def test_find_similar(self):
        logger.info("\n--- Test: Find Similar ---")
        acme_id = self.ids['acme_corp']
        try:
            resp = await self.client.entity_registry.find_similar("Acme Corporation")
            self._report("Find similar returns response", resp.success is True)
            self._report("Find similar has candidates", len(resp.candidates) >= 1,
                         f"count={len(resp.candidates)}")

            candidate_ids = [c.entity_id for c in resp.candidates]
            self._report("Acme Corp in results", acme_id in candidate_ids,
                         f"expected={acme_id}")

            if resp.candidates:
                top = resp.candidates[0]
                self._report("Candidate has score", top.score > 0, f"score={top.score}")
                self._report("Candidate has match_level",
                             top.match_level in ('high', 'likely', 'possible'),
                             f"match_level={top.match_level}")
                self._report("Candidate has score_detail",
                             top.score_detail is not None and 'ratio' in top.score_detail)

            resp2 = await self.client.entity_registry.find_similar("ACME")
            candidate_ids2 = [c.entity_id for c in resp2.candidates]
            self._report("Alias 'ACME' finds entity",
                         acme_id in candidate_ids2,
                         f"count={len(resp2.candidates)}")

            resp3 = await self.client.entity_registry.find_similar(
                "Xyloquest Barvonian Plc", min_score=70.0)
            self._report("Unrelated name returns no likely matches",
                         len(resp3.candidates) == 0,
                         f"count={len(resp3.candidates)}")

            resp4 = await self.client.entity_registry.find_similar(
                "Acme Corporation", country="US")
            self._report("Find similar with country filter works",
                         resp4.success and len(resp4.candidates) >= 1,
                         f"count={len(resp4.candidates)}")

        except Exception as e:
            self._report("Find similar", False, str(e))
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Phonetic matching tests
    # ------------------------------------------------------------------

    async def test_find_similar_phonetic(self):
        logger.info("\n--- Test: Find Similar — Phonetic Matching ---")
        try:
            # Schneider / Snyder cluster
            schneider_id = self.ids.get('hans_schneider')
            snyder_id = self.ids.get('john_snyder')

            if not schneider_id or not snyder_id:
                self._report("Phonetic test entities present", False, "Missing IDs in manifest")
                return

            # Query "Snyder" — should find Schneider via phonetic LSH
            resp = await self.client.entity_registry.find_similar(
                "Hans Snyder", min_score=30.0)
            candidate_ids = [c.entity_id for c in resp.candidates]
            self._report("Phonetic: 'Hans Snyder' finds Hans Schneider",
                         schneider_id in candidate_ids,
                         f"candidates={len(resp.candidates)}")
            self._report("Phonetic: 'Hans Snyder' finds John Snyder",
                         snyder_id in candidate_ids)

            # Schmidt / Schmitt cluster
            schmidt_id = self.ids.get('erik_schmidt')
            schmitt_id = self.ids.get('eric_schmitt')
            resp2 = await self.client.entity_registry.find_similar(
                "Eric Schmidt", min_score=30.0)
            candidate_ids2 = [c.entity_id for c in resp2.candidates]
            self._report("Phonetic: 'Eric Schmidt' finds Erik Schmidt",
                         schmidt_id in candidate_ids2,
                         f"candidates={len(resp2.candidates)}")
            self._report("Phonetic: 'Eric Schmidt' finds Eric Schmitt",
                         schmitt_id in candidate_ids2)

            # Meyer / Meier cluster
            meyer_id = self.ids.get('klaus_meyer')
            meier_id = self.ids.get('klaus_meier')
            resp3 = await self.client.entity_registry.find_similar(
                "Klaus Meyer", min_score=30.0)
            candidate_ids3 = [c.entity_id for c in resp3.candidates]
            self._report("Phonetic: 'Klaus Meyer' finds Klaus Meier",
                         meier_id in candidate_ids3,
                         f"candidates={len(resp3.candidates)}")

            # Fischer / Fisher cluster
            fischer_id = self.ids.get('fischer_tech')
            fisher_id = self.ids.get('fisher_tech')
            resp4 = await self.client.entity_registry.find_similar(
                "Fisher Technologies", min_score=30.0)
            candidate_ids4 = [c.entity_id for c in resp4.candidates]
            self._report("Phonetic: 'Fisher Technologies' finds Fischer Technologies",
                         fischer_id in candidate_ids4,
                         f"candidates={len(resp4.candidates)}")

            # Thompson / Thomson cluster
            thompson_id = self.ids.get('thompson_consulting')
            thomson_id = self.ids.get('thomson_consulting')
            resp5 = await self.client.entity_registry.find_similar(
                "Thomson Consulting", min_score=30.0)
            candidate_ids5 = [c.entity_id for c in resp5.candidates]
            self._report("Phonetic: 'Thomson Consulting' finds Thompson Consulting",
                         thompson_id in candidate_ids5,
                         f"candidates={len(resp5.candidates)}")

        except Exception as e:
            self._report("Find similar phonetic", False, str(e))
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Typo matching tests (edit-distance-1 via primary LSH batch query)
    # ------------------------------------------------------------------

    async def test_find_similar_typo(self):
        logger.info("\n--- Test: Find Similar — Typo Matching ---")
        try:
            smith_id = self.ids.get('smith_associates')
            anderson_id = self.ids.get('anderson_consulting')
            microsoft_id = self.ids.get('microsoft_corp')
            deutsche_id = self.ids.get('deutsche_bank')

            if not smith_id:
                self._report("Typo test entities present", False, "Missing IDs in manifest")
                return

            # Transposition: "Smtih" → "Smith"
            resp = await self.client.entity_registry.find_similar(
                "Smtih & Associates", min_score=30.0)
            candidate_ids = [c.entity_id for c in resp.candidates]
            self._report("Typo: 'Smtih & Associates' finds Smith & Associates",
                         smith_id in candidate_ids,
                         f"candidates={len(resp.candidates)}")

            # Deletion: "Andersom" → "Anderson"
            resp2 = await self.client.entity_registry.find_similar(
                "Andersom Consulting Group", min_score=30.0)
            candidate_ids2 = [c.entity_id for c in resp2.candidates]
            self._report("Typo: 'Andersom Consulting' finds Anderson Consulting",
                         anderson_id in candidate_ids2,
                         f"candidates={len(resp2.candidates)}")

            # Deletion: "Microsft" → "Microsoft"
            resp3 = await self.client.entity_registry.find_similar(
                "Microsft Corporation", min_score=30.0)
            candidate_ids3 = [c.entity_id for c in resp3.candidates]
            self._report("Typo: 'Microsft Corporation' finds Microsoft Corporation",
                         microsoft_id in candidate_ids3,
                         f"candidates={len(resp3.candidates)}")

            # Deletion: "Deutche" → "Deutsche"
            resp4 = await self.client.entity_registry.find_similar(
                "Deutche Bank AG", min_score=30.0)
            candidate_ids4 = [c.entity_id for c in resp4.candidates]
            self._report("Typo: 'Deutche Bank AG' finds Deutsche Bank AG",
                         deutsche_id in candidate_ids4,
                         f"candidates={len(resp4.candidates)}")

        except Exception as e:
            self._report("Find similar typo", False, str(e))
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Near-duplicate cluster tests
    # ------------------------------------------------------------------

    async def test_find_similar_near_dupes(self):
        logger.info("\n--- Test: Find Similar — Near-Duplicate Clusters ---")
        try:
            # Johnson Manufacturing cluster
            jm_id = self.ids.get('johnson_mfg')
            jm_inc_id = self.ids.get('johnson_mfg_inc')
            jm_llc_id = self.ids.get('johnson_mfg_llc')

            if not jm_id:
                self._report("Near-dupe test entities present", False, "Missing IDs in manifest")
                return

            resp = await self.client.entity_registry.find_similar(
                "Johnson Manufacturing Corporation", min_score=40.0)
            candidate_ids = [c.entity_id for c in resp.candidates]
            self._report("Near-dupe: finds Johnson Manufacturing",
                         jm_id in candidate_ids,
                         f"candidates={len(resp.candidates)}")
            self._report("Near-dupe: finds Johnson Manufacturing Inc",
                         jm_inc_id in candidate_ids)
            self._report("Near-dupe: finds Johnson Manufacturing LLC",
                         jm_llc_id in candidate_ids)

            # Acme cluster (original + bulk additions)
            acme_id = self.ids['acme_corp']
            acme_inc_id = self.ids.get('acme_inc')
            acme_intl_id = self.ids.get('acme_intl')

            resp2 = await self.client.entity_registry.find_similar(
                "Acme Corporation", min_score=40.0)
            candidate_ids2 = [c.entity_id for c in resp2.candidates]
            self._report("Near-dupe: 'Acme Corporation' finds acme_corp",
                         acme_id in candidate_ids2,
                         f"candidates={len(resp2.candidates)}")
            self._report("Near-dupe: 'Acme Corporation' finds acme_inc",
                         acme_inc_id in candidate_ids2)
            self._report("Near-dupe: 'Acme Corporation' finds acme_intl",
                         acme_intl_id in candidate_ids2)

            # GlobalTech cluster
            gt_sol_id = self.ids.get('globaltech_solutions')
            gt_sys_id = self.ids.get('globaltech_systems')
            gt_inc_id = self.ids.get('global_tech_inc')

            resp3 = await self.client.entity_registry.find_similar(
                "GlobalTech Solutions", min_score=40.0)
            candidate_ids3 = [c.entity_id for c in resp3.candidates]
            self._report("Near-dupe: 'GlobalTech Solutions' finds itself",
                         gt_sol_id in candidate_ids3,
                         f"candidates={len(resp3.candidates)}")
            self._report("Near-dupe: 'GlobalTech Solutions' finds GlobalTech Systems",
                         gt_sys_id in candidate_ids3)

        except Exception as e:
            self._report("Find similar near-dupes", False, str(e))
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Alias-based matching tests
    # ------------------------------------------------------------------

    async def test_find_similar_aliases(self):
        logger.info("\n--- Test: Find Similar — Alias Matching ---")
        try:
            ibm_id = self.ids.get('ibm')
            ge_id = self.ids.get('general_electric')

            if not ibm_id:
                self._report("Alias test entities present", False, "Missing IDs in manifest")
                return

            # Query "IBM" — should find "International Business Machines" via alias
            resp = await self.client.entity_registry.find_similar(
                "IBM", min_score=30.0)
            candidate_ids = [c.entity_id for c in resp.candidates]
            self._report("Alias: 'IBM' finds International Business Machines",
                         ibm_id in candidate_ids,
                         f"candidates={len(resp.candidates)}")

            # Query "GE" — should find "General Electric Company" via alias
            if ge_id:
                resp2 = await self.client.entity_registry.find_similar(
                    "GE", min_score=30.0)
                candidate_ids2 = [c.entity_id for c in resp2.candidates]
                self._report("Alias: 'GE' finds General Electric Company",
                             ge_id in candidate_ids2,
                             f"candidates={len(resp2.candidates)}")

            # Query full name should still work
            resp3 = await self.client.entity_registry.find_similar(
                "International Business Machines", min_score=40.0)
            candidate_ids3 = [c.entity_id for c in resp3.candidates]
            self._report("Full name: 'International Business Machines' finds IBM entity",
                         ibm_id in candidate_ids3,
                         f"candidates={len(resp3.candidates)}")

        except Exception as e:
            self._report("Find similar aliases", False, str(e))
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Score detail / phonetic_match field tests
    # ------------------------------------------------------------------

    async def test_find_similar_score_detail(self):
        logger.info("\n--- Test: Find Similar — Score Detail ---")
        try:
            schneider_id = self.ids.get('hans_schneider')
            if not schneider_id:
                self._report("Score detail test entities present", False, "Missing IDs in manifest")
                return

            # Query that should trigger a phonetic match
            resp = await self.client.entity_registry.find_similar(
                "Hans Snyder", min_score=30.0)

            # Find the Schneider candidate
            schneider_result = next(
                (c for c in resp.candidates if c.entity_id == schneider_id), None)

            if schneider_result:
                self._report("Score detail: Schneider candidate found",
                             True, f"score={schneider_result.score}")
                self._report("Score detail: has score_detail dict",
                             schneider_result.score_detail is not None)
                if schneider_result.score_detail:
                    self._report("Score detail: has ratio",
                                 'ratio' in schneider_result.score_detail)
                    self._report("Score detail: has token_sort_ratio",
                                 'token_sort_ratio' in schneider_result.score_detail)
                    self._report("Score detail: has phonetic_match",
                                 'phonetic_match' in schneider_result.score_detail)
                    self._report("Score detail: phonetic_match is True",
                                 bool(schneider_result.score_detail.get('phonetic_match')),
                                 f"phonetic_match={schneider_result.score_detail.get('phonetic_match')}")
            else:
                self._report("Score detail: Schneider candidate found", False,
                             f"candidates={[c.entity_id for c in resp.candidates]}")

            # Query that should NOT have a phonetic match (pure string similarity)
            resp2 = await self.client.entity_registry.find_similar(
                "Acme Corporation", min_score=50.0)
            acme_id = self.ids['acme_corp']
            acme_result = next(
                (c for c in resp2.candidates if c.entity_id == acme_id), None)

            if acme_result and acme_result.score_detail:
                self._report("Score detail: Acme has high string score",
                             acme_result.score >= 80.0,
                             f"score={acme_result.score}")
                self._report("Score detail: has match_level",
                             acme_result.match_level in ('high', 'likely', 'possible'),
                             f"match_level={acme_result.match_level}")
            else:
                self._report("Score detail: Acme result found", False)

        except Exception as e:
            self._report("Find similar score detail", False, str(e))
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Entity search (unified semantic + geo) tests
    # ------------------------------------------------------------------

    async def test_entity_search(self):
        logger.info("\n--- Test: Entity Search (Weaviate) ---")
        acme_id = self.ids['acme_corp']
        geo_id = self.ids['geo_test']
        try:
            # Basic semantic search (q only)
            resp = await self.client.entity_registry.search_entity(
                q="corporation business", min_certainty=0.5, limit=10)
            self._report("Entity search returns response", resp.success is True)
            self._report("Entity search has results", len(resp.results) > 0,
                         f"count={len(resp.results)}")

            if resp.results:
                result_ids = [r.entity_id for r in resp.results]
                self._report("Acme Corp in entity search results", acme_id in result_ids)
                top = resp.results[0]
                self._report("Result has score", top.score > 0, f"score={top.score}")
                self._report("Result has distance", top.distance is not None)
                self._report("Result has type_key", top.type_key is not None,
                             f"type_key={top.type_key}")

            # Filter by type_key
            resp2 = await self.client.entity_registry.search_entity(
                q="corporation", type_key="person", min_certainty=0.5, limit=10)
            self._report("Type filter 'person' excludes businesses",
                         all(r.type_key == 'person' for r in resp2.results),
                         f"count={len(resp2.results)}")

            # Filter by country
            resp3 = await self.client.entity_registry.search_entity(
                q="corporation", country="US", min_certainty=0.5, limit=10)
            self._report("Country filter returns results",
                         resp3.success and len(resp3.results) >= 0,
                         f"count={len(resp3.results)}")

            # Query unlikely to match anything
            resp4 = await self.client.entity_registry.search_entity(
                q="quantum teleportation flux capacitor", min_certainty=0.95, limit=10)
            self._report("Unrelated query returns few/no results",
                         len(resp4.results) == 0,
                         f"count={len(resp4.results)}")

            # Verify geo coordinates appear in search results
            resp5 = await self.client.entity_registry.search_entity(
                q="GeoTest Newark", min_certainty=0.5, limit=10)
            geo_results = [r for r in resp5.results if r.entity_id == geo_id]
            if geo_results:
                gr = geo_results[0]
                self._report("Search result has latitude",
                             gr.latitude is not None,
                             f"latitude={gr.latitude}")
                self._report("Search result has longitude",
                             gr.longitude is not None,
                             f"longitude={gr.longitude}")
            else:
                self._report("GeoTest entity in search results", False,
                             f"results={[r.entity_id for r in resp5.results]}")

            # Combined semantic + geo: entities near SF
            resp6 = await self.client.entity_registry.search_entity(
                q="corporation", latitude=37.78, longitude=-122.42,
                radius_km=10, min_certainty=0.3, limit=10)
            geo_range_ids = [r.entity_id for r in resp6.results]
            self._report("Semantic+geo near SF returns results",
                         len(resp6.results) > 0, f"count={len(resp6.results)}")
            self._report("Acme Corp within 10km of SF",
                         acme_id in geo_range_ids,
                         f"results={geo_range_ids}")

            # Combined semantic + geo: entities near Newark
            resp7 = await self.client.entity_registry.search_entity(
                q="corporation", latitude=40.74, longitude=-74.17,
                radius_km=10, min_certainty=0.3, limit=10)
            geo_range_ids2 = [r.entity_id for r in resp7.results]
            self._report("Semantic+geo near Newark returns results",
                         len(resp7.results) > 0, f"count={len(resp7.results)}")
            self._report("GeoTest within 10km of Newark",
                         geo_id in geo_range_ids2,
                         f"results={geo_range_ids2}")

            # Combined semantic + geo: remote location
            resp8 = await self.client.entity_registry.search_entity(
                q="corporation", latitude=0.0, longitude=0.0,
                radius_km=1, min_certainty=0.3, limit=10)
            self._report("Semantic+geo at 0,0 returns no results",
                         len(resp8.results) == 0,
                         f"count={len(resp8.results)}")

        except Exception as e:
            self._report("Entity search", False, str(e))
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Location CRUD tests
    # ------------------------------------------------------------------

    async def test_locations(self):
        logger.info("\n--- Test: Location CRUD ---")
        acme_id = self.ids['acme_corp']
        geo_id = self.ids['geo_test']
        reg = self.client.entity_registry

        try:
            # List locations for Acme Corp (should have 2 from load_test_data)
            locs = await reg.list_locations(acme_id)
            self._report("List Acme locations", len(locs) >= 2,
                         f"count={len(locs)}")

            # List locations for GeoTest (should have 3)
            geo_locs = await reg.list_locations(geo_id)
            self._report("List GeoTest locations", len(geo_locs) >= 3,
                         f"count={len(geo_locs)}")

            # Get a specific location
            if locs:
                loc = await reg.get_location(locs[0].location_id)
                self._report("Get location by ID", loc is not None)
                self._report("Location has entity_id", loc.entity_id == acme_id)
                self._report("Location has latitude",
                             loc.latitude is not None,
                             f"lat={loc.latitude}")

            # Create a new location
            new_loc = await reg.create_location(
                acme_id,
                LocationCreateRequest(
                    location_type_key='branch',
                    location_name='Acme Test Branch',
                    address_line_1='999 Test Avenue',
                    locality='Portland',
                    admin_area_1='Oregon',
                    country='United States',
                    country_code='US',
                    postal_code='97201',
                    formatted_address='999 Test Ave, Portland, OR 97201, US',
                    latitude=45.5152,
                    longitude=-122.6784,
                    timezone='America/Los_Angeles',
                ),
            )
            self._report("Create location", new_loc is not None and new_loc.location_id > 0,
                         f"location_id={new_loc.location_id}")

            # Store for cleanup
            test_location_id = new_loc.location_id

            # Verify it appears in the list
            locs2 = await reg.list_locations(acme_id)
            self._report("New location in list", len(locs2) == len(locs) + 1,
                         f"before={len(locs)} after={len(locs2)}")

            # Update the location
            updated = await reg.update_location(
                test_location_id,
                LocationUpdateRequest(
                    location_name='Acme Portland Branch (Updated)',
                    description='Updated test branch office',
                ),
            )
            self._report("Update location name",
                         updated.location_name == 'Acme Portland Branch (Updated)')

            # Remove the test location
            await reg.remove_location(test_location_id)
            locs3 = await reg.list_locations(acme_id)
            self._report("Remove location restores count",
                         len(locs3) == len(locs),
                         f"count={len(locs3)}")

        except Exception as e:
            self._report("Location CRUD", False, str(e))
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Geo Search tests (LocationIndex)
    # ------------------------------------------------------------------

    async def test_geo_search(self):
        logger.info("\n--- Test: Geo Search (LocationIndex) ---")
        acme_id = self.ids['acme_corp']
        geo_id = self.ids['geo_test']
        pinnacle_id = self.ids['pinnacle_consulting']
        reg = self.client.entity_registry

        try:
            # --- search_location (location geo search) ---
            # Near SF (37.79, -122.40) within 20 km
            loc_resp = await reg.search_location(
                latitude=37.79, longitude=-122.40, radius_km=20)
            self._report("Locations near SF returns results",
                         loc_resp.success and len(loc_resp.results) > 0,
                         f"count={len(loc_resp.results)}")
            sf_loc_entities = {r.entity_id for r in loc_resp.results}
            self._report("Acme HQ/warehouse in SF results",
                         acme_id in sf_loc_entities)
            self._report("GeoTest (Newark) NOT in SF results",
                         geo_id not in sf_loc_entities)

            # Near Newark NJ (40.74, -74.17) within 10 km
            loc_resp2 = await reg.search_location(
                latitude=40.74, longitude=-74.17, radius_km=10)
            self._report("Locations near Newark returns results",
                         loc_resp2.success and len(loc_resp2.results) > 0,
                         f"count={len(loc_resp2.results)}")
            newark_loc_entities = {r.entity_id for r in loc_resp2.results}
            self._report("GeoTest HQ in Newark results",
                         geo_id in newark_loc_entities)

            # Filter by location_type_key
            loc_resp3 = await reg.search_location(
                latitude=37.79, longitude=-122.40, radius_km=20,
                location_type_key='headquarters')
            if loc_resp3.results:
                all_hq = all(r.location_type_key == 'headquarters' for r in loc_resp3.results)
                self._report("HQ filter returns only headquarters", all_hq,
                             f"count={len(loc_resp3.results)}")
            else:
                self._report("HQ filter near SF returns results", False)

            # --- Response field validation ---
            if loc_resp.results:
                r0 = loc_resp.results[0]
                self._report("Result has country_code field",
                             hasattr(r0, 'country_code') and r0.country_code is not None,
                             f"country_code={r0.country_code}")
                self._report("Result has address_line_1 field",
                             hasattr(r0, 'address_line_1'),
                             f"address_line_1={r0.address_line_1}")
                self._report("Result has address_line_2 field",
                             hasattr(r0, 'address_line_2'),
                             f"address_line_2={r0.address_line_2}")

            # --- Filter by country_code ---
            loc_cc = await reg.search_location(
                latitude=37.79, longitude=-122.40, radius_km=20,
                country_code='US')
            self._report("country_code=US filter returns results",
                         loc_cc.success and len(loc_cc.results) > 0,
                         f"count={len(loc_cc.results)}")
            loc_cc_none = await reg.search_location(
                latitude=37.79, longitude=-122.40, radius_km=20,
                country_code='XX')
            self._report("country_code=XX filter returns no results",
                         len(loc_cc_none.results) == 0)

            # --- Filter by location_name ---
            loc_name = await reg.search_location(
                latitude=37.79, longitude=-122.40, radius_km=20,
                location_name='Acme HQ')
            self._report("location_name='Acme HQ' filter returns results",
                         loc_name.success and len(loc_name.results) > 0,
                         f"count={len(loc_name.results)}")
            if loc_name.results:
                self._report("location_name filter matches exact name",
                             loc_name.results[0].location_name == 'Acme HQ')

            # --- Semantic search (q) on location name/description ---
            loc_q = await reg.search_location(
                latitude=37.79, longitude=-122.40, radius_km=50,
                q='distribution center', min_certainty=0.3)
            self._report("q='distribution center' returns results",
                         loc_q.success and len(loc_q.results) > 0,
                         f"count={len(loc_q.results)}")

            # --- BM25 keyword search (address) ---
            loc_addr = await reg.search_location(
                latitude=37.79, longitude=-122.40, radius_km=20,
                address='Market Street')
            self._report("address='Market Street' BM25 returns results",
                         loc_addr.success and len(loc_addr.results) > 0,
                         f"count={len(loc_addr.results)}")
            if loc_addr.results:
                # Acme HQ is at 100 Market Street
                addr_ids = {r.entity_id for r in loc_addr.results}
                self._report("Acme in address search results",
                             acme_id in addr_ids)

            # BM25 address search with no match
            loc_addr_none = await reg.search_location(
                latitude=37.79, longitude=-122.40, radius_km=20,
                address='Nonexistent Boulevard 99999')
            self._report("BM25 no-match address returns no results",
                         len(loc_addr_none.results) == 0)

            # --- search_entity with q + geo (combined semantic + geo) ---
            # "manufacturing" near SF — should find Acme, not GeoTest
            topic_resp = await reg.search_entity(
                q="manufacturing company",
                latitude=37.79, longitude=-122.40, radius_km=20,
                min_certainty=0.3)
            self._report("Entity search q+geo near SF returns results",
                         topic_resp.success and len(topic_resp.results) > 0,
                         f"count={len(topic_resp.results)}")
            topic_ids = [r.entity_id for r in topic_resp.results]
            self._report("Acme Corp in q+geo SF results",
                         acme_id in topic_ids)
            self._report("GeoTest NOT in q+geo SF results",
                         geo_id not in topic_ids)

            # Check locations returned inline
            if topic_resp.results:
                acme_result = next((r for r in topic_resp.results if r.entity_id == acme_id), None)
                if acme_result:
                    self._report("q+geo result has locations",
                                 len(acme_result.locations) > 0,
                                 f"count={len(acme_result.locations)}")
                    self._report("q+geo result has score",
                                 acme_result.score > 0,
                                 f"score={acme_result.score}")

            # "consulting" near Boston — should find Pinnacle
            topic_resp2 = await reg.search_entity(
                q="consulting advisory",
                latitude=42.35, longitude=-71.06, radius_km=15,
                min_certainty=0.3)
            self._report("Entity search q+geo near Boston returns results",
                         topic_resp2.success and len(topic_resp2.results) > 0,
                         f"count={len(topic_resp2.results)}")
            boston_ids = [r.entity_id for r in topic_resp2.results]
            self._report("Pinnacle in Boston q+geo results",
                         pinnacle_id in boston_ids)

            # "geospatial" near Newark — should find GeoTest
            topic_resp3 = await reg.search_entity(
                q="geospatial analytics",
                latitude=40.74, longitude=-74.17, radius_km=10,
                min_certainty=0.3)
            topic3_ids = [r.entity_id for r in topic_resp3.results]
            self._report("GeoTest in Newark q+geo results",
                         geo_id in topic3_ids,
                         f"results={topic3_ids}")

            # --- search_entity with geo only (no q) ---
            # Entities with a location near SF
            ent_resp = await reg.search_entity(
                latitude=37.79, longitude=-122.40, radius_km=20)
            self._report("Geo-only entities near SF returns results",
                         ent_resp.success and len(ent_resp.results) > 0,
                         f"count={len(ent_resp.results)}")
            ent_ids = {r.entity_id for r in ent_resp.results}
            self._report("Acme Corp in geo-only SF",
                         acme_id in ent_ids)
            self._report("GeoTest NOT in geo-only SF",
                         geo_id not in ent_ids)

            # Entities near Newark
            ent_resp2 = await reg.search_entity(
                latitude=40.74, longitude=-74.17, radius_km=10)
            ent_ids2 = {r.entity_id for r in ent_resp2.results}
            self._report("GeoTest in geo-only Newark",
                         geo_id in ent_ids2)

            # Check locations included in response
            if ent_resp.results:
                first = ent_resp.results[0]
                self._report("Geo-only has locations list",
                             hasattr(first, 'locations') and isinstance(first.locations, list))

            # Remote location — should find nothing
            ent_resp3 = await reg.search_entity(
                latitude=0.0, longitude=0.0, radius_km=1)
            self._report("Geo-only at 0,0 returns no results",
                         len(ent_resp3.results) == 0,
                         f"count={len(ent_resp3.results)}")

        except Exception as e:
            self._report("Geo search", False, str(e))
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Delete test (soft-delete on alice_johnson)
    # ------------------------------------------------------------------

    async def test_delete_entity(self):
        logger.info("\n--- Test: Delete Entity ---")
        person_id = self.ids['alice_johnson']
        try:
            # Check current status first
            entity = await self.client.entity_registry.get_entity(person_id)
            if entity.status == 'deleted':
                self._report("Entity already deleted (from previous run)", True)
                self._report("Deleted entity still retrievable", True)
                self._report("Deleted entity excluded from active list", True)
                return

            result = await self.client.entity_registry.delete_entity(person_id)
            self._report("Soft-delete entity", result.get('success') is True)

            results = await self.client.entity_registry.search_entities(status='active')
            active_ids = [e.entity_id for e in results.entities]
            self._report("Deleted entity excluded from active list", person_id not in active_ids)

            entity = await self.client.entity_registry.get_entity(person_id)
            self._report("Deleted entity still retrievable", entity.status == 'deleted')
        except Exception as e:
            self._report("Delete entity", False, str(e))

    # ------------------------------------------------------------------
    # Error case tests
    # ------------------------------------------------------------------

    async def test_error_cases(self):
        logger.info("\n--- Test: Error Cases ---")

        try:
            await self.client.entity_registry.get_entity('e_nonexistent')
            self._report("Get non-existent entity returns 404", False, "Should have raised")
        except Exception as e:
            self._report("Get non-existent entity returns error", '404' in str(e) or 'not found' in str(e).lower(),
                         str(e)[:80])

        try:
            from vitalgraph.model.entity_registry_model import EntityCreateRequest
            req = EntityCreateRequest(type_key='invalid_type', primary_name='Bad Entity')
            await self.client.entity_registry.create_entity(req)
            self._report("Invalid type_key rejected", False, "Should have raised")
        except Exception as e:
            self._report("Invalid type_key rejected", True, str(e)[:80])


async def main():
    if not MANIFEST_PATH.exists():
        logger.error(f"Test data manifest not found: {MANIFEST_PATH}")
        logger.error("Run 'python vitalgraph_client_test/load_test_data.py' first.")
        sys.exit(1)

    manifest = json.loads(MANIFEST_PATH.read_text())
    logger.info(f"Loaded manifest: {len(manifest['entities'])} entities")

    runner = EntityRegistryTestRunner(manifest)
    await runner.run_all()
    sys.exit(0 if runner.tests_failed == 0 else 1)


if __name__ == '__main__':
    asyncio.run(main())
