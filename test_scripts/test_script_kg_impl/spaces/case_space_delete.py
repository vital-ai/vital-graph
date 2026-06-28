#!/usr/bin/env python3
"""
Space Deletion Test Module

Modular test implementation for space deletion operations.
Used by the main Spaces endpoint test orchestrator.

Focuses on:
- Space deletion with dual-write cleanup
- Fuseki dataset deletion
- PostgreSQL metadata cleanup
- Response validation
- Error handling for invalid deletions
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

# Import models
from vitalgraph.model.spaces_model import SpaceDeleteResponse

logger = logging.getLogger(__name__)


class SpaceDeleteTester:
    """
    Modular test implementation for space deletion operations.
    
    Handles:
    - Space deletion with dual-write cleanup
    - Validation of complete cleanup
    - Response format verification
    - Error handling for invalid operations
    """
    
    def __init__(self, endpoint, space_manager):
        """
        Initialize the space deletion tester.
        
        Args:
            endpoint: SpacesEndpoint instance
            space_manager: SpaceManager instance for validation
        """
        self.endpoint = endpoint
        self.space_manager = space_manager
        self.logger = logging.getLogger(f"{__name__}.SpaceDeleteTester")
    
    async def test_space_deletion(self, space_id: str) -> Dict[str, Any]:
        """
        Test space deletion operations.
        
        Args:
            space_id: Space ID to delete
            
        Returns:
            Dict containing test results and metadata
        """
        test_name = "Space Deletion Operations"
        
        try:
            self.logger.info(f"🧪 Testing space deletion for ID: {space_id}")
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            # Verify space exists in both storage layers before deletion
            pre_deletion_validation = await self._validate_space_dual_storage(space_id)
            
            if not (pre_deletion_validation["fuseki_exists"] and pre_deletion_validation["postgresql_exists"]):
                return {
                    "test_name": test_name,
                    "success": False,
                    "message": f"Space not properly created in dual storage before deletion: {space_id}",
                    "space_id": space_id,
                    "pre_deletion_validation": pre_deletion_validation
                }
            
            # Delete the space
            deletion_result = await self.endpoint.delete_space(space_id, current_user)
            
            if not deletion_result:
                return {
                    "test_name": test_name,
                    "success": False,
                    "message": f"Space deletion returned None for: {space_id}",
                    "space_id": space_id
                }
            
            # Verify space is removed from both storage layers
            post_deletion_validation = await self._validate_space_dual_storage(space_id)
            
            if not post_deletion_validation["fuseki_exists"] and not post_deletion_validation["postgresql_exists"]:
                return {
                    "test_name": test_name,
                    "success": True,
                    "message": f"Space successfully deleted from dual storage: {space_id}",
                    "space_id": space_id,
                    "pre_deletion": pre_deletion_validation,
                    "post_deletion": post_deletion_validation
                }
            else:
                return {
                    "test_name": test_name,
                    "success": False,
                    "message": f"Space deletion incomplete - still exists in storage: {space_id}",
                    "space_id": space_id,
                    "pre_deletion": pre_deletion_validation,
                    "post_deletion": post_deletion_validation
                }
            
        except Exception as e:
            self.logger.error(f"Exception during space deletion: {e}")
            return {
                "test_name": test_name,
                "success": False,
                "message": f"Exception during space deletion: {e}",
                "space_id": space_id,
                "error": str(e)
            }
    
    async def test_invalid_space_deletion(self, invalid_space_id: str = "nonexistent_space_123") -> Dict[str, Any]:
        """
        Test deletion of a non-existent space to validate error handling.
        
        Args:
            invalid_space_id: Non-existent space ID to test
            
        Returns:
            Dict containing test results and metadata
        """
        test_name = "Invalid Space Deletion"
        
        try:
            self.logger.info(f"🧪 Testing deletion of non-existent space: {invalid_space_id}")
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            try:
                deletion_result = await self.endpoint.delete_space(invalid_space_id, current_user)
                
                # If we get here without exception, the deletion succeeded (unexpected)
                if deletion_result:
                    return {
                        "test_name": test_name,
                        "success": False,
                        "message": f"Unexpectedly succeeded deleting non-existent space: {invalid_space_id}",
                        "space_id": invalid_space_id,
                        "result": deletion_result
                    }
                else:
                    # Deletion failed (expected behavior)
                    return {
                        "test_name": test_name,
                        "success": True,
                        "message": f"Correctly failed to delete non-existent space: {invalid_space_id}",
                        "space_id": invalid_space_id
                    }
                    
            except Exception as api_error:
                # Exception raised for non-existent space deletion (expected behavior)
                self.logger.info(f"Expected exception for non-existent space deletion: {api_error}")
                return {
                    "test_name": test_name,
                    "success": True,
                    "message": f"Correctly raised exception for non-existent space deletion: {invalid_space_id}",
                    "space_id": invalid_space_id,
                    "expected_error": str(api_error)
                }
            
        except Exception as e:
            self.logger.error(f"Exception during invalid space deletion: {e}")
            return {
                "test_name": test_name,
                "success": False,
                "message": f"Exception during invalid space deletion: {e}",
                "space_id": invalid_space_id,
                "error": str(e)
            }
    
    async def _validate_space_dual_storage(self, space_id: str) -> Dict[str, Any]:
        """
        Validate that space exists in both Fuseki and PostgreSQL storage.
        
        Args:
            space_id: Space ID to validate
            
        Returns:
            Dict with validation results
        """
        try:
            # Check Fuseki dataset existence
            fuseki_exists = False
            try:
                fuseki_exists = await self.space_manager.fuseki_manager.dataset_exists(space_id)
            except Exception as e:
                self.logger.warning(f"Error checking Fuseki dataset: {e}")
            
            # Check PostgreSQL space metadata table
            postgresql_exists = False
            try:
                # Check if space metadata exists in PostgreSQL space table
                pg_query = "SELECT COUNT(*) as count FROM space WHERE space_id = $1"
                pg_results = await self.space_manager.postgresql_impl.execute_query(pg_query, [space_id])
                postgresql_exists = pg_results and len(pg_results) > 0 and pg_results[0].get('count', 0) > 0
            except Exception as e:
                self.logger.warning(f"Error checking PostgreSQL space table: {e}")
                # Fallback: check if backup tables exist
                try:
                    table_name = f"{space_id}_rdf_quad"
                    pg_query = "SELECT COUNT(*) as count FROM information_schema.tables WHERE table_name = $1"
                    pg_results = await self.space_manager.postgresql_impl.execute_query(pg_query, [table_name])
                    postgresql_exists = pg_results and len(pg_results) > 0 and pg_results[0].get('count', 0) > 0
                except Exception as e2:
                    self.logger.warning(f"Error checking PostgreSQL backup tables: {e2}")
            
            return {
                "space_id": space_id,
                "fuseki_exists": fuseki_exists,
                "postgresql_exists": postgresql_exists,
                "consistent": fuseki_exists and postgresql_exists,  # Both must exist for consistency
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Exception validating space dual storage: {e}")
            return {
                "space_id": space_id,
                "fuseki_exists": False,
                "postgresql_exists": False,
                "consistent": False,
                "error": str(e)
            }
    
    async def _validate_space_exists(self, space_id: str) -> Dict[str, Any]:
        """
        Validate that space exists in both Fuseki and PostgreSQL storage.
        
        Args:
            space_id: Space ID to validate
            
        Returns:
            Dict with validation results
        """
        try:
            # Check if space exists via space manager
            space_impl = await self.space_manager.get_space_impl(space_id)
            exists = space_impl is not None
            
            return {
                "exists": exists,
                "space_id": space_id,
                "message": f"Space {'exists' if exists else 'does not exist'} in storage"
            }
            
        except Exception as e:
            self.logger.error(f"Error validating space existence for {space_id}: {e}")
            return {
                "exists": False,
                "space_id": space_id,
                "message": f"Error checking space existence: {e}",
                "error": str(e)
            }
    
    async def _validate_space_deleted(self, space_id: str) -> Dict[str, Any]:
        """
        Validate that space has been completely deleted from both storage layers.
        
        Args:
            space_id: Space ID to validate
            
        Returns:
            Dict with validation results
        """
        try:
            # Try to retrieve the space - should fail or return None
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            try:
                space_data = await self.endpoint.get_space(space_id, current_user)
                if space_data is None:
                    endpoint_deleted = True
                    endpoint_message = "Space not found via endpoint"
                else:
                    endpoint_deleted = False
                    endpoint_message = "Space still accessible via endpoint"
            except Exception:
                endpoint_deleted = True
                endpoint_message = "Space correctly raises exception when accessed"
            
            # Check if space exists via space manager
            try:
                space_impl = await self.space_manager.get_space_impl(space_id)
                manager_deleted = space_impl is None
                manager_message = "Space not found in space manager" if manager_deleted else "Space still exists in space manager"
            except Exception:
                manager_deleted = True
                manager_message = "Space correctly raises exception in space manager"
            
            deleted = endpoint_deleted and manager_deleted
            
            return {
                "deleted": deleted,
                "space_id": space_id,
                "message": f"Space deletion {'successful' if deleted else 'incomplete'}",
                "endpoint_deleted": endpoint_deleted,
                "endpoint_message": endpoint_message,
                "manager_deleted": manager_deleted,
                "manager_message": manager_message
            }
            
        except Exception as e:
            self.logger.error(f"Error validating space deletion for {space_id}: {e}")
            return {
                "deleted": False,
                "space_id": space_id,
                "message": f"Error validating space deletion: {e}",
                "error": str(e)
            }
    
    def _validate_delete_response(self, response: Any, expected_space_id: str) -> Dict[str, Any]:
        """
        Validate the structure of the space delete response.
        
        Args:
            response: Delete response to validate
            expected_space_id: Expected space ID
            
        Returns:
            Dict with validation results
        """
        try:
            # Check if response has expected attributes
            if hasattr(response, 'message') and hasattr(response, 'deleted_uris'):
                # Pydantic model format
                if expected_space_id not in response.deleted_uris:
                    return {
                        "valid": False,
                        "message": f"Space ID {expected_space_id} not found in deleted_uris: {response.deleted_uris}",
                        "response_type": type(response).__name__
                    }
                
                return {
                    "valid": True,
                    "message": "Delete response structure is valid",
                    "response_type": type(response).__name__,
                    "deleted_uris": response.deleted_uris
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
                    "message": "Delete response structure is valid",
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
