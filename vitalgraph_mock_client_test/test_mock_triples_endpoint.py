#!/usr/bin/env python3
"""
Test script for MockTriplesEndpoint with VitalSigns native functionality.

This script demonstrates:
- VitalSigns native object creation and conversion
- pyoxigraph quad store operations for triple management
- Complete triple lifecycle: add, list, query, delete
- Real SPARQL pattern matching for triple queries
- Quad-based response handling and conversion
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
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.VITAL_Node import VITAL_Node
from ai_haley_kg_domain.model.KGEntity import KGEntity
from vitalgraph.utils.quad_format_utils import quad_list_to_graphobjects


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
    
    def create_test_graphobjects(self):
        """Create test GraphObjects for triples operations."""
        entity1 = KGEntity()
        entity1.URI = "http://example.org/entity1"
        entity1.kGraphDescription = "Test Entity 1 Description"
        
        entity2 = KGEntity()
        entity2.URI = "http://example.org/entity2"
        entity2.kGraphDescription = "Test Entity 2 Description"
        
        return [entity1, entity2]
    
    def create_simple_graphobject(self):
        """Create a simple GraphObject for triples operations."""
        entity = KGEntity()
        entity.URI = "http://example.org/simple1"
        entity.kGraphDescription = "Simple Test Entity"
        
        return [entity]
    
    def test_list_triples_empty(self):
        """Test listing triples when no triples exist."""
        try:
            response = self.endpoint.list_triples(self.test_space_id, self.test_graph_id)
            
            success = (
                isinstance(response, TripleListResponse) and
                hasattr(response, 'total_count') and
                response.total_count == 0
            )
            
            graph_objects = quad_list_to_graphobjects(response.results) if response.results else []
            
            self.log_test_result(
                "List Triples (Empty)",
                success,
                f"Found {len(graph_objects)} entities in empty graph",
                {
                    "entities_count": len(graph_objects),
                    "total_count": getattr(response, 'total_count', 0)
                }
            )
            
        except Exception as e:
            self.log_test_result("List Triples (Empty)", False, f"Exception: {e}")
    
    def test_add_triples(self):
        """Test adding triples via GraphObjects."""
        try:
            test_objects = self.create_test_graphobjects()
            response = self.endpoint.add_triples(self.test_space_id, self.test_graph_id, test_objects)
            
            success = (
                isinstance(response, TripleOperationResponse) and
                response.success
            )
            
            self.log_test_result(
                "Add Triples",
                success,
                f"Added triples from GraphObjects",
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
            
            graph_objects = quad_list_to_graphobjects(response.results) if response.results else []
            
            success = (
                isinstance(response, TripleListResponse) and
                response.total_count > 0 and
                len(graph_objects) > 0
            )
            
            entities_data = []
            for obj in graph_objects[:3]:  # Show first 3 objects
                entities_data.append({
                    "URI": str(obj.URI),
                    "type": type(obj).__name__
                })
            
            self.log_test_result(
                "List Triples (With Data)",
                success,
                f"Found {len(graph_objects)} objects in graph",
                {
                    "objects_count": len(graph_objects),
                    "total_count": getattr(response, 'total_count', 0),
                    "sample_objects": entities_data
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
            
            graph_objects = quad_list_to_graphobjects(response.results) if response.results else []
            
            success = (
                isinstance(response, TripleListResponse) and
                response.page_size == 2 and
                response.offset == 0
            )
            
            self.log_test_result(
                "List Triples (Pagination)",
                success,
                f"Retrieved page with {len(graph_objects)} objects",
                {
                    "objects_count": len(graph_objects),
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
            
            graph_objects = quad_list_to_graphobjects(response.results) if response.results else []
            
            success = isinstance(response, TripleListResponse)
            
            # Verify all returned objects have the correct URI
            if success and graph_objects:
                for obj in graph_objects:
                    if str(obj.URI) != subject_filter:
                        success = False
                        break
            
            self.log_test_result(
                "List Triples (Subject Filter)",
                success,
                f"Found {len(graph_objects)} objects with subject {subject_filter}",
                {
                    "subject_filter": subject_filter,
                    "objects_count": len(graph_objects),
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
            
            graph_objects = quad_list_to_graphobjects(response.results) if response.results else []
            
            success = isinstance(response, TripleListResponse)
            
            self.log_test_result(
                "List Triples (Predicate Filter)",
                success,
                f"Found {len(graph_objects)} objects with predicate {predicate_filter}",
                {
                    "predicate_filter": predicate_filter,
                    "objects_count": len(graph_objects),
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
        """Test adding simple triples via GraphObjects."""
        try:
            test_objects = self.create_simple_graphobject()
            response = self.endpoint.add_triples(self.test_space_id, self.test_graph_id, test_objects)
            
            success = (
                isinstance(response, TripleOperationResponse) and
                response.success
            )
            
            self.log_test_result(
                "Add Simple Triples",
                success,
                f"Added simple triples from GraphObjects",
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
            
            graph_objects = quad_list_to_graphobjects(response.results) if response.results else []
            
            success = (
                isinstance(response, TripleListResponse) and
                response.total_count == 0 and
                len(graph_objects) == 0
            )
            
            self.log_test_result(
                "Error Handling (Nonexistent Space)",
                success,
                "Gracefully handled nonexistent space request",
                {
                    "error": getattr(response, 'error', None),
                    "objects_count": len(graph_objects)
                }
            )
            
            return success
            
        except Exception as e:
            self.log_test_result("Error Handling (Nonexistent Space)", False, f"Exception: {e}")
            return False
    
    def test_add_triples_nonexistent_space(self):
        """Test adding triples to nonexistent space."""
        try:
            test_objects = self.create_simple_graphobject()
            response = self.endpoint.add_triples("nonexistent-space-12345", self.test_graph_id, test_objects)
            
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
            
            graph_objects = quad_list_to_graphobjects(response.results) if response.results else []
            
            success = (
                isinstance(response, TripleListResponse) and
                len(graph_objects) == 0 and
                response.total_count == 0
            )
            
            self.log_test_result(
                "List Triples No Matches",
                success,
                "Filter with no matches returned empty list",
                {
                    "objects_count": len(graph_objects),
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
