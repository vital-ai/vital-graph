#!/usr/bin/env python3
"""
Debug the SPARQL parsing error with proper URI.
"""

import pyoxigraph as px

def test_updated_sparql_query():
    """Test the updated SPARQL query with proper URI."""
    
    # Create a pyoxigraph store
    store = px.Store()
    
    print("🧪 Testing updated SPARQL query with proper URI")
    print("=" * 60)
    
    # The updated query with proper URI
    query = """PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT DISTINCT ?entity ?sort_val_0 WHERE {
            GRAPH <http://example.com/test-graph> {
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
    
    print("🔍 Testing the updated query:")
    
    try:
        result = store.query(query)
        print("✅ SUCCESS: Query parsed successfully")
        print(f"   Result type: {type(result)}")
    except Exception as e:
        print(f"❌ FAILED: {e}")
        print(f"   Error type: {type(e)}")
        
        # Let's try to identify the exact character position
        lines = query.split('\n')
        print(f"\n🔍 Analyzing error position:")
        for i, line in enumerate(lines):
            print(f"   Line {i+1}: '{line}'")
            if i == 6:  # Line 7
                print(f"   >>> This is line 7 where error occurs")
                if len(line) > 27:
                    print(f"   >>> Char 27: '{line[26]}'")

if __name__ == "__main__":
    test_updated_sparql_query()
