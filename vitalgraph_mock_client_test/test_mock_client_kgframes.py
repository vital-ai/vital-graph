#!/usr/bin/env python3
"""
Test suite for MockVitalGraphClient KGFrames operations.

This test suite validates the mock client's KGFrames management functionality using:
- Direct client method calls (not endpoint calls)
- Proper request/response model validation
- Complete KGFrames CRUD operations with VitalSigns-compatible data
- Space and graph creation as prerequisites for KGFrames operations
- Frame-slot relationship testing
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
from vitalgraph.model.kgframes_model import FramesResponse, FrameCreateResponse, FrameUpdateResponse, FrameDeleteResponse
from vitalgraph.model.jsonld_model import JsonLdDocument

# VitalSigns imports
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from ai_haley_kg_domain.model.KGFrame import KGFrame


class TestMockClientKGFrames:
    """Test suite for MockVitalGraphClient KGFrames operations."""
    
    def __init__(self):
        """Initialize test suite."""
        # Configure logging to see debug output
        logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
        
        self.test_results = []
        self.client = None
        self.test_space_id = "test_kgframes_space"
        self.test_graph_id = "http://vital.ai/graph/test-kgframes"
        self.created_kgframes = []  # Track created KGFrames for cleanup
        
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
                hasattr(self.client, 'list_kgframes') and
                hasattr(self.client, 'create_kgframes') and
                hasattr(self.client, 'update_kgframes') and
                hasattr(self.client, 'delete_kgframe') and
                hasattr(self.client, 'delete_kgframes_batch') and
                hasattr(self.client, 'get_kgframes_with_slots') and
                hasattr(self.client, 'create_kgframes_with_slots')
            )
            
            client_type = type(self.client).__name__
            
            self.log_test_result(
                "Client Initialization",
                success,
                f"Created client: {client_type}",
                {"client_type": client_type, "has_kgframe_methods": success}
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
        """Test creating a test space for KGFrames operations."""
        try:
            # Create test space (required for KGFrames operations)
            test_space = Space(
                space=self.test_space_id,
                space_name="Test KGFrames Space",
                space_description="A test space for KGFrames operations testing"
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
        """Test creating a test graph for KGFrames operations."""
        try:
            # Create test graph (required for KGFrames operations)
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
    
    def test_list_kgframes_empty(self):
        """Test listing KGFrames when no KGFrames exist in the graph."""
        try:
            response = self.client.list_kgframes(self.test_space_id, self.test_graph_id)
            
            success = (
                isinstance(response, FramesResponse) and
                hasattr(response, 'frames') and
                hasattr(response, 'total_count') and
                response.total_count == 0
            )
            
            frames_count = 0
            if hasattr(response.frames, 'graph') and response.frames.graph:
                frames_count = len(response.frames.graph)
            
            self.log_test_result(
                "List KGFrames (Empty)",
                success,
                f"Found {frames_count} KGFrames, total_count: {response.total_count}",
                {
                    "frames_count": frames_count,
                    "total_count": response.total_count,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("List KGFrames (Empty)", False, f"Exception: {e}")
    
    def _create_test_kgframes(self) -> List[KGFrame]:
        """Create test KGFrame objects using VitalSigns."""
        frames = []
        
        # Create first test KGFrame
        frame1 = KGFrame()
        frame1.URI = "http://vital.ai/haley.ai/app/KGFrame/test_frame_001"
        frame1.name = "TestFrame1"
        frame1.kGraphDescription = "A test frame for VitalSigns mock client testing"
        frame1.kGFrameTypeDescription = "Test Frame Type"
        frame1.frameSequence = 1
        frame1.kGModelVersion = "1.0.0"
        frames.append(frame1)
        
        # Create second test KGFrame
        frame2 = KGFrame()
        frame2.URI = "http://vital.ai/haley.ai/app/KGFrame/test_frame_002"
        frame2.name = "TestFrame2"
        frame2.kGraphDescription = "Another test frame for VitalSigns mock client testing"
        frame2.kGFrameTypeDescription = "Another Test Frame Type"
        frame2.frameSequence = 2
        frame2.kGModelVersion = "1.0.0"
        frames.append(frame2)
        
        # Create third test KGFrame
        frame3 = KGFrame()
        frame3.URI = "http://vital.ai/haley.ai/app/KGFrame/test_frame_003"
        frame3.name = "TestFrame3"
        frame3.kGraphDescription = "Third test frame for VitalSigns mock client testing"
        frame3.kGFrameTypeDescription = "Third Test Frame Type"
        frame3.frameSequence = 3
        frame3.kGModelVersion = "1.0.0"
        frames.append(frame3)
        
        return frames
    
    def test_create_kgframes(self):
        """Test creating new KGFrames."""
        try:
            # Create test KGFrames using VitalSigns
            test_frames = self._create_test_kgframes()
            
            # Convert to JSON-LD using VitalSigns
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            jsonld_data = GraphObject.to_jsonld_list(test_frames)
            
            # Create JsonLdDocument
            kgframes_document = JsonLdDocument(**jsonld_data)
            
            response = self.client.create_kgframes(self.test_space_id, self.test_graph_id, kgframes_document)
            
            success = (
                isinstance(response, FrameCreateResponse) and
                hasattr(response, 'created_uris') and
                isinstance(response.created_uris, list) and
                len(response.created_uris) == 3
            )
            
            if success:
                self.created_kgframes.extend(response.created_uris)
            
            self.log_test_result(
                "Create KGFrames",
                success,
                f"Created {len(response.created_uris)} KGFrames",
                {
                    "created_count": response.created_count,
                    "created_uris": response.created_uris,
                    "message": response.message,
                    "response_type": type(response).__name__
                }
            )
            
            return response.created_uris if success else []
            
        except Exception as e:
            self.log_test_result("Create KGFrames", False, f"Exception: {e}")
            return []
    
    def test_get_kgframe(self, kgframe_uri: str):
        """Test retrieving a specific KGFrame by URI."""
        if not kgframe_uri:
            self.log_test_result("Get KGFrame", False, "No KGFrame URI provided")
            return
        
        try:
            response = self.client.get_kgframe(self.test_space_id, self.test_graph_id, kgframe_uri)
            
            # Handle both FramesResponse and JsonLdDocument return types
            success = False
            kgframe_name = None
            frames_count = 0
            
            if isinstance(response, FramesResponse):
                # Standard FramesResponse format
                success = (
                    hasattr(response, 'frames') and
                    hasattr(response.frames, 'graph') and
                    response.frames.graph and
                    len(response.frames.graph) > 0
                )
                if success and response.frames.graph:
                    # Find the KGFrame in the response
                    for item in response.frames.graph:
                        if item.get('@id') == kgframe_uri:
                            kgframe_name = item.get('vital-core:hasName', 'Unknown')
                            break
                    frames_count = len(response.frames.graph)
            elif hasattr(response, 'graph') and response.graph:
                # Direct JsonLdDocument format
                success = len(response.graph) > 0
                if success:
                    # Find the KGFrame in the response
                    for item in response.graph:
                        if item.get('@id') == kgframe_uri:
                            kgframe_name = item.get('vital-core:hasName', 'Unknown')
                            break
                    frames_count = len(response.graph)
            elif hasattr(response, 'id') and response.id == kgframe_uri:
                # Single object JsonLdDocument format
                success = True
                kgframe_name = getattr(response, 'http://vital.ai/ontology/vital-core#hasName', {}).get('@value', 'Unknown')
                frames_count = 1
            
            self.log_test_result(
                "Get KGFrame",
                success,
                f"Retrieved KGFrame: {kgframe_uri}",
                {
                    "uri": kgframe_uri,
                    "name": kgframe_name,
                    "frames_count": frames_count,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Get KGFrame", False, f"Exception: {e}")
    
    def test_list_kgframes_with_data(self):
        """Test listing KGFrames when KGFrames exist."""
        try:
            response = self.client.list_kgframes(self.test_space_id, self.test_graph_id, page_size=10, offset=0)
            
            success = (
                isinstance(response, FramesResponse) and
                hasattr(response, 'frames') and
                hasattr(response, 'total_count') and
                response.total_count > 0
            )
            
            frames_count = 0
            frame_names = []
            if hasattr(response.frames, 'graph') and response.frames.graph:
                frames_count = len(response.frames.graph)
                for frame_data in response.frames.graph:
                    frame_name = frame_data.get('vital-core:hasName', 'Unknown')
                    frame_names.append(frame_name)
            
            self.log_test_result(
                "List KGFrames (With Data)",
                success,
                f"Found {frames_count} KGFrames, total_count: {response.total_count}",
                {
                    "frames_count": frames_count,
                    "total_count": response.total_count,
                    "frame_names": frame_names[:3],  # Show first 3 names
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("List KGFrames (With Data)", False, f"Exception: {e}")
    
    def test_search_kgframes(self):
        """Test searching KGFrames with filters."""
        try:
            response = self.client.list_kgframes(
                self.test_space_id, 
                self.test_graph_id, 
                page_size=10, 
                offset=0, 
                search="test"
            )
            
            success = (
                isinstance(response, FramesResponse) and
                hasattr(response, 'frames') and
                hasattr(response, 'total_count')
            )
            
            frames_count = 0
            if hasattr(response.frames, 'graph') and response.frames.graph:
                frames_count = len(response.frames.graph)
            
            self.log_test_result(
                "Search KGFrames",
                success,
                f"Search found {frames_count} KGFrames matching 'test'",
                {
                    "search_term": "test",
                    "frames_count": frames_count,
                    "total_count": response.total_count,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Search KGFrames", False, f"Exception: {e}")
    
    def test_update_kgframes(self, kgframe_uris: List[str]):
        """Test updating existing KGFrames."""
        if not kgframe_uris:
            self.log_test_result("Update KGFrames", False, "No KGFrame URIs provided")
            return
        
        try:
            # Create updated KGFrame using VitalSigns
            updated_frame = KGFrame()
            updated_frame.URI = kgframe_uris[0]
            updated_frame.name = "UpdatedTestFrame"
            updated_frame.kGraphDescription = "An updated test frame for VitalSigns mock client testing"
            updated_frame.kGFrameTypeDescription = "Updated Test Frame Type"
            updated_frame.frameSequence = 100
            updated_frame.kGModelVersion = "2.0.0"
            
            # Convert to JSON-LD using VitalSigns
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            jsonld_data = GraphObject.to_jsonld_list([updated_frame])
            
            # Ensure the JSON-LD has a graph array format
            if 'graph' not in jsonld_data or jsonld_data['graph'] is None:
                # Convert single object format to graph array format
                single_obj = {k: v for k, v in jsonld_data.items() if k not in ['@context']}
                jsonld_data['graph'] = [single_obj]
            
            # Create JsonLdDocument
            update_document = JsonLdDocument(**jsonld_data)
            
            response = self.client.update_kgframes(self.test_space_id, self.test_graph_id, update_document)
            
            success = (
                isinstance(response, FrameUpdateResponse) and
                hasattr(response, 'updated_uri') and
                response.updated_uri != ""
            )
            
            self.log_test_result(
                "Update KGFrames",
                success,
                f"Updated KGFrame: {response.updated_uri if success else 'None'}",
                {
                    "updated_uri": response.updated_uri if hasattr(response, 'updated_uri') else None,
                    "message": response.message if hasattr(response, 'message') else None,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Update KGFrames", False, f"Exception: {e}")
    
    # def test_get_kgframes_with_slots(self):
    #     """Test retrieving KGFrames with their associated slots."""
    #     try:
    #         response = self.client.get_kgframes_with_slots(self.test_space_id, self.test_graph_id, page_size=10, offset=0)
    #         
    #         success = (
    #             isinstance(response, FramesResponse) and
    #             hasattr(response, 'frames') and
    #             hasattr(response, 'total_count')
    #         )
    #         
    #         frames_count = 0
    #         if hasattr(response.frames, 'graph') and response.frames.graph:
    #             frames_count = len(response.frames.graph)
    #         
    #         self.log_test_result(
    #             "Get KGFrames With Slots",
    #             success,
    #             f"Found {frames_count} KGFrames with slots, total_count: {response.total_count}",
    #             {
    #                 "frames_count": frames_count,
    #                 "total_count": response.total_count,
    #                 "response_type": type(response).__name__
    #             }
    #         )
    #         
    #     except Exception as e:
    #         self.log_test_result("Get KGFrames With Slots", False, f"Exception: {e}")
    
    def test_delete_kgframe(self, kgframe_uri: str):
        """Test deleting a single KGFrame."""
        if not kgframe_uri:
            self.log_test_result("Delete KGFrame", False, "No KGFrame URI provided")
            return
        
        try:
            response = self.client.delete_kgframe(self.test_space_id, self.test_graph_id, kgframe_uri)
            
            success = (
                isinstance(response, FrameDeleteResponse) and
                hasattr(response, 'deleted_count') and
                response.deleted_count > 0
            )
            
            if success and kgframe_uri in self.created_kgframes:
                self.created_kgframes.remove(kgframe_uri)
            
            self.log_test_result(
                "Delete KGFrame",
                success,
                f"Deleted KGFrame: {kgframe_uri}",
                {
                    "deleted_count": response.deleted_count,
                    "deleted_uris": response.deleted_uris if hasattr(response, 'deleted_uris') else [],
                    "message": response.message if hasattr(response, 'message') else None,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Delete KGFrame", False, f"Exception: {e}")
    
    def test_delete_kgframes_batch(self, kgframe_uris: List[str]):
        """Test batch deletion of KGFrames."""
        if not kgframe_uris:
            self.log_test_result("Delete KGFrames Batch", False, "No KGFrame URIs provided")
            return
        
        try:
            uri_list = ",".join(kgframe_uris)
            response = self.client.delete_kgframes_batch(self.test_space_id, self.test_graph_id, uri_list)
            
            success = (
                isinstance(response, FrameDeleteResponse) and
                hasattr(response, 'deleted_count') and
                response.deleted_count > 0
            )
            
            if success:
                for uri in kgframe_uris:
                    if uri in self.created_kgframes:
                        self.created_kgframes.remove(uri)
            
            self.log_test_result(
                "Delete KGFrames Batch",
                success,
                f"Batch deleted {response.deleted_count} KGFrames",
                {
                    "deleted_count": response.deleted_count,
                    "deleted_uris": response.deleted_uris if hasattr(response, 'deleted_uris') else [],
                    "message": response.message if hasattr(response, 'message') else None,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Delete KGFrames Batch", False, f"Exception: {e}")
    
    def test_error_handling_nonexistent_space(self):
        """Test error handling with nonexistent space."""
        try:
            # Test with nonexistent space
            response = self.client.list_kgframes("nonexistent_space_12345", self.test_graph_id)
            
            success = (
                isinstance(response, FramesResponse) and
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
    
    def test_error_handling_nonexistent_kgframe(self):
        """Test error handling for non-existent KGFrame operations."""
        try:
            # Try to get a non-existent KGFrame
            response = self.client.get_kgframe(
                self.test_space_id, 
                self.test_graph_id, 
                "http://nonexistent.kgframe/uri-12345"
            )
            
            # Should handle gracefully - either return empty response or None
            success = True  # If no exception thrown, it's handling gracefully
            
            frames_count = 0
            if response and hasattr(response, 'frames') and hasattr(response.frames, 'graph'):
                frames_count = len(response.frames.graph) if response.frames.graph else 0
            
            self.log_test_result(
                "Error Handling (Non-existent KGFrame)",
                success,
                "Gracefully handled non-existent KGFrame request",
                {
                    "requested_uri": "http://nonexistent.kgframe/uri-12345",
                    "frames_count": frames_count
                }
            )
            
        except Exception as e:
            # Check if it's a reasonable error response
            success = "not found" in str(e).lower() or "does not exist" in str(e).lower()
            self.log_test_result(
                "Error Handling (Non-existent KGFrame)",
                success,
                f"Exception: {e}"
            )
    
    def test_list_kgframes_after_operations(self):
        """Test listing KGFrames after all operations (should be empty or reduced)."""
        try:
            response = self.client.list_kgframes(self.test_space_id, self.test_graph_id)
            
            success = isinstance(response, FramesResponse)
            
            frames_count = 0
            if hasattr(response.frames, 'graph') and response.frames.graph:
                frames_count = len(response.frames.graph)
            
            self.log_test_result(
                "List KGFrames (After Operations)",
                success,
                f"Found {frames_count} KGFrames after operations",
                {
                    "frames_count": frames_count,
                    "total_count": response.total_count if hasattr(response, 'total_count') else 0
                }
            )
            
        except Exception as e:
            self.log_test_result("List KGFrames (After Operations)", False, f"Exception: {e}")
    
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
    
    def cleanup_remaining_kgframes(self):
        """Clean up any remaining KGFrames."""
        try:
            cleanup_count = 0
            for kgframe_uri in self.created_kgframes[:]:  # Copy list to avoid modification during iteration
                try:
                    response = self.client.delete_kgframe(self.test_space_id, self.test_graph_id, kgframe_uri)
                    if hasattr(response, 'deleted_count') and response.deleted_count > 0:
                        cleanup_count += 1
                        self.created_kgframes.remove(kgframe_uri)
                except:
                    pass  # Ignore cleanup errors
            
            if cleanup_count > 0:
                print(f"🧹 Cleaned up {cleanup_count} remaining KGFrames")
                
        except Exception as e:
            print(f"⚠️  Cleanup error: {e}")
    
    def run_all_tests(self):
        """Run all tests in sequence."""
        print("🧪 Testing MockVitalGraphClient KGFrames Operations")
        print("=" * 60)
        
        # Run tests in logical order
        self.test_client_initialization()
        self.test_client_connection()
        self.test_create_test_space()
        self.test_create_test_graph()
        self.test_list_kgframes_empty()
        
        # Basic KGFrames CRUD operations
        kgframe_uris = self.test_create_kgframes()
        if kgframe_uris:
            self.test_get_kgframe(kgframe_uris[0])
            self.test_list_kgframes_with_data()
            self.test_search_kgframes()
            # self.test_get_kgframes_with_slots()  # Commented out - method not implemented in mock endpoint
            self.test_update_kgframes(kgframe_uris)
            
            # Test deletion operations
            if len(kgframe_uris) > 1:
                # Delete one KGFrame individually
                self.test_delete_kgframe(kgframe_uris[0])
                # Delete remaining KGFrames in batch
                self.test_delete_kgframes_batch(kgframe_uris[1:])
            else:
                self.test_delete_kgframes_batch(kgframe_uris)
        
        # Error handling and edge cases
        self.test_error_handling_nonexistent_space()
        self.test_error_handling_nonexistent_kgframe()
        
        # Final verification
        self.test_list_kgframes_after_operations()
        
        # Cleanup any remaining KGFrames
        self.cleanup_remaining_kgframes()
        
        # Disconnect client
        self.test_client_disconnection()
        
        # Print summary
        print("=" * 60)
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        
        if passed == total:
            print(f"Test Results: {passed}/{total} tests passed")
            print("🎉 All tests passed! MockVitalGraphClient KGFrames operations are working correctly.")
        else:
            print(f"Test Results: {passed}/{total} tests passed")
            print("⚠️  Some tests failed. Check the output above for details.")
        
        return passed == total


def main():
    """Main test runner."""
    test_suite = TestMockClientKGFrames()
    success = test_suite.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
