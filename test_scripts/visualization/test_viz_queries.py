#!/usr/bin/env python3
"""
test_viz_queries.py — Validate SPARQL queries for graph visualization.

Tests the queries that the frontend will use:
  1. Entity search by name
  2. Neighbor expansion (both directions)
  3. Neighbor expansion with relation type filter
  4. Entity detail lookup
  5. Client-side frame simplification logic

Requires:
  - Jena sidecar running at localhost:7070
  - PostgreSQL with WordNet data in wordnet_exp_* tables

Usage:
    python test_scripts/visualization/test_viz_queries.py
"""

import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph_sparql_sql.jena_sparql_orchestrator import SparqlOrchestrator

logger = logging.getLogger("test_viz_queries")

SPACE_ID = "wordnet_exp"

# ---------------------------------------------------------------------------
# Ontology constants
# ---------------------------------------------------------------------------
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
HALEY_ENTITY_TYPE_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGEntityTypeDescription"


def _remap_rows(result) -> list:
    """Remap row keys from opaque SQL names to SPARQL variable names."""
    vm = getattr(result, 'var_map', None) or {}
    if not vm or not result.rows:
        return result.rows or []
    remap = {opaque: sparql.lower() for opaque, sparql in vm.items()}
    return [{remap.get(k, k): v for k, v in row.items()} for row in result.rows]


# ---------------------------------------------------------------------------
# Globals set by test_entity_search for subsequent tests
# ---------------------------------------------------------------------------
SAMPLE_ENTITY_URI = None
SAMPLE_ENTITY_NAME = None
SAMPLE_REL_TYPE = None


# ---------------------------------------------------------------------------
# Test functions
# ---------------------------------------------------------------------------

async def test_entity_search(orch: SparqlOrchestrator) -> bool:
    """Test 1: Search for entities by name substring."""
    global SAMPLE_ENTITY_URI, SAMPLE_ENTITY_NAME

    print("\n" + "=" * 70)
    print("Test 1: Entity Search (name contains 'happy')")
    print("=" * 70)

    # Case-insensitive REGEX triggers filter pushdown (term_text ~* 'happy')
    # using GIN trgm index. Avoids LCASE (prevents pushdown, 227× slower)
    # and OPTIONAL LEFT JOIN (~1.8s overhead). Entity type fetched on-demand.
    sparql = f"""
        SELECT ?entity ?name WHERE {{
            ?entity <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
            ?entity <{VITAL_NAME}> ?name .
            FILTER(REGEX(?name, "happy", "i"))
        }} LIMIT 50
    """

    t0 = time.monotonic()
    result = await orch.execute(sparql, include_sql=True)
    wall_ms = (time.monotonic() - t0) * 1000

    if not result.ok:
        print(f"  FAIL: {result.error}")
        return False

    rows = _remap_rows(result)
    print(f"  Rows: {len(rows)}, Wall: {wall_ms:.0f}ms")
    if result.timing:
        print(f"  Timing: {result.timing}")

    if not rows:
        print("  FAIL: No results (expected at least 1 entity named 'happy')")
        return False

    print(f"\n  Results:")
    for row in rows[:10]:
        print(f"    {row.get('name', '?')} ({row.get('entitytypedesc', 'unknown type')})")
        print(f"      URI: {row.get('entity', '?')}")

    # Capture a URI for subsequent tests
    SAMPLE_ENTITY_URI = rows[0].get('entity')
    SAMPLE_ENTITY_NAME = rows[0].get('name', '?')
    print(f"\n  Using entity for expansion tests: {SAMPLE_ENTITY_NAME} ({SAMPLE_ENTITY_URI})")

    print(f"  PASS ({len(rows)} entities found)")
    return True


