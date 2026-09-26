#!/usr/bin/env python3
"""
Test module for atomic KGEntity UPDATE functionality using the revised KGEntityUpdateProcessor.

This module validates the revised KGEntity UPDATE operations that use the validated
update_quads function for true atomicity and consistency.

Location: /Users/hadfield/Local/vital-git/vital-graph/test_scripts/fuseki_postgresql/test_atomic_entity_update.py
"""

import sys
import os
import logging
import asyncio
import traceback
from typing import List, Dict, Any
from pathlib import Path

# Add the project root to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGDoubleSlot import KGDoubleSlot

# VitalGraph imports
from vitalgraph.kg_impl.kg_backend_utils import create_backend_adapter
from vitalgraph.kg_impl.kgentity_update_impl import KGEntityUpdateProcessor
from test_fuseki_postgresql_endpoint_utils import FusekiPostgreSQLEndpointTester

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AtomicEntityUpdateTestSuite:
    """Test suite for atomic KGEntity UPDATE functionality."""
    
    def __init__(self):
        self.tester = None
        self.backend_adapter = None
        self.space_id = None
        self.graph_id = "http://vital.ai/graph/test_atomic_entity_update"
        self.processor = KGEntityUpdateProcessor()

    async def setup_test_environment(self):
        """Set up test environment with hybrid backend."""
        try:
            logger.info("🔧 Setting up atomic entity UPDATE test environment...")
            
            # Initialize tester and backend
            self.tester = FusekiPostgreSQLEndpointTester()
            await self.tester.setup_hybrid_backend()
            
            # Create test space
            self.space_id = await self.tester.create_test_space("atomic_entity_update_test")
            
            # Create backend adapter
            self.backend_adapter = create_backend_adapter(self.tester.hybrid_backend)
            
            logger.info("✅ Atomic entity UPDATE test environment setup complete")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to setup test environment: {e}")
            traceback.print_exc()
            return False

    async def test_atomic_entity_update_basic(self) -> bool:
        """Test basic atomic KGEntity UPDATE operation."""
        try:
            logger.info("🧪 Testing basic atomic KGEntity UPDATE...")
            
            # Step 1: Create initial entity with frame and slot
            initial_entity = KGEntity()
            initial_entity.URI = "http://vital.ai/test/entity_update_basic"
            initial_entity.name = "Initial Entity"
            initial_entity.kGGraphURI = initial_entity.URI  # Entity-level grouping
            
            initial_frame = KGFrame()
            initial_frame.URI = "http://vital.ai/test/frame_update_basic"
            initial_frame.name = "Initial Frame"
            initial_frame.kGGraphURI = initial_entity.URI  # Belongs to entity
            
            initial_slot = KGTextSlot()
            initial_slot.URI = "http://vital.ai/test/slot_update_basic"
            initial_slot.textSlotValue = "Initial Value"
            initial_slot.kGGraphURI = initial_entity.URI  # Belongs to entity
            
            # Store initial entity graph
            initial_objects = [initial_entity, initial_frame, initial_slot]
            store_result = await self.backend_adapter.store_objects(
                self.space_id, self.graph_id, initial_objects
            )
            
            if not store_result.success:
                raise Exception(f"Failed to store initial entity: {store_result.message}")
            
            logger.info("✅ Initial entity created successfully")
            
            # Step 2: Update entity with new data using atomic UPDATE
            updated_entity = KGEntity()
            updated_entity.URI = initial_entity.URI  # Same URI for update
            updated_entity.name = "Updated Entity"
            updated_entity.kGGraphURI = updated_entity.URI
            
            updated_frame = KGFrame()
            updated_frame.URI = "http://vital.ai/test/frame_update_new"  # New frame URI
            updated_frame.name = "Updated Frame"
            updated_frame.kGGraphURI = updated_entity.URI
            
            updated_slot = KGDoubleSlot()
            updated_slot.URI = "http://vital.ai/test/slot_update_new"  # New slot URI
            updated_slot.doubleSlotValue = 42.5
            updated_slot.kGGraphURI = updated_entity.URI
            
            # Execute atomic UPDATE
            updated_objects = [updated_entity, updated_frame, updated_slot]
            update_result = await self.processor.update_entity(
                self.backend_adapter, self.space_id, self.graph_id,
                str(initial_entity.URI), updated_objects
            )
            
            if not update_result.updated_uri:
                raise Exception(f"Atomic entity UPDATE failed: {update_result.message}")
            
            logger.info("✅ Atomic entity UPDATE completed successfully")
            
            # Step 3: Verify update results by checking graph state
            subjects_query = f"""
            SELECT DISTINCT ?s WHERE {{
                GRAPH <{self.graph_id}> {{
                    ?s ?p ?o .
                }}
            }}
            """
            subjects_result = await self.backend_adapter.execute_sparql_query(self.space_id, subjects_query)
            
            # Extract subject URIs from results
            subject_uris = []
            if isinstance(subjects_result, list):
                for result in subjects_result:
                    if isinstance(result, dict) and 's' in result:
                        uri = result['s'].get('value', '') if isinstance(result['s'], dict) else str(result['s'])
                        if uri:
                            subject_uris.append(uri)
            
            # Check that old objects are gone and new objects exist
            old_frame_exists = str(initial_frame.URI) in subject_uris
            old_slot_exists = str(initial_slot.URI) in subject_uris
            new_frame_exists = str(updated_frame.URI) in subject_uris
            new_slot_exists = str(updated_slot.URI) in subject_uris
            entity_exists = str(updated_entity.URI) in subject_uris
            
            logger.info(f"🔍 Atomic UPDATE validation:")
            logger.info(f"  - Entity exists: {entity_exists}")
            logger.info(f"  - Old frame exists: {old_frame_exists}")
            logger.info(f"  - Old slot exists: {old_slot_exists}")
            logger.info(f"  - New frame exists: {new_frame_exists}")
            logger.info(f"  - New slot exists: {new_slot_exists}")
            
            if old_frame_exists or old_slot_exists:
                raise Exception("Old objects still exist after UPDATE - atomicity failed")
            
            if not entity_exists or not new_frame_exists or not new_slot_exists:
                raise Exception("New objects not found after UPDATE")
            
            logger.info("✅ Basic atomic entity UPDATE test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Basic atomic entity UPDATE test failed: {e}")
            traceback.print_exc()
            return False

    async def test_atomic_entity_update_with_validation(self) -> bool:
        """Test atomic entity UPDATE with existence validation."""
        try:
            logger.info("🧪 Testing atomic entity UPDATE with validation...")
            
            # Step 1: Create initial entity
            entity = KGEntity()
            entity.URI = "http://vital.ai/test/entity_validation"
            entity.name = "Entity for Validation"
            entity.kGGraphURI = entity.URI
            
            # Store initial entity
            store_result = await self.backend_adapter.store_objects(
                self.space_id, self.graph_id, [entity]
            )
            
            if not store_result.success:
                raise Exception("Failed to store initial entity")
            
            # Step 2: Verify entity exists before update
            exists = await self.processor.entity_exists(
                self.backend_adapter, self.space_id, self.graph_id, str(entity.URI)
            )
            
            if not exists:
                raise Exception("Entity existence validation failed")
            
            # Step 3: Update entity
            updated_entity = KGEntity()
            updated_entity.URI = entity.URI
            updated_entity.name = "Updated Entity with Validation"
            updated_entity.kGGraphURI = updated_entity.URI
            
            update_result = await self.processor.update_entity(
                self.backend_adapter, self.space_id, self.graph_id,
                str(entity.URI), [updated_entity]
            )
            
            if not update_result.updated_uri:
                raise Exception(f"Entity update failed: {update_result.message}")
            
            logger.info("✅ Atomic entity UPDATE with validation test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Atomic entity UPDATE with validation test failed: {e}")
            traceback.print_exc()
            return False

    async def test_atomic_entity_update_nonexistent(self) -> bool:
        """Test atomic entity UPDATE on non-existent entity."""
        try:
            logger.info("🧪 Testing atomic entity UPDATE on non-existent entity...")
            
            # Try to update non-existent entity
            nonexistent_entity = KGEntity()
            nonexistent_entity.URI = "http://vital.ai/test/entity_nonexistent"
            nonexistent_entity.name = "Non-existent Entity"
            nonexistent_entity.kGGraphURI = nonexistent_entity.URI
            
            update_result = await self.processor.update_entity(
                self.backend_adapter, self.space_id, self.graph_id,
                str(nonexistent_entity.URI), [nonexistent_entity]
            )
            
            # Should still succeed (atomic update will just insert if nothing to delete)
            if not update_result.updated_uri:
                raise Exception("Update of non-existent entity should succeed")
            
            logger.info("✅ Atomic entity UPDATE non-existent test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Atomic entity UPDATE non-existent test failed: {e}")
            traceback.print_exc()
            return False

    async def cleanup_test_environment(self):
        """Clean up test environment."""
        try:
            if self.tester:
                await self.tester.cleanup_resources()
            logger.info("✅ Test environment cleanup completed")
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")


