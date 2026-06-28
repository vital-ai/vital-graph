#!/usr/bin/env python3
"""
Debug the exact SPARQL parsing error.
"""

import pyoxigraph as px

def test_exact_sparql_query():
    """Test the exact SPARQL query that's failing."""
    
    # Create a pyoxigraph store
    store = px.Store()
    
    print("🧪 Testing exact SPARQL query from the error")
    print("=" * 60)
    
    # The exact query from the error output
    query = """PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT DISTINCT ?entity ?sort_val_0 WHERE {
            GRAPH <test-graph> {
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
    
    print("🔍 Testing the exact query:")
    print(query[:200] + "...")
    
    try:
        result = store.query(query)
        print("✅ SUCCESS: Query parsed successfully")
        print(f"   Result type: {type(result)}")
    except Exception as e:
        print(f"❌ FAILED: {e}")
        print(f"   Error type: {type(e)}")
        
        # Let's try to identify the exact character position
        lines = query.split('\n')
        print(f"\n🔍 Analyzing error position 7:27 and 7:31:")
        if len(lines) > 6:  # Line 7 (0-indexed is 6)
            line7 = lines[6]
            print(f"   Line 7: '{line7}'")
            if len(line7) > 27:
                print(f"   Char 27: '{line7[26]}'")
            if len(line7) > 31:
                print(f"   Char 31: '{line7[30]}'")
    
    # Test a simpler version
    simple_query = """PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?s WHERE {
    ?s rdf:type haley:KGEntity .
} LIMIT 1"""
    
    print(f"\n🔍 Testing simplified query:")
    try:
        result = store.query(simple_query)
        print("✅ SUCCESS: Simplified query parsed successfully")
    except Exception as e:
        print(f"❌ FAILED: {e}")

if __name__ == "__main__":
    test_exact_sparql_query()
