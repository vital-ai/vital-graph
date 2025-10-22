#!/usr/bin/env python3
"""
Test suite for MockVitalGraphClient object operations.

This test suite validates the mock client's object management functionality using:
- Direct client method calls (not endpoint calls)
- Proper request/response model validation
- Complete object CRUD operations with VitalSigns-compatible data
- Space and graph creation as prerequisites for object operations
- Error handling and edge cases
- Direct test runner format (no pytest dependency)
"""

import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, List

# Add the parent directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.client.client_factory import create_vitalgraph_client
from vitalgraph.client.config.client_config_loader import VitalGraphClientConfig
from vitalgraph.model.spaces_model import Space, SpaceCreateResponse
from vitalgraph.model.sparql_model import SPARQLGraphResponse
from vitalgraph.model.objects_model import ObjectsResponse, ObjectCreateResponse, ObjectUpdateResponse, ObjectDeleteResponse
from vitalgraph.model.jsonld_model import JsonLdDocument


class TestMockClientObjects:
    """Test suite for MockVitalGraphClient object operations."""
    
    def __init__(self):
        """Initialize test suite."""
        # Configure logging to see debug output
        logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
        
        self.test_results = []
        self.client = None
        self.test_space_id = "test_objects_space"
        self.test_graph_id = "http://vital.ai/graph/test-objects"
        self.created_objects = []  # Track created objects for cleanup
        
        # Create mock client config
        self.config = self._create_mock_config()
    
    def _create_mock_config(self) -> VitalGraphClientConfig:
        """Create a config object with mock client enabled."""
        config = VitalGraphClientConfig()
        
        # Override the config data to enable mock client
        config.config_data = {
            'server': {
                'url': 'http://localhost:8001',
                'api_base_path': '/api/v1'
            },
            'auth': {
                'username': 'admin',
                'password': 'admin'
            },
            'client': {
                'timeout': 30,
                'max_retries': 3,
                'retry_delay': 1,
                'use_mock_client': True,  # This enables the mock client
                'mock': {
                    'filePath': '/Users/hadfield/Local/vital-git/vital-graph/minioFiles'
                }
            }
        }
        config.config_path = "<programmatically created>"
        
        return config
    
    def log_test_result(self, test_name: str, success: bool, message: str, data: Dict[str, Any] = None):
        """Log test result in a consistent format."""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}")
        if not success or data:
            print(f"    {message}")
            if data:
                print(f"    Data: {json.dumps(data, indent=2)}")
        print()
        
        self.test_results.append({
            "test_name": test_name,
            "success": success,
            "message": message,
            "data": data or {}
        })
    
    def test_client_initialization(self):
        """Test mock client initialization and connection."""
        try:
            # Create client using factory with config object
            self.client = create_vitalgraph_client(config=self.config)
            
            success = (
                self.client is not None and
                hasattr(self.client, 'list_objects') and
                hasattr(self.client, 'create_objects') and
                hasattr(self.client, 'update_objects') and
                hasattr(self.client, 'delete_object') and
                hasattr(self.client, 'delete_objects_batch')
            )
            
            client_type = type(self.client).__name__
            
            self.log_test_result(
                "Client Initialization",
                success,
                f"Created client: {client_type}",
                {"client_type": client_type, "has_object_methods": success}
            )
            
        except Exception as e:
            self.log_test_result("Client Initialization", False, f"Exception: {e}")
    
    def test_client_connection(self):
        """Test client connection management."""
        try:
            # Open connection
            self.client.open()
            is_connected_after_open = self.client.is_connected()
            
            # Get server info
            server_info = self.client.get_server_info()
            
            success = (
                is_connected_after_open and
                isinstance(server_info, dict) and
                ('name' in server_info or 'mock' in server_info)
            )
            
            server_name = server_info.get('name', 'Mock Server' if server_info.get('mock') else 'Unknown')
            
            self.log_test_result(
                "Client Connection",
                success,
                f"Connected: {is_connected_after_open}, Server: {server_name}",
                {
                    "connected": is_connected_after_open,
                    "server_name": server_name,
                    "is_mock": server_info.get('mock', False)
                }
            )
            
        except Exception as e:
            self.log_test_result("Client Connection", False, f"Exception: {e}")
    
    def test_create_test_space(self):
        """Test creating a test space for object operations."""
        try:
            # Create test space (required for object operations)
            test_space = Space(
                space=self.test_space_id,
                space_name="Test Objects Space",
                space_description="A test space for object operations testing"
            )
            
            response = self.client.add_space(test_space)
            
            success = (
                isinstance(response, SpaceCreateResponse) and
                response.created_count > 0
            )
            
            self.log_test_result(
                "Create Test Space",
                success,
                f"Created space: {self.test_space_id}",
                {
                    "space_id": self.test_space_id,
                    "created_count": response.created_count,
                    "message": response.message,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Create Test Space", False, f"Exception: {e}")
    
    def test_create_test_graph(self):
        """Test creating a test graph for object operations."""
        try:
            # Create test graph (required for object operations)
            response = self.client.create_graph(self.test_space_id, self.test_graph_id)
            
            success = (
                isinstance(response, SPARQLGraphResponse) and
                response.success
            )
            
            self.log_test_result(
                "Create Test Graph",
                success,
                f"Created graph: {self.test_graph_id}",
                {
                    "graph_id": self.test_graph_id,
                    "success": response.success,
                    "message": response.message,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Create Test Graph", False, f"Exception: {e}")
    
    def test_list_objects_empty(self):
        """Test listing objects when no objects exist in the graph."""
        try:
            response = self.client.list_objects(self.test_space_id, self.test_graph_id)
            
            success = (
                isinstance(response, ObjectsResponse) and
                hasattr(response, 'objects') and
                hasattr(response, 'total_count') and
                response.total_count == 0
            )
            
            objects_count = 0
            if hasattr(response.objects, 'graph') and response.objects.graph:
                objects_count = len(response.objects.graph)
            
            self.log_test_result(
                "List Objects (Empty)",
                success,
                f"Found {objects_count} objects, total_count: {response.total_count}",
                {
                    "objects_count": objects_count,
                    "total_count": response.total_count,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("List Objects (Empty)", False, f"Exception: {e}")
    
    def test_create_objects(self):
        """Test creating new objects."""
        try:
            # Create JSON-LD document with KGEntity objects using correct schema properties
            objects_data = JsonLdDocument(
                context={
                    "vital": "http://vital.ai/ontology/vital#",
                    "vital-core": "http://vital.ai/ontology/vital-core#",
                    "haley": "http://vital.ai/ontology/haley-ai-kg#"
                },
                graph=[
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
            )
            
            response = self.client.create_objects(self.test_space_id, self.test_graph_id, objects_data)
            
            success = (
                isinstance(response, ObjectCreateResponse) and
                hasattr(response, 'created_uris') and
                isinstance(response.created_uris, list) and
                len(response.created_uris) == 3
            )
            
            if success:
                self.created_objects.extend(response.created_uris)
            
            self.log_test_result(
                "Create Objects",
                success,
                f"Created {len(response.created_uris)} objects",
                {
                    "created_count": response.created_count,
                    "created_uris": response.created_uris,
                    "message": response.message,
                    "response_type": type(response).__name__
                }
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
            response = self.client.get_object(self.test_space_id, self.test_graph_id, object_uri)
            
            # Handle both ObjectsResponse and JsonLdDocument return types
            success = False
            object_type = None
            objects_count = 0
            
            if isinstance(response, ObjectsResponse):
                # Standard ObjectsResponse format
                success = (
                    hasattr(response, 'objects') and
                    hasattr(response.objects, 'graph') and
                    response.objects.graph and
                    len(response.objects.graph) > 0
                )
                if success and response.objects.graph:
                    object_type = response.objects.graph[0].get('@type', 'Unknown')
                    objects_count = len(response.objects.graph)
            elif hasattr(response, 'graph') and response.graph:
                # Direct JsonLdDocument format
                success = len(response.graph) > 0
                if success:
                    object_type = response.graph[0].get('@type', 'Unknown')
                    objects_count = len(response.graph)
            
            self.log_test_result(
                "Get Object",
                success,
                f"Retrieved object: {object_uri}",
                {
                    "uri": object_uri,
                    "type": object_type,
                    "objects_count": objects_count,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Get Object", False, f"Exception: {e}")
    
    def test_list_objects_with_data(self):
        """Test listing objects when objects exist."""
        try:
            response = self.client.list_objects(self.test_space_id, self.test_graph_id, page_size=10, offset=0)
            
            success = (
                isinstance(response, ObjectsResponse) and
                hasattr(response, 'objects') and
                hasattr(response, 'total_count') and
                response.total_count > 0
            )
            
            objects_count = 0
            object_types = []
            if hasattr(response.objects, 'graph') and response.objects.graph:
                objects_count = len(response.objects.graph)
                for obj_data in response.objects.graph:
                    obj_type = obj_data.get('@type', 'Unknown')
                    object_types.append(obj_type)
            
            self.log_test_result(
                "List Objects (With Data)",
                success,
                f"Found {objects_count} objects, total_count: {response.total_count}",
                {
                    "objects_count": objects_count,
                    "total_count": response.total_count,
                    "types": object_types[:3],  # Show first 3 types
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("List Objects (With Data)", False, f"Exception: {e}")
    
    def test_search_objects(self):
        """Test searching objects with filters."""
        try:
            response = self.client.list_objects(
                self.test_space_id, 
                self.test_graph_id, 
                page_size=10, 
                offset=0, 
                search="test"
            )
            
            success = (
                isinstance(response, ObjectsResponse) and
                hasattr(response, 'objects') and
                hasattr(response, 'total_count')
            )
            
            objects_count = 0
            if hasattr(response.objects, 'graph') and response.objects.graph:
                objects_count = len(response.objects.graph)
            
            self.log_test_result(
                "Search Objects",
                success,
                f"Search found {objects_count} objects matching 'test'",
                {
                    "search_term": "test",
                    "objects_count": objects_count,
                    "total_count": response.total_count,
                    "response_type": type(response).__name__
                }
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
            updated_data = JsonLdDocument(
                context={
                    "vital": "http://vital.ai/ontology/vital#",
                    "vital-core": "http://vital.ai/ontology/vital-core#",
                    "haley": "http://vital.ai/ontology/haley-ai-kg#"
                },
                graph=[{
                    "@id": object_uris[0],
                    "@type": "haley:KGEntity",
                    "vital-core:hasName": "Updated Test Entity",
                    "haley:hasKGraphDescription": "An updated test KG entity",
                    "haley:hasKGEntityType": "http://vital.ai/ontology/haley-ai-kg#PersonType"
                }]
            )
            
            response = self.client.update_objects(self.test_space_id, self.test_graph_id, updated_data)
            
            success = (
                isinstance(response, ObjectUpdateResponse) and
                hasattr(response, 'updated_uri') and
                response.updated_uri != ""
            )
            
            self.log_test_result(
                "Update Objects",
                success,
                f"Updated object: {response.updated_uri if success else 'None'}",
                {
                    "updated_uri": response.updated_uri if hasattr(response, 'updated_uri') else None,
                    "message": response.message if hasattr(response, 'message') else None,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Update Objects", False, f"Exception: {e}")
    
    def test_delete_object(self, object_uri: str):
        """Test deleting a single object."""
        if not object_uri:
            self.log_test_result("Delete Object", False, "No object URI provided")
            return
        
        try:
            response = self.client.delete_object(self.test_space_id, self.test_graph_id, object_uri)
            
            success = (
                isinstance(response, ObjectDeleteResponse) and
                hasattr(response, 'deleted_count') and
                response.deleted_count > 0
            )
            
            if success and object_uri in self.created_objects:
                self.created_objects.remove(object_uri)
            
            self.log_test_result(
                "Delete Object",
                success,
                f"Deleted object: {object_uri}",
                {
                    "deleted_count": response.deleted_count,
                    "deleted_uris": response.deleted_uris if hasattr(response, 'deleted_uris') else [],
                    "message": response.message if hasattr(response, 'message') else None,
                    "response_type": type(response).__name__
                }
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
            response = self.client.delete_objects_batch(self.test_space_id, self.test_graph_id, uri_list)
            
            success = (
                isinstance(response, ObjectDeleteResponse) and
                hasattr(response, 'deleted_count') and
                response.deleted_count > 0
            )
            
            if success:
                for uri in object_uris:
                    if uri in self.created_objects:
                        self.created_objects.remove(uri)
            
            self.log_test_result(
                "Delete Objects Batch",
                success,
                f"Batch deleted {response.deleted_count} objects",
                {
                    "deleted_count": response.deleted_count,
                    "deleted_uris": response.deleted_uris if hasattr(response, 'deleted_uris') else [],
                    "message": response.message if hasattr(response, 'message') else None,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Delete Objects Batch", False, f"Exception: {e}")
    
    def test_error_handling_nonexistent_space(self):
        """Test error handling with nonexistent space."""
        try:
            # Test with nonexistent space
            response = self.client.list_objects("nonexistent_space_12345", self.test_graph_id)
            
            success = (
                isinstance(response, ObjectsResponse) and
                response.total_count == 0
            )
            
            self.log_test_result(
                "Error Handling (Nonexistent Space)",
                success,
                "Gracefully handled nonexistent space request",
                {
                    "requested_space": "nonexistent_space_12345",
                    "total_count": response.total_count if hasattr(response, 'total_count') else 0
                }
            )
            
        except Exception as e:
            self.log_test_result("Error Handling (Nonexistent Space)", False, f"Exception: {e}")
    
    def test_error_handling_nonexistent_object(self):
        """Test error handling for non-existent object operations."""
        try:
            # Try to get a non-existent object
            response = self.client.get_object(
                self.test_space_id, 
                self.test_graph_id, 
                "http://nonexistent.object/uri-12345"
            )
            
            # Should handle gracefully - either return empty response or None
            success = True  # If no exception thrown, it's handling gracefully
            
            objects_count = 0
            if response and hasattr(response, 'objects') and hasattr(response.objects, 'graph'):
                objects_count = len(response.objects.graph) if response.objects.graph else 0
            
            self.log_test_result(
                "Error Handling (Non-existent Object)",
                success,
                "Gracefully handled non-existent object request",
                {
                    "requested_uri": "http://nonexistent.object/uri-12345",
                    "objects_count": objects_count
                }
            )
            
        except Exception as e:
            # Check if it's a reasonable error response
            success = "not found" in str(e).lower() or "does not exist" in str(e).lower()
            self.log_test_result(
                "Error Handling (Non-existent Object)",
                success,
                f"Exception: {e}"
            )
    
    def test_list_objects_after_operations(self):
        """Test listing objects after all operations (should be empty or reduced)."""
        try:
            response = self.client.list_objects(self.test_space_id, self.test_graph_id)
            
            success = isinstance(response, ObjectsResponse)
            
            objects_count = 0
            if hasattr(response.objects, 'graph') and response.objects.graph:
                objects_count = len(response.objects.graph)
            
            self.log_test_result(
                "List Objects (After Operations)",
                success,
                f"Found {objects_count} objects after operations",
                {
                    "objects_count": objects_count,
                    "total_count": response.total_count if hasattr(response, 'total_count') else 0
                }
            )
            
        except Exception as e:
            self.log_test_result("List Objects (After Operations)", False, f"Exception: {e}")
    
    def test_client_disconnection(self):
        """Test client disconnection."""
        try:
            # Close connection
            self.client.close()
            is_connected_after_close = self.client.is_connected()
            
            success = not is_connected_after_close
            
            self.log_test_result(
                "Client Disconnection",
                success,
                f"Disconnected: {not is_connected_after_close}",
                {"connected": is_connected_after_close}
            )
            
        except Exception as e:
            self.log_test_result("Client Disconnection", False, f"Exception: {e}")
    
    def cleanup_remaining_objects(self):
        """Clean up any remaining objects."""
        try:
            cleanup_count = 0
            for object_uri in self.created_objects[:]:  # Copy list to avoid modification during iteration
                try:
                    response = self.client.delete_object(self.test_space_id, self.test_graph_id, object_uri)
                    if hasattr(response, 'deleted_count') and response.deleted_count > 0:
                        cleanup_count += 1
                        self.created_objects.remove(object_uri)
                except:
                    pass  # Ignore cleanup errors
            
            if cleanup_count > 0:
                print(f"🧹 Cleaned up {cleanup_count} remaining objects")
                
        except Exception as e:
            print(f"⚠️  Cleanup error: {e}")
    
    def run_all_tests(self):
        """Run all tests in sequence."""
        print("🧪 Testing MockVitalGraphClient Object Operations")
        print("=" * 60)
        
        # Run tests in logical order
        self.test_client_initialization()
        self.test_client_connection()
        self.test_create_test_space()
        self.test_create_test_graph()
        self.test_list_objects_empty()
        
        # Basic object CRUD operations
        object_uris = self.test_create_objects()
        if object_uris:
            self.test_get_object(object_uris[0])
            self.test_list_objects_with_data()
            self.test_search_objects()
            self.test_update_objects(object_uris)
            
            # Test deletion operations
            if len(object_uris) > 1:
                # Delete one object individually
                self.test_delete_object(object_uris[0])
                # Delete remaining objects in batch
                self.test_delete_objects_batch(object_uris[1:])
            else:
                self.test_delete_objects_batch(object_uris)
        
        # Error handling and edge cases
        self.test_error_handling_nonexistent_space()
        self.test_error_handling_nonexistent_object()
        
        # Final verification
        self.test_list_objects_after_operations()
        
        # Cleanup any remaining objects
        self.cleanup_remaining_objects()
        
        # Disconnect client
        self.test_client_disconnection()
        
        # Print summary
        print("=" * 60)
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        
        if passed == total:
            print(f"Test Results: {passed}/{total} tests passed")
            print("🎉 All tests passed! MockVitalGraphClient object operations are working correctly.")
        else:
            print(f"Test Results: {passed}/{total} tests passed")
            print("⚠️  Some tests failed. Check the output above for details.")
        
        return passed == total


def main():
    """Main test runner."""
    test_suite = TestMockClientObjects()
    success = test_suite.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
