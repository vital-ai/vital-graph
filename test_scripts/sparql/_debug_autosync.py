#!/usr/bin/env python3
"""Quick debug: create KGFrameType, search for it, cleanup."""
import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from ai_haley_kg_domain.model.KGFrameType import KGFrameType

SPACE_ID = 'framenet_kgtypes_test'
GRAPH_ID = 'urn:vitalgraph:framenet_kgtypes_test:kg_types'


async def main():
    client = VitalGraphClient(token_expiry_seconds=300)
    await client.open()

    ft = KGFrameType()
    ft.URI = 'http://vital.ai/test/autosync/TestDebugFrame'
    ft.name = 'TestDebugFrame'
    ft.kGraphDescription = 'Debug test frame for auto-sync'

    resp = await client.kgtypes.create_kgtypes(
        space_id=SPACE_ID, graph_id=GRAPH_ID, objects=[ft],
    )
    print(f"Create: success={resp.is_success}")
    if hasattr(resp, 'created_uris'):
        print(f"  created_uris={resp.created_uris}")
    if hasattr(resp, 'message'):
        print(f"  message={resp.message}")

    time.sleep(2)

    # Keyword search
    sr = await client.kgtypes.search_types(
        SPACE_ID, GRAPH_ID, query='TestDebugFrame', search_mode='keyword',
    )
    names = []
    if hasattr(sr, 'types') and sr.types:
        for t in sr.types:
            if isinstance(t, dict):
                names.append(t.get('name', ''))
            else:
                names.append(getattr(t, 'name', ''))
    print(f"Keyword search: count={sr.count}, names={names[:5]}")

    # Also try SPARQL queries to see if the data is there
    from vitalgraph.model.sparql_model import SPARQLQueryRequest

    # Test 1: With default_graph_uri
    sparql = f"""
PREFIX vc: <http://vital.ai/ontology/vital-core#>
SELECT ?s ?name ?vt WHERE {{
  ?s vc:hasName ?name .
  ?s vc:vitaltype ?vt .
  FILTER(?name = "TestDebugFrame")
}}
LIMIT 10
"""
    sq_resp = await client.sparql.execute_sparql_query(SPACE_ID, SPARQLQueryRequest(
        query=sparql.strip(), default_graph_uri=[GRAPH_ID],
    ))
    bindings = []
    if sq_resp.results and isinstance(sq_resp.results, dict):
        bindings = sq_resp.results.get('bindings', [])
    print(f"SPARQL with default_graph_uri: {len(bindings)} bindings")
    for b in bindings:
        print(f"  s={b.get('s', {}).get('value', '')}, "
              f"name={b.get('name', {}).get('value', '')}, "
              f"vt={b.get('vt', {}).get('value', '')}")

    # Test 2: Without default_graph_uri (like keyword search does)
    sq_resp2 = await client.sparql.execute_sparql_query(SPACE_ID, SPARQLQueryRequest(
        query=sparql.strip(),
    ))
    bindings2 = []
    if sq_resp2.results and isinstance(sq_resp2.results, dict):
        bindings2 = sq_resp2.results.get('bindings', [])
    print(f"SPARQL without default_graph_uri: {len(bindings2)} bindings")

    # Test 3: With explicit GRAPH clause
    sparql_graph = f"""
PREFIX vc: <http://vital.ai/ontology/vital-core#>
SELECT ?s ?name ?vt WHERE {{
  GRAPH <{GRAPH_ID}> {{
    ?s vc:hasName ?name .
    ?s vc:vitaltype ?vt .
    FILTER(?name = "TestDebugFrame")
  }}
}}
LIMIT 10
"""
    sq_resp3 = await client.sparql.execute_sparql_query(SPACE_ID, SPARQLQueryRequest(
        query=sparql_graph.strip(),
    ))
    bindings3 = []
    if sq_resp3.results and isinstance(sq_resp3.results, dict):
        bindings3 = sq_resp3.results.get('bindings', [])
    print(f"SPARQL with GRAPH clause: {len(bindings3)} bindings")

    # Test 4: Exact keyword search SPARQL (matches _search_types_keyword)
    type_values = ' '.join([
        '<http://vital.ai/ontology/haley-ai-kg#KGType>',
        '<http://vital.ai/ontology/haley-ai-kg#KGEntityType>',
        '<http://vital.ai/ontology/haley-ai-kg#KGFrameType>',
        '<http://vital.ai/ontology/haley-ai-kg#KGSlotType>',
        '<http://vital.ai/ontology/haley-ai-kg#KGRelationType>',
    ])
    kw_sparql = f"""
PREFIX vc: <http://vital.ai/ontology/vital-core#>

SELECT ?s ?name ?vitaltype ?description WHERE {{
  ?s vc:vitaltype ?vitaltype .
  VALUES ?vitaltype {{ {type_values} }}
  ?s vc:hasName ?name .
  OPTIONAL {{ ?s <http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription> ?description . }}
  FILTER(
    CONTAINS(LCASE(?name), LCASE("TestDebugFrame"))
    || CONTAINS(LCASE(COALESCE(?description, "")), LCASE("TestDebugFrame"))
  )
}}
ORDER BY ?name
LIMIT 100
"""
    sq_resp4 = await client.sparql.execute_sparql_query(SPACE_ID, SPARQLQueryRequest(
        query=kw_sparql.strip(),
    ))
    bindings4 = []
    if sq_resp4.results and isinstance(sq_resp4.results, dict):
        bindings4 = sq_resp4.results.get('bindings', [])
    print(f"SPARQL keyword-style query: {len(bindings4)} bindings")
    for b in bindings4:
        print(f"  s={b.get('s', {}).get('value', '')}, name={b.get('name', {}).get('value', '')}")

    # Test 5: Without VALUES, explicit type filter
    kw_sparql5 = f"""
PREFIX vc: <http://vital.ai/ontology/vital-core#>
SELECT ?s ?name ?vitaltype WHERE {{
  ?s vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGFrameType> .
  ?s vc:hasName ?name .
  FILTER(CONTAINS(LCASE(?name), LCASE("TestDebugFrame")))
}}
LIMIT 10
"""
    sq_resp5 = await client.sparql.execute_sparql_query(SPACE_ID, SPARQLQueryRequest(
        query=kw_sparql5.strip(),
    ))
    bindings5 = []
    if sq_resp5.results and isinstance(sq_resp5.results, dict):
        bindings5 = sq_resp5.results.get('bindings', [])
    print(f"SPARQL no VALUES, explicit type: {len(bindings5)} bindings")

    # Test 6: VALUES but no FILTER
    kw_sparql6 = f"""
PREFIX vc: <http://vital.ai/ontology/vital-core#>
SELECT ?s ?name ?vitaltype WHERE {{
  ?s vc:vitaltype ?vitaltype .
  VALUES ?vitaltype {{ <http://vital.ai/ontology/haley-ai-kg#KGFrameType> }}
  ?s vc:hasName ?name .
  FILTER(?name = "TestDebugFrame")
}}
LIMIT 10
"""
    sq_resp6 = await client.sparql.execute_sparql_query(SPACE_ID, SPARQLQueryRequest(
        query=kw_sparql6.strip(),
    ))
    bindings6 = []
    if sq_resp6.results and isinstance(sq_resp6.results, dict):
        bindings6 = sq_resp6.results.get('bindings', [])
    print(f"SPARQL VALUES + exact match: {len(bindings6)} bindings")

    # Cleanup
    try:
        await client.kgtypes.delete_kgtype(
            space_id=SPACE_ID, graph_id=GRAPH_ID, uri=ft.URI,
        )
        print("Cleanup: deleted")
    except Exception as e:
        print(f"Cleanup error: {e}")

    await client.close()


if __name__ == '__main__':
    asyncio.run(main())