async def test_expand_neighbors(orch: SparqlOrchestrator) -> bool:
    """Test 2: Expand a node to find all neighbors via frames."""
    global SAMPLE_REL_TYPE

    print("\n" + "=" * 70)
    print(f"Test 2: Expand Neighbors of '{SAMPLE_ENTITY_NAME}'")
    print("=" * 70)

    # Use UNION instead of FILTER(OR) so the optimizer can bind the
    # entity URI directly in each arm, avoiding a full scan.
    sparql = f"""
        SELECT ?srcEntity ?srcName ?dstEntity ?dstName ?frame ?relationType WHERE {{
            {{
                BIND(<{SAMPLE_ENTITY_URI}> AS ?srcEntity)
                ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
                ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .

                ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame <{HALEY_FRAME_TYPE_DESC}> ?relationType .

                ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
                ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
                ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .

                ?srcEntity <{VITAL_NAME}> ?srcName .
                ?dstEntity <{VITAL_NAME}> ?dstName .
            }}
            UNION
            {{
                BIND(<{SAMPLE_ENTITY_URI}> AS ?dstEntity)
                ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
                ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
                ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .

                ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame <{HALEY_FRAME_TYPE_DESC}> ?relationType .

                ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
                ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .

                ?srcEntity <{VITAL_NAME}> ?srcName .
                ?dstEntity <{VITAL_NAME}> ?dstName .
            }}
        }}
    """

    t0 = time.monotonic()
    result = await orch.execute(sparql, include_sql=True)
    wall_ms = (time.monotonic() - t0) * 1000
    if result.timing:
        print(f"  Timing: {result.timing}")

    if not result.ok:
        print(f"  FAIL: {result.error}")
        return False

    rows = _remap_rows(result)
    print(f"  Rows: {len(rows)}, Wall: {wall_ms:.0f}ms")

    if not rows:
        print("  FAIL: No neighbors found")
        return False

    # Count unique neighbors and relation types
    neighbors = set()
    rel_types = set()
    for row in rows:
        src = row.get('srcentity')
        dst = row.get('dstentity')
        rel = row.get('relationtype', '')
        if src != SAMPLE_ENTITY_URI:
            neighbors.add(src)
        if dst != SAMPLE_ENTITY_URI:
            neighbors.add(dst)
        rel_types.add(rel)

    print(f"  Unique neighbors: {len(neighbors)}")
    print(f"  Relation types: {sorted(rel_types)}")

    # Show sample relationships
    print(f"\n  Sample relationships:")
    for row in rows[:10]:
        src_name = row.get('srcname', '?')
        dst_name = row.get('dstname', '?')
        rel = row.get('relationtype', '?')
        if rel.startswith('Edge_Wordnet'):
            rel = rel[len('Edge_Wordnet'):]
        elif rel.startswith('Edge_'):
            rel = rel[len('Edge_'):]
        print(f"    {src_name} --({rel})--> {dst_name}")

    SAMPLE_REL_TYPE = sorted(rel_types)[0] if rel_types else None

    print(f"\n  PASS ({len(neighbors)} neighbors, {len(rel_types)} rel types)")
    return True


async def test_expand_filtered(orch: SparqlOrchestrator) -> bool:
    """Test 3: Expand with a specific relationship type filter."""
    print("\n" + "=" * 70)
    print(f"Test 3: Expand with Relation Type Filter ('{SAMPLE_REL_TYPE}')")
    print("=" * 70)

    if not SAMPLE_REL_TYPE:
        print("  SKIP: No relation type available from Test 2")
        return True

    # Use direct literal in triple pattern instead of FILTER(?relationType = "...").
    # This allows index lookup on the object value rather than a post-filter scan.
    sparql = f"""
        SELECT ?srcEntity ?srcName ?dstEntity ?dstName ?frame ?relationType WHERE {{
            {{
                BIND(<{SAMPLE_ENTITY_URI}> AS ?srcEntity)
                BIND("{SAMPLE_REL_TYPE}" AS ?relationType)
                ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
                ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .

                ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame <{HALEY_FRAME_TYPE_DESC}> "{SAMPLE_REL_TYPE}" .

                ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
                ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
                ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .

                ?srcEntity <{VITAL_NAME}> ?srcName .
                ?dstEntity <{VITAL_NAME}> ?dstName .
            }}
            UNION
            {{
                BIND(<{SAMPLE_ENTITY_URI}> AS ?dstEntity)
                BIND("{SAMPLE_REL_TYPE}" AS ?relationType)
                ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
                ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
                ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .

                ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame <{HALEY_FRAME_TYPE_DESC}> "{SAMPLE_REL_TYPE}" .

                ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
                ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .

                ?srcEntity <{VITAL_NAME}> ?srcName .
                ?dstEntity <{VITAL_NAME}> ?dstName .
            }}
        }}
    """

    t0 = time.monotonic()
    result = await orch.execute(sparql, include_sql=True)
    wall_ms = (time.monotonic() - t0) * 1000
    if result.timing:
        print(f"  Timing: {result.timing}")

    if not result.ok:
        print(f"  FAIL: {result.error}")
        return False

    rows = _remap_rows(result)
    print(f"  Rows: {len(rows)}, Wall: {wall_ms:.0f}ms")

    # Verify all rows have the expected relation type
    wrong_types = [r for r in rows if r.get('relationtype') != SAMPLE_REL_TYPE]
    if wrong_types:
        print(f"  FAIL: {len(wrong_types)} rows have wrong relation type")
        return False

    for row in rows[:5]:
        src_name = row.get('srcname', '?')
        dst_name = row.get('dstname', '?')
        print(f"    {src_name} --> {dst_name}")

    print(f"\n  PASS ({len(rows)} rows, all match filter)")
    return True


