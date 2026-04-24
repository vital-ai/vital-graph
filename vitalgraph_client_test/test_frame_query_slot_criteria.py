#!/usr/bin/env python3
"""
Case 1 Test: frame_query with slot_criteria filtering on WordNet.

Tests:
1. Basic frame_query (no filter) — baseline
2. frame_query filtered by frame_type
3. frame_query filtered by slot_criteria (entity slot value)
4. frame_query with frame_type + slot_criteria combined
5. frame_query with non-matching slot_criteria → expect 0 results

Usage:
    /opt/homebrew/anaconda3/envs/vital-graph/bin/python vitalgraph_client_test/test_frame_query_slot_criteria.py
"""
import asyncio, sys, json
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
load_dotenv(project_root / '.env')

import logging
logging.basicConfig(level=logging.WARNING)

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria
from vitalgraph.model.sparql_model import SPARQLQueryRequest

SPACE = "wordnet_frames"
GRAPH = "urn:wordnet_frames"

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}{(' — ' + detail) if detail else ''}")
    else:
        failed += 1
        print(f"  ❌ {name}{(' — ' + detail) if detail else ''}")


async def main():
    global passed, failed

    c = VitalGraphClient()
    await c.open()

    # ── Discovery: find slot types and a sample entity URI in WordNet ──
    print("=== Discovery: WordNet slot types ===")
    resp = await c.sparql.execute_sparql_query(SPACE, SPARQLQueryRequest(query=f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?slot_type (COUNT(*) AS ?cnt) WHERE {{
          GRAPH <{GRAPH}> {{
            ?s a haley:KGEntitySlot .
            ?s haley:hasKGSlotType ?slot_type .
          }}
        }} GROUP BY ?slot_type ORDER BY DESC(?cnt) LIMIT 10
    """))
    bindings = resp.results.get('bindings', []) if resp.results else []
    slot_types = []
    for b in bindings:
        st = b['slot_type']['value']
        cnt = b['cnt']['value']
        slot_types.append(st)
        print(f"  {st.split('#')[-1] if '#' in st else st}  ({cnt})")

    # Pick the most common slot type and find a sample entity value
    if not slot_types:
        print("No entity slots found in WordNet — cannot run slot_criteria tests")
        await c.close()
        return

    target_slot_type = slot_types[0]
    print(f"\nUsing slot_type: {target_slot_type}")

    resp2 = await c.sparql.execute_sparql_query(SPACE, SPARQLQueryRequest(query=f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?entity_val WHERE {{
          GRAPH <{GRAPH}> {{
            ?s a haley:KGEntitySlot .
            ?s haley:hasKGSlotType <{target_slot_type}> .
            ?s haley:hasEntitySlotValue ?entity_val .
          }}
        }} LIMIT 1
    """))
    b2 = resp2.results.get('bindings', []) if resp2.results else []
    if not b2:
        # Try URI slot
        resp2 = await c.sparql.execute_sparql_query(SPACE, SPARQLQueryRequest(query=f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            SELECT ?entity_val WHERE {{
              GRAPH <{GRAPH}> {{
                ?s a haley:KGEntitySlot .
                ?s haley:hasKGSlotType <{target_slot_type}> .
                ?s haley:hasUriSlotValue ?entity_val .
              }}
            }} LIMIT 1
        """))
        b2 = resp2.results.get('bindings', []) if resp2.results else []

    sample_entity = b2[0]['entity_val']['value'] if b2 else None
    print(f"Sample entity value: {sample_entity}")

    # Also discover frame types
    resp3 = await c.sparql.execute_sparql_query(SPACE, SPARQLQueryRequest(query=f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?ft (COUNT(*) AS ?cnt) WHERE {{
          GRAPH <{GRAPH}> {{
            ?f a haley:KGFrame .
            ?f haley:hasKGFrameType ?ft .
          }}
        }} GROUP BY ?ft ORDER BY DESC(?cnt) LIMIT 5
    """))
    b3 = resp3.results.get('bindings', []) if resp3.results else []
    frame_types = [b['ft']['value'] for b in b3]
    for b in b3:
        print(f"  frame_type: {b['ft']['value'].split('#')[-1] if '#' in b['ft']['value'] else b['ft']['value']}  ({b['cnt']['value']})")

    target_frame_type = frame_types[0] if frame_types else None
    print(f"\nUsing frame_type: {target_frame_type}")

    # ── Test 1: Basic frame_query (no filters) ──
    print("\n=== Test 1: Basic frame_query (no filters) ===")
    r1 = await c.kgqueries.query_frames(
        space_id=SPACE, graph_id=GRAPH, page_size=5, offset=0
    )
    check("returns frames", r1.results and len(r1.results) > 0,
          f"{len(r1.results or [])} frames, total={r1.total_count}")

    # ── Test 2: frame_query filtered by frame_type ──
    print("\n=== Test 2: frame_query with frame_type filter ===")
    if target_frame_type:
        r2 = await c.kgqueries.query_frames(
            space_id=SPACE, graph_id=GRAPH,
            frame_type=target_frame_type,
            page_size=5, offset=0
        )
        check("returns frames", r2.results and len(r2.results) > 0,
              f"{len(r2.results or [])} frames, total={r2.total_count}")
        check("total_count <= unfiltered", r2.total_count <= r1.total_count,
              f"{r2.total_count} <= {r1.total_count}")
        if r2.results:
            all_match_type = all(fr.frame_type_uri == target_frame_type for fr in r2.results)
            check("all frame_type_uri match", all_match_type)
    else:
        print("  ⚠️  No frame types found, skipping")

    # ── Test 3: frame_query with slot_criteria (entity slot value eq) ──
    print("\n=== Test 3: frame_query with slot_criteria ===")
    if sample_entity:
        r3 = await c.kgqueries.query_frames(
            space_id=SPACE, graph_id=GRAPH,
            slot_criteria=[SlotCriteria(
                slot_type=target_slot_type,
                slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGEntitySlot",
                value=sample_entity,
                comparator="eq"
            )],
            page_size=5, offset=0
        )
        check("returns frames", r3.results and len(r3.results) > 0,
              f"{len(r3.results or [])} frames, total={r3.total_count}")
        check("total_count <= unfiltered", r3.total_count <= r1.total_count,
              f"{r3.total_count} <= {r1.total_count}")
        # Each returned frame should have an entity_ref matching sample_entity
        if r3.results:
            frames_with_match = 0
            for fr in r3.results:
                if any(er.entity_uri == sample_entity for er in fr.entity_refs):
                    frames_with_match += 1
            check("entity_refs contain matching entity",
                  frames_with_match > 0,
                  f"{frames_with_match}/{len(r3.results)} frames have matching ref")
    else:
        print("  ⚠️  No sample entity found, skipping")

    # ── Test 4: frame_query with frame_type + slot_criteria combined ──
    print("\n=== Test 4: frame_type + slot_criteria combined ===")
    if target_frame_type and sample_entity:
        r4 = await c.kgqueries.query_frames(
            space_id=SPACE, graph_id=GRAPH,
            frame_type=target_frame_type,
            slot_criteria=[SlotCriteria(
                slot_type=target_slot_type,
                slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGEntitySlot",
                value=sample_entity,
                comparator="eq"
            )],
            page_size=5, offset=0
        )
        check("query succeeds", r4.total_count is not None,
              f"{len(r4.results)} frames, total={r4.total_count}")
        check("total_count <= slot-only",
              r4.total_count <= (r3.total_count if sample_entity else r1.total_count),
              f"{r4.total_count} <= {r3.total_count if sample_entity else r1.total_count}")
    else:
        print("  ⚠️  Missing frame_type or entity, skipping")

    # ── Test 5: non-matching slot_criteria → 0 results ──
    print("\n=== Test 5: non-matching slot_criteria → 0 results ===")
    r5 = await c.kgqueries.query_frames(
        space_id=SPACE, graph_id=GRAPH,
        slot_criteria=[SlotCriteria(
            slot_type="http://nonexistent.type/NoSuchSlot",
            value="http://nonexistent.entity/nothing",
            comparator="eq"
        )],
        page_size=5, offset=0
    )
    check("returns 0 results", r5.total_count == 0,
          f"total_count={r5.total_count}")

    # ── Summary ──
    total = passed + failed
    print(f"\n{'='*60}")
    print(f"Case 1 Slot Criteria Tests: {passed}/{total} passed")
    print(f"{'='*60}")

    await c.close()


if __name__ == "__main__":
    asyncio.run(main())
