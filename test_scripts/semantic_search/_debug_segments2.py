"""Debug: test the SPARQL query directly."""
import asyncio
from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest

async def main():
    c = VitalGraphClient()
    await c.open()

    # Test the exact two-hop query
    q = """PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX vital: <http://vital.ai/ontology/vital-core#>

SELECT DISTINCT ?seg WHERE {
    GRAPH <urn:semantic_search_test> {
        {
            ?e1 vital:hasEdgeSource <urn:semantic_test:doc:tokyo_food_guide> .
            ?e1 vital:hasEdgeDestination ?parent_copy .
            ?parent_copy haley:hasKGDocumentSegmentTypeURI <urn:segtype:segmentation_parent> .
            ?e2 vital:hasEdgeSource ?parent_copy .
            ?e2 vital:hasEdgeDestination ?seg .
            ?seg haley:hasKGDocumentSegmentTypeURI ?segType .
            FILTER(?segType != <urn:segtype:segmentation_parent>)
        } UNION {
            ?e3 vital:hasEdgeSource <urn:semantic_test:doc:tokyo_food_guide> .
            ?e3 vital:hasEdgeDestination ?seg .
            ?seg haley:hasKGDocumentSegmentTypeURI ?segType .
            FILTER(?segType != <urn:segtype:segmentation_parent>)
        }
    }
}
ORDER BY ?seg"""
    req = SPARQLQueryRequest(query=q)
    resp = await c.sparql.execute_sparql_query(space_id="sp_semantic_search_test", request=req)
    bindings = resp.results.get("bindings", []) if resp.results else []
    print(f"Full two-hop query: {len(bindings)} results")
    for b in bindings:
        print(f"  {b['seg']['value']}")

    # Step 1: Can we find the edge from original to parent?
    q2 = """PREFIX vital: <http://vital.ai/ontology/vital-core#>
SELECT ?dest WHERE {
    GRAPH <urn:semantic_search_test> {
        ?e vital:hasEdgeSource <urn:semantic_test:doc:tokyo_food_guide> .
        ?e vital:hasEdgeDestination ?dest .
    }
}"""
    req2 = SPARQLQueryRequest(query=q2)
    resp2 = await c.sparql.execute_sparql_query(space_id="sp_semantic_search_test", request=req2)
    bindings2 = resp2.results.get("bindings", []) if resp2.results else []
    print(f"\nEdges from original: {len(bindings2)}")
    for b in bindings2:
        print(f"  -> {b['dest']['value']}")

    # Step 1a1b: Query by subject URI directly
    q2a1b = """PREFIX vital: <http://vital.ai/ontology/vital-core#>
SELECT ?p ?o WHERE {
    GRAPH <urn:semantic_search_test> {
        <urn:semantic_test:doc:tokyo_food_guide_edge_to_markdown_heading_split_parent> ?p ?o .
    }
}"""
    req2a1b = SPARQLQueryRequest(query=q2a1b)
    resp2a1b = await c.sparql.execute_sparql_query(space_id="sp_semantic_search_test", request=req2a1b)
    bindings2a1b = resp2a1b.results.get("bindings", []) if resp2a1b.results else []
    print(f"\nDirect subject query on edge URI: {len(bindings2a1b)} triples")
    for b in bindings2a1b:
        print(f"  {b['p']['value']} = {b['o']['value']} (type={b['o'].get('type')})")

    # Step 1a1c-pre: One-hop from parent_copy to segments
    q_onehop = """PREFIX vital: <http://vital.ai/ontology/vital-core#>
SELECT ?seg WHERE {
    GRAPH <urn:semantic_search_test> {
        ?e vital:hasEdgeSource <urn:semantic_test:doc:tokyo_food_guide_parent_markdown_heading_split> .
        ?e vital:hasEdgeDestination ?seg .
    }
}"""
    req_oh = SPARQLQueryRequest(query=q_onehop)
    resp_oh = await c.sparql.execute_sparql_query(space_id="sp_semantic_search_test", request=req_oh)
    bindings_oh = resp_oh.results.get("bindings", []) if resp_oh.results else []
    print(f"\nOne-hop from parent_copy: {len(bindings_oh)}")
    for b in bindings_oh:
        print(f"  {b['seg']['value']}")

    # Step 1a1c: Try with FILTER variable binding workaround
    q2a1c = """PREFIX vital: <http://vital.ai/ontology/vital-core#>
SELECT ?e ?dest WHERE {
    GRAPH <urn:semantic_search_test> {
        ?e vital:hasEdgeSource ?src .
        FILTER(?src = <urn:semantic_test:doc:tokyo_food_guide>)
        ?e vital:hasEdgeDestination ?dest .
    }
}"""
    req2a1c = SPARQLQueryRequest(query=q2a1c)
    resp2a1c = await c.sparql.execute_sparql_query(space_id="sp_semantic_search_test", request=req2a1c)
    bindings2a1c = resp2a1c.results.get("bindings", []) if resp2a1c.results else []
    print(f"\nEdges via FILTER workaround: {len(bindings2a1c)}")
    for b in bindings2a1c:
        print(f"  -> {b['dest']['value']}")

    # Step 1a1d: Try STR comparison
    q2a1d = """PREFIX vital: <http://vital.ai/ontology/vital-core#>
SELECT ?e ?dest WHERE {
    GRAPH <urn:semantic_search_test> {
        ?e vital:hasEdgeSource ?src .
        FILTER(STR(?src) = "urn:semantic_test:doc:tokyo_food_guide")
        ?e vital:hasEdgeDestination ?dest .
    }
}"""
    req2a1d = SPARQLQueryRequest(query=q2a1d)
    resp2a1d = await c.sparql.execute_sparql_query(space_id="sp_semantic_search_test", request=req2a1d)
    bindings2a1d = resp2a1d.results.get("bindings", []) if resp2a1d.results else []
    print(f"\nEdges via STR() comparison: {len(bindings2a1d)}")
    for b in bindings2a1d:
        print(f"  -> {b['dest']['value']}")

    # Step 1a2: Try with type constraint (like working code uses)
    q2a2 = """PREFIX vital: <http://vital.ai/ontology/vital-core#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
SELECT ?dest WHERE {
    GRAPH <urn:semantic_search_test> {
        ?e a haley:Edge_hasKGDocumentSegment ;
           vital:hasEdgeSource <urn:semantic_test:doc:tokyo_food_guide> ;
           vital:hasEdgeDestination ?dest .
    }
}"""
    req2a2 = SPARQLQueryRequest(query=q2a2)
    resp2a2 = await c.sparql.execute_sparql_query(space_id="sp_semantic_search_test", request=req2a2)
    bindings2a2 = resp2a2.results.get("bindings", []) if resp2a2.results else []
    print(f"\nEdges from original (with type constraint): {len(bindings2a2)}")
    for b in bindings2a2:
        print(f"  -> {b['dest']['value']}")

    # Step 1b: Check edge source value type
    q2b = """PREFIX vital: <http://vital.ai/ontology/vital-core#>
SELECT ?e ?src WHERE {
    GRAPH <urn:semantic_search_test> {
        ?e vital:hasEdgeSource ?src .
        FILTER(CONTAINS(STR(?e), "tokyo_food_guide_edge"))
    }
} LIMIT 3"""
    req2b = SPARQLQueryRequest(query=q2b)
    resp2b = await c.sparql.execute_sparql_query(space_id="sp_semantic_search_test", request=req2b)
    bindings2b = resp2b.results.get("bindings", []) if resp2b.results else []
    print(f"\nEdge source type info:")
    for b in bindings2b:
        src = b['src']
        print(f"  edge={b['e']['value']}")
        print(f"    src type={src.get('type')}, value={src.get('value')}, datatype={src.get('datatype','')}")

    # Step 1c: Try matching edge source as string literal
    q2c = """PREFIX vital: <http://vital.ai/ontology/vital-core#>
SELECT ?dest WHERE {
    GRAPH <urn:semantic_search_test> {
        ?e vital:hasEdgeSource "urn:semantic_test:doc:tokyo_food_guide" .
        ?e vital:hasEdgeDestination ?dest .
    }
}"""
    req2c = SPARQLQueryRequest(query=q2c)
    resp2c = await c.sparql.execute_sparql_query(space_id="sp_semantic_search_test", request=req2c)
    bindings2c = resp2c.results.get("bindings", []) if resp2c.results else []
    print(f"\nEdges from original (literal match): {len(bindings2c)}")
    for b in bindings2c:
        print(f"  -> {b['dest']['value']}")

    # Step 2: Check what segTypeURI value type is
    q3 = """PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
SELECT ?doc ?segType WHERE {
    GRAPH <urn:semantic_search_test> {
        ?doc haley:hasKGDocumentSegmentTypeURI ?segType .
    }
} LIMIT 5"""
    req3 = SPARQLQueryRequest(query=q3)
    resp3 = await c.sparql.execute_sparql_query(space_id="sp_semantic_search_test", request=req3)
    bindings3 = resp3.results.get("bindings", []) if resp3.results else []
    print(f"\nSegType values (with type info):")
    for b in bindings3:
        seg_type = b['segType']
        print(f"  {b['doc']['value']}: type={seg_type.get('type')}, value={seg_type.get('value')}, datatype={seg_type.get('datatype','')}")

    await c.close()

asyncio.run(main())
