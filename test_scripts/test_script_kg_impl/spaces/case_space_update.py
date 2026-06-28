#!/usr/bin/env python3
"""
Space Update Test Module

Modular test implementation for space update operations.
Used by the main Spaces endpoint test orchestrator.

Focuses on:
- Space metadata updates
- Dual-write consistency for updates
- Response validation
- Error handling for invalid updates
"""

import logging
from typing import Dict, Any, Optional

# Import models
from vitalgraph.model.spaces_model import Space, SpaceUpdateResponse

logger = logging.getLogger(__name__)


class SpaceUpdateTester:
    """
    Modular test implementation for space update operations.
    
    Handles:
    - Space metadata updates
    - Dual-write consistency validation
    - Response format verification
    - Error handling for invalid operations
    """
    
    def __init__(self, endpoint, space_manager):
        """
        Initialize the space update tester.
        
        Args:
            endpoint: SpacesEndpoint instance
            space_manager: SpaceManager instance for validation
        """
        self.endpoint = endpoint
        self.space_manager = space_manager
        self.logger = logging.getLogger(f"{__name__}.SpaceUpdateTester")
    
    async def test_space_update(self, space_id: str, updated_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Test space update operations.
        
        Args:
            space_id: Space ID to update
            updated_data: Dictionary containing updated space data
            
        Returns:
            Dict containing test results and metadata
        """
        test_name = "Space Update Operations"
        
        try:
            self.logger.info(f"🧪 Testing space update for ID: {space_id}")
            
            # Get current space data for comparison
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            original_data = await self.endpoint.get_space(space_id, current_user)
            
            if not original_data:
                return {
                    "test_name": test_name,
                    "success": False,
                    "message": f"Could not retrieve original space data for ID: {space_id}",
                    "space_id": space_id
                }
            
            # Create updated space object
            updated_space = Space(
                space=space_id,
                space_name=updated_data.get("space_name", "Updated Test Space Name") if updated_data else "Updated Test Space Name",
                space_description=updated_data.get("space_description", "Updated description for dual-write validation") if updated_data else "Updated description for dual-write validation",
                tenant=updated_data.get("tenant", "updated_tenant") if updated_data else "updated_tenant"
            )
            
            # Call the endpoint update method
            response = await self.endpoint.update_space(space_id, updated_space, current_user)
            
            if not response:
                return {
                    "test_name": test_name,
                    "success": False,
                    "message": f"Space update returned None for ID: {space_id}",
                    "space_id": space_id
                }
            
            # Validate response structure
            validation_result = self._validate_update_response(response, space_id)
            if not validation_result["valid"]:
                return {
                    "test_name": test_name,
                    "success": False,
                    "message": f"Update response validation failed: {validation_result['message']}",
                    "space_id": space_id,
                    "validation": validation_result
                }
            
            # Verify the update was applied by retrieving the space again
            updated_data_retrieved = await self.endpoint.get_space(space_id, current_user)
            
            if not updated_data_retrieved:
                return {
                    "test_name": test_name,
                    "success": False,
                    "message": f"Could not retrieve updated space data for verification: {space_id}",
                    "space_id": space_id
                }
            
            # Validate that changes were applied
            changes_applied = self._validate_changes_applied(
                original_data, updated_data_retrieved, updated_data
            )
            
            if changes_applied["valid"]:
                return {
                    "test_name": test_name,
                    "success": True,
                    "message": f"Space updated successfully: {space_id}",
                    "space_id": space_id,
                    "original_data": original_data,
                    "updated_data": updated_data_retrieved,
                    "changes_validation": changes_applied,
                    "response_validation": validation_result
                }
            else:
                return {
                    "test_name": test_name,
                    "success": False,
                    "message": f"Changes validation failed: {changes_applied['message']}",
                    "space_id": space_id,
                    "changes_validation": changes_applied
                }
            
        except Exception as e:
            self.logger.error(f"Exception during space update: {e}")
            return {
                "test_name": test_name,
                "success": False,
                "message": f"Exception during space update: {e}",
                "space_id": space_id,
                "error": str(e)
            }
    
    async def test_invalid_space_update(self, invalid_space_id: str = "nonexistent_space_123") -> Dict[str, Any]:
        """
        Test update of a non-existent space to validate error handling.
        
        Args:
            invalid_space_id: Non-existent space ID to test
            
        Returns:
            Dict containing test results and metadata
        """
        test_name = "Invalid Space Update"
        
        try:
            self.logger.info(f"🧪 Testing update of non-existent space: {invalid_space_id}")
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            # Create space object for update
            updated_space = Space(
                space=invalid_space_id,
                space_name="Invalid Update Test",
                space_description="This should fail",
                tenant="test_tenant"
            )
            
            # Call the endpoint update method
            response = await self.endpoint.update_space(invalid_space_id, updated_space, current_user)
            
            # Should return None or raise an exception for non-existent space
            if response is None:
                return {
                    "test_name": test_name,
                    "success": True,
                    "message": f"Correctly returned None for non-existent space update: {invalid_space_id}",
                    "space_id": invalid_space_id
                }
            else:
                return {
                    "test_name": test_name,
                    "success": False,
                    "message": f"Unexpectedly succeeded updating non-existent space: {invalid_space_id}",
                    "space_id": invalid_space_id,
                    "unexpected_response": response
                }
            
        except Exception as e:
            # Exception is also acceptable for non-existent space
            self.logger.info(f"Expected exception for non-existent space update: {e}")
            return {
                "test_name": test_name,
                "success": True,
                "message": f"Correctly raised exception for non-existent space update: {invalid_space_id}",
                "space_id": invalid_space_id,
                "exception": str(e)
            }
    
    def _validate_update_response(self, response: Any, expected_space_id: str) -> Dict[str, Any]:
        """
        Validate the structure of the space update response.
        
        Args:
            response: Update response to validate
            expected_space_id: Expected space ID
            
        Returns:
            Dict with validation results
        """
        try:
            # Check if response has expected attributes
            if hasattr(response, 'message') and hasattr(response, 'updated_uri'):
                # Pydantic model format
                if response.updated_uri != expected_space_id:
                    return {
                        "valid": False,
                        "message": f"Updated URI mismatch: expected {expected_space_id}, got {response.updated_uri}",
                        "response_type": type(response).__name__
                    }
                
                return {
                    "valid": True,
                    "message": "Update response structure is valid",
                    "response_type": type(response).__name__,
                    "updated_uri": response.updated_uri
                }
            
            elif isinstance(response, dict):
                # Dictionary format
                if 'message' not in response:
                    return {
                        "valid": False,
                        "message": "Missing 'message' field in response",
                        "response_type": "dict"
                    }
                
                return {
                    "valid": True,
                    "message": "Update response structure is valid",
                    "response_type": "dict"
                }
            
            else:
                return {
                    "valid": False,
                    "message": f"Unexpected response type: {type(response)}",
                    "response_type": type(response).__name__
                }
            
        except Exception as e:
            return {
                "valid": False,
                "message": f"Exception during response validation: {e}",
                "error": str(e)
            }
    
    def _validate_changes_applied(self, original_data: Any, updated_data: Any, expected_changes: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate that the expected changes were applied to the space data.
        
        Args:
            original_data: Original space data
            updated_data: Updated space data
            expected_changes: Expected changes
            
        Returns:
            Dict with validation results
        """
        try:
            changes_found = []
            changes_missing = []
            
            for field, expected_value in expected_changes.items():
                # Get values from both original and updated data
                original_value = self._get_field_value(original_data, field)
                updated_value = self._get_field_value(updated_data, field)
                
                if updated_value == expected_value and updated_value != original_value:
                    changes_found.append({
                        "field": field,
                        "original": original_value,
                        "updated": updated_value,
                        "expected": expected_value
                    })
                else:
                    changes_missing.append({
                        "field": field,
                        "original": original_value,
                        "updated": updated_value,
                        "expected": expected_value
                    })
            
            if not changes_missing:
                return {
                    "valid": True,
                    "message": "All expected changes were applied",
                    "changes_found": changes_found,
                    "changes_missing": []
                }
            else:
                return {
                    "valid": False,
                    "message": f"Some changes were not applied: {[c['field'] for c in changes_missing]}",
                    "changes_found": changes_found,
                    "changes_missing": changes_missing
                }
            
        except Exception as e:
            return {
                "valid": False,
                "message": f"Exception during changes validation: {e}",
                "error": str(e)
            }
    
    def _get_field_value(self, data: Any, field: str) -> Any:
        """
        Get field value from data (handles both dict and object formats).
        
        Args:
            data: Data object or dict
            field: Field name to get
            
        Returns:
            Field value or None if not found
        """
        if hasattr(data, field):
            return getattr(data, field)
        elif isinstance(data, dict):
            return data.get(field)
        else:
            return None
