#!/usr/bin/env python3
"""
Spaces Endpoint Test Script for Fuseki+PostgreSQL Backend

Tests space management operations (create, list, get, update, delete, filter) using the
Fuseki+PostgreSQL hybrid backend without running the full REST service.

This script validates:
- Space creation with dual-write to both Fuseki datasets and PostgreSQL metadata tables
- Space listing and filtering operations
- Space metadata management and updates
- Space deletion with cleanup of both storage layers
- Dual-write consistency validation between Fuseki and PostgreSQL
- Error handling and edge cases

Test Coverage:
- Space lifecycle management (CRUD operations)
- Space metadata operations via PostgreSQL admin tables
- Fuseki dataset creation and management
- Dual-write consistency validation
- Space access control and filtering
- Performance comparison between storage layers
"""

import sys
import os
import json
import logging
import uuid
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

# Add the project root to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import the base tester class
from test_fuseki_postgresql_endpoint_utils import FusekiPostgreSQLEndpointTester, run_hybrid_test_suite

# VitalGraph imports
from vitalgraph.endpoint.spaces_endpoint import SpacesEndpoint
from vitalgraph.model.spaces_model import Space, SpacesListResponse, SpaceCreateResponse, SpaceUpdateResponse, SpaceDeleteResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import modular test cases
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "test_script_kg_impl"))
from test_script_kg_impl.spaces.case_space_create import SpaceCreateTester
from test_script_kg_impl.spaces.case_space_list import SpaceListTester
from test_script_kg_impl.spaces.case_space_get import SpaceGetTester
from test_script_kg_impl.spaces.case_space_update import SpaceUpdateTester
from test_script_kg_impl.spaces.case_space_delete import SpaceDeleteTester


