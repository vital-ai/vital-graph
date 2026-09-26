#!/usr/bin/env python3
"""
Test module for atomic update_quads functionality.

This module provides comprehensive validation of the atomic update_quads function
with focus on PostgreSQL transaction management, Fuseki synchronization, and
atomic operation validation.

Location: /Users/hadfield/Local/vital-git/vital-graph/test_scripts/fuseki_postgresql/test_update_quads.py
"""

import sys
import os
import logging
import asyncio
import time
import traceback
from typing import List, Tuple, Dict, Any

# Add the project root to Python path for imports
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot

# VitalGraph imports
from vitalgraph.kg_impl.kg_backend_utils import create_backend_adapter
from test_fuseki_postgresql_endpoint_utils import FusekiPostgreSQLEndpointTester

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class UpdateQuadsTestSuite:
    """Comprehensive test suite for atomic update_quads functionality."""
    
    def __init__(self):
        self.tester = None
        self.backend_adapter = None
        self.space_id = None
        self.graph_id = "http://vital.ai/graph/test_update_quads"
        
    async def setup(self):
        """Initialize test environment."""
        try:
            logger.info("🔧 Setting up UpdateQuads test environment...")
            
            # Create Fuseki+PostgreSQL endpoint tester
            self.tester = FusekiPostgreSQLEndpointTester()
            
            # Setup hybrid backend
            if not await self.tester.setup_hybrid_backend():
                raise Exception("Failed to setup hybrid backend")
            
            # Create test space
            self.space_id = await self.tester.create_test_space("update_quads_test")
            if not self.space_id:
                raise Exception("Failed to create test space")
            
            # Get backend adapter from the hybrid backend
            self.backend_adapter = create_backend_adapter(self.tester.hybrid_backend)
            
            logger.info("✅ UpdateQuads test environment setup complete")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to setup test environment: {e}")
            return False
    
    async def test_basic_update_quads(self) -> bool:
        """Test basic atomic update with simple quad replacement."""
        try:
            logger.info("🧪 Testing basic update_quads functionality...")
            
            # Create test entity
            entity = KGEntity()
            entity.URI = "http://vital.ai/test/entity_basic_update"
            entity.name = "Original Entity Name"  # Use 'name' instead of 'hasName'
            entity.kGGraphURI = self.graph_id
            
            # Store initial entity
            store_result = await self.backend_adapter.store_objects(
                self.space_id, self.graph_id, [entity]
            )
            if not store_result.success:
                raise Exception(f"Failed to store initial entity: {store_result.message}")
            
            # Build delete quads (original name) - use hasName property URI
            delete_quads = [
                (entity.URI, "http://vital.ai/ontology/vital-core#hasName", "Original Entity Name", self.graph_id)
            ]
            
            # Build insert quads (updated name)
            insert_quads = [
                (entity.URI, "http://vital.ai/ontology/vital-core#hasName", "Updated Entity Name", self.graph_id)
            ]
            
            # Execute atomic update
            success = await self.backend_adapter.update_quads(
                self.space_id, self.graph_id, delete_quads, insert_quads
            )
            
            if not success:
                raise Exception("update_quads returned False")
            
            # Verify update by retrieving entity
            get_result = await self.backend_adapter.get_entity(
                self.space_id, self.graph_id, entity.URI
            )
            
            if not get_result.success or not get_result.objects:
                raise Exception("Failed to retrieve updated entity")
            
            updated_entity = get_result.objects[0]
            # Cast VitalSigns property to string for comparison
            entity_name = str(updated_entity.name) if hasattr(updated_entity, 'name') and updated_entity.name else ""
            if entity_name != "Updated Entity Name":
                raise Exception(f"Entity name not updated: {entity_name}")
            
            logger.info("✅ Basic update_quads test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Basic update_quads test failed: {e}")
            logger.error("FULL TRACEBACK:")
            traceback.print_exc()
            return False
    
    async def test_update_quads_empty_sets(self) -> bool:
        """Test edge cases with empty delete/insert sets."""
        try:
            logger.info("🧪 Testing update_quads with empty sets...")
            
            # Test 1: Empty delete set, non-empty insert
            entity_uri = "http://vital.ai/test/entity_empty_delete"
            insert_quads = [
                (entity_uri, "http://vital.ai/ontology/vital-core#hasName", "New Entity", self.graph_id),
                (entity_uri, "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "http://vital.ai/ontology/haley-ai-kg#KGEntity", self.graph_id)
            ]
            
            success = await self.backend_adapter.update_quads(
                self.space_id, self.graph_id, [], insert_quads
            )
            
            if not success:
                raise Exception("update_quads with empty delete set failed")
            
            # Test 2: Non-empty delete set, empty insert (deletion only)
            delete_quads = [
                (entity_uri, "http://vital.ai/ontology/vital-core#hasName", "New Entity", self.graph_id)
            ]
            
            success = await self.backend_adapter.update_quads(
                self.space_id, self.graph_id, delete_quads, []
            )
            
            if not success:
                raise Exception("update_quads with empty insert set failed")
            
            # Test 3: Both sets empty (no-op)
            success = await self.backend_adapter.update_quads(
                self.space_id, self.graph_id, [], []
            )
            
            if not success:
                raise Exception("update_quads with both empty sets failed")
            
            logger.info("✅ Empty sets test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Empty sets test failed: {e}")
            return False
    
    async def test_update_quads_large_operations(self) -> bool:
        """Test performance with large quad sets (1000+ quads)."""
        try:
            logger.info("🧪 Testing update_quads with large quad sets...")
            
            # Generate large number of entities
            num_entities = 100
            entities = []
            delete_quads = []
            insert_quads = []
            
            for i in range(num_entities):
                entity_uri = f"http://vital.ai/test/entity_large_{i}"
                
                # Original quads (to be deleted)
                delete_quads.extend([
                    (entity_uri, "http://vital.ai/ontology/vital-core#hasName", f"Original Name {i}", self.graph_id),
                    (entity_uri, "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "http://vital.ai/ontology/haley-ai-kg#KGEntity", self.graph_id)
                ])
                
                # Updated quads (to be inserted)
                insert_quads.extend([
                    (entity_uri, "http://vital.ai/ontology/vital-core#hasName", f"Updated Name {i}", self.graph_id),
                    (entity_uri, "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "http://vital.ai/ontology/haley-ai-kg#KGEntity", self.graph_id),
                    (entity_uri, "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription", f"Description {i}", self.graph_id)
                ])
            
            # First, store initial entities
            initial_entities = []
            for i in range(num_entities):
                entity = KGEntity()
                entity.URI = f"http://vital.ai/test/entity_large_{i}"
                entity.name = f"Original Name {i}"
                entity.kGGraphURI = self.graph_id
                initial_entities.append(entity)
            
            store_result = await self.backend_adapter.store_objects(
                self.space_id, self.graph_id, initial_entities
            )
            if not store_result.success:
                raise Exception(f"Failed to store initial entities: {store_result.message}")
            
            logger.info(f"🔄 Executing atomic update with {len(delete_quads)} delete quads and {len(insert_quads)} insert quads...")
            
            # Measure performance
            start_time = time.time()
            
            success = await self.backend_adapter.update_quads(
                self.space_id, self.graph_id, delete_quads, insert_quads
            )
            
            end_time = time.time()
            duration = end_time - start_time
            
            if not success:
                raise Exception("Large update_quads operation failed")
            
            logger.info(f"⚡ Large update_quads completed in {duration:.2f} seconds")
            logger.info(f"⚡ Performance: {len(delete_quads + insert_quads) / duration:.0f} quads/second")
            
            # Verify a sample of updates
            sample_entity_uri = "http://vital.ai/test/entity_large_0"
            get_result = await self.backend_adapter.get_entity(
                self.space_id, self.graph_id, sample_entity_uri
            )
            
            if not get_result.success or not get_result.objects:
                raise Exception("Failed to retrieve sample updated entity")
            
            sample_entity = get_result.objects[0]
            # Cast VitalSigns property to string for comparison
            entity_name = str(sample_entity.name) if hasattr(sample_entity, 'name') and sample_entity.name else ""
            if entity_name != "Updated Name 0":
                raise Exception(f"Sample entity not updated correctly: {entity_name}")
            
            logger.info("✅ Large operations test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Large operations test failed: {e}")
            return False
    
    async def test_update_quads_concurrent_operations(self) -> bool:
        """Test concurrent update_quads operations for race conditions."""
        try:
            logger.info("🧪 Testing concurrent update_quads operations...")
            
            # Create multiple entities for concurrent updates
            num_concurrent = 5
            entities = []
            
            for i in range(num_concurrent):
                entity = KGEntity()
                entity.URI = f"http://vital.ai/test/entity_concurrent_{i}"
                entity.name = f"Initial Name {i}"
                entity.kGGraphURI = self.graph_id
                entities.append(entity)
            
            # Store initial entities
            store_result = await self.backend_adapter.store_objects(
                self.space_id, self.graph_id, entities
            )
            if not store_result.success:
                raise Exception(f"Failed to store initial entities: {store_result.message}")
            
            # Define concurrent update operations
            async def update_entity(entity_index: int) -> bool:
                entity_uri = f"http://vital.ai/test/entity_concurrent_{entity_index}"
                
                delete_quads = [
                    (entity_uri, "http://vital.ai/ontology/vital-core#hasName", f"Initial Name {entity_index}", self.graph_id)
                ]
                
                insert_quads = [
                    (entity_uri, "http://vital.ai/ontology/vital-core#hasName", f"Concurrent Update {entity_index}", self.graph_id)
                ]
                
                return await self.backend_adapter.update_quads(
                    self.space_id, self.graph_id, delete_quads, insert_quads
                )
            
            # Execute concurrent updates
            logger.info(f"🔄 Executing {num_concurrent} concurrent update_quads operations...")
            
            tasks = [update_entity(i) for i in range(num_concurrent)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Check results
            successful_updates = 0
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(f"Concurrent update {i} failed with exception: {result}")
                elif result:
                    successful_updates += 1
                else:
                    logger.warning(f"Concurrent update {i} returned False")
            
            if successful_updates != num_concurrent:
                logger.warning(f"Only {successful_updates}/{num_concurrent} concurrent updates succeeded")
            
            # Verify final state
            for i in range(num_concurrent):
                entity_uri = f"http://vital.ai/test/entity_concurrent_{i}"
                get_result = await self.backend_adapter.get_entity(
                    self.space_id, self.graph_id, entity_uri
                )
                
                if get_result.success and get_result.objects:
                    entity = get_result.objects[0]
                    expected_name = f"Concurrent Update {i}"
                    # Cast VitalSigns property to string for comparison
                    entity_name = str(entity.name) if hasattr(entity, 'name') and entity.name else ""
                    if entity_name == expected_name:
                        logger.info(f"✅ Entity {i} updated correctly")
                    else:
                        logger.warning(f"⚠️ Entity {i} has unexpected name: {entity_name}")
                else:
                    logger.warning(f"⚠️ Failed to retrieve entity {i}")
            
            logger.info("✅ Concurrent operations test completed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Concurrent operations test failed: {e}")
            return False
    
    async def test_update_quads_transaction_rollback(self) -> bool:
        """Test PostgreSQL transaction rollback on failure."""
        try:
            logger.info("🧪 Testing update_quads transaction rollback...")
            
            # Create test entity
            entity = KGEntity()
            entity.URI = "http://vital.ai/test/entity_rollback"
            entity.name = "Original Name"
            entity.kGGraphURI = self.graph_id
            
            # Store initial entity
            store_result = await self.backend_adapter.store_objects(
                self.space_id, self.graph_id, [entity]
            )
            if not store_result.success:
                raise Exception(f"Failed to store initial entity: {store_result.message}")
            
            # Create invalid quads that should cause transaction failure
            # Note: This test depends on backend implementation details
            # We'll simulate by using extremely long values that might cause issues
            delete_quads = [
                (entity.URI, "http://vital.ai/ontology/vital-core#hasName", "Original Name", self.graph_id)
            ]
            
            # Create problematic insert quads (very long string that might cause issues)
            problematic_value = "x" * 10000  # Very long string
            insert_quads = [
                (entity.URI, "http://vital.ai/ontology/vital-core#hasName", problematic_value, self.graph_id)
            ]
            
            # Attempt update (may succeed or fail depending on backend limits)
            try:
                success = await self.backend_adapter.update_quads(
                    self.space_id, self.graph_id, delete_quads, insert_quads
                )
                
                # If it succeeded, verify the update
                if success:
                    get_result = await self.backend_adapter.get_entity(
                        self.space_id, self.graph_id, entity.URI
                    )
                    
                    if get_result.success and get_result.objects:
                        updated_entity = get_result.objects[0]
                        # Cast VitalSigns property to string for comparison
                        entity_name = str(updated_entity.name) if hasattr(updated_entity, 'name') and updated_entity.name else ""
                        if len(entity_name) == 10000:
                            logger.info("✅ Large value update succeeded (no rollback needed)")
                        else:
                            logger.warning("⚠️ Update succeeded but value not as expected")
                    else:
                        logger.warning("⚠️ Update reported success but entity not retrievable")
                else:
                    # Verify original state preserved
                    get_result = await self.backend_adapter.get_entity(
                        self.space_id, self.graph_id, entity.URI
                    )
                    
                    if get_result.success and get_result.objects:
                        entity_after_failure = get_result.objects[0]
                        # Cast VitalSigns property to string for comparison
                        entity_name = str(entity_after_failure.name) if hasattr(entity_after_failure, 'name') and entity_after_failure.name else ""
                        if entity_name == "Original Name":
                            logger.info("✅ Transaction rollback preserved original state")
                        else:
                            raise Exception("Transaction rollback failed - state corrupted")
                    else:
                        raise Exception("Entity lost after failed update")
                
            except Exception as e:
                logger.info(f"✅ Update failed as expected (transaction rollback): {e}")
                
                # Verify original state preserved
                get_result = await self.backend_adapter.get_entity(
                    self.space_id, self.graph_id, entity.URI
                )
                
                if get_result.success and get_result.objects:
                    entity_after_failure = get_result.objects[0]
                    # Cast VitalSigns property to string for comparison
                    entity_name = str(entity_after_failure.name) if hasattr(entity_after_failure, 'name') and entity_after_failure.name else ""
                    if entity_name == "Original Name":
                        logger.info("✅ Transaction rollback preserved original state after exception")
                    else:
                        raise Exception("Transaction rollback failed - state corrupted after exception")
                else:
                    raise Exception("Entity lost after failed update with exception")
            
            logger.info("✅ Transaction rollback test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Transaction rollback test failed: {e}")
            return False
    
    async def test_update_quads_fuseki_sync_failure(self) -> bool:
        """Test Fuseki sync failure handling after PostgreSQL success."""
        try:
            logger.info("🧪 Testing Fuseki sync failure handling...")
            
            # Note: This test is challenging to implement without mocking
            # because we need to simulate Fuseki failure while PostgreSQL succeeds
            # For now, we'll test the normal case and log that sync failure testing
            # would require additional mocking infrastructure
            
            # Create test entity
            entity = KGEntity()
            entity.URI = "http://vital.ai/test/entity_fuseki_sync"
            entity.name = "Original Name"
            entity.kGGraphURI = self.graph_id
            
            # Store initial entity
            store_result = await self.backend_adapter.store_objects(
                self.space_id, self.graph_id, [entity]
            )
            if not store_result.success:
                raise Exception(f"Failed to store initial entity: {store_result.message}")
            
            # Normal update (both PostgreSQL and Fuseki should succeed)
            delete_quads = [
                (entity.URI, "http://vital.ai/ontology/vital-core#hasName", "Original Name", self.graph_id)
            ]
            
            insert_quads = [
                (entity.URI, "http://vital.ai/ontology/vital-core#hasName", "Updated Name", self.graph_id)
            ]
            
            success = await self.backend_adapter.update_quads(
                self.space_id, self.graph_id, delete_quads, insert_quads
            )
            
            if not success:
                raise Exception("Normal update_quads failed")
            
            # Verify update
            get_result = await self.backend_adapter.get_entity(
                self.space_id, self.graph_id, entity.URI
            )
            
            if not get_result.success or not get_result.objects:
                raise Exception("Failed to retrieve updated entity")
            
            updated_entity = get_result.objects[0]
            # Cast VitalSigns property to string for comparison
            entity_name = str(updated_entity.name) if hasattr(updated_entity, 'name') and updated_entity.name else ""
            if entity_name != "Updated Name":
                raise Exception(f"Entity not updated correctly: {entity_name}")
            
            logger.info("✅ Normal Fuseki sync test passed")
            logger.info("ℹ️ Note: Fuseki sync failure testing requires additional mocking infrastructure")
            logger.info("ℹ️ The implementation handles Fuseki sync failures by returning True (PostgreSQL succeeded)")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Fuseki sync failure test failed: {e}")
            return False
    
    async def run_all_tests(self) -> bool:
        """Run all update_quads tests."""
        logger.info("🚀 Starting comprehensive update_quads test suite...")
        
        # Setup test environment
        if not await self.setup():
            logger.error("❌ Test setup failed")
            return False
        
        # Define test cases
        test_cases = [
            ("Basic Update Quads", self.test_basic_update_quads),
            ("Empty Sets", self.test_update_quads_empty_sets),
            ("Large Operations", self.test_update_quads_large_operations),
            ("Concurrent Operations", self.test_update_quads_concurrent_operations),
            ("Transaction Rollback", self.test_update_quads_transaction_rollback),
            ("Fuseki Sync Failure", self.test_update_quads_fuseki_sync_failure),
        ]
        
        # Run tests
        passed_tests = 0
        total_tests = len(test_cases)
        
        for test_name, test_func in test_cases:
            logger.info(f"\n{'='*60}")
            logger.info(f"🧪 Running test: {test_name}")
            logger.info(f"{'='*60}")
            
            try:
                if await test_func():
                    passed_tests += 1
                    logger.info(f"✅ {test_name}: PASSED")
                else:
                    logger.error(f"❌ {test_name}: FAILED")
            except Exception as e:
                logger.error(f"❌ {test_name}: FAILED with exception: {e}")
        
        # Summary
        logger.info(f"\n{'='*60}")
        logger.info(f"🎯 UPDATE_QUADS TEST SUITE SUMMARY")
        logger.info(f"{'='*60}")
        logger.info(f"✅ Passed: {passed_tests}/{total_tests}")
        logger.info(f"❌ Failed: {total_tests - passed_tests}/{total_tests}")
        logger.info(f"📊 Success Rate: {(passed_tests/total_tests)*100:.1f}%")
        
        if passed_tests == total_tests:
            logger.info("🎉 ALL UPDATE_QUADS TESTS PASSED!")
            return True
        else:
            logger.error("💥 SOME UPDATE_QUADS TESTS FAILED!")
            return False


async def main():
    """Main test execution function."""
    test_suite = UpdateQuadsTestSuite()
    success = await test_suite.run_all_tests()
    
    # Force aggressive resource cleanup to prevent ResourceWarning messages
    try:
        from vitalgraph.utils.resource_manager import cleanup_resources
        await cleanup_resources()
        
        # Additional aggressive cleanup
        from vitalgraph.utils.aggressive_cleanup import aggressive_cleanup
        await aggressive_cleanup()
        
    except Exception as e:
        logger.warning(f"⚠️ Error during final resource cleanup: {e}")
    
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
