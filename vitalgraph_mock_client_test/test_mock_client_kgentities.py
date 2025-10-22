#!/usr/bin/env python3
"""
Test suite for MockVitalGraphClient KGEntities operations.

This test suite validates the mock client's KGEntities management functionality using:
- Direct client method calls (not endpoint calls)
- Proper request/response model validation
- Complete KGEntities CRUD operations with VitalSigns-compatible data
- Space and graph creation as prerequisites for KGEntities operations
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
from vitalgraph.model.kgentities_model import EntitiesResponse, EntityCreateResponse, EntityUpdateResponse, EntityDeleteResponse
from vitalgraph.model.jsonld_model import JsonLdDocument

# VitalSigns imports
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from ai_haley_kg_domain.model.KGEntity import KGEntity


class TestMockClientKGEntities:
    """Test suite for MockVitalGraphClient KGEntities operations."""
    
    def __init__(self):
        """Initialize test suite."""
        # Configure logging to see debug output
        logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
        
        self.test_results = []
        self.client = None
        self.test_space_id = "test_kgentities_space"
        self.test_graph_id = "http://vital.ai/graph/test-kgentities"
        self.created_kgentities = []  # Track created KGEntities for cleanup
        
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
                hasattr(self.client, 'list_kgentities') and
                hasattr(self.client, 'create_kgentities') and
                hasattr(self.client, 'update_kgentities') and
                hasattr(self.client, 'delete_kgentity') and
                hasattr(self.client, 'delete_kgentities_batch')
            )
            
            client_type = type(self.client).__name__
            
            self.log_test_result(
                "Client Initialization",
                success,
                f"Created client: {client_type}",
                {"client_type": client_type, "has_kgentity_methods": success}
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
        """Test creating a test space for KGEntities operations."""
        try:
            # Create test space (required for KGEntities operations)
            test_space = Space(
                space=self.test_space_id,
                space_name="Test KGEntities Space",
                space_description="A test space for KGEntities operations testing"
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
        """Test creating a test graph for KGEntities operations."""
        try:
            # Create test graph (required for KGEntities operations)
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
    
    def test_list_kgentities_empty(self):
        """Test listing KGEntities when no KGEntities exist in the graph."""
        try:
            response = self.client.list_kgentities(self.test_space_id, self.test_graph_id)
            
            success = (
                isinstance(response, EntitiesResponse) and
                hasattr(response, 'entities') and
                hasattr(response, 'total_count') and
                response.total_count == 0
            )
            
            entities_count = 0
            if hasattr(response.entities, 'graph') and response.entities.graph:
                entities_count = len(response.entities.graph)
            
            self.log_test_result(
                "List KGEntities (Empty)",
                success,
                f"Found {entities_count} KGEntities, total_count: {response.total_count}",
                {
                    "entities_count": entities_count,
                    "total_count": response.total_count,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("List KGEntities (Empty)", False, f"Exception: {e}")
    
    def _create_test_kgentities(self) -> List[KGEntity]:
        """Create test KGEntity objects using VitalSigns."""
        entities = []
        
        # Create first test KGEntity
        entity1 = KGEntity()
        entity1.URI = "http://vital.ai/haley.ai/app/KGEntity/test_entity_001"
        entity1.name = "TestEntity1"
        entity1.kGraphDescription = "A test entity for VitalSigns mock client testing"
        entity1.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#PersonType"
        entity1.kGModelVersion = "1.0.0"
        entities.append(entity1)
        
        # Create second test KGEntity
        entity2 = KGEntity()
        entity2.URI = "http://vital.ai/haley.ai/app/KGEntity/test_entity_002"
        entity2.name = "TestEntity2"
        entity2.kGraphDescription = "Another test entity for VitalSigns mock client testing"
        entity2.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#OrganizationType"
        entity2.kGModelVersion = "1.0.0"
        entities.append(entity2)
        
        # Create third test KGEntity
        entity3 = KGEntity()
        entity3.URI = "http://vital.ai/haley.ai/app/KGEntity/test_entity_003"
        entity3.name = "TestEntity3"
        entity3.kGraphDescription = "Third test entity for VitalSigns mock client testing"
        entity3.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#LocationType"
        entity3.kGModelVersion = "1.0.0"
        entities.append(entity3)
        
        return entities
    
    def test_create_kgentities(self):
        """Test creating new KGEntities."""
        try:
            # Create test KGEntities using VitalSigns
            test_entities = self._create_test_kgentities()
            
            # Convert to JSON-LD using VitalSigns
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            jsonld_data = GraphObject.to_jsonld_list(test_entities)
            
            # Create JsonLdDocument
            kgentities_document = JsonLdDocument(**jsonld_data)
            
            response = self.client.create_kgentities(self.test_space_id, self.test_graph_id, kgentities_document)
            
            success = (
                isinstance(response, EntityCreateResponse) and
                hasattr(response, 'created_uris') and
                isinstance(response.created_uris, list) and
                len(response.created_uris) == 3
            )
            
            if success:
                self.created_kgentities.extend(response.created_uris)
            
            self.log_test_result(
                "Create KGEntities",
                success,
                f"Created {len(response.created_uris)} KGEntities",
                {
                    "created_count": response.created_count,
                    "created_uris": response.created_uris,
                    "message": response.message,
                    "response_type": type(response).__name__
                }
            )
            
            return response.created_uris if success else []
            
        except Exception as e:
            self.log_test_result("Create KGEntities", False, f"Exception: {e}")
            return []
    
    def test_get_kgentity(self, kgentity_uri: str):
        """Test retrieving a specific KGEntity by URI."""
        if not kgentity_uri:
            self.log_test_result("Get KGEntity", False, "No KGEntity URI provided")
            return
        
        try:
            response = self.client.get_kgentity(self.test_space_id, self.test_graph_id, kgentity_uri)
            
            # Handle both EntitiesResponse and JsonLdDocument return types
            success = False
            kgentity_name = None
            entities_count = 0
            
            if isinstance(response, EntitiesResponse):
                # Standard EntitiesResponse format
                success = (
                    hasattr(response, 'entities') and
                    hasattr(response.entities, 'graph') and
                    response.entities.graph and
                    len(response.entities.graph) > 0
                )
                if success and response.entities.graph:
                    # Find the KGEntity in the response
                    for item in response.entities.graph:
                        if item.get('@id') == kgentity_uri:
                            kgentity_name = item.get('vital-core:hasName', 'Unknown')
                            break
                    entities_count = len(response.entities.graph)
            elif hasattr(response, 'graph') and response.graph:
                # Direct JsonLdDocument format
                success = len(response.graph) > 0
                if success:
                    # Find the KGEntity in the response
                    for item in response.graph:
                        if item.get('@id') == kgentity_uri:
                            kgentity_name = item.get('vital-core:hasName', 'Unknown')
                            break
                    entities_count = len(response.graph)
            elif hasattr(response, 'id') and response.id == kgentity_uri:
                # Single object JsonLdDocument format
                success = True
                kgentity_name = getattr(response, 'http://vital.ai/ontology/vital-core#hasName', {}).get('@value', 'Unknown')
                entities_count = 1
            
            self.log_test_result(
                "Get KGEntity",
                success,
                f"Retrieved KGEntity: {kgentity_uri}",
                {
                    "uri": kgentity_uri,
                    "name": kgentity_name,
                    "entities_count": entities_count,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Get KGEntity", False, f"Exception: {e}")
    
    def test_list_kgentities_with_data(self):
        """Test listing KGEntities when KGEntities exist."""
        try:
            response = self.client.list_kgentities(self.test_space_id, self.test_graph_id, page_size=10, offset=0)
            
            success = (
                isinstance(response, EntitiesResponse) and
                hasattr(response, 'entities') and
                hasattr(response, 'total_count') and
                response.total_count > 0
            )
            
            entities_count = 0
            entity_names = []
            if hasattr(response.entities, 'graph') and response.entities.graph:
                entities_count = len(response.entities.graph)
                for entity_data in response.entities.graph:
                    entity_name = entity_data.get('vital-core:hasName', 'Unknown')
                    entity_names.append(entity_name)
            
            self.log_test_result(
                "List KGEntities (With Data)",
                success,
                f"Found {entities_count} KGEntities, total_count: {response.total_count}",
                {
                    "entities_count": entities_count,
                    "total_count": response.total_count,
                    "entity_names": entity_names[:3],  # Show first 3 names
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("List KGEntities (With Data)", False, f"Exception: {e}")
    
    def test_search_kgentities(self):
        """Test searching KGEntities with filters."""
        try:
            response = self.client.list_kgentities(
                self.test_space_id, 
                self.test_graph_id, 
                page_size=10, 
                offset=0, 
                search="test"
            )
            
            success = (
                isinstance(response, EntitiesResponse) and
                hasattr(response, 'entities') and
                hasattr(response, 'total_count')
            )
            
            entities_count = 0
            if hasattr(response.entities, 'graph') and response.entities.graph:
                entities_count = len(response.entities.graph)
            
            self.log_test_result(
                "Search KGEntities",
                success,
                f"Search found {entities_count} KGEntities matching 'test'",
                {
                    "search_term": "test",
                    "entities_count": entities_count,
                    "total_count": response.total_count,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Search KGEntities", False, f"Exception: {e}")
    
    def test_update_kgentities(self, kgentity_uris: List[str]):
        """Test updating existing KGEntities."""
        if not kgentity_uris:
            self.log_test_result("Update KGEntities", False, "No KGEntity URIs provided")
            return
        
        try:
            # Create updated KGEntity using VitalSigns
            updated_entity = KGEntity()
            updated_entity.URI = kgentity_uris[0]
            updated_entity.name = "UpdatedTestEntity"
            updated_entity.kGraphDescription = "An updated test entity for VitalSigns mock client testing"
            updated_entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#UpdatedPersonType"
            updated_entity.kGModelVersion = "2.0.0"
            
            # Convert to JSON-LD using VitalSigns
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            jsonld_data = GraphObject.to_jsonld_list([updated_entity])
            
            # Ensure the JSON-LD has a graph array format
            if 'graph' not in jsonld_data or jsonld_data['graph'] is None:
                # Convert single object format to graph array format
                single_obj = {k: v for k, v in jsonld_data.items() if k not in ['@context']}
                jsonld_data['graph'] = [single_obj]
            
            # Create JsonLdDocument
            update_document = JsonLdDocument(**jsonld_data)
            
            response = self.client.update_kgentities(self.test_space_id, self.test_graph_id, update_document)
            
            success = (
                isinstance(response, EntityUpdateResponse) and
                hasattr(response, 'updated_uri') and
                response.updated_uri != ""
            )
            
            self.log_test_result(
                "Update KGEntities",
                success,
                f"Updated KGEntity: {response.updated_uri if success else 'None'}",
                {
                    "updated_uri": response.updated_uri if hasattr(response, 'updated_uri') else None,
                    "message": response.message if hasattr(response, 'message') else None,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Update KGEntities", False, f"Exception: {e}")
    
    def test_delete_kgentity(self, kgentity_uri: str):
        """Test deleting a single KGEntity."""
        if not kgentity_uri:
            self.log_test_result("Delete KGEntity", False, "No KGEntity URI provided")
            return
        
        try:
            response = self.client.delete_kgentity(self.test_space_id, self.test_graph_id, kgentity_uri)
            
            success = (
                isinstance(response, EntityDeleteResponse) and
                hasattr(response, 'deleted_count') and
                response.deleted_count > 0
            )
            
            if success and kgentity_uri in self.created_kgentities:
                self.created_kgentities.remove(kgentity_uri)
            
            self.log_test_result(
                "Delete KGEntity",
                success,
                f"Deleted KGEntity: {kgentity_uri}",
                {
                    "deleted_count": response.deleted_count,
                    "deleted_uris": response.deleted_uris if hasattr(response, 'deleted_uris') else [],
                    "message": response.message if hasattr(response, 'message') else None,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Delete KGEntity", False, f"Exception: {e}")
    
    def test_delete_kgentities_batch(self, kgentity_uris: List[str]):
        """Test batch deletion of KGEntities."""
        if not kgentity_uris:
            self.log_test_result("Delete KGEntities Batch", False, "No KGEntity URIs provided")
            return
        
        try:
            uri_list = ",".join(kgentity_uris)
            response = self.client.delete_kgentities_batch(self.test_space_id, self.test_graph_id, uri_list)
            
            success = (
                isinstance(response, EntityDeleteResponse) and
                hasattr(response, 'deleted_count') and
                response.deleted_count > 0
            )
            
            if success:
                for uri in kgentity_uris:
                    if uri in self.created_kgentities:
                        self.created_kgentities.remove(uri)
            
            self.log_test_result(
                "Delete KGEntities Batch",
                success,
                f"Batch deleted {response.deleted_count} KGEntities",
                {
                    "deleted_count": response.deleted_count,
                    "deleted_uris": response.deleted_uris if hasattr(response, 'deleted_uris') else [],
                    "message": response.message if hasattr(response, 'message') else None,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Delete KGEntities Batch", False, f"Exception: {e}")
    
    def test_error_handling_nonexistent_space(self):
        """Test error handling with nonexistent space."""
        try:
            # Test with nonexistent space
            response = self.client.list_kgentities("nonexistent_space_12345", self.test_graph_id)
            
            success = (
                isinstance(response, EntitiesResponse) and
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
    
    def test_error_handling_nonexistent_kgentity(self):
        """Test error handling for non-existent KGEntity operations."""
        try:
            # Try to get a non-existent KGEntity
            response = self.client.get_kgentity(
                self.test_space_id, 
                self.test_graph_id, 
                "http://nonexistent.kgentity/uri-12345"
            )
            
            # Should handle gracefully - either return empty response or None
            success = True  # If no exception thrown, it's handling gracefully
            
            entities_count = 0
            if response and hasattr(response, 'entities') and hasattr(response.entities, 'graph'):
                entities_count = len(response.entities.graph) if response.entities.graph else 0
            
            self.log_test_result(
                "Error Handling (Non-existent KGEntity)",
                success,
                "Gracefully handled non-existent KGEntity request",
                {
                    "requested_uri": "http://nonexistent.kgentity/uri-12345",
                    "entities_count": entities_count
                }
            )
            
        except Exception as e:
            # Check if it's a reasonable error response
            success = "not found" in str(e).lower() or "does not exist" in str(e).lower()
            self.log_test_result(
                "Error Handling (Non-existent KGEntity)",
                success,
                f"Exception: {e}"
            )
    
    def test_list_kgentities_after_operations(self):
        """Test listing KGEntities after all operations (should be empty or reduced)."""
        try:
            response = self.client.list_kgentities(self.test_space_id, self.test_graph_id)
            
            success = isinstance(response, EntitiesResponse)
            
            entities_count = 0
            if hasattr(response.entities, 'graph') and response.entities.graph:
                entities_count = len(response.entities.graph)
            
            self.log_test_result(
                "List KGEntities (After Operations)",
                success,
                f"Found {entities_count} KGEntities after operations",
                {
                    "entities_count": entities_count,
                    "total_count": response.total_count if hasattr(response, 'total_count') else 0
                }
            )
            
        except Exception as e:
            self.log_test_result("List KGEntities (After Operations)", False, f"Exception: {e}")
    
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
    
    def cleanup_remaining_kgentities(self):
        """Clean up any remaining KGEntities."""
        try:
            cleanup_count = 0
            for kgentity_uri in self.created_kgentities[:]:  # Copy list to avoid modification during iteration
                try:
                    response = self.client.delete_kgentity(self.test_space_id, self.test_graph_id, kgentity_uri)
                    if hasattr(response, 'deleted_count') and response.deleted_count > 0:
                        cleanup_count += 1
                        self.created_kgentities.remove(kgentity_uri)
                except:
                    pass  # Ignore cleanup errors
            
            if cleanup_count > 0:
                print(f"🧹 Cleaned up {cleanup_count} remaining KGEntities")
                
        except Exception as e:
            print(f"⚠️  Cleanup error: {e}")
    
    def run_all_tests(self):
        """Run all tests in sequence."""
        print("🧪 Testing MockVitalGraphClient KGEntities Operations")
        print("=" * 60)
        
        # Run tests in logical order
        self.test_client_initialization()
        self.test_client_connection()
        self.test_create_test_space()
        self.test_create_test_graph()
        self.test_list_kgentities_empty()
        
        # Basic KGEntities CRUD operations
        kgentity_uris = self.test_create_kgentities()
        if kgentity_uris:
            self.test_get_kgentity(kgentity_uris[0])
            self.test_list_kgentities_with_data()
            self.test_search_kgentities()
            self.test_update_kgentities(kgentity_uris)
            
            # Test deletion operations
            if len(kgentity_uris) > 1:
                # Delete one KGEntity individually
                self.test_delete_kgentity(kgentity_uris[0])
                # Delete remaining KGEntities in batch
                self.test_delete_kgentities_batch(kgentity_uris[1:])
            else:
                self.test_delete_kgentities_batch(kgentity_uris)
        
        # Error handling and edge cases
        self.test_error_handling_nonexistent_space()
        self.test_error_handling_nonexistent_kgentity()
        
        # Final verification
        self.test_list_kgentities_after_operations()
        
        # Cleanup any remaining KGEntities
        self.cleanup_remaining_kgentities()
        
        # Disconnect client
        self.test_client_disconnection()
        
        # Print summary
        print("=" * 60)
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        
        if passed == total:
            print(f"Test Results: {passed}/{total} tests passed")
            print("🎉 All tests passed! MockVitalGraphClient KGEntities operations are working correctly.")
        else:
            print(f"Test Results: {passed}/{total} tests passed")
            print("⚠️  Some tests failed. Check the output above for details.")
        
        return passed == total


def main():
    """Main test runner."""
    test_suite = TestMockClientKGEntities()
    success = test_suite.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
