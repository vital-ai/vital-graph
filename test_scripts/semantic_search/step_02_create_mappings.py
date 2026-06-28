#!/usr/bin/env python3
"""
Step 2: Create KG Types, Search Mappings, Indexes & Geo Config

Creates the full indexing infrastructure needed before data insertion:
  1. KG Types (entity types, frame types, slot types, relation types)
  2. Vector index  + vector mapping with properties
  3. FTS index     + search mapping with properties
  4. Fuzzy index   + fuzzy mapping with properties
  5. Geo config (enabled, auto-sync)
"""

import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Path & env setup
# ---------------------------------------------------------------------------
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path)

# ---------------------------------------------------------------------------
# Imports (after path setup)
# ---------------------------------------------------------------------------
from vitalgraph.client.vitalgraph_client import VitalGraphClient

from ai_haley_kg_domain.model.KGEntityType import KGEntityType
from ai_haley_kg_domain.model.KGFrameType import KGFrameType
from ai_haley_kg_domain.model.KGSlotType import KGSlotType
from ai_haley_kg_domain.model.KGRelationType import KGRelationType

from test_scripts.semantic_search.config import (
    TEST_SPACE_ID, TEST_GRAPH_ID,
    VECTOR_INDEX_NAME, FTS_INDEX_NAME, FUZZY_INDEX_NAME, HYBRID_INDEX_NAME,
    PROP_NAME, PROP_DESCRIPTION, PROP_TEXT_SLOT,
    GEO_DATATYPE_GEOLOCATION, GEO_DATATYPE_WKT,
    ENTITY_TYPE_RESTAURANT, ENTITY_TYPE_LANDMARK, ENTITY_TYPE_ARTICLE,
    FRAME_TYPE_LOCATION, FRAME_TYPE_DESCRIPTION, FRAME_TYPE_METADATA,
    SLOT_TYPE_CITY, SLOT_TYPE_COUNTRY, SLOT_TYPE_SUMMARY,
    SLOT_TYPE_CATEGORY, SLOT_TYPE_YEAR,
    RELATION_TYPE_NEAR, RELATION_TYPE_MENTIONS,
)


# ===========================================================================
# KG Type definitions
# ===========================================================================
def build_kg_types():
    """Return a list of KG Type graph objects for insertion."""
    types = []

    # Entity types
    for uri, name, desc in [
        (ENTITY_TYPE_RESTAURANT, "RestaurantEntity", "An entity representing a restaurant or food establishment"),
        (ENTITY_TYPE_LANDMARK, "LandmarkEntity", "An entity representing a notable landmark or point of interest"),
        (ENTITY_TYPE_ARTICLE, "ArticleEntity", "An entity representing an article or written content"),
    ]:
        t = KGEntityType()
        t.URI = uri
        t.name = name
        t.kGraphDescription = desc
        types.append(t)

    # Frame types
    for uri, name, desc in [
        (FRAME_TYPE_LOCATION, "LocationFrame", "Frame holding geographic location data"),
        (FRAME_TYPE_DESCRIPTION, "DescriptionFrame", "Frame holding a textual description"),
        (FRAME_TYPE_METADATA, "MetadataFrame", "Frame holding metadata (category, year, etc.)"),
    ]:
        t = KGFrameType()
        t.URI = uri
        t.name = name
        t.kGraphDescription = desc
        types.append(t)

    # Slot types
    for uri, name, desc in [
        (SLOT_TYPE_CITY, "CitySlot", "Text slot for city name"),
        (SLOT_TYPE_COUNTRY, "CountrySlot", "Text slot for country name"),
        (SLOT_TYPE_SUMMARY, "SummarySlot", "Text slot for summary / description text"),
        (SLOT_TYPE_CATEGORY, "CategorySlot", "Text slot for category label"),
        (SLOT_TYPE_YEAR, "YearSlot", "Integer slot for year"),
    ]:
        t = KGSlotType()
        t.URI = uri
        t.name = name
        t.kGraphDescription = desc
        types.append(t)

    # Relation types
    for uri, name, desc in [
        (RELATION_TYPE_NEAR, "NearRelation", "Relation between two geographically nearby entities"),
        (RELATION_TYPE_MENTIONS, "MentionsRelation", "Relation indicating an article mentions an entity"),
    ]:
        t = KGRelationType()
        t.URI = uri
        t.name = name
        t.kGraphDescription = desc
        types.append(t)

    return types


