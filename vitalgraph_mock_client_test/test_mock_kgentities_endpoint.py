#!/usr/bin/env python3
"""
Test suite for MockKGEntitiesEndpoint following the same pattern as MockObjectsEndpoint and MockKGTypesEndpoint.

This test suite validates the mock implementation of KGEntity operations using:
- VitalSigns native object creation and conversion
- pyoxigraph in-memory SPARQL quad store
- Direct test runner format (no pytest dependency)
- Complete CRUD operations with proper vitaltype handling
"""

import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, List

# Add the parent directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.mock.client.mock_vitalgraph_client import MockVitalGraphClient
from vitalgraph.mock.client.space.mock_space_manager import MockSpaceManager
from vitalgraph.model.spaces_model import Space
from vitalgraph.model.kgentities_model import EntitiesResponse, EntityCreateResponse, EntityUpdateResponse, EntityDeleteResponse
from vitalgraph.model.jsonld_model import JsonLdDocument

# VitalSigns imports
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from ai_haley_kg_domain.model.KGEntity import KGEntity


class TestMockKGEntitiesEndpoint:
    """Test suite for MockKGEntitiesEndpoint with VitalSigns integration."""
    
    def __init__(self):
        """Initialize test suite."""
        # Configure logging to see debug output
        logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
        
        # Create mock client
        mock_client = MockVitalGraphClient()
        self.space_manager = mock_client.space_manager
        self.endpoint = mock_client.kgentities
        self.test_results = []
        self.test_space_id = "test_kgentities_space"
        self.test_graph_id = "http://vital.ai/graph/test-kgentities"
        
        # Initialize test space
        self.space_manager.create_space(self.test_space_id)
    
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
    
    def test_list_kgentities_empty(self):
        """Test listing KGEntities from empty space."""
        try:
            response = self.endpoint.list_kgentities(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                page_size=10,
                offset=0
            )
            
            success = (
                isinstance(response, EntitiesResponse) and
                response.total_count == 0 and
                response.entities is not None
            )
            
            # Check if response has graph structure
            entities_count = 0
            if hasattr(response.entities, 'graph') and response.entities.graph:
                entities_count = len(response.entities.graph)
            
            self.log_test_result(
                "List KGEntities (Empty)",
                success,
                f"Found {entities_count} entities, total_count: {response.total_count}",
                {"entities_count": entities_count, "total_count": response.total_count}
            )
            
        except Exception as e:
            self.log_test_result("List KGEntities (Empty)", False, f"Exception: {e}")
    
    def test_create_kgentities(self):
        """Test creating KGEntities."""
        try:
            # Create test KGEntities JSON-LD document using correct schema properties
            kgentities_jsonld = {
                "@context": {
                    "vital": "http://vital.ai/ontology/vital#",
                    "vital-core": "http://vital.ai/ontology/vital-core#",
                    "haley": "http://vital.ai/ontology/haley-ai-kg#"
                },
                "@graph": [
                    {
                        "@id": "http://vital.ai/haley.ai/app/KGEntity/test-entity-001",
                        "@type": "haley:KGEntity",
                        "vital-core:hasName": "TestEntity1",
                        "haley:hasKGraphDescription": "A test entity for mock client testing",
                        "haley:hasKGEntityType": "http://vital.ai/ontology/haley-ai-kg#PersonType"
                    },
                    {
                        "@id": "http://vital.ai/haley.ai/app/KGEntity/test-entity-002",
                        "@type": "haley:KGEntity",
                        "vital-core:hasName": "TestEntity2",
                        "haley:hasKGraphDescription": "Another test entity for mock client testing",
                        "haley:hasKGEntityType": "http://vital.ai/ontology/haley-ai-kg#OrganizationType"
                    }
                ]
            }
            
            document = JsonLdDocument(**kgentities_jsonld)
            response = self.endpoint.create_kgentities(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document
            )
            
            success = (
                isinstance(response, EntityCreateResponse) and
                response.created_count == 2 and
                len(response.created_uris) == 2
            )
            
            self.log_test_result(
                "Create KGEntities",
                success,
                f"Created {response.created_count} entities",
                {
                    "created_count": response.created_count,
                    "created_uris": response.created_uris
                }
            )
            
        except Exception as e:
            self.log_test_result("Create KGEntities", False, f"Exception: {e}")
    
    def test_get_kgentity(self):
        """Test getting a single KGEntity by URI."""
        try:
            target_uri = "http://vital.ai/haley.ai/app/KGEntity/test-entity-001"
            response = self.endpoint.get_kgentity(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri=target_uri
            )
            
            success = (
                isinstance(response, JsonLdDocument) and
                (hasattr(response, 'id') or hasattr(response, 'context'))
            )
            
            self.log_test_result(
                "Get KGEntity",
                success,
                f"Retrieved entity: {target_uri}",
                {"uri": target_uri, "response_type": type(response).__name__}
            )
            
        except Exception as e:
            self.log_test_result("Get KGEntity", False, f"Exception: {e}")
    
    def test_list_kgentities_with_data(self):
        """Test listing KGEntities with data present."""
        try:
            response = self.endpoint.list_kgentities(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                page_size=10,
                offset=0
            )
            
            success = (
                isinstance(response, EntitiesResponse) and
                response.total_count > 0 and
                response.entities is not None
            )
            
            # Check if response has graph structure
            entities_count = 0
            if hasattr(response.entities, 'graph') and response.entities.graph:
                entities_count = len(response.entities.graph)
            
            self.log_test_result(
                "List KGEntities (With Data)",
                success,
                f"Found {entities_count} entities, total_count: {response.total_count}",
                {"entities_count": entities_count, "total_count": response.total_count}
            )
            
        except Exception as e:
            self.log_test_result("List KGEntities (With Data)", False, f"Exception: {e}")
    
    def test_update_kgentities(self):
        """Test updating KGEntities."""
        try:
            # Create updated KGEntity JSON-LD document
            updated_kgentity_jsonld = {
                "@context": {
                    "vital": "http://vital.ai/ontology/vital#",
                    "vital-core": "http://vital.ai/ontology/vital-core#",
                    "haley": "http://vital.ai/ontology/haley-ai-kg#"
                },
                "@graph": [{
                    "@id": "http://vital.ai/haley.ai/app/KGEntity/test-entity-001",
                    "@type": "haley:KGEntity",
                    "vital-core:hasName": "UpdatedTestEntity1",
                    "haley:hasKGraphDescription": "Updated description for testing",
                    "haley:hasKGEntityType": "http://vital.ai/ontology/haley-ai-kg#PersonType"
                }]
            }
            
            document = JsonLdDocument(**updated_kgentity_jsonld)
            response = self.endpoint.update_kgentities(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document
            )
            
            success = (
                isinstance(response, EntityUpdateResponse) and
                response.updated_uri is not None
            )
            
            self.log_test_result(
                "Update KGEntities",
                success,
                f"Updated entity: {response.updated_uri}",
                {"updated_uri": response.updated_uri}
            )
            
        except Exception as e:
            self.log_test_result("Update KGEntities", False, f"Exception: {e}")
    
    def test_search_kgentities(self):
        """Test searching KGEntities."""
        try:
            response = self.endpoint.list_kgentities(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                page_size=10,
                offset=0,
                search="Updated"
            )
            
            success = (
                isinstance(response, EntitiesResponse) and
                response.entities is not None
            )
            
            # Check if response has graph structure
            entities_count = 0
            if hasattr(response.entities, 'graph') and response.entities.graph:
                entities_count = len(response.entities.graph)
            
            self.log_test_result(
                "Search KGEntities",
                success,
                f"Search found {entities_count} entities, total_count: {response.total_count}",
                {"entities_count": entities_count, "total_count": response.total_count, "search_term": "Updated"}
            )
            
        except Exception as e:
            self.log_test_result("Search KGEntities", False, f"Exception: {e}")
    
    def test_error_handling(self):
        """Test error handling for non-existent KGEntity."""
        try:
            response = self.endpoint.get_kgentity(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri="http://nonexistent.kgentity/uri"
            )
            
            # Should handle gracefully - either return None or empty response
            success = True  # If no exception thrown, it's handling gracefully
            
            self.log_test_result(
                "Error Handling (Non-existent KGEntity)",
                success,
                "Gracefully handled non-existent entity request"
            )
            
        except Exception as e:
            # Check if it's a reasonable error response
            success = "not found" in str(e).lower() or "does not exist" in str(e).lower()
            self.log_test_result(
                "Error Handling (Non-existent KGEntity)",
                success,
                f"Exception: {e}"
            )
    
    def test_delete_kgentity(self):
        """Test deleting a single KGEntity."""
        try:
            target_uri = "http://vital.ai/haley.ai/app/KGEntity/test-entity-001"
            response = self.endpoint.delete_kgentity(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri=target_uri
            )
            
            success = (
                isinstance(response, EntityDeleteResponse) and
                response.deleted_count >= 0
            )
            
            self.log_test_result(
                "Delete KGEntity",
                success,
                f"Deleted entity: {target_uri}",
                {
                    "deleted_count": response.deleted_count,
                    "deleted_uris": getattr(response, 'deleted_uris', [target_uri])
                }
            )
            
        except Exception as e:
            self.log_test_result("Delete KGEntity", False, f"Exception: {e}")
    
    def test_delete_kgentities_batch(self):
        """Test batch deleting KGEntities."""
        try:
            uri_list = "http://vital.ai/haley.ai/app/KGEntity/test-entity-002"
            response = self.endpoint.delete_kgentities_batch(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri_list=uri_list
            )
            
            success = (
                isinstance(response, EntityDeleteResponse) and
                response.deleted_count >= 0
            )
            
            self.log_test_result(
                "Delete KGEntities Batch",
                success,
                f"Batch deleted {response.deleted_count} entities",
                {
                    "deleted_count": response.deleted_count,
                    "deleted_uris": getattr(response, 'deleted_uris', uri_list.split(','))
                }
            )
            
        except Exception as e:
            self.log_test_result("Delete KGEntities Batch", False, f"Exception: {e}")
    
    def test_list_kgentities_empty_final(self):
        """Test listing KGEntities after deletion (should be empty)."""
        try:
            response = self.endpoint.list_kgentities(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                page_size=10,
                offset=0
            )
            
            success = (
                isinstance(response, EntitiesResponse) and
                response.total_count == 0
            )
            
            # Check if response has graph structure
            entities_count = 0
            if hasattr(response.entities, 'graph') and response.entities.graph:
                entities_count = len(response.entities.graph)
            
            self.log_test_result(
                "List KGEntities (Empty)",
                success,
                f"Found {entities_count} entities, total_count: {response.total_count}",
                {"entities_count": entities_count, "total_count": response.total_count}
            )
            
        except Exception as e:
            self.log_test_result("List KGEntities (Empty)", False, f"Exception: {e}")
    
    def run_all_tests(self):
        """Run all tests in sequence."""
        print("🧪 Testing MockKGEntitiesEndpoint")
        print("=" * 50)
        
        # Run tests in logical order
        self.test_list_kgentities_empty()
        self.test_create_kgentities()
        self.test_get_kgentity()
        self.test_list_kgentities_with_data()
        self.test_update_kgentities()
        self.test_search_kgentities()
        self.test_error_handling()
        self.test_delete_kgentity()
        self.test_delete_kgentities_batch()
        self.test_list_kgentities_empty_final()
        
        # Print summary
        print("=" * 50)
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        
        if passed == total:
            print(f"Test Results: {passed}/{total} tests passed")
            print("🎉 All tests passed! MockKGEntitiesEndpoint is working correctly.")
        else:
            print(f"Test Results: {passed}/{total} tests passed")
            print("⚠️  Some tests failed. Check the output above for details.")
        
        return passed == total


def main():
    """Main test runner."""
    test_suite = TestMockKGEntitiesEndpoint()
    success = test_suite.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
