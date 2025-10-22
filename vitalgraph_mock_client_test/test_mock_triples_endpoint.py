#!/usr/bin/env python3
"""
Test script for MockTriplesEndpoint with VitalSigns native functionality.

This script demonstrates:
- VitalSigns native object creation and conversion
- pyoxigraph quad store operations for triple management
- Complete triple lifecycle: add, list, query, delete
- Real SPARQL pattern matching for triple queries
- JSON-LD document processing and conversion
- Comprehensive error handling and edge cases
"""
import logging
import sys
import json
from pathlib import Path
from typing import Dict, Any

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)

from vitalgraph.mock.client.endpoint.mock_triples_endpoint import MockTriplesEndpoint
from vitalgraph.mock.client.space.mock_space_manager import MockSpaceManager
from vitalgraph.model.triples_model import TripleListResponse, TripleOperationResponse
from vitalgraph.model.jsonld_model import JsonLdDocument
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.VITAL_Node import VITAL_Node


class TestMockTriplesEndpoint:
    """Test suite for MockTriplesEndpoint."""
    
    def __init__(self):
        """Initialize test suite."""
        self.space_manager = MockSpaceManager()
        self.endpoint = MockTriplesEndpoint(client=None, space_manager=self.space_manager)
        self.test_results = []
        self.test_space_id = "test-triples-space"
        self.test_graph_id = "http://example.org/test-graph-001"
        
        # Create test space and graph
        self.space_manager.create_space(self.test_space_id)
        space = self.space_manager.get_space(self.test_space_id)
        if space:
            space.add_graph(self.test_graph_id, name="Test Graph")
    
    def log_test_result(self, test_name: str, success: bool, message: str, data: Dict[str, Any] = None):
        """Log a test result."""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}")
        print(f"    {message}")
        
        if data:
            print(f"    Data: {json.dumps(data, indent=2)}")
        
        self.test_results.append({
            "test_name": test_name,
            "success": success,
            "message": message,
            "data": data
        })
        print()
    
    def cleanup_all_triples(self):
        """Clean up all triples in the test graph."""
        try:
            # Delete all triples from the test graph
            response = self.endpoint.delete_triples(self.test_space_id, self.test_graph_id)
            deleted_count = getattr(response, 'deleted_count', 0)
            print(f"🧹 Cleaned up {deleted_count} triples")
            
        except Exception as e:
            print(f"⚠️  Cleanup error: {e}")
    
    def create_test_jsonld_document(self) -> JsonLdDocument:
        """Create a test JSON-LD document with VitalSigns-compatible data."""
        jsonld_data = {
            "@context": {
                "vital": "http://vital.ai/ontology/vital-core#",
                "haley": "http://vital.ai/ontology/haley-ai-kg#"
            },
            "@graph": [
                {
                    "@id": "http://example.org/entity1",
                    "@type": "http://vital.ai/ontology/haley-ai-kg#KGEntity",
                    "http://vital.ai/ontology/vital-core#vitaltype": "http://vital.ai/ontology/haley-ai-kg#KGEntity",
                    "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription": "Test Entity 1 Description"
                },
                {
                    "@id": "http://example.org/entity2", 
                    "@type": "http://vital.ai/ontology/haley-ai-kg#KGEntity",
                    "http://vital.ai/ontology/vital-core#vitaltype": "http://vital.ai/ontology/haley-ai-kg#KGEntity",
                    "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription": "Test Entity 2 Description"
                }
            ]
        }
        return JsonLdDocument(**jsonld_data)
    
    def create_simple_jsonld_document(self) -> JsonLdDocument:
        """Create a simple JSON-LD document with VitalSigns-compatible entity."""
        jsonld_data = {
            "@context": {
                "vital": "http://vital.ai/ontology/vital-core#",
                "haley": "http://vital.ai/ontology/haley-ai-kg#"
            },
            "@id": "http://example.org/simple1",
            "@type": "http://vital.ai/ontology/haley-ai-kg#KGEntity",
            "http://vital.ai/ontology/vital-core#vitaltype": "http://vital.ai/ontology/haley-ai-kg#KGEntity",
            "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription": "Simple Test Entity"
        }
        return JsonLdDocument(**jsonld_data)
    
    def test_list_triples_empty(self):
        """Test listing triples when no triples exist."""
        try:
            response = self.endpoint.list_triples(self.test_space_id, self.test_graph_id)
            
            success = (
                hasattr(response, 'data') and
                hasattr(response.data, 'model_dump') and
                hasattr(response, 'total_count') and
                response.total_count == 0
            )
            
            # Get the JSON-LD data
            jsonld_data = response.data.model_dump(by_alias=True) if hasattr(response, 'data') else {}
            graph_items = jsonld_data.get('@graph', []) if isinstance(jsonld_data, dict) else []
            graph_items = graph_items or []  # Ensure it's never None
            
            self.log_test_result(
                "List Triples (Empty)",
                success,
                f"Found {len(graph_items)} entities in empty graph",
                {
                    "entities_count": len(graph_items),
                    "total_count": getattr(response, 'total_count', 0)
                }
            )
            
        except Exception as e:
            self.log_test_result("List Triples (Empty)", False, f"Exception: {e}")
    
    def test_add_triples(self):
        """Test adding triples via JSON-LD document."""
        try:
            document = self.create_test_jsonld_document()
            response = self.endpoint.add_triples(self.test_space_id, self.test_graph_id, document)
            
            success = (
                isinstance(response, TripleOperationResponse) and
                response.success
            )
            
            self.log_test_result(
                "Add Triples",
                success,
                f"Added triples from JSON-LD document",
                {
                    "success": response.success,
                    "message": response.message
                }
            )
            
            return success
            
        except Exception as e:
            self.log_test_result("Add Triples", False, f"Exception: {e}")
            return False
    
    def test_list_triples_with_data(self):
        """Test listing triples when triples exist."""
        try:
            response = self.endpoint.list_triples(self.test_space_id, self.test_graph_id)
            
            # Get the JSON-LD data (use by_alias=True to get @graph instead of graph)
            jsonld_data = response.data.model_dump(by_alias=True) if hasattr(response, 'data') else {}
            graph_items = jsonld_data.get('@graph', []) if isinstance(jsonld_data, dict) else []
            graph_items = graph_items or []  # Ensure it's never None
            
            success = (
                hasattr(response, 'data') and
                hasattr(response, 'total_count') and
                response.total_count > 0 and
                len(graph_items) > 0
            )
            
            entities_data = []
            for entity in graph_items[:3]:  # Show first 3 entities
                entities_data.append({
                    "@id": entity.get("@id", ""),
                    "@type": entity.get("@type", ""),
                    "properties": {k: v for k, v in entity.items() if not k.startswith('@')}
                })
            
            self.log_test_result(
                "List Triples (With Data)",
                success,
                f"Found {len(graph_items)} entities in graph",
                {
                    "entities_count": len(graph_items),
                    "total_count": getattr(response, 'total_count', 0),
                    "sample_entities": entities_data
                }
            )
            
        except Exception as e:
            self.log_test_result("List Triples (With Data)", False, f"Exception: {e}")
    
    def test_list_triples_with_pagination(self):
        """Test listing triples with pagination."""
        try:
            # Test with page_size=2, offset=0
            response = self.endpoint.list_triples(
                self.test_space_id, 
                self.test_graph_id, 
                page_size=2, 
                offset=0
            )
            
            # Get the JSON-LD data
            jsonld_data = response.data.model_dump(by_alias=True) if hasattr(response, 'data') else {}
            graph_items = jsonld_data.get('@graph', []) if isinstance(jsonld_data, dict) else []
            graph_items = graph_items or []  # Ensure it's never None
            
            success = (
                hasattr(response, 'data') and
                hasattr(response, 'page_size') and
                response.page_size == 2 and
                hasattr(response, 'offset') and
                response.offset == 0
            )
            
            self.log_test_result(
                "List Triples (Pagination)",
                success,
                f"Retrieved page with {len(graph_items)} entities",
                {
                    "entities_count": len(graph_items),
                    "page_size": getattr(response, 'page_size', 0),
                    "offset": getattr(response, 'offset', 0),
                    "total_count": getattr(response, 'total_count', 0)
                }
            )
            
        except Exception as e:
            self.log_test_result("List Triples (Pagination)", False, f"Exception: {e}")
    
    def test_list_triples_with_subject_filter(self):
        """Test listing triples with subject filter."""
        try:
            # Filter by a specific subject
            subject_filter = "http://example.org/entity1"
            response = self.endpoint.list_triples(
                self.test_space_id, 
                self.test_graph_id, 
                subject=subject_filter
            )
            
            # Get the JSON-LD data
            jsonld_data = response.data.model_dump(by_alias=True) if hasattr(response, 'data') else {}
            graph_items = jsonld_data.get('@graph', []) if isinstance(jsonld_data, dict) else []
            graph_items = graph_items or []  # Ensure it's never None
            
            success = hasattr(response, 'data')
            
            # Verify all returned entities have the correct @id
            if success and graph_items:
                for entity in graph_items:
                    if entity.get("@id") != subject_filter:
                        success = False
                        break
            
            self.log_test_result(
                "List Triples (Subject Filter)",
                success,
                f"Found {len(graph_items)} entities with subject {subject_filter}",
                {
                    "subject_filter": subject_filter,
                    "entities_count": len(graph_items),
                    "total_count": getattr(response, 'total_count', 0)
                }
            )
            
        except Exception as e:
            self.log_test_result("List Triples (Subject Filter)", False, f"Exception: {e}")
    
    def test_list_triples_with_predicate_filter(self):
        """Test listing triples with predicate filter."""
        try:
            # Filter by a specific predicate
            predicate_filter = "http://vital.ai/ontology/haley-ai-kg#hasName"
            response = self.endpoint.list_triples(
                self.test_space_id, 
                self.test_graph_id, 
                predicate=predicate_filter
            )
            
            # Get the JSON-LD data
            jsonld_data = response.data.model_dump(by_alias=True) if hasattr(response, 'data') else {}
            graph_items = jsonld_data.get('@graph', []) if isinstance(jsonld_data, dict) else []
            graph_items = graph_items or []  # Ensure it's never None
            
            success = hasattr(response, 'data')
            
            # For predicate filtering, we expect entities that have the specified property
            entities_with_predicate = 0
            if success and graph_items:
                for entity in graph_items:
                    if predicate_filter in entity or "name" in entity:  # Check both full URI and short form
                        entities_with_predicate += 1
            
            self.log_test_result(
                "List Triples (Predicate Filter)",
                success,
                f"Found {entities_with_predicate} entities with predicate {predicate_filter}",
                {
                    "predicate_filter": predicate_filter,
                    "entities_with_predicate": entities_with_predicate,
                    "total_entities": len(graph_items),
                    "total_count": getattr(response, 'total_count', 0)
                }
            )
            
        except Exception as e:
            self.log_test_result("List Triples (Predicate Filter)", False, f"Exception: {e}")
    
    def test_delete_triples_by_subject(self):
        """Test deleting triples by subject filter."""
        try:
            # Delete triples for a specific subject
            subject_to_delete = "http://example.org/entity1"
            response = self.endpoint.delete_triples(
                self.test_space_id, 
                self.test_graph_id, 
                subject=subject_to_delete
            )
            
            success = (
                isinstance(response, TripleOperationResponse) and
                response.success
            )
            
            deleted_count = getattr(response, 'deleted_count', 0)
            
            self.log_test_result(
                "Delete Triples (By Subject)",
                success,
                f"Deleted {deleted_count} triples for subject {subject_to_delete}",
                {
                    "success": response.success,
                    "message": response.message,
                    "deleted_count": deleted_count,
                    "subject_filter": subject_to_delete
                }
            )
            
            return deleted_count
            
        except Exception as e:
            self.log_test_result("Delete Triples (By Subject)", False, f"Exception: {e}")
            return 0
    
    def test_delete_triples_by_predicate(self):
        """Test deleting triples by predicate filter."""
        try:
            # Delete triples with a specific predicate
            predicate_to_delete = "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription"
            response = self.endpoint.delete_triples(
                self.test_space_id, 
                self.test_graph_id, 
                predicate=predicate_to_delete
            )
            
            success = (
                isinstance(response, TripleOperationResponse) and
                response.success
            )
            
            deleted_count = getattr(response, 'deleted_count', 0)
            
            self.log_test_result(
                "Delete Triples (By Predicate)",
                success,
                f"Deleted {deleted_count} triples with predicate {predicate_to_delete}",
                {
                    "success": response.success,
                    "message": response.message,
                    "deleted_count": deleted_count,
                    "predicate_filter": predicate_to_delete
                }
            )
            
            return deleted_count
            
        except Exception as e:
            self.log_test_result("Delete Triples (By Predicate)", False, f"Exception: {e}")
            return 0
    
    def test_add_simple_triples(self):
        """Test adding simple triples via JSON-LD document."""
        try:
            document = self.create_simple_jsonld_document()
            response = self.endpoint.add_triples(self.test_space_id, self.test_graph_id, document)
            
            success = (
                isinstance(response, TripleOperationResponse) and
                response.success
            )
            
            self.log_test_result(
                "Add Simple Triples",
                success,
                f"Added simple triples from JSON-LD document",
                {
                    "success": response.success,
                    "message": response.message
                }
            )
            
            return success
            
        except Exception as e:
            self.log_test_result("Add Simple Triples", False, f"Exception: {e}")
            return False
    
    def test_delete_all_triples(self):
        """Test deleting all triples from the graph."""
        try:
            # Log before deletion
            logging.info("=== STARTING DELETE ALL TRIPLES TEST ===")
            
            # Check how many triples exist before deletion
            list_response = self.endpoint.list_triples(self.test_space_id, self.test_graph_id)
            before_count = getattr(list_response, 'total_count', 0)
            logging.info(f"Triples before deletion: {before_count}")
            
            # Delete all triples (no filters)
            logging.info("Calling delete_triples with no filters")
            response = self.endpoint.delete_triples(self.test_space_id, self.test_graph_id)
            
            logging.info(f"Delete response: success={response.success}, message='{response.message}'")
            logging.info(f"Delete response deleted_count: {getattr(response, 'deleted_count', 'NOT SET')}")
            
            success = (
                isinstance(response, TripleOperationResponse) and
                response.success
            )
            
            deleted_count = getattr(response, 'deleted_count', 0)
            
            # Check how many triples exist after deletion
            list_response_after = self.endpoint.list_triples(self.test_space_id, self.test_graph_id)
            after_count = getattr(list_response_after, 'total_count', 0)
            logging.info(f"Triples after deletion: {after_count}")
            
            self.log_test_result(
                "Delete All Triples",
                success,
                f"Deleted {deleted_count} triples from graph",
                {
                    "success": response.success,
                    "message": response.message,
                    "deleted_count": deleted_count,
                    "before_count": before_count,
                    "after_count": after_count
                }
            )
            
            return deleted_count
            
        except Exception as e:
            self.log_test_result("Delete All Triples", False, f"Exception: {e}")
            return 0
    
    def test_error_handling_nonexistent_space(self):
        """Test error handling with nonexistent space."""
        try:
            response = self.endpoint.list_triples("nonexistent-space-12345", self.test_graph_id)
            
            # Get the JSON-LD data
            jsonld_data = response.data.model_dump(by_alias=True) if hasattr(response, 'data') else {}
            graph_items = jsonld_data.get('@graph', []) if isinstance(jsonld_data, dict) else []
            graph_items = graph_items or []  # Ensure it's never None
            
            success = (
                isinstance(response, TripleListResponse) and
                hasattr(response, 'data') and
                hasattr(response, 'total_count') and
                response.total_count == 0 and
                len(graph_items) == 0
            )
            
            self.log_test_result(
                "Error Handling (Nonexistent Space)",
                success,
                "Gracefully handled nonexistent space request",
                {
                    "error": getattr(response, 'error', None),
                    "triples_count": len(graph_items)
                }
            )
            
            return success
            
        except Exception as e:
            self.log_test_result("Error Handling (Nonexistent Space)", False, f"Exception: {e}")
            return False
    
    def test_add_triples_nonexistent_space(self):
        """Test adding triples to nonexistent space."""
        try:
            document = self.create_simple_jsonld_document()
            response = self.endpoint.add_triples("nonexistent-space-12345", self.test_graph_id, document)
            
            success = (
                isinstance(response, TripleOperationResponse) and
                not response.success and
                "not found" in response.message.lower()
            )
            
            self.log_test_result(
                "Add Triples Nonexistent Space",
                success,
                "Handled nonexistent space gracefully",
                {
                    "success": response.success,
                    "message": response.message
                }
            )
            
        except Exception as e:
            self.log_test_result("Add Triples Nonexistent Space", False, f"Exception: {e}")
    
    def test_delete_triples_nonexistent_space(self):
        """Test deleting triples from nonexistent space."""
        try:
            response = self.endpoint.delete_triples("nonexistent-space-12345", self.test_graph_id)
            
            success = (
                isinstance(response, TripleOperationResponse) and
                not response.success and
                "not found" in response.message.lower()
            )
            
            self.log_test_result(
                "Delete Triples Nonexistent Space",
                success,
                "Handled nonexistent space gracefully",
                {
                    "success": response.success,
                    "message": response.message
                }
            )
            
        except Exception as e:
            self.log_test_result("Delete Triples Nonexistent Space", False, f"Exception: {e}")
    
    def test_list_triples_no_matches(self):
        """Test listing triples with filters that match nothing."""
        try:
            # Use a subject that doesn't exist
            response = self.endpoint.list_triples(
                self.test_space_id, 
                self.test_graph_id, 
                subject="http://example.org/nonexistent-subject"
            )
            
            # Get the JSON-LD data
            jsonld_data = response.data.model_dump(by_alias=True) if hasattr(response, 'data') else {}
            graph_items = jsonld_data.get('@graph', []) if isinstance(jsonld_data, dict) else []
            graph_items = graph_items or []  # Ensure it's never None
            
            success = (
                hasattr(response, 'data') and
                len(graph_items) == 0 and
                hasattr(response, 'total_count') and
                response.total_count == 0
            )
            
            self.log_test_result(
                "List Triples No Matches",
                success,
                "Filter with no matches returned empty list",
                {
                    "entities_count": len(graph_items),
                    "total_count": getattr(response, 'total_count', 0)
                }
            )
            
        except Exception as e:
            self.log_test_result("List Triples No Matches", False, f"Exception: {e}")

    def run_all_tests(self):
        """Run complete test suite."""
        print("MockTriplesEndpoint Test Suite")
        print("=" * 50)
        
        # Test 1: Initial empty state
        self.test_list_triples_empty()
        
        # Test 2-6: Basic triple operations
        add_success = self.test_add_triples()
        if add_success:
            self.test_list_triples_with_data()
            self.test_list_triples_with_pagination()
            self.test_list_triples_with_subject_filter()
            self.test_list_triples_with_predicate_filter()
        
        # Test 7-8: Deletion operations
        self.test_delete_triples_by_subject()
        self.test_delete_triples_by_predicate()
        
        # Test 9-10: Add more data and test different operations
        self.test_add_simple_triples()
        self.test_delete_all_triples()
        
        # Test 11-14: Error handling and edge cases
        self.test_error_handling_nonexistent_space()
        self.test_add_triples_nonexistent_space()
        self.test_delete_triples_nonexistent_space()
        self.test_list_triples_no_matches()
        
        # Clean up any remaining triples before final test
        self.cleanup_all_triples()
        
        # Test 15: Final verification - should be empty now
        self.test_list_triples_empty()
        
        # Summary
        print("=" * 50)
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        print(f"Test Results: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 All tests passed!")
        else:
            print("⚠️  Some tests failed. Check the output above for details.")
        
        return passed == total


def main():
    """Run the test suite."""
    test_suite = TestMockTriplesEndpoint()
    success = test_suite.run_all_tests()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
