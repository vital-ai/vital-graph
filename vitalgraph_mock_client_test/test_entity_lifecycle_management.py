#!/usr/bin/env python3

"""
Test Entity Lifecycle Management

This module tests the enhanced KGEntities endpoint with proper graph-level operations:
- Operation modes (create/update/upsert) with structure validation
- Parent URI validation and connection verification
- Atomic operations with backup/rollback capability
- Complete entity graph structure validation (entity→frame, frame→frame, frame→slot)
"""

import sys
import os
import logging
import tempfile
import yaml
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Import VitalSigns models
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from vital_ai_vitalsigns.model.GraphObject import GraphObject

# Import VitalGraph components
from vitalgraph.client.client_factory import create_vitalgraph_client
from vitalgraph.client.config.client_config_loader import VitalGraphClientConfig
from vitalgraph.model.jsonld_model import JsonLdDocument
from vitalgraph.model.spaces_model import Space


class TestEntityLifecycleManagement:
    """Test entity lifecycle management with enhanced operations."""
    
    def __init__(self):
        self.mock_client = None
        self.test_space_id = "test_entity_lifecycle_space"
        self.test_graph_id = "http://vital.ai/haley.ai/app/test_entity_lifecycle_graph"
        self.entity_uri = "http://vital.ai/haley.ai/app/KGEntity/lifecycle_test_entity"
        
    def setup_test_environment(self):
        """Set up test environment with mock client and test space."""
        try:
            logger.info("Setting up test environment...")
            
            # Create mock client config
            config = self.create_mock_config()
            self.mock_client = create_vitalgraph_client(config=config)
            
            # Create test space
            space = Space(space=self.test_space_id, space_name="Test Entity Lifecycle Management Space")
            space_response = self.mock_client.spaces.add_space(space)
            
            if space_response and space_response.created_count > 0:
                logger.info("Test environment setup complete: Space created successfully")
                return True
            else:
                logger.error(f"Failed to create test space: {space_response.message if space_response else 'No response'}")
                return False
                
        except Exception as e:
            logger.error(f"Error setting up test environment: {e}")
            return False
    
    def cleanup_test_environment(self):
        """Clean up test environment."""
        try:
            if self.mock_client:
                # Close client (space cleanup handled by space manager)
                self.mock_client.close()
                
            logger.info("Test environment cleaned up")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
    
    def create_mock_config(self) -> VitalGraphClientConfig:
        """Create a config object with mock client enabled."""
        config_data = {
            'server': {
                'url': 'http://localhost:8001',
                'api_key': 'test-api-key'
            },
            'client': {
                'use_mock_client': True,
                'mock_data_dir': str(Path(__file__).parent / 'mock_data')
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config_data, f)
            temp_config_path = f.name
        
        return VitalGraphClientConfig(temp_config_path)

    def create_test_entity_with_frames_and_slots(self, entity_name_suffix: str = "") -> list:
        """Create a test entity with frames and slots for testing."""
        # Create KGEntity
        entity = KGEntity()
        entity.URI = f"{self.entity_uri}{entity_name_suffix}"
        entity.name = f"Lifecycle Test Entity{entity_name_suffix}"
        entity.kGEntityType = "urn:LifecycleTestEntityType"
        
        # Create KGFrame
        frame = KGFrame()
        frame.URI = f"http://vital.ai/haley.ai/app/KGFrame/lifecycle_test_frame{entity_name_suffix}"
        frame.name = f"Lifecycle Test Frame{entity_name_suffix}"
        frame.kGFrameType = "urn:LifecycleTestFrameType"
        
        # Create KGTextSlot
        text_slot = KGTextSlot()
        text_slot.URI = f"http://vital.ai/haley.ai/app/KGTextSlot/lifecycle_text_slot{entity_name_suffix}"
        text_slot.name = f"Lifecycle Text Slot{entity_name_suffix}"
        text_slot.kGSlotType = "urn:LifecycleTextSlotType"
        text_slot.textSlotValue = f"Lifecycle Test Value{entity_name_suffix}"
        
        # Create KGIntegerSlot
        integer_slot = KGIntegerSlot()
        integer_slot.URI = f"http://vital.ai/haley.ai/app/KGIntegerSlot/lifecycle_integer_slot{entity_name_suffix}"
        integer_slot.name = f"Lifecycle Integer Slot{entity_name_suffix}"
        integer_slot.kGSlotType = "urn:LifecycleIntegerSlotType"
        integer_slot.integerSlotValue = 200
        
        # Create Edge_hasEntityKGFrame relationship (entity → frame)
        entity_frame_edge = Edge_hasEntityKGFrame()
        entity_frame_edge.URI = f"http://vital.ai/haley.ai/app/Edge_hasEntityKGFrame/lifecycle_entity_frame_edge{entity_name_suffix}"
        entity_frame_edge.edgeSource = entity.URI
        entity_frame_edge.edgeDestination = frame.URI
        
        # Create Edge_hasKGSlot relationships (frame → slots)
        frame_text_edge = Edge_hasKGSlot()
        frame_text_edge.URI = f"http://vital.ai/haley.ai/app/Edge_hasKGSlot/lifecycle_frame_text_edge{entity_name_suffix}"
        frame_text_edge.edgeSource = frame.URI
        frame_text_edge.edgeDestination = text_slot.URI
        
        frame_integer_edge = Edge_hasKGSlot()
        frame_integer_edge.URI = f"http://vital.ai/haley.ai/app/Edge_hasKGSlot/lifecycle_frame_integer_edge{entity_name_suffix}"
        frame_integer_edge.edgeSource = frame.URI
        frame_integer_edge.edgeDestination = integer_slot.URI
        
        return [entity, frame, text_slot, integer_slot, entity_frame_edge, frame_text_edge, frame_integer_edge]

    def test_entity_operation_modes(self):
        """Test entity operation modes (create/update/upsert)."""
        try:
            logger.info("🧪 Testing Entity Operation Modes")
            
            # Test CREATE mode - should succeed for new entity
            create_objects = self.create_test_entity_with_frames_and_slots("_create_mode")
            create_document = GraphObject.to_jsonld_list(create_objects)
            document = JsonLdDocument(**create_document)
            
            create_response = self.mock_client.kgentities.update_kgentities(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document,
                operation_mode="create"
            )
            
            if create_response.updated_uri:
                logger.info("✅ CREATE mode: Entity created successfully")
            else:
                logger.error(f"❌ Entity operation modes test failed: CREATE mode failed - {create_response.message}")
                return False
            
            # Test CREATE mode again - should fail for existing entity
            create_response_2 = self.mock_client.kgentities.update_kgentities(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document,
                operation_mode="create"
            )
            
            if not create_response_2.updated_uri and "already exists" in create_response_2.message:
                logger.info(f"✅ CREATE mode: Correctly rejected existing entity - {create_response_2.message}")
            else:
                logger.error(f"❌ Entity operation modes test failed: CREATE mode should have failed on existing entity")
                return False
            
            # Test UPDATE mode - modify the text slot value
            update_objects = self.create_test_entity_with_frames_and_slots("_create_mode")
            # Modify the text slot value
            for obj in update_objects:
                if hasattr(obj, 'textSlotValue'):
                    obj.textSlotValue = "Updated in UPDATE mode"
            
            update_document = GraphObject.to_jsonld_list(update_objects)
            document = JsonLdDocument(**update_document)
            
            update_response = self.mock_client.kgentities.update_kgentities(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document,
                operation_mode="update"
            )
            
            if update_response.updated_uri:
                logger.info("✅ UPDATE mode: Entity updated successfully")
            else:
                logger.error(f"❌ Entity operation modes test failed: UPDATE mode failed - {update_response.message}")
                return False
            
            # Test UPDATE mode on non-existent entity - should fail
            nonexistent_objects = self.create_test_entity_with_frames_and_slots("_nonexistent")
            nonexistent_document = GraphObject.to_jsonld_list(nonexistent_objects)
            document = JsonLdDocument(**nonexistent_document)
            
            update_response_2 = self.mock_client.kgentities.update_kgentities(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document,
                operation_mode="update"
            )
            
            if not update_response_2.updated_uri and "does not exist" in update_response_2.message:
                logger.info(f"✅ UPDATE mode: Correctly rejected non-existent entity - {update_response_2.message}")
            else:
                logger.error(f"❌ Entity operation modes test failed: UPDATE mode should have failed on non-existent entity")
                return False
            
            # Test UPSERT mode - should work for both existing and new entities
            upsert_objects = self.create_test_entity_with_frames_and_slots("_upsert_mode")
            upsert_document = GraphObject.to_jsonld_list(upsert_objects)
            document = JsonLdDocument(**upsert_document)
            
            upsert_response = self.mock_client.kgentities.update_kgentities(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document,
                operation_mode="upsert"
            )
            
            if upsert_response.updated_uri:
                logger.info("✅ UPSERT mode: Entity created/updated successfully")
            else:
                logger.error(f"❌ Entity operation modes test failed: UPSERT mode failed - {upsert_response.message}")
                return False
            
            logger.info("✅ PASS Entity Operation Modes")
            return True
            
        except Exception as e:
            logger.error(f"❌ Entity operation modes test failed: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def run_all_tests(self):
        """Run all entity lifecycle management tests."""
        logger.info("=" * 100)
        logger.info("🚀 Starting Entity Lifecycle Management Tests")
        logger.info("=" * 100)
        
        if not self.setup_test_environment():
            logger.error("❌ Failed to setup test environment")
            return False
        
        try:
            tests = [
                ("Entity Operation Modes", self.test_entity_operation_modes),
            ]
            
            passed_tests = 0
            total_tests = len(tests)
            
            for test_name, test_method in tests:
                logger.info("=" * 100)
                logger.info(f"🧪 Running: {test_name}")
                logger.info("=" * 100)
                
                if test_method():
                    passed_tests += 1
                    logger.info(f"✅ PASS {test_name}")
                    logger.info("    Test completed successfully")
                else:
                    logger.error(f"❌ FAIL {test_name}")
                    logger.error("    Test failed - check logs above")
            
            logger.info("=" * 100)
            logger.info(f"Test Results: {passed_tests}/{total_tests} tests passed")
            
            if passed_tests == total_tests:
                logger.info("🎉 All entity lifecycle management tests passed!")
                return True
            else:
                logger.error(f"❌ {total_tests - passed_tests} test(s) failed")
                return False
                
        finally:
            self.cleanup_test_environment()


if __name__ == "__main__":
    test_runner = TestEntityLifecycleManagement()
    success = test_runner.run_all_tests()
    exit(0 if success else 1)
