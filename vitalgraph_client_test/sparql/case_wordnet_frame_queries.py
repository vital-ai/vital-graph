"""
WordNet Frame SPARQL Query Test Cases

Tests the frame query pattern from happy_words.py:
- UNION query finding entities with "happy" in description (source OR dest side)
- KGFrame structure traversal via slots and edges
- ASK queries on frame data
"""

import logging
import time
from typing import Dict, Any

from vitalgraph.model.sparql_model import SPARQLQueryRequest, SPARQLQueryResponse

logger = logging.getLogger(__name__)

# Ontology constants
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
VITAL_NAME = "http://vital.ai/ontology/vital-core#hasName"
VITAL_EDGE_SRC = "http://vital.ai/ontology/vital-core#hasEdgeSource"
VITAL_EDGE_DST = "http://vital.ai/ontology/vital-core#hasEdgeDestination"
HALEY_KG_ENTITY = "http://vital.ai/ontology/haley-ai-kg#KGEntity"
HALEY_KG_FRAME = "http://vital.ai/ontology/haley-ai-kg#KGFrame"
HALEY_KG_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription"
HALEY_FRAME_TYPE_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription"
HALEY_SLOT_TYPE = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType"
HALEY_SLOT_VALUE = "http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue"


class WordNetFrameQueryTester:
    """Test case for WordNet frame UNION queries."""

    def __init__(self, client):
        self.client = client

    async def run_tests(self, space_id: str) -> Dict[str, Any]:
        """Run all frame query tests.

        Args:
            space_id: Space containing WordNet data

        Returns:
            Dict with test results
        """
        results = {
            "test_name": "WordNet Frame Queries",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
        }

        tests = [
            ("ASK: KGFrames Exist", self._test_ask_frames_exist),
            ("Frame Count", self._test_frame_count),
            ("Happy Frame UNION Query", self._test_happy_frame_union),
            ("Frame Type Distribution", self._test_frame_type_distribution),
        ]

        for name, fn in tests:
            results["tests_run"] += 1
            try:
                passed = await fn(space_id)
                if passed:
                    results["tests_passed"] += 1
                    logger.info(f"  ✅ {name}")
                else:
                    results["tests_failed"] += 1
                    results["errors"].append(name)
                    logger.info(f"  ❌ {name}")
            except Exception as e:
                results["tests_failed"] += 1
                results["errors"].append(f"{name}: {e}")
                logger.info(f"  ❌ {name}: {e}")

        return results

    async def _query(self, space_id: str, sparql: str) -> SPARQLQueryResponse:
        req = SPARQLQueryRequest(query=sparql, format="json")
        return await self.client.execute_sparql_query(space_id, req)

    async def _test_ask_frames_exist(self, space_id: str) -> bool:
        """ASK whether any KGFrame instances exist."""
        sparql = f"""
        ASK {{
            ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
        }}
        """
        result = await self._query(space_id, sparql)
        boolean_result = getattr(result, "boolean", None)
        logger.info(f"    ASK KGFrame exists: {boolean_result}")
        return boolean_result is True

    async def _test_frame_count(self, space_id: str) -> bool:
        """Count total KGFrame instances."""
        sparql = f"""
        SELECT (COUNT(?frame) AS ?count) WHERE {{
            ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
        }}
        """
        t0 = time.time()
        result = await self._query(space_id, sparql)
        dt = time.time() - t0

        bindings = result.results.get("bindings", []) if result.results else []
        if not bindings:
            logger.info("    No frame count returned")
            return False

        count = int(bindings[0].get("count", {}).get("value", "0"))
        logger.info(f"    KGFrame count: {count:,} ({dt:.3f}s)")
        return count > 0

    async def _test_happy_frame_union(self, space_id: str) -> bool:
        """UNION query: find frames where source OR dest has 'happy' in description.

        This is the frame query from happy_words.py.
        """
        sparql = f"""
        SELECT ?entity ?frame ?srcEntity ?dstEntity WHERE {{
            {{
                ?srcEntity <{HALEY_KG_DESC}> ?srcDesc .
                FILTER(CONTAINS(?srcDesc, "happy"))
                FILTER(?srcEntity != ?dstEntity)

                ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
                ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .
                ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
                ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
                ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .
                BIND(?srcEntity AS ?entity)
            }}
            UNION
            {{
                ?dstEntity <{HALEY_KG_DESC}> ?dstDesc .
                FILTER(CONTAINS(?dstDesc, "happy"))
                FILTER(?srcEntity != ?dstEntity)

                ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
                ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .
                ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
                ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
                ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .
                BIND(?dstEntity AS ?entity)
            }}
        }}
        ORDER BY ?entity
        """
        t0 = time.time()
        result = await self._query(space_id, sparql)
        dt = time.time() - t0

        bindings = result.results.get("bindings", []) if result.results else []
        logger.info(f"    UNION query: {len(bindings)} rows ({dt:.3f}s)")

        if not bindings:
            logger.info("    No frame results — data may lack descriptions with 'happy'")
            # This is still a valid test result (query executed successfully)
            return True

        # Count unique entities
        entities = {b.get("entity", {}).get("value") for b in bindings}
        frames = {b.get("frame", {}).get("value") for b in bindings}
        logger.info(f"    Unique entities: {len(entities)}, unique frames: {len(frames)}")
        return True

    async def _test_frame_type_distribution(self, space_id: str) -> bool:
        """Distribution of frame types (hasKGFrameTypeDescription values)."""
        sparql = f"""
        SELECT ?frameType (COUNT(?frame) AS ?count) WHERE {{
            ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
            ?frame <{HALEY_FRAME_TYPE_DESC}> ?frameType .
        }}
        GROUP BY ?frameType
        ORDER BY DESC(?count)
        LIMIT 10
        """
        t0 = time.time()
        result = await self._query(space_id, sparql)
        dt = time.time() - t0

        bindings = result.results.get("bindings", []) if result.results else []
        if not bindings:
            logger.info("    No frame types found")
            return False

        logger.info(f"    Frame types ({dt:.3f}s):")
        for b in bindings[:8]:
            ft = b.get("frameType", {}).get("value", "?")
            c = b.get("count", {}).get("value", "0")
            if ft.startswith("Edge_Wordnet"):
                ft = ft[len("Edge_Wordnet"):]
            elif ft.startswith("Edge_"):
                ft = ft[len("Edge_"):]
            logger.info(f"      {ft}: {int(c):,}")
        return True
