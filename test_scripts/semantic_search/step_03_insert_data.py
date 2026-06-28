#!/usr/bin/env python3
"""
Step 3: Insert Test Data

Inserts KG entities with frames, slots, and edges that exercise all search modes:
  - Vector search (text descriptions for embedding)
  - Full-text search (keyword-rich names and descriptions)
  - Geo search (KGGeoLocationSlot with WKT POINT values)
  - Hybrid/fuzzy (similar names, typo-prone text)

Data includes:
  - Restaurants (with geo locations, descriptions)
  - Landmarks (with geo locations, descriptions)
  - Articles (text-rich, no geo)

Each entity has:
  - KGEntity (name, kGEntityType, kGraphDescription)
  - LocationFrame with KGGeoLocationSlot (for geo entities)
  - DescriptionFrame with KGTextSlot (summary text)
  - MetadataFrame with KGTextSlot (category)
"""

import asyncio
import logging
import sys
import uuid
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
from vital_ai_vitalsigns.model.GraphObject import GraphObject

from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGGeoLocationSlot import KGGeoLocationSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.KGDocument import KGDocument

from vitalgraph.model.entity_registry_model import (
    EntityCreateRequest,
    EntityTypeCreateRequest,
    LocationCreateRequest,
)
from vitalgraph.agent_registry.agent_models import (
    AgentCreate,
    AgentTypeCreate,
)

from test_scripts.semantic_search.config import (
    TEST_SPACE_ID, TEST_GRAPH_ID,
    ENTITY_TYPE_RESTAURANT, ENTITY_TYPE_LANDMARK, ENTITY_TYPE_ARTICLE,
    FRAME_TYPE_LOCATION, FRAME_TYPE_DESCRIPTION, FRAME_TYPE_METADATA,
    SLOT_TYPE_CITY, SLOT_TYPE_COUNTRY, SLOT_TYPE_SUMMARY, SLOT_TYPE_CATEGORY,
    DOCUMENT_TYPE_ARTICLE, TEST_DOCUMENTS,
    ER_ENTITY_TYPE_KEY, ER_AGENT_TYPE_KEY, ER_AGENT_URI, ER_ENTITIES,
)


# ===========================================================================
# Test data definitions
# ===========================================================================

BASE_URI = "http://vital.ai/test/semantic"


def _uri(kind: str, slug: str) -> str:
    return f"{BASE_URI}/{kind}/{slug}"


# Restaurants — geo + text
RESTAURANTS = [
    {
        "slug": "joes_pizza",
        "name": "Joe's Pizza",
        "description": "Classic New York style pizza by the slice in Greenwich Village since 1975",
        "category": "italian",
        "city": "New York",
        "country": "USA",
        "lat": 40.7308, "lon": -74.0020,
    },
    {
        "slug": "le_bernardin",
        "name": "Le Bernardin",
        "description": "Upscale French seafood restaurant with three Michelin stars in Midtown Manhattan",
        "category": "french",
        "city": "New York",
        "country": "USA",
        "lat": 40.7615, "lon": -73.9818,
    },
    {
        "slug": "dishoom_kings_cross",
        "name": "Dishoom King's Cross",
        "description": "Bombay-inspired cafe serving breakfast naan rolls and black daal in London",
        "category": "indian",
        "city": "London",
        "country": "UK",
        "lat": 51.5352, "lon": -0.1260,
    },
    {
        "slug": "sushi_saito",
        "name": "Sushi Saito",
        "description": "Legendary omakase sushi counter with three Michelin stars in Minato Tokyo",
        "category": "japanese",
        "city": "Tokyo",
        "country": "Japan",
        "lat": 35.6627, "lon": 139.7340,
    },
    {
        "slug": "noma_copenhagen",
        "name": "Noma",
        "description": "World-renowned Nordic cuisine restaurant known for foraging and fermentation in Copenhagen",
        "category": "nordic",
        "city": "Copenhagen",
        "country": "Denmark",
        "lat": 55.6832, "lon": 12.6104,
    },
    {
        "slug": "central_lima",
        "name": "Central",
        "description": "Peruvian fine dining exploring diverse ecosystems and altitudes of Peru",
        "category": "peruvian",
        "city": "Lima",
        "country": "Peru",
        "lat": -12.1525, "lon": -77.0224,
    },
    {
        "slug": "peter_luger",
        "name": "Peter Luger Steak House",
        "description": "Legendary Brooklyn steakhouse serving dry-aged porterhouse since 1887",
        "category": "steakhouse",
        "city": "New York",
        "country": "USA",
        "lat": 40.7099, "lon": -73.9623,
    },
    {
        "slug": "the_ledbury",
        "name": "The Ledbury",
        "description": "Two Michelin star modern European restaurant in Notting Hill London",
        "category": "european",
        "city": "London",
        "country": "UK",
        "lat": 51.5152, "lon": -0.2005,
    },
]