# ===========================================================================
# Main
# ===========================================================================
async def main():
    print("\n" + "=" * 70)
    print("  Step 2: Create KG Types, Indexes, Mappings & Geo Config")
    print("=" * 70)

    client = VitalGraphClient()
    await client.open()
    if not client.is_connected():
        logger.error("Failed to connect to VitalGraph server")
        return False
    logger.info("Connected to VitalGraph server\n")

    try:
        # ---------------------------------------------------------------
        # 1. Insert KG Types (idempotent — skip if already exist)
        # ---------------------------------------------------------------
        print("  --- KG Types ---")
        kg_types = build_kg_types()
        try:
            resp = await client.kgtypes.create_kgtypes(
                space_id=TEST_SPACE_ID,
                objects=kg_types,
            )
            if resp.is_success:
                logger.info(f"  Inserted {len(kg_types)} KG types")
            else:
                err = resp.error_message or ""
                if "already exists" in err.lower():
                    logger.info(f"  KG types already exist, skipping")
                else:
                    logger.error(f"  Failed to insert KG types: {err}")
                    return False
        except Exception as e:
            if "already exists" in str(e).lower():
                logger.info(f"  KG types already exist, skipping")
            else:
                logger.error(f"  Failed to insert KG types: {e}")
                return False

        # ---------------------------------------------------------------
        # 2. Vector index + vector mapping + properties
        # ---------------------------------------------------------------
        print("\n  --- Vector Index ---")
        vi = await client.vector_indexes.create_index(
            space_id=TEST_SPACE_ID,
            index_name=VECTOR_INDEX_NAME,
            dimensions=384,
            distance_metric="cosine",
            provider="vitalsigns",
            description="Main vector index for semantic search testing",
        )
        logger.info(f"  Vector index '{vi.index_name}' created (dim={vi.dimensions})")

        # Vector mapping for kgentity
        vm = await client.vector_mappings.create_mapping(
            space_id=TEST_SPACE_ID,
            index_name=VECTOR_INDEX_NAME,
            mapping_type="kgentity",
            enabled=True,
            source_type="properties",
        )
        logger.info(f"  Vector mapping id={vm.mapping_id} created (kgentity)")

        # Add properties to vector mapping
        for uri in [PROP_NAME, PROP_DESCRIPTION, PROP_TEXT_SLOT]:
            await client.vector_mappings.add_property(
                space_id=TEST_SPACE_ID,
                mapping_id=vm.mapping_id,
                property_uri=uri,
            )
        logger.info(f"  Added 3 properties to vector mapping")

        # ---------------------------------------------------------------
        # 3. FTS index + search mapping + properties
        # ---------------------------------------------------------------
        print("\n  --- FTS Index ---")
        fi = await client.fts_indexes.create_index(
            space_id=TEST_SPACE_ID,
            index_name=FTS_INDEX_NAME,
            languages=["english"],
        )
        logger.info(f"  FTS index '{fi.index_name}' created")

        # Search mapping for kgentity
        sm = await client.search_mappings.create_mapping(
            space_id=TEST_SPACE_ID,
            index_name=FTS_INDEX_NAME,
            mapping_type="kgentity",
            enabled=True,
            source_type="properties",
        )
        logger.info(f"  Search mapping id={sm.mapping_id} created (kgentity)")

        # Add properties to search mapping
        for uri in [PROP_NAME, PROP_DESCRIPTION, PROP_TEXT_SLOT]:
            await client.search_mappings.add_property(
                space_id=TEST_SPACE_ID,
                mapping_id=sm.mapping_id,
                property_uri=uri,
            )
        logger.info(f"  Added 3 properties to search mapping")

        # ---------------------------------------------------------------
        # 3b. Hybrid search mapping + index associations
        # ---------------------------------------------------------------
        print("\n  --- Hybrid Search Mapping (index associations) ---")
        # Create a search mapping with a distinct name for hybrid search.
        # hybridSearch("entity_hybrid") resolves via search_mapping_index junction.
        hsm = await client.search_mappings.create_mapping(
            space_id=TEST_SPACE_ID,
            index_name=HYBRID_INDEX_NAME,
            mapping_type="kgentity",
            enabled=True,
            source_type="properties",
        )
        logger.info(f"  Hybrid search mapping id={hsm.mapping_id} created (index_name={HYBRID_INDEX_NAME})")

        # Add properties to hybrid mapping (same as vector/FTS)
        for uri in [PROP_NAME, PROP_DESCRIPTION, PROP_TEXT_SLOT]:
            await client.search_mappings.add_property(
                space_id=TEST_SPACE_ID,
                mapping_id=hsm.mapping_id,
                property_uri=uri,
            )
        logger.info(f"  Added 3 properties to hybrid search mapping")

        # Associate both vector and FTS indexes with this mapping
        await client.search_mappings.add_index(
            space_id=TEST_SPACE_ID,
            mapping_id=hsm.mapping_id,
            index_type="vector",
            index_name=VECTOR_INDEX_NAME,
        )
        await client.search_mappings.add_index(
            space_id=TEST_SPACE_ID,
            mapping_id=hsm.mapping_id,
            index_type="fts",
            index_name=FTS_INDEX_NAME,
        )
        logger.info(f"  Associated vector '{VECTOR_INDEX_NAME}' and fts '{FTS_INDEX_NAME}' with hybrid mapping id={hsm.mapping_id}")

        # ---------------------------------------------------------------
        # 4. Fuzzy index + fuzzy mapping + properties
        # ---------------------------------------------------------------
        print("\n  --- Fuzzy Index ---")
        fm = await client.fuzzy_mappings.create_mapping(
            space_id=TEST_SPACE_ID,
            index_name=FUZZY_INDEX_NAME,
            mapping_type="kgentity",
            enabled=True,
        )
        logger.info(f"  Fuzzy mapping id={fm.mapping_id} created (kgentity)")

        # Add only name property to fuzzy mapping (fuzzy match is for names)
        await client.fuzzy_mappings.add_property(
            space_id=TEST_SPACE_ID,
            mapping_id=fm.mapping_id,
            property_uri=PROP_NAME,
        )
        logger.info(f"  Added hasName property to fuzzy mapping")

        # Populate fuzzy bands
        await client.fuzzy_mappings.populate(
            space_id=TEST_SPACE_ID, mapping_id=fm.mapping_id)
        logger.info(f"  Fuzzy mapping populated")

        # ---------------------------------------------------------------
        # 5. Geo config (datatype-driven: detects geoLocation-typed literals)
        # ---------------------------------------------------------------
        print("\n  --- Geo Config ---")
        geo = await client.geo_config.update_config(
            space_id=TEST_SPACE_ID,
            enabled=True,
            auto_sync=True,
        )
        logger.info(f"  Geo config enabled (auto_sync={geo.auto_sync})")
        logger.info(f"  Geo is datatype-driven: detects {GEO_DATATYPE_GEOLOCATION} and {GEO_DATATYPE_WKT}")

        print("\n  Step 2 complete.")
        return True

    finally:
        await client.close()
        logger.info("  Client closed")


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
