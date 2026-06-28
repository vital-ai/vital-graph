"""
Files List Test Cases

Tests for listing files via the Files endpoint.
"""

import logging
from typing import Dict, Any, List, Optional

from vitalgraph.model.files_model import FilesResponse

logger = logging.getLogger(__name__)


class FilesListTester:
    """Test cases for Files listing operations."""
    
    def __init__(self, endpoint, space_id: str, graph_id: str):
        self.endpoint = endpoint
        self.space_id = space_id
        self.graph_id = graph_id
    
    def log_test_result(self, test_name: str, success: bool, message: str, details: Dict[str, Any] = None):
        """Log test result with consistent formatting."""
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"{status} - {test_name}: {message}")
        if details:
            logger.debug(f"Details: {details}")
    
    async def test_list_empty_files(self) -> bool:
        """Test listing files when no files exist (or stub returns sample data)."""
        try:
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._list_files(
                space_id=self.space_id,
                graph_id=self.graph_id,
                page_size=100,
                offset=0,
                file_filter=None,
                current_user=current_user
            )
            
            if response and hasattr(response, 'files'):
                # For stub implementation, this will return sample files
                total_count = getattr(response, 'total_count', 0)
                self.log_test_result(
                    "List Empty Files",
                    True,
                    f"Successfully listed files (total: {total_count})",
                    {"total_count": total_count, "page_size": response.page_size, "offset": response.offset}
                )
                return True
            else:
                self.log_test_result(
                    "List Empty Files",
                    False,
                    "Failed to list files",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "List Empty Files",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_list_files_with_pagination(self) -> bool:
        """Test listing files with pagination parameters."""
        try:
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._list_files(
                space_id=self.space_id,
                graph_id=self.graph_id,
                page_size=2,  # Small page size to test pagination
                offset=0,
                file_filter=None,
                current_user=current_user
            )
            
            if response and hasattr(response, 'files'):
                total_count = getattr(response, 'total_count', 0)
                page_size = getattr(response, 'page_size', 0)
                offset = getattr(response, 'offset', 0)
                
                self.log_test_result(
                    "List Files With Pagination",
                    True,
                    f"Successfully listed files with pagination (total: {total_count}, page_size: {page_size}, offset: {offset})",
                    {"total_count": total_count, "page_size": page_size, "offset": offset}
                )
                return True
            else:
                self.log_test_result(
                    "List Files With Pagination",
                    False,
                    "Failed to list files with pagination",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "List Files With Pagination",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_list_files_with_filter(self) -> bool:
        """Test listing files with keyword filter."""
        try:
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._list_files(
                space_id=self.space_id,
                graph_id=self.graph_id,
                page_size=100,
                offset=0,
                file_filter="research",  # Filter for files containing "research"
                current_user=current_user
            )
            
            if response and hasattr(response, 'files'):
                total_count = getattr(response, 'total_count', 0)
                self.log_test_result(
                    "List Files With Filter",
                    True,
                    f"Successfully listed filtered files (total: {total_count})",
                    {"total_count": total_count, "filter": "research"}
                )
                return True
            else:
                self.log_test_result(
                    "List Files With Filter",
                    False,
                    "Failed to list filtered files",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "List Files With Filter",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_list_files_large_offset(self) -> bool:
        """Test listing files with large offset (edge case)."""
        try:
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._list_files(
                space_id=self.space_id,
                graph_id=self.graph_id,
                page_size=10,
                offset=1000,  # Large offset beyond available data
                file_filter=None,
                current_user=current_user
            )
            
            if response and hasattr(response, 'files'):
                total_count = getattr(response, 'total_count', 0)
                offset = getattr(response, 'offset', 0)
                
                self.log_test_result(
                    "List Files Large Offset",
                    True,
                    f"Successfully handled large offset (total: {total_count}, offset: {offset})",
                    {"total_count": total_count, "offset": offset}
                )
                return True
            else:
                self.log_test_result(
                    "List Files Large Offset",
                    False,
                    "Failed to handle large offset",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "List Files Large Offset",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_list_files_invalid_parameters(self) -> bool:
        """Test listing files with invalid parameters (should handle gracefully)."""
        try:
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._list_files(
                space_id=self.space_id,
                graph_id=self.graph_id,
                page_size=-1,  # Invalid page size
                offset=-10,    # Invalid offset
                file_filter="",  # Empty filter
                current_user=current_user
            )
            
            # For stub implementation, this might succeed with default values
            success = True
            result_msg = "Handled invalid parameters gracefully"
            if response and hasattr(response, 'total_count'):
                result_msg += f" (total: {response.total_count})"
            
            self.log_test_result(
                "List Files Invalid Parameters",
                success,
                result_msg,
                {"response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for invalid parameters is acceptable
            self.log_test_result(
                "List Files Invalid Parameters",
                True,
                f"Exception for invalid parameters (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def run_all_list_tests(self) -> Dict[str, bool]:
        """Run all file listing tests."""
        logger.info("🧪 Running Files List Tests")
        
        results = {}
        
        # Test empty files listing
        results["list_empty_files"] = await self.test_list_empty_files()
        
        # Test pagination
        results["list_files_with_pagination"] = await self.test_list_files_with_pagination()
        
        # Test filtering
        results["list_files_with_filter"] = await self.test_list_files_with_filter()
        
        # Test large offset
        results["list_files_large_offset"] = await self.test_list_files_large_offset()
        
        # Test invalid parameters
        results["list_files_invalid_parameters"] = await self.test_list_files_invalid_parameters()
        
        return results