# Landmarks — geo + text
LANDMARKS = [
    {
        "slug": "statue_of_liberty",
        "name": "Statue of Liberty",
        "description": "Colossal neoclassical sculpture on Liberty Island gifted by France in 1886",
        "category": "monument",
        "city": "New York",
        "country": "USA",
        "lat": 40.6892, "lon": -74.0445,
    },
    {
        "slug": "tower_bridge",
        "name": "Tower Bridge",
        "description": "Victorian combined bascule and suspension bridge over the River Thames built in 1894",
        "category": "bridge",
        "city": "London",
        "country": "UK",
        "lat": 51.5055, "lon": -0.0754,
    },
    {
        "slug": "eiffel_tower",
        "name": "Eiffel Tower",
        "description": "Wrought iron lattice tower on the Champ de Mars built for the 1889 World Fair",
        "category": "tower",
        "city": "Paris",
        "country": "France",
        "lat": 48.8584, "lon": 2.2945,
    },
    {
        "slug": "senso_ji",
        "name": "Senso-ji Temple",
        "description": "Ancient Buddhist temple in Asakusa Tokyo originally built in 645 AD",
        "category": "temple",
        "city": "Tokyo",
        "country": "Japan",
        "lat": 35.7148, "lon": 139.7967,
    },
    {
        "slug": "colosseum",
        "name": "Colosseum",
        "description": "Ancient Roman amphitheatre in the centre of Rome built of travertine limestone",
        "category": "ruins",
        "city": "Rome",
        "country": "Italy",
        "lat": 41.8902, "lon": 12.4922,
    },
    {
        "slug": "sydney_opera_house",
        "name": "Sydney Opera House",
        "description": "Multi-venue performing arts centre with distinctive sail-shaped roof shells",
        "category": "theatre",
        "city": "Sydney",
        "country": "Australia",
        "lat": -33.8568, "lon": 151.2153,
    },
    {
        "slug": "central_park",
        "name": "Central Park",
        "description": "Urban park in Manhattan spanning 843 acres with lakes meadows and woodland",
        "category": "park",
        "city": "New York",
        "country": "USA",
        "lat": 40.7829, "lon": -73.9654,
    },
    {
        "slug": "big_ben",
        "name": "Big Ben",
        "description": "Iconic clock tower at the north end of the Palace of Westminster in London",
        "category": "tower",
        "city": "London",
        "country": "UK",
        "lat": 51.5007, "lon": -0.1246,
    },
]

# Articles — text only, no geo
ARTICLES = [
    {
        "slug": "future_of_ai",
        "name": "The Future of Artificial Intelligence in Healthcare",
        "description": "An exploration of how machine learning and neural networks are transforming diagnostics and drug discovery in modern medicine",
        "category": "technology",
    },
    {
        "slug": "climate_change_2025",
        "name": "Climate Change Impact Report 2025",
        "description": "Comprehensive analysis of rising sea levels glacier retreat and extreme weather patterns across global regions",
        "category": "environment",
    },
    {
        "slug": "quantum_computing",
        "name": "Quantum Computing Breakthrough at MIT",
        "description": "Researchers achieve stable qubit coherence at room temperature opening doors to practical quantum processors",
        "category": "science",
    },
    {
        "slug": "remote_work_trends",
        "name": "Remote Work Trends and Productivity Analysis",
        "description": "Study of distributed workforce patterns showing increased output and employee satisfaction in hybrid models",
        "category": "business",
    },
    {
        "slug": "biodiversity_amazon",
        "name": "Biodiversity of the Amazon Rainforest",
        "description": "Documentation of newly discovered species in the Amazon basin including rare amphibians and medicinal plants",
        "category": "environment",
    },
    {
        "slug": "space_exploration",
        "name": "Mars Colony Planning and Challenges",
        "description": "Engineering challenges of establishing a permanent human settlement on Mars including radiation shielding and food production",
        "category": "science",
    },
]


