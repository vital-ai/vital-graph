#!/usr/bin/env python3
"""
Entity Registry Query Test Script

Tests the full feature set of the Entity Registry via VitalGraphClient
using the real dataset imported from registry_output/.

Covers:
  - Entity CRUD and retrieval
  - Alias lookup and matching
  - Identifier lookup (SF_ACCOUNT_ID, EIN, PHONE, EMAIL, CARDIFF_DM_CODE)
  - Category filtering
  - Geo-radius location search
  - Semantic (vector topic) search
  - Combined semantic + geo search
  - Location search with address BM25
  - Phonetic / typo dedup (find_similar)
  - Relationship traversal
  - Changelog

Does NOT create or delete entities — read-only against the imported dataset.

Usage:
    python vitalgraph_client_test/test_entity_registry_queries.py
"""

import asyncio
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known entities from registry_output/entities.jsonl
# These were selected to exercise every feature:
#   - aliases, identifiers, locations, geo, categories, relationships, websites
# ---------------------------------------------------------------------------

# Business entity with alias "Aces Braces of Flatbush", customer, LLC, Brooklyn NY
ACES_DENTAL = 'ent_xaji0y6dpb'

# Business entity with 6 relationships, Delray Beach FL, EIN + SF_ACCOUNT_ID + PHONE
UPRISING_AGENCY = 'ent_hzn4kgeuid'

# DBA entity with alias "Blue Knight Public Safety", Riverside CA, 3 identifiers, website
BLUE_KNIGHT = 'ent_owgzrixa11'

# Business entity with alias "Topnotch Design Center" (very different from primary), Upland CA
ALPHA_OMEGA = 'ent_phr62gdswm'

# Business entity with alias "FJ Carne En Vara Steakhouse", Kissimmee FL
FPL_GROUP = 'ent_l8hl88kzru'

# Business entity with alias "Mr. Handyman", Indianola IA, S Corporation
HOBBS_KOLO = 'ent_gh8riec4d1'

# Business entity with alias "Alaska Landworks", Anchorage AK
SUB_ZERO = 'ent_39pecn0dl5'

# Business entity with alias "Pixel Canvas", Los Angeles CA, corporation
PIXEL_CANVAS = 'ent_gx32uew9g6'

# Business person with 5 identifiers (SF_LEAD_ID, EMAIL, PHONE, CARDIFF_DM_CODE)
DOLORES_DE_ALBA = 'ent_tp4julsxl8'

# Business entity with alias "Smoking Monkey Pizza", misspelled name "Tb Enterpises", Renton WA
TB_ENTERPISES = 'ent_w1wudcbl4c'

# Business entity, Brown Brothers Construction, San Clemente CA, S Corp, customer
BROWN_BROTHERS = 'ent_hsahxthv3a'

# Business entity, Quick Cakes Gnv LLC, Gainesville FL, 4 relationships
QUICK_CAKES = 'ent_ww4fyb8dal'

# Business entity, Spectra Development Inc, alias "Spectra", Brooklyn NY
SPECTRA_DEV = 'ent_l1cq99chj7'

# Business person with EMAIL identifier
NINA_ANDERSON = 'ent_j8np9s8e9g'

# Business entity, Daniel Patrick Inc, Los Angeles CA, 4 relationships
DANIEL_PATRICK = 'ent_pkianouof0'

# Geo reference points (city centers)
GEO_NYC = (40.7128, -74.0060)
GEO_LA = (34.0522, -118.2437)
GEO_MIAMI = (25.7617, -80.1918)
GEO_CHICAGO = (41.8781, -87.6298)
GEO_HOUSTON = (29.7604, -95.3698)
GEO_ANCHORAGE = (61.2181, -149.9003)
GEO_BROOKLYN = (40.6782, -73.9442)
GEO_RIVERSIDE = (33.9806, -117.3755)


