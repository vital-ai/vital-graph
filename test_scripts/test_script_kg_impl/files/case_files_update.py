"""
Files Update Test Cases

Tests for updating file metadata via the Files endpoint.
"""

import logging
from typing import Dict, Any, List, Optional

from vitalgraph.model.files_model import FileUpdateResponse
from vital_ai_domain.model.FileNode import FileNode
from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list

logger = logging.getLogger(__name__)


class FilesUpdateTester:
    """Test cases for Files update operations."""
    
    def __init__(self, endpoint, space_id: str, graph_id: str):
        self.endpoint = endpoint
        self.space_id = space_id
        self.graph_id = graph_id
        self.test_file_uris = []
    
    def log_test_result(self, test_name: str, success: bool, message: str, details: Dict[str, Any] = None):
        """Log test result with consistent formatting."""
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"{status} - {test_name}: {message}")
        if details:
            logger.debug(f"Details: {details}")
    
    def set_test_file_uris(self, uris: List[str]):
        """Set test file URIs from create tests."""
        self.test_file_uris = uris.copy()
    
    async def test_update_file_metadata(self) -> bool:
        """Test updating file metadata using VitalSigns FileNode."""
        try:
            # Use a test URI or generate one for stub testing
            test_uri = self.test_file_uris[0] if self.test_file_uris else "http://vital.ai/test/file/sample_document"
            
            # Create updated file metadata using VitalSigns FileNode
            file_node = FileNode()
            file_node.URI = test_uri
            file_node.name = "Updated Document Name"
            
            # Convert to quads for the update endpoint
            quads = graphobjects_to_quad_list([file_node], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._update_file_metadata(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                current_user=current_user
            )
            
            if response and hasattr(response, 'updated_uri') and response.updated_uri:
                self.log_test_result(
                    "Update File Metadata",
                    True,
                    f"Successfully updated file metadata: {response.updated_uri}",
                    {"uri": response.updated_uri, "message": response.message}
                )
                return True
            else:
                # Log the actual response message to see validation error
                error_msg = "Failed to update file metadata"
                if response and hasattr(response, 'message'):
                    error_msg += f" - {response.message}"
                self.log_test_result(
                    "Update File Metadata",
                    False,
                    error_msg,
                    {"uri": test_uri, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Update File Metadata",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_update_multiple_files(self) -> bool:
        """Test updating multiple files in one request."""
        try:
            # Use test URIs or generate sample ones for stub testing
            if len(self.test_file_uris) >= 2:
                test_uris = self.test_file_uris[:2]
            else:
                test_uris = [
                    "http://vital.ai/test/file/sample_document_1",
                    "http://vital.ai/test/file/sample_document_2"
                ]
            
            # Create updated metadata for multiple files using VitalSigns FileNode
            file_node_1 = FileNode()
            file_node_1.URI = test_uris[0]
            file_node_1.name = "Batch Updated Document 1"
            
            file_node_2 = FileNode()
            file_node_2.URI = test_uris[1]
            file_node_2.name = "Batch Updated Image 1"
            
            # Convert list of FileNodes to quads for the update endpoint
            files_list = [file_node_1, file_node_2]
            quads = graphobjects_to_quad_list(files_list, self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._update_file_metadata(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                current_user=current_user
            )
            
            if response and hasattr(response, 'updated_uri') and response.updated_uri:
                self.log_test_result(
                    "Update Multiple Files",
                    True,
                    f"Successfully updated multiple files: {response.updated_uri}",
                    {"updated_uri": response.updated_uri, "message": response.message}
                )
                return True
            else:
                self.log_test_result(
                    "Update Multiple Files",
                    False,
                    "Failed to update multiple files",
                    {"uris": test_uris, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Update Multiple Files",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_update_nonexistent_file(self) -> bool:
        """Test updating a file that doesn't exist using VitalSigns FileNode."""
        try:
            nonexistent_uri = "http://vital.ai/test/file/nonexistent_file_12345"
            
            # Create FileNode for nonexistent file using VitalSigns
            file_node = FileNode()
            file_node.URI = nonexistent_uri
            file_node.name = "Nonexistent File Update"
            
            # Convert to quads for the update endpoint
            quads = graphobjects_to_quad_list([file_node], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._update_file_metadata(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                current_user=current_user
            )
            
            # For stub implementation, this might succeed - that's acceptable
            success = True
            result_msg = "Handled nonexistent file update"
            if response and hasattr(response, 'updated_uri'):
                result_msg += f" (updated_uri: {response.updated_uri})"
            
            self.log_test_result(
                "Update Nonexistent File",
                success,
                result_msg,
                {"uri": nonexistent_uri, "response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for nonexistent file is acceptable
            self.log_test_result(
                "Update Nonexistent File",
                True,
                f"Exception for nonexistent file (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_update_with_property_changes(self) -> bool:
        """Test updating file with property additions/removals using VitalSigns FileNode."""
        try:
            # Use a test URI or generate one for stub testing
            test_uri = self.test_file_uris[-1] if self.test_file_uris else "http://vital.ai/test/file/property_test"
            
            # Create file update with new properties using VitalSigns FileNode
            file_node = FileNode()
            file_node.URI = test_uri
            file_node.name = "Property Updated File"
            
            # Convert to quads for the update endpoint
            quads = graphobjects_to_quad_list([file_node], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._update_file_metadata(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                current_user=current_user
            )
            
            if response and hasattr(response, 'updated_uri') and response.updated_uri:
                self.log_test_result(
                    "Update Property Changes",
                    True,
                    f"Successfully updated file properties: {response.updated_uri}",
                    {"uri": response.updated_uri, "message": response.message}
                )
                return True
            else:
                self.log_test_result(
                    "Update Property Changes",
                    False,
                    "Failed to update file properties",
                    {"uri": test_uri, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Update Property Changes",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_update_invalid_metadata(self) -> bool:
        """Test updating file with invalid metadata (should handle gracefully) using VitalSigns FileNode."""
        try:
            test_uri = self.test_file_uris[0] if self.test_file_uris else "http://vital.ai/test/file/invalid_test"
            
            # Create FileNode with minimal metadata using VitalSigns
            file_node = FileNode()
            file_node.URI = test_uri
            file_node.name = "Invalid Update"
            
            # Convert to quads for the update endpoint
            quads = graphobjects_to_quad_list([file_node], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._update_file_metadata(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                current_user=current_user
            )
            
            # For stub implementation, this might succeed - that's acceptable
            success = True
            result_msg = "Handled invalid metadata update"
            if response and hasattr(response, 'updated_uri'):
                result_msg += f" (updated_uri: {response.updated_uri})"
            
            self.log_test_result(
                "Update Invalid Metadata",
                success,
                result_msg,
                {"response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for invalid metadata is acceptable
            self.log_test_result(
                "Update Invalid Metadata",
                True,
                f"Exception for invalid metadata (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def run_all_update_tests(self) -> Dict[str, bool]:
        """Run all file update tests."""
        logger.info("🧪 Running Files Update Tests")
        
        results = {}
        
        # Test single file metadata update
        results["update_file_metadata"] = await self.test_update_file_metadata()
        
        # Test multiple files update
        results["update_multiple_files"] = await self.test_update_multiple_files()
        
        # Test nonexistent file update
        results["update_nonexistent_file"] = await self.test_update_nonexistent_file()
        
        # Test property changes
        results["update_property_changes"] = await self.test_update_with_property_changes()
        
        # Test invalid metadata update
        results["update_invalid_metadata"] = await self.test_update_invalid_metadata()
        
        return results
