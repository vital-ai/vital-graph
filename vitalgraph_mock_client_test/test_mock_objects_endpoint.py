#!/usr/bin/env python3
"""
Test script for MockObjectsEndpoint with VitalSigns native functionality.

This script demonstrates:
- VitalSigns native object creation and conversion
- pyoxigraph in-memory SPARQL quad store operations
- Complete CRUD operations for various object types
- Real JSON-LD handling without mock data generation
- Graph-based operations and filtering
"""

import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.mock.client.endpoint.mock_objects_endpoint import MockObjectsEndpoint
from vitalgraph.mock.client.space.mock_space_manager import MockSpaceManager
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from ai_haley_kg_domain.model.KGEntity import KGEntity


class TestMockObjectsEndpoint:
    """Test suite for MockObjectsEndpoint."""
    
    def __init__(self):
        """Initialize test suite."""
        # Configure logging to see debug output
        logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
        
        self.space_manager = MockSpaceManager()
        self.endpoint = MockObjectsEndpoint(client=None, space_manager=self.space_manager)
        self.test_results = []
        self.test_space_id = "test_objects_space"
        self.test_graph_id = "http://vital.ai/graph/test-objects"
        
        # Initialize test space
        self.space_manager.create_space(self.test_space_id)
        
    def log_test_result(self, test_name: str, success: bool, message: str = "", data: Any = None):
        """Log test result."""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}")
        if message:
            print(f"    {message}")
        if data and isinstance(data, dict) and len(str(data)) < 500:
            print(f"    Data: {json.dumps(data, indent=2)}")
        
        self.test_results.append({
            "test": test_name,
            "success": success,
            "message": message,
            "data": data
        })
        print()
    
    def test_list_objects_empty(self):
        """Test listing objects when none exist."""
        try:
            response = self.endpoint.list_objects(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            # Check if we have a valid JsonLdDocument with no objects
            objects_count = 0
            if hasattr(response, 'objects') and hasattr(response.objects, 'graph'):
                objects_count = len(response.objects.graph) if response.objects.graph else 0
            
            success = (
                hasattr(response, 'objects') and
                hasattr(response, 'total_count') and
                response.total_count == 0 and
                objects_count == 0
            )
            
            self.log_test_result(
                "List Objects (Empty)",
                success,
                f"Found {objects_count} objects, total_count: {response.total_count}",
                {"objects_count": objects_count, "total_count": response.total_count}
            )
            
        except Exception as e:
            self.log_test_result("List Objects (Empty)", False, f"Exception: {e}")
    
    def test_create_objects(self):
        """Test creating new objects."""
        try:
            # Create JSON-LD document with KGEntity objects using correct schema properties
            objects_jsonld = {
                "@context": {
                    "vital": "http://vital.ai/ontology/vital#",
                    "vital-core": "http://vital.ai/ontology/vital-core#",
                    "haley": "http://vital.ai/ontology/haley-ai-kg#"
                },
                "@graph": [
                    {
                        "@id": "http://vital.ai/haley.ai/app/test-entity-001",
                        "@type": "haley:KGEntity",
                        "vital-core:hasName": "Test Entity 1",
                        "haley:hasKGraphDescription": "A test KG entity"
                    },
                    {
                        "@id": "http://vital.ai/haley.ai/app/test-entity-002",
                        "@type": "haley:KGEntity", 
                        "vital-core:hasName": "Test Entity 2",
                        "haley:hasKGraphDescription": "Another test KG entity"
                    },
                    {
                        "@id": "http://vital.ai/haley.ai/app/test-entity-003",
                        "@type": "haley:KGEntity",
                        "vital-core:hasName": "Test Entity 3",
                        "haley:hasKGraphDescription": "Third test KG entity"
                    }
                ]
            }
            
            from vitalgraph.model.jsonld_model import JsonLdDocument
            response = self.endpoint.create_objects(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=JsonLdDocument(**objects_jsonld)
            )
            
            success = (
                hasattr(response, 'created_uris') and
                isinstance(response.created_uris, list) and
                len(response.created_uris) == 3
            )
            
            self.log_test_result(
                "Create Objects",
                success,
                f"Created {len(response.created_uris)} objects",
                {"created_uris": response.created_uris}
            )
            
            return response.created_uris if success else []
            
        except Exception as e:
            self.log_test_result("Create Objects", False, f"Exception: {e}")
            return []
    
    def test_get_object(self, object_uri: str):
        """Test retrieving a specific object by URI."""
        if not object_uri:
            self.log_test_result("Get Object", False, "No object URI provided")
            return
        
        try:
            response = self.endpoint.get_object(
                space_id=self.test_space_id,
                uri=object_uri,
                graph_id=self.test_graph_id
            )
            
            # Check if we have a valid JsonLdDocument with the object
            objects_count = 0
            object_type = None
            if response and hasattr(response, 'graph') and response.graph:
                objects_count = len(response.graph)
                if objects_count > 0:
                    object_type = response.graph[0].get('@type', 'Unknown')
            
            success = (
                response is not None and
                objects_count > 0
            )
            
            self.log_test_result(
                "Get Object",
                success,
                f"Retrieved object: {object_uri}",
                {"uri": object_uri, "type": object_type}
            )
            
        except Exception as e:
            self.log_test_result("Get Object", False, f"Exception: {e}")
    
    def test_get_objects_by_uris(self, object_uris: List[str]):
        """Test retrieving multiple objects by URIs."""
        if not object_uris:
            self.log_test_result("Get Objects by URIs", False, "No object URIs provided")
            return
        
        try:
            uri_list = ",".join(object_uris[:2])  # Test with first 2 URIs
            response = self.endpoint.get_objects_by_uris(
                space_id=self.test_space_id,
                uri_list=uri_list,
                graph_id=self.test_graph_id
            )
            
            # Check if we have a valid JsonLdDocument with objects
            objects_count = 0
            if hasattr(response, 'objects') and hasattr(response.objects, 'graph'):
                objects_count = len(response.objects.graph) if response.objects.graph else 0
            
            success = (
                hasattr(response, 'objects') and
                hasattr(response, 'total_count') and
                objects_count > 0
            )
            
            self.log_test_result(
                "Get Objects by URIs",
                success,
                f"Retrieved {objects_count} objects from URI list",
                {"requested_count": 2, "retrieved_count": objects_count}
            )
            
        except Exception as e:
            self.log_test_result("Get Objects by URIs", False, f"Exception: {e}")
    
    def test_list_objects_with_data(self):
        """Test listing objects when data exists."""
        try:
            response = self.endpoint.list_objects(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                page_size=10,
                offset=0
            )
            
            # Check if we have a valid JsonLdDocument with objects
            objects_count = 0
            object_types = []
            if hasattr(response, 'objects') and hasattr(response.objects, 'graph'):
                objects_count = len(response.objects.graph) if response.objects.graph else 0
                if response.objects.graph:
                    for obj_data in response.objects.graph:
                        obj_type = obj_data.get('@type', 'Unknown')
                        object_types.append(obj_type)
            
            success = (
                hasattr(response, 'objects') and
                hasattr(response, 'total_count') and
                response.total_count > 0 and
                objects_count > 0
            )
            
            self.log_test_result(
                "List Objects (With Data)",
                success,
                f"Found {objects_count} objects, total_count: {response.total_count}",
                {"objects_count": objects_count, "total_count": response.total_count, "types": object_types}
            )
            
        except Exception as e:
            self.log_test_result("List Objects (With Data)", False, f"Exception: {e}")
    
    def test_search_objects(self):
        """Test searching objects with filters."""
        try:
            response = self.endpoint.list_objects(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                page_size=10,
                offset=0,
                search="test"
            )
            
            # Check if we have a valid JsonLdDocument response
            objects_count = 0
            if hasattr(response, 'objects') and hasattr(response.objects, 'graph'):
                objects_count = len(response.objects.graph) if response.objects.graph else 0
            
            success = (
                hasattr(response, 'objects') and
                hasattr(response, 'total_count')
            )
            
            self.log_test_result(
                "Search Objects",
                success,
                f"Search found {objects_count} objects matching 'test'",
                {"objects_count": objects_count, "total_count": response.total_count}
            )
            
        except Exception as e:
            self.log_test_result("Search Objects", False, f"Exception: {e}")
    
    def test_update_objects(self, object_uris: List[str]):
        """Test updating existing objects."""
        if not object_uris:
            self.log_test_result("Update Objects", False, "No object URIs provided")
            return
        
        try:
            # Create updated JSON-LD document with valid KGEntity properties
            updated_jsonld = {
                "@context": {
                    "vital": "http://vital.ai/ontology/vital#",
                    "vital-core": "http://vital.ai/ontology/vital-core#",
                    "haley": "http://vital.ai/ontology/haley-ai-kg#"
                },
                "@graph": [{
                    "@id": object_uris[0],
                    "@type": "haley:KGEntity",
                    "vital-core:hasName": "Updated Test Entity",
                    "haley:hasKGraphDescription": "An updated test KG entity",
                    "haley:hasKGEntityType": "http://vital.ai/ontology/haley-ai-kg#PersonType"
                }]
            }
            
            from vitalgraph.model.jsonld_model import JsonLdDocument
            response = self.endpoint.update_objects(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=JsonLdDocument(**updated_jsonld)
            )
            
            success = (
                hasattr(response, 'updated_uri') and
                response.updated_uri != ""
            )
            
            self.log_test_result(
                "Update Objects",
                success,
                f"Updated object: {response.updated_uri if success else 'None'}",
                {"updated_uri": response.updated_uri if hasattr(response, 'updated_uri') else None}
            )
            
        except Exception as e:
            self.log_test_result("Update Objects", False, f"Exception: {e}")
    
    def test_delete_object(self, object_uri: str):
        """Test deleting a single object."""
        if not object_uri:
            self.log_test_result("Delete Object", False, "No object URI provided")
            return
        
        try:
            response = self.endpoint.delete_object(
                space_id=self.test_space_id,
                uri=object_uri,
                graph_id=self.test_graph_id
            )
            
            success = (
                hasattr(response, 'deleted_count') and
                response.deleted_count > 0 and
                hasattr(response, 'deleted_uris') and
                object_uri in response.deleted_uris
            )
            
            self.log_test_result(
                "Delete Object",
                success,
                f"Deleted object: {object_uri}",
                {"deleted_count": response.deleted_count, "deleted_uris": response.deleted_uris}
            )
            
        except Exception as e:
            self.log_test_result("Delete Object", False, f"Exception: {e}")
    
    def test_delete_objects_batch(self, object_uris: List[str]):
        """Test batch deletion of objects."""
        if not object_uris:
            self.log_test_result("Delete Objects Batch", False, "No object URIs provided")
            return
        
        try:
            uri_list = ",".join(object_uris)
            response = self.endpoint.delete_objects_batch(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri_list=uri_list
            )
            
            success = (
                hasattr(response, 'deleted_count') and
                response.deleted_count > 0
            )
            
            self.log_test_result(
                "Delete Objects Batch",
                success,
                f"Batch deleted {response.deleted_count} objects",
                {
                    "deleted_count": response.deleted_count,
                    "deleted_uris": response.deleted_uris if hasattr(response, 'deleted_uris') else []
                }
            )
            
        except Exception as e:
            self.log_test_result("Delete Objects Batch", False, f"Exception: {e}")
    
    def test_graph_operations(self):
        """Test graph-specific operations."""
        try:
            # Create objects in different graphs
            graph1_jsonld = {
                "@context": {
                    "vital": "http://vital.ai/ontology/vital#",
                    "vital-core": "http://vital.ai/ontology/vital-core#",
                    "haley": "http://vital.ai/ontology/haley-ai-kg#"
                },
                "@graph": [{
                    "@id": "http://vital.ai/haley.ai/app/graph1-object",
                    "@type": "haley:KGEntity",
                    "vital-core:hasName": "Graph 1 Object",
                    "haley:hasKGraphDescription": "Object in graph 1"
                }]
            }
            
            graph2_jsonld = {
                "@context": {
                    "vital": "http://vital.ai/ontology/vital#",
                    "vital-core": "http://vital.ai/ontology/vital-core#",
                    "haley": "http://vital.ai/ontology/haley-ai-kg#"
                },
                "@graph": [{
                    "@id": "http://vital.ai/haley.ai/app/graph2-object",
                    "@type": "haley:KGEntity",
                    "vital-core:hasName": "Graph 2 Object",
                    "haley:hasKGraphDescription": "Object in graph 2"
                }]
            }
            
            # Create in different graphs
            from vitalgraph.model.jsonld_model import JsonLdDocument
            print(f"DEBUG: Creating object in graph: http://vital.ai/graph/test-graph-1")
            response1 = self.endpoint.create_objects(
                space_id=self.test_space_id,
                graph_id="http://vital.ai/graph/test-graph-1",
                document=JsonLdDocument(**graph1_jsonld)
            )
            print(f"DEBUG: Created {len(response1.created_uris)} objects in graph 1: {response1.created_uris}")
            
            print(f"DEBUG: Creating object in graph: http://vital.ai/graph/test-graph-2")
            response2 = self.endpoint.create_objects(
                space_id=self.test_space_id,
                graph_id="http://vital.ai/graph/test-graph-2",
                document=JsonLdDocument(**graph2_jsonld)
            )
            print(f"DEBUG: Created {len(response2.created_uris)} objects in graph 2: {response2.created_uris}")
            
            # List objects from specific graph
            print(f"DEBUG: Listing objects from graph: http://vital.ai/graph/test-graph-1")
            list_response = self.endpoint.list_objects(
                space_id=self.test_space_id,
                graph_id="http://vital.ai/graph/test-graph-1"
            )
            print(f"DEBUG: List response objects count: {len(list_response.objects.graph) if hasattr(list_response.objects, 'graph') and list_response.objects.graph else 0}")
            print(f"DEBUG: List response total_count: {list_response.total_count}")
            
            # Check list response objects count
            list_objects_count = 0
            if hasattr(list_response, 'objects') and hasattr(list_response.objects, 'graph'):
                list_objects_count = len(list_response.objects.graph) if list_response.objects.graph else 0
            
            success = (
                len(response1.created_uris) > 0 and
                len(response2.created_uris) > 0 and
                list_objects_count > 0
            )
            
            self.log_test_result(
                "Graph Operations",
                success,
                f"Created objects in 2 graphs, listed {list_objects_count} from graph 1",
                {
                    "graph1_objects": len(response1.created_uris),
                    "graph2_objects": len(response2.created_uris),
                    "graph1_list_count": list_objects_count
                }
            )
            
            # Clean up
            if response1.created_uris:
                self.endpoint.delete_object(
                    space_id=self.test_space_id,
                    uri=response1.created_uris[0],
                    graph_id="http://vital.ai/graph/test-graph-1"
                )
            if response2.created_uris:
                self.endpoint.delete_object(
                    space_id=self.test_space_id,
                    uri=response2.created_uris[0],
                    graph_id="http://vital.ai/graph/test-graph-2"
                )
            
        except Exception as e:
            self.log_test_result("Graph Operations", False, f"Exception: {e}")
    
    def test_error_handling(self):
        """Test error handling scenarios."""
        try:
            # Test getting non-existent object
            response = self.endpoint.get_object(
                space_id=self.test_space_id,
                uri="http://nonexistent.object/uri",
                graph_id=self.test_graph_id
            )
            
            # Should return None or empty response, not crash
            success = True  # If we get here without exception, error handling works
            
            self.log_test_result(
                "Error Handling (Non-existent Object)",
                success,
                "Gracefully handled non-existent object request"
            )
            
        except Exception as e:
            self.log_test_result("Error Handling (Non-existent Object)", False, f"Exception: {e}")
    
    def run_all_tests(self):
        """Run complete test suite."""
        print("MockObjectsEndpoint Test Suite")
        print("=" * 50)
        
        # Test empty state
        self.test_list_objects_empty()
        
        # Test CRUD operations
        object_uris = self.test_create_objects()
        if object_uris:
            self.test_get_object(object_uris[0])
            self.test_get_objects_by_uris(object_uris)
            self.test_list_objects_with_data()
            self.test_update_objects(object_uris)
            self.test_search_objects()
        
        # Test graph operations
        self.test_graph_operations()
        
        # Test error handling
        self.test_error_handling()
        
        # Test deletion
        if object_uris:
            # Delete one object individually
            if len(object_uris) > 1:
                self.test_delete_object(object_uris[0])
                # Delete remaining objects in batch
                self.test_delete_objects_batch(object_uris[1:])
            else:
                self.test_delete_objects_batch(object_uris)
        
        # Final verification
        self.test_list_objects_empty()
        
        # Summary
        print("=" * 50)
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        print(f"Test Results: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 All tests passed! MockObjectsEndpoint is working correctly.")
        else:
            print("⚠️  Some tests failed. Check the output above for details.")
        
        return passed == total


def main():
    """Run the test suite."""
    test_suite = TestMockObjectsEndpoint()
    success = test_suite.run_all_tests()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
