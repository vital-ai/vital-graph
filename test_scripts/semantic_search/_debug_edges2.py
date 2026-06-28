"""Debug: check Edge_hasKGDocumentSegment objects and their properties."""
import asyncio
from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest

async def main():
    c = VitalGraphClient()
    await c.open()

    # Check if Edge_hasKGDocumentSegment objects exist at all
    q1 = """PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
SELECT (COUNT(?e) AS ?cnt) WHERE {
    GRAPH <urn:semantic_search_test> {
        ?e a haley:Edge_hasKGDocumentSegment .
    }
}"""
    req = SPARQLQueryRequest(query=q1)
    resp = await c.sparql.execute_sparql_query(space_id="sp_semantic_search_test", request=req)
    bindings = resp.results.get("bindings", []) if resp.results else []
    print(f"Edge_hasKGDocumentSegment count: {bindings}")

    # Get a sample edge and all its properties
    q2 = """PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
SELECT ?e ?p ?o WHERE {
    GRAPH <urn:semantic_search_test> {
        ?e a haley:Edge_hasKGDocumentSegment .
        ?e ?p ?o .
    }
} LIMIT 20"""
    req2 = SPARQLQueryRequest(query=q2)
    resp2 = await c.sparql.execute_sparql_query(space_id="sp_semantic_search_test", request=req2)
    bindings2 = resp2.results.get("bindings", []) if resp2.results else []
    print(f"\nSample edge properties: {len(bindings2)} triples")
    for b in bindings2:
        e = b["e"]["value"]
        p = b["p"]["value"]
        o = b["o"]["value"]
        print(f"  {e}")
        print(f"    {p} = {o}")

    # Check for any object with URI containing "edge_to"
    q3 = """SELECT ?s ?p ?o WHERE {
    GRAPH <urn:semantic_search_test> {
        ?s ?p ?o .
        FILTER(CONTAINS(STR(?s), "edge_to"))
    }
} LIMIT 20"""
    req3 = SPARQLQueryRequest(query=q3)
    resp3 = await c.sparql.execute_sparql_query(space_id="sp_semantic_search_test", request=req3)
    bindings3 = resp3.results.get("bindings", []) if resp3.results else []
    print(f"\nObjects with 'edge_to' in URI: {len(bindings3)} triples")
    for b in bindings3:
        s = b["s"]["value"]
        p = b["p"]["value"]
        o = b["o"]["value"]
        print(f"  {s} | {p} | {o}")

    await c.close()

asyncio.run(main())