# ===========================================================================
# Entity graph builder
# ===========================================================================

def build_entity_graph(data: dict, entity_type_uri: str, has_geo: bool) -> list:
    """
    Build a complete entity graph: KGEntity + frames + slots + edges.

    Returns a flat list of GraphObjects ready for insertion.
    """
    objects = []
    slug = data["slug"]

    # --- KGEntity ---
    entity = KGEntity()
    entity.URI = _uri("entity", slug)
    entity.name = data["name"]
    entity.kGEntityType = entity_type_uri
    entity.kGraphDescription = data["description"]
    objects.append(entity)

    # --- DescriptionFrame + SummarySlot ---
    desc_frame = KGFrame()
    desc_frame.URI = _uri("frame", f"{slug}_description")
    desc_frame.name = f"{data['name']} Description"
    desc_frame.kGFrameType = FRAME_TYPE_DESCRIPTION
    objects.append(desc_frame)

    summary_slot = KGTextSlot()
    summary_slot.URI = _uri("slot", f"{slug}_summary")
    summary_slot.kGSlotType = SLOT_TYPE_SUMMARY
    summary_slot.textSlotValue = data["description"]
    objects.append(summary_slot)

    # Edge: entity -> description frame
    e2df = Edge_hasEntityKGFrame()
    e2df.URI = _uri("edge", f"{slug}_e2df_{uuid.uuid4().hex[:8]}")
    e2df.edgeSource = entity.URI
    e2df.edgeDestination = desc_frame.URI
    objects.append(e2df)

    # Edge: description frame -> summary slot
    df2ss = Edge_hasKGSlot()
    df2ss.URI = _uri("edge", f"{slug}_df2ss_{uuid.uuid4().hex[:8]}")
    df2ss.edgeSource = desc_frame.URI
    df2ss.edgeDestination = summary_slot.URI
    objects.append(df2ss)

    # --- MetadataFrame + CategorySlot ---
    meta_frame = KGFrame()
    meta_frame.URI = _uri("frame", f"{slug}_metadata")
    meta_frame.name = f"{data['name']} Metadata"
    meta_frame.kGFrameType = FRAME_TYPE_METADATA
    objects.append(meta_frame)

    cat_slot = KGTextSlot()
    cat_slot.URI = _uri("slot", f"{slug}_category")
    cat_slot.kGSlotType = SLOT_TYPE_CATEGORY
    cat_slot.textSlotValue = data["category"]
    objects.append(cat_slot)

    # Edge: entity -> metadata frame
    e2mf = Edge_hasEntityKGFrame()
    e2mf.URI = _uri("edge", f"{slug}_e2mf_{uuid.uuid4().hex[:8]}")
    e2mf.edgeSource = entity.URI
    e2mf.edgeDestination = meta_frame.URI
    objects.append(e2mf)

    # Edge: metadata frame -> category slot
    mf2cs = Edge_hasKGSlot()
    mf2cs.URI = _uri("edge", f"{slug}_mf2cs_{uuid.uuid4().hex[:8]}")
    mf2cs.edgeSource = meta_frame.URI
    mf2cs.edgeDestination = cat_slot.URI
    objects.append(mf2cs)

    # --- LocationFrame + GeoLocationSlot + CitySlot + CountrySlot (if geo) ---
    if has_geo:
        loc_frame = KGFrame()
        loc_frame.URI = _uri("frame", f"{slug}_location")
        loc_frame.name = f"{data['name']} Location"
        loc_frame.kGFrameType = FRAME_TYPE_LOCATION
        objects.append(loc_frame)

        # Geo slot with WKT POINT(lon lat)
        geo_slot = KGGeoLocationSlot()
        geo_slot.URI = _uri("slot", f"{slug}_geo")
        geo_slot.kGSlotType = FRAME_TYPE_LOCATION  # slot type can reference the frame concept
        geo_slot.geoLocationSlotValue = f"POINT({data['lon']} {data['lat']})"
        objects.append(geo_slot)

        # City text slot
        city_slot = KGTextSlot()
        city_slot.URI = _uri("slot", f"{slug}_city")
        city_slot.kGSlotType = SLOT_TYPE_CITY
        city_slot.textSlotValue = data["city"]
        objects.append(city_slot)

        # Country text slot
        country_slot = KGTextSlot()
        country_slot.URI = _uri("slot", f"{slug}_country")
        country_slot.kGSlotType = SLOT_TYPE_COUNTRY
        country_slot.textSlotValue = data["country"]
        objects.append(country_slot)

        # Edge: entity -> location frame
        e2lf = Edge_hasEntityKGFrame()
        e2lf.URI = _uri("edge", f"{slug}_e2lf_{uuid.uuid4().hex[:8]}")
        e2lf.edgeSource = entity.URI
        e2lf.edgeDestination = loc_frame.URI
        objects.append(e2lf)

        # Edges: location frame -> slots
        for slot in [geo_slot, city_slot, country_slot]:
            edge = Edge_hasKGSlot()
            edge.URI = _uri("edge", f"{slug}_lf2s_{uuid.uuid4().hex[:8]}")
            edge.edgeSource = loc_frame.URI
            edge.edgeDestination = slot.URI
            objects.append(edge)

    return objects


