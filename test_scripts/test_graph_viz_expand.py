#!/usr/bin/env python3
"""
Graph Visualization — Expand Query Tests
==========================================

Tests the SPARQL expand queries used by the graph visualization frontend
against the graph_viz_a through graph_viz_f test datasets.

Each dataset targets a specific visualization pattern:
  A — People & Employment   (binary aspect frames + direct relations)
  B — Research Project       (N-ary aspect frames)
  C — Supply Chain           (mixed arity + subframes)
  D — Social Network         (pure Edge_hasKGRelation, no frames)
  E — Unary Frame            (annotation/tag, data-value slots only)
  F — Top-Level Frames       (Assertions, no owning entity)

Usage:
    python test_scripts/test_graph_viz_expand.py
    python test_scripts/test_graph_viz_expand.py --dataset A
    python test_scripts/test_graph_viz_expand.py --verbose

Requires a running VitalGraph server with the test spaces loaded.
"""

import asyncio
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (must match frontend useGraphVisualization.ts)
# ---------------------------------------------------------------------------

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
VITAL_NAME = "http://vital.ai/ontology/vital-core#hasName"
VITAL_EDGE_SRC = "http://vital.ai/ontology/vital-core#hasEdgeSource"
VITAL_EDGE_DST = "http://vital.ai/ontology/vital-core#hasEdgeDestination"
HALEY_KG_ENTITY = "http://vital.ai/ontology/haley-ai-kg#KGEntity"
HALEY_KG_FRAME = "http://vital.ai/ontology/haley-ai-kg#KGFrame"
HALEY_FRAME_TYPE_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription"
HALEY_SLOT_TYPE = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType"
HALEY_SLOT_VALUE = "http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue"
HALEY_REL_TYPE_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGRelationTypeDescription"
HALEY_FRAME_GRAPH_URI = "http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI"
HALEY_KG_GRAPH_URI = "http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI"


# ---------------------------------------------------------------------------
# Query builder (mirrors frontend buildExpandQuery for non-kgtype spaces)
# ---------------------------------------------------------------------------

