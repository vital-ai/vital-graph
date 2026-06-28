#!/usr/bin/env python3

import sys
sys.path.append('.')

from test_vitalsigns_query_real import setup_mock_endpoints_with_data

def main():
    print("🔍 Debugging address frame loading...")
    
    # Set up test data
    entity_endpoint, frame_endpoint, space_id, graph_id = setup_mock_endpoints_with_data()
    
    # Get the space from the setup
    space = entity_endpoint.space_manager.get_space(space_id)
    
    # Test 0: Very basic query to see if SPARQL works at all
    query0 = """
    SELECT ?s ?p ?o WHERE {
        ?s ?p ?o .
    } LIMIT 5
    """
    
    print("\n0. Basic SPARQL test (any 5 triples):")
    try:
        results = space.query_sparql(query0)
        print(f"   Query result type: {type(results)}")
        print(f"   Query result keys: {results.keys() if isinstance(results, dict) else 'Not a dict'}")
        if isinstance(results, dict) and 'results' in results:
            bindings = results.get('results', {}).get('bindings', [])
            print(f"   Number of bindings: {len(bindings)}")
            for i, result in enumerate(bindings[:3]):
                s = result.get('s', {}).get('value', 'N/A')
                p = result.get('p', {}).get('value', 'N/A')
                o = result.get('o', {}).get('value', 'N/A')
                print(f"   {i+1}. {s} -> {p} -> {o}")
        else:
            print(f"   Unexpected result format: {results}")
    except Exception as e:
        print(f"   Error in basic query: {e}")
    
    # Test 1: Check if ANY frames with hasKGFrameType exist
    query1 = """
    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
    SELECT ?frame ?type WHERE {
        ?frame haley:hasKGFrameType ?type .
    } LIMIT 10
    """
    
    print("\n1. All frames with hasKGFrameType:")
    try:
        results = space.query_sparql(query1)
        bindings = results.get('results', {}).get('bindings', [])
        print(f"   Found {len(bindings)} frames with hasKGFrameType")
        for result in bindings:
            frame = result.get('frame', {}).get('value', 'N/A')
            frame_type = result.get('type', {}).get('value', 'N/A')
            print(f"   {frame} -> {frame_type}")
    except Exception as e:
        print(f"   Error querying frame types: {e}")
    
    # Test 2: Check if ANY address-related triples exist
    query2 = """
    SELECT ?s ?p ?o WHERE {
        ?s ?p ?o .
        FILTER(CONTAINS(STR(?s), "address") || CONTAINS(STR(?o), "address") || CONTAINS(STR(?p), "address"))
    } LIMIT 10
    """
    
    print("\n2. Any address-related triples:")
    results = space.query_sparql(query2)
    for result in results.get('results', {}).get('bindings', []):
        s = result.get('s', {}).get('value', 'N/A')
        p = result.get('p', {}).get('value', 'N/A')
        o = result.get('o', {}).get('value', 'N/A')
        print(f"   {s} -> {p} -> {o}")
    
    # Test 3: Count total triples
    query3 = """
    SELECT (COUNT(*) as ?count) WHERE {
        ?s ?p ?o .
    }
    """
    
    print("\n3. Total triples in store:")
    results = space.query_sparql(query3)
    for result in results.get('results', {}).get('bindings', []):
        count = result.get('count', {}).get('value', 'N/A')
        print(f"   Total: {count}")

if __name__ == "__main__":
    main()
