#!/usr/bin/env python3
"""
Space Manager Test Script
========================

Test the complete space management lifecycle in VitalGraph including:
- Space creation with database records and tables
- Space validation and orphaned space detection
- Data insertion and retrieval in managed spaces
- Space deletion with complete cleanup
- Integration between SpaceManager, SpaceImpl, and PostgreSQLSpaceImpl

This test follows the pattern of other VitalGraph test scripts and validates
the complete space management architecture.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import List, Dict, Any

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.config.config_loader import get_config
from vitalgraph.space.space_manager import SpaceManager
from vitalgraph.space.space_impl import SpaceImpl

# Configure logging to see detailed space management operations
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(name)s - %(message)s')

# Suppress verbose logging from other modules
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.space.postgresql_space_core').setLevel(logging.WARNING)

# Test configuration
# Use short space ID to avoid PostgreSQL identifier length limits (63 chars)
timestamp = int(time.time()) % 10000  # Use last 4 digits only
TEST_SPACE_ID = f"test_sm_{timestamp}"
TEST_SPACE_NAME = "Test Space Manager Space"
TEST_SPACE_DESCRIPTION = "Test space created by space manager test script"

async def cleanup_test_space(impl, space_id: str):
    """
    Comprehensive cleanup of test space including tables, indexes, and database records.
    
    Args:
        impl: VitalGraphImpl instance
        space_id: Space identifier to clean up
    """
    print(f"🧹 Performing comprehensive cleanup for space '{space_id}'...")
    
    try:
        # Step 1: Manual index cleanup (addresses the core issue)
        print(f"🔧 Cleaning up indexes for space '{space_id}'...")
        global_prefix = impl.db_impl.global_prefix
        table_prefix = f"{global_prefix}__{space_id}__"
        
        # Get database connection for manual index cleanup
        with impl.db_impl.shared_pool.connection() as conn:
            cursor = conn.cursor()
            
            # List of index patterns to clean up
            index_patterns = [
                f"idx_{table_prefix}%",
                f"idx_{table_prefix}_unlogged%"
            ]
            
            for pattern in index_patterns:
                # Find indexes matching the pattern
                cursor.execute("""
                    SELECT indexname FROM pg_indexes 
                    WHERE indexname LIKE %s
                """, (pattern,))
                
                indexes = cursor.fetchall()
                for (index_name,) in indexes:
                    try:
                        cursor.execute(f"DROP INDEX IF EXISTS {index_name} CASCADE")
                        print(f"✅ Dropped index: {index_name}")
                    except Exception as e:
                        print(f"⚠️ Failed to drop index {index_name}: {e}")
            
            # Also clean up any tables matching the pattern
            table_patterns = [
                f"{table_prefix}%"
            ]
            
            for pattern in table_patterns:
                cursor.execute("""
                    SELECT tablename FROM pg_tables 
                    WHERE tablename LIKE %s AND schemaname = 'public'
                """, (pattern,))
                
                tables = cursor.fetchall()
                for (table_name,) in tables:
                    try:
                        cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
                        print(f"✅ Dropped table: {table_name}")
                    except Exception as e:
                        print(f"⚠️ Failed to drop table {table_name}: {e}")
            
            conn.commit()
        
        # Step 2: Use standard space deletion if space exists
        space_impl_pg = impl.db_impl.space_impl
        if space_impl_pg.space_exists(space_id):
            print(f"📋 Space tables still exist for '{space_id}', using standard deletion...")
            if space_impl_pg.delete_space_tables(space_id):
                print(f"✅ Successfully deleted remaining tables for space '{space_id}'")
            else:
                print(f"⚠️ Failed to delete remaining tables for space '{space_id}'")
        else:
            print(f"📋 No remaining tables found for space '{space_id}'")
            
        # Step 3: Check and delete database record
        db_spaces = await impl.db_impl.list_spaces()
        existing_space = next((s for s in db_spaces if s.get('space') == space_id), None)
        
        if existing_space:
            print(f"📋 Database record exists for '{space_id}', deleting...")
            space_db_id = existing_space.get('id')
            if await impl.db_impl.remove_space(str(space_db_id)):
                print(f"✅ Successfully deleted database record for space '{space_id}'")
            else:
                print(f"⚠️ Failed to delete database record for space '{space_id}'")
        else:
            print(f"📋 No database record found for space '{space_id}'")
            
        # Step 4: Remove from space manager registry if present
        space_manager = impl.space_manager
        if space_manager.has_space(space_id):
            space_manager.remove_space(space_id)
            print(f"✅ Removed space '{space_id}' from registry")
            
        print(f"🎯 Comprehensive cleanup complete for space '{space_id}'")
        return True
        
    except Exception as e:
        print(f"❌ Cleanup failed for space '{space_id}': {e}")
        return False

def test_space_id_validation(space_manager):
    """Test space ID length validation to prevent PostgreSQL identifier issues."""
    import sys
    from vitalgraph.db.postgresql.space.postgresql_space_utils import PostgreSQLSpaceUtils
    
    try:
        # Test 1: Valid short space ID should pass
        print("   ✅ Testing valid short space ID...")
        sys.stdout.flush()
        PostgreSQLSpaceUtils.validate_space_id("test_sm_123")
        
        # Test 2: Space ID at reasonable length should pass
        print("   ✅ Testing reasonable length space ID...")
        sys.stdout.flush()
        PostgreSQLSpaceUtils.validate_space_id("test_space")
        
        # Test 3: Very long space ID should fail (over 14 chars)
        print("   ⚠️ Testing overly long space ID (should fail)...")
        sys.stdout.flush()
        try:
            long_space_id = "test_space_manager_very_long_name"  # 30 chars - definitely over limit
            PostgreSQLSpaceUtils.validate_space_id(long_space_id)
            print(f"   ❌ ERROR: Long space ID '{long_space_id}' was accepted (should have been rejected)")
            sys.stdout.flush()
            return False
        except ValueError as e:
            if "too long" in str(e) and "PostgreSQL" in str(e):
                print(f"   ✅ Long space ID properly rejected: {str(e)[:80]}...")
                sys.stdout.flush()
            else:
                print(f"   ❌ ERROR: Wrong error message: {e}")
                sys.stdout.flush()
                return False
        
        # Test 4: Demonstrate the problem this prevents
        print("   🔍 Demonstrating PostgreSQL identifier length issue prevention...")
        sys.stdout.flush()
        problematic_space_id = "test_space_manager_12345"
        global_prefix = "vitalgraph1"
        table_prefix = f"{global_prefix}__{problematic_space_id}__"
        longest_index = f"idx_{table_prefix}_unlogged_term_text_gist_trgm"
        
        print(f"   📊 Example problematic space ID: '{problematic_space_id}' ({len(problematic_space_id)} chars)")
        print(f"   📊 Generated index name would be: '{longest_index}' ({len(longest_index)} chars)")
        print(f"   📊 PostgreSQL limit: 63 characters")
        sys.stdout.flush()
        
        if len(longest_index) > 63:
            print(f"   ⚠️ Would exceed limit by {len(longest_index) - 63} chars - validation prevents this!")
            sys.stdout.flush()
        
        return True
        
    except Exception as e:
        print(f"   ❌ Validation test failed with unexpected error: {e}")
        sys.stdout.flush()
        return False

async def test_space_manager_lifecycle():
    """Test the complete space manager lifecycle including creation, validation, and deletion."""
    print("🚀 Space Manager Lifecycle Test")
    print("=" * 50)
    
    # Initialize VitalGraph with configuration
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    print(f"✅ Connected to database | Testing space manager functionality")
    
    # Get the space manager
    space_manager = impl.get_space_manager()
    print(f"📋 Space Manager: {type(space_manager).__name__}")
    print(f"📊 Initial spaces in registry: {len(space_manager)}")
    
    # List existing spaces for reference
    existing_spaces = space_manager.list_spaces()
    print(f"📝 Existing spaces: {existing_spaces}")
    
    test_results = []
    
    try:
        # Test 1: Detect orphaned spaces (if any)
        print(f"\n1️⃣ ORPHANED SPACE DETECTION")
        print("-" * 30)
        
        orphaned_spaces = await space_manager.detect_orphaned_spaces()
        if orphaned_spaces:
            print(f"⚠️ Found {len(orphaned_spaces)} orphaned spaces: {orphaned_spaces}")
        else:
            print("✅ No orphaned spaces detected")
        test_results.append(("Orphaned Space Detection", True, "Completed successfully"))
        
        # Test 2: Space ID Length Validation
        print(f"\n2️⃣ SPACE ID LENGTH VALIDATION")
        print("-" * 30)
        
        # Inline validation tests to ensure they display properly
        from vitalgraph.db.postgresql.space.postgresql_space_utils import PostgreSQLSpaceUtils
        validation_passed = True
        
        try:
            # Test 1: Valid short space ID should pass
            print("   ✅ Testing valid short space ID...")
            PostgreSQLSpaceUtils.validate_space_id("test_sm_123")
            print("      PASS: Short space ID accepted")
            
            # Test 2: Space ID at reasonable length should pass
            print("   ✅ Testing reasonable length space ID...")
            PostgreSQLSpaceUtils.validate_space_id("test_space")
            print("      PASS: Reasonable space ID accepted")
            
            # Test 3: Very long space ID should fail (over 14 chars)
            print("   ⚠️ Testing overly long space ID (should fail)...")
            try:
                long_space_id = "test_space_manager_very_long_name"  # 30 chars - definitely over limit
                PostgreSQLSpaceUtils.validate_space_id(long_space_id)
                print(f"      ❌ ERROR: Long space ID '{long_space_id}' was accepted (should have been rejected)")
                validation_passed = False
            except ValueError as e:
                if "too long" in str(e) and "PostgreSQL" in str(e):
                    print(f"      ✅ PASS: Long space ID properly rejected")
                    print(f"      Error: {str(e)[:80]}...")
                else:
                    print(f"      ❌ ERROR: Wrong error message: {e}")
                    validation_passed = False
            
            # Test 4: Demonstrate the problem this prevents
            print("   🔍 Demonstrating PostgreSQL identifier length issue prevention...")
            problematic_space_id = "test_space_manager_12345"
            global_prefix = "vitalgraph1"
            table_prefix = f"{global_prefix}__{problematic_space_id}__"
            longest_index = f"idx_{table_prefix}_unlogged_term_text_gist_trgm"
            
            print(f"      📊 Example problematic space ID: '{problematic_space_id}' ({len(problematic_space_id)} chars)")
            print(f"      📊 Generated index name would be: '{longest_index}' ({len(longest_index)} chars)")
            print(f"      📊 PostgreSQL limit: 63 characters")
            
            if len(longest_index) > 63:
                print(f"      ⚠️ Would exceed limit by {len(longest_index) - 63} chars - validation prevents this!")
            
            if validation_passed:
                print("✅ Space ID length validation working correctly")
                test_results.append(("Space ID Validation", True, "Length validation prevents problematic space IDs"))
            else:
                print("❌ Space ID length validation failed")
                test_results.append(("Space ID Validation", False, "Length validation not working properly"))
                
        except Exception as e:
            print(f"❌ Space ID validation test failed with exception: {e}")
            test_results.append(("Space ID Validation", False, f"Exception: {e}"))
        
        # Test 3: Create new space with complete lifecycle
        print(f"\n3️⃣ SPACE CREATION WITH TABLES")
        print("-" * 30)
        
        # Perform comprehensive cleanup of test space before starting
        await cleanup_test_space(impl, TEST_SPACE_ID)
        
        # Create the space
        creation_success = await space_manager.create_space_with_tables(
            space_id=TEST_SPACE_ID,
            space_name=TEST_SPACE_NAME,
            space_description=TEST_SPACE_DESCRIPTION
        )
        
        if creation_success:
            print(f"✅ Successfully created space '{TEST_SPACE_ID}'")
            test_results.append(("Space Creation", True, "Space created with tables and database record"))
        else:
            print(f"❌ Failed to create space '{TEST_SPACE_ID}'")
            test_results.append(("Space Creation", False, "Space creation failed"))
            return test_results
        
        # Test 4: Validate space exists in all components
        print(f"\n4️⃣ SPACE VALIDATION")
        print("-" * 30)
        
        # Check registry
        in_registry = space_manager.has_space(TEST_SPACE_ID)
        print(f"📋 In registry: {in_registry}")
        
        # Check database record
        db_spaces = await impl.db_impl.list_spaces()
        in_database = any(space.get('space') == TEST_SPACE_ID for space in db_spaces)
        print(f"🗄️ In database: {in_database}")
        
        # Check tables exist
        space_record = space_manager.get_space(TEST_SPACE_ID)
        tables_exist = await space_record.space_impl.exists() if space_record else False
        print(f"🗃️ Tables exist: {tables_exist}")
        
        validation_success = in_registry and in_database and tables_exist
        if validation_success:
            print("✅ Space validation passed - exists in registry, database, and has tables")
            test_results.append(("Space Validation", True, "Space exists in all components"))
        else:
            print("❌ Space validation failed")
            test_results.append(("Space Validation", False, f"Registry: {in_registry}, DB: {in_database}, Tables: {tables_exist}"))
        
        # Test 5: Insert test data into the space
        print(f"\n5️⃣ DATA INSERTION TEST")
        print("-" * 30)
        
        try:
            # Get the PostgreSQL space implementation for data operations
            space_impl_pg = impl.db_impl.get_space_impl()
            
            # Insert some test RDF quads
            from rdflib import URIRef, Literal
            
            test_quads = [
                (
                    URIRef("http://example.org/test/entity1"),
                    URIRef("http://example.org/test/hasName"),
                    Literal("Test Entity 1"),
                    URIRef("http://example.org/test/graph")
                ),
                (
                    URIRef("http://example.org/test/entity1"),
                    URIRef("http://example.org/test/hasType"),
                    URIRef("http://example.org/test/TestEntity"),
                    URIRef("http://example.org/test/graph")
                ),
                (
                    URIRef("http://example.org/test/entity2"),
                    URIRef("http://example.org/test/hasName"),
                    Literal("Test Entity 2"),
                    URIRef("http://example.org/test/graph")
                )
            ]
            
            # Insert the quads
            inserted_count = await space_impl_pg.add_rdf_quads_batch(TEST_SPACE_ID, test_quads)
            print(f"📝 Inserted {inserted_count} test quads")
            
            # Verify data was inserted
            quad_count = await space_impl_pg.get_quad_count(TEST_SPACE_ID)
            print(f"📊 Total quads in space: {quad_count}")
            
            if inserted_count > 0 and quad_count >= inserted_count:
                print("✅ Data insertion successful")
                test_results.append(("Data Insertion", True, f"Inserted {inserted_count} quads"))
            else:
                print("❌ Data insertion failed")
                test_results.append(("Data Insertion", False, f"Expected {len(test_quads)}, got {inserted_count}"))
                
        except Exception as e:
            print(f"❌ Data insertion failed: {e}")
            test_results.append(("Data Insertion", False, f"Exception: {e}"))
        
        # Test 6: Space information retrieval
        print(f"\n6️⃣ SPACE INFORMATION")
        print("-" * 30)
        
        space_info = await space_manager.get_space_info(TEST_SPACE_ID)
        if space_info:
            print(f"📋 Space Info: {space_info}")
            test_results.append(("Space Information", True, "Retrieved space information"))
        else:
            print("❌ Failed to retrieve space information")
            test_results.append(("Space Information", False, "No space information available"))
        
        # Test 7: Space deletion with cleanup
        print(f"\n7️⃣ SPACE DELETION WITH CLEANUP")
        print("-" * 30)
        
        deletion_success = await space_manager.delete_space_with_tables(TEST_SPACE_ID)
        
        if deletion_success:
            print(f"✅ Successfully deleted space '{TEST_SPACE_ID}'")
            
            # Verify complete cleanup
            print("🔍 Verifying complete cleanup...")
            
            # Check registry
            still_in_registry = space_manager.has_space(TEST_SPACE_ID)
            print(f"📋 Still in registry: {still_in_registry}")
            
            # Check database
            db_spaces_after = await impl.db_impl.list_spaces()
            still_in_database = any(space.get('space') == TEST_SPACE_ID for space in db_spaces_after)
            print(f"🗄️ Still in database: {still_in_database}")
            
            cleanup_success = not still_in_registry and not still_in_database
            if cleanup_success:
                print("✅ Complete cleanup verified")
                test_results.append(("Space Deletion", True, "Space deleted with complete cleanup"))
            else:
                print("⚠️ Incomplete cleanup detected")
                test_results.append(("Space Deletion", False, f"Registry: {still_in_registry}, DB: {still_in_database}"))
        else:
            print(f"❌ Failed to delete space '{TEST_SPACE_ID}'")
            test_results.append(("Space Deletion", False, "Space deletion failed"))
        
    except Exception as e:
        print(f"❌ Test execution failed: {e}")
        test_results.append(("Test Execution", False, f"Exception: {e}"))
    
    finally:
        # Cleanup: ensure test space is removed even if tests failed
        try:
            if space_manager.has_space(TEST_SPACE_ID):
                print(f"\n🧹 Final cleanup: removing test space '{TEST_SPACE_ID}'")
                space_manager.delete_space_with_cleanup(TEST_SPACE_ID)
        except Exception as cleanup_e:
            print(f"⚠️ Final cleanup warning: {cleanup_e}")
        
        # Disconnect from database
        await impl.db_impl.disconnect()
        print("\n🔌 Disconnected from database")
    
    return test_results

def print_test_summary(test_results: List[tuple]):
    """Print a comprehensive test results summary."""
    print(f"\n📊 TEST RESULTS SUMMARY")
    print("=" * 50)
    
    total_tests = len(test_results)
    passed_tests = sum(1 for _, success, _ in test_results if success)
    failed_tests = total_tests - passed_tests
    success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
    
    print(f"Total Tests: {total_tests}")
    print(f"✅ Passed: {passed_tests}")
    print(f"❌ Failed: {failed_tests}")
    print(f"📈 Success Rate: {success_rate:.1f}%")
    
    if failed_tests > 0:
        print(f"\n❌ Failed Tests:")
        for test_name, success, message in test_results:
            if not success:
                print(f"   • {test_name}: {message}")
    
    print(f"\n📋 Detailed Results:")
    for test_name, success, message in test_results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"   {status} {test_name}: {message}")

async def main():
    """Main test execution function."""
    print("🧪 VitalGraph Space Manager Test Suite")
    print("=" * 60)
    print("Testing complete space lifecycle management:")
    print("• Space creation with database records and tables")
    print("• Orphaned space detection and validation")
    print("• Data insertion and retrieval")
    print("• Space deletion with complete cleanup")
    print("• Integration between all space management components")
    print()
    
    start_time = time.time()
    
    try:
        test_results = await test_space_manager_lifecycle()
        
        execution_time = time.time() - start_time
        print(f"\n⏱️ Total execution time: {execution_time:.2f} seconds")
        
        print_test_summary(test_results)
        
        # Determine overall success
        overall_success = all(success for _, success, _ in test_results)
        
        if overall_success:
            print(f"\n🎉 ALL TESTS PASSED! Space Manager is working correctly.")
            print("✅ Space lifecycle management is fully functional")
        else:
            print(f"\n⚠️ Some tests failed. Please review the results above.")
            
    except Exception as e:
        print(f"\n💥 Test suite execution failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
