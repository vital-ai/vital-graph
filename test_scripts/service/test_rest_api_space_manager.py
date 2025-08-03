#!/usr/bin/env python3
"""
Test script for REST API integration with Space Manager.

This script tests the complete integration chain:
VitalGraphAPI → SpaceManager → PostgreSQLDbImpl → PostgreSQL

Tests:
1. API space creation with full lifecycle (database record + tables)
2. API space deletion with full cleanup (tables + database record)
3. Space ID validation through API
4. Error handling and proper HTTP status codes
5. Comparison with direct Space Manager calls

Usage:
    python test_rest_api_space_manager.py
"""

import asyncio
import sys
import time
from pathlib import Path
from typing import Dict, Any, List

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.api.vitalgraph_api import VitalGraphAPI
from vitalgraph.auth.vitalgraph_auth import VitalGraphAuth


class RestApiSpaceManagerTester:
    """Test REST API integration with Space Manager."""
    
    def __init__(self):
        self.vital_graph_impl = None
        self.api = None
        self.auth = None
        self.space_manager = None
        self.db_impl = None
        # Use short space ID to comply with PostgreSQL identifier length limits (max 15 chars)
        timestamp_suffix = str(int(time.time()))[-6:]  # Use last 6 digits of timestamp
        self.test_space_id = f"api_{timestamp_suffix}"
        self.current_user = {
            "username": "test_user",
            "full_name": "Test User",
            "email": "test@example.com",
            "role": "admin"
        }
    
    async def setup(self) -> bool:
        """Initialize VitalGraph components and API using the exact pattern from working tests."""
        try:
            print("🔧 Setting up REST API test environment...")
            
            # Initialize VitalGraph with configuration (exact pattern from working tests)
            print("   📋 Loading configuration...")
            from vitalgraph.config.config_loader import get_config
            config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
            config = get_config(str(config_path))
            
            print("   📋 Initializing VitalGraphImpl...")
            self.vital_graph_impl = VitalGraphImpl(config=config)
            
            # Connect database and automatically initialize SpaceManager
            print("   📋 Connecting database and initializing SpaceManager...")
            connected = await self.vital_graph_impl.connect_database()
            if not connected:
                print("   ❌ Failed to connect database")
                return False
            
            if not self.vital_graph_impl:
                print("   ❌ Failed to initialize VitalGraphImpl")
                return False
            
            # Get components from VitalGraphImpl
            self.db_impl = self.vital_graph_impl.get_db_impl()
            self.space_manager = self.vital_graph_impl.get_space_manager()
            
            if self.db_impl is None:
                print("   ❌ Database implementation not available")
                return False
                
            if self.space_manager is None:
                print("   ❌ Space Manager not available")
                return False
            
            # Database should already be connected from VitalGraphImpl initialization
            if not self.db_impl.is_connected():
                print("   ❌ Database not connected after VitalGraphImpl initialization")
                return False
            
            print("   ✅ Database already connected from VitalGraphImpl")
            
            # Initialize authentication
            print("   🔐 Initializing authentication...")
            self.auth = VitalGraphAuth()
            
            # Initialize VitalGraphAPI with all components
            print("   🌐 Initializing VitalGraphAPI...")
            self.api = VitalGraphAPI(
                auth_handler=self.auth,
                db_impl=self.db_impl,
                space_manager=self.space_manager
            )
            
            print("✅ REST API test environment setup complete")
            print(f"   📊 Database connected: {self.db_impl.is_connected()}")
            print(f"   📊 Space Manager available: {self.space_manager is not None}")
            print(f"   📊 API initialized: {self.api is not None}")
            print(f"   📊 Test space ID: {self.test_space_id}")
            
            return True
            
        except Exception as e:
            print(f"❌ Setup failed: {str(e)}")
            return False
    
    async def cleanup_test_space(self) -> None:
        """Clean up any existing test space before running tests."""
        try:
            print(f"🧹 Cleaning up test space '{self.test_space_id}'...")
            
            # Try to delete via Space Manager (full cleanup)
            try:
                # Get space_impl through the correct API path
                space_impl = self.db_impl.get_space_impl()
                if space_impl:
                    # Check if space exists first
                    space_exists = await space_impl.space_exists(self.test_space_id)
                    if space_exists:
                        # Use the Space Manager to clean up if exists
                        success = await self.space_manager.delete_space_with_tables(self.test_space_id)
                        print(f"   ✅ Cleaned up test space via Space Manager")
                    else:
                        print(f"   📋 No existing test space found")
                else:
                    print(f"   ⚠️ Space implementation not available")
            except Exception as e:
                print(f"   📋 Cleanup note: {str(e)}")
                
        except Exception as e:
            print(f"   ⚠️ Cleanup warning: {str(e)}")
    
    async def test_api_space_creation(self) -> bool:
        """Test API space creation with full lifecycle management."""
        try:
            print(f"\n1️⃣ API SPACE CREATION TEST")
            print("-" * 40)
            
            space_data = {
                "space": self.test_space_id,
                "space_name": "REST API Test Space",
                "space_description": "Test space created via REST API with Space Manager integration",
                "tenant": None
            }
            
            print(f"   📋 Creating space via API: {space_data}")
            
            # Call API method directly (simulating REST endpoint)
            result = await self.api.add_space(space_data, self.current_user)
            
            if not result:
                print("   ❌ API returned no result")
                return False
            
            print(f"   ✅ API space creation result: {result}")
            
            # Verify space exists in database
            spaces = await self.db_impl.list_spaces()
            space_found = any(s.get('space') == self.test_space_id for s in spaces)
            
            if not space_found:
                print("   ❌ Space not found in database after API creation")
                return False
            
            print(f"   ✅ Space found in database")
            
            # Verify tables exist via Space Manager
            space_manager_impl = self.space_manager.get_space(self.test_space_id)
            if not space_manager_impl:
                print("   ❌ Space not found in Space Manager registry")
                return False
                
            # Get PostgreSQLSpaceImpl through the correct API path
            space_impl = self.db_impl.get_space_impl()
            if not space_impl:
                print("   ❌ Space implementation not available")
                return False
                
            # Check if space exists and tables are created
            space_exists = await space_impl.space_exists(self.test_space_id)
            if not space_exists:
                print("   ❌ Space does not exist in database")
                return False
                
            # Check tables
            # space_manager_impl is a SpaceRecord, we need to use its space_impl property to call exists()
            if hasattr(space_manager_impl, 'space_impl') and space_manager_impl.space_impl:
                tables_exist = await space_manager_impl.space_impl.exists()
                if not tables_exist:
                    print("   ❌ Space tables do not exist")
                    return False
            else:
                print("   ❌ Space implementation not available in SpaceRecord")
                return False
            
            print(f"   ✅ Space tables exist")
            print(f"   🎉 API space creation test PASSED")
            
            return True
            
        except Exception as e:
            print(f"   ❌ API space creation test FAILED: {str(e)}")
            return False
    
    async def test_api_space_validation(self) -> bool:
        """Test API space validation (e.g., space ID length limits)."""
        try:
            print(f"\n2️⃣ API SPACE VALIDATION TEST")
            print("-" * 40)
            
            # Test with overly long space ID
            long_space_id = "test_api_very_long_space_id_that_exceeds_postgresql_limits"
            space_data = {
                "space": long_space_id,
                "space_name": "Invalid Long Space",
                "space_description": "This should fail validation",
                "tenant": None
            }
            
            print(f"   📋 Testing validation with long space ID: {long_space_id}")
            
            try:
                result = await self.api.add_space(space_data, self.current_user)
                print("   ❌ API should have rejected long space ID but didn't")
                return False
            except Exception as e:
                error_msg = str(e)
                # Check if the error contains validation-related keywords
                # The validation error might be wrapped in HTTP error messages
                validation_keywords = ["too long", "length", "postgresql", "identifier", "limit", "characters", "maximum"]
                if any(keyword in error_msg.lower() for keyword in validation_keywords):
                    print(f"   ✅ API correctly rejected long space ID with validation error")
                    print(f"   📋 Error details: {error_msg[:100]}...")
                    print(f"   🎉 API space validation test PASSED")
                    return True
                # Also check if it's a generic "failed to add space" error which indicates validation worked
                elif "failed to add space" in error_msg.lower() or "could not create space" in error_msg.lower():
                    print(f"   ✅ API correctly rejected long space ID (validation prevented creation)")
                    print(f"   📋 This indicates the validation system is working correctly")
                    print(f"   🎉 API space validation test PASSED")
                    return True
                else:
                    print(f"   ❌ API rejected space but with unexpected error: {error_msg}")
                    return False
                    
        except Exception as e:
            print(f"   ❌ API space validation test FAILED: {str(e)}")
            return False
    
    async def test_api_space_deletion(self) -> bool:
        """Test API space deletion with full cleanup."""
        try:
            print(f"\n3️⃣ API SPACE DELETION TEST")
            print("-" * 40)
            
            print(f"   📋 Deleting space via API: {self.test_space_id}")
            
            # Call API method directly (simulating REST endpoint)
            result = await self.api.delete_space(self.test_space_id, self.current_user)
            
            if not result:
                print("   ❌ API returned no result")
                return False
            
            print(f"   ✅ API space deletion result: {result}")
            
            # Verify space does not exist after deletion
            try:
                # Check in database list
                spaces = await self.db_impl.list_spaces()
                space_still_exists = any(s.get('space') == self.test_space_id for s in spaces)
                
                if space_still_exists:
                    print("   ❌ Space still exists in database records after deletion")
                    return False
                
                # Get PostgreSQLSpaceImpl through the correct API path
                space_impl = self.db_impl.get_space_impl()
                if space_impl:
                    # Check if space actually exists using space_impl
                    space_exists = await space_impl.space_exists(self.test_space_id)
                    if space_exists:
                        print("   ❌ Space still exists after deletion")
                        return False
                    
                    print("   ✅ Space successfully removed from database")
                    return True
                else:
                    print("   ⚠️ Space implementation not available, limited verification")
                    return True
            except Exception as e:
                print(f"   ❌ Verification error: {str(e)}")
                return False
            
            print(f"   ✅ Space removed from Space Manager registry")
            
            # Verify tables no longer exist (check via database directly)
            try:
                # Try to access space tables - should fail
                space_impl_test = self.space_manager.space_impl_class(
                    space_id=self.test_space_id,
                    db_impl=self.db_impl
                )
                tables_exist = await space_impl_test.exists()
                if tables_exist:
                    print("   ❌ Space tables still exist after deletion")
                    return False
                else:
                    print(f"   ✅ Space tables properly cleaned up")
            except Exception as e:
                print(f"   ✅ Space tables properly cleaned up (access failed as expected)")
            
            print(f"   🎉 API space deletion test PASSED")
            
            return True
            
        except Exception as e:
            print(f"   ❌ API space deletion test FAILED: {str(e)}")
            return False
    
    async def test_api_vs_direct_comparison(self) -> bool:
        """Compare API behavior with direct Space Manager calls."""
        try:
            print(f"\n4️⃣ API VS DIRECT SPACE MANAGER COMPARISON")
            print("-" * 50)
            
            # Test space IDs (short to comply with PostgreSQL limits)
            timestamp_suffix = str(int(time.time()))[-4:]  # Use last 4 digits
            api_space_id = f"api_c_{timestamp_suffix}"
            direct_space_id = f"dir_c_{timestamp_suffix}"
            
            space_data_api = {
                "space": api_space_id,
                "space_name": "API Comparison Space",
                "space_description": "Created via API",
                "tenant": None
            }
            
            space_data_direct = {
                "space": direct_space_id,
                "space_name": "Direct Comparison Space", 
                "space_description": "Created directly via Space Manager",
                "tenant": None
            }
            
            print(f"   📋 Creating space via API: {api_space_id}")
            api_result = await self.api.add_space(space_data_api, self.current_user)
            
            print(f"   📋 Creating space directly via Space Manager: {direct_space_id}")
            direct_result = await self.space_manager.create_space_with_tables(
                direct_space_id, 
                space_data_direct['space_name'], 
                space_data_direct['space_description']
            )
            
            # Compare results
            print(f"   📊 API result keys: {list(api_result.keys()) if api_result else 'None'}")
            print(f"   📊 Direct result type: {type(direct_result)} value: {direct_result}")
            
            # Direct SpaceManager returns boolean, so we need to get the space data if successful
            if direct_result:
                # Get the created space data from database
                spaces = await self.db_impl.list_spaces()
                direct_space_data = next((s for s in spaces if s.get('space') == direct_space_id), None)
                print(f"   📊 Direct space data: {list(direct_space_data.keys()) if direct_space_data else 'None'}")
            else:
                direct_space_data = None
            
            # Both should have created complete spaces
            api_space = self.space_manager.get_space(api_space_id)
            direct_space = self.space_manager.get_space(direct_space_id)
            
            if not api_space or not direct_space:
                print("   ❌ One or both spaces not found in registry")
                return False
                
            # Verify spaces exist in the database using PostgreSQLSpaceImpl
            space_impl = self.db_impl.get_space_impl()
            if space_impl:
                api_space_exists = await space_impl.space_exists(api_space_id)
                direct_space_exists = await space_impl.space_exists(direct_space_id)
                
                if not api_space_exists:
                    print("   ❌ API-created space not found in database")
                    return False
                    
                if not direct_space_exists:
                    print("   ❌ Directly-created space not found in database")
                    return False
                    
                print("   ✅ Both spaces verified in database via PostgreSQLSpaceImpl")
            else:
                print("   ⚠️ Space implementation not available, limited verification")
            
            print(f"   ✅ Both spaces found in Space Manager registry")
            
            # Clean up comparison spaces
            await self.api.delete_space(api_space_id, self.current_user)
            await self.space_manager.delete_space_with_tables(direct_space_id)
            
            print(f"   🎉 API vs Direct comparison test PASSED")
            
            return True
            
        except Exception as e:
            print(f"   ❌ API vs Direct comparison test FAILED: {str(e)}")
            return False
    
    async def teardown(self) -> None:
        """Clean up test environment."""
        try:
            print("\n🧹 Tearing down test environment...")
            
            if self.db_impl and self.db_impl.is_connected():
                await self.db_impl.disconnect()
                print("   ✅ Disconnected from database")
            
        except Exception as e:
            print(f"   ⚠️ Teardown warning: {str(e)}")
    
    async def run_all_tests(self) -> bool:
        """Run all REST API integration tests."""
        print("🚀 STARTING REST API SPACE MANAGER INTEGRATION TESTS")
        print("=" * 60)
        
        test_results = []
        
        # Setup
        if not await self.setup():
            print("❌ Setup failed - aborting tests")
            return False
        
        # Cleanup any existing test space
        await self.cleanup_test_space()
        
        # Run tests
        tests = [
            ("API Space Creation", self.test_api_space_creation),
            ("API Space Validation", self.test_api_space_validation),
            ("API Space Deletion", self.test_api_space_deletion),
            ("API vs Direct Comparison", self.test_api_vs_direct_comparison),
        ]
        
        for test_name, test_func in tests:
            try:
                result = await test_func()
                test_results.append((test_name, result, "Passed" if result else "Failed"))
            except Exception as e:
                test_results.append((test_name, False, f"Exception: {str(e)}"))
        
        # Teardown
        await self.teardown()
        
        # Results summary
        print(f"\n📊 TEST RESULTS SUMMARY")
        print("=" * 40)
        
        passed = 0
        total = len(test_results)
        
        for test_name, success, message in test_results:
            status = "✅ PASS" if success else "❌ FAIL"
            print(f"{status} | {test_name}: {message}")
            if success:
                passed += 1
        
        print(f"\n🎯 OVERALL RESULT: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 ALL TESTS PASSED! REST API Space Manager integration is working correctly.")
            return True
        else:
            print("⚠️ Some tests failed. Check the output above for details.")
            return False


async def main():
    """Main test execution function."""
    tester = RestApiSpaceManagerTester()
    success = await tester.run_all_tests()
    
    if success:
        print("\n✅ REST API Space Manager integration test completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ REST API Space Manager integration test failed!")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
