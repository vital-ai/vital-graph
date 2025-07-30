#!/usr/bin/env python3
"""
PostgreSQL Space Transaction Management Test Script
==================================================

Comprehensive testing of PostgreSQLSpaceTransaction functionality including:
- Transaction creation and lifecycle management
- Connection encapsulation and cleanup
- Commit and rollback operations
- Active transaction tracking
- Bulk rollback functionality
- Context manager support
- Integration with space operations

Follows the established VitalGraph test patterns for database operations.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Optional

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.config.config_loader import get_config
from vitalgraph.db.postgresql.space.postgresql_space_transaction import PostgreSQLSpaceTransaction
from rdflib import URIRef, Literal, Namespace

# Reduce logging chatter
logging.getLogger('vitalgraph.db.postgresql.postgresql_space_impl').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)

# Configuration - Use existing test space with real data
SPACE_ID = "space_test"
GRAPH_URI = "http://vital.ai/graph/test"

# Global variables for database connection
impl = None
space_impl = None

# Test namespaces - Use actual test data namespaces
VITAL_NS = Namespace("http://vital.ai/ontology/vital#")
TEST_NS = Namespace("http://vital.ai/ontology/test#")
EX_NS = Namespace("http://example.org/")

async def setup_connection():
    """Initialize database connection for tests."""
    global impl, space_impl
    
    print("🔌 Setting up database connection...")
    
    # Initialize VitalGraphImpl with config file
    project_root = Path(__file__).parent.parent.parent
    config_path = project_root / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    config = get_config(str(config_path))
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    # Get space implementation for transaction operations
    space_impl = impl.db_impl.get_space_impl()
    
    # Check connection pool stats
    pool_stats = space_impl.core.get_pool_stats()
    print(f"✅ Connected to database with global prefix: {space_impl.global_prefix}")
    print(f"📊 Connection Pool Stats:")
    for pool_name, stats in pool_stats.items():
        print(f"   {pool_name}: {stats}")

async def cleanup_connection():
    """Clean up database connection."""
    global impl, space_impl
    
    if impl:
        await impl.db_impl.disconnect()
        print("🔌 Database connection closed")
    
    # Clear global references
    impl = None
    space_impl = None

async def ensure_test_space():
    """Ensure test space exists with test data loaded."""
    if not space_impl.space_exists(SPACE_ID):
        print(f"❌ Test space '{SPACE_ID}' does not exist!")
        print(f"Please run the test data loader first: python test_scripts/data/reload_test_data.py")
        raise RuntimeError(f"Required test space '{SPACE_ID}' not found")
    else:
        print(f"✅ Test space '{SPACE_ID}' exists with test data")
        
        # Verify test data is loaded by checking quad count
        try:
            quad_count = await space_impl.get_quad_count(SPACE_ID)
            print(f"✅ Test space contains {quad_count} quads")
            if quad_count == 0:
                print(f"⚠️  Warning: Test space exists but contains no data")
                print(f"Consider running: python test_scripts/data/reload_test_data.py")
        except Exception as e:
            print(f"⚠️  Could not verify quad count: {e}")

async def test_transaction_creation_and_basic_operations():
    """Test basic transaction creation, commit, and rollback operations."""
    print("\n" + "="*60)
    print("TEST: Transaction Creation and Basic Operations")
    print("="*60)
    
    try:
        # Ensure test space exists
        await ensure_test_space()
        
        # Get core for transaction management
        core = space_impl.core
        
        print(f"✅ Using space implementation with global prefix: {space_impl.global_prefix}")
        
        # Test 1: Create transaction and verify with existing test data
        print("\n1. Creating transaction and verifying with test data...")
        transaction1 = await core.create_transaction(space_impl)
        
        # Use transaction connection to query existing test data
        conn = transaction1.get_connection()
        cursor = conn.cursor()
        
        # Query for existing test entities (entity1, entity2, etc. from test data)
        term_table = space_impl.utils.get_table_name(space_impl.global_prefix, SPACE_ID, "term")
        cursor.execute(f"SELECT term_text, term_type FROM {term_table} WHERE term_text LIKE '%entity%' LIMIT 5")
        entities = cursor.fetchall()
        
        print(f"✅ Found {len(entities)} test entities in transaction:")
        for entity in entities:
            print(f"   - {entity[0]} ({entity[1]})")
        
        # Test 2: Create another transaction
        print("\n2. Creating second transaction...")
        transaction2 = await core.get_transaction(space_impl)  # Using alias method
        print(f"✅ Created second transaction: {transaction2}")
        
        active_count = core.get_active_transaction_count()
        print(f"✅ Active transaction count: {active_count}")
        assert active_count == 2, f"Expected 2 active transactions, got {active_count}"
        
        # Test 3: Commit first transaction
        print("\n3. Committing first transaction...")
        success = await core.commit_transaction_object(transaction1)
        print(f"✅ Transaction 1 commit result: {success}")
        assert success, "Transaction 1 commit failed"
        
        active_count = core.get_active_transaction_count()
        print(f"✅ Active transaction count after commit: {active_count}")
        assert active_count == 1, f"Expected 1 active transaction after commit, got {active_count}"
        
        # Test 4: Rollback second transaction
        print("\n4. Rolling back second transaction...")
        success = await core.rollback_transaction_object(transaction2)
        print(f"✅ Transaction 2 rollback result: {success}")
        assert success, "Transaction 2 rollback failed"
        
        active_count = core.get_active_transaction_count()
        print(f"✅ Active transaction count after rollback: {active_count}")
        assert active_count == 0, f"Expected 0 active transactions after rollback, got {active_count}"
        
        print("\n✅ All basic transaction operations passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_transaction_context_manager():
    """Test transaction as async context manager."""
    print("\n" + "="*60)
    print("TEST: Transaction Context Manager")
    print("="*60)
    
    try:
        # Ensure test space exists
        await ensure_test_space()
        
        # Get core for transaction management
        core = space_impl.core
        
        print(f"✅ Using space implementation")
        
        # Test 1: Context manager with successful completion (should auto-commit)
        print("\n1. Testing context manager with success...")
        async with await core.create_transaction(space_impl) as transaction:
            # Perform read operations that will succeed
            conn = transaction.get_connection()
            cursor = conn.cursor()
            
            # Query for specific test entities from the loaded test data
            term_table = space_impl.utils.get_table_name(space_impl.global_prefix, SPACE_ID, "term")
            cursor.execute(f"SELECT term_text FROM {term_table} WHERE term_text LIKE '%entity1%' LIMIT 1")
            result = cursor.fetchone()
            if result:
                print(f"✅ Successfully queried test entity: {result[0]}")
            else:
                print(f"✅ Query completed (no entity1 found, but transaction worked)")
            # Should auto-commit when exiting context manager
        
        print(f"✅ Context manager completed successfully (auto-committed)")
        
        active_count = core.get_active_transaction_count()
        print(f"✅ Active transaction count after context: {active_count}")
        assert active_count == 0, f"Expected 0 active transactions after context, got {active_count}"
        
        # Test 2: Context manager with exception (should rollback)
        print("\n2. Testing context manager with exception...")
        try:
            async with await core.create_transaction(space_impl) as transaction:
                # Perform read operations within context manager
                conn = transaction.get_connection()
                cursor = conn.cursor()
                
                # Query test data within transaction context
                term_table = space_impl.utils.get_table_name(space_impl.global_prefix, SPACE_ID, "term")
                cursor.execute(f"SELECT COUNT(*) as count FROM {term_table}")
                term_count = (cursor.fetchone())[0]
                print(f"✅ Found {term_count} terms in context manager transaction")
                
                # Force an exception to test auto-rollback
                raise ValueError("Intentional test exception")
                
        except ValueError as e:
            print(f"✅ Caught expected exception: {e}")
            print(f"✅ Transaction should have been automatically rolled back")
        
        active_count = core.get_active_transaction_count()
        print(f"✅ Active transaction count after exception: {active_count}")
        assert active_count == 0, f"Expected 0 active transactions after exception, got {active_count}"
        
        print("\n✅ All context manager tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_bulk_rollback():
    """Test bulk rollback functionality."""
    print("\n" + "="*60)
    print("TEST: Bulk Rollback Functionality")
    print("="*60)
    
    try:
        # Ensure test space exists
        await ensure_test_space()
        
        # Get core for transaction management
        core = space_impl.core
        
        print(f"✅ Using space implementation")
        
        # Clean up any leftover transactions from previous tests
        initial_count = core.get_active_transaction_count()
        if initial_count > 0:
            print(f"⚠️  Found {initial_count} leftover transactions, cleaning up...")
            await core.rollback_all_transactions()
            print(f"✅ Cleaned up leftover transactions")
        
        # Check initial pool stats
        pool_stats = core.get_pool_stats()
        print(f"📊 Initial pool stats: {pool_stats}")
        
        # Create multiple transactions (use 3 to stay within connection pool limits)
        print("\n1. Creating multiple transactions...")
        transactions = []
        for i in range(3):
            transaction = await core.create_transaction(space_impl)
            transactions.append(transaction)
            print(f"✅ Created transaction {i+1}: {transaction.transaction_id}")
            
            # Check pool stats after each transaction
            pool_stats = core.get_pool_stats()
            print(f"   Pool stats after transaction {i+1}: {pool_stats}")
        
        active_count = core.get_active_transaction_count()
        print(f"✅ Total active transactions: {active_count}")
        print(f"📊 Final pool stats before assertion: {core.get_pool_stats()}")
        
        # Debug: Let's see what transactions are actually active
        print(f"🔍 Active transaction IDs: {list(core.active_transactions.keys())}")
        
        assert active_count == 3, f"Expected 3 active transactions, got {active_count}"
        
        # Test bulk rollback
        print("\n2. Performing bulk rollback...")
        rollback_results = await core.rollback_all_transactions()
        
        print(f"✅ Rollback results: {rollback_results}")
        
        # Check that all transactions were rolled back successfully
        successful_rollbacks = sum(1 for success in rollback_results.values() if success)
        print(f"✅ Successful rollbacks: {successful_rollbacks}/3")
        assert successful_rollbacks == 3, f"Expected 3 successful rollbacks, got {successful_rollbacks}"
        
        # Check that no transactions are active
        active_count = core.get_active_transaction_count()
        print(f"✅ Active transaction count after bulk rollback: {active_count}")
        assert active_count == 0, f"Expected 0 active transactions after bulk rollback, got {active_count}"
        
        # Verify individual transaction states
        print("\n3. Verifying individual transaction states...")
        for i, transaction in enumerate(transactions):
            print(f"✅ Transaction {i+1} - Rolled back: {transaction.is_rolled_back}, Active: {transaction.is_active}")
            assert transaction.is_rolled_back, f"Transaction {i+1} should be rolled back"
            assert not transaction.is_active, f"Transaction {i+1} should not be active"
        
        print("\n✅ All bulk rollback tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_transaction_with_space_operations():
    """Test transaction integration with actual space operations."""
    print("\n" + "="*60)
    print("TEST: Transaction Integration with Space Operations")
    print("="*60)
    
    try:
        # Ensure test space exists
        await ensure_test_space()
        
        # Get core for transaction management
        core = space_impl.core
        
        print(f"✅ Using space implementation")
        
        # Test 1: Transaction with connection usage
        print(f"\n1. Testing transaction connection usage...")
        
        transaction = await core.create_transaction(space_impl)
        print(f"✅ Created transaction: {transaction.transaction_id}")
        
        # Get connection from transaction
        conn = transaction.get_connection()
        assert conn is not None, "Transaction should provide a valid connection"
        print(f"✅ Got connection from transaction: {type(conn)}")
        
        # Test query using transaction connection with actual test data
        try:
            cursor = conn.cursor()
            
            # Query actual test data - count quads in the test space
            quad_table = space_impl.utils.get_table_name(space_impl.global_prefix, SPACE_ID, "rdf_quad")
            cursor.execute(f"SELECT COUNT(*) as quad_count FROM {quad_table}")
            result = cursor.fetchone()
            quad_count = result[0]
            print(f"✅ Query result using transaction connection: {quad_count} quads found")
            assert quad_count > 0, f"Expected test data to contain quads, found {quad_count}"
            
            # Query for specific test entities
            term_table = space_impl.utils.get_table_name(space_impl.global_prefix, SPACE_ID, "term")
            cursor.execute(f"SELECT term_text FROM {term_table} WHERE term_text LIKE '%entity%' LIMIT 3")
            entities = cursor.fetchall()
            print(f"✅ Found {len(entities)} test entities:")
            for entity in entities:
                print(f"   - {entity[0]}")
                
        except Exception as e:
            print(f"❌ Query failed: {e}")
            raise
        
        # Commit transaction
        success = await core.commit_transaction_object(transaction)
        assert success, "Transaction commit should succeed"
        print(f"✅ Transaction committed successfully")
        
        # Test 2: Verify transaction can query test data patterns
        print(f"\n2. Testing transaction with test data patterns...")
        
        transaction2 = await core.create_transaction(space_impl)
        conn2 = transaction2.get_connection()
        cursor2 = conn2.cursor()
        
        # Query for test data patterns (entities with hasName property)
        quad_table = space_impl.utils.get_table_name(space_impl.global_prefix, SPACE_ID, "rdf_quad")
        term_table = space_impl.utils.get_table_name(space_impl.global_prefix, SPACE_ID, "term")
        
        # Find entities with hasName property (common in test data)
        query = f"""
        SELECT DISTINCT s.term_text as subject
        FROM {quad_table} q
        JOIN {term_table} s ON q.subject_uuid = s.term_uuid
        JOIN {term_table} p ON q.predicate_uuid = p.term_uuid
        WHERE p.term_text LIKE '%hasName%'
        LIMIT 5
        """
        cursor2.execute(query)
        subjects = cursor2.fetchall()
        
        print(f"✅ Found {len(subjects)} entities with hasName property:")
        for subject in subjects:
            print(f"   - {subject[0]}")
            
        # Commit this transaction too
        success2 = await core.commit_transaction_object(transaction2)
        assert success2, "Second transaction should commit successfully"
        print(f"✅ Second transaction committed successfully")
        
        print("\n✅ All transaction integration tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Main test controller."""
    print("🧪 PostgreSQL Space Transaction Management Test Suite")
    print("=" * 60)
    
    # Setup connection
    await setup_connection()
    
    try:
        # Run comprehensive transaction test suite
        tests = [
            ("Basic Operations", test_transaction_creation_and_basic_operations),
            ("Context Manager", test_transaction_context_manager),
            ("Bulk Rollback", test_bulk_rollback),
            ("Space Integration", test_transaction_with_space_operations),
        ]
        
        results = []
        
        for test_name, test_func in tests:
            print(f"\n🧪 Running {test_name} test...")
            try:
                success = await test_func()
                results.append((test_name, success))
                if success:
                    print(f"✅ {test_name} test PASSED")
                else:
                    print(f"❌ {test_name} test FAILED")
            except Exception as e:
                print(f"❌ {test_name} test FAILED with exception: {e}")
                import traceback
                traceback.print_exc()
                results.append((test_name, False))
        
        # Summary
        print("\n" + "=" * 60)
        print("📊 TEST SUMMARY")
        print("=" * 60)
        
        passed = sum(1 for _, success in results if success)
        total = len(results)
        
        for test_name, success in results:
            status = "✅ PASSED" if success else "❌ FAILED"
            print(f"{test_name:.<40} {status}")
        
        print("-" * 60)
        print(f"Total: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 All tests passed! Transaction management is working correctly.")
        else:
            print("⚠️  Some tests failed. Please review the output above.")
            
    finally:
        # Cleanup
        await cleanup_connection()
        print("\n✅ PostgreSQL Space Transaction Management Test Complete!")

if __name__ == "__main__":
    asyncio.run(main())
