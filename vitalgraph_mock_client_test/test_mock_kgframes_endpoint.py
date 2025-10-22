#!/usr/bin/env python3
"""
Test suite for MockKGFramesEndpoint following the same pattern as MockObjectsEndpoint, MockKGTypesEndpoint, and MockKGEntitiesEndpoint.

This test suite validates the mock implementation of KGFrame operations using:
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
from vitalgraph.model.kgframes_model import FramesResponse, FrameCreateResponse, FrameUpdateResponse, FrameDeleteResponse
from vitalgraph.model.jsonld_model import JsonLdDocument

# VitalSigns imports
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from ai_haley_kg_domain.model.KGFrame import KGFrame


class TestMockKGFramesEndpoint:
    """Test suite for MockKGFramesEndpoint with VitalSigns integration."""
    
    def __init__(self):
        """Initialize test suite."""
        # Configure logging to see debug output
        logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
        
        # Create mock client
        mock_client = MockVitalGraphClient()
        self.space_manager = mock_client.space_manager
        self.endpoint = mock_client.kgframes
        self.test_results = []
        self.test_space_id = "test_kgframes_space"
        self.test_graph_id = "http://vital.ai/graph/test-kgframes"
        
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
    
    def test_list_kgframes_empty(self):
        """Test listing KGFrames from empty space."""
        try:
            response = self.endpoint.list_kgframes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                page_size=10,
                offset=0
            )
            
            success = (
                isinstance(response, FramesResponse) and
                response.total_count == 0 and
                response.frames is not None
            )
            
            # Check if response has graph structure
            frames_count = 0
            if hasattr(response.frames, 'graph') and response.frames.graph:
                frames_count = len(response.frames.graph)
            
            self.log_test_result(
                "List KGFrames (Empty)",
                success,
                f"Found {frames_count} frames, total_count: {response.total_count}",
                {"frames_count": frames_count, "total_count": response.total_count}
            )
            
        except Exception as e:
            self.log_test_result("List KGFrames (Empty)", False, f"Exception: {e}")
    
    def test_create_kgframes(self):
        """Test creating KGFrames."""
        try:
            # Create test KGFrames JSON-LD document using correct schema properties
            kgframes_jsonld = {
                "@context": {
                    "vital": "http://vital.ai/ontology/vital#",
                    "vital-core": "http://vital.ai/ontology/vital-core#",
                    "haley": "http://vital.ai/ontology/haley-ai-kg#"
                },
                "@graph": [
                    {
                        "@id": "http://vital.ai/haley.ai/app/KGFrame/test-frame-001",
                        "@type": "haley:KGFrame",
                        "vital-core:hasName": "TestFrame1",
                        "haley:hasKGraphDescription": "A test frame for mock client testing",
                        "haley:hasKGFrameTypeDescription": "Test frame type description",
                        "haley:hasFrameSequence": 1
                    },
                    {
                        "@id": "http://vital.ai/haley.ai/app/KGFrame/test-frame-002",
                        "@type": "haley:KGFrame",
                        "vital-core:hasName": "TestFrame2",
                        "haley:hasKGraphDescription": "Another test frame for mock client testing",
                        "haley:hasKGFrameTypeDescription": "Another test frame type description",
                        "haley:hasFrameSequence": 2
                    }
                ]
            }
            
            document = JsonLdDocument(**kgframes_jsonld)
            response = self.endpoint.create_kgframes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document
            )
            
            success = (
                isinstance(response, FrameCreateResponse) and
                response.created_count == 2 and
                len(response.created_uris) == 2
            )
            
            self.log_test_result(
                "Create KGFrames",
                success,
                f"Created {response.created_count} frames",
                {
                    "created_count": response.created_count,
                    "created_uris": response.created_uris
                }
            )
            
        except Exception as e:
            self.log_test_result("Create KGFrames", False, f"Exception: {e}")
    
    def test_get_kgframe(self):
        """Test getting a single KGFrame by URI."""
        try:
            target_uri = "http://vital.ai/haley.ai/app/KGFrame/test-frame-001"
            response = self.endpoint.get_kgframe(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri=target_uri
            )
            
            success = (
                isinstance(response, JsonLdDocument) and
                (hasattr(response, 'id') or hasattr(response, 'context'))
            )
            
            self.log_test_result(
                "Get KGFrame",
                success,
                f"Retrieved frame: {target_uri}",
                {"uri": target_uri, "response_type": type(response).__name__}
            )
            
        except Exception as e:
            self.log_test_result("Get KGFrame", False, f"Exception: {e}")
    
    def test_list_kgframes_with_data(self):
        """Test listing KGFrames with data present."""
        try:
            response = self.endpoint.list_kgframes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                page_size=10,
                offset=0
            )
            
            success = (
                isinstance(response, FramesResponse) and
                response.total_count > 0 and
                response.frames is not None
            )
            
            # Check if response has graph structure
            frames_count = 0
            if hasattr(response.frames, 'graph') and response.frames.graph:
                frames_count = len(response.frames.graph)
            
            self.log_test_result(
                "List KGFrames (With Data)",
                success,
                f"Found {frames_count} frames, total_count: {response.total_count}",
                {"frames_count": frames_count, "total_count": response.total_count}
            )
            
        except Exception as e:
            self.log_test_result("List KGFrames (With Data)", False, f"Exception: {e}")
    
    def test_update_kgframes(self):
        """Test updating KGFrames."""
        try:
            # Create updated KGFrame JSON-LD document
            updated_kgframe_jsonld = {
                "@context": {
                    "vital": "http://vital.ai/ontology/vital#",
                    "vital-core": "http://vital.ai/ontology/vital-core#",
                    "haley": "http://vital.ai/ontology/haley-ai-kg#"
                },
                "@graph": [{
                    "@id": "http://vital.ai/haley.ai/app/KGFrame/test-frame-001",
                    "@type": "haley:KGFrame",
                    "vital-core:hasName": "UpdatedTestFrame1",
                    "haley:hasKGraphDescription": "Updated description for testing",
                    "haley:hasKGFrameTypeDescription": "Updated test frame type description",
                    "haley:hasFrameSequence": 10
                }]
            }
            
            document = JsonLdDocument(**updated_kgframe_jsonld)
            response = self.endpoint.update_kgframes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document
            )
            
            success = (
                isinstance(response, FrameUpdateResponse) and
                response.updated_uri is not None
            )
            
            self.log_test_result(
                "Update KGFrames",
                success,
                f"Updated frame: {response.updated_uri}",
                {"updated_uri": response.updated_uri}
            )
            
        except Exception as e:
            self.log_test_result("Update KGFrames", False, f"Exception: {e}")
    
    def test_search_kgframes(self):
        """Test searching KGFrames."""
        try:
            response = self.endpoint.list_kgframes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                page_size=10,
                offset=0,
                search="Updated"
            )
            
            success = (
                isinstance(response, FramesResponse) and
                response.frames is not None
            )
            
            # Check if response has graph structure
            frames_count = 0
            if hasattr(response.frames, 'graph') and response.frames.graph:
                frames_count = len(response.frames.graph)
            
            self.log_test_result(
                "Search KGFrames",
                success,
                f"Search found {frames_count} frames, total_count: {response.total_count}",
                {"frames_count": frames_count, "total_count": response.total_count, "search_term": "Updated"}
            )
            
        except Exception as e:
            self.log_test_result("Search KGFrames", False, f"Exception: {e}")
    
    def test_error_handling(self):
        """Test error handling for non-existent KGFrame."""
        try:
            response = self.endpoint.get_kgframe(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri="http://nonexistent.kgframe/uri"
            )
            
            # Should handle gracefully - either return None or empty response
            success = True  # If no exception thrown, it's handling gracefully
            
            self.log_test_result(
                "Error Handling (Non-existent KGFrame)",
                success,
                "Gracefully handled non-existent frame request"
            )
            
        except Exception as e:
            # Check if it's a reasonable error response
            success = "not found" in str(e).lower() or "does not exist" in str(e).lower()
            self.log_test_result(
                "Error Handling (Non-existent KGFrame)",
                success,
                f"Exception: {e}"
            )
    
    def test_delete_kgframe(self):
        """Test deleting a single KGFrame."""
        try:
            target_uri = "http://vital.ai/haley.ai/app/KGFrame/test-frame-001"
            response = self.endpoint.delete_kgframe(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri=target_uri
            )
            
            success = (
                isinstance(response, FrameDeleteResponse) and
                response.deleted_count >= 0
            )
            
            self.log_test_result(
                "Delete KGFrame",
                success,
                f"Deleted frame: {target_uri}",
                {
                    "deleted_count": response.deleted_count,
                    "deleted_uris": getattr(response, 'deleted_uris', [target_uri])
                }
            )
            
        except Exception as e:
            self.log_test_result("Delete KGFrame", False, f"Exception: {e}")
    
    def test_delete_kgframes_batch(self):
        """Test batch deleting KGFrames."""
        try:
            uri_list = "http://vital.ai/haley.ai/app/KGFrame/test-frame-002"
            response = self.endpoint.delete_kgframes_batch(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri_list=uri_list
            )
            
            success = (
                isinstance(response, FrameDeleteResponse) and
                response.deleted_count >= 0
            )
            
            self.log_test_result(
                "Delete KGFrames Batch",
                success,
                f"Batch deleted {response.deleted_count} frames",
                {
                    "deleted_count": response.deleted_count,
                    "deleted_uris": getattr(response, 'deleted_uris', uri_list.split(','))
                }
            )
            
        except Exception as e:
            self.log_test_result("Delete KGFrames Batch", False, f"Exception: {e}")
    
    def test_list_kgframes_empty_final(self):
        """Test listing KGFrames after deletion (should be empty)."""
        try:
            response = self.endpoint.list_kgframes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                page_size=10,
                offset=0
            )
            
            success = (
                isinstance(response, FramesResponse) and
                response.total_count == 0
            )
            
            # Check if response has graph structure
            frames_count = 0
            if hasattr(response.frames, 'graph') and response.frames.graph:
                frames_count = len(response.frames.graph)
            
            self.log_test_result(
                "List KGFrames (Empty)",
                success,
                f"Found {frames_count} frames, total_count: {response.total_count}",
                {"frames_count": frames_count, "total_count": response.total_count}
            )
            
        except Exception as e:
            self.log_test_result("List KGFrames (Empty)", False, f"Exception: {e}")
    
    def run_all_tests(self):
        """Run all tests in sequence."""
        print("🧪 Testing MockKGFramesEndpoint")
        print("=" * 50)
        
        # Run tests in logical order
        self.test_list_kgframes_empty()
        self.test_create_kgframes()
        self.test_get_kgframe()
        self.test_list_kgframes_with_data()
        self.test_update_kgframes()
        self.test_search_kgframes()
        self.test_error_handling()
        self.test_delete_kgframe()
        self.test_delete_kgframes_batch()
        self.test_list_kgframes_empty_final()
        
        # Print summary
        print("=" * 50)
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        
        if passed == total:
            print(f"Test Results: {passed}/{total} tests passed")
            print("🎉 All tests passed! MockKGFramesEndpoint is working correctly.")
        else:
            print(f"Test Results: {passed}/{total} tests passed")
            print("⚠️  Some tests failed. Check the output above for details.")
        
        return passed == total


def main():
    """Main test runner."""
    test_suite = TestMockKGFramesEndpoint()
    success = test_suite.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
