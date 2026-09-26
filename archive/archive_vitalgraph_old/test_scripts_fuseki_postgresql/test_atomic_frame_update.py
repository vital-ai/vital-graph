#!/usr/bin/env python3
"""
Test module for atomic frame UPDATE functionality using the enhanced KGEntityFrameCreateProcessor.

This module validates the new atomic frame UPDATE operations that use the validated
update_quads function for true atomicity and consistency.

Location: /Users/hadfield/Local/vital-git/vital-graph/test_scripts/fuseki_postgresql/test_atomic_frame_update.py
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
from vitalgraph.kg_impl.kgentity_frame_create_impl import KGEntityFrameCreateProcessor
from test_fuseki_postgresql_endpoint_utils import FusekiPostgreSQLEndpointTester

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AtomicFrameUpdateTestSuite:
    """Test suite for atomic frame UPDATE functionality."""
    
    def __init__(self):
        self.tester = None
        self.backend_adapter = None
        self.space_id = None
        self.graph_id = "http://vital.ai/graph/test_atomic_frame_update"
        self.processor = KGEntityFrameCreateProcessor()

    async def setup_test_environment(self):
        """Set up test environment with hybrid backend."""
        try:
            logger.info("🔧 Setting up atomic frame UPDATE test environment...")
            
            # Initialize tester and backend
            self.tester = FusekiPostgreSQLEndpointTester()
            await self.tester.setup_hybrid_backend()
            
            # Create test space
            self.space_id = await self.tester.create_test_space("atomic_frame_update_test")
            
            # Create backend adapter
            self.backend_adapter = create_backend_adapter(self.tester.hybrid_backend)
            
            logger.info("✅ Atomic frame UPDATE test environment setup complete")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to setup test environment: {e}")
            traceback.print_exc()
            return False

    async def test_atomic_frame_update_basic(self) -> bool:
        """Test basic atomic frame UPDATE operation."""
        try:
            logger.info("🧪 Testing basic atomic frame UPDATE...")
            
            # Step 1: Create initial entity and frame
            entity = KGEntity()
            entity.URI = "http://vital.ai/test/entity_frame_update"
            entity.name = "Test Entity for Frame Update"
            
            # Store entity first
            await self.backend_adapter.store_objects(self.space_id, self.graph_id, [entity])
            
            # Step 2: Create initial frame with slots
            initial_frame = KGFrame()
            initial_frame.URI = "http://vital.ai/test/frame_update_initial"
            initial_frame.name = "Initial Frame"
            initial_frame.frameGraphURI = initial_frame.URI  # Frame-level grouping
            
            initial_slot = KGTextSlot()
            initial_slot.URI = "http://vital.ai/test/slot_update_initial"
            initial_slot.textSlotValue = "Initial Value"
            initial_slot.frameGraphURI = initial_frame.URI  # Belongs to frame
            
            # Create initial frame using CREATE mode
            result = await self.processor.create_entity_frame(
                self.backend_adapter, self.space_id, self.graph_id, 
                str(entity.URI), [initial_frame, initial_slot], "CREATE"
            )
            
            if not result.success:
                raise Exception(f"Failed to create initial frame: {result.message}")
            
            logger.info("✅ Initial frame created successfully")
            
            # Step 3: Update frame with new data using atomic UPDATE
            updated_frame = KGFrame()
            updated_frame.URI = initial_frame.URI  # Same URI for update
            updated_frame.name = "Updated Frame"
            updated_frame.frameGraphURI = updated_frame.URI
            
            updated_slot = KGTextSlot()
            updated_slot.URI = "http://vital.ai/test/slot_update_new"  # New slot URI
            updated_slot.textSlotValue = "Updated Value"
            updated_slot.frameGraphURI = updated_frame.URI
            
            new_slot = KGDoubleSlot()
            new_slot.URI = "http://vital.ai/test/slot_additional"
            new_slot.doubleSlotValue = 42.5
            new_slot.frameGraphURI = updated_frame.URI
            
            # Execute atomic UPDATE
            update_result = await self.processor.create_entity_frame(
                self.backend_adapter, self.space_id, self.graph_id,
                str(entity.URI), [updated_frame, updated_slot, new_slot], "UPDATE"
            )
            
            if not update_result.success:
                raise Exception(f"Atomic frame UPDATE failed: {update_result.message}")
            
            logger.info("✅ Atomic frame UPDATE completed successfully")
            
            # Step 4: Verify atomic UPDATE worked by checking the graph state
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
            
            old_slot_exists = str(initial_slot.URI) in subject_uris
            new_slot_exists = str(updated_slot.URI) in subject_uris
            additional_slot_exists = str(new_slot.URI) in subject_uris
            
            if old_slot_exists:
                raise Exception("Old slot still exists after UPDATE - atomicity failed")
            
            if not new_slot_exists:
                raise Exception("New slot not found after UPDATE")
                
            if not additional_slot_exists:
                raise Exception("Additional slot not found after UPDATE")
            
            logger.info("✅ Basic atomic frame UPDATE test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Basic atomic frame UPDATE test failed: {e}")
            traceback.print_exc()
            return False

    async def test_atomic_frame_upsert_new_frame(self) -> bool:
        """Test atomic frame UPSERT with new frame (should create)."""
        try:
            logger.info("🧪 Testing atomic frame UPSERT with new frame...")
            
            # Step 1: Create entity
            entity = KGEntity()
            entity.URI = "http://vital.ai/test/entity_upsert_new"
            entity.name = "Test Entity for UPSERT New"
            
            await self.backend_adapter.store_objects(self.space_id, self.graph_id, [entity])
            
            # Step 2: UPSERT a new frame (should create)
            new_frame = KGFrame()
            new_frame.URI = "http://vital.ai/test/frame_upsert_new"
            new_frame.name = "New Frame via UPSERT"
            new_frame.frameGraphURI = new_frame.URI
            
            new_slot = KGTextSlot()
            new_slot.URI = "http://vital.ai/test/slot_upsert_new"
            new_slot.textSlotValue = "UPSERT New Value"
            new_slot.frameGraphURI = new_frame.URI
            
            # Execute UPSERT (should create since frame doesn't exist)
            result = await self.processor.create_entity_frame(
                self.backend_adapter, self.space_id, self.graph_id,
                str(entity.URI), [new_frame, new_slot], "UPSERT"
            )
            
            if not result.success:
                raise Exception(f"UPSERT new frame failed: {result.message}")
            
            # Verify frame was created using SPARQL query
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
            
            frame_exists = str(new_frame.URI) in subject_uris
            slot_exists = str(new_slot.URI) in subject_uris
            
            if not frame_exists or not slot_exists:
                raise Exception("UPSERT failed to create new frame and slot")
            
            logger.info("✅ Atomic frame UPSERT new frame test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Atomic frame UPSERT new frame test failed: {e}")
            traceback.print_exc()
            return False

    async def test_atomic_frame_upsert_existing_frame(self) -> bool:
        """Test atomic frame UPSERT with existing frame (should update)."""
        try:
            logger.info("🧪 Testing atomic frame UPSERT with existing frame...")
            
            # Step 1: Create entity and initial frame
            entity = KGEntity()
            entity.URI = "http://vital.ai/test/entity_upsert_existing"
            entity.name = "Test Entity for UPSERT Existing"
            
            await self.backend_adapter.store_objects(self.space_id, self.graph_id, [entity])
            
            # Create initial frame
            initial_frame = KGFrame()
            initial_frame.URI = "http://vital.ai/test/frame_upsert_existing"
            initial_frame.name = "Initial Frame for UPSERT"
            initial_frame.frameGraphURI = initial_frame.URI
            
            initial_slot = KGTextSlot()
            initial_slot.URI = "http://vital.ai/test/slot_upsert_initial"
            initial_slot.textSlotValue = "Initial UPSERT Value"
            initial_slot.frameGraphURI = initial_frame.URI
            
            # Create initial frame
            create_result = await self.processor.create_entity_frame(
                self.backend_adapter, self.space_id, self.graph_id,
                str(entity.URI), [initial_frame, initial_slot], "CREATE"
            )
            
            if not create_result.success:
                raise Exception("Failed to create initial frame for UPSERT test")
            
            # Step 2: UPSERT existing frame (should update)
            updated_frame = KGFrame()
            updated_frame.URI = initial_frame.URI  # Same URI
            updated_frame.name = "Updated Frame via UPSERT"
            updated_frame.frameGraphURI = updated_frame.URI
            
            updated_slot = KGTextSlot()
            updated_slot.URI = "http://vital.ai/test/slot_upsert_updated"  # Different slot
            updated_slot.textSlotValue = "Updated UPSERT Value"
            updated_slot.frameGraphURI = updated_frame.URI
            
            # Execute UPSERT (should update since frame exists)
            upsert_result = await self.processor.create_entity_frame(
                self.backend_adapter, self.space_id, self.graph_id,
                str(entity.URI), [updated_frame, updated_slot], "UPSERT"
            )
            
            if not upsert_result.success:
                raise Exception(f"UPSERT existing frame failed: {upsert_result.message}")
            
            # Verify atomic UPDATE worked by checking the graph state
            # Query for subjects to validate the atomic operation
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
            
            old_slot_exists = str(initial_slot.URI) in subject_uris
            new_slot_exists = str(updated_slot.URI) in subject_uris
            
            logger.info(f"🔍 Atomic UPDATE validation:")
            logger.info(f"  - Total subjects in graph: {len(subject_uris)}")
            logger.info(f"  - Old slot exists: {old_slot_exists} (URI: {initial_slot.URI})")
            logger.info(f"  - New slot exists: {new_slot_exists} (URI: {updated_slot.URI})")
            
            if old_slot_exists:
                raise Exception("Old slot still exists after UPSERT - atomicity failed")
                
            if not new_slot_exists:
                raise Exception("New slot not found after UPSERT")
            
            logger.info("✅ Atomic frame UPSERT existing frame test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Atomic frame UPSERT existing frame test failed: {e}")
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


async def run_atomic_frame_update_tests():
    """Run all atomic frame UPDATE tests."""
    logger.info("🎯 ATOMIC FRAME UPDATE TEST SUITE")
    logger.info("=" * 60)
    
    test_suite = AtomicFrameUpdateTestSuite()
    
    try:
        # Setup test environment
        if not await test_suite.setup_test_environment():
            logger.error("💥 FAILED TO SETUP TEST ENVIRONMENT!")
            return False
        
        # Run tests
        tests = [
            ("Basic Atomic Frame UPDATE", test_suite.test_atomic_frame_update_basic),
            ("Atomic Frame UPSERT New", test_suite.test_atomic_frame_upsert_new_frame),
            ("Atomic Frame UPSERT Existing", test_suite.test_atomic_frame_upsert_existing_frame),
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
        logger.info("🎯 ATOMIC FRAME UPDATE TEST SUITE SUMMARY")
        logger.info("=" * 60)
        logger.info(f"✅ Passed: {passed}/{passed + failed}")
        logger.info(f"❌ Failed: {failed}/{passed + failed}")
        logger.info(f"📊 Success Rate: {(passed / (passed + failed) * 100):.1f}%")
        
        if failed == 0:
            logger.info("🎉 ALL ATOMIC FRAME UPDATE TESTS PASSED!")
            return True
        else:
            logger.error("💥 SOME ATOMIC FRAME UPDATE TESTS FAILED!")
            return False
            
    finally:
        await test_suite.cleanup_test_environment()


if __name__ == "__main__":
    asyncio.run(run_atomic_frame_update_tests())
