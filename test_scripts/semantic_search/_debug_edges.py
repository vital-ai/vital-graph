"""Quick debug: check edges from parent copies."""
import asyncio
from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest

async def main():
    c = VitalGraphClient()
    await c.open()
    query = """PREFIX vital: <http://vital.ai/ontology/vital-core#>
SELECT ?src ?dst WHERE {
    GRAPH <urn:semantic_search_test> {
        ?edge vital:hasEdgeSource ?src .
        ?edge vital:hasEdgeDestination ?dst .
        FILTER(CONTAINS(STR(?src), "parent"))
    }
} LIMIT 10"""
    req = SPARQLQueryRequest(query=query)
    resp = await c.sparql.execute_sparql_query(space_id="sp_semantic_search_test", request=req)
    bindings = resp.results.get("bindings", []) if resp.results else []
    print(f"Edges from parent copies: {len(bindings)}")
    for b in bindings:
        src = b["src"]["value"]
        dst = b["dst"]["value"]
        print(f"  {src} -> {dst}")

    # Check all edges involving 'tokyo'
    query2 = """PREFIX vital: <http://vital.ai/ontology/vital-core#>
SELECT ?edge ?src ?dst WHERE {
    GRAPH <urn:semantic_search_test> {
        ?edge vital:hasEdgeSource ?src .
        ?edge vital:hasEdgeDestination ?dst .
        FILTER(CONTAINS(STR(?src), "tokyo") || CONTAINS(STR(?dst), "tokyo"))
    }
} LIMIT 10"""
    req2 = SPARQLQueryRequest(query=query2)
    resp2 = await c.sparql.execute_sparql_query(space_id="sp_semantic_search_test", request=req2)
    bindings2 = resp2.results.get("bindings", []) if resp2.results else []
    print(f"\nEdges involving 'tokyo': {len(bindings2)}")
    for b in bindings2:
        src = b["src"]["value"]
        dst = b["dst"]["value"]
        edge = b["edge"]["value"]
        print(f"  {edge}")
        print(f"    {src} -> {dst}")

    # Sample 5 random edges
    query3 = """PREFIX vital: <http://vital.ai/ontology/vital-core#>
SELECT ?edge ?src ?dst WHERE {
    GRAPH <urn:semantic_search_test> {
        ?edge vital:hasEdgeSource ?src .
        ?edge vital:hasEdgeDestination ?dst .
    }
} LIMIT 5"""
    req3 = SPARQLQueryRequest(query=query3)
    resp3 = await c.sparql.execute_sparql_query(space_id="sp_semantic_search_test", request=req3)
    bindings3 = resp3.results.get("bindings", []) if resp3.results else []
    print(f"\nSample edges: {len(bindings3)}")
    for b in bindings3:
        src = b["src"]["value"]
        dst = b["dst"]["value"]
        edge = b["edge"]["value"]
        print(f"  {edge}: {src} -> {dst}")

    await c.close()

asyncio.run(main())
