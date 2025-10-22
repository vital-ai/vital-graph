#!/usr/bin/env python3
"""
Test suite for MockVitalGraphClient KGTypes operations.

This test suite validates the mock client's KGTypes management functionality using:
- Direct client method calls (not endpoint calls)
- Proper request/response model validation
- Complete KGTypes CRUD operations with VitalSigns-compatible data
- Space and graph creation as prerequisites for KGTypes operations
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
from vitalgraph.model.kgtypes_model import KGTypeListResponse, KGTypeCreateResponse, KGTypeUpdateResponse, KGTypeDeleteResponse
from vitalgraph.model.jsonld_model import JsonLdDocument

# VitalSigns imports
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from ai_haley_kg_domain.model.KGType import KGType


class TestMockClientKGTypes:
    """Test suite for MockVitalGraphClient KGTypes operations."""
    
    def __init__(self):
        """Initialize test suite."""
        # Configure logging to see debug output
        logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
        
        self.test_results = []
        self.client = None
        self.test_space_id = "test_kgtypes_space"
        self.test_graph_id = "http://vital.ai/graph/test-kgtypes"
        self.created_kgtypes = []  # Track created KGTypes for cleanup
        
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
                hasattr(self.client, 'list_kgtypes') and
                hasattr(self.client, 'create_kgtypes') and
                hasattr(self.client, 'update_kgtypes') and
                hasattr(self.client, 'delete_kgtype') and
                hasattr(self.client, 'delete_kgtypes_batch')
            )
            
            client_type = type(self.client).__name__
            
            self.log_test_result(
                "Client Initialization",
                success,
                f"Created client: {client_type}",
                {"client_type": client_type, "has_kgtype_methods": success}
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
        """Test creating a test space for KGTypes operations."""
        try:
            # Create test space (required for KGTypes operations)
            test_space = Space(
                space=self.test_space_id,
                space_name="Test KGTypes Space",
                space_description="A test space for KGTypes operations testing"
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
        """Test creating a test graph for KGTypes operations."""
        try:
            # Create test graph (required for KGTypes operations)
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
    
    def test_list_kgtypes_empty(self):
        """Test listing KGTypes when no KGTypes exist in the graph."""
        try:
            response = self.client.list_kgtypes(self.test_space_id, self.test_graph_id)
            
            success = (
                isinstance(response, KGTypeListResponse) and
                hasattr(response, 'types') and
                hasattr(response, 'total_count') and
                response.total_count == 0
            )
            
            types_count = 0
            if hasattr(response.types, 'graph') and response.types.graph:
                types_count = len(response.types.graph)
            
            self.log_test_result(
                "List KGTypes (Empty)",
                success,
                f"Found {types_count} KGTypes, total_count: {response.total_count}",
                {
                    "types_count": types_count,
                    "total_count": response.total_count,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("List KGTypes (Empty)", False, f"Exception: {e}")
    
    def _create_test_kgtypes(self) -> List[KGType]:
        """Create test KGType objects using VitalSigns."""
        types = []
        
        # Create first test KGType
        type1 = KGType()
        type1.URI = "http://vital.ai/haley.ai/app/KGType/test_type_001"
        type1.name = "TestType1"
        type1.kGraphDescription = "A test type for VitalSigns mock client testing"
        type1.kGTypeVersion = "1.0.0"
        type1.kGModelVersion = "1.0.0"
        types.append(type1)
        
        # Create second test KGType
        type2 = KGType()
        type2.URI = "http://vital.ai/haley.ai/app/KGType/test_type_002"
        type2.name = "TestType2"
        type2.kGraphDescription = "Another test type for VitalSigns mock client testing"
        type2.kGTypeVersion = "1.0.0"
        type2.kGModelVersion = "1.0.0"
        types.append(type2)
        
        # Create third test KGType
        type3 = KGType()
        type3.URI = "http://vital.ai/haley.ai/app/KGType/test_type_003"
        type3.name = "TestType3"
        type3.kGraphDescription = "Third test type for VitalSigns mock client testing"
        type3.kGTypeVersion = "1.0.0"
        type3.kGModelVersion = "1.0.0"
        types.append(type3)
        
        return types
    
    def test_create_kgtypes(self):
        """Test creating new KGTypes."""
        try:
            # Create test KGTypes using VitalSigns
            test_types = self._create_test_kgtypes()
            
            # Convert to JSON-LD using VitalSigns
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            jsonld_data = GraphObject.to_jsonld_list(test_types)
            
            # Create JsonLdDocument
            kgtypes_document = JsonLdDocument(**jsonld_data)
            
            response = self.client.create_kgtypes(self.test_space_id, self.test_graph_id, kgtypes_document)
            
            success = (
                isinstance(response, KGTypeCreateResponse) and
                hasattr(response, 'created_uris') and
                isinstance(response.created_uris, list) and
                len(response.created_uris) == 3
            )
            
            if success:
                self.created_kgtypes.extend(response.created_uris)
            
            self.log_test_result(
                "Create KGTypes",
                success,
                f"Created {len(response.created_uris)} KGTypes",
                {
                    "created_count": response.created_count,
                    "created_uris": response.created_uris,
                    "message": response.message,
                    "response_type": type(response).__name__
                }
            )
            
            return response.created_uris if success else []
            
        except Exception as e:
            self.log_test_result("Create KGTypes", False, f"Exception: {e}")
            return []
    
    def test_get_kgtype(self, kgtype_uri: str):
        """Test retrieving a specific KGType by URI."""
        if not kgtype_uri:
            self.log_test_result("Get KGType", False, "No KGType URI provided")
            return
        
        try:
            response = self.client.get_kgtype(self.test_space_id, self.test_graph_id, kgtype_uri)
            
            # Handle both KGTypeListResponse and JsonLdDocument return types
            success = False
            kgtype_name = None
            types_count = 0
            
            if isinstance(response, KGTypeListResponse):
                # Standard KGTypeListResponse format
                success = (
                    hasattr(response, 'types') and
                    hasattr(response.types, 'graph') and
                    response.types.graph and
                    len(response.types.graph) > 0
                )
                if success and response.types.graph:
                    # Find the KGType in the response
                    for item in response.types.graph:
                        if item.get('@id') == kgtype_uri:
                            kgtype_name = item.get('vital-core:hasName', 'Unknown')
                            break
                    types_count = len(response.types.graph)
            elif hasattr(response, 'graph') and response.graph:
                # Direct JsonLdDocument format
                success = len(response.graph) > 0
                if success:
                    # Find the KGType in the response
                    for item in response.graph:
                        if item.get('@id') == kgtype_uri:
                            kgtype_name = item.get('vital-core:hasName', 'Unknown')
                            break
                    types_count = len(response.graph)
            elif hasattr(response, 'id') and response.id == kgtype_uri:
                # Single object JsonLdDocument format
                success = True
                kgtype_name = getattr(response, 'http://vital.ai/ontology/vital-core#hasName', {}).get('@value', 'Unknown')
                types_count = 1
            
            self.log_test_result(
                "Get KGType",
                success,
                f"Retrieved KGType: {kgtype_uri}",
                {
                    "uri": kgtype_uri,
                    "name": kgtype_name,
                    "types_count": types_count,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Get KGType", False, f"Exception: {e}")
    
    def test_list_kgtypes_with_data(self):
        """Test listing KGTypes when KGTypes exist."""
        try:
            response = self.client.list_kgtypes(self.test_space_id, self.test_graph_id, page_size=10, offset=0)
            
            success = (
                isinstance(response, KGTypeListResponse) and
                hasattr(response, 'types') and
                hasattr(response, 'total_count') and
                response.total_count > 0
            )
            
            types_count = 0
            type_names = []
            if hasattr(response.types, 'graph') and response.types.graph:
                types_count = len(response.types.graph)
                for type_data in response.types.graph:
                    type_name = type_data.get('vital-core:hasName', 'Unknown')
                    type_names.append(type_name)
            
            self.log_test_result(
                "List KGTypes (With Data)",
                success,
                f"Found {types_count} KGTypes, total_count: {response.total_count}",
                {
                    "types_count": types_count,
                    "total_count": response.total_count,
                    "type_names": type_names[:3],  # Show first 3 names
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("List KGTypes (With Data)", False, f"Exception: {e}")
    
    def test_search_kgtypes(self):
        """Test searching KGTypes with filters."""
        try:
            response = self.client.list_kgtypes(
                self.test_space_id, 
                self.test_graph_id, 
                page_size=10, 
                offset=0, 
                search="test"
            )
            
            success = (
                isinstance(response, KGTypeListResponse) and
                hasattr(response, 'types') and
                hasattr(response, 'total_count')
            )
            
            types_count = 0
            if hasattr(response.types, 'graph') and response.types.graph:
                types_count = len(response.types.graph)
            
            self.log_test_result(
                "Search KGTypes",
                success,
                f"Search found {types_count} KGTypes matching 'test'",
                {
                    "search_term": "test",
                    "types_count": types_count,
                    "total_count": response.total_count,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Search KGTypes", False, f"Exception: {e}")
    
    def test_update_kgtypes(self, kgtype_uris: List[str]):
        """Test updating existing KGTypes."""
        if not kgtype_uris:
            self.log_test_result("Update KGTypes", False, "No KGType URIs provided")
            return
        
        try:
            # Create updated KGType using VitalSigns
            updated_type = KGType()
            updated_type.URI = kgtype_uris[0]
            updated_type.name = "UpdatedTestType"
            updated_type.kGraphDescription = "An updated test type for VitalSigns mock client testing"
            updated_type.kGTypeVersion = "2.0.0"
            updated_type.kGModelVersion = "2.0.0"
            
            # Convert to JSON-LD using VitalSigns
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            jsonld_data = GraphObject.to_jsonld_list([updated_type])
            
            # Ensure the JSON-LD has a graph array format
            if 'graph' not in jsonld_data or jsonld_data['graph'] is None:
                # Convert single object format to graph array format
                single_obj = {k: v for k, v in jsonld_data.items() if k not in ['@context']}
                jsonld_data['graph'] = [single_obj]
            
            # Create JsonLdDocument
            update_document = JsonLdDocument(**jsonld_data)
            
            response = self.client.update_kgtypes(self.test_space_id, self.test_graph_id, update_document)
            
            success = (
                isinstance(response, KGTypeUpdateResponse) and
                hasattr(response, 'updated_uri') and
                response.updated_uri != ""
            )
            
            self.log_test_result(
                "Update KGTypes",
                success,
                f"Updated KGType: {response.updated_uri if success else 'None'}",
                {
                    "updated_uri": response.updated_uri if hasattr(response, 'updated_uri') else None,
                    "message": response.message if hasattr(response, 'message') else None,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Update KGTypes", False, f"Exception: {e}")
    
    def test_delete_kgtype(self, kgtype_uri: str):
        """Test deleting a single KGType."""
        if not kgtype_uri:
            self.log_test_result("Delete KGType", False, "No KGType URI provided")
            return
        
        try:
            response = self.client.delete_kgtype(self.test_space_id, self.test_graph_id, kgtype_uri)
            
            success = (
                isinstance(response, KGTypeDeleteResponse) and
                hasattr(response, 'deleted_count') and
                response.deleted_count > 0
            )
            
            if success and kgtype_uri in self.created_kgtypes:
                self.created_kgtypes.remove(kgtype_uri)
            
            self.log_test_result(
                "Delete KGType",
                success,
                f"Deleted KGType: {kgtype_uri}",
                {
                    "deleted_count": response.deleted_count,
                    "deleted_uris": response.deleted_uris if hasattr(response, 'deleted_uris') else [],
                    "message": response.message if hasattr(response, 'message') else None,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Delete KGType", False, f"Exception: {e}")
    
    def test_delete_kgtypes_batch(self, kgtype_uris: List[str]):
        """Test batch deletion of KGTypes."""
        if not kgtype_uris:
            self.log_test_result("Delete KGTypes Batch", False, "No KGType URIs provided")
            return
        
        try:
            uri_list = ",".join(kgtype_uris)
            response = self.client.delete_kgtypes_batch(self.test_space_id, self.test_graph_id, uri_list)
            
            success = (
                isinstance(response, KGTypeDeleteResponse) and
                hasattr(response, 'deleted_count') and
                response.deleted_count > 0
            )
            
            if success:
                for uri in kgtype_uris:
                    if uri in self.created_kgtypes:
                        self.created_kgtypes.remove(uri)
            
            self.log_test_result(
                "Delete KGTypes Batch",
                success,
                f"Batch deleted {response.deleted_count} KGTypes",
                {
                    "deleted_count": response.deleted_count,
                    "deleted_uris": response.deleted_uris if hasattr(response, 'deleted_uris') else [],
                    "message": response.message if hasattr(response, 'message') else None,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Delete KGTypes Batch", False, f"Exception: {e}")
    
    def test_error_handling_nonexistent_space(self):
        """Test error handling with nonexistent space."""
        try:
            # Test with nonexistent space
            response = self.client.list_kgtypes("nonexistent_space_12345", self.test_graph_id)
            
            success = (
                isinstance(response, KGTypeListResponse) and
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
    
    def test_error_handling_nonexistent_kgtype(self):
        """Test error handling for non-existent KGType operations."""
        try:
            # Try to get a non-existent KGType
            response = self.client.get_kgtype(
                self.test_space_id, 
                self.test_graph_id, 
                "http://nonexistent.kgtype/uri-12345"
            )
            
            # Should handle gracefully - either return empty response or None
            success = True  # If no exception thrown, it's handling gracefully
            
            types_count = 0
            if response and hasattr(response, 'types') and hasattr(response.types, 'graph'):
                types_count = len(response.types.graph) if response.types.graph else 0
            
            self.log_test_result(
                "Error Handling (Non-existent KGType)",
                success,
                "Gracefully handled non-existent KGType request",
                {
                    "requested_uri": "http://nonexistent.kgtype/uri-12345",
                    "types_count": types_count
                }
            )
            
        except Exception as e:
            # Check if it's a reasonable error response
            success = "not found" in str(e).lower() or "does not exist" in str(e).lower()
            self.log_test_result(
                "Error Handling (Non-existent KGType)",
                success,
                f"Exception: {e}"
            )
    
    def test_list_kgtypes_after_operations(self):
        """Test listing KGTypes after all operations (should be empty or reduced)."""
        try:
            response = self.client.list_kgtypes(self.test_space_id, self.test_graph_id)
            
            success = isinstance(response, KGTypeListResponse)
            
            types_count = 0
            if hasattr(response.types, 'graph') and response.types.graph:
                types_count = len(response.types.graph)
            
            self.log_test_result(
                "List KGTypes (After Operations)",
                success,
                f"Found {types_count} KGTypes after operations",
                {
                    "types_count": types_count,
                    "total_count": response.total_count if hasattr(response, 'total_count') else 0
                }
            )
            
        except Exception as e:
            self.log_test_result("List KGTypes (After Operations)", False, f"Exception: {e}")
    
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
    
    def cleanup_remaining_kgtypes(self):
        """Clean up any remaining KGTypes."""
        try:
            cleanup_count = 0
            for kgtype_uri in self.created_kgtypes[:]:  # Copy list to avoid modification during iteration
                try:
                    response = self.client.delete_kgtype(self.test_space_id, self.test_graph_id, kgtype_uri)
                    if hasattr(response, 'deleted_count') and response.deleted_count > 0:
                        cleanup_count += 1
                        self.created_kgtypes.remove(kgtype_uri)
                except:
                    pass  # Ignore cleanup errors
            
            if cleanup_count > 0:
                print(f"🧹 Cleaned up {cleanup_count} remaining KGTypes")
                
        except Exception as e:
            print(f"⚠️  Cleanup error: {e}")
    
    def run_all_tests(self):
        """Run all tests in sequence."""
        print("🧪 Testing MockVitalGraphClient KGTypes Operations")
        print("=" * 60)
        
        # Run tests in logical order
        self.test_client_initialization()
        self.test_client_connection()
        self.test_create_test_space()
        self.test_create_test_graph()
        self.test_list_kgtypes_empty()
        
        # Basic KGTypes CRUD operations
        kgtype_uris = self.test_create_kgtypes()
        if kgtype_uris:
            self.test_get_kgtype(kgtype_uris[0])
            self.test_list_kgtypes_with_data()
            self.test_search_kgtypes()
            self.test_update_kgtypes(kgtype_uris)
            
            # Test deletion operations
            if len(kgtype_uris) > 1:
                # Delete one KGType individually
                self.test_delete_kgtype(kgtype_uris[0])
                # Delete remaining KGTypes in batch
                self.test_delete_kgtypes_batch(kgtype_uris[1:])
            else:
                self.test_delete_kgtypes_batch(kgtype_uris)
        
        # Error handling and edge cases
        self.test_error_handling_nonexistent_space()
        self.test_error_handling_nonexistent_kgtype()
        
        # Final verification
        self.test_list_kgtypes_after_operations()
        
        # Cleanup any remaining KGTypes
        self.cleanup_remaining_kgtypes()
        
        # Disconnect client
        self.test_client_disconnection()
        
        # Print summary
        print("=" * 60)
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        
        if passed == total:
            print(f"Test Results: {passed}/{total} tests passed")
            print("🎉 All tests passed! MockVitalGraphClient KGTypes operations are working correctly.")
        else:
            print(f"Test Results: {passed}/{total} tests passed")
            print("⚠️  Some tests failed. Check the output above for details.")
        
        return passed == total


def main():
    """Main test runner."""
    test_suite = TestMockClientKGTypes()
    success = test_suite.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
