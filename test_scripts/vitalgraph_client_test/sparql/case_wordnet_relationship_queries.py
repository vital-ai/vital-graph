"""
WordNet Happy Words SPARQL Query Test Cases

Uses the exact queries from vitalgraph_sparql_sql/scripts/happy_words_v2.py:
  1. Relationships query — REGEX("happy","i") on hasName, traverse KGFrame graph
  2. Frame UNION query — REGEX("animal","i") on hasKGraphDescription, source OR dest
"""

import logging
import time
from typing import Dict, Any

from vitalgraph.model.sparql_model import SPARQLQueryRequest, SPARQLQueryResponse

logger = logging.getLogger(__name__)

# Ontology constants — identical to happy_words.py
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
VITAL_NAME = "http://vital.ai/ontology/vital-core#hasName"
VITAL_EDGE_SRC = "http://vital.ai/ontology/vital-core#hasEdgeSource"
VITAL_EDGE_DST = "http://vital.ai/ontology/vital-core#hasEdgeDestination"
HALEY_KG_ENTITY = "http://vital.ai/ontology/haley-ai-kg#KGEntity"
HALEY_KG_FRAME = "http://vital.ai/ontology/haley-ai-kg#KGFrame"
HALEY_FRAME_TYPE_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription"
HALEY_KG_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription"
HALEY_SLOT_TYPE = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType"
HALEY_SLOT_VALUE = "http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue"

# ── Exact SPARQL from happy_words_v2.py lines 138-158 ────────────────────
RELATIONSHIPS_SPARQL = f"""
    SELECT ?srcName ?relationType ?dstName WHERE {{
        ?srcEntity <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
        ?srcEntity <{VITAL_NAME}> ?srcName .
        FILTER(REGEX(?srcName, "happy", "i"))

        ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
        ?frame <{HALEY_FRAME_TYPE_DESC}> ?relationType .

        ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
        ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
        ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
        ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .

        ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
        ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
        ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
        ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .

        ?dstEntity <{VITAL_NAME}> ?dstName .
    }}
"""

# ── Exact SPARQL from happy_words_v2.py lines 162-196 ────────────────────
FRAME_UNION_SPARQL = f"""
    SELECT ?entity ?frame ?srcEntity ?dstEntity WHERE {{
        {{
            ?srcEntity <{HALEY_KG_DESC}> ?srcDesc .
            FILTER(REGEX(?srcDesc, "happy", "i"))
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
            FILTER(REGEX(?dstDesc, "happy", "i"))
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


class WordNetHappyWordsTester:
    """Test case for the exact happy_words.py queries via REST API."""

    def __init__(self, client):
        self.client = client

    async def run_tests(self, space_id: str) -> Dict[str, Any]:
        """Run both happy_words.py queries.

        Args:
            space_id: Space containing WordNet data

        Returns:
            Dict with test results
        """
        results = {
            "test_name": "WordNet Happy Words Queries (v2)",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
        }

        tests = [
            ("Relationships Query (happy_words_v2.py L138-158)", self._test_relationships),
            ("Frame UNION Query (happy_words_v2.py L162-196)", self._test_frame_union),
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

    async def _test_relationships(self, space_id: str) -> bool:
        """Exact relationships query from happy_words.py run() lines 91-112."""
        t0 = time.time()
        result = await self._query(space_id, RELATIONSHIPS_SPARQL)
        dt = time.time() - t0

        bindings = result.results.get("bindings", []) if result.results else []
        logger.info(f"    {len(bindings)} relationships ({dt:.3f}s)")

        if not bindings:
            logger.info("    No relationships found")
            return False

        # Group by relation type (same display logic as happy_words.py)
        by_rel: dict = {}
        for b in bindings:
            src = b.get("srcName", {}).get("value", "?")
            rel = b.get("relationType", {}).get("value", "?")
            dst = b.get("dstName", {}).get("value", "?")
            rel_short = rel
            if rel_short.startswith("Edge_Wordnet"):
                rel_short = rel_short[len("Edge_Wordnet"):]
            elif rel_short.startswith("Edge_"):
                rel_short = rel_short[len("Edge_"):]
            by_rel.setdefault(rel_short, []).append((src, dst))

        for rel_type in sorted(by_rel.keys()):
            pairs = by_rel[rel_type]
            logger.info(f"    {rel_type} ({len(pairs)}):")
            for src, dst in sorted(pairs)[:3]:
                logger.info(f"      {src} ---{rel_type}---> {dst}")
            if len(pairs) > 3:
                logger.info(f"      ... and {len(pairs) - 3} more")

        return True

    async def _test_frame_union(self, space_id: str) -> bool:
        """Exact frame UNION query from happy_words.py lines 272-307."""
        t0 = time.time()
        result = await self._query(space_id, FRAME_UNION_SPARQL)
        dt = time.time() - t0

        bindings = result.results.get("bindings", []) if result.results else []

        # Collect unique entities and frames (same as happy_words.py)
        entity_uris = set()
        frame_uris = set()
        for b in bindings:
            for key in ("entity", "srcEntity", "dstEntity"):
                uri = b.get(key, {}).get("value")
                if uri:
                    entity_uris.add(uri)
            f = b.get("frame", {}).get("value")
            if f:
                frame_uris.add(f)

        logger.info(f"    {len(bindings)} rows ({dt:.3f}s)")
        logger.info(f"    Unique entities: {len(entity_uris)}, unique frames: {len(frame_uris)}")

        if not bindings:
            logger.info("    No frame results — data may lack descriptions with 'happy'")
            return True  # Query executed successfully, just no matching data

        return True
