#!/usr/bin/env python3
"""Debug why keyword search returns 0 results for framenet_kgtypes_test."""

import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest

SPACE_ID = "framenet_kgtypes_test"
GRAPH_ID = "urn:vitalgraph:framenet_kgtypes_test:kg_types"


async def main():
    client = VitalGraphClient(token_expiry_seconds=300)
    await client.open()

    # 1. Verify data exists via list
    print("=== Step 1: List types (page_size=3) ===")
    resp = await client.kgtypes.list_kgtypes(SPACE_ID, GRAPH_ID, page_size=3)
    print(f"  Count: {resp.count}")
    if resp.types:
        for t in resp.types[:3]:
            print(f"  - {t.name} ({type(t).__name__})")

    # 2. Try keyword search via client
    print("\n=== Step 2: Keyword search 'Commerce' ===")
    resp2 = await client.kgtypes.search_types(SPACE_ID, GRAPH_ID, query="Commerce", search_mode="keyword")
    print(f"  Success: {resp2.is_success}")
    print(f"  Count: {resp2.count}")
    print(f"  Types: {resp2.types[:3] if resp2.types else 'empty'}")

    # 3. Run raw SPARQL to test CONTAINS
    print("\n=== Step 3: Raw SPARQL with CONTAINS ===")
    sparql = 'PREFIX vc: <http://vital.ai/ontology/vital-core#>\nSELECT ?s ?name WHERE { ?s vc:hasName ?name . FILTER(CONTAINS(LCASE(?name), "commerce")) } LIMIT 5'
    req3 = SPARQLQueryRequest(query=sparql)
    resp3 = await client.execute_sparql_query(SPACE_ID, req3)
    bindings3 = resp3.results.get('bindings', []) if resp3.results else []
    print(f"  Bindings: {len(bindings3)}")
    for b in bindings3[:5]:
        print(f"  - {b.get('name', {}).get('value', '?')}")
    if resp3.error:
        print(f"  ERROR: {resp3.error}")

    # 4. Simple count of all types in this space
    print("\n=== Step 4: Count all subjects with vc:hasName ===")
    sparql2 = 'PREFIX vc: <http://vital.ai/ontology/vital-core#>\nSELECT (COUNT(?s) AS ?cnt) WHERE { ?s vc:hasName ?name . }'
    req4 = SPARQLQueryRequest(query=sparql2)
    resp4 = await client.execute_sparql_query(SPACE_ID, req4)
    bindings4 = resp4.results.get('bindings', []) if resp4.results else []
    if bindings4:
        print(f"  Total with hasName: {bindings4[0].get('cnt', {}).get('value', '?')}")
    if resp4.error:
        print(f"  ERROR: {resp4.error}")

    # 5. Check search endpoint internal SPARQL (type_filter='frame')
    print("\n=== Step 5: Keyword search 'Commerce' type=frame ===")
    resp5 = await client.kgtypes.search_types(SPACE_ID, GRAPH_ID, query="Commerce", type="frame", search_mode="keyword")
    print(f"  Success: {resp5.is_success}")
    print(f"  Count: {resp5.count}")

    # 6. Reproduce exact unfiltered SPARQL from _search_types_keyword
    print("\n=== Step 6: Reproduce unfiltered SPARQL with VALUES ===")
    values = " ".join(
        f"<{u}>" for u in [
            "http://vital.ai/ontology/haley-ai-kg#KGType",
            "http://vital.ai/ontology/haley-ai-kg#KGEntityType",
            "http://vital.ai/ontology/haley-ai-kg#KGFrameType",
            "http://vital.ai/ontology/haley-ai-kg#KGRelationType",
            "http://vital.ai/ontology/haley-ai-kg#KGSlotType",
            "http://vital.ai/ontology/haley-ai-kg#KGSlotRoleType",
        ]
    )
    sparql6 = (
        "PREFIX vc: <http://vital.ai/ontology/vital-core#>\n"
        "SELECT ?s ?name ?vitaltype WHERE {\n"
        f"  ?s vc:vitaltype ?vt . VALUES ?vt {{ {values} }}\n"
        "  ?s vc:vitaltype ?vitaltype .\n"
        '  ?s vc:hasName ?name .\n'
        '  FILTER(CONTAINS(LCASE(?name), "commerce"))\n'
        "} LIMIT 5"
    )
    print(f"  SPARQL:\n{sparql6}")
    req6 = SPARQLQueryRequest(query=sparql6)
    resp6 = await client.execute_sparql_query(SPACE_ID, req6)
    bindings6 = resp6.results.get('bindings', []) if resp6.results else []
    print(f"  Bindings: {len(bindings6)}")
    for b in bindings6[:5]:
        print(f"  - name={b.get('name', {}).get('value', '?')} vitaltype={b.get('vitaltype', {}).get('value', '?')}")
    if resp6.error:
        print(f"  ERROR: {resp6.error}")

    # 7. Try without VALUES — single type filter
    print("\n=== Step 7: Single type filter (KGFrameType) ===")
    sparql7 = (
        "PREFIX vc: <http://vital.ai/ontology/vital-core#>\n"
        "SELECT ?s ?name ?vitaltype WHERE {\n"
        "  ?s vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGFrameType> .\n"
        "  ?s vc:vitaltype ?vitaltype .\n"
        '  ?s vc:hasName ?name .\n'
        '  FILTER(CONTAINS(LCASE(?name), "commerce"))\n'
        "} LIMIT 5"
    )
    req7 = SPARQLQueryRequest(query=sparql7)
    resp7 = await client.execute_sparql_query(SPACE_ID, req7)
    bindings7 = resp7.results.get('bindings', []) if resp7.results else []
    print(f"  Bindings: {len(bindings7)}")
    for b in bindings7[:5]:
        print(f"  - name={b.get('name', {}).get('value', '?')}")
    if resp7.error:
        print(f"  ERROR: {resp7.error}")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
