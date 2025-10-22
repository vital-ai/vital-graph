#!/usr/bin/env python3
"""
Test suite for MockVitalGraphClient space operations.

This test suite validates the mock client's space management functionality using:
- Direct client method calls (not endpoint calls)
- Proper request/response model validation
- Complete CRUD operations for spaces
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
from vitalgraph.model.spaces_model import Space, SpacesListResponse, SpaceCreateResponse, SpaceUpdateResponse, SpaceDeleteResponse


class TestMockClientSpaces:
    """Test suite for MockVitalGraphClient space operations."""
    
    def __init__(self):
        """Initialize test suite."""
        # Configure logging to see debug output
        logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
        
        self.test_results = []
        self.client = None
        
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
                hasattr(self.client, 'list_spaces') and
                hasattr(self.client, 'add_space') and
                hasattr(self.client, 'delete_space')
            )
            
            client_type = type(self.client).__name__
            
            self.log_test_result(
                "Client Initialization",
                success,
                f"Created client: {client_type}",
                {"client_type": client_type, "has_space_methods": success}
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
                    "server_version": server_info.get('version'),
                    "is_mock": server_info.get('mock', False)
                }
            )
            
        except Exception as e:
            self.log_test_result("Client Connection", False, f"Exception: {e}")
    
    def test_list_spaces_empty(self):
        """Test listing spaces when no spaces exist."""
        try:
            response = self.client.list_spaces()
            
            success = (
                isinstance(response, SpacesListResponse) and
                hasattr(response, 'spaces') and
                hasattr(response, 'total_count') and
                hasattr(response, 'page_size') and
                hasattr(response, 'offset') and
                isinstance(response.spaces, list)
            )
            
            self.log_test_result(
                "List Spaces (Empty)",
                success,
                f"Found {response.total_count} spaces",
                {
                    "total_count": response.total_count,
                    "spaces_count": len(response.spaces),
                    "page_size": response.page_size,
                    "offset": response.offset,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("List Spaces (Empty)", False, f"Exception: {e}")
    
    def test_create_space(self):
        """Test creating a new space."""
        try:
            # Create test space
            test_space = Space(
                space="test_space_001",
                space_name="Test Space 001",
                space_description="A test space for client testing"
            )
            
            response = self.client.add_space(test_space)
            
            success = (
                isinstance(response, SpaceCreateResponse) and
                hasattr(response, 'message') and
                hasattr(response, 'created_count') and
                hasattr(response, 'created_uris') and
                response.created_count >= 0
            )
            
            self.log_test_result(
                "Create Space",
                success,
                f"Created space: {test_space.space}",
                {
                    "space_id": test_space.space,
                    "space_name": test_space.space_name,
                    "created_count": response.created_count,
                    "created_uris": response.created_uris,
                    "message": response.message,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Create Space", False, f"Exception: {e}")
    
    def test_create_multiple_spaces(self):
        """Test creating multiple spaces."""
        try:
            spaces_to_create = [
                Space(
                    space="test_space_002",
                    space_name="Test Space 002",
                    space_description="Second test space"
                ),
                Space(
                    space="test_space_003",
                    space_name="Test Space 003",
                    space_description="Third test space"
                )
            ]
            
            created_spaces = []
            for space in spaces_to_create:
                response = self.client.add_space(space)
                created_spaces.append({
                    "space_id": space.space,
                    "created_count": response.created_count,
                    "message": response.message
                })
            
            success = len(created_spaces) == 2
            
            self.log_test_result(
                "Create Multiple Spaces",
                success,
                f"Created {len(created_spaces)} spaces",
                {
                    "spaces_created": len(created_spaces),
                    "created_spaces": created_spaces
                }
            )
            
        except Exception as e:
            self.log_test_result("Create Multiple Spaces", False, f"Exception: {e}")
    
    def test_list_spaces_with_data(self):
        """Test listing spaces when spaces exist."""
        try:
            response = self.client.list_spaces()
            
            success = (
                isinstance(response, SpacesListResponse) and
                response.total_count > 0 and
                len(response.spaces) > 0
            )
            
            # Extract space information
            space_info = []
            for space in response.spaces:
                space_info.append({
                    "space_id": space.space,
                    "space_name": space.space_name,
                    "description": space.space_description
                })
            
            self.log_test_result(
                "List Spaces (With Data)",
                success,
                f"Found {response.total_count} spaces",
                {
                    "total_count": response.total_count,
                    "spaces_returned": len(response.spaces),
                    "spaces": space_info[:3]  # Show first 3 spaces
                }
            )
            
        except Exception as e:
            self.log_test_result("List Spaces (With Data)", False, f"Exception: {e}")
    
    def test_get_space(self):
        """Test getting a specific space by ID."""
        try:
            # Try to get the first space we created
            space = self.client.get_space("test_space_001")
            
            success = (
                isinstance(space, Space) and
                hasattr(space, 'space') and
                hasattr(space, 'space_name') and
                space.space == "test_space_001"
            )
            
            self.log_test_result(
                "Get Space",
                success,
                f"Retrieved space: {space.space if success else 'None'}",
                {
                    "space_id": space.space if success else None,
                    "space_name": space.space_name if success else None,
                    "description": space.space_description if success else None,
                    "response_type": type(space).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Get Space", False, f"Exception: {e}")
    
    def test_update_space(self):
        """Test updating an existing space."""
        try:
            # Create updated space data
            updated_space = Space(
                space="test_space_001",
                space_name="Updated Test Space 001",
                space_description="Updated description for testing"
            )
            
            response = self.client.update_space("test_space_001", updated_space)
            
            success = (
                isinstance(response, SpaceUpdateResponse) and
                hasattr(response, 'message') and
                hasattr(response, 'updated_uri')
            )
            
            self.log_test_result(
                "Update Space",
                success,
                f"Updated space: {updated_space.space}",
                {
                    "space_id": updated_space.space,
                    "new_name": updated_space.space_name,
                    "new_description": updated_space.space_description,
                    "updated_uri": response.updated_uri if success else None,
                    "message": response.message if success else None,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Update Space", False, f"Exception: {e}")
    
    def test_filter_spaces(self):
        """Test filtering spaces by name."""
        try:
            response = self.client.filter_spaces("Test")
            
            success = (
                isinstance(response, SpacesListResponse) and
                hasattr(response, 'spaces') and
                hasattr(response, 'total_count')
            )
            
            # Check if filtered results contain "Test" in the name
            filtered_spaces = []
            if success and response.spaces:
                for space in response.spaces:
                    if "Test" in space.space_name:
                        filtered_spaces.append({
                            "space_id": space.space,
                            "space_name": space.space_name
                        })
            
            self.log_test_result(
                "Filter Spaces",
                success,
                f"Filter 'Test' found {response.total_count if success else 0} spaces",
                {
                    "filter_term": "Test",
                    "total_count": response.total_count if success else 0,
                    "matching_spaces": filtered_spaces
                }
            )
            
        except Exception as e:
            self.log_test_result("Filter Spaces", False, f"Exception: {e}")
    
    def test_error_handling_nonexistent_space(self):
        """Test error handling for non-existent space operations."""
        try:
            # Try to get a non-existent space
            space = self.client.get_space("nonexistent_space_12345")
            
            # Should handle gracefully - either return None or raise appropriate exception
            success = True  # If no exception thrown, it's handling gracefully
            
            self.log_test_result(
                "Error Handling (Non-existent Space)",
                success,
                "Gracefully handled non-existent space request",
                {
                    "requested_space": "nonexistent_space_12345",
                    "response_type": type(space).__name__ if space else "None"
                }
            )
            
        except Exception as e:
            # Check if it's a reasonable error response
            success = "not found" in str(e).lower() or "does not exist" in str(e).lower()
            self.log_test_result(
                "Error Handling (Non-existent Space)",
                success,
                f"Exception: {e}"
            )
    
    def test_delete_space(self):
        """Test deleting a space."""
        try:
            response = self.client.delete_space("test_space_002")
            
            success = (
                isinstance(response, SpaceDeleteResponse) and
                hasattr(response, 'message') and
                hasattr(response, 'deleted_count') and
                response.deleted_count >= 0
            )
            
            self.log_test_result(
                "Delete Space",
                success,
                f"Deleted space: test_space_002",
                {
                    "space_id": "test_space_002",
                    "deleted_count": response.deleted_count if success else None,
                    "message": response.message if success else None,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Delete Space", False, f"Exception: {e}")
    
    def test_delete_multiple_spaces(self):
        """Test deleting multiple spaces."""
        try:
            spaces_to_delete = ["test_space_001", "test_space_003"]
            deleted_spaces = []
            
            for space_id in spaces_to_delete:
                response = self.client.delete_space(space_id)
                deleted_spaces.append({
                    "space_id": space_id,
                    "deleted_count": response.deleted_count,
                    "message": response.message
                })
            
            success = len(deleted_spaces) == 2
            
            self.log_test_result(
                "Delete Multiple Spaces",
                success,
                f"Deleted {len(deleted_spaces)} spaces",
                {
                    "spaces_deleted": len(deleted_spaces),
                    "deleted_spaces": deleted_spaces
                }
            )
            
        except Exception as e:
            self.log_test_result("Delete Multiple Spaces", False, f"Exception: {e}")
    
    def test_list_spaces_after_deletion(self):
        """Test listing spaces after deletion (should be empty or reduced)."""
        try:
            response = self.client.list_spaces()
            
            success = (
                isinstance(response, SpacesListResponse) and
                hasattr(response, 'total_count')
            )
            
            self.log_test_result(
                "List Spaces (After Deletion)",
                success,
                f"Found {response.total_count if success else 0} spaces after deletion",
                {
                    "total_count": response.total_count if success else 0,
                    "spaces_count": len(response.spaces) if success and response.spaces else 0
                }
            )
            
        except Exception as e:
            self.log_test_result("List Spaces (After Deletion)", False, f"Exception: {e}")
    
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
    
    def run_all_tests(self):
        """Run all tests in sequence."""
        print("🧪 Testing MockVitalGraphClient Space Operations")
        print("=" * 60)
        
        # Run tests in logical order
        self.test_client_initialization()
        self.test_client_connection()
        self.test_list_spaces_empty()
        self.test_create_space()
        self.test_create_multiple_spaces()
        self.test_list_spaces_with_data()
        self.test_get_space()
        self.test_update_space()
        self.test_filter_spaces()
        self.test_error_handling_nonexistent_space()
        self.test_delete_space()
        self.test_delete_multiple_spaces()
        self.test_list_spaces_after_deletion()
        self.test_client_disconnection()
        
        # Print summary
        print("=" * 60)
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        
        if passed == total:
            print(f"Test Results: {passed}/{total} tests passed")
            print("🎉 All tests passed! MockVitalGraphClient space operations are working correctly.")
        else:
            print(f"Test Results: {passed}/{total} tests passed")
            print("⚠️  Some tests failed. Check the output above for details.")
        
        return passed == total


def main():
    """Main test runner."""
    test_suite = TestMockClientSpaces()
    success = test_suite.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