class SpacesEndpointFusekiPostgreSQLTester(FusekiPostgreSQLEndpointTester):
    """Test Spaces endpoint operations with Fuseki+PostgreSQL hybrid backend using modular test cases."""
    
    def __init__(self):
        super().__init__()
        self.spaces_endpoint = None
        self.test_spaces = []
        self.created_space_ids = []
        self.test_cases = {}
    
    async def setup_hybrid_backend(self) -> bool:
        """Setup hybrid backend, spaces endpoint, and modular test cases."""
        success = await super().setup_hybrid_backend()
        if not success:
            return False
        
        try:
            # Create mock auth dependency for testing
            def mock_auth_dependency():
                return {"username": "test_user", "user_id": "test_user_123"}
            
            # Initialize spaces endpoint with space manager (like KG endpoint tests)
            from vitalgraph.endpoint.spaces_endpoint import SpacesEndpoint
            from vitalgraph.api.vitalgraph_api import VitalGraphAPI
            
            # Create VitalGraphAPI instance with hybrid backend
            api = VitalGraphAPI(
                space_manager=self.space_manager,
                auth_handler=mock_auth_dependency,
                db_impl=self.hybrid_backend
            )
            
            self.spaces_endpoint = SpacesEndpoint(
                api=api,
                auth_dependency=mock_auth_dependency
            )
            
            # Initialize modular test cases
            self.test_cases = {
                'create': SpaceCreateTester(self.spaces_endpoint, self.hybrid_backend),
                'list': SpaceListTester(self.spaces_endpoint),
                'get': SpaceGetTester(self.spaces_endpoint),
                'update': SpaceUpdateTester(self.spaces_endpoint, self.hybrid_backend),
                'delete': SpaceDeleteTester(self.spaces_endpoint, self.hybrid_backend)
            }
            
            logger.info("✅ Spaces endpoint and modular test cases initialized")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to setup spaces endpoint: {e}")
            return False
    
    async def test_space_creation(self):
        """Test space creation using modular test case."""
        result = await self.test_cases['create'].test_space_creation()
        
        # Track created space for cleanup
        if result["success"] and result.get("space_id"):
            self.created_space_ids.append(result["space_id"])
        
        # Log result in the expected format
        self.log_test_result(
            result["test_name"],
            result["success"],
            result["message"],
            result.get("details", {})
        )
    
    async def test_space_listing(self):
        """Test space listing using modular test case."""
        result = await self.test_cases['list'].test_space_listing(self.created_space_ids)
        
        # Log result in the expected format
        self.log_test_result(
            result["test_name"],
            result["success"],
            result["message"],
            result.get("details", {})
        )
    
    async def test_space_retrieval(self):
        """Test space retrieval using modular test case."""
        if not self.created_space_ids:
            self.log_test_result("Space Retrieval by ID", False, "No spaces available for retrieval test")
            return
        
        result = await self.test_cases['get'].test_space_retrieval(self.created_space_ids[0])
        
        # Log result in the expected format
        self.log_test_result(
            result["test_name"],
            result["success"],
            result["message"],
            result.get("details", {})
        )
    
    async def test_space_update(self):
        """Test space update using modular test case."""
        if not self.created_space_ids:
            self.log_test_result("Space Update Operations", False, "No spaces available for update test")
            return
        
        update_data = {
            "space_name": "Updated Test Space",
            "space_description": "Updated description for testing space update operations"
        }
        
        result = await self.test_cases['update'].test_space_update(self.created_space_ids[0], update_data)
        
        # Log result in the expected format
        self.log_test_result(
            result["test_name"],
            result["success"],
            result["message"],
            result.get("details", {})
        )
    
    async def test_space_filtering(self):
        """Test space filtering using modular test case."""
        result = await self.test_cases['list'].test_space_filtering("Filterable")
        
        # Track created space for cleanup if one was created
        if result["success"] and result.get("details", {}).get("filter_space_id"):
            filter_space_id = result["details"]["filter_space_id"]
            if filter_space_id not in self.created_space_ids:
                self.created_space_ids.append(filter_space_id)
        
        # Log result in the expected format
        self.log_test_result(
            result["test_name"],
            result["success"],
            result["message"],
            result.get("details", {})
        )
    
    async def test_space_deletion(self):
        """Test space deletion using modular test case."""
        # Use an existing created space or create one if none exist
        if not self.created_space_ids:
            await self.test_space_creation()
        
        if not self.created_space_ids:
            self.log_test_result("Space Deletion Operations", False, "No spaces available for deletion test")
            return
        
        # Use the first created space for deletion test
        space_to_delete = self.created_space_ids[0]
        
        result = await self.test_cases['delete'].test_space_deletion(space_to_delete)
        
        # Remove the deleted space from our tracking list if deletion was successful
        if result["success"] and space_to_delete in self.created_space_ids:
            self.created_space_ids.remove(space_to_delete)
        
        # Log result in the expected format
        self.log_test_result(
            result["test_name"],
            result["success"],
            result["message"],
            result.get("details", {})
        )
    
    async def test_dual_write_consistency(self):
        """Test dual-write consistency using modular test cases."""
        test_name = "Dual-Write Consistency Validation"
        
        try:
            logger.info("🧪 Testing dual-write consistency between Fuseki and PostgreSQL")
            
            # Create multiple spaces using modular test case and validate consistency
            consistency_results = []
            initial_space_count = len(self.created_space_ids)
            
            for i in range(3):
                # Use modular test case to create space
                create_result = await self.test_cases['create'].test_space_creation()
                
                if create_result["success"] and create_result.get("space_id"):
                    space_id = create_result["space_id"]
                    self.created_space_ids.append(space_id)
                    
                    # Validate dual-write consistency using existing validation method
                    validation_result = await self._validate_space_dual_storage(space_id)
                    consistency_results.append({
                        "space_id": space_id,
                        "consistent": validation_result["fuseki_exists"] and validation_result["postgresql_exists"],
                        "details": validation_result
                    })
            
            # Analyze consistency results
            consistent_count = sum(1 for result in consistency_results if result["consistent"])
            total_count = len(consistency_results)
            
            if consistent_count == total_count:
                self.log_test_result(
                    test_name, 
                    True, 
                    f"All {total_count} spaces show dual-write consistency",
                    {"consistent_spaces": consistent_count, "total_spaces": total_count, "results": consistency_results}
                )
            else:
                self.log_test_result(
                    test_name, 
                    False, 
                    f"Dual-write consistency failed: {consistent_count}/{total_count} spaces consistent",
                    {"consistent_spaces": consistent_count, "total_spaces": total_count, "results": consistency_results}
                )
            
        except Exception as e:
            self.log_test_result(test_name, False, f"Exception during dual-write consistency test: {e}")
    
    async def _validate_space_dual_storage(self, space_id: str) -> Dict[str, Any]:
        """Validate that space exists in both Fuseki and PostgreSQL storage."""
        try:
            # Check Fuseki dataset existence
            fuseki_exists = False
            try:
                fuseki_exists = await self.hybrid_backend.fuseki_manager.dataset_exists(space_id)
            except Exception as e:
                logger.warning(f"Error checking Fuseki dataset: {e}")
            
            # Check PostgreSQL space metadata table
            postgresql_exists = False
            try:
                # Check if space metadata exists in PostgreSQL space table
                pg_query = "SELECT COUNT(*) as count FROM space WHERE space_id = $1"
                pg_results = await self.hybrid_backend.postgresql_impl.execute_query(pg_query, [space_id])
                postgresql_exists = pg_results and len(pg_results) > 0 and pg_results[0].get('count', 0) > 0
            except Exception as e:
                logger.warning(f"Error checking PostgreSQL space table: {e}")
                # Fallback: check if backup tables exist
                try:
                    table_name = f"{space_id}_rdf_quad"
                    pg_query = "SELECT COUNT(*) as count FROM information_schema.tables WHERE table_name = $1"
                    pg_results = await self.hybrid_backend.postgresql_impl.execute_query(pg_query, [table_name])
                    postgresql_exists = pg_results and len(pg_results) > 0 and pg_results[0].get('count', 0) > 0
                except Exception as e2:
                    logger.warning(f"Error checking PostgreSQL backup tables: {e2}")
            
            return {
                "space_id": space_id,
                "fuseki_exists": fuseki_exists,
                "postgresql_exists": postgresql_exists,
                "consistent": fuseki_exists and postgresql_exists,  # Both must exist for consistency
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Exception validating space dual storage: {e}")
            return {
                "space_id": space_id,
                "fuseki_exists": False,
                "postgresql_exists": False,
                "consistent": False,
                "error": str(e)
            }
    
    async def test_spaces_modular(self):
        """Optional test method using modular test cases if available."""
        if not MODULAR_TESTS_AVAILABLE:
            logger.info("ℹ️ Skipping modular tests - not available")
            return
        
        test_name = "Modular Spaces Tests"
        
        try:
            logger.info("🧪 Running modular spaces endpoint tests")
            
            # Initialize modular test cases
            test_cases = {
                'create': SpaceCreateTester(self.spaces_endpoint, self.hybrid_backend),
                'list': SpaceListTester(self.spaces_endpoint),
                'get': SpaceGetTester(self.spaces_endpoint),
                'update': SpaceUpdateTester(self.spaces_endpoint, self.hybrid_backend),
                'delete': SpaceDeleteTester(self.spaces_endpoint, self.hybrid_backend)
            }
            
            modular_results = []
            
            # Test 1: Modular Space Creation
            create_result = await test_cases['create'].test_space_creation()
            modular_results.append(create_result)
            if create_result["success"] and create_result.get("space_id"):
                self.created_space_ids.append(create_result["space_id"])
            
            # Test 2: Modular Space Listing
            list_result = await test_cases['list'].test_space_listing(self.created_space_ids)
            modular_results.append(list_result)
            
            # Test 3: Modular Space Retrieval (if we have spaces)
            if self.created_space_ids:
                get_result = await test_cases['get'].test_space_retrieval(self.created_space_ids[0])
                modular_results.append(get_result)
            
            # Test 4: Modular Space Update (if we have spaces)
            if self.created_space_ids:
                update_data = {"space_name": "Modular Updated Space", "space_description": "Updated via modular test"}
                update_result = await test_cases['update'].test_space_update(self.created_space_ids[0], update_data)
                modular_results.append(update_result)
            
            # Test 5: Modular Space Deletion (clean up)
            for space_id in self.created_space_ids.copy():
                delete_result = await test_cases['delete'].test_space_deletion(space_id)
                modular_results.append(delete_result)
                if delete_result["success"]:
                    self.created_space_ids.remove(space_id)
            
            # Analyze modular test results
            passed_modular = sum(1 for result in modular_results if result["success"])
            total_modular = len(modular_results)
            
            if passed_modular == total_modular:
                self.log_test_result(
                    test_name, 
                    True, 
                    f"All {total_modular} modular tests passed",
                    {"passed": passed_modular, "total": total_modular, "results": modular_results}
                )
            else:
                self.log_test_result(
                    test_name, 
                    False, 
                    f"Modular tests failed: {passed_modular}/{total_modular} passed",
                    {"passed": passed_modular, "total": total_modular, "results": modular_results}
                )
            
        except Exception as e:
            self.log_test_result(test_name, False, f"Exception during modular tests: {e}")

    async def cleanup_resources(self):
        """Clean up test spaces and resources."""
        try:
            logger.info("🧹 Cleaning up spaces endpoint test resources")
            
            # Clean up created spaces
            if self.created_space_ids:
                current_user = {"username": "test_user", "user_id": "test_user_123"}
                
                for space_id in self.created_space_ids:
                    try:
                        await self.spaces_endpoint.api.delete_space(space_id, current_user)
                        logger.info(f"🧹 Cleaned up test space: {space_id}")
                    except Exception as e:
                        logger.warning(f"⚠️ Error cleaning up space {space_id}: {e}")
            
            # Call parent cleanup
            await super().cleanup_resources()
            
        except Exception as e:
            logger.error(f"❌ Error during spaces endpoint cleanup: {e}")


# Now using real VitalGraphAPI implementation instead of mock


async def main():
    """Main test execution function."""
    logger.info("🚀 Starting Spaces Endpoint Fuseki+PostgreSQL Tests")
    
    # Standard test methods (always run)
    test_methods = [
        "test_space_creation",
        "test_space_listing", 
        "test_space_retrieval",
        "test_space_update",
        "test_space_filtering",
        "test_dual_write_consistency",
        "test_space_deletion"
    ]
    
    # Standard test methods only
    
    success = await run_hybrid_test_suite(SpacesEndpointFusekiPostgreSQLTester, test_methods)
    
    if success:
        logger.info("🎉 All Spaces endpoint tests completed successfully!")
        return 0
    else:
        logger.error("💥 Some Spaces endpoint tests failed!")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
