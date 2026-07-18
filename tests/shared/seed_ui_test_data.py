"""Seed deterministic test data for UI and API tests.

Run via:
    python -m tests.shared.seed_ui_test_data
    python -m tests.shared.seed_ui_test_data --server-url http://localhost:8002

Produces a known set of:
  - Spaces (global)
  - Graphs (per-space)
  - KG Entities + Relations (per-graph)
  - Vector indexes + mappings (per-space)

All URIs, names, and counts are constants importable by both
pytest fixtures and Playwright global-setup.

Environment variables for client config:
  VITALGRAPH_CLIENT_ENVIRONMENT  — profile name (default: test)
  TEST_CLIENT_SERVER_URL         — server URL  (default: http://localhost:8002)
  TEST_CLIENT_AUTH_USERNAME      — login user  (default: admin)
  TEST_CLIENT_AUTH_PASSWORD      — login pass  (default: admin)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — importable by test files
# ---------------------------------------------------------------------------

SPACE_ID = "e2e_test_space"
SPACE_NAME = "E2E Test Space"
SPACE_DESCRIPTION = "Seeded space for Playwright and pytest E2E tests"

GRAPH_ID = "urn:e2e:graph:main"

ADMIN_USER = "admin"
ADMIN_PASS = "admin"

ENTITY_DEFS = {
    "alice": {
        "uri": "urn:e2e:entity:alice",
        "name": "Alice Anderson",
        "description": "Software engineer who likes sushi",
    },
    "bob": {
        "uri": "urn:e2e:entity:bob",
        "name": "Bob Baker",
        "description": "Chef who likes pizza",
    },
    "carol": {
        "uri": "urn:e2e:entity:carol",
        "name": "Carol Chen",
        "description": "Data scientist who likes ramen",
    },
}

ENTITY_URIS = {k: v["uri"] for k, v in ENTITY_DEFS.items()}

EXPECTED_COUNTS = {
    "spaces": 1,
    "graphs": 1,
    "entities": len(ENTITY_DEFS),
}

# KG Document
DOCUMENT_URI = "urn:e2e:document:readme"
DOCUMENT_TITLE = "E2E Readme"

# Entity Registry
REGISTRY_TYPE_KEY = "person"
REGISTRY_PRIMARY_NAME = "E2E Registry Person"

# Agent Registry
AGENT_TYPE_KEY = "e2e_bot"
AGENT_TYPE_LABEL = "E2E Bot"
AGENT_NAME = "E2E Test Agent"
AGENT_URI = "urn:e2e:agent:test_bot"

# KG Frames
FRAME_DEFS = {
    "alice_profile": {
        "uri": "urn:e2e:frame:alice_profile",
        "name": "Alice Profile Frame",
    },
    "bob_profile": {
        "uri": "urn:e2e:frame:bob_profile",
        "name": "Bob Profile Frame",
    },
}

# FTS / Vector indexes & mappings
FTS_INDEX_NAME = "e2e_fts_idx"
VECTOR_INDEX_NAME = "e2e_vec_idx"
VECTOR_DIMENSIONS = 384
SEARCH_MAPPING_TYPE = "kgentity"
FUZZY_MAPPING_TYPE = "kgentity"


# ---------------------------------------------------------------------------
# Seed implementation
# ---------------------------------------------------------------------------

async def seed(server_url: str = "http://localhost:8002") -> None:
    """Seed all test data via the REST API.

    Idempotent — skips creation if data already exists.
    """
    # Configure client env vars for the test server
    os.environ.setdefault("VITALGRAPH_CLIENT_ENVIRONMENT", "test")
    os.environ["TEST_CLIENT_SERVER_URL"] = server_url
    os.environ.setdefault("TEST_CLIENT_AUTH_USERNAME", ADMIN_USER)
    os.environ.setdefault("TEST_CLIENT_AUTH_PASSWORD", ADMIN_PASS)

    from vitalgraph.client.vitalgraph_client import VitalGraphClient

    client = VitalGraphClient()
    await client.open()
    logger.info("Connected to %s", server_url)

    try:
        await _seed_space(client)
        await _seed_graph(client)
        await _seed_entities(client)
        await _seed_frames(client)
        await _seed_kgdocument(client)
        await _seed_entity_registry(client)
        await _seed_agent_registry(client)
        await _seed_fts_index(client)
        await _seed_vector_index(client)
        await _seed_search_mapping(client)
        await _seed_fuzzy_mapping(client)
        logger.info("✅ Seed complete")
    finally:
        await client.close()


async def _seed_space(client) -> None:
    """Create the E2E test space (skip if exists)."""
    from vitalgraph.model.spaces_model import Space

    resp = await client.spaces.list_spaces()
    if resp.is_success:
        existing = [s.space for s in resp.spaces]
        if SPACE_ID in existing:
            logger.info("Space '%s' already exists, skipping", SPACE_ID)
            return

    space = Space(
        space=SPACE_ID,
        space_name=SPACE_NAME,
        space_description=SPACE_DESCRIPTION,
    )
    cr = await client.spaces.create_space(space)
    if not cr.is_success:
        raise RuntimeError(f"Failed to create space: {cr.error_message}")
    logger.info("Created space '%s'", SPACE_ID)


async def _seed_graph(client) -> None:
    """Create the E2E test graph (skip if exists)."""
    resp = await client.graphs.list_graphs(SPACE_ID)
    if resp.is_success:
        existing = [g.graph_uri for g in resp.graphs]
        if GRAPH_ID in existing:
            logger.info("Graph '%s' already exists, skipping", GRAPH_ID)
            return

    cr = await client.graphs.create_graph(SPACE_ID, GRAPH_ID)
    if hasattr(cr, "is_success") and not cr.is_success:
        raise RuntimeError(f"Failed to create graph: {getattr(cr, 'error_message', cr)}")
    logger.info("Created graph '%s'", GRAPH_ID)


async def _seed_entities(client) -> None:
    """Create the E2E test entities (skip if they already exist)."""
    from ai_haley_kg_domain.model.KGEntity import KGEntity

    for key, defn in ENTITY_DEFS.items():
        entity = KGEntity()
        entity.URI = defn["uri"]
        entity.name = defn["name"]

        cr = await client.kgentities.create_kgentities(
            space_id=SPACE_ID, graph_id=GRAPH_ID, objects=[entity]
        )
        if hasattr(cr, "is_success") and not cr.is_success:
            # May already exist — log and continue
            logger.warning("Entity '%s' creation response: %s", key, getattr(cr, "error_message", cr))
        else:
            logger.info("Created entity '%s' (%s)", key, defn["uri"])


async def _seed_frames(client) -> None:
    """Create the E2E test frames (skip if they already exist)."""
    from ai_haley_kg_domain.model.KGFrame import KGFrame

    for key, defn in FRAME_DEFS.items():
        frame = KGFrame()
        frame.URI = defn["uri"]
        frame.name = defn["name"]

        try:
            cr = await client.kgframes.create_kgframes(
                space_id=SPACE_ID, graph_id=GRAPH_ID, objects=[frame]
            )
            if hasattr(cr, "is_success") and not cr.is_success:
                logger.warning("Frame '%s' creation response: %s", key, getattr(cr, "error_message", cr))
            else:
                logger.info("Created frame '%s' (%s)", key, defn["uri"])
        except Exception as e:
            logger.warning("Frame '%s' seed skipped: %s", key, e)


async def _seed_kgdocument(client) -> None:
    """Create a seeded KGDocument (skip if exists)."""
    from ai_haley_kg_domain.model.KGDocument import KGDocument

    try:
        existing = await client.kgdocuments.get_kgdocument(
            space_id=SPACE_ID, graph_id=GRAPH_ID, uri=DOCUMENT_URI
        )
        if hasattr(existing, "is_success") and existing.is_success:
            logger.info("KGDocument '%s' already exists, skipping", DOCUMENT_URI)
            return
    except Exception:
        pass  # Not found or error — proceed to create

    doc = KGDocument()
    doc.URI = DOCUMENT_URI
    doc.name = DOCUMENT_TITLE

    try:
        cr = await client.kgdocuments.create_kgdocuments(
            space_id=SPACE_ID, graph_id=GRAPH_ID, objects=[doc]
        )
        if hasattr(cr, "is_success") and not cr.is_success:
            logger.warning("KGDocument creation response: %s", getattr(cr, "error_message", cr))
        else:
            logger.info("Created KGDocument '%s'", DOCUMENT_URI)
    except Exception as e:
        logger.warning("KGDocument seed skipped: %s", e)


async def _seed_entity_registry(client) -> None:
    """Create a seeded entity-registry entry."""
    from vitalgraph.model.entity_registry_model import EntityCreateRequest

    try:
        req = EntityCreateRequest(
            type_key=REGISTRY_TYPE_KEY,
            primary_name=REGISTRY_PRIMARY_NAME,
            description="Seeded by E2E test runner",
        )
        await client.entity_registry.create_entity(req)
        logger.info("Created entity-registry entry '%s'", REGISTRY_PRIMARY_NAME)
    except Exception as e:
        logger.warning("Entity-registry seed skipped: %s", e)


async def _seed_agent_registry(client) -> None:
    """Create a seeded agent-registry entry."""
    from vitalgraph.agent_registry.agent_models import AgentTypeCreate, AgentCreate

    try:
        # Ensure the agent type exists
        try:
            await client.agent_registry.create_agent_type(
                AgentTypeCreate(type_key=AGENT_TYPE_KEY, type_label=AGENT_TYPE_LABEL)
            )
            logger.info("Created agent type '%s'", AGENT_TYPE_KEY)
        except Exception:
            logger.info("Agent type '%s' may already exist", AGENT_TYPE_KEY)

        req = AgentCreate(
            agent_type_key=AGENT_TYPE_KEY,
            agent_name=AGENT_NAME,
            agent_uri=AGENT_URI,
            description="Seeded by E2E test runner",
        )
        await client.agent_registry.create_agent(req)
        logger.info("Created agent '%s'", AGENT_NAME)
    except Exception as e:
        logger.warning("Agent-registry seed skipped: %s", e)


async def _seed_fts_index(client) -> None:
    """Create a seeded FTS index."""
    try:
        await client.fts_indexes.create_index(
            space_id=SPACE_ID, index_name=FTS_INDEX_NAME
        )
        logger.info("Created FTS index '%s'", FTS_INDEX_NAME)
    except Exception as e:
        logger.warning("FTS index seed skipped: %s", e)


async def _seed_vector_index(client) -> None:
    """Create a seeded vector index."""
    try:
        await client.vector_indexes.create_index(
            space_id=SPACE_ID,
            index_name=VECTOR_INDEX_NAME,
            dimensions=VECTOR_DIMENSIONS,
            description="Seeded by E2E test runner",
        )
        logger.info("Created vector index '%s'", VECTOR_INDEX_NAME)
    except Exception as e:
        logger.warning("Vector index seed skipped: %s", e)


async def _seed_search_mapping(client) -> None:
    """Create a seeded search mapping (requires FTS index)."""
    try:
        await client.search_mappings.create_mapping(
            space_id=SPACE_ID,
            index_name=FTS_INDEX_NAME,
            mapping_type=SEARCH_MAPPING_TYPE,
        )
        logger.info("Created search mapping for '%s'", FTS_INDEX_NAME)
    except Exception as e:
        logger.warning("Search mapping seed skipped: %s", e)


async def _seed_fuzzy_mapping(client) -> None:
    """Create a seeded fuzzy mapping (requires FTS index)."""
    try:
        await client.fuzzy_mappings.create_mapping(
            space_id=SPACE_ID,
            index_name=FTS_INDEX_NAME,
            mapping_type=FUZZY_MAPPING_TYPE,
        )
        logger.info("Created fuzzy mapping for '%s'", FTS_INDEX_NAME)
    except Exception as e:
        logger.warning("Fuzzy mapping seed skipped: %s", e)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Seed E2E test data")
    parser.add_argument(
        "--server-url",
        default=os.getenv("TEST_CLIENT_SERVER_URL", "http://localhost:8002"),
        help="VitalGraph server URL (default: http://localhost:8002)",
    )
    parser.add_argument(
        "--profile",
        choices=["minimal", "full"],
        default="minimal",
        help="Seed profile: 'minimal' for basic CRUD data, 'full' includes WordNet/FrameNet",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.profile == "full":
        logger.info("Full profile requested — WordNet/FrameNet import not yet implemented")
        # TODO: Import WordNet/FrameNet N-Triples via vitalgraphimport CLI

    asyncio.run(seed(server_url=args.server_url))


if __name__ == "__main__":
    main()
