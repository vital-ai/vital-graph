#!/usr/bin/env python3
"""
Test the exact SPARQL query that's failing to identify the parsing error.
"""

import pyoxigraph as px

def test_exact_failing_query():
    """Test the exact SPARQL query that's failing."""
    
    print("🧪 Testing the exact failing SPARQL query")
    print("=" * 60)
    
    # Create a pyoxigraph store
    store = px.Store()
    
    # The exact query from the error output
    failing_query = """PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT DISTINCT ?entity ?sort_val_0 WHERE {
            GRAPH <None> {
                ?entity rdf:type haley:KGEntity .
                ?entity vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#CustomerEntity> .
                {
                ?entity rdfs:label ?label .
                FILTER(CONTAINS(LCASE(?label), LCASE("Premium")))
            } UNION {
                ?entity vital-core:name ?name .
                FILTER(CONTAINS(LCASE(?name), LCASE("Premium")))
            }
                ?entity <http://vital.ai/ontology/vital-core#name> ?sort_val_0 .
            }
        }
        ORDER BY ASC(?sort_val_0)
        LIMIT 10
        OFFSET 0"""
    
    print("🔍 Testing the failing query:")
    try:
        result = store.query(failing_query)
        print("✅ SUCCESS: Query parsed successfully")
    except Exception as e:
        print(f"❌ FAILED: {e}")
        
        # Let's analyze the exact position
        lines = failing_query.split('\n')
        print(f"\n🔍 Analyzing error position 7:25:")
        for i, line in enumerate(lines):
            print(f"   Line {i+1}: '{line}'")
            if i == 6:  # Line 7 (0-indexed is 6)
                print(f"   >>> This is line 7 where error occurs")
                print(f"   >>> Length: {len(line)}")
                if len(line) > 25:
                    print(f"   >>> Char 25: '{line[24]}'")
                    print(f"   >>> Around char 25: '{line[20:30]}'")
    
    # Test without GRAPH clause
    print(f"\n🔍 Testing without GRAPH clause:")
    query_no_graph = """PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT DISTINCT ?entity ?sort_val_0 WHERE {
            ?entity rdf:type haley:KGEntity .
            ?entity vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#CustomerEntity> .
            {
            ?entity rdfs:label ?label .
            FILTER(CONTAINS(LCASE(?label), LCASE("Premium")))
        } UNION {
            ?entity vital-core:name ?name .
            FILTER(CONTAINS(LCASE(?name), LCASE("Premium")))
        }
            ?entity <http://vital.ai/ontology/vital-core#name> ?sort_val_0 .
        }
        ORDER BY ASC(?sort_val_0)
        LIMIT 10
        OFFSET 0"""
    
    try:
        result = store.query(query_no_graph)
        print("✅ SUCCESS: Query without GRAPH parsed successfully")
    except Exception as e:
        print(f"❌ FAILED: {e}")

if __name__ == "__main__":
    test_exact_failing_query()