async def run_atomic_entity_update_tests():
    """Run all atomic entity UPDATE tests."""
    logger.info("🎯 ATOMIC ENTITY UPDATE TEST SUITE")
    logger.info("=" * 60)
    
    test_suite = AtomicEntityUpdateTestSuite()
    
    try:
        # Setup test environment
        if not await test_suite.setup_test_environment():
            logger.error("💥 FAILED TO SETUP TEST ENVIRONMENT!")
            return False
        
        # Run tests
        tests = [
            ("Basic Atomic Entity UPDATE", test_suite.test_atomic_entity_update_basic),
            ("Atomic Entity UPDATE with Validation", test_suite.test_atomic_entity_update_with_validation),
            ("Atomic Entity UPDATE Non-existent", test_suite.test_atomic_entity_update_nonexistent),
        ]
        
        passed = 0
        failed = 0
        
        for test_name, test_func in tests:
            logger.info("=" * 60)
            logger.info(f"🧪 Running test: {test_name}")
            logger.info("=" * 60)
            
            if await test_func():
                logger.info(f"✅ {test_name}: PASSED")
                passed += 1
            else:
                logger.error(f"❌ {test_name}: FAILED")
                failed += 1
        
        # Summary
        logger.info("=" * 60)
        logger.info("🎯 ATOMIC ENTITY UPDATE TEST SUITE SUMMARY")
        logger.info("=" * 60)
        logger.info(f"✅ Passed: {passed}/{passed + failed}")
        logger.info(f"❌ Failed: {failed}/{passed + failed}")
        logger.info(f"📊 Success Rate: {(passed / (passed + failed) * 100):.1f}%")
        
        if failed == 0:
            logger.info("🎉 ALL ATOMIC ENTITY UPDATE TESTS PASSED!")
            return True
        else:
            logger.error("💥 SOME ATOMIC ENTITY UPDATE TESTS FAILED!")
            return False
            
    finally:
        await test_suite.cleanup_test_environment()


if __name__ == "__main__":
    asyncio.run(run_atomic_entity_update_tests())
