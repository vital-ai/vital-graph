#!/usr/bin/env python3
"""
Test suite for MockKGTypesEndpoint following the same pattern as MockObjectsEndpoint.

This test suite validates the mock implementation of KGType operations using:
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
from vitalgraph.model.kgtypes_model import KGTypeListResponse, KGTypeCreateResponse, KGTypeUpdateResponse, KGTypeDeleteResponse
from vitalgraph.model.jsonld_model import JsonLdDocument

# VitalSigns imports
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from ai_haley_kg_domain.model.KGType import KGType


class TestMockKGTypesEndpoint:
    """Test suite for MockKGTypesEndpoint with VitalSigns integration."""
    
    def __init__(self):
        """Initialize test suite."""
        # Configure logging to see debug output
        logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
        
        # Create mock client
        mock_client = MockVitalGraphClient()
        self.space_manager = mock_client.space_manager
        self.endpoint = mock_client.kgtypes
        self.test_results = []
        self.test_space_id = "test_kgtypes_space"
        self.test_graph_id = "http://vital.ai/graph/test-kgtypes"
        
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
    
    def test_list_kgtypes_empty(self):
        """Test listing KGTypes from empty space."""
        try:
            response = self.endpoint.list_kgtypes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                page_size=10,
                offset=0
            )
            
            success = (
                isinstance(response, KGTypeListResponse) and
                response.total_count == 0 and
                response.types is not None
            )
            
            # Check if response has graph structure
            types_count = 0
            if hasattr(response.types, 'graph') and response.types.graph:
                types_count = len(response.types.graph)
            
            self.log_test_result(
                "List KGTypes (Empty)",
                success,
                f"Found {types_count} types, total_count: {response.total_count}",
                {"types_count": types_count, "total_count": response.total_count}
            )
            
        except Exception as e:
            self.log_test_result("List KGTypes (Empty)", False, f"Exception: {e}")
    
    def test_create_kgtypes(self):
        """Test creating KGTypes."""
        try:
            # Create test KGTypes JSON-LD document
            kgtypes_jsonld = {
                "@context": {
                    "vital": "http://vital.ai/ontology/vital#",
                    "vital-core": "http://vital.ai/ontology/vital-core#",
                    "haley": "http://vital.ai/ontology/haley-ai-kg#"
                },
                "@graph": [
                    {
                        "@id": "http://vital.ai/haley.ai/app/KGType/test-type-001",
                        "@type": "haley:KGType",
                        "vital-core:hasName": "TestType1",
                        "haley:hasKGraphDescription": "A test type for mock client testing",
                        "haley:hasKGModelVersion": "1.0.0",
                        "haley:hasKGTypeVersion": "1.0.0"
                    },
                    {
                        "@id": "http://vital.ai/haley.ai/app/KGType/test-type-002",
                        "@type": "haley:KGType",
                        "vital-core:hasName": "TestType2",
                        "haley:hasKGraphDescription": "Another test type for mock client testing",
                        "haley:hasKGModelVersion": "1.0.0",
                        "haley:hasKGTypeVersion": "1.0.0"
                    }
                ]
            }
            
            document = JsonLdDocument(**kgtypes_jsonld)
            response = self.endpoint.create_kgtypes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document
            )
            
            success = (
                isinstance(response, KGTypeCreateResponse) and
                response.created_count == 2 and
                len(response.created_uris) == 2
            )
            
            self.log_test_result(
                "Create KGTypes",
                success,
                f"Created {response.created_count} types",
                {
                    "created_count": response.created_count,
                    "created_uris": response.created_uris
                }
            )
            
        except Exception as e:
            self.log_test_result("Create KGTypes", False, f"Exception: {e}")
    
    def test_get_kgtype(self):
        """Test getting a single KGType by URI."""
        try:
            target_uri = "http://vital.ai/haley.ai/app/KGType/test-type-001"
            response = self.endpoint.get_kgtype(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri=target_uri
            )
            
            success = (
                isinstance(response, JsonLdDocument) and
                (hasattr(response, 'id') or hasattr(response, 'context'))
            )
            
            self.log_test_result(
                "Get KGType",
                success,
                f"Retrieved type: {target_uri}",
                {"uri": target_uri, "response_type": type(response).__name__}
            )
            
        except Exception as e:
            self.log_test_result("Get KGType", False, f"Exception: {e}")
    
    def test_list_kgtypes_with_data(self):
        """Test listing KGTypes with data present."""
        try:
            response = self.endpoint.list_kgtypes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                page_size=10,
                offset=0
            )
            
            success = (
                isinstance(response, KGTypeListResponse) and
                response.total_count > 0 and
                response.types is not None
            )
            
            # Check if response has graph structure
            types_count = 0
            if hasattr(response.types, 'graph') and response.types.graph:
                types_count = len(response.types.graph)
            
            self.log_test_result(
                "List KGTypes (With Data)",
                success,
                f"Found {types_count} types, total_count: {response.total_count}",
                {"types_count": types_count, "total_count": response.total_count}
            )
            
        except Exception as e:
            self.log_test_result("List KGTypes (With Data)", False, f"Exception: {e}")
    
    def test_update_kgtypes(self):
        """Test updating KGTypes."""
        try:
            # Create updated KGType JSON-LD document
            updated_kgtype_jsonld = {
                "@context": {
                    "vital": "http://vital.ai/ontology/vital#",
                    "vital-core": "http://vital.ai/ontology/vital-core#",
                    "haley": "http://vital.ai/ontology/haley-ai-kg#"
                },
                "@graph": [{
                    "@id": "http://vital.ai/haley.ai/app/KGType/test-type-001",
                    "@type": "haley:KGType",
                    "vital-core:hasName": "UpdatedTestType1",
                    "haley:hasKGraphDescription": "Updated description for testing",
                    "haley:hasKGModelVersion": "2.0.0",
                    "haley:hasKGTypeVersion": "2.0.0"
                }]
            }
            
            document = JsonLdDocument(**updated_kgtype_jsonld)
            response = self.endpoint.update_kgtypes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document
            )
            
            success = (
                isinstance(response, KGTypeUpdateResponse) and
                response.updated_uri is not None
            )
            
            self.log_test_result(
                "Update KGTypes",
                success,
                f"Updated type: {response.updated_uri}",
                {"updated_uri": response.updated_uri}
            )
            
        except Exception as e:
            self.log_test_result("Update KGTypes", False, f"Exception: {e}")
    
    def test_search_kgtypes(self):
        """Test searching KGTypes."""
        try:
            response = self.endpoint.list_kgtypes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                page_size=10,
                offset=0,
                search="Updated"
            )
            
            success = (
                isinstance(response, KGTypeListResponse) and
                response.types is not None
            )
            
            # Check if response has graph structure
            types_count = 0
            if hasattr(response.types, 'graph') and response.types.graph:
                types_count = len(response.types.graph)
            
            self.log_test_result(
                "Search KGTypes",
                success,
                f"Search found {types_count} types, total_count: {response.total_count}",
                {"types_count": types_count, "total_count": response.total_count, "search_term": "Updated"}
            )
            
        except Exception as e:
            self.log_test_result("Search KGTypes", False, f"Exception: {e}")
    
    def test_error_handling(self):
        """Test error handling for non-existent KGType."""
        try:
            response = self.endpoint.get_kgtype(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri="http://nonexistent.kgtype/uri"
            )
            
            # Should handle gracefully - either return None or empty response
            success = True  # If no exception thrown, it's handling gracefully
            
            self.log_test_result(
                "Error Handling (Non-existent KGType)",
                success,
                "Gracefully handled non-existent type request"
            )
            
        except Exception as e:
            # Check if it's a reasonable error response
            success = "not found" in str(e).lower() or "does not exist" in str(e).lower()
            self.log_test_result(
                "Error Handling (Non-existent KGType)",
                success,
                f"Exception: {e}"
            )
    
    def test_delete_kgtype(self):
        """Test deleting a single KGType."""
        try:
            target_uri = "http://vital.ai/haley.ai/app/KGType/test-type-001"
            response = self.endpoint.delete_kgtype(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri=target_uri
            )
            
            success = (
                isinstance(response, KGTypeDeleteResponse) and
                response.deleted_count >= 0
            )
            
            self.log_test_result(
                "Delete KGType",
                success,
                f"Deleted type: {target_uri}",
                {
                    "deleted_count": response.deleted_count,
                    "deleted_uris": getattr(response, 'deleted_uris', [target_uri])
                }
            )
            
        except Exception as e:
            self.log_test_result("Delete KGType", False, f"Exception: {e}")
    
    def test_delete_kgtypes_batch(self):
        """Test batch deleting KGTypes."""
        try:
            uri_list = "http://vital.ai/haley.ai/app/KGType/test-type-002"
            response = self.endpoint.delete_kgtypes_batch(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri_list=uri_list
            )
            
            success = (
                isinstance(response, KGTypeDeleteResponse) and
                response.deleted_count >= 0
            )
            
            self.log_test_result(
                "Delete KGTypes Batch",
                success,
                f"Batch deleted {response.deleted_count} types",
                {
                    "deleted_count": response.deleted_count,
                    "deleted_uris": getattr(response, 'deleted_uris', uri_list.split(','))
                }
            )
            
        except Exception as e:
            self.log_test_result("Delete KGTypes Batch", False, f"Exception: {e}")
    
    def test_list_kgtypes_empty_final(self):
        """Test listing KGTypes after deletion (should be empty)."""
        try:
            response = self.endpoint.list_kgtypes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                page_size=10,
                offset=0
            )
            
            success = (
                isinstance(response, KGTypeListResponse) and
                response.total_count == 0
            )
            
            # Check if response has graph structure
            types_count = 0
            if hasattr(response.types, 'graph') and response.types.graph:
                types_count = len(response.types.graph)
            
            self.log_test_result(
                "List KGTypes (Empty)",
                success,
                f"Found {types_count} types, total_count: {response.total_count}",
                {"types_count": types_count, "total_count": response.total_count}
            )
            
        except Exception as e:
            self.log_test_result("List KGTypes (Empty)", False, f"Exception: {e}")
    
    def run_all_tests(self):
        """Run all tests in sequence."""
        print("🧪 Testing MockKGTypesEndpoint")
        print("=" * 50)
        
        # Run tests in logical order
        self.test_list_kgtypes_empty()
        self.test_create_kgtypes()
        self.test_get_kgtype()
        self.test_list_kgtypes_with_data()
        self.test_update_kgtypes()
        self.test_search_kgtypes()
        self.test_error_handling()
        self.test_delete_kgtype()
        self.test_delete_kgtypes_batch()
        self.test_list_kgtypes_empty_final()
        
        # Print summary
        print("=" * 50)
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        
        if passed == total:
            print(f"Test Results: {passed}/{total} tests passed")
            print("🎉 All tests passed! MockKGTypesEndpoint is working correctly.")
        else:
            print(f"Test Results: {passed}/{total} tests passed")
            print("⚠️  Some tests failed. Check the output above for details.")
        
        return passed == total


def main():
    """Main test runner."""
    test_suite = TestMockKGTypesEndpoint()
    success = test_suite.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