# ===========================================================================
# Main
# ===========================================================================

async def main():
    print("\n" + "=" * 70)
    print("  Step 3: Insert Test Data")
    print("=" * 70)

    client = VitalGraphClient()
    await client.open()
    if not client.is_connected():
        logger.error("Failed to connect to VitalGraph server")
        return False
    logger.info("Connected to VitalGraph server\n")

    try:
        total_objects = 0

        # --- Restaurants ---
        print("  --- Restaurants ---")
        for data in RESTAURANTS:
            objects = build_entity_graph(data, ENTITY_TYPE_RESTAURANT, has_geo=True)
            resp = await client.kgentities.create_kgentities(
                space_id=TEST_SPACE_ID,
                graph_id=TEST_GRAPH_ID,
                objects=objects,
            )
            if resp.is_success:
                total_objects += len(objects)
                logger.info(f"    {data['name']} ({len(objects)} objects)")
            else:
                logger.error(f"    FAILED {data['name']}: {resp.error_message}")

        # --- Landmarks ---
        print("\n  --- Landmarks ---")
        for data in LANDMARKS:
            objects = build_entity_graph(data, ENTITY_TYPE_LANDMARK, has_geo=True)
            resp = await client.kgentities.create_kgentities(
                space_id=TEST_SPACE_ID,
                graph_id=TEST_GRAPH_ID,
                objects=objects,
            )
            if resp.is_success:
                total_objects += len(objects)
                logger.info(f"    {data['name']} ({len(objects)} objects)")
            else:
                logger.error(f"    FAILED {data['name']}: {resp.error_message}")

        # --- Articles ---
        print("\n  --- Articles ---")
        for data in ARTICLES:
            objects = build_entity_graph(data, ENTITY_TYPE_ARTICLE, has_geo=False)
            resp = await client.kgentities.create_kgentities(
                space_id=TEST_SPACE_ID,
                graph_id=TEST_GRAPH_ID,
                objects=objects,
            )
            if resp.is_success:
                total_objects += len(objects)
                logger.info(f"    {data['name']} ({len(objects)} objects)")
            else:
                logger.error(f"    FAILED {data['name']}: {resp.error_message}")

        # =================================================================
        # Entity Registry data (global, not space-scoped)
        # =================================================================
        print("\n  --- Entity Registry ---")
        reg = client.entity_registry
        er_entity_ids = []

        # Create entity type (idempotent — ignore if exists)
        try:
            await reg.create_entity_type(EntityTypeCreateRequest(
                type_key=ER_ENTITY_TYPE_KEY,
                type_label="Semantic Test Business",
                type_description="Entity type for semantic search test data",
            ))
            logger.info(f"    Created entity type: {ER_ENTITY_TYPE_KEY}")
        except Exception as e:
            if '409' in str(e) or 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
                logger.info(f"    Entity type '{ER_ENTITY_TYPE_KEY}' already exists, skipping")
            else:
                logger.error(f"    Failed to create entity type: {e}")

        # Create entities with locations
        for ent_def in ER_ENTITIES:
            try:
                resp = await reg.create_entity(EntityCreateRequest(
                    type_key=ent_def["type_key"],
                    primary_name=ent_def["name"],
                    description=ent_def["description"],
                    country=ent_def["country"],
                    locality=ent_def["locality"],
                    latitude=ent_def["lat"],
                    longitude=ent_def["lon"],
                    created_by="semantic_search_test",
                    locations=[
                        LocationCreateRequest(
                            location_type_key="headquarters",
                            location_name=ent_def["location_name"],
                            address_line_1=ent_def["address"],
                            locality=ent_def["locality"],
                            country=ent_def["country"],
                            latitude=ent_def["lat"],
                            longitude=ent_def["lon"],
                            is_primary=True,
                        ),
                    ],
                ))
                er_entity_ids.append(resp.entity_id)
                logger.info(f"    {ent_def['name']} (entity_id={resp.entity_id})")
            except Exception as e:
                logger.error(f"    FAILED {ent_def['name']}: {e}")

        logger.info(f"    Created {len(er_entity_ids)} entity registry entities")

        # Populate vector/FTS/geo tables for entity registry
        try:
            pop_resp = await reg.populate_vectors()
            logger.info(f"    Populated ER vectors: {pop_resp}")
        except Exception as e:
            logger.warning(f"    ER populate_vectors failed (may need manual rebuild): {e}")

        # =================================================================
        # Agent Registry data (global, not space-scoped)
        # =================================================================
        print("\n  --- Agent Registry ---")
        ar = client.agent_registry

        # Create agent type (idempotent)
        try:
            await ar.create_agent_type(AgentTypeCreate(
                type_key=ER_AGENT_TYPE_KEY,
                type_label="Semantic Test Bot",
                type_description="Agent type for semantic search test data",
            ))
            logger.info(f"    Created agent type: {ER_AGENT_TYPE_KEY}")
        except Exception as e:
            if '409' in str(e) or 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
                logger.info(f"    Agent type '{ER_AGENT_TYPE_KEY}' already exists, skipping")
            else:
                logger.error(f"    Failed to create agent type: {e}")

        # Create a test agent
        try:
            agent_resp = await ar.create_agent(AgentCreate(
                agent_type_key=ER_AGENT_TYPE_KEY,
                agent_name="Semantic Search Test Bot",
                agent_uri=ER_AGENT_URI,
                description="A test agent for verifying agent registry search",
                version="1.0.0",
                capabilities=["search", "summarize"],
            ))
            logger.info(f"    Created agent: {agent_resp.agent_name} (id={agent_resp.agent_id})")
        except Exception as e:
            if '409' in str(e) or 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
                logger.info(f"    Agent '{ER_AGENT_URI}' already exists, skipping")
            else:
                logger.error(f"    Failed to create agent: {e}")

        # ---------------------------------------------------------------
        # 4. KG Documents
        # ---------------------------------------------------------------
        print("\n  --- KG Documents ---")
        doc_objects: list = []
        for doc_def in TEST_DOCUMENTS:
            doc = KGDocument()
            doc.URI = doc_def["uri"]
            doc.name = doc_def["name"]
            doc.kGDocumentHeadline = doc_def["headline"]
            doc.kGDocumentContent = doc_def["content"]
            doc.kGraphDescription = doc_def["description"]
            doc.kGDocumentType = DOCUMENT_TYPE_ARTICLE
            doc_objects.append(doc)

        resp = await client.kgdocuments.create_kgdocuments(
            space_id=TEST_SPACE_ID, graph_id=TEST_GRAPH_ID, objects=doc_objects)
        if resp.is_success:
            logger.info(f"  Inserted {len(doc_objects)} KG documents")
        else:
            logger.error(f"  Failed to insert KG documents: {resp.error_message}")

        # Trigger segmentation for each document
        for doc_def in TEST_DOCUMENTS:
            try:
                seg_resp = await client.kgdocuments.segment_document(
                    space_id=TEST_SPACE_ID,
                    graph_id=TEST_GRAPH_ID,
                    document_uri=doc_def["uri"],
                    segment_method_uri="urn:segmethod:markdown_heading_split",
                    max_segment_tokens=256,
                )
                seg_count = seg_resp.get("segments_created", seg_resp.get("segment_count", "?"))
                logger.info(f"    Segmented '{doc_def['name']}': {seg_count} segments")
            except Exception as e:
                logger.warning(f"    Segmentation of '{doc_def['name']}' failed: {e}")

        # --- Summary ---
        entity_count = len(RESTAURANTS) + len(LANDMARKS) + len(ARTICLES)
        print(f"\n  Inserted {entity_count} KG entities ({total_objects} total objects)")
        print(f"  Inserted {len(doc_objects)} KG documents")
        print(f"  Inserted {len(er_entity_ids)} entity registry entities")
        print(f"  Inserted 1 agent registry agent")
        print("  Step 3 complete.")
        return True

    finally:
        await client.close()
        logger.info("  Client closed")


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
