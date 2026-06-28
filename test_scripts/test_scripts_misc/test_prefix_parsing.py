#!/usr/bin/env python3
"""
Test to confirm whether vital-core prefix causes SPARQL parsing errors in pyoxigraph.
"""

import pyoxigraph as px

def test_vital_core_prefix():
    """Test if vital-core prefix causes parsing errors in pyoxigraph."""
    
    # Create a pyoxigraph store
    store = px.Store()
    
    print("🧪 Testing SPARQL prefix parsing with pyoxigraph")
    print("=" * 60)
    
    # Test 1: Query with vital-core prefix (hyphenated)
    query_with_hyphen = """
    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
    PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    
    SELECT ?s ?p ?o WHERE {
        ?s rdf:type haley:KGEntity .
        ?s vital-core:vitaltype ?o .
    } LIMIT 1
    """
    
    print("\n🔍 Test 1: Query with vital-core prefix (hyphenated)")
    try:
        result = store.query(query_with_hyphen)
        print("✅ SUCCESS: vital-core prefix parsed successfully")
        print(f"   Result type: {type(result)}")
    except Exception as e:
        print(f"❌ FAILED: {e}")
        print(f"   Error type: {type(e)}")
    
    # Test 2: Query with vital prefix (no hyphen)
    query_without_hyphen = """
    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
    PREFIX vital: <http://vital.ai/ontology/vital-core#>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    
    SELECT ?s ?p ?o WHERE {
        ?s rdf:type haley:KGEntity .
        ?s vital:vitaltype ?o .
    } LIMIT 1
    """
    
    print("\n🔍 Test 2: Query with vital prefix (no hyphen)")
    try:
        result = store.query(query_without_hyphen)
        print("✅ SUCCESS: vital prefix parsed successfully")
        print(f"   Result type: {type(result)}")
    except Exception as e:
        print(f"❌ FAILED: {e}")
        print(f"   Error type: {type(e)}")
    
    # Test 3: Query with other hyphenated prefix
    query_other_hyphen = """
    PREFIX test-prefix: <http://example.org/test#>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    
    SELECT ?s ?p ?o WHERE {
        ?s rdf:type test-prefix:TestClass .
    } LIMIT 1
    """
    
    print("\n🔍 Test 3: Query with test-prefix (other hyphenated prefix)")
    try:
        result = store.query(query_other_hyphen)
        print("✅ SUCCESS: test-prefix parsed successfully")
        print(f"   Result type: {type(result)}")
    except Exception as e:
        print(f"❌ FAILED: {e}")
        print(f"   Error type: {type(e)}")
    
    # Test 4: Minimal query to isolate the issue
    minimal_query = """
    PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
    SELECT ?s WHERE { ?s ?p ?o } LIMIT 1
    """
    
    print("\n🔍 Test 4: Minimal query with vital-core prefix")
    try:
        result = store.query(minimal_query)
        print("✅ SUCCESS: Minimal vital-core query parsed successfully")
        print(f"   Result type: {type(result)}")
    except Exception as e:
        print(f"❌ FAILED: {e}")
        print(f"   Error type: {type(e)}")
        
    print("\n" + "=" * 60)
    print("🏁 Test completed")

if __name__ == "__main__":
    test_vital_core_prefix()
