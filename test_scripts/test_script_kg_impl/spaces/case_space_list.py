#!/usr/bin/env python3
"""
Space Listing Test Module

Modular test implementation for space listing operations.
Used by the main Spaces endpoint test orchestrator.

Focuses on:
- Space listing operations
- Filtering and pagination
- Response validation
- Data consistency checks
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

# Import models
from vitalgraph.model.spaces_model import Space, SpacesListResponse

logger = logging.getLogger(__name__)


class SpaceListTester:
    """Test case for space listing and filtering operations."""
    
    def __init__(self, spaces_endpoint):
        self.spaces_endpoint = spaces_endpoint
        self.logger = logging.getLogger(f"{__name__}.SpaceListTester")
    
    async def test_space_listing(self, created_space_ids: List[str] = None) -> Dict[str, Any]:
        """
        Test space listing operations using the working logic from the original test script.
        
        Args:
            created_space_ids: List of space IDs that should be found in the listing
            
        Returns:
            Dict with test results including success status and details
        """
        test_name = "Space Listing Operations"
        
        try:
            self.logger.info("🧪 Testing space listing operations")
            
            # Test listing all spaces using endpoint method
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            # Call the endpoint method directly
            response = await self.spaces_endpoint.list_spaces(current_user)
            spaces_list = response.spaces if hasattr(response, 'spaces') else []
            
            if not isinstance(spaces_list, list):
                return {
                    "test_name": test_name,
                    "success": False,
                    "message": "Space listing did not return a list",
                    "spaces_count": 0
                }
            
            # If we have created spaces, validate they are in the list
            if created_space_ids:
                found_spaces = 0
                for space_id in created_space_ids:
                    for space in spaces_list:
                        # Handle both dict and Pydantic model formats
                        space_field = space.space if hasattr(space, 'space') else space.get('space')
                        if space_field == space_id:
                            found_spaces += 1
                            break
                
                success = found_spaces == len(created_space_ids)
                message = f"Found {found_spaces}/{len(created_space_ids)} created spaces in listing"
                
                return {
                    "test_name": test_name,
                    "success": success,
                    "message": message,
                    "total_spaces": len(spaces_list),
                    "found_spaces": found_spaces,
                    "expected_spaces": len(created_space_ids)
                }
            else:
                # No specific spaces to validate, just check that listing works
                return {
                    "test_name": test_name,
                    "success": True,
                    "message": f"Space listing successful, found {len(spaces_list)} spaces",
                    "total_spaces": len(spaces_list)
                }
            
        except Exception as e:
            self.logger.error(f"❌ Exception during space listing test: {e}")
            return {
                "test_name": test_name,
                "success": False,
                "message": f"Exception during space listing: {e}",
                "error": str(e)
            }
    
    async def test_space_filtering(self, filter_term: str = "Filterable") -> Dict[str, Any]:
        """
        Test space filtering by name using the working logic from the original test script.
        
        Args:
            filter_term: Term to filter spaces by
            
        Returns:
            Dict with test results including success status and details
        """
        test_name = "Space Filtering by Name"
        
        try:
            self.logger.info(f"🧪 Testing space filtering with term: {filter_term}")
            
            # Create a space with a specific name pattern for filtering
            filter_test_space = Space(
                space=f"filterable_space_{uuid.uuid4().hex[:8]}",
                space_name="Filterable Test Space",
                space_description="Space created specifically for filter testing",
                tenant="filter_test_tenant"
            )
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            # Create the filterable space
            created_space = await self.spaces_endpoint.api.add_space(filter_test_space.model_dump(), current_user)
            filter_space_id = None
            if created_space:
                filter_space_id = created_space.get('space', filter_test_space.space)
            
            # Test filtering with partial name match
            filtered_spaces = await self.spaces_endpoint.api.filter_spaces_by_name(filter_term, current_user)
            
            if not isinstance(filtered_spaces, list):
                return {
                    "test_name": test_name,
                    "success": False,
                    "message": "Space filtering did not return a list",
                    "filter_term": filter_term
                }
            
            # Check if our filterable space is in the results
            found_filterable = False
            for space in filtered_spaces:
                if filter_term.lower() in space.get('space_name', '').lower():
                    found_filterable = True
                    break
            
            # Clean up the test space
            if filter_space_id:
                try:
                    await self.spaces_endpoint.api.delete_space(filter_space_id, current_user)
                except Exception as cleanup_error:
                    self.logger.warning(f"Failed to cleanup filter test space: {cleanup_error}")
            
            if found_filterable:
                return {
                    "test_name": test_name,
                    "success": True,
                    "message": f"Space filtering successful with term '{filter_term}'",
                    "filter_term": filter_term,
                    "results_count": len(filtered_spaces)
                }
            else:
                return {
                    "test_name": test_name,
                    "success": False,
                    "message": f"Space filtering failed to find expected results with term '{filter_term}'",
                    "filter_term": filter_term,
                    "results": filtered_spaces
                }
            
        except Exception as e:
            self.logger.error(f"❌ Exception during space filtering test: {e}")
            return {
                "test_name": test_name,
                "success": False,
                "message": f"Exception during space filtering: {e}",
                "filter_term": filter_term,
                "error": str(e)
            }
    
    def _validate_response_structure(self, response) -> Dict[str, Any]:
        """
        Validate the structure of the spaces list response.
        
        Args:
            response: Response object to validate
            
        Returns:
            Dict with validation results
        """
        try:
            # Check if response has expected attributes
            required_attrs = ['spaces', 'total_count', 'page_size', 'offset']
            missing_attrs = []
            
            for attr in required_attrs:
                if not hasattr(response, attr):
                    missing_attrs.append(attr)
            
            if missing_attrs:
                return {
                    "valid": False,
                    "message": f"Missing required attributes: {missing_attrs}",
                    "response_type": type(response).__name__
                }
            
            # Validate spaces list structure
            spaces = response.spaces
            if not isinstance(spaces, list):
                return {
                    "valid": False,
                    "message": f"Spaces field is not a list: {type(spaces)}",
                    "response_type": type(response).__name__
                }
            
            # Validate individual space objects
            for i, space in enumerate(spaces):
                space_attrs = ['space', 'space_name'] if hasattr(space, 'space') else ['space', 'space_name']
                for attr in space_attrs:
                    if hasattr(space, attr):
                        continue
                    elif isinstance(space, dict) and attr in space:
                        continue
                    else:
                        return {
                            "valid": False,
                            "message": f"Space {i} missing attribute: {attr}",
                            "space_type": type(space).__name__
                        }
            
            return {
                "valid": True,
                "message": "Response structure is valid",
                "response_type": type(response).__name__,
                "spaces_count": len(spaces)
            }
            
        except Exception as e:
            return {
                "valid": False,
                "message": f"Exception during validation: {e}",
                "error": str(e)
            }
