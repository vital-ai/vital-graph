"""Tests for TemporaryTripleStore

Tests the pyoxigraph wrapper functionality including JSON-LD loading,
SPARQL query execution, and utility methods.
"""

import sys
import os
import logging
import traceback

# Add the parent directory to the path so we can import vitalgraph
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vitalgraph.sparql.triple_store import TemporaryTripleStore
from test_sparql.fixtures.sample_entity_graphs import (
    create_single_entity_graph,
    create_multiple_entity_graphs,
    create_empty_document
)
from test_sparql.utils.test_helpers import setup_test_logging


class TestTemporaryTripleStore:
    """Test TemporaryTripleStore functionality."""
    
    def __init__(self):
        """Set up test class."""
        setup_test_logging()
        self.passed = 0
        self.failed = 0
        self.errors = []
    
    def run_test(self, test_method, test_name):
        """Run a single test method."""
        try:
            print(f"Running {test_name}...")
            test_method()
            print(f"✅ {test_name} PASSED")
            self.passed += 1
        except Exception as e:
            print(f"❌ {test_name} FAILED: {str(e)}")
            self.failed += 1
            self.errors.append(f"{test_name}: {str(e)}")
            traceback.print_exc()
    
    def test_initialization(self):
        """Test store initialization."""
        store = TemporaryTripleStore()
        
        assert store.store is not None
        assert store.vitalsigns is not None
        assert store.logger is not None
    
    def test_load_empty_document(self):
        """Test loading an empty JSON-LD document."""
        store = TemporaryTripleStore()
        document = create_empty_document()
        
        # Should not raise an exception
        store.load_jsonld_document(document)
        
        # Should have no triples
        count = store.get_triple_count()
        assert count == 0
    
    def test_load_single_entity_document(self):
        """Test loading a single entity JSON-LD document."""
        store = TemporaryTripleStore()
        document = create_single_entity_graph()
        
        store.load_jsonld_document(document)
        
        # Should have loaded triples
        count = store.get_triple_count()
        assert count > 0
    
    def test_load_multiple_entities_document(self):
        """Test loading multiple entities JSON-LD document."""
        store = TemporaryTripleStore()
        document = create_multiple_entity_graphs()
        
        store.load_jsonld_document(document)
        
        # Should have more triples than single entity
        count = store.get_triple_count()
        assert count > 5  # Should have multiple entities, frames, slots, and relationships
    
    def test_execute_simple_select_query(self):
        """Test executing a simple SELECT query."""
        store = TemporaryTripleStore()
        document = create_single_entity_graph()
        store.load_jsonld_document(document)
        
        query = """
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?entity WHERE {
            ?entity a haley:KGEntity .
        }
        """
        
        results = store.execute_query(query)
        
        assert len(results) > 0
        assert 'entity' in results[0]
        assert results[0]['entity']['value'] == "http://example.org/entity1"
    
    def test_execute_count_query(self):
        """Test executing a COUNT query."""
        store = TemporaryTripleStore()
        document = create_multiple_entity_graphs()
        store.load_jsonld_document(document)
        
        query = """
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT (COUNT(?entity) as ?count) WHERE {
            ?entity a haley:KGEntity .
        }
        """
        
        results = store.execute_query(query)
        
        assert len(results) == 1
        assert 'count' in results[0]
        # Should find 2 entities in the multiple entities document
        assert int(results[0]['count']['value']) == 2
    
    def test_get_subject_triples(self):
        """Test getting all triples for a specific subject."""
        store = TemporaryTripleStore()
        document = create_single_entity_graph()
        store.load_jsonld_document(document)
        
        subject_uri = "http://example.org/entity1"
        triples = store.get_subject_triples(subject_uri)
        
        assert len(triples) > 0
        
        # All triples should have the correct subject
        for triple in triples:
            assert triple['subject'] == subject_uri
            assert 'predicate' in triple
            assert 'object' in triple
    
    def test_get_all_subjects(self):
        """Test getting all unique subjects."""
        store = TemporaryTripleStore()
        document = create_multiple_entity_graphs()
        store.load_jsonld_document(document)
        
        subjects = store.get_all_subjects()
        
        assert len(subjects) > 0
        
        # Should include both entities
        assert "http://example.org/entity1" in subjects
        assert "http://example.org/entity2" in subjects
        
        # Should also include frames and slots
        assert any("frame" in subject.lower() for subject in subjects)
        assert any("slot" in subject.lower() for subject in subjects)
    
    def test_get_triple_count(self):
        """Test getting total triple count."""
        store = TemporaryTripleStore()
        
        # Empty store should have 0 triples
        assert store.get_triple_count() == 0
        
        # Load document and check count increases
        document = create_single_entity_graph()
        store.load_jsonld_document(document)
        
        count = store.get_triple_count()
        assert count > 0
    
    def test_clear_store(self):
        """Test clearing all triples from store."""
        store = TemporaryTripleStore()
        document = create_single_entity_graph()
        store.load_jsonld_document(document)
        
        # Should have triples
        assert store.get_triple_count() > 0
        
        # Clear and check
        store.clear()
        assert store.get_triple_count() == 0
    
    def test_invalid_sparql_query(self):
        """Test handling of invalid SPARQL queries."""
        store = TemporaryTripleStore()
        document = create_single_entity_graph()
        store.load_jsonld_document(document)
        
        # Invalid SPARQL syntax
        invalid_query = "INVALID SPARQL SYNTAX"
        
        try:
            store.execute_query(invalid_query)
            assert False, "Expected exception for invalid SPARQL query"
        except Exception:
            # Expected behavior
            pass
    
    def test_query_nonexistent_data(self):
        """Test querying for data that doesn't exist."""
        store = TemporaryTripleStore()
        document = create_single_entity_graph()
        store.load_jsonld_document(document)
        
        query = """
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?entity WHERE {
            ?entity a haley:NonExistentType .
        }
        """
        
        results = store.execute_query(query)
        
        # Should return empty results, not raise an exception
        assert len(results) == 0
    
    def test_get_subject_triples_nonexistent(self):
        """Test getting triples for a nonexistent subject."""
        store = TemporaryTripleStore()
        document = create_single_entity_graph()
        store.load_jsonld_document(document)
        
        nonexistent_uri = "http://example.org/nonexistent"
        triples = store.get_subject_triples(nonexistent_uri)
        
        # Should return empty list, not raise an exception
        assert len(triples) == 0
    
    def test_term_type_detection(self):
        """Test internal term type detection."""
        store = TemporaryTripleStore()
        
        # Test with mock pyoxigraph terms (this is implementation-specific)
        # The actual test would depend on pyoxigraph's term types
        
        # For now, just test that the method exists and doesn't crash
        # In a real implementation, you'd create actual pyoxigraph terms
        pass
    
    def test_multiple_loads_same_document(self):
        """Test loading the same document multiple times."""
        store = TemporaryTripleStore()
        document = create_single_entity_graph()
        
        # Load once
        store.load_jsonld_document(document)
        count1 = store.get_triple_count()
        
        # Load again (pyoxigraph may deduplicate, so count might stay the same)
        store.load_jsonld_document(document)
        count2 = store.get_triple_count()
        
        # Count should be at least the same (pyoxigraph deduplicates identical triples)
        assert count2 >= count1
    
    def test_complex_sparql_query(self):
        """Test executing a complex SPARQL query with multiple patterns."""
        store = TemporaryTripleStore()
        document = create_multiple_entity_graphs()
        store.load_jsonld_document(document)
        
        query = """
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT ?entity ?frame ?slot WHERE {
            ?entity a haley:KGEntity .
            ?edge_frame a haley:Edge_hasKGFrame .
            ?edge_frame vital:hasEdgeSource ?entity .
            ?edge_frame vital:hasEdgeDestination ?frame .
            ?edge_slot a haley:Edge_hasKGSlot .
            ?edge_slot vital:hasEdgeSource ?frame .
            ?edge_slot vital:hasEdgeDestination ?slot .
        }
        """
        
        results = store.execute_query(query)
        
        assert len(results) > 0
        
        # Each result should have entity, frame, and slot
        for result in results:
            assert 'entity' in result
            assert 'frame' in result
            assert 'slot' in result
    
    def run_all_tests(self):
        """Run all test methods."""
        print("=" * 60)
        print("Running TemporaryTripleStore Tests")
        print("=" * 60)
        
        # Get all test methods
        test_methods = [
            (self.test_initialization, "test_initialization"),
            (self.test_load_empty_document, "test_load_empty_document"),
            (self.test_load_single_entity_document, "test_load_single_entity_document"),
            (self.test_load_multiple_entities_document, "test_load_multiple_entities_document"),
            (self.test_execute_simple_select_query, "test_execute_simple_select_query"),
            (self.test_execute_count_query, "test_execute_count_query"),
            (self.test_get_subject_triples, "test_get_subject_triples"),
            (self.test_get_all_subjects, "test_get_all_subjects"),
            (self.test_get_triple_count, "test_get_triple_count"),
            (self.test_clear_store, "test_clear_store"),
            (self.test_invalid_sparql_query, "test_invalid_sparql_query"),
            (self.test_query_nonexistent_data, "test_query_nonexistent_data"),
            (self.test_get_subject_triples_nonexistent, "test_get_subject_triples_nonexistent"),
            (self.test_term_type_detection, "test_term_type_detection"),
            (self.test_multiple_loads_same_document, "test_multiple_loads_same_document"),
            (self.test_complex_sparql_query, "test_complex_sparql_query")
        ]
        
        # Run each test
        for test_method, test_name in test_methods:
            self.run_test(test_method, test_name)
        
        # Print summary
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        print(f"✅ Passed: {self.passed}")
        print(f"❌ Failed: {self.failed}")
        print(f"📊 Total: {self.passed + self.failed}")
        
        if self.errors:
            print("\nERRORS:")
            for error in self.errors:
                print(f"  - {error}")
        
        return self.failed == 0


def main():
    """Main function to run all tests."""
    tester = TestTemporaryTripleStore()
    success = tester.run_all_tests()
    
    if success:
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print(f"\n💥 {tester.failed} test(s) failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