async def test_entity_detail(orch: SparqlOrchestrator) -> bool:
    """Test 4: Get entity detail for tooltip/panel."""
    print("\n" + "=" * 70)
    print(f"Test 4: Entity Detail for '{SAMPLE_ENTITY_NAME}'")
    print("=" * 70)

    sparql = f"""
        SELECT ?name ?entityTypeDesc ?description WHERE {{
            <{SAMPLE_ENTITY_URI}> <{VITAL_NAME}> ?name .
            OPTIONAL {{ <{SAMPLE_ENTITY_URI}> <{HALEY_ENTITY_TYPE_DESC}> ?entityTypeDesc }}
            OPTIONAL {{ <{SAMPLE_ENTITY_URI}> <{HALEY_KG_DESC}> ?description }}
        }}
    """

    t0 = time.monotonic()
    result = await orch.execute(sparql)
    wall_ms = (time.monotonic() - t0) * 1000

    if not result.ok:
        print(f"  FAIL: {result.error}")
        return False

    rows = _remap_rows(result)
    print(f"  Rows: {len(rows)}, Wall: {wall_ms:.0f}ms")

    if not rows:
        print("  FAIL: No detail found for entity")
        return False

    row = rows[0]
    print(f"  Name: {row.get('name', '?')}")
    print(f"  Type: {row.get('entitytypedesc', 'unknown')}")
    desc = row.get('description', '')
    if desc:
        print(f"  Description: {desc[:200]}{'...' if len(desc) > 200 else ''}")

    print(f"\n  PASS")
    return True


def test_graph_simplification() -> bool:
    """Test 5: Verify client-side frame simplification logic."""
    print("\n" + "=" * 70)
    print("Test 5: Client-Side Frame Simplification (mock data)")
    print("=" * 70)

    # Simulate SPARQL result rows
    mock_rows = [
        {'srcentity': 'urn:entity:happy', 'srcname': 'happy',
         'dstentity': 'urn:entity:glad', 'dstname': 'glad',
         'frame': 'urn:frame:1', 'relationtype': 'Edge_WordnetSimilar'},
        {'srcentity': 'urn:entity:happy', 'srcname': 'happy',
         'dstentity': 'urn:entity:feeling', 'dstname': 'feeling',
         'frame': 'urn:frame:2', 'relationtype': 'Edge_WordnetHypernym'},
        {'srcentity': 'urn:entity:blissful', 'srcname': 'blissful',
         'dstentity': 'urn:entity:happy', 'dstname': 'happy',
         'frame': 'urn:frame:3', 'relationtype': 'Edge_WordnetSimilar'},
        # Duplicate frame URI should be fuzzylicated
        {'srcentity': 'urn:entity:happy', 'srcname': 'happy',
         'dstentity': 'urn:entity:glad', 'dstname': 'glad',
         'frame': 'urn:frame:1', 'relationtype': 'Edge_WordnetSimilar'},
    ]

    nodes = {}
    edges = {}
    for row in mock_rows:
        src = row['srcentity']
        dst = row['dstentity']
        frame = row['frame']
        rel = row['relationtype']

        if src not in nodes:
            nodes[src] = {'id': src, 'label': row['srcname']}
        if dst not in nodes:
            nodes[dst] = {'id': dst, 'label': row['dstname']}
        if frame not in edges:
            short_rel = rel
            if short_rel.startswith('Edge_Wordnet'):
                short_rel = short_rel[len('Edge_Wordnet'):]
            elif short_rel.startswith('Edge_'):
                short_rel = short_rel[len('Edge_'):]
            edges[frame] = {
                'id': frame,
                'source': src,
                'target': dst,
                'label': short_rel,
            }

    print(f"  Input rows: {len(mock_rows)}")
    print(f"  Unique nodes: {len(nodes)} (expected 4)")
    print(f"  Unique edges: {len(edges)} (expected 3, fuzzyed from 4)")

    for nid, n in nodes.items():
        print(f"    Node: {n['label']} ({nid})")
    for eid, e in edges.items():
        print(f"    Edge: {nodes[e['source']]['label']} --({e['label']})--> {nodes[e['target']]['label']}")

    ok = len(nodes) == 4 and len(edges) == 3
    print(f"\n  {'PASS' if ok else 'FAIL'}")
    return ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    print("=" * 70)
    print("Graph Visualization — SPARQL Query Validation")
    print(f"Space: {SPACE_ID}")
    print("=" * 70)

    results = {}

    # Tests 1-4 use the orchestrator (require sidecar + DB)
    async with SparqlOrchestrator(space_id=SPACE_ID) as orch:
        # Warmup: pay cold-start cost (sidecar connect, DB pool, first compile)
        print("\nWarming up (sidecar + DB connect)...")
        t0 = time.monotonic()
        warmup = await orch.execute("SELECT ?s WHERE { ?s ?p ?o } LIMIT 1")
        warmup_ms = (time.monotonic() - t0) * 1000
        print(f"  Warmup: {'OK' if warmup.ok else 'FAIL'} in {warmup_ms:.0f}ms")

        results['1_entity_search'] = await test_entity_search(orch)

        if SAMPLE_ENTITY_URI:
            results['2_expand_neighbors'] = await test_expand_neighbors(orch)
            results['3_expand_filtered'] = await test_expand_filtered(orch)
            results['4_entity_detail'] = await test_entity_detail(orch)
        else:
            print("\n  SKIP: Tests 2-4 require entity URI from Test 1")
            results['2_expand_neighbors'] = False
            results['3_expand_filtered'] = False
            results['4_entity_detail'] = False

    # Test 5: client-side logic (no DB needed)
    results['5_graph_simplification'] = test_graph_simplification()

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  {status}: {name}")
    print(f"\n  {passed}/{total} tests passed")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
