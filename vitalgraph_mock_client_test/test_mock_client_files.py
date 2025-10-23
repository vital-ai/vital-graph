#!/usr/bin/env python3
"""
Test suite for MockVitalGraphClient file operations.

This test suite validates the mock client's file management functionality using:
- Direct client method calls (not endpoint calls)
- Proper request/response model validation
- Complete file CRUD operations with VitalSigns-compatible data
- Space and graph creation as prerequisites for file operations
- Error handling and edge cases
- Direct test runner format (no pytest dependency)
"""

import sys
import json
import logging
import tempfile
import os
from pathlib import Path
from typing import Dict, Any, List

# Add the parent directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.client.client_factory import create_vitalgraph_client
from vitalgraph.client.config.client_config_loader import VitalGraphClientConfig
from vitalgraph.model.spaces_model import Space, SpaceCreateResponse
from vitalgraph.model.sparql_model import SPARQLGraphResponse
from vitalgraph.model.files_model import FilesResponse, FileCreateResponse, FileUpdateResponse, FileDeleteResponse, FileUploadResponse
from vitalgraph.model.jsonld_model import JsonLdDocument

# VitalSigns imports
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_domain.model.FileNode import FileNode


class TestMockClientFiles:
    """Test suite for MockVitalGraphClient file operations."""
    
    def __init__(self):
        """Initialize test suite."""
        # Configure logging to see debug output
        logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
        
        self.test_results = []
        self.client = None
        self.test_space_id = "test_files_space"
        self.test_graph_id = "http://vital.ai/graph/test-files"
        self.created_files = []  # Track created files for cleanup
        self.temp_files = []  # Track temporary files for cleanup
        
        # Test files directory
        self.test_files_dir = Path("/Users/hadfield/Local/vital-git/vital-graph/localTestFiles")
        
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
    
    def _get_test_file_path(self, filename: str) -> str:
        """Get path to a test file from the localTestFiles directory."""
        test_file_path = self.test_files_dir / filename
        if test_file_path.exists():
            return str(test_file_path)
        else:
            # Fallback: create a temporary test file if the specific file doesn't exist
            temp_file = tempfile.NamedTemporaryFile(mode='w', suffix=f'_{filename}', delete=False)
            temp_file.write(f"Test content for {filename}")
            temp_file.close()
            self.temp_files.append(temp_file.name)
            return temp_file.name
    
    def test_client_initialization(self):
        """Test mock client initialization and connection."""
        try:
            # Create client using factory with config object
            self.client = create_vitalgraph_client(config=self.config)
            
            success = (
                self.client is not None and
                hasattr(self.client, 'list_files') and
                hasattr(self.client, 'create_file') and
                hasattr(self.client, 'update_file') and
                hasattr(self.client, 'delete_file') and
                hasattr(self.client, 'upload_file_content') and
                hasattr(self.client, 'download_file_content')
            )
            
            client_type = type(self.client).__name__
            
            self.log_test_result(
                "Client Initialization",
                success,
                f"Created client: {client_type}",
                {"client_type": client_type, "has_file_methods": success}
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
        """Test creating a test space for file operations."""
        try:
            # Create test space (required for file operations)
            test_space = Space(
                space=self.test_space_id,
                space_name="Test Files Space",
                space_description="A test space for file operations testing"
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
        """Test creating a test graph for file operations."""
        try:
            # Create test graph (required for file operations)
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
    
    def test_list_files_empty(self):
        """Test listing files when no files exist in the graph."""
        try:
            response = self.client.list_files(self.test_space_id, self.test_graph_id)
            
            success = (
                isinstance(response, FilesResponse) and
                hasattr(response, 'files') and
                hasattr(response, 'total_count') and
                response.total_count == 0
            )
            
            files_count = 0
            if hasattr(response.files, 'graph') and response.files.graph:
                files_count = len(response.files.graph)
            
            self.log_test_result(
                "List Files (Empty)",
                success,
                f"Found {files_count} files, total_count: {response.total_count}",
                {
                    "files_count": files_count,
                    "total_count": response.total_count,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("List Files (Empty)", False, f"Exception: {e}")
    
    def test_create_file_metadata(self):
        """Test creating file metadata."""
        try:
            # Create FileNode objects using VitalSigns
            files = []
            
            # Create first file
            file1 = FileNode()
            file1.URI = "http://vital.ai/haley.ai/app/test-file-001"
            file1.fileName = "2510.04871v1.pdf"
            file1.fileLength = 427299
            files.append(file1)
            
            # Create second file
            file2 = FileNode()
            file2.URI = "http://vital.ai/haley.ai/app/test-file-002"
            file2.fileName = "downloaded_paper.pdf"
            file2.fileLength = 427299
            files.append(file2)
            
            # Convert to JSON-LD using VitalSigns
            jsonld_data = GraphObject.to_jsonld_list(files)
            files_data = JsonLdDocument(**jsonld_data)
            
            response = self.client.create_file(self.test_space_id, files_data, self.test_graph_id)
            
            success = (
                isinstance(response, FileCreateResponse) and
                hasattr(response, 'created_uris') and
                isinstance(response.created_uris, list) and
                len(response.created_uris) >= 1
            )
            
            if success:
                self.created_files.extend(response.created_uris)
            
            self.log_test_result(
                "Create File Metadata",
                success,
                f"Created {len(response.created_uris)} file metadata entries",
                {
                    "created_count": response.created_count,
                    "created_uris": response.created_uris,
                    "message": response.message,
                    "response_type": type(response).__name__
                }
            )
            
            return response.created_uris if success else []
            
        except Exception as e:
            self.log_test_result("Create File Metadata", False, f"Exception: {e}")
            return []
    
    def test_upload_file(self, file_uri: str):
        """Test uploading file binary content."""
        if not file_uri:
            self.log_test_result("Upload File", False, "No file URI provided")
            return
        
        try:
            # Use actual test file from localTestFiles directory
            test_file_path = self._get_test_file_path("2510.04871v1.pdf")
            file_size = os.path.getsize(test_file_path) if os.path.exists(test_file_path) else 0
            
            response = self.client.upload_file_content(
                self.test_space_id,
                file_uri,
                test_file_path,
                graph_id=self.test_graph_id
            )
            
            success = (
                response is not None and
                hasattr(response, 'message') and
                hasattr(response, 'file_uri')
            )
            
            self.log_test_result(
                "Upload File",
                success,
                f"Uploaded file: {file_uri}",
                {
                    "file_uri": file_uri,
                    "file_path": test_file_path,
                    "file_size": file_size,
                    "uploaded_uri": response.file_uri if success else None,
                    "message": response.message if hasattr(response, 'message') else None,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Upload File", False, f"Exception: {e}")
    
    def test_get_file(self, file_uri: str):
        """Test retrieving a specific file by URI."""
        if not file_uri:
            self.log_test_result("Get File", False, "No file URI provided")
            return
        
        try:
            response = self.client.get_file(self.test_space_id, file_uri, self.test_graph_id)
            
            success = False
            file_name = None
            files_count = 0
            
            if isinstance(response, FilesResponse):
                # Standard FilesResponse format
                success = (
                    hasattr(response, 'files') and
                    hasattr(response.files, 'graph') and
                    response.files.graph and
                    len(response.files.graph) > 0
                )
                if success and response.files.graph:
                    file_name = response.files.graph[0].get('http://vital.ai/ontology/vital#hasFileName', 
                                                           response.files.graph[0].get('vital:hasFileName', 'Unknown'))
                    files_count = len(response.files.graph)
            elif hasattr(response, 'graph') and response.graph:
                # Direct JsonLdDocument format
                success = len(response.graph) > 0
                if success:
                    file_name = response.graph[0].get('http://vital.ai/ontology/vital#hasFileName',
                                                     response.graph[0].get('vital:hasFileName', 'Unknown'))
                    files_count = len(response.graph)
            
            self.log_test_result(
                "Get File",
                success,
                f"Retrieved file: {file_uri}",
                {
                    "uri": file_uri,
                    "name": file_name,
                    "files_count": files_count,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Get File", False, f"Exception: {e}")
    
    def test_download_file(self, file_uri: str):
        """Test downloading file binary content."""
        if not file_uri:
            self.log_test_result("Download File", False, "No file URI provided")
            return
        
        try:
            # Create temporary download path
            download_path = tempfile.mktemp(suffix='_download_test.txt')
            self.temp_files.append(download_path)
            
            response = self.client.download_file_content(
                self.test_space_id,
                file_uri,
                download_path,
                graph_id=self.test_graph_id
            )
            
            # Check if file was downloaded
            file_exists = os.path.exists(download_path)
            file_size = os.path.getsize(download_path) if file_exists else 0
            
            success = (
                response is not None and
                file_exists and
                file_size > 0
            )
            
            self.log_test_result(
                "Download File",
                success,
                f"Downloaded file: {file_uri}",
                {
                    "file_uri": file_uri,
                    "download_path": download_path,
                    "file_size": file_size,
                    "file_exists": file_exists,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Download File", False, f"Exception: {e}")
    
    def test_list_files_with_data(self):
        """Test listing files when files exist."""
        try:
            response = self.client.list_files(self.test_space_id, self.test_graph_id, page_size=10, offset=0)
            
            success = (
                isinstance(response, FilesResponse) and
                hasattr(response, 'files') and
                hasattr(response, 'total_count') and
                response.total_count > 0
            )
            
            files_count = 0
            file_names = []
            if hasattr(response.files, 'graph') and response.files.graph:
                files_count = len(response.files.graph)
                for file_data in response.files.graph:
                    file_name = file_data.get('http://vital.ai/ontology/vital#hasFileName', 
                                             file_data.get('vital:hasFileName', 'Unknown'))
                    file_names.append(file_name)
            
            self.log_test_result(
                "List Files (With Data)",
                success,
                f"Found {files_count} files, total_count: {response.total_count}",
                {
                    "files_count": files_count,
                    "total_count": response.total_count,
                    "file_names": file_names[:3],  # Show first 3 names
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("List Files (With Data)", False, f"Exception: {e}")
    
    def test_search_files(self):
        try:
            # Test search functionality using file_filter parameter
            response = self.client.list_files(
                self.test_space_id, 
                self.test_graph_id, 
                file_filter="pdf"
            )
            
            success = (
                isinstance(response, FilesResponse) and
                hasattr(response, 'files') and
                hasattr(response, 'total_count')
            )
            
            files_count = 0
            if hasattr(response.files, 'graph') and response.files.graph:
                files_count = len(response.files.graph)
            
            self.log_test_result(
                "Search Files",
                success,
                f"Search found {files_count} files matching 'test'",
                {
                    "search_term": "test",
                    "files_count": files_count,
                    "total_count": response.total_count,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Search Files", False, f"Exception: {e}")
    
    def test_update_file(self, file_uris: List[str]):
        """Test updating existing file metadata."""
        if not file_uris:
            self.log_test_result("Update File", False, "No file URIs provided")
            return
        
        try:
            # Create updated FileNode object using VitalSigns
            updated_file = FileNode()
            updated_file.URI = file_uris[0]
            updated_file.fileName = "updated_2510.04871v1.pdf"
            updated_file.fileLength = 427299
            
            # Convert to JSON-LD using VitalSigns
            jsonld_data = GraphObject.to_jsonld_list([updated_file])
            updated_data = JsonLdDocument(**jsonld_data)
            
            response = self.client.update_file(self.test_space_id, updated_data, self.test_graph_id)
            
            success = (
                isinstance(response, FileUpdateResponse) and
                hasattr(response, 'updated_uri') and
                response.updated_uri != ""
            )
            
            self.log_test_result(
                "Update File",
                success,
                f"Updated file: {response.updated_uri if success else 'None'}",
                {
                    "updated_uri": response.updated_uri if hasattr(response, 'updated_uri') else None,
                    "message": response.message if hasattr(response, 'message') else None,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Update File", False, f"Exception: {e}")
    
    def test_delete_file(self, file_uri: str):
        """Test deleting a single file."""
        if not file_uri:
            self.log_test_result("Delete File", False, "No file URI provided")
            return
        
        try:
            response = self.client.delete_file(self.test_space_id, file_uri, self.test_graph_id)
            
            success = (
                isinstance(response, FileDeleteResponse) and
                hasattr(response, 'deleted_count') and
                response.deleted_count > 0
            )
            
            if success and file_uri in self.created_files:
                self.created_files.remove(file_uri)
            
            self.log_test_result(
                "Delete File",
                success,
                f"Deleted file: {file_uri}",
                {
                    "deleted_count": response.deleted_count,
                    "deleted_uris": response.deleted_uris if hasattr(response, 'deleted_uris') else [],
                    "message": response.message if hasattr(response, 'message') else None,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Delete File", False, f"Exception: {e}")
    
    def test_error_handling_nonexistent_space(self):
        """Test error handling with nonexistent space."""
        try:
            # Test with nonexistent space
            response = self.client.list_files("nonexistent_space_12345", self.test_graph_id)
            
            success = (
                isinstance(response, FilesResponse) and
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
    
    def test_list_files_after_operations(self):
        """Test listing files after all operations."""
        try:
            response = self.client.list_files(self.test_space_id, self.test_graph_id)
            
            success = isinstance(response, FilesResponse)
            
            files_count = 0
            if hasattr(response.files, 'graph') and response.files.graph:
                files_count = len(response.files.graph)
            
            self.log_test_result(
                "List Files (After Operations)",
                success,
                f"Found {files_count} files after operations",
                {
                    "files_count": files_count,
                    "total_count": response.total_count if hasattr(response, 'total_count') else 0
                }
            )
            
        except Exception as e:
            self.log_test_result("List Files (After Operations)", False, f"Exception: {e}")
    
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
    
    def cleanup_remaining_files(self):
        """Clean up any remaining files."""
        try:
            cleanup_count = 0
            for file_uri in self.created_files[:]:  # Copy list to avoid modification during iteration
                try:
                    response = self.client.delete_file(self.test_space_id, file_uri, self.test_graph_id)
                    if hasattr(response, 'deleted_count') and response.deleted_count > 0:
                        cleanup_count += 1
                        self.created_files.remove(file_uri)
                except:
                    pass  # Ignore cleanup errors
            
            # Clean up temporary files
            for temp_file in self.temp_files:
                try:
                    if os.path.exists(temp_file):
                        os.unlink(temp_file)
                except:
                    pass
            
            if cleanup_count > 0:
                print(f"🧹 Cleaned up {cleanup_count} remaining files")
                
        except Exception as e:
            print(f"⚠️  Cleanup error: {e}")
    
    def run_all_tests(self):
        """Run all tests in sequence."""
        print("🧪 Testing MockVitalGraphClient File Operations")
        print("=" * 60)
        
        # Run tests in logical order
        self.test_client_initialization()
        self.test_client_connection()
        self.test_create_test_space()
        self.test_create_test_graph()
        self.test_list_files_empty()
        
        # Basic file CRUD operations
        file_uris = self.test_create_file_metadata()
        if file_uris:
            self.test_get_file(file_uris[0])
            self.test_upload_file(file_uris[0])
            self.test_download_file(file_uris[0])
            self.test_list_files_with_data()
            self.test_search_files()
            self.test_update_file(file_uris)
            
            # Test deletion operations
            if len(file_uris) > 1:
                # Delete one file
                self.test_delete_file(file_uris[0])
        
        # Error handling and edge cases
        self.test_error_handling_nonexistent_space()
        
        # Final verification
        self.test_list_files_after_operations()
        
        # Cleanup any remaining files
        self.cleanup_remaining_files()
        
        # Disconnect client
        self.test_client_disconnection()
        
        # Print summary
        print("=" * 60)
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        
        if passed == total:
            print(f"Test Results: {passed}/{total} tests passed")
            print("🎉 All tests passed! MockVitalGraphClient file operations are working correctly.")
        else:
            print(f"Test Results: {passed}/{total} tests passed")
            print("⚠️  Some tests failed. Check the output above for details.")
        
        return passed == total


def main():
    """Main test runner."""
    test_suite = TestMockClientFiles()
    success = test_suite.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
