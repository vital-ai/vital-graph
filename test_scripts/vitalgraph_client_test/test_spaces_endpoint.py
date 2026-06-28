#!/usr/bin/env python3
"""
Comprehensive Spaces Endpoint Test

Tests all space operations including:
- Create space
- Get space
- Get space info
- List spaces
- Update space
- Delete space
- Error response handling
- Type annotation validation
"""

import sys
import logging
import asyncio
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.spaces_model import Space
from vitalgraph.client.response.client_response import (
    SpaceResponse,
    SpaceInfoResponse,
    SpacesListResponse,
    SpaceCreateResponse,
    SpaceUpdateResponse,
    SpaceDeleteResponse
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


class SpacesEndpointTester:
    """Test suite for Spaces endpoint operations."""
    
    def __init__(self):
        """Initialize the tester."""
        self.client = None
        self.test_space_id = "test_spaces_endpoint_space"
        self.results = {
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": []
        }
    
    async def setup(self) -> bool:
        """Set up the test client."""
        logger.info("\n" + "=" * 80)
        logger.info("SETUP: Initializing VitalGraph Client")
        logger.info("=" * 80)
        
        try:
            self.client = VitalGraphClient()
            await self.client.open()
            logger.info("✅ Client initialized and opened successfully")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to initialize client: {e}")
            return False
    
    async def cleanup_existing_space(self) -> None:
        """Clean up any existing test space."""
        logger.info("\n" + "=" * 80)
        logger.info("CLEANUP: Removing existing test space if present")
        logger.info("=" * 80)
        
        try:
            # Try to delete the test space
            delete_response = await self.client.spaces.delete_space(self.test_space_id)
            if delete_response.is_success:
                logger.info(f"✅ Deleted existing test space: {self.test_space_id}")
            else:
                logger.info(f"ℹ️  No existing test space to delete")
        except Exception as e:
            logger.info(f"ℹ️  No existing test space (error: {e})")
    
    async def test_create_space(self) -> bool:
        """Test creating a new space."""
        logger.info("\n" + "=" * 80)
        logger.info("TEST 1: Create Space")
        logger.info("=" * 80)
        
        self.results["tests_run"] += 1
        
        try:
            # Create space data
            space_data = Space(
                space=self.test_space_id,
                space_name="Spaces Endpoint Test Space",
                space_description="Test space for comprehensive spaces endpoint testing",
                tenant="test_tenant"
            )
            
            # Create the space
            logger.info(f"Creating space: {self.test_space_id}")
            response = await self.client.spaces.create_space(space_data)
            
            # Check response type
            if not isinstance(response, SpaceCreateResponse):
                logger.error(f"❌ Wrong response type: {type(response)}")
                self.results["tests_failed"] += 1
                self.results["errors"].append("Create space returned wrong response type")
                return False
            
            # Check success
            if not response.is_success:
                logger.error(f"❌ Create failed: {response.error_message}")
                self.results["tests_failed"] += 1
                self.results["errors"].append(f"Create space failed: {response.error_message}")
                return False
            
            # Verify response properties
            logger.info(f"✅ Space created successfully")
            logger.info(f"   Space ID: {response.space.space if response.space else 'N/A'}")
            logger.info(f"   Created count: {response.created_count}")
            logger.info(f"   Response type: {type(response).__name__}")
            
            # Verify created_count
            if response.created_count != 1:
                logger.warning(f"⚠️  Expected created_count=1, got {response.created_count}")
            
            # Verify space object
            if response.space is None:
                logger.error(f"❌ Response.space is None")
                self.results["tests_failed"] += 1
                self.results["errors"].append("Create response missing space object")
                return False
            
            # Verify space type annotation works
            if not isinstance(response.space, Space):
                logger.error(f"❌ Space is not a Space instance: {type(response.space)}")
                self.results["tests_failed"] += 1
                self.results["errors"].append("Space type annotation failed")
                return False
            
            logger.info(f"✅ Space type annotation validated: {type(response.space).__name__}")
            
            self.results["tests_passed"] += 1
            return True
            
        except Exception as e:
            logger.error(f"❌ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            self.results["tests_failed"] += 1
            self.results["errors"].append(f"Create space exception: {str(e)}")
            return False
    
    async def test_get_space(self) -> bool:
        """Test getting a space by ID."""
        logger.info("\n" + "=" * 80)
        logger.info("TEST 2: Get Space")
        logger.info("=" * 80)
        
        self.results["tests_run"] += 1
        
        try:
            logger.info(f"Getting space: {self.test_space_id}")
            response = await self.client.spaces.get_space(self.test_space_id)
            
            # Check response type
            if not isinstance(response, SpaceResponse):
                logger.error(f"❌ Wrong response type: {type(response)}")
                self.results["tests_failed"] += 1
                self.results["errors"].append("Get space returned wrong response type")
                return False
            
            # Check success
            if not response.is_success:
                logger.error(f"❌ Get failed: {response.error_message}")
                self.results["tests_failed"] += 1
                self.results["errors"].append(f"Get space failed: {response.error_message}")
                return False
            
            # Verify space data
            logger.info(f"✅ Space retrieved successfully")
            logger.info(f"   Space ID: {response.space.space}")
            logger.info(f"   Space Name: {response.space.space_name}")
            logger.info(f"   Description: {response.space.space_description}")
            logger.info(f"   Response type: {type(response).__name__}")
            
            # Verify space type
            if not isinstance(response.space, Space):
                logger.error(f"❌ Space is not a Space instance: {type(response.space)}")
                self.results["tests_failed"] += 1
                self.results["errors"].append("Get space type annotation failed")
                return False
            
            logger.info(f"✅ Space type annotation validated: {type(response.space).__name__}")
            
            self.results["tests_passed"] += 1
            return True
            
        except Exception as e:
            logger.error(f"❌ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            self.results["tests_failed"] += 1
            self.results["errors"].append(f"Get space exception: {str(e)}")
            return False
    
    async def test_get_space_not_found(self) -> bool:
        """Test getting a non-existent space (error response)."""
        logger.info("\n" + "=" * 80)
        logger.info("TEST 3: Get Non-Existent Space (Error Response)")
        logger.info("=" * 80)
        
        self.results["tests_run"] += 1
        
        try:
            non_existent_id = "non_existent_space_12345"
            logger.info(f"Getting non-existent space: {non_existent_id}")
            response = await self.client.spaces.get_space(non_existent_id)
            
            # Check response type
            if not isinstance(response, SpaceResponse):
                logger.error(f"❌ Wrong response type: {type(response)}")
                self.results["tests_failed"] += 1
                self.results["errors"].append("Get non-existent space returned wrong response type")
                return False
            
            # Should NOT be successful
            if response.is_success:
                logger.error(f"❌ Expected failure, but got success")
                self.results["tests_failed"] += 1
                self.results["errors"].append("Get non-existent space should fail")
                return False
            
            # Verify error properties
            logger.info(f"✅ Correctly returned error response")
            logger.info(f"   is_success: {response.is_success}")
            logger.info(f"   is_error: {response.is_error}")
            logger.info(f"   error_code: {response.error_code}")
            logger.info(f"   error_message: {response.error_message}")
            logger.info(f"   space: {response.space}")
            
            # Verify error_code is set
            if response.error_code == 0:
                logger.error(f"❌ Error code should be non-zero")
                self.results["tests_failed"] += 1
                self.results["errors"].append("Error response has error_code=0")
                return False
            
            # Verify is_error property
            if not response.is_error:
                logger.error(f"❌ is_error should be True")
                self.results["tests_failed"] += 1
                self.results["errors"].append("Error response is_error is False")
                return False
            
            logger.info(f"✅ Error response properties validated")
            
            self.results["tests_passed"] += 1
            return True
            
        except Exception as e:
            logger.error(f"❌ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            self.results["tests_failed"] += 1
            self.results["errors"].append(f"Get non-existent space exception: {str(e)}")
            return False
    
    async def test_list_spaces(self) -> bool:
        """Test listing all spaces."""
        logger.info("\n" + "=" * 80)
        logger.info("TEST 4: List Spaces")
        logger.info("=" * 80)
        
        self.results["tests_run"] += 1
        
        try:
            logger.info("Listing all spaces")
            response = await self.client.spaces.list_spaces()
            
            # Check response type
            if not isinstance(response, SpacesListResponse):
                logger.error(f"❌ Wrong response type: {type(response)}")
                self.results["tests_failed"] += 1
                self.results["errors"].append("List spaces returned wrong response type")
                return False
            
            # Check success
            if not response.is_success:
                logger.error(f"❌ List failed: {response.error_message}")
                self.results["tests_failed"] += 1
                self.results["errors"].append(f"List spaces failed: {response.error_message}")
                return False
            
            # Verify spaces list
            logger.info(f"✅ Spaces listed successfully")
            logger.info(f"   Total spaces: {response.total}")
            logger.info(f"   Count: {response.count}")
            logger.info(f"   Response type: {type(response).__name__}")
            
            # Verify our test space is in the list
            test_space = next((s for s in response.spaces if s.space == self.test_space_id), None)
            if test_space is None:
                logger.error(f"❌ Test space not found in list")
                self.results["tests_failed"] += 1
                self.results["errors"].append("Test space not in list")
                return False
            
            logger.info(f"✅ Test space found in list: {test_space.space_name}")
            
            # Verify space types
            for space in response.spaces[:3]:  # Check first 3
                if not isinstance(space, Space):
                    logger.error(f"❌ Space is not a Space instance: {type(space)}")
                    self.results["tests_failed"] += 1
                    self.results["errors"].append("List spaces type annotation failed")
                    return False
            
            logger.info(f"✅ Space type annotations validated")
            
            self.results["tests_passed"] += 1
            return True
            
        except Exception as e:
            logger.error(f"❌ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            self.results["tests_failed"] += 1
            self.results["errors"].append(f"List spaces exception: {str(e)}")
            return False
    
    async def test_get_space_info(self) -> bool:
        """Test getting detailed space information."""
        logger.info("\n" + "=" * 80)
        logger.info("TEST 5: Get Space Info")
        logger.info("=" * 80)
        
        self.results["tests_run"] += 1
        
        try:
            logger.info(f"Getting space info: {self.test_space_id}")
            response = await self.client.spaces.get_space_info(self.test_space_id)
            
            # Check response type
            if not isinstance(response, SpaceInfoResponse):
                logger.error(f"❌ Wrong response type: {type(response)}")
                self.results["tests_failed"] += 1
                self.results["errors"].append("Get space info returned wrong response type")
                return False
            
            # Check success
            if not response.is_success:
                logger.error(f"❌ Get info failed: {response.error_message}")
                self.results["tests_failed"] += 1
                self.results["errors"].append(f"Get space info failed: {response.error_message}")
                return False
            
            # Verify space info
            logger.info(f"✅ Space info retrieved successfully")
            logger.info(f"   Space ID: {response.space.space}")
            logger.info(f"   Space Name: {response.space.space_name}")
            logger.info(f"   Statistics: {response.statistics}")
            logger.info(f"   Quad dump: {len(response.quad_dump) if response.quad_dump else 0} quads")
            logger.info(f"   Response type: {type(response).__name__}")
            
            # Verify space type
            if not isinstance(response.space, Space):
                logger.error(f"❌ Space is not a Space instance: {type(response.space)}")
                self.results["tests_failed"] += 1
                self.results["errors"].append("Get space info type annotation failed")
                return False
            
            logger.info(f"✅ Space type annotation validated: {type(response.space).__name__}")
            
            self.results["tests_passed"] += 1
            return True
            
        except Exception as e:
            logger.error(f"❌ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            self.results["tests_failed"] += 1
            self.results["errors"].append(f"Get space info exception: {str(e)}")
            return False
    
    async def test_update_space(self) -> bool:
        """Test updating a space."""
        logger.info("\n" + "=" * 80)
        logger.info("TEST 6: Update Space")
        logger.info("=" * 80)
        
        self.results["tests_run"] += 1
        
        try:
            # Create updated space data
            updated_space = Space(
                space=self.test_space_id,
                space_name="Updated Spaces Endpoint Test Space",
                space_description="Updated description for testing",
                tenant="test_tenant"
            )
            
            logger.info(f"Updating space: {self.test_space_id}")
            response = await self.client.spaces.update_space(self.test_space_id, updated_space)
            
            # Check response type
            if not isinstance(response, SpaceUpdateResponse):
                logger.error(f"❌ Wrong response type: {type(response)}")
                self.results["tests_failed"] += 1
                self.results["errors"].append("Update space returned wrong response type")
                return False
            
            # Check success
            if not response.is_success:
                logger.error(f"❌ Update failed: {response.error_message}")
                self.results["tests_failed"] += 1
                self.results["errors"].append(f"Update space failed: {response.error_message}")
                return False
            
            # Verify update
            logger.info(f"✅ Space updated successfully")
            logger.info(f"   Updated count: {response.updated_count}")
            logger.info(f"   Response type: {type(response).__name__}")
            
            # Verify updated_count
            if response.updated_count != 1:
                logger.warning(f"⚠️  Expected updated_count=1, got {response.updated_count}")
            
            self.results["tests_passed"] += 1
            return True
            
        except Exception as e:
            logger.error(f"❌ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            self.results["tests_failed"] += 1
            self.results["errors"].append(f"Update space exception: {str(e)}")
            return False
    
    async def test_delete_space(self) -> bool:
        """Test deleting a space."""
        logger.info("\n" + "=" * 80)
        logger.info("TEST 7: Delete Space")
        logger.info("=" * 80)
        
        self.results["tests_run"] += 1
        
        try:
            logger.info(f"Deleting space: {self.test_space_id}")
            response = await self.client.spaces.delete_space(self.test_space_id)
            
            # Check response type
            if not isinstance(response, SpaceDeleteResponse):
                logger.error(f"❌ Wrong response type: {type(response)}")
                self.results["tests_failed"] += 1
                self.results["errors"].append("Delete space returned wrong response type")
                return False
            
            # Check success
            if not response.is_success:
                logger.error(f"❌ Delete failed: {response.error_message}")
                self.results["tests_failed"] += 1
                self.results["errors"].append(f"Delete space failed: {response.error_message}")
                return False
            
            # Verify deletion
            logger.info(f"✅ Space deleted successfully")
            logger.info(f"   Deleted count: {response.deleted_count}")
            logger.info(f"   Space ID: {response.space_id}")
            logger.info(f"   Response type: {type(response).__name__}")
            
            # Verify deleted_count
            if response.deleted_count != 1:
                logger.warning(f"⚠️  Expected deleted_count=1, got {response.deleted_count}")
            
            self.results["tests_passed"] += 1
            return True
            
        except Exception as e:
            logger.error(f"❌ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            self.results["tests_failed"] += 1
            self.results["errors"].append(f"Delete space exception: {str(e)}")
            return False
    
    def print_summary(self) -> None:
        """Print test summary."""
        logger.info("\n" + "=" * 80)
        logger.info("TEST SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Tests run: {self.results['tests_run']}")
        logger.info(f"Tests passed: {self.results['tests_passed']}")
        logger.info(f"Tests failed: {self.results['tests_failed']}")
        
        if self.results["errors"]:
            logger.info("\nErrors:")
            for error in self.results["errors"]:
                logger.info(f"  • {error}")
        
        logger.info("=" * 80)
        
        if self.results["tests_failed"] == 0:
            logger.info("🎉 All tests PASSED!")
        else:
            logger.info(f"❌ {self.results['tests_failed']} test(s) FAILED")
    
    async def run_all_tests(self) -> bool:
        """Run all tests."""
        if not await self.setup():
            return False
        
        # Clean up any existing test space
        await self.cleanup_existing_space()
        
        # Run tests in order
        await self.test_create_space()
        await self.test_get_space()
        await self.test_get_space_not_found()  # Error response test
        await self.test_list_spaces()
        await self.test_get_space_info()
        await self.test_update_space()
        await self.test_delete_space()
        
        # Print summary
        self.print_summary()
        
        # Close client
        if self.client:
            await self.client.close()
            logger.info("\n✅ Client closed")
        
        return self.results["tests_failed"] == 0


async def main():
    """Main entry point."""
    tester = SpacesEndpointTester()
    success = await tester.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
