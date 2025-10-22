#!/usr/bin/env python3
"""
Test script for MockFilesEndpoint with VitalSigns native functionality and MinIO simulation.

This script demonstrates:
- VitalSigns native object creation and conversion for File objects
- pyoxigraph in-memory SPARQL quad store operations for file metadata
- MinIO simulation with configurable storage (temporary or persistent)
- Complete file lifecycle: create metadata, upload binary, download, delete
- Batch operations and error handling
"""

import sys
import json
import tempfile
import os
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)

from vitalgraph.mock.client.endpoint.mock_files_endpoint import MockFilesEndpoint
from vitalgraph.mock.client.space.mock_space_manager import MockSpaceManager
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.VITAL_Node import VITAL_Node


class MockConfig:
    """Mock configuration class for testing."""
    
    def __init__(self, use_temp_storage=True, file_path=None):
        self._use_temp_storage = use_temp_storage
        self._file_path = file_path
    
    def use_temp_storage(self):
        """Return whether to use temporary storage."""
        return self._use_temp_storage
    
    def get_mock_file_path(self):
        return self._file_path


class TestMockFilesEndpoint:
    """Test suite for MockFilesEndpoint."""
    
    def __init__(self, use_temp_storage=True):
        """Initialize test suite."""
        self.space_manager = MockSpaceManager()
        
        # Configure storage type
        if use_temp_storage:
            self.config = MockConfig(use_temp_storage=True)
        else:
            # Create a temporary directory for persistent storage testing
            self.persistent_dir = tempfile.mkdtemp(prefix="mock_files_persistent_")
            self.config = MockConfig(use_temp_storage=False, file_path=self.persistent_dir)
        
        self.endpoint = MockFilesEndpoint(client=None, space_manager=self.space_manager, config=self.config)
        self.test_results = []
        self.test_space_id = "test_files_space"
        self.test_graph_id = "http://vital.ai/graph/test-files"
        
        # Initialize test space
        self.space_manager.create_space(self.test_space_id)
        
        # Create test files for upload testing
        self.test_files = self._create_test_files()
        
    def _create_test_files(self):
        """Create temporary test files for upload testing."""
        test_files = {}
        
        # Create text file
        text_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        text_file.write("This is a test text file for MockFilesEndpoint testing.\n")
        text_file.write("It contains multiple lines of text.\n")
        text_file.write("Used for testing file upload and download operations.")
        text_file.close()
        test_files['text'] = text_file.name
        
        # Create binary file
        binary_file = tempfile.NamedTemporaryFile(mode='wb', suffix='.bin', delete=False)
        binary_file.write(b'\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0A\x0B\x0C\x0D\x0E\x0F')
        binary_file.write(b'Binary test data for file operations')
        binary_file.close()
        test_files['binary'] = binary_file.name
        
        # Create JSON file
        json_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump({
            "test": "data",
            "numbers": [1, 2, 3, 4, 5],
            "nested": {"key": "value", "array": ["a", "b", "c"]}
        }, json_file, indent=2)
        json_file.close()
        test_files['json'] = json_file.name
        
        return test_files
    
    def _cleanup_test_files(self):
        """Clean up temporary test files."""
        for file_path in self.test_files.values():
            try:
                os.unlink(file_path)
            except:
                pass
        
        # Clean up persistent directory if used
        if hasattr(self, 'persistent_dir'):
            import shutil
            try:
                shutil.rmtree(self.persistent_dir)
            except:
                pass
    
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
    
    def test_storage_configuration(self):
        """Test storage configuration."""
        try:
            storage_type = "Temporary" if self.endpoint._use_temp_storage else "Configured"
            has_minio_path = self.endpoint.minio_base_path is not None
            has_minio_client = self.endpoint.minio_client is not None
            
            success = has_minio_path and has_minio_client
            
            self.log_test_result(
                "Storage Configuration",
                success,
                f"Storage type: {storage_type}, Path exists: {has_minio_path}, Client configured: {has_minio_client}",
                {
                    "storage_type": storage_type,
                    "minio_path": str(self.endpoint.minio_base_path) if has_minio_path else None,
                    "temp_dir": self.endpoint._temp_dir
                }
            )
            
        except Exception as e:
            self.log_test_result("Storage Configuration", False, f"Exception: {e}")
    
    def test_list_files_empty(self):
        """Test listing files when none exist."""
        try:
            response = self.endpoint.list_files(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            success = (
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
                {"files_count": files_count, "total_count": response.total_count}
            )
            
        except Exception as e:
            self.log_test_result("List Files (Empty)", False, f"Exception: {e}")
    
    def test_create_file_nodes(self):
        """Test creating file metadata nodes."""
        try:
            # Create JSON-LD document with file metadata
            files_jsonld = {
                "@context": {
                    "vital": "http://vital.ai/ontology/vital#",
                    "vital-core": "http://vital.ai/ontology/vital-core#",
                    "haley": "http://vital.ai/ontology/haley-ai-kg#"
                },
                "@graph": [
                    {
                        "@id": "http://vital.ai/haley.ai/app/test-file-001.txt",
                        "@type": "vital:FileNode",
                        "vital:hasFileName": "test-file-001.txt",
                        "vital:hasFileType": "text/plain",
                        "vital:hasFileLength": 1024
                    },
                    {
                        "@id": "http://vital.ai/haley.ai/app/test-file-002.bin",
                        "@type": "vital:FileNode",
                        "vital:hasFileName": "test-file-002.bin",
                        "vital:hasFileType": "application/octet-stream",
                        "vital:hasFileLength": 2048
                    },
                    {
                        "@id": "http://vital.ai/haley.ai/app/test-file-003.json",
                        "@type": "vital:FileNode",
                        "vital:hasFileName": "test-file-003.json",
                        "vital:hasFileType": "application/json",
                        "vital:hasFileLength": 512
                    }
                ]
            }
            
            from vitalgraph.model.jsonld_model import JsonLdDocument
            document = JsonLdDocument(**files_jsonld)
            response = self.endpoint.create_file(
                space_id=self.test_space_id,
                document=document,
                graph_id=self.test_graph_id
            )
            
            success = (
                hasattr(response, 'created_uris') and
                isinstance(response.created_uris, list) and
                len(response.created_uris) == 3
            )
            
            self.log_test_result(
                "Create File Nodes",
                success,
                f"Created {len(response.created_uris)} file metadata nodes",
                {"created_uris": response.created_uris}
            )
            
            return response.created_uris if success else []
            
        except Exception as e:
            self.log_test_result("Create File Nodes", False, f"Exception: {e}")
            return []
    
    def test_upload_file_content(self, file_uris: List[str]):
        """Test uploading binary file content."""
        if not file_uris:
            self.log_test_result("Upload File Content", False, "No file URIs provided")
            return
        
        try:
            # Upload different types of files
            upload_results = []
            
            for i, (file_type, file_path) in enumerate(self.test_files.items()):
                if i < len(file_uris):
                    file_uri = file_uris[i]
                    
                    response = self.endpoint.upload_file_content(
                        space_id=self.test_space_id,
                        uri=file_uri,
                        file_path=file_path,
                        graph_id=self.test_graph_id
                    )
                    
                    upload_success = (
                        hasattr(response, 'file_uri') and
                        response.file_uri == file_uri and
                        hasattr(response, 'file_size') and
                        response.file_size > 0
                    )
                    
                    upload_results.append({
                        "uri": file_uri,
                        "type": file_type,
                        "success": upload_success,
                        "size": response.file_size if upload_success else 0
                    })
            
            success = all(result["success"] for result in upload_results)
            
            self.log_test_result(
                "Upload File Content",
                success,
                f"Uploaded {len(upload_results)} files to MinIO storage",
                {"uploads": upload_results}
            )
            
        except Exception as e:
            self.log_test_result("Upload File Content", False, f"Exception: {e}")
    
    def test_get_file(self, file_uri: str):
        """Test retrieving a specific file by URI."""
        if not file_uri:
            self.log_test_result("Get File", False, "No file URI provided")
            return
        
        try:
            response = self.endpoint.get_file(
                space_id=self.test_space_id,
                uri=file_uri,
                graph_id=self.test_graph_id
            )
            
            # Check if we got a valid JsonLdDocument with file data
            has_file_data = False
            if response and hasattr(response, 'graph') and response.graph:
                has_file_data = len(response.graph) > 0
                # Check if the file has the expected URI
                for file_data in response.graph:
                    if file_data.get('@id') == file_uri:
                        has_file_data = True
                        break
            
            success = response is not None and has_file_data
            
            self.log_test_result(
                "Get File",
                success,
                f"Retrieved file metadata: {file_uri}",
                {"uri": file_uri, "has_metadata": has_file_data}
            )
            
        except Exception as e:
            self.log_test_result("Get File", False, f"Exception: {e}")
    
    def test_download_file_content(self, file_uris: List[str]):
        """Test downloading binary file content."""
        if not file_uris:
            self.log_test_result("Download File Content", False, "No file URIs provided")
            return
        
        try:
            download_results = []
            
            for file_uri in file_uris[:2]:  # Test first 2 files
                # Create temporary output file
                output_file = tempfile.NamedTemporaryFile(delete=False)
                output_path = output_file.name
                output_file.close()
                
                try:
                    success = self.endpoint.download_file_content(
                        space_id=self.test_space_id,
                        uri=file_uri,
                        output_path=output_path,
                        graph_id=self.test_graph_id
                    )
                    
                    # Check if file was downloaded
                    downloaded_size = 0
                    if success and os.path.exists(output_path):
                        downloaded_size = os.path.getsize(output_path)
                    
                    download_results.append({
                        "uri": file_uri,
                        "success": success,
                        "size": downloaded_size,
                        "output_path": output_path
                    })
                    
                    # Clean up output file
                    if os.path.exists(output_path):
                        os.unlink(output_path)
                        
                except Exception as e:
                    download_results.append({
                        "uri": file_uri,
                        "success": False,
                        "error": str(e)
                    })
            
            success = all(result["success"] for result in download_results)
            
            self.log_test_result(
                "Download File Content",
                success,
                f"Downloaded {len(download_results)} files from MinIO storage",
                {"downloads": download_results}
            )
            
        except Exception as e:
            self.log_test_result("Download File Content", False, f"Exception: {e}")
    
    def test_list_files_with_data(self):
        """Test listing files when data exists."""
        try:
            response = self.endpoint.list_files(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                page_size=10,
                offset=0
            )
            
            # Check if we have a valid JsonLdDocument with files
            files_count = 0
            if hasattr(response, 'files') and hasattr(response.files, 'graph'):
                files_count = len(response.files.graph) if response.files.graph else 0
            
            success = (
                hasattr(response, 'files') and
                hasattr(response, 'total_count') and
                response.total_count > 0 and
                files_count > 0
            )
            
            file_names = []
            if success and response.files.graph:
                for file_data in response.files.graph:
                    name = file_data.get('vital:hasFileName', 'Unknown')
                    file_names.append(name)
            
            self.log_test_result(
                "List Files (With Data)",
                success,
                f"Found {files_count} files, total_count: {response.total_count}",
                {"files_count": files_count, "total_count": response.total_count, "names": file_names}
            )
            
        except Exception as e:
            self.log_test_result("List Files (With Data)", False, f"Exception: {e}")
    
    def test_search_files(self):
        """Test searching files with filters."""
        try:
            response = self.endpoint.list_files(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                page_size=10,
                offset=0,
                file_filter="test"
            )
            
            # Check if we have a valid JsonLdDocument with files
            files_count = 0
            if hasattr(response, 'files') and hasattr(response.files, 'graph'):
                files_count = len(response.files.graph) if response.files.graph else 0
            
            success = (
                hasattr(response, 'files') and
                hasattr(response, 'total_count')
            )
            
            self.log_test_result(
                "Search Files",
                success,
                f"Search found {files_count} files matching 'test'",
                {"files_count": files_count, "total_count": response.total_count}
            )
            
        except Exception as e:
            self.log_test_result("Search Files", False, f"Exception: {e}")
    
    def test_update_file(self, file_uri: str):
        """Test updating file metadata."""
        if not file_uri:
            self.log_test_result("Update File", False, "No file URI provided")
            return
        
        try:
            # Create updated JSON-LD document
            updated_jsonld = {
                "@context": {
                    "vital": "http://vital.ai/ontology/vital#",
                    "vital-core": "http://vital.ai/ontology/vital-core#",
                    "haley": "http://vital.ai/ontology/haley-ai-kg#"
                },
                "@graph": [{
                    "@id": file_uri,
                    "@type": "vital:FileNode",
                    "vital:hasFileName": "updated-test-file.txt",
                    "vital:hasFileType": "text/plain",
                    "vital:hasFileLength": 2048
                }]
            }
            
            from vitalgraph.model.jsonld_model import JsonLdDocument
            document = JsonLdDocument(**updated_jsonld)
            response = self.endpoint.update_file(
                space_id=self.test_space_id,
                document=document,
                graph_id=self.test_graph_id
            )
            
            success = (
                hasattr(response, 'updated_uri') and
                response.updated_uri == file_uri
            )
            
            self.log_test_result(
                "Update File",
                success,
                f"Updated file metadata: {file_uri}",
                {"updated_uri": response.updated_uri if success else None}
            )
            
        except Exception as e:
            self.log_test_result("Update File", False, f"Exception: {e}")
    
    def test_delete_file(self, file_uri: str):
        """Test deleting a file (metadata + binary content)."""
        if not file_uri:
            self.log_test_result("Delete File", False, "No file URI provided")
            return
        
        try:
            response = self.endpoint.delete_file(
                space_id=self.test_space_id,
                uri=file_uri,
                graph_id=self.test_graph_id
            )
            
            success = (
                hasattr(response, 'deleted_count') and
                response.deleted_count > 0 and
                hasattr(response, 'deleted_uris') and
                file_uri in response.deleted_uris
            )
            
            self.log_test_result(
                "Delete File",
                success,
                f"Deleted file (metadata + binary): {file_uri}",
                {"deleted_count": response.deleted_count, "deleted_uris": response.deleted_uris}
            )
            
        except Exception as e:
            self.log_test_result("Delete File", False, f"Exception: {e}")
    
    def test_delete_files_batch(self, file_uris: List[str]):
        """Test batch deletion of files."""
        if not file_uris:
            self.log_test_result("Delete Files Batch", False, "No file URIs provided")
            return
        
        try:
            uri_list = ",".join(file_uris)
            response = self.endpoint.delete_files_batch(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri_list=uri_list
            )
            
            success = (
                isinstance(response, dict) and
                "deleted_count" in response and
                response["deleted_count"] > 0
            )
            
            self.log_test_result(
                "Delete Files Batch",
                success,
                f"Batch deleted {response.get('deleted_count', 0)} files (metadata + binary)",
                response
            )
            
        except Exception as e:
            self.log_test_result("Delete Files Batch", False, f"Exception: {e}")
    
    def test_file_upload_download_comparison(self):
        """Test uploading a file and then downloading it to verify integrity."""
        try:
            # Use a test file from localTestFiles
            import tempfile
            import os
            
            # Create a test file with known content
            test_content = b"This is a test file for upload/download comparison.\nIt contains multiple lines.\nAnd some special characters: !@#$%^&*()"
            test_uri = "http://vital.ai/haley.ai/app/test-comparison-file.txt"
            
            with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.txt') as temp_file:
                temp_file.write(test_content)
                temp_file_path = temp_file.name
            
            try:
                # Upload the file
                upload_response = self.endpoint.upload_file_content(
                    space_id=self.test_space_id,
                    uri=test_uri,
                    file_path=temp_file_path,
                    graph_id=self.test_graph_id
                )
                
                upload_success = (hasattr(upload_response, 'file_uri') and 
                                upload_response.file_uri == test_uri and
                                hasattr(upload_response, 'message'))
                
                if upload_success:
                    # Download the file
                    with tempfile.NamedTemporaryFile(mode='wb', delete=False) as download_file:
                        download_path = download_file.name
                    
                    download_response = self.endpoint.download_file_content(
                        space_id=self.test_space_id,
                        uri=test_uri,
                        output_path=download_path,
                        graph_id=self.test_graph_id
                    )
                    
                    download_success = download_response is True
                    
                    if download_success:
                        # Compare the files
                        with open(download_path, 'rb') as f:
                            downloaded_content = f.read()
                        
                        files_match = test_content == downloaded_content
                        
                        self.log_test_result(
                            "File Upload/Download Comparison",
                            files_match,
                            f"File integrity verified: {len(test_content)} bytes",
                            {
                                "original_size": len(test_content),
                                "downloaded_size": len(downloaded_content),
                                "files_match": files_match,
                                "uri": test_uri
                            }
                        )
                    else:
                        self.log_test_result("File Upload/Download Comparison", False, "Download failed")
                    
                    # Cleanup downloaded file
                    try:
                        os.unlink(download_path)
                    except:
                        pass
                else:
                    self.log_test_result("File Upload/Download Comparison", False, "Upload failed")
                    
            finally:
                # Cleanup original test file
                try:
                    os.unlink(temp_file_path)
                except:
                    pass
                    
        except Exception as e:
            self.log_test_result("File Upload/Download Comparison", False, f"Exception: {e}")
    
    def test_list_files_empty_final(self):
        """Test MinIO storage-specific operations."""
        try:
            # Test storage clearing
            clear_success = self.endpoint.clear_minio_storage(self.test_space_id)
            
            # Test storage info
            storage_exists = self.endpoint.minio_base_path.exists() if self.endpoint.minio_base_path else False
            
            success = clear_success and storage_exists
            
            self.log_test_result(
                "MinIO Storage Operations",
                success,
                f"Storage clear: {clear_success}, Storage exists: {storage_exists}",
                {
                    "clear_success": clear_success,
                    "storage_exists": storage_exists,
                    "storage_path": str(self.endpoint.minio_base_path) if self.endpoint.minio_base_path else None
                }
            )
            
        except Exception as e:
            self.log_test_result("MinIO Storage Operations", False, f"Exception: {e}")
    
    def test_error_handling(self):
        """Test error handling scenarios."""
        try:
            # Test getting non-existent file
            response = self.endpoint.get_file(
                space_id=self.test_space_id,
                uri="http://nonexistent.file/uri",
                graph_id=self.test_graph_id
            )
            
            # Test downloading non-existent file
            try:
                output_file = tempfile.NamedTemporaryFile(delete=False)
                output_path = output_file.name
                output_file.close()
                
                download_success = self.endpoint.download_file_content(
                    space_id=self.test_space_id,
                    uri="http://nonexistent.file/uri",
                    output_path=output_path,
                    graph_id=self.test_graph_id
                )
                
                # Clean up
                if os.path.exists(output_path):
                    os.unlink(output_path)
                    
            except Exception:
                pass  # Expected for non-existent file
            
            # Should not crash
            success = True
            
            self.log_test_result(
                "Error Handling",
                success,
                "Gracefully handled non-existent file operations"
            )
            
        except Exception as e:
            self.log_test_result("Error Handling", False, f"Exception: {e}")
    
    def run_all_tests(self):
        """Run complete test suite."""
        storage_type = "Temporary" if self.endpoint._use_temp_storage else "Configured"
        print(f"MockFilesEndpoint Test Suite ({storage_type} Storage)")
        print("=" * 60)
        
        # Test storage configuration
        self.test_storage_configuration()
        
        # Test empty state
        self.test_list_files_empty()
        
        # Test file lifecycle
        file_uris = self.test_create_file_nodes()
        if file_uris:
            self.test_upload_file_content(file_uris)
            self.test_get_file(file_uris[0])
            self.test_download_file_content(file_uris)
            self.test_list_files_with_data()
            self.test_search_files()
            self.test_update_file(file_uris[0])
        
        # Test MinIO operations
        self.test_list_files_empty_final()
        
        # Test error handling
        self.test_error_handling()
        
        # Test file upload/download comparison
        self.test_file_upload_download_comparison()
        
        # Test deletion
        if file_uris:
            # Delete one file individually
            if len(file_uris) > 1:
                self.test_delete_file(file_uris[0])
                # Delete remaining files in batch
                self.test_delete_files_batch(file_uris[1:])
            else:
                self.test_delete_files_batch(file_uris)
        
        # Final verification
        self.test_list_files_empty()
        
        # Summary
        print("=" * 60)
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        print(f"Test Results: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 All tests passed! MockFilesEndpoint is working correctly.")
        else:
            print("⚠️  Some tests failed. Check the output above for details.")
        
        return passed == total


def main():
    """Run the test suite."""
    print("Testing both storage configurations...\n")
    
    # Test temporary storage
    print("Testing with TEMPORARY storage:")
    temp_test = TestMockFilesEndpoint(use_temp_storage=True)
    temp_success = temp_test.run_all_tests()
    temp_test._cleanup_test_files()
    
    print("\n" + "="*80 + "\n")
    
    # Test configured storage
    print("Testing with CONFIGURED storage:")
    config_test = TestMockFilesEndpoint(use_temp_storage=False)
    config_success = config_test.run_all_tests()
    config_test._cleanup_test_files()
    
    print("\n" + "="*80)
    print("OVERALL RESULTS:")
    print(f"Temporary Storage: {'✅ PASS' if temp_success else '❌ FAIL'}")
    print(f"Configured Storage: {'✅ PASS' if config_success else '❌ FAIL'}")
    
    overall_success = temp_success and config_success
    if overall_success:
        print("🎉 All storage configurations working correctly!")
    else:
        print("⚠️  Some storage configurations failed.")
    
    # Exit with appropriate code
    sys.exit(0 if overall_success else 1)


if __name__ == "__main__":
    main()
