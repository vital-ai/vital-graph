#!/usr/bin/env python3
"""
Space Retrieval Test Module

Modular test implementation for space retrieval operations.
Used by the main Spaces endpoint test orchestrator.

Focuses on:
- Individual space retrieval by ID
- Response validation
- Data consistency checks
- Error handling for non-existent spaces
"""

import logging
from typing import Dict, Any, Optional

# Import models
from vitalgraph.model.spaces_model import Space

logger = logging.getLogger(__name__)


class SpaceGetTester:
    """Test case for space retrieval operations."""
    
    def __init__(self, spaces_endpoint):
        self.spaces_endpoint = spaces_endpoint
        self.logger = logging.getLogger(f"{__name__}.SpaceGetTester")
    
    async def test_space_retrieval(self, space_id: str) -> Dict[str, Any]:
        """
        Test individual space retrieval by ID using the working logic from the original test script.
        
        Args:
            space_id: Space ID to retrieve
            
        Returns:
            Dict with test results including success status and details
        """
        test_name = "Space Retrieval by ID"
        
        try:
            self.logger.info(f"🧪 Testing space retrieval for ID: {space_id}")
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            retrieved_space = await self.spaces_endpoint.api.get_space_by_id(space_id, current_user)
            
            if not retrieved_space:
                return {
                    "test_name": test_name,
                    "success": False,
                    "message": f"Failed to retrieve space: {space_id}",
                    "space_id": space_id
                }
            
            # Validate space data
            if retrieved_space.get('space') == space_id:
                return {
                    "test_name": test_name,
                    "success": True,
                    "message": f"Successfully retrieved space: {space_id}",
                    "space_id": space_id,
                    "space_data": retrieved_space
                }
            else:
                return {
                    "test_name": test_name,
                    "success": False,
                    "message": f"Retrieved space ID mismatch: expected {space_id}, got {retrieved_space.get('space')}",
                    "space_id": space_id,
                    "retrieved_space": retrieved_space
                }
            
        except Exception as e:
            self.logger.error(f"❌ Exception during space retrieval test: {e}")
            return {
                "test_name": test_name,
                "success": False,
                "message": f"Exception during space retrieval: {e}",
                "space_id": space_id,
                "error": str(e)
            }
    
    async def test_nonexistent_space_retrieval(self) -> Dict[str, Any]:
        """
        Test retrieval of non-existent space to validate error handling.
        Uses the working logic from the original test script.
        
        Returns:
            Dict with test results including success status and details
        """
        test_name = "Non-existent Space Retrieval"
        nonexistent_space_id = "nonexistent_space_123"
        
        try:
            self.logger.info(f"🧪 Testing retrieval of non-existent space: {nonexistent_space_id}")
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            try:
                retrieved_space = await self.spaces_endpoint.api.get_space_by_id(nonexistent_space_id, current_user)
                
                # If we get here without exception, the space was found (unexpected)
                if retrieved_space:
                    return {
                        "test_name": test_name,
                        "success": False,
                        "message": f"Unexpectedly found non-existent space: {nonexistent_space_id}",
                        "space_id": nonexistent_space_id,
                        "retrieved_space": retrieved_space
                    }
                else:
                    # Space not found (expected behavior)
                    return {
                        "test_name": test_name,
                        "success": True,
                        "message": f"Correctly handled non-existent space retrieval: {nonexistent_space_id}",
                        "space_id": nonexistent_space_id
                    }
                    
            except Exception as api_error:
                # Exception raised for non-existent space (expected behavior)
                self.logger.info(f"Expected exception for non-existent space retrieval: {api_error}")
                return {
                    "test_name": test_name,
                    "success": True,
                    "message": f"Correctly raised exception for non-existent space retrieval: {nonexistent_space_id}",
                    "space_id": nonexistent_space_id,
                    "expected_error": str(api_error)
                }
            
        except Exception as e:
            self.logger.error(f"❌ Unexpected exception during non-existent space retrieval test: {e}")
            return {
                "test_name": test_name,
                "success": False,
                "message": f"Unexpected exception during non-existent space retrieval: {e}",
                "space_id": nonexistent_space_id,
                "error": str(e)
            }
    
    def _validate_space_data(self, space_data: Any, expected_space_id: str) -> Dict[str, Any]:
        """
        Validate the structure and content of retrieved space data.
        
        Args:
            space_data: Space data to validate
            expected_space_id: Expected space ID
            
        Returns:
            Dict with validation results
        """
        try:
            # Check if space_data has expected structure
            if isinstance(space_data, dict):
                # Dictionary format
                required_fields = ['space', 'space_name']
                missing_fields = []
                
                for field in required_fields:
                    if field not in space_data:
                        missing_fields.append(field)
                
                if missing_fields:
                    return {
                        "valid": False,
                        "message": f"Missing required fields: {missing_fields}",
                        "data_type": "dict"
                    }
                
                # Validate space ID matches
                if space_data.get('space') != expected_space_id:
                    return {
                        "valid": False,
                        "message": f"Space ID mismatch: expected {expected_space_id}, got {space_data.get('space')}",
                        "data_type": "dict"
                    }
                
            elif hasattr(space_data, 'space'):
                # Pydantic model format
                if space_data.space != expected_space_id:
                    return {
                        "valid": False,
                        "message": f"Space ID mismatch: expected {expected_space_id}, got {space_data.space}",
                        "data_type": type(space_data).__name__
                    }
                
                # Check for required attributes
                required_attrs = ['space', 'space_name']
                missing_attrs = []
                
                for attr in required_attrs:
                    if not hasattr(space_data, attr):
                        missing_attrs.append(attr)
                
                if missing_attrs:
                    return {
                        "valid": False,
                        "message": f"Missing required attributes: {missing_attrs}",
                        "data_type": type(space_data).__name__
                    }
            else:
                return {
                    "valid": False,
                    "message": f"Unexpected data type: {type(space_data)}",
                    "data_type": type(space_data).__name__
                }
            
            return {
                "valid": True,
                "message": "Space data structure is valid",
                "data_type": type(space_data).__name__,
                "space_id": expected_space_id
            }
            
        except Exception as e:
            return {
                "valid": False,
                "message": f"Exception during validation: {e}",
                "error": str(e)
            }
