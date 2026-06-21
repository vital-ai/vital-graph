#!/usr/bin/env python3
"""
SPARQL-SQL Backend Multi-Vector Query End-to-End Test

Tests the full multi-vector pipeline against a live VitalGraph server:
1. Creates a test space with two vector indexes
2. Creates entities (KGEntity objects via VitalSigns)
3. Inserts embedding vectors directly via the vector table
4. Runs multi-vector queries via the KGQuery endpoint
5. Verifies weighted score fusion and INTERSECT semantics
6. Cleans up

Requires:
    - Running VitalGraph server with pgvector extension
    - VITALGRAPH_CLIENT_ENVIRONMENT=local (or appropriate env)

Usage:
    python vitalgraph_client_test/test_sparql_sql_multi_vector.py
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Path & env setup
# ---------------------------------------------------------------------------
project_root = Path(__file__).parent.parent
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
from vitalgraph.model.spaces_model import Space
from vitalgraph.model.kgqueries_model import KGQueryCriteria
from vitalgraph.model.kgentities_model import (
    MultiVectorSearchCriteria, WeightedVectorInput, EntityQueryCriteria,
)

# ===========================================================================
# Configuration
# ===========================================================================
TEST_SPACE_ID = "sp_sql_multi_vector"
TEST_SPACE_NAME = "SPARQL-SQL Multi-Vector Test Space"
TEST_GRAPH_ID = "urn:sql_multi_vector"

DELETE_SPACE_AT_END = True

# Vector index configs
INDEX_A_NAME = "entity_type_default"
INDEX_A_DIMS = 8
INDEX_B_NAME = "entity_default"
INDEX_B_DIMS = 8

# Test entities with pre-computed 8-dim vectors
# Designed so that:
#   - Acme dominates index_a (cosine ~1.0 with query_a)
#   - Green dominates index_b (cosine ~1.0 with query_b)
#   - Tech is moderate in both
#   - Oil Drilling only in index_a (tests INTERSECT exclusion)
TEST_ENTITIES = [
    {
        "name": "Acme Solar Corp",
        "vec_a": [0.85, 0.35, 0.15, 0.0, -0.1, 0.25, 0.45, 0.15],
        "vec_b": [0.5, 0.1, 0.0, -0.2, 0.3, 0.6, 0.1, 0.4],
    },
    {
        "name": "Green Power LLC",
        "vec_a": [0.3, 0.6, 0.1, 0.4, -0.2, 0.0, 0.1, 0.5],
        "vec_b": [0.15, 0.75, 0.45, 0.25, 0.05, -0.15, 0.15, 0.05],
    },
    {
        "name": "TechStartup Inc",
        "vec_a": [0.5, 0.2, 0.4, 0.3, 0.1, 0.1, 0.2, 0.6],
        "vec_b": [0.3, 0.4, 0.1, 0.6, 0.2, 0.0, 0.3, 0.1],
    },
    {
        "name": "Oil Drilling Corp",
        # Only in index_a — tests INTERSECT (excluded from multi-vector results)
        "vec_a": [0.4, 0.2, 0.1, 0.6, 0.3, 0.0, 0.1, 0.2],
        "vec_b": None,
    },
]

# Query vectors
QUERY_VEC_A = [0.85, 0.35, 0.15, 0.0, -0.1, 0.25, 0.45, 0.15]
QUERY_VEC_B = [0.15, 0.75, 0.45, 0.25, 0.05, -0.15, 0.15, 0.05]


# ===========================================================================
# Test runner
# ===========================================================================
class MultiVectorTestRunner:
    """End-to-end test for multi-vector queries."""

    def __init__(self, client: VitalGraphClient):
        self.client = client
        self.passed = 0
        self.failed = 0
        self.entity_uris = {}  # name → URI

    def check(self, name: str, passed: bool, detail: str = ""):
        if passed:
            self.passed += 1
            logger.info(f"  \u2705 {name}{' -- ' + detail if detail else ''}")
        else:
            self.failed += 1
            logger.error(f"  \u274c {name}{' -- ' + detail if detail else ''}")

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    async def setup_vector_indexes(self):
        """Create two vector indexes for the test space."""
        logger.info("\n--- Creating vector indexes ---")
        try:
            await self.client.vector_indexes.create_index(
                space_id=TEST_SPACE_ID,
                index_name=INDEX_A_NAME,
                dimensions=INDEX_A_DIMS,
                distance_metric="cosine",
                provider="vitalsigns",
                description="Entity type vectors (test)",
            )
            logger.info(f"  Created index: {INDEX_A_NAME} ({INDEX_A_DIMS}d)")

            await self.client.vector_indexes.create_index(
                space_id=TEST_SPACE_ID,
                index_name=INDEX_B_NAME,
                dimensions=INDEX_B_DIMS,
                distance_metric="cosine",
                provider="vitalsigns",
                description="Entity description vectors (test)",
            )
            logger.info(f"  Created index: {INDEX_B_NAME} ({INDEX_B_DIMS}d)")
            return True
        except Exception as e:
            logger.error(f"  Failed to create indexes: {e}")
            return False

    async def setup_entities_and_vectors(self):
        """Create test entities and insert vectors."""
        logger.info("\n--- Creating entities and inserting vectors ---")

        try:
            import uuid
            from ai_haley_kg_domain.model.KGEntity import KGEntity

            base_uri = "http://vital.ai/test/multi_vector"

            objects = []
            for ent in TEST_ENTITIES:
                entity = KGEntity()
                entity_id = ent["name"].lower().replace(" ", "_")
                entity.URI = f"{base_uri}/{entity_id}/{uuid.uuid4()}"
                entity.name = ent["name"]
                self.entity_uris[ent["name"]] = str(entity.URI)
                objects.append(entity)

            # Create entities via the kgentities endpoint
            resp = await self.client.kgentities.create_kgentities(
                space_id=TEST_SPACE_ID,
                graph_id=TEST_GRAPH_ID,
                objects=objects,
            )

            if not resp.is_success:
                logger.error(f"  Entity creation failed: {resp}")
                return False

            for name, uri in self.entity_uris.items():
                logger.info(f"  Created: {name} -> {uri}")

            # Insert vectors via the upsert_vectors API
            for ent in TEST_ENTITIES:
                uri = self.entity_uris.get(ent["name"])
                if not uri:
                    continue

                if ent["vec_a"]:
                    await self.client.vector_indexes.upsert_vectors(
                        space_id=TEST_SPACE_ID,
                        index_name=INDEX_A_NAME,
                        vectors=[{
                            "subject_uri": uri,
                            "graph_uri": TEST_GRAPH_ID,
                            "embedding": ent["vec_a"],
                        }],
                    )

                if ent["vec_b"]:
                    await self.client.vector_indexes.upsert_vectors(
                        space_id=TEST_SPACE_ID,
                        index_name=INDEX_B_NAME,
                        vectors=[{
                            "subject_uri": uri,
                            "graph_uri": TEST_GRAPH_ID,
                            "embedding": ent["vec_b"],
                        }],
                    )

            logger.info(f"  Inserted vectors for {len(self.entity_uris)} entities")
            return True

        except Exception as e:
            logger.error(f"  Setup failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def _build_multi_vector_criteria(self, weight_a=0.5, weight_b=0.5,
                                     top_k=10, min_score=None):
        """Build a KGQueryCriteria with multi_vector_criteria."""
        return KGQueryCriteria(
            query_type="entity",
            multi_vector_criteria=MultiVectorSearchCriteria(
                vectors=[
                    WeightedVectorInput(
                        vector=str(QUERY_VEC_A),
                        index_name=INDEX_A_NAME,
                        weight=weight_a,
                    ),
                    WeightedVectorInput(
                        vector=str(QUERY_VEC_B),
                        index_name=INDEX_B_NAME,
                        weight=weight_b,
                    ),
                ],
                top_k=top_k,
                min_score=min_score,
            ),
        )

    async def test_multi_vector_nearby_basic(self):
        """Test multiVectorNearby with equal weights."""
        logger.info("\n--- Test: Multi-Vector Nearby (equal weights) ---")
        try:
            criteria = self._build_multi_vector_criteria(weight_a=0.5, weight_b=0.5)
            resp = await self.client.kgqueries.query_connections(
                space_id=TEST_SPACE_ID,
                graph_id=TEST_GRAPH_ID,
                criteria=criteria,
                page_size=10,
            )

            entity_uris_result = resp.entity_uris or []
            self.check("Returns results", len(entity_uris_result) > 0,
                       f"got {len(entity_uris_result)} entities")

            # Oil Drilling Corp should NOT appear (missing from index B → INTERSECT)
            oil_uri = self.entity_uris.get("Oil Drilling Corp")
            if oil_uri:
                self.check("INTERSECT semantics - Oil Drilling excluded",
                           oil_uri not in entity_uris_result,
                           f"Oil Drilling URI={oil_uri}")

            # Acme Solar should be in results (good match on both vectors)
            acme_uri = self.entity_uris.get("Acme Solar Corp")
            if acme_uri and entity_uris_result:
                self.check("Acme Solar in results",
                           acme_uri in entity_uris_result,
                           f"Acme URI={acme_uri}")

        except Exception as e:
            self.check("Multi-vector nearby basic", False, str(e))

    async def test_multi_vector_nearby_weighted(self):
        """Test that changing weights changes ranking order."""
        logger.info("\n--- Test: Multi-Vector Nearby (weighted) ---")
        try:
            # Heavy weight on entity_type (vec_a)
            criteria_a = self._build_multi_vector_criteria(weight_a=0.9, weight_b=0.1)
            resp_a = await self.client.kgqueries.query_connections(
                space_id=TEST_SPACE_ID,
                graph_id=TEST_GRAPH_ID,
                criteria=criteria_a,
                page_size=10,
            )

            # Heavy weight on entity_default (vec_b)
            criteria_b = self._build_multi_vector_criteria(weight_a=0.1, weight_b=0.9)
            resp_b = await self.client.kgqueries.query_connections(
                space_id=TEST_SPACE_ID,
                graph_id=TEST_GRAPH_ID,
                criteria=criteria_b,
                page_size=10,
            )

            uris_a = resp_a.entity_uris or []
            uris_b = resp_b.entity_uris or []

            self.check("Type-weighted returns results", len(uris_a) > 0)
            self.check("Entity-weighted returns results", len(uris_b) > 0)

            if uris_a and uris_b and len(uris_a) > 1 and len(uris_b) > 1:
                self.check("Different weights produce different rankings",
                           uris_a != uris_b,
                           f"type-biased top={uris_a[0]}, entity-biased top={uris_b[0]}")

        except Exception as e:
            self.check("Multi-vector nearby weighted", False, str(e))

    async def test_multi_vector_min_score(self):
        """Test min_score threshold filtering."""
        logger.info("\n--- Test: Multi-Vector with min_score threshold ---")
        try:
            # Very high threshold — cosine sim on 8-dim won't reach 0.99
            criteria = self._build_multi_vector_criteria(
                weight_a=0.5, weight_b=0.5, min_score=0.99)
            resp = await self.client.kgqueries.query_connections(
                space_id=TEST_SPACE_ID,
                graph_id=TEST_GRAPH_ID,
                criteria=criteria,
                page_size=10,
            )

            uris = resp.entity_uris or []
            self.check("High threshold filters results",
                       len(uris) < len(self.entity_uris),
                       f"got {len(uris)} (expected fewer than {len(self.entity_uris)})")

        except Exception as e:
            self.check("Multi-vector min_score", False, str(e))


# ===========================================================================
# Main
# ===========================================================================
async def main():
    print("\n" + "=" * 80)
    print("  SPARQL-SQL Backend -- Multi-Vector Query End-to-End Test")
    print("=" * 80)
    print(f"  Space:  {TEST_SPACE_ID}")
    print(f"  Graph:  {TEST_GRAPH_ID}")

    client = VitalGraphClient()
    await client.open()
    if not client.is_connected():
        logger.error("\u274c Failed to connect to VitalGraph server")
        return False
    logger.info("\n\u2705 Connected to VitalGraph server\n")

    t0 = time.time()
    success = True

    try:
        # Pre-test cleanup
        resp = await client.spaces.list_spaces()
        existing_ids = [s.space for s in resp.spaces] if resp.is_success else []
        if TEST_SPACE_ID in existing_ids:
            logger.info(f"  Deleting pre-existing space '{TEST_SPACE_ID}'...")
            await client.spaces.delete_space(TEST_SPACE_ID)

        # Create space
        space = Space(space=TEST_SPACE_ID, space_name=TEST_SPACE_NAME,
                      space_description="Multi-vector end-to-end test space")
        cr = await client.spaces.create_space(space)
        if not cr.is_success:
            logger.error(f"\u274c Failed to create space: {cr.error_message}")
            return False
        logger.info(f"  \u2705 Space '{TEST_SPACE_ID}' created")

        # Create graph
        await client.graphs.create_graph(TEST_SPACE_ID, TEST_GRAPH_ID)
        logger.info(f"  \u2705 Graph '{TEST_GRAPH_ID}' created")

        # Run tests
        runner = MultiVectorTestRunner(client)

        if not await runner.setup_vector_indexes():
            logger.error("\u274c Failed to set up vector indexes")
            success = False
        elif not await runner.setup_entities_and_vectors():
            logger.error("\u274c Failed to set up entities and vectors")
            success = False
        else:
            await runner.test_multi_vector_nearby_basic()
            await runner.test_multi_vector_nearby_weighted()
            await runner.test_multi_vector_min_score()

        # Summary
        elapsed = time.time() - t0
        print(f"\n{'=' * 80}")
        print(f"  Results: {runner.passed} passed, {runner.failed} failed "
              f"({elapsed:.1f}s)")
        print(f"{'=' * 80}\n")
        success = runner.failed == 0

    finally:
        if DELETE_SPACE_AT_END:
            logger.info("\n--- Cleanup: deleting test space ---")
            try:
                await client.spaces.delete_space(TEST_SPACE_ID)
                logger.info(f"  Deleted space: {TEST_SPACE_ID}")
            except Exception as e:
                logger.warning(f"  Cleanup failed: {e}")

        await client.close()

    return success


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