class QueryTestRunner:
    """Runs entity registry query tests against the real imported dataset."""

    def __init__(self):
        self.client = VitalGraphClient()
        self.reg = None  # set after open
        self.tests_passed = 0
        self.tests_failed = 0
        self.tests_skipped = 0

    def _report(self, name: str, passed: bool, detail: str = ""):
        if passed:
            self.tests_passed += 1
            logger.info(f"  PASS: {name}{' - ' + detail if detail else ''}")
        else:
            self.tests_failed += 1
            logger.error(f"  FAIL: {name}{' - ' + detail if detail else ''}")

    def _skip(self, name: str, reason: str):
        self.tests_skipped += 1
        logger.warning(f"  SKIP: {name} - {reason}")

    async def run_all(self):
        logger.info("=" * 70)
        logger.info("Entity Registry Query Tests (real dataset)")
        logger.info("=" * 70)

        try:
            await self.client.open()
            self.reg = self.client.entity_registry
            logger.info("Client connected")
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return

        try:
            await self.test_get_entity_basic()
            await self.test_get_entity_with_alias()
            await self.test_identifiers_lookup()
            await self.test_identifier_by_ein()
            await self.test_identifier_by_email()
            await self.test_aliases_list()
            await self.test_categories()
            await self.test_category_filter()
            await self.test_relationships()
            await self.test_search_entities_by_name()
            await self.test_search_entities_by_type()
            await self.test_find_similar_exact()
            await self.test_find_similar_alias()
            await self.test_find_similar_dba()
            await self.test_find_similar_typo()
            await self.test_find_similar_phonetic()
            await self.test_find_similar_partial()
            await self.test_semantic_search_topic()
            await self.test_semantic_search_industry()
            await self.test_semantic_search_no_match()
            await self.test_geo_search_location_brooklyn()
            await self.test_geo_search_location_la()
            await self.test_geo_search_location_anchorage()
            await self.test_geo_search_location_type_filter()
            await self.test_geo_search_location_country_filter()
            await self.test_geo_search_address_bm25()
            await self.test_entity_search_semantic_only()
            await self.test_entity_search_geo_only()
            await self.test_entity_search_semantic_plus_geo()
            await self.test_entity_search_remote_location()
            await self.test_changelog()
            await self.test_location_crud()
            await self.test_error_cases()
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            traceback.print_exc()
        finally:
            await self.client.close()

        logger.info("=" * 70)
        total = self.tests_passed + self.tests_failed
        logger.info(f"Results: {self.tests_passed}/{total} passed, "
                     f"{self.tests_failed} failed, {self.tests_skipped} skipped")
        logger.info("=" * 70)

    # ------------------------------------------------------------------
    # Entity retrieval
    # ------------------------------------------------------------------

    async def test_get_entity_basic(self):
        logger.info("\n--- Get Entity (basic fields) ---")
        try:
            e = await self.reg.get_entity(ACES_DENTAL)
            self._report("Get by ID", e.entity_id == ACES_DENTAL)
            self._report("Has primary_name", e.primary_name == 'Aces Dental, P.C.')
            self._report("Has entity_uri", e.entity_uri is not None and e.entity_uri.startswith('urn:entity:'))
            self._report("Type key is business_entity", e.type_key == 'business_entity')
            self._report("Country is US", e.country == 'US')
            self._report("Region is NY", e.region == 'NY')
            self._report("Locality is Brooklyn", e.locality == 'Brooklyn')
            self._report("Has latitude", e.latitude is not None and abs(e.latitude - 40.6546) < 0.01,
                         f"lat={e.latitude}")
            self._report("Has longitude", e.longitude is not None and abs(e.longitude - (-73.9306)) < 0.01,
                         f"lon={e.longitude}")
            self._report("Has website", e.website == 'http://www.acesbraces.com')
        except Exception as ex:
            self._report("Get entity basic", False, str(ex))

    async def test_get_entity_with_alias(self):
        logger.info("\n--- Get Entity (aliases + identifiers inline) ---")
        try:
            e = await self.reg.get_entity(ACES_DENTAL)
            self._report("Has aliases list", e.aliases is not None and len(e.aliases) >= 1,
                         f"count={len(e.aliases) if e.aliases else 0}")
            if e.aliases:
                alias_names = [a.alias_name for a in e.aliases]
                self._report("Alias 'Aces Braces of Flatbush' present",
                             'Aces Braces of Flatbush' in alias_names,
                             f"aliases={alias_names}")
            self._report("Has identifiers list", e.identifiers is not None and len(e.identifiers) >= 2,
                         f"count={len(e.identifiers) if e.identifiers else 0}")
            if e.identifiers:
                ns_set = {i.identifier_namespace for i in e.identifiers}
                self._report("Has SF_ACCOUNT_ID identifier", 'SF_ACCOUNT_ID' in ns_set)
                self._report("Has PHONE identifier", 'PHONE' in ns_set)
        except Exception as ex:
            self._report("Get entity with alias", False, str(ex))

    # ------------------------------------------------------------------
    # Identifier lookup
    # ------------------------------------------------------------------

    async def test_identifiers_lookup(self):
        logger.info("\n--- Identifier Lookup (SF_ACCOUNT_ID) ---")
        try:
            results = await self.reg.lookup_by_identifier(
                'SF_ACCOUNT_ID', '0018b00002MhtCzAAJ')
            found_ids = [e.entity_id for e in results]
            self._report("Lookup SF_ACCOUNT_ID finds Aces Dental",
                         ACES_DENTAL in found_ids,
                         f"matched={len(results)}")
        except Exception as ex:
            self._report("Identifier lookup SF_ACCOUNT_ID", False, str(ex))

    async def test_identifier_by_ein(self):
        logger.info("\n--- Identifier Lookup (EIN) ---")
        try:
            # Uprising Agency has EIN 87-1490780
            results = await self.reg.lookup_by_identifier('EIN', '87-1490780')
            found_ids = [e.entity_id for e in results]
            self._report("Lookup EIN finds Uprising Agency",
                         UPRISING_AGENCY in found_ids,
                         f"matched={len(results)}")
        except Exception as ex:
            self._report("Identifier lookup EIN", False, str(ex))

    async def test_identifier_by_email(self):
        logger.info("\n--- Identifier Lookup (EMAIL) ---")
        try:
            # Nina Anderson has EMAIL hello@thegroomhaus.com
            results = await self.reg.lookup_by_identifier(
                'EMAIL', 'hello@thegroomhaus.com')
            found_ids = [e.entity_id for e in results]
            self._report("Lookup EMAIL finds Nina Anderson",
                         NINA_ANDERSON in found_ids,
                         f"matched={len(results)}")
        except Exception as ex:
            self._report("Identifier lookup EMAIL", False, str(ex))

    # ------------------------------------------------------------------
    # Aliases
    # ------------------------------------------------------------------

    async def test_aliases_list(self):
        logger.info("\n--- List Aliases ---")
        try:
            aliases = await self.reg.list_aliases(ALPHA_OMEGA)
            alias_names = [a.alias_name for a in aliases]
            self._report("Alpha Omega has aliases", len(aliases) >= 1,
                         f"count={len(aliases)}")
            self._report("Alias 'Topnotch Design Center' present",
                         'Topnotch Design Center' in alias_names,
                         f"aliases={alias_names}")

            aliases2 = await self.reg.list_aliases(TB_ENTERPISES)
            alias_names2 = [a.alias_name for a in aliases2]
            self._report("Tb Enterpises has alias 'Smoking Monkey Pizza'",
                         'Smoking Monkey Pizza' in alias_names2,
                         f"aliases={alias_names2}")
        except Exception as ex:
            self._report("List aliases", False, str(ex))

    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------

    async def test_categories(self):
        logger.info("\n--- List Entity Categories ---")
        try:
            cats = await self.reg.list_entity_categories(ACES_DENTAL)
            cat_keys = [c.category_key for c in cats]
            self._report("Aces Dental has categories", len(cats) >= 2,
                         f"keys={cat_keys}")
            self._report("Has 'customer' category", 'customer' in cat_keys)
            self._report("Has 'llc' category", 'llc' in cat_keys)

            cats2 = await self.reg.list_entity_categories(HOBBS_KOLO)
            cat_keys2 = [c.category_key for c in cats2]
            self._report("Hobbs Kolo has 's_corporation' category",
                         's_corporation' in cat_keys2,
                         f"keys={cat_keys2}")
        except Exception as ex:
            self._report("Categories", False, str(ex))

    async def test_category_filter(self):
        logger.info("\n--- List Entities by Category ---")
        try:
            entities = await self.reg.list_entities_by_category('customer')
            self._report("Customer category has entities", len(entities) > 0,
                         f"count={len(entities)}")
            customer_ids = [e.entity_id for e in entities]
            self._report("Aces Dental in customer list",
                         ACES_DENTAL in customer_ids)
        except Exception as ex:
            self._report("Category filter", False, str(ex))

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    async def test_relationships(self):
        logger.info("\n--- Relationships ---")
        try:
            rels = await self.reg.list_relationships(UPRISING_AGENCY)
            self._report("Uprising Agency has relationships", len(rels) >= 4,
                         f"count={len(rels)}")
            if rels:
                type_keys = {r.relationship_type_key for r in rels}
                self._report("Has 'owner_of' relationship", 'owner_of' in type_keys,
                             f"types={type_keys}")

            rels2 = await self.reg.list_relationships(QUICK_CAKES)
            self._report("Quick Cakes has relationships", len(rels2) >= 2,
                         f"count={len(rels2)}")
        except Exception as ex:
            self._report("Relationships", False, str(ex))

    # ------------------------------------------------------------------
    # Search entities (PostgreSQL text search)
    # ------------------------------------------------------------------

    async def test_search_entities_by_name(self):
        logger.info("\n--- Search Entities by Name ---")
        try:
            results = await self.reg.search_entities(query='Aces Dental')
            self._report("Search 'Aces Dental' returns results",
                         results.total_count >= 1,
                         f"total={results.total_count}")
            found_ids = [e.entity_id for e in results.entities]
            self._report("Aces Dental in results", ACES_DENTAL in found_ids)

            results2 = await self.reg.search_entities(query='Pixel Canvas')
            found_ids2 = [e.entity_id for e in results2.entities]
            self._report("Search 'Pixel Canvas' finds entity",
                         PIXEL_CANVAS in found_ids2,
                         f"total={results2.total_count}")
        except Exception as ex:
            self._report("Search by name", False, str(ex))

    async def test_search_entities_by_type(self):
        logger.info("\n--- Search Entities by Type ---")
        try:
            results = await self.reg.search_entities(
                type_key='business_person', page_size=5)
            self._report("Filter by business_person returns results",
                         results.total_count > 0,
                         f"total={results.total_count}")
            all_correct = all(e.type_key == 'business_person' for e in results.entities)
            self._report("All results are business_person type", all_correct)
        except Exception as ex:
            self._report("Search by type", False, str(ex))

    # ------------------------------------------------------------------
    # Find Similar (phonetic / typo / dedup)
    # ------------------------------------------------------------------

    async def test_find_similar_exact(self):
        logger.info("\n--- Find Similar (exact match) ---")
        try:
            resp = await self.reg.find_similar("Aces Dental, P.C.", min_score=50.0)
            self._report("Find similar returns response", resp.success is True)
            candidate_ids = [c.entity_id for c in resp.candidates]
            self._report("Aces Dental in results", ACES_DENTAL in candidate_ids,
                         f"candidates={len(resp.candidates)}")
            if resp.candidates:
                top = resp.candidates[0]
                self._report("Top score > 80", top.score > 80, f"score={top.score}")
                self._report("Has score_detail", top.score_detail is not None)
        except Exception as ex:
            self._report("Find similar exact", False, str(ex))

    async def test_find_similar_alias(self):
        logger.info("\n--- Find Similar (alias match) ---")
        try:
            # "Aces Braces of Flatbush" is an alias of Aces Dental
            resp = await self.reg.find_similar("Aces Braces of Flatbush", min_score=30.0)
            candidate_ids = [c.entity_id for c in resp.candidates]
            self._report("Alias 'Aces Braces of Flatbush' finds Aces Dental",
                         ACES_DENTAL in candidate_ids,
                         f"candidates={len(resp.candidates)}")

            # "Smoking Monkey Pizza" is alias of Tb Enterpises LLC
            resp2 = await self.reg.find_similar("Smoking Monkey Pizza", min_score=30.0)
            candidate_ids2 = [c.entity_id for c in resp2.candidates]
            self._report("Alias 'Smoking Monkey Pizza' finds Tb Enterpises",
                         TB_ENTERPISES in candidate_ids2,
                         f"candidates={len(resp2.candidates)}")

            # "Mr. Handyman" is alias of Hobbs Kolo Enterprises
            resp3 = await self.reg.find_similar("Mr. Handyman", min_score=30.0)
            candidate_ids3 = [c.entity_id for c in resp3.candidates]
            self._report("Alias 'Mr. Handyman' finds Hobbs Kolo",
                         HOBBS_KOLO in candidate_ids3,
                         f"candidates={len(resp3.candidates)}")
        except Exception as ex:
            self._report("Find similar alias", False, str(ex))

    async def test_find_similar_dba(self):
        logger.info("\n--- Find Similar (DBA name) ---")
        try:
            # "Blue Knight Protection Services" is part of the DBA name
            resp = await self.reg.find_similar(
                "Blue Knight Protection Services", min_score=30.0)
            candidate_ids = [c.entity_id for c in resp.candidates]
            self._report("'Blue Knight Protection Services' finds entity",
                         BLUE_KNIGHT in candidate_ids,
                         f"candidates={len(resp.candidates)}")

            # The alias "Blue Knight Public Safety" should also match
            resp2 = await self.reg.find_similar(
                "Blue Knight Public Safety", min_score=30.0)
            candidate_ids2 = [c.entity_id for c in resp2.candidates]
            self._report("'Blue Knight Public Safety' (alias) finds entity",
                         BLUE_KNIGHT in candidate_ids2,
                         f"candidates={len(resp2.candidates)}")
        except Exception as ex:
            self._report("Find similar DBA", False, str(ex))

    async def test_find_similar_typo(self):
        logger.info("\n--- Find Similar (typo / misspelling) ---")
        try:
            # "Aces Dential" (typo for Dental)
            resp = await self.reg.find_similar("Aces Dential", min_score=30.0)
            candidate_ids = [c.entity_id for c in resp.candidates]
            self._report("Typo 'Aces Dential' finds Aces Dental",
                         ACES_DENTAL in candidate_ids,
                         f"candidates={len(resp.candidates)}")

            # "Pixle Canvas" (transposition)
            resp2 = await self.reg.find_similar("Pixle Canvas Inc", min_score=30.0)
            candidate_ids2 = [c.entity_id for c in resp2.candidates]
            self._report("Typo 'Pixle Canvas' finds Pixel Canvas",
                         PIXEL_CANVAS in candidate_ids2,
                         f"candidates={len(resp2.candidates)}")

            # "Browm Brothers Construction" (m for n)
            resp3 = await self.reg.find_similar(
                "Browm Brothers Construction", min_score=30.0)
            candidate_ids3 = [c.entity_id for c in resp3.candidates]
            self._report("Typo 'Browm Brothers' finds Brown Brothers",
                         BROWN_BROTHERS in candidate_ids3,
                         f"candidates={len(resp3.candidates)}")
        except Exception as ex:
            self._report("Find similar typo", False, str(ex))

    async def test_find_similar_phonetic(self):
        logger.info("\n--- Find Similar (phonetic) ---")
        try:
            # "Spectra Developement" (phonetically same, different spelling)
            resp = await self.reg.find_similar(
                "Spectra Developement Inc", min_score=30.0)
            candidate_ids = [c.entity_id for c in resp.candidates]
            self._report("Phonetic 'Spectra Developement' finds Spectra Development",
                         SPECTRA_DEV in candidate_ids,
                         f"candidates={len(resp.candidates)}")

            # "Sub Zeero Thawing" (phonetic variation)
            resp2 = await self.reg.find_similar(
                "Sub Zeero Thawing", min_score=30.0)
            candidate_ids2 = [c.entity_id for c in resp2.candidates]
            self._report("Phonetic 'Sub Zeero Thawing' finds Sub Zero Thawing",
                         SUB_ZERO in candidate_ids2,
                         f"candidates={len(resp2.candidates)}")
        except Exception as ex:
            self._report("Find similar phonetic", False, str(ex))

    async def test_find_similar_partial(self):
        logger.info("\n--- Find Similar (partial / abbreviated) ---")
        try:
            # "Uprising Agency" without LLC
            resp = await self.reg.find_similar("Uprising Agency", min_score=40.0)
            candidate_ids = [c.entity_id for c in resp.candidates]
            self._report("'Uprising Agency' (no LLC) finds full entity",
                         UPRISING_AGENCY in candidate_ids,
                         f"candidates={len(resp.candidates)}")

            # Unrelated name should return nothing
            resp2 = await self.reg.find_similar(
                "Xyloquest Barvonian Plc", min_score=70.0)
            self._report("Unrelated name returns no matches",
                         len(resp2.candidates) == 0,
                         f"candidates={len(resp2.candidates)}")
        except Exception as ex:
            self._report("Find similar partial", False, str(ex))

    # ------------------------------------------------------------------
    # Semantic (Weaviate vector topic) search
    # ------------------------------------------------------------------

    async def test_semantic_search_topic(self):
        logger.info("\n--- Semantic Search (topic) ---")
        try:
            # "dental clinic" should find Aces Dental
            resp = await self.reg.search_entity(
                q="dental clinic orthodontics", min_certainty=0.3, limit=10)
            self._report("Semantic search returns results",
                         resp.success and len(resp.results) > 0,
                         f"count={len(resp.results)}")
            result_ids = [r.entity_id for r in resp.results]
            self._report("Aces Dental in dental topic results",
                         ACES_DENTAL in result_ids,
                         f"results={result_ids[:5]}")
        except Exception as ex:
            self._report("Semantic search topic", False, str(ex))

    async def test_semantic_search_industry(self):
        logger.info("\n--- Semantic Search (industry terms) ---")
        try:
            # "trucking logistics transportation" should find trucking companies
            resp = await self.reg.search_entity(
                q="trucking logistics transportation", min_certainty=0.3, limit=10)
            self._report("Trucking search returns results",
                         resp.success and len(resp.results) > 0,
                         f"count={len(resp.results)}")
            if resp.results:
                names = [r.primary_name for r in resp.results]
                has_trucking = any('truck' in n.lower() or 'transport' in n.lower()
                                   or 'logistics' in n.lower() or 'hauling' in n.lower()
                                   for n in names)
                self._report("Results contain trucking-related entities",
                             has_trucking, f"names={names[:5]}")

            # "construction building contractor" should find construction companies
            resp2 = await self.reg.search_entity(
                q="construction building contractor", min_certainty=0.3, limit=10)
            self._report("Construction search returns results",
                         resp2.success and len(resp2.results) > 0,
                         f"count={len(resp2.results)}")
        except Exception as ex:
            self._report("Semantic search industry", False, str(ex))

    async def test_semantic_search_no_match(self):
        logger.info("\n--- Semantic Search (no match) ---")
        try:
            resp = await self.reg.search_entity(
                q="quantum teleportation flux capacitor antimatter",
                min_certainty=0.95, limit=10)
            self._report("Nonsense query returns no results",
                         len(resp.results) == 0,
                         f"count={len(resp.results)}")
        except Exception as ex:
            self._report("Semantic search no match", False, str(ex))

    # ------------------------------------------------------------------
    # Geo-radius location search
    # ------------------------------------------------------------------

    async def test_geo_search_location_brooklyn(self):
        logger.info("\n--- Geo Location Search (Brooklyn) ---")
        try:
            resp = await self.reg.search_location(
                latitude=GEO_BROOKLYN[0], longitude=GEO_BROOKLYN[1],
                radius_km=10, limit=100)
            self._report("Brooklyn location search returns results",
                         resp.success and len(resp.results) > 0,
                         f"count={len(resp.results)}")
            loc_entity_ids = {r.entity_id for r in resp.results}
            self._report("Aces Dental (Brooklyn) in results",
                         ACES_DENTAL in loc_entity_ids)
            # Spectra Development is also in Brooklyn
            self._report("Spectra Dev (Brooklyn) in results",
                         SPECTRA_DEV in loc_entity_ids)
            # LA entities should NOT be in Brooklyn results
            self._report("LA entity NOT in Brooklyn results",
                         PIXEL_CANVAS not in loc_entity_ids)
        except Exception as ex:
            self._report("Geo search Brooklyn", False, str(ex))

    async def test_geo_search_location_la(self):
        logger.info("\n--- Geo Location Search (Los Angeles) ---")
        try:
            resp = await self.reg.search_location(
                latitude=GEO_LA[0], longitude=GEO_LA[1],
                radius_km=25, limit=100)
            self._report("LA location search returns results",
                         resp.success and len(resp.results) > 0,
                         f"count={len(resp.results)}")
            la_entity_ids = {r.entity_id for r in resp.results}
            self._report("Pixel Canvas (LA) in results",
                         PIXEL_CANVAS in la_entity_ids)
            self._report("Daniel Patrick (LA) in results",
                         DANIEL_PATRICK in la_entity_ids)
        except Exception as ex:
            self._report("Geo search LA", False, str(ex))

    async def test_geo_search_location_anchorage(self):
        logger.info("\n--- Geo Location Search (Anchorage) ---")
        try:
            resp = await self.reg.search_location(
                latitude=GEO_ANCHORAGE[0], longitude=GEO_ANCHORAGE[1],
                radius_km=50, limit=20)
            self._report("Anchorage location search returns results",
                         resp.success and len(resp.results) > 0,
                         f"count={len(resp.results)}")
            ak_entity_ids = {r.entity_id for r in resp.results}
            self._report("Sub Zero Thawing (Anchorage) in results",
                         SUB_ZERO in ak_entity_ids)
        except Exception as ex:
            self._report("Geo search Anchorage", False, str(ex))

    async def test_geo_search_location_type_filter(self):
        logger.info("\n--- Geo Location Search (type filter) ---")
        try:
            resp = await self.reg.search_location(
                latitude=GEO_LA[0], longitude=GEO_LA[1],
                radius_km=25, location_type_key='headquarters', limit=20)
            self._report("HQ filter returns results",
                         resp.success and len(resp.results) > 0,
                         f"count={len(resp.results)}")
            if resp.results:
                all_hq = all(r.location_type_key == 'headquarters' for r in resp.results)
                self._report("All results are headquarters", all_hq)
        except Exception as ex:
            self._report("Geo search type filter", False, str(ex))

    async def test_geo_search_location_country_filter(self):
        logger.info("\n--- Geo Location Search (country filter) ---")
        try:
            resp = await self.reg.search_location(
                latitude=GEO_NYC[0], longitude=GEO_NYC[1],
                radius_km=20, country_code='US', limit=20)
            self._report("country_code=US returns results",
                         resp.success and len(resp.results) > 0,
                         f"count={len(resp.results)}")

            resp2 = await self.reg.search_location(
                latitude=GEO_NYC[0], longitude=GEO_NYC[1],
                radius_km=20, country_code='XX', limit=20)
            self._report("country_code=XX returns no results",
                         len(resp2.results) == 0)
        except Exception as ex:
            self._report("Geo search country filter", False, str(ex))

    async def test_geo_search_address_bm25(self):
        logger.info("\n--- Geo Location Search (address BM25) ---")
        try:
            # Aces Dental is at 763 Utica Ave, Brooklyn
            resp = await self.reg.search_location(
                latitude=GEO_BROOKLYN[0], longitude=GEO_BROOKLYN[1],
                radius_km=15, address='Utica Ave', limit=20)
            self._report("Address 'Utica Ave' returns results",
                         resp.success and len(resp.results) > 0,
                         f"count={len(resp.results)}")
            if resp.results:
                addr_entity_ids = {r.entity_id for r in resp.results}
                self._report("Aces Dental in address results",
                             ACES_DENTAL in addr_entity_ids)

            # No-match address — use gibberish with no real-word substrings
            resp2 = await self.reg.search_location(
                latitude=GEO_BROOKLYN[0], longitude=GEO_BROOKLYN[1],
                radius_km=15, address='Xzqvwk Jmlnrt', limit=20)
            self._report("Gibberish address returns no results",
                         len(resp2.results) == 0,
                         f"count={len(resp2.results)}")
        except Exception as ex:
            self._report("Geo search address BM25", False, str(ex))

    # ------------------------------------------------------------------
    # Entity search (unified semantic + geo)
    # ------------------------------------------------------------------

    async def test_entity_search_semantic_only(self):
        logger.info("\n--- Entity Search (semantic only) ---")
        try:
            resp = await self.reg.search_entity(
                q="pizza restaurant food service", min_certainty=0.3, limit=10)
            self._report("Food/pizza search returns results",
                         resp.success and len(resp.results) > 0,
                         f"count={len(resp.results)}")
            if resp.results:
                top = resp.results[0]
                self._report("Result has score", top.score > 0, f"score={top.score}")
                self._report("Result has entity_id", top.entity_id is not None)
                self._report("Result has type_key", top.type_key is not None)
        except Exception as ex:
            self._report("Entity search semantic", False, str(ex))

    async def test_entity_search_geo_only(self):
        logger.info("\n--- Entity Search (geo only) ---")
        try:
            # Entities near Miami
            resp = await self.reg.search_entity(
                latitude=GEO_MIAMI[0], longitude=GEO_MIAMI[1],
                radius_km=20, limit=20)
            self._report("Geo-only Miami returns results",
                         resp.success and len(resp.results) > 0,
                         f"count={len(resp.results)}")

            # Entities near Anchorage (sparse)
            resp2 = await self.reg.search_entity(
                latitude=GEO_ANCHORAGE[0], longitude=GEO_ANCHORAGE[1],
                radius_km=50, limit=20)
            ak_ids = {r.entity_id for r in resp2.results}
            self._report("Geo-only Anchorage finds Sub Zero Thawing",
                         SUB_ZERO in ak_ids,
                         f"count={len(resp2.results)}")
        except Exception as ex:
            self._report("Entity search geo only", False, str(ex))

    async def test_entity_search_semantic_plus_geo(self):
        logger.info("\n--- Entity Search (semantic + geo combined) ---")
        try:
            # "dental" near Brooklyn — should find Aces Dental
            resp = await self.reg.search_entity(
                q="dental clinic", latitude=GEO_BROOKLYN[0],
                longitude=GEO_BROOKLYN[1], radius_km=15,
                min_certainty=0.3, limit=10)
            self._report("Semantic+geo 'dental' near Brooklyn returns results",
                         resp.success and len(resp.results) > 0,
                         f"count={len(resp.results)}")
            result_ids = [r.entity_id for r in resp.results]
            self._report("Aces Dental in semantic+geo Brooklyn results",
                         ACES_DENTAL in result_ids)

            # "construction" near Houston
            resp2 = await self.reg.search_entity(
                q="construction contractor building",
                latitude=GEO_HOUSTON[0], longitude=GEO_HOUSTON[1],
                radius_km=20, min_certainty=0.3, limit=10)
            self._report("Semantic+geo 'construction' near Houston returns results",
                         resp2.success and len(resp2.results) > 0,
                         f"count={len(resp2.results)}")

            # Check that locations are included in response
            if resp.results:
                acme_r = next((r for r in resp.results if r.entity_id == ACES_DENTAL), None)
                if acme_r:
                    self._report("Result has locations list",
                                 hasattr(acme_r, 'locations') and len(acme_r.locations) > 0,
                                 f"loc_count={len(acme_r.locations)}")
        except Exception as ex:
            self._report("Entity search semantic+geo", False, str(ex))

    async def test_entity_search_remote_location(self):
        logger.info("\n--- Entity Search (remote location) ---")
        try:
            # Middle of the ocean — should find nothing
            resp = await self.reg.search_entity(
                latitude=0.0, longitude=0.0, radius_km=1, limit=10)
            self._report("Search at 0,0 returns no results",
                         len(resp.results) == 0,
                         f"count={len(resp.results)}")
        except Exception as ex:
            self._report("Entity search remote", False, str(ex))

    # ------------------------------------------------------------------
    # Changelog
    # ------------------------------------------------------------------

    async def test_changelog(self):
        logger.info("\n--- Changelog ---")
        try:
            cl = await self.reg.get_entity_changelog(ACES_DENTAL, limit=10)
            self._report("Entity changelog returns entries",
                         cl.success and cl.total_count > 0,
                         f"total={cl.total_count}")

            recent = await self.reg.get_recent_changelog(limit=10)
            self._report("Recent changelog returns entries",
                         recent.success and len(recent.entries) > 0,
                         f"count={len(recent.entries)}")
        except Exception as ex:
            self._report("Changelog", False, str(ex))

    # ------------------------------------------------------------------
    # Location CRUD (create, verify, remove)
    # ------------------------------------------------------------------

    async def test_location_crud(self):
        logger.info("\n--- Location CRUD ---")
        try:
            from vitalgraph.model.entity_registry_model import (
                LocationCreateRequest, LocationUpdateRequest)

            # List existing locations
            locs = await self.reg.list_locations(ACES_DENTAL)
            original_count = len(locs)
            self._report("List locations", original_count >= 1,
                         f"count={original_count}")

            if locs:
                loc0 = await self.reg.get_location(locs[0].location_id)
                self._report("Get location by ID", loc0 is not None)
                self._report("Location has latitude", loc0.latitude is not None)

            # Create a test location
            new_loc = await self.reg.create_location(
                ACES_DENTAL,
                LocationCreateRequest(
                    location_type_key='branch',
                    location_name='Aces Dental Test Branch',
                    address_line_1='999 Test Avenue',
                    locality='Manhattan',
                    admin_area_1='NY',
                    country='United States',
                    country_code='US',
                    postal_code='10001',
                    latitude=40.7484,
                    longitude=-73.9967,
                ))
            self._report("Create location", new_loc.location_id > 0,
                         f"id={new_loc.location_id}")

            # Update it
            updated = await self.reg.update_location(
                new_loc.location_id,
                LocationUpdateRequest(location_name='Aces Dental Manhattan (Updated)'))
            self._report("Update location name",
                         updated.location_name == 'Aces Dental Manhattan (Updated)')

            # Remove it
            await self.reg.remove_location(new_loc.location_id)
            locs_after = await self.reg.list_locations(ACES_DENTAL)
            self._report("Remove restores count",
                         len(locs_after) == original_count,
                         f"before={original_count} after={len(locs_after)}")
        except Exception as ex:
            self._report("Location CRUD", False, str(ex))
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Error cases
    # ------------------------------------------------------------------

    async def test_error_cases(self):
        logger.info("\n--- Error Cases ---")
        try:
            await self.reg.get_entity('ent_nonexistent_xyz')
            self._report("Get non-existent entity raises error", False, "Should have raised")
        except Exception as e:
            self._report("Get non-existent entity raises error",
                         '404' in str(e) or 'not found' in str(e).lower(),
                         str(e)[:80])


async def main():
    runner = QueryTestRunner()
    await runner.run_all()
    sys.exit(0 if runner.tests_failed == 0 else 1)


if __name__ == '__main__':
    asyncio.run(main())
