#!/usr/bin/env python3

"""Test grouping URI-based SPARQL queries functionality."""

import sys
import os

# Add the parent directory to the path so we can import vitalgraph
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vitalgraph.sparql.grouping_uri_queries import GroupingURIQueryBuilder, GroupingURIGraphRetriever


def test_query_builder():
    """Test SPARQL query building for grouping URIs."""
    
    print("=== Testing Grouping URI Query Builder ===")
    
    builder = GroupingURIQueryBuilder()
    entity_uri = "http://example.org/entity1"
    frame_uri = "http://example.org/frame1"
    graph_id = "http://example.org/graph1"
    
    # Test entity graph subjects query
    entity_subjects_query = builder.build_entity_graph_subjects_query(entity_uri, graph_id)
    if "hasKGGraphURI" in entity_subjects_query and entity_uri in entity_subjects_query:
        print("✅ Entity graph subjects query built correctly")
    else:
        print("❌ Entity graph subjects query missing key components")
        return False
    
    # Test frame graph subjects query
    frame_subjects_query = builder.build_frame_graph_subjects_query(frame_uri, graph_id)
    if "hasFrameGraphURI" in frame_subjects_query and frame_uri in frame_subjects_query:
        print("✅ Frame graph subjects query built correctly")
    else:
        print("❌ Frame graph subjects query missing key components")
        return False
    
    # Test complete entity graph query
    complete_entity_query = builder.build_complete_entity_graph_query(entity_uri, graph_id)
    if all(term in complete_entity_query for term in ["hasKGGraphURI", entity_uri, "?subject ?predicate ?object"]):
        print("✅ Complete entity graph query built correctly")
    else:
        print("❌ Complete entity graph query missing key components")
        return False
    
    # Test complete frame graph query
    complete_frame_query = builder.build_complete_frame_graph_query(frame_uri, graph_id)
    if all(term in complete_frame_query for term in ["hasFrameGraphURI", frame_uri, "?subject ?predicate ?object"]):
        print("✅ Complete frame graph query built correctly")
    else:
        print("❌ Complete frame graph query missing key components")
        return False
    
    return True


def test_components_by_type_queries():
    """Test queries that group components by type."""
    
    print("\n=== Testing Components by Type Queries ===")
    
    builder = GroupingURIQueryBuilder()
    entity_uri = "http://example.org/entity1"
    frame_uri = "http://example.org/frame1"
    graph_id = "http://example.org/graph1"
    
    # Test entity components by type query
    entity_components_query = builder.build_entity_components_by_type_query(entity_uri, graph_id)
    expected_types = ["KGEntity", "KGFrame", "KGSlot", "hasSlot"]
    
    if all(type_name in entity_components_query for type_name in expected_types):
        print("✅ Entity components by type query includes all expected types")
    else:
        print("❌ Entity components by type query missing expected types")
        return False
    
    # Test frame components by type query
    frame_components_query = builder.build_frame_components_by_type_query(frame_uri, graph_id)
    expected_frame_types = ["KGFrame", "KGSlot", "hasSlot"]
    
    if all(type_name in frame_components_query for type_name in expected_frame_types):
        print("✅ Frame components by type query includes all expected types")
    else:
        print("❌ Frame components by type query missing expected types")
        return False
    
    return True