def build_expand_query(entity_uri: str) -> str:
    """Build the SPARQL expand query — must match the frontend exactly."""
    return f"""
    SELECT ?srcEntity ?srcName ?dstEntity ?dstName ?frame ?relationType WHERE {{
      {{
        BIND(<{entity_uri}> AS ?srcEntity)
        ?mySlot <{HALEY_SLOT_VALUE}> ?srcEntity .
        ?mySlot <{HALEY_FRAME_GRAPH_URI}> ?frame .
        ?frame <{HALEY_FRAME_TYPE_DESC}> ?relationType .
        ?otherSlot <{HALEY_FRAME_GRAPH_URI}> ?frame .
        ?otherSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
        FILTER(?otherSlot != ?mySlot)
        ?srcEntity <{VITAL_NAME}> ?srcName .
        ?dstEntity <{VITAL_NAME}> ?dstName .
      }}
      UNION
      {{
        BIND(<{entity_uri}> AS ?srcEntity)
        ?frame <{HALEY_KG_GRAPH_URI}> ?srcEntity .
        ?frame <{HALEY_FRAME_TYPE_DESC}> ?relationType .
        ?slot <{HALEY_FRAME_GRAPH_URI}> ?frame .
        ?slot <{HALEY_SLOT_VALUE}> ?dstEntity .
        FILTER(?dstEntity != ?srcEntity)
        ?srcEntity <{VITAL_NAME}> ?srcName .
        ?dstEntity <{VITAL_NAME}> ?dstName .
      }}
      UNION
      {{
        BIND(<{entity_uri}> AS ?srcEntity)
        ?rel <{VITAL_EDGE_SRC}> ?srcEntity .
        ?rel <{VITAL_EDGE_DST}> ?dstEntity .
        ?rel <{HALEY_REL_TYPE_DESC}> ?relationType .
        BIND(?rel AS ?frame)
        ?srcEntity <{VITAL_NAME}> ?srcName .
        ?dstEntity <{VITAL_NAME}> ?dstName .
      }}
      UNION
      {{
        BIND(<{entity_uri}> AS ?dstEntity)
        ?rel <{VITAL_EDGE_DST}> ?dstEntity .
        ?rel <{VITAL_EDGE_SRC}> ?srcEntity .
        ?rel <{HALEY_REL_TYPE_DESC}> ?relationType .
        BIND(?rel AS ?frame)
        ?srcEntity <{VITAL_NAME}> ?srcName .
        ?dstEntity <{VITAL_NAME}> ?dstName .
      }}
      UNION
      {{
        BIND(<{entity_uri}> AS ?srcEntity)
        ?slot <{HALEY_FRAME_GRAPH_URI}> <{entity_uri}> .
        ?slot <{HALEY_SLOT_VALUE}> ?dstEntity .
        ?slot <{HALEY_SLOT_TYPE}> ?relationType .
        BIND(?slot AS ?frame)
        <{entity_uri}> <{VITAL_NAME}> ?srcName .
        ?dstEntity <{VITAL_NAME}> ?dstName .
      }}
    }}
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_bindings(result) -> list:
    """Extract SPARQL result bindings from response."""
    if hasattr(result, 'results'):
        r = result.results
    else:
        r = result
    if isinstance(r, dict):
        return r.get('bindings', [])
    return []


def get_value(binding: dict, var: str) -> str:
    return binding.get(var, {}).get('value', '')


async def find_entities(client: VitalGraphClient, space_id: str, limit: int = 10) -> list:
    """Find KGEntity URIs and names in a space."""
    q = f"""
    SELECT ?s ?name WHERE {{
      ?s <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
      ?s <{VITAL_NAME}> ?name .
    }} LIMIT {limit}
    """
    result = await client.sparql.execute_sparql_query(space_id, SPARQLQueryRequest(query=q))
    return [(get_value(b, 's'), get_value(b, 'name')) for b in extract_bindings(result)]


async def find_frames(client: VitalGraphClient, space_id: str, limit: int = 10) -> list:
    """Find KGFrame URIs and names in a space."""
    q = f"""
    SELECT ?s ?name ?formType WHERE {{
      ?s <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
      ?s <{VITAL_NAME}> ?name .
      OPTIONAL {{ ?s <http://vital.ai/ontology/haley-ai-kg#hasKGFormType> ?formType }}
    }} LIMIT {limit}
    """
    result = await client.sparql.execute_sparql_query(space_id, SPARQLQueryRequest(query=q))
    return [
        (get_value(b, 's'), get_value(b, 'name'), get_value(b, 'formType'))
        for b in extract_bindings(result)
    ]


async def count_relations(client: VitalGraphClient, space_id: str) -> int:
    """Count Edge_hasKGRelation edges in a space."""
    q = """
    SELECT (COUNT(?s) AS ?cnt) WHERE {
      ?s <http://vital.ai/ontology/vital-core#vitaltype>
         <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .
    }
    """
    result = await client.sparql.execute_sparql_query(space_id, SPARQLQueryRequest(query=q))
    bindings = extract_bindings(result)
    return int(get_value(bindings[0], 'cnt')) if bindings else 0


async def count_entity_slots(client: VitalGraphClient, space_id: str) -> int:
    """Count KGEntitySlot objects in a space."""
    q = """
    SELECT (COUNT(?s) AS ?cnt) WHERE {
      ?s <http://vital.ai/ontology/vital-core#vitaltype>
         <http://vital.ai/ontology/haley-ai-kg#KGEntitySlot> .
    }
    """
    result = await client.sparql.execute_sparql_query(space_id, SPARQLQueryRequest(query=q))
    bindings = extract_bindings(result)
    return int(get_value(bindings[0], 'cnt')) if bindings else 0


# ---------------------------------------------------------------------------
# Test functions
# ---------------------------------------------------------------------------

async def test_dataset_a(client: VitalGraphClient, verbose: bool = False):
    """Dataset A: People & Employment — binary aspect frames + relations."""
    space = "graph_viz_a"
    print(f"\n{'='*60}")
    print(f"Dataset A: People & Employment (space={space})")
    print(f"  Expected: binary aspect frames (EmploymentFrame) + knows/partner_of relations")
    print(f"{'='*60}")

    entities = await find_entities(client, space, limit=5)
    n_relations = await count_relations(client, space)
    n_slots = await count_entity_slots(client, space)
    print(f"  Inventory: {len(entities)}+ entities, {n_relations} relations, {n_slots} entity slots")

    if not entities:
        print("  ❌ SKIP — no entities found (space may not be loaded)")
        return False

    ok = True

    # Test 1: Expand a person entity (should find frame-based employment + knows relations)
    person_uri, person_name = entities[0]
    print(f"\n  [Test A.1] Expand person: {person_name}")
    result = await client.sparql.execute_sparql_query(space, SPARQLQueryRequest(query=build_expand_query(person_uri)))
    rows = extract_bindings(result)
    frame_rows = [r for r in rows if 'Frame' in get_value(r, 'relationType')]
    rel_rows = [r for r in rows if 'Frame' not in get_value(r, 'relationType')]
    print(f"    Total: {len(rows)} rows ({len(frame_rows)} frame, {len(rel_rows)} relation)")
    if verbose:
        for r in rows:
            print(f"      {get_value(r, 'srcName'):30s} → {get_value(r, 'dstName'):30s}  [{get_value(r, 'relationType')}]")
    if len(rows) == 0:
        print("    ❌ FAIL — expected at least 1 connection (employer + possible knows)")
        ok = False
    else:
        print(f"    ✅ PASS — found {len(rows)} connections")

    # Test 2: Expand a company entity (should find frame-based employees + partner relations)
    company = next(((u, n) for u, n in entities if 'Corp' in n or 'Inc' in n or 'Org' in n), None)
    if not company:
        # Find a company explicitly
        q = f"""SELECT ?s ?name WHERE {{
          ?s <{VITAL_NAME}> ?name .
          ?s <http://vital.ai/ontology/haley-ai-kg#hasKGEntityTypeDescription> "Organization" .
        }} LIMIT 1"""
        r = await client.sparql.execute_sparql_query(space, SPARQLQueryRequest(query=q))
        b = extract_bindings(r)
        if b:
            company = (get_value(b[0], 's'), get_value(b[0], 'name'))

    if company:
        comp_uri, comp_name = company
        print(f"\n  [Test A.2] Expand company: {comp_name}")
        result = await client.sparql.execute_sparql_query(space, SPARQLQueryRequest(query=build_expand_query(comp_uri)))
        rows = extract_bindings(result)
        frame_rows = [r for r in rows if 'Frame' in get_value(r, 'relationType')]
        rel_rows = [r for r in rows if 'Frame' not in get_value(r, 'relationType')]
        print(f"    Total: {len(rows)} rows ({len(frame_rows)} frame, {len(rel_rows)} relation)")
        if verbose:
            for r in rows:
                print(f"      {get_value(r, 'srcName'):30s} → {get_value(r, 'dstName'):30s}  [{get_value(r, 'relationType')}]")
        if len(rows) == 0:
            print("    ❌ FAIL — expected employees + partner relations")
            ok = False
        else:
            print(f"    ✅ PASS — found {len(rows)} connections")

    return ok


async def test_dataset_b(client: VitalGraphClient, verbose: bool = False):
    """Dataset B: Research — N-ary aspect frames."""
    space = "graph_viz_b"
    print(f"\n{'='*60}")
    print(f"Dataset B: Research (space={space})")
    print(f"  Expected: N-ary aspect frames (3-5 researchers per frame) + relations")
    print(f"{'='*60}")

    entities = await find_entities(client, space, limit=5)
    n_slots = await count_entity_slots(client, space)
    print(f"  Inventory: {len(entities)}+ entities, {n_slots} entity slots")

    if not entities:
        print("  ❌ SKIP — no entities found")
        return False

    ok = True

    # Test: Expand a researcher (should find N-ary frame connections to co-researchers + relations)
    person_uri, person_name = entities[0]
    print(f"\n  [Test B.1] Expand researcher: {person_name}")
    result = await client.sparql.execute_sparql_query(space, SPARQLQueryRequest(query=build_expand_query(person_uri)))
    rows = extract_bindings(result)
    unique_dst = set(get_value(r, 'dstName') for r in rows)
    print(f"    Total: {len(rows)} rows, {len(unique_dst)} unique destinations")
    if verbose:
        for r in rows:
            print(f"      {get_value(r, 'srcName'):30s} → {get_value(r, 'dstName'):30s}  [{get_value(r, 'relationType')}]")
    if len(rows) == 0:
        print("    ❌ FAIL — expected N-ary frame connections + relations")
        ok = False
    else:
        print(f"    ✅ PASS — found {len(rows)} connections to {len(unique_dst)} entities")

    return ok


async def test_dataset_c(client: VitalGraphClient, verbose: bool = False):
    """Dataset C: Supply Chain — mixed arity + subframes."""
    space = "graph_viz_c"
    print(f"\n{'='*60}")
    print(f"Dataset C: Supply Chain (space={space})")
    print(f"  Expected: PurchaseOrder (binary) + Shipping subframes")
    print(f"{'='*60}")

    entities = await find_entities(client, space, limit=5)
    if not entities:
        print("  ❌ SKIP — no entities found")
        return False

    ok = True

    # Expand a buyer
    buyer = next(((u, n) for u, n in entities if 'Buyer' in n), None) or entities[0]
    buyer_uri, buyer_name = buyer
    print(f"\n  [Test C.1] Expand buyer: {buyer_name}")
    result = await client.sparql.execute_sparql_query(space, SPARQLQueryRequest(query=build_expand_query(buyer_uri)))
    rows = extract_bindings(result)
    rel_types = set(get_value(r, 'relationType') for r in rows)
    print(f"    Total: {len(rows)} rows, relation types: {rel_types}")
    if verbose:
        for r in rows:
            print(f"      {get_value(r, 'srcName'):30s} → {get_value(r, 'dstName'):30s}  [{get_value(r, 'relationType')}]")
    if len(rows) == 0:
        print("    ❌ FAIL — expected PO frame connections + customer_of relations")
        ok = False
    else:
        print(f"    ✅ PASS — found {len(rows)} connections")

    return ok


async def test_dataset_d(client: VitalGraphClient, verbose: bool = False):
    """Dataset D: Social Network — pure Edge_hasKGRelation, no frames."""
    space = "graph_viz_d"
    print(f"\n{'='*60}")
    print(f"Dataset D: Social Network (space={space})")
    print(f"  Expected: only direct relation edges (knows, follows, mentors, etc.)")
    print(f"{'='*60}")

    entities = await find_entities(client, space, limit=5)
    n_relations = await count_relations(client, space)
    n_slots = await count_entity_slots(client, space)
    print(f"  Inventory: {len(entities)}+ entities, {n_relations} relations, {n_slots} entity slots")

    if not entities:
        print("  ❌ SKIP — no entities found")
        return False

    ok = True

    # Should have 0 entity slots (no frames)
    if n_slots > 0:
        print(f"    ⚠ WARNING — expected 0 entity slots but found {n_slots}")

    person_uri, person_name = entities[0]
    print(f"\n  [Test D.1] Expand person: {person_name}")
    result = await client.sparql.execute_sparql_query(space, SPARQLQueryRequest(query=build_expand_query(person_uri)))
    rows = extract_bindings(result)
    rel_types = set(get_value(r, 'relationType') for r in rows)
    print(f"    Total: {len(rows)} rows, relation types: {rel_types}")
    if verbose:
        for r in rows[:10]:
            print(f"      {get_value(r, 'srcName'):30s} → {get_value(r, 'dstName'):30s}  [{get_value(r, 'relationType')}]")
        if len(rows) > 10:
            print(f"      ... and {len(rows) - 10} more")
    if len(rows) == 0:
        print("    ❌ FAIL — expected relation edges")
        ok = False
    else:
        print(f"    ✅ PASS — found {len(rows)} relation connections")

    return ok


async def test_dataset_e(client: VitalGraphClient, verbose: bool = False):
    """Dataset E: Unary Frame — data-value slots only, no entity slots."""
    space = "graph_viz_e"
    print(f"\n{'='*60}")
    print(f"Dataset E: Unary Frames (space={space})")
    print(f"  Expected: entities with frames that have no entity slots (classification only)")
    print(f"{'='*60}")

    entities = await find_entities(client, space, limit=5)
    n_relations = await count_relations(client, space)
    n_slots = await count_entity_slots(client, space)
    print(f"  Inventory: {len(entities)}+ entities, {n_relations} relations, {n_slots} entity slots")

    if not entities:
        print("  ❌ SKIP — no entities found")
        return False

    ok = True

    # Should have 0 entity slots (only text/integer slots)
    if n_slots > 0:
        print(f"    ⚠ WARNING — expected 0 entity slots but found {n_slots}")

    topic_uri, topic_name = entities[0]
    print(f"\n  [Test E.1] Expand topic: {topic_name}")
    result = await client.sparql.execute_sparql_query(space, SPARQLQueryRequest(query=build_expand_query(topic_uri)))
    rows = extract_bindings(result)
    print(f"    Total: {len(rows)} rows")
    if verbose:
        for r in rows[:5]:
            print(f"      {get_value(r, 'srcName'):30s} → {get_value(r, 'dstName'):30s}  [{get_value(r, 'relationType')}]")
    # Unary frames have no entity slots, so only relation edges (parent_topic) should appear
    if len(rows) > 0:
        print(f"    ✅ PASS — found {len(rows)} relation connections (parent_topic expected)")
    else:
        if n_relations > 0:
            print("    ❌ FAIL — expected parent_topic relations but found 0")
            ok = False
        else:
            print("    ✅ PASS — 0 connections (correct: unary frames with no entity slots)")

    return ok


async def test_dataset_f(client: VitalGraphClient, verbose: bool = False):
    """Dataset F: Top-Level Frames — Assertions, no owning entity."""
    space = "graph_viz_f"
    print(f"\n{'='*60}")
    print(f"Dataset F: Top-Level Frames / Assertions (space={space})")
    print(f"  Expected: frames without owning entity, connected to entities via slots")
    print(f"{'='*60}")

    entities = await find_entities(client, space, limit=5)
    frames = await find_frames(client, space, limit=5)
    n_slots = await count_entity_slots(client, space)
    print(f"  Inventory: {len(entities)}+ entities, {len(frames)}+ frames, {n_slots} entity slots")

    if not entities:
        print("  ❌ SKIP — no entities found")
        return False

    ok = True

    # Test 1: Expand an entity — should find connections via assertion frames
    person_uri, person_name = entities[0]
    print(f"\n  [Test F.1] Expand entity: {person_name}")
    result = await client.sparql.execute_sparql_query(space, SPARQLQueryRequest(query=build_expand_query(person_uri)))
    rows = extract_bindings(result)
    unique_dst = set(get_value(r, 'dstName') for r in rows)
    print(f"    Total: {len(rows)} rows, {len(unique_dst)} unique destinations")
    if verbose:
        for r in rows[:10]:
            print(f"      {get_value(r, 'srcName'):30s} → {get_value(r, 'dstName'):30s}  [{get_value(r, 'relationType')}]")
        if len(rows) > 10:
            print(f"      ... and {len(rows) - 10} more")
    if len(rows) == 0:
        print("    ❌ FAIL — expected connections via assertion frame slots + relations")
        ok = False
    else:
        print(f"    ✅ PASS — found {len(rows)} connections")

    # Test 2: Expand a frame (assertion case) — should find connected entities via slots
    assertion_frames = [f for f in frames if 'Assertion' in f[2] or 'Meeting' in f[1] or 'Decision' in f[1]]
    if not assertion_frames:
        assertion_frames = frames
    if assertion_frames:
        frame_uri, frame_name, form_type = assertion_frames[0]
        print(f"\n  [Test F.2] Expand frame (assertion): {frame_name}")
        print(f"    Form type: {form_type}")
        result = await client.sparql.execute_sparql_query(space, SPARQLQueryRequest(query=build_expand_query(frame_uri)))
        rows = extract_bindings(result)
        unique_dst = set(get_value(r, 'dstName') for r in rows)
        print(f"    Total: {len(rows)} rows, {len(unique_dst)} unique destinations")
        if verbose:
            for r in rows:
                print(f"      {get_value(r, 'srcName'):30s} → {get_value(r, 'dstName'):30s}  [{get_value(r, 'relationType')}]")
        if len(rows) == 0:
            print("    ❌ FAIL — expected entity slot connections from assertion frame")
            ok = False
        else:
            print(f"    ✅ PASS — found {len(rows)} entity connections from assertion frame")

    return ok


# ---------------------------------------------------------------------------
# Data inspection
# ---------------------------------------------------------------------------

async def inspect_dataset(client: VitalGraphClient, space_id: str, verbose: bool = False):
    """Print a summary of data in a space."""
    print(f"\n  --- Data inspection for {space_id} ---")

    # Entities
    entities = await find_entities(client, space_id, limit=100)
    print(f"  Entities: {len(entities)}")
    if verbose:
        for uri, name in entities[:5]:
            print(f"    {name:40s}  {uri}")

    # Frames
    frames = await find_frames(client, space_id, limit=100)
    aspect_frames = [f for f in frames if 'Aspect' in f[2]]
    assertion_frames = [f for f in frames if 'Assertion' in f[2]]
    other_frames = [f for f in frames if f not in aspect_frames and f not in assertion_frames]
    print(f"  Frames: {len(frames)} total ({len(aspect_frames)} aspect, {len(assertion_frames)} assertion, {len(other_frames)} other)")
    if verbose:
        for uri, name, ft in frames[:5]:
            ft_short = ft.split('#')[-1] if '#' in ft else ft
            print(f"    {name:40s}  {ft_short}")

    # Entity slots
    n_entity_slots = await count_entity_slots(client, space_id)
    print(f"  Entity slots: {n_entity_slots}")

    # Relations
    n_relations = await count_relations(client, space_id)
    print(f"  Relations: {n_relations}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

TESTS = {
    "A": ("graph_viz_a", test_dataset_a),
    "B": ("graph_viz_b", test_dataset_b),
    "C": ("graph_viz_c", test_dataset_c),
    "D": ("graph_viz_d", test_dataset_d),
    "E": ("graph_viz_e", test_dataset_e),
    "F": ("graph_viz_f", test_dataset_f),
}


async def main():
    parser = argparse.ArgumentParser(description="Test graph visualization expand queries")
    parser.add_argument("--dataset", "-d", type=str, default=None,
                        help="Test only this dataset (A-F). Default: all.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show individual row results")
    parser.add_argument("--inspect", "-i", action="store_true",
                        help="Inspect data inventory before testing")
    args = parser.parse_args()

    client = VitalGraphClient()
    await client.open()

    try:
        if args.dataset:
            key = args.dataset.upper()
            if key not in TESTS:
                print(f"Unknown dataset '{key}'. Choose from: {', '.join(TESTS.keys())}")
                sys.exit(1)
            selected = {key: TESTS[key]}
        else:
            selected = TESTS

        results = {}
        for key, (space_id, test_fn) in sorted(selected.items()):
            if args.inspect:
                await inspect_dataset(client, space_id, verbose=args.verbose)
            try:
                results[key] = await test_fn(client, verbose=args.verbose)
            except Exception as e:
                err_msg = str(e)
                if "404" in err_msg or "not found" in err_msg.lower():
                    print(f"\n  ❌ SKIP — space '{space_id}' not found")
                    results[key] = None
                else:
                    print(f"\n  ❌ ERROR — {e}")
                    results[key] = False

        # Summary
        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")
        for key in sorted(results.keys()):
            status = results[key]
            space_id = TESTS[key][0]
            if status is None:
                icon = "⏭️ "
                label = "SKIPPED"
            elif status:
                icon = "✅"
                label = "PASSED"
            else:
                icon = "❌"
                label = "FAILED"
            print(f"  {icon} [{key}] {space_id:20s} {label}")

        passed = sum(1 for v in results.values() if v is True)
        failed = sum(1 for v in results.values() if v is False)
        skipped = sum(1 for v in results.values() if v is None)
        print(f"\n  {passed} passed, {failed} failed, {skipped} skipped")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
