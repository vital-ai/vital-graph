#!/usr/bin/env python3
"""
KG Type Relationship SPARQL Queries — Test against FrameNet Data
================================================================

Tests the SPARQL queries needed for Phase 2 (Type Detail Enhancements)
against the real FrameNet KG types dataset in the framenet_kgtypes_test
space.  This validates query correctness before wiring into endpoints/UI.

Queries tested:
  1. Get sub-frame types for a given frame type (Edge_hasSubKGFrameType)
  2. Get parent frame types for a given frame type
  3. Get all relationships for a frame type (outgoing + incoming edges)
  4. Count frames with/without children
  5. Get a specific frame type with its properties
  6. List frame types with hierarchy depth info

Requirements:
  - PostgreSQL with sparql_sql_graph database (FrameNet data loaded)
  - Jena sidecar running at localhost:7070

Usage:
  python test_scripts/sparql/test_kgtype_relationship_queries.py
"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────
SPACE_ID = "framenet_kgtypes_test"
GRAPH_URI = "urn:vitalgraph:framenet_kgtypes_test:kg_types"
SIDECAR_URL = "http://localhost:7070"

PG_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "sparql_sql_graph",
    "username": "postgres",
    "password": "postgres",
}

# RDF property URIs
VITALTYPE = "http://vital.ai/ontology/vital-core#vitaltype"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
HAS_NAME = "http://vital.ai/ontology/vital-core#hasName"
HAS_DESCRIPTION = "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription"
HAS_EDGE_SOURCE = "http://vital.ai/ontology/vital-core#hasEdgeSource"
HAS_EDGE_DESTINATION = "http://vital.ai/ontology/vital-core#hasEdgeDestination"
HAS_EXTERN_ID = "http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeExternIdentifier"

TYPE_KGFRAMETYPE = "http://vital.ai/ontology/haley-ai-kg#KGFrameType"
TYPE_KGSLOTTYPE = "http://vital.ai/ontology/haley-ai-kg#KGSlotType"
TYPE_EDGE_SUB = "http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGFrameType"


# ── Helpers ────────────────────────────────────────────────────────────────

def extract_value(binding: dict, var: str) -> Optional[str]:
    """Extract a value from a SPARQL JSON binding."""
    entry = binding.get(var)
    if entry is None:
        return None
    return entry.get("value")


async def run_query(
    space_impl: SparqlSQLSpaceImpl,
    name: str,
    sparql: str,
    expected_count: Optional[int] = None,
    show_max: int = 10,
) -> List[dict]:
    """Run a SPARQL query, print results, and return bindings."""
    print(f"\n{'─' * 70}")
    print(f"  {name}")
    print(f"{'─' * 70}")

    t0 = time.time()
    result = await space_impl.execute_sparql_query(SPACE_ID, sparql)
    elapsed = time.time() - t0

    bindings = result.get("results", {}).get("bindings", [])
    count = len(bindings)

    status = "✅"
    if expected_count is not None and count != expected_count:
        status = "❌"

    expected_str = f" (expected {expected_count})" if expected_count is not None else ""
    print(f"  {status} {count} results in {elapsed:.3f}s{expected_str}")

    for i, b in enumerate(bindings[:show_max]):
        vals = {k: v.get("value", "?") for k, v in b.items()}
        print(f"    [{i+1}] {vals}")
    if count > show_max:
        print(f"    ... and {count - show_max} more")

    if not result.get("success", True):
        print(f"  ⚠️  Error: {result.get('error')}")

    return bindings


# ── Queries ────────────────────────────────────────────────────────────────
#
# NOTE: vitaltype values are stored as URIs, so always use <URI> syntax
# in SPARQL, not "literal" string syntax.  E.g.:
#   ?edge vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGFrameType> .
#

TEST_FRAME_URI = "urn:vitalgraph:framenet:frame-type:Intentionally_act"
TEST_FRAME_COMMERCE = "urn:vitalgraph:framenet:frame-type:Commerce_buy"
TEST_SLOT_URI = "urn:vitalgraph:framenet:slot-type:Agent"

Q1_SUB_FRAME_TYPES = f"""\
PREFIX vc: <http://vital.ai/ontology/vital-core#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?childURI ?childName ?childDesc
WHERE {{
  ?edge vc:vitaltype <{TYPE_EDGE_SUB}> .
  ?edge vc:hasEdgeSource <{TEST_FRAME_URI}> .
  ?edge vc:hasEdgeDestination ?childURI .
  ?childURI vc:hasName ?childName .
  OPTIONAL {{ ?childURI haley:hasKGraphDescription ?childDesc }}
}}
ORDER BY ?childName
"""

Q2_PARENT_FRAME_TYPES = f"""\
PREFIX vc: <http://vital.ai/ontology/vital-core#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?parentURI ?parentName
WHERE {{
  ?edge vc:vitaltype <{TYPE_EDGE_SUB}> .
  ?edge vc:hasEdgeSource ?parentURI .
  ?edge vc:hasEdgeDestination <{TEST_FRAME_URI}> .
  ?parentURI vc:hasName ?parentName .
}}
ORDER BY ?parentName
"""

Q3_ALL_RELATIONSHIPS = f"""\
PREFIX vc: <http://vital.ai/ontology/vital-core#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?direction ?relatedURI ?relatedName ?edgeType
WHERE {{
  {{
    ?edge vc:vitaltype ?edgeType .
    ?edge vc:hasEdgeSource ?thisURI .
    ?edge vc:hasEdgeDestination ?relatedURI .
    ?relatedURI vc:hasName ?relatedName .
    FILTER(?thisURI = <{TEST_FRAME_URI}>)
    BIND("outgoing" AS ?direction)
  }}
  UNION
  {{
    ?edge vc:vitaltype ?edgeType .
    ?edge vc:hasEdgeSource ?relatedURI .
    ?edge vc:hasEdgeDestination ?thisURI .
    ?relatedURI vc:hasName ?relatedName .
    FILTER(?thisURI = <{TEST_FRAME_URI}>)
    BIND("incoming" AS ?direction)
  }}
}}
ORDER BY ?direction ?relatedName
"""

Q4_HIERARCHY_STATS = f"""\
PREFIX vc: <http://vital.ai/ontology/vital-core#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?parentName (COUNT(?childURI) AS ?childCount)
WHERE {{
  ?edge vc:vitaltype <{TYPE_EDGE_SUB}> .
  ?edge vc:hasEdgeSource ?parentURI .
  ?edge vc:hasEdgeDestination ?childURI .
  ?parentURI vc:hasName ?parentName .
}}
GROUP BY ?parentName
ORDER BY DESC(?childCount)
"""

Q5_FRAME_TYPE_DETAIL = f"""\
PREFIX vc: <http://vital.ai/ontology/vital-core#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?name ?description ?externId
WHERE {{
  <{TEST_FRAME_COMMERCE}> vc:vitaltype <{TYPE_KGFRAMETYPE}> .
  <{TEST_FRAME_COMMERCE}> vc:hasName ?name .
  OPTIONAL {{ <{TEST_FRAME_COMMERCE}> haley:hasKGraphDescription ?description }}
  OPTIONAL {{ <{TEST_FRAME_COMMERCE}> haley:hasKGFrameTypeExternIdentifier ?externId }}
}}
"""

Q6_LEAF_FRAMES = f"""\
PREFIX vc: <http://vital.ai/ontology/vital-core#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT (COUNT(?frame) AS ?leafCount)
WHERE {{
  ?frame vc:vitaltype <{TYPE_KGFRAMETYPE}> .
  FILTER NOT EXISTS {{
    ?edge vc:vitaltype <{TYPE_EDGE_SUB}> .
    ?edge vc:hasEdgeSource ?frame .
  }}
}}
"""

Q7_ROOT_FRAMES = f"""\
PREFIX vc: <http://vital.ai/ontology/vital-core#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?name
WHERE {{
  ?frame vc:vitaltype <{TYPE_KGFRAMETYPE}> .
  ?frame vc:hasName ?name .
  FILTER NOT EXISTS {{
    ?edge vc:vitaltype <{TYPE_EDGE_SUB}> .
    ?edge vc:hasEdgeDestination ?frame .
  }}
}}
ORDER BY ?name
"""

Q8_SLOT_TYPE_DETAIL = f"""\
PREFIX vc: <http://vital.ai/ontology/vital-core#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?name ?label ?description ?externId
WHERE {{
  <{TEST_SLOT_URI}> vc:vitaltype <{TYPE_KGSLOTTYPE}> .
  <{TEST_SLOT_URI}> vc:hasName ?name .
  OPTIONAL {{ <{TEST_SLOT_URI}> haley:hasKGSlotTypeLabel ?label }}
  OPTIONAL {{ <{TEST_SLOT_URI}> haley:hasKGraphDescription ?description }}
  OPTIONAL {{ <{TEST_SLOT_URI}> haley:hasKGSlotTypeExternIdentifier ?externId }}
}}
"""

Q9_TYPE_SEARCH_BY_NAME = f"""\
PREFIX vc: <http://vital.ai/ontology/vital-core#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?uri ?name ?vitaltype
WHERE {{
  ?uri vc:vitaltype ?vitaltype .
  ?uri vc:hasName ?name .
  FILTER(CONTAINS(LCASE(?name), "commerce"))
}}
ORDER BY ?name
"""


# ── Main ───────────────────────────────────────────────────────────────────

async def main():
    print("=" * 70)
    print("  KG Type Relationship SPARQL Queries — FrameNet Test Data")
    print("=" * 70)
    print(f"  Space:   {SPACE_ID}")
    print(f"  Graph:   {GRAPH_URI}")
    print(f"  Sidecar: {SIDECAR_URL}")

    space_impl = SparqlSQLSpaceImpl(
        postgresql_config=PG_CONFIG,
        sidecar_config={"url": SIDECAR_URL},
    )

    connected = await space_impl.connect()
    if not connected:
        print("❌ Failed to connect to PostgreSQL")
        return False

    print("  ✅ Connected\n")

    passed = 0
    failed = 0
    total = 0

    tests = [
        ("Q1: Sub-frame types of Intentionally_act", Q1_SUB_FRAME_TYPES, None),
        ("Q2: Parent frame types of Intentionally_act", Q2_PARENT_FRAME_TYPES, None),
        ("Q3: All relationships of Intentionally_act", Q3_ALL_RELATIONSHIPS, None),
        ("Q4: Hierarchy stats (frames with most children)", Q4_HIERARCHY_STATS, None),
        ("Q5: Frame type detail — Commerce_buy", Q5_FRAME_TYPE_DETAIL, 1),
        ("Q6: Count of leaf frames (no children)", Q6_LEAF_FRAMES, 1),
        ("Q7: Root frames (no parents)", Q7_ROOT_FRAMES, None),
        ("Q8: Slot type detail — Agent", Q8_SLOT_TYPE_DETAIL, 1),
        ("Q9: Type search by name containing 'commerce'", Q9_TYPE_SEARCH_BY_NAME, None),
    ]

    for name, sparql, expected in tests:
        total += 1
        try:
            bindings = await run_query(space_impl, name, sparql, expected_count=expected)
            if expected is not None and len(bindings) != expected:
                failed += 1
            else:
                passed += 1
        except Exception as e:
            print(f"  ❌ Exception: {e}")
            failed += 1

    await space_impl.disconnect()

    print(f"\n{'=' * 70}")
    print(f"  Results: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 70}\n")

    return failed == 0


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