def test_graph_retriever():
    """Test the graph retriever functionality."""
    
    print("\n=== Testing Graph Retriever ===")
    
    retriever = GroupingURIGraphRetriever()
    
    # Mock SPARQL executor
    def mock_sparql_executor(query):
        """Mock SPARQL executor that returns sample results."""
        if "hasKGGraphURI" in query:
            return [
                {'subject': 'http://example.org/entity1', 'predicate': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'object': 'http://vital.ai/ontology/haley-ai-kg#KGEntity'},
                {'subject': 'http://example.org/frame1', 'predicate': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'object': 'http://vital.ai/ontology/haley-ai-kg#KGFrame'},
                {'subject': 'http://example.org/slot1', 'predicate': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'object': 'http://vital.ai/ontology/haley-ai-kg#KGSlot'}
            ]
        elif "hasFrameGraphURI" in query:
            return [
                {'subject': 'http://example.org/frame1', 'predicate': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'object': 'http://vital.ai/ontology/haley-ai-kg#KGFrame'},
                {'subject': 'http://example.org/slot1', 'predicate': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'object': 'http://vital.ai/ontology/haley-ai-kg#KGSlot'}
            ]
        else:
            return []
    
    # Test entity graph retrieval
    entity_triples = retriever.get_entity_graph_triples(
        "http://example.org/entity1", 
        "http://example.org/graph1", 
        mock_sparql_executor
    )
    
    if len(entity_triples) == 3 and all('subject' in triple for triple in entity_triples):
        print("✅ Entity graph triples retrieved correctly")
    else:
        print("❌ Entity graph triples retrieval failed")
        return False
    
    # Test frame graph retrieval
    frame_triples = retriever.get_frame_graph_triples(
        "http://example.org/frame1",
        "http://example.org/graph1",
        mock_sparql_executor
    )
    
    if len(frame_triples) == 2 and all('subject' in triple for triple in frame_triples):
        print("✅ Frame graph triples retrieved correctly")
    else:
        print("❌ Frame graph triples retrieval failed")
        return False
    
    return True


def test_query_structure():
    """Test the structure and syntax of generated queries."""
    
    print("\n=== Testing Query Structure ===")
    
    builder = GroupingURIQueryBuilder()
    
    # Test that queries have proper SPARQL structure
    query = builder.build_complete_entity_graph_query("http://example.org/entity1", "http://example.org/graph1")
    
    required_sparql_elements = [
        "SELECT",
        "WHERE",
        "GRAPH",
        "DISTINCT",
        "?subject",
        "?predicate", 
        "?object"
    ]
    
    if all(element in query for element in required_sparql_elements):
        print("✅ Query has proper SPARQL structure")
    else:
        print("❌ Query missing required SPARQL elements")
        return False
    
    # Test proper URI formatting
    if "<http://example.org/entity1>" in query and "<http://example.org/graph1>" in query:
        print("✅ URIs properly formatted in angle brackets")
    else:
        print("❌ URIs not properly formatted")
        return False
    
    return True


def test_haley_prefix():
    """Test that Haley ontology prefix is used correctly."""
    
    print("\n=== Testing Haley Ontology Prefix ===")
    
    builder = GroupingURIQueryBuilder()
    
    expected_prefix = "http://vital.ai/ontology/haley-ai-kg#"
    if builder.haley_prefix == expected_prefix:
        print("✅ Haley prefix set correctly")
    else:
        print(f"❌ Haley prefix incorrect: {builder.haley_prefix}")
        return False
    
    # Test prefix usage in queries
    query = builder.build_entity_graph_subjects_query("http://example.org/entity1", "http://example.org/graph1")
    if f"<{expected_prefix}hasKGGraphURI>" in query:
        print("✅ Haley prefix used correctly in queries")
    else:
        print("❌ Haley prefix not used correctly in queries")
        return False
    
    return True


def main():
    """Run all tests."""
    
    print("🧪 Testing Grouping URI SPARQL Queries")
    print("=" * 50)
    
    tests = [
        test_query_builder,
        test_components_by_type_queries,
        test_graph_retriever,
        test_query_structure,
        test_haley_prefix
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ Test {test.__name__} crashed: {e}")
            failed += 1
    
    print("\n" + "=" * 50)
    print("📊 SPARQL QUERY TEST RESULTS")
    print("=" * 50)
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")
    print(f"📈 Total: {passed + failed}")
    
    if failed == 0:
        print("\n🎉 All SPARQL query tests passed! Grouping URI queries work correctly.")
        print("\n📋 Key Features Tested:")
        print("• Entity graph retrieval using hasKGGraphURI")
        print("• Frame graph retrieval using hasFrameGraphURI") 
        print("• Component type grouping queries")
        print("• Proper SPARQL syntax and structure")
        print("• Haley ontology prefix usage")
        return 0
    else:
        print(f"\n💥 {failed} SPARQL query test(s) failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
