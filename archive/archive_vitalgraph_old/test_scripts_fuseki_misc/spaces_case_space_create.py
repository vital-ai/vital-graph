#!/usr/bin/env python3
"""
Space Creation Test Module

Modular test implementation for space creation operations.
Used by the main Spaces endpoint test orchestrator.

Focuses on:
- Space creation with dual-write validation
- Fuseki dataset creation
- PostgreSQL metadata table creation
- Dual-write consistency validation
- Error handling and validation
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

# Import models
from vitalgraph.model.spaces_model import Space, SpaceCreateResponse

logger = logging.getLogger(__name__)


class SpaceCreateTester:
    """Test case for space creation with dual-write validation."""
    
    def __init__(self, spaces_endpoint, hybrid_backend):
        self.spaces_endpoint = spaces_endpoint
        self.hybrid_backend = hybrid_backend
        self.logger = logging.getLogger(f"{__name__}.SpaceCreateTester")
        self.created_space_ids = []
    
    async def test_space_creation(self) -> Dict[str, Any]:
        """
        Test space creation with dual-write validation.
        
        Returns:
            Dict with test results including success status and details
        """
        test_name = "Space Creation with Dual-Write"
        
        try:
            self.logger.info("🧪 Testing space creation with Fuseki+PostgreSQL dual-write")
            
            # Create test space data
            test_space = Space(
                space=f"test_space_{uuid.uuid4().hex[:8]}",
                space_name="Test Space for Hybrid Backend",
                space_description="Test space for validating Fuseki+PostgreSQL dual-write operations",
                tenant="test_tenant"
            )
            
            # Test space creation via endpoint
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            # Call the endpoint method directly
            response = await self.spaces_endpoint.add_space(test_space, current_user)
            
            if not response:
                return {
                    "test_name": test_name,
                    "success": False,
                    "message": "Space creation returned None",
                    "space_id": None
                }
            
            # Extract space_id from response (endpoint function returns Pydantic model)
            space_id = response.created_uris[0] if response.created_uris else test_space.space
            self.created_space_ids.append(space_id)
            
            # Validate space exists in both Fuseki and PostgreSQL
            validation_result = await self._validate_space_dual_storage(space_id)
            
            if validation_result["fuseki_exists"] and validation_result["postgresql_exists"]:
                return {
                    "test_name": test_name,
                    "success": True,
                    "message": f"Space created successfully with dual-write: {space_id}",
                    "space_id": space_id,
                    "validation_result": validation_result
                }
            else:
                return {
                    "test_name": test_name,
                    "success": False,
                    "message": f"Space dual-write validation failed: {space_id}",
                    "space_id": space_id,
                    "validation_result": validation_result,
                    "error": "Dual-write validation failed"
                }
            
        except Exception as e:
            self.logger.error(f"❌ Exception during space creation test: {e}")
            return {
                "test_name": test_name,
                "success": False,
                "message": f"Exception during space creation: {e}",
                "space_id": None,
                "error": str(e)
            }
    
    async def _validate_space_dual_storage(self, space_id: str) -> Dict[str, Any]:
        """
        Validate that space exists in both Fuseki and PostgreSQL storage.
        Uses the working validation logic from the original test script.
        
        Args:
            space_id: Space ID to validate
            
        Returns:
            Dict with validation results
        """
        try:
            # Check Fuseki dataset existence
            fuseki_exists = False
            try:
                fuseki_exists = await self.hybrid_backend.fuseki_manager.dataset_exists(space_id)
            except Exception as e:
                self.logger.warning(f"Error checking Fuseki dataset: {e}")
            
            # Check PostgreSQL space metadata table
            postgresql_exists = False
            try:
                # Check if space metadata exists in PostgreSQL space table
                pg_query = "SELECT COUNT(*) as count FROM space WHERE space_id = $1"
                pg_results = await self.hybrid_backend.postgresql_impl.execute_query(pg_query, [space_id])
                postgresql_exists = pg_results and len(pg_results) > 0 and pg_results[0].get('count', 0) > 0
            except Exception as e:
                self.logger.warning(f"Error checking PostgreSQL space table: {e}")
                # Fallback: check if backup tables exist
                try:
                    table_name = f"{space_id}_rdf_quad"
                    pg_query = "SELECT COUNT(*) as count FROM information_schema.tables WHERE table_name = $1"
                    pg_results = await self.hybrid_backend.postgresql_impl.execute_query(pg_query, [table_name])
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
            self.logger.error(f"❌ Exception validating space dual storage: {e}")
            return {
                "space_id": space_id,
                "fuseki_exists": False,
                "postgresql_exists": False,
                "consistent": False,
                "error": str(e)
            }
    
    def get_created_space_ids(self) -> List[str]:
        """Get list of space IDs created during testing for cleanup."""
        return self.created_space_ids.copy()
    
    async def cleanup_created_spaces(self) -> Dict[str, Any]:
        """
        Clean up all spaces created during testing.
        
        Returns:
            Dict with cleanup results
        """
        cleanup_results = []
        
        for space_id in self.created_space_ids:
            try:
                # Delete space using space manager
                result = await self.space_manager.delete_space(space_id)
                cleanup_results.append({
                    "space_id": space_id,
                    "success": result,
                    "message": "Space deleted successfully" if result else "Failed to delete space"
                })
            except Exception as e:
                cleanup_results.append({
                    "space_id": space_id,
                    "success": False,
                    "message": f"Exception during cleanup: {e}"
                })
        
        # Clear the list after cleanup
        self.created_space_ids.clear()
        
        return {
            "cleanup_results": cleanup_results,
            "total_cleaned": len(cleanup_results)
        }
