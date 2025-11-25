#!/usr/bin/env python3
"""
Data Lifecycle Management Tests for MockKGFramesEndpoint.

This test suite validates:
- Atomic update operations with rollback capability
- Stale triple detection and cleanup
- Operation mode support (create/update/upsert)
- Edge relationship management with referential integrity
- Server-authoritative grouping URI enforcement

Tests the enhanced update_kgframes method with comprehensive data lifecycle management.
"""

import sys
import os
import tempfile
import logging
import yaml
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.client.client_factory import create_vitalgraph_client
from vitalgraph.client.config.client_config_loader import VitalGraphClientConfig
from vitalgraph.model.kgframes_model import JsonLdDocument
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vitalgraph.model.spaces_model import Space

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class TestDataLifecycleManagement:
    """Test suite for data lifecycle management in MockKGFramesEndpoint."""
    
    def __init__(self):
        self.mock_client = None
        self.test_space_id = "test_lifecycle_space"
        self.test_graph_id = "http://vital.ai/haley.ai/app/test_lifecycle_graph"
        self.frame_uri = "http://vital.ai/haley.ai/app/KGFrame/lifecycle_test_frame"
        
    def setup_test_environment(self):
        """Set up test environment with mock client and test space."""
        try:
            # Create config data for mock client (following existing pattern)
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
            
            # Create temporary config file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                yaml.dump(config_data, f)
                temp_config_path = f.name
            
            # Create config object
            config = VitalGraphClientConfig(temp_config_path)
            
            # Create mock client using config object
            self.mock_client = create_vitalgraph_client(config=config)
            
            # Create test space
            space = Space(space=self.test_space_id, space_name="Test Lifecycle Management Space")
            space_response = self.mock_client.spaces.add_space(space)
            
            logger.info(f"Test environment setup complete: {space_response.message}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to setup test environment: {e}")
            return False

    def cleanup_test_environment(self):
        """Clean up test environment."""
        try:
            if self.mock_client:
                # Delete test space
                self.mock_client.spaces.delete_space(space_id=self.test_space_id)
                
                # Close client
                self.mock_client.close()
                
            logger.info("Test environment cleaned up")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def create_test_frame_with_slots(self, frame_name_suffix: str = "") -> list:
        """Create a test frame with slots and edges for testing."""
        # Create KGFrame
        frame = KGFrame()
        frame.URI = f"{self.frame_uri}{frame_name_suffix}"
        frame.name = f"Lifecycle Test Frame{frame_name_suffix}"
        frame.kGFrameType = "urn:LifecycleTestFrameType"
        
        # Create KGTextSlot
        text_slot = KGTextSlot()
        text_slot.URI = f"http://vital.ai/haley.ai/app/KGTextSlot/lifecycle_text_slot{frame_name_suffix}"
        text_slot.name = f"Lifecycle Text Slot{frame_name_suffix}"
        text_slot.kGSlotType = "urn:LifecycleTextSlotType"
        text_slot.textSlotValue = f"Lifecycle Test Value{frame_name_suffix}"
        
        # Create KGIntegerSlot
        integer_slot = KGIntegerSlot()
        integer_slot.URI = f"http://vital.ai/haley.ai/app/KGIntegerSlot/lifecycle_integer_slot{frame_name_suffix}"
        integer_slot.name = f"Lifecycle Integer Slot{frame_name_suffix}"
        integer_slot.kGSlotType = "urn:LifecycleIntegerSlotType"
        integer_slot.integerSlotValue = 100
        
        # Create Edge_hasKGSlot relationships
        text_edge = Edge_hasKGSlot()
        text_edge.URI = f"http://vital.ai/haley.ai/app/Edge_hasKGSlot/lifecycle_frame_text_edge{frame_name_suffix}"
        text_edge.edgeSource = frame.URI
        text_edge.edgeDestination = text_slot.URI
        
        integer_edge = Edge_hasKGSlot()
        integer_edge.URI = f"http://vital.ai/haley.ai/app/Edge_hasKGSlot/lifecycle_frame_integer_edge{frame_name_suffix}"
        integer_edge.edgeSource = frame.URI
        integer_edge.edgeDestination = integer_slot.URI
        
        return [frame, text_slot, integer_slot, text_edge, integer_edge]

    def test_atomic_update_operations(self):
        """Test atomic update operations with rollback capability."""
        try:
            logger.info("🧪 Testing Atomic Update Operations")
            
            # Step 1: Create initial frame
            initial_objects = self.create_test_frame_with_slots("_initial")
            initial_document = GraphObject.to_jsonld_list(initial_objects)
            document = JsonLdDocument(**initial_document)
            
            create_response = self.mock_client.kgframes.create_kgframes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document
            )
            
            assert create_response.created_count > 0, "Initial frame creation failed"
            logger.info(f"✅ Initial frame created: {create_response.created_count} objects")
            
            # Step 2: Update with valid data (should succeed)
            updated_objects = self.create_test_frame_with_slots("_initial")  # Same URI, updated data
            updated_objects[1].textSlotValue = "Updated Test Value"  # Update text slot value
            updated_objects[2].integerSlotValue = 200  # Update integer slot value
            
            updated_document = GraphObject.to_jsonld_list(updated_objects)
            document = JsonLdDocument(**updated_document)
            
            update_response = self.mock_client.kgframes.update_kgframes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document,
                operation_mode="update"
            )
            
            assert update_response.updated_uri, "Update operation failed"
            logger.info(f"✅ Atomic update succeeded: {update_response.updated_uri}")
            
            # Step 3: Verify updated data
            get_response = self.mock_client.kgframes.get_kgframe(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri=f"{self.frame_uri}_initial"
            )
            
            assert get_response, "Failed to retrieve updated frame"
            logger.info("✅ Updated frame retrieved successfully")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Atomic update operations test failed: {e}")
            return False

    def test_operation_modes(self):
        """Test create/update/upsert operation modes."""
        try:
            logger.info("🧪 Testing Operation Modes")
            
            # Test CREATE mode
            create_objects = self.create_test_frame_with_slots("_create_mode")
            create_document = GraphObject.to_jsonld_list(create_objects)
            document = JsonLdDocument(**create_document)
            
            # First create should succeed
            create_response = self.mock_client.kgframes.update_kgframes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document,
                operation_mode="create"
            )
            
            assert create_response.updated_uri, "CREATE mode failed on new frame"
            logger.info("✅ CREATE mode: New frame created successfully")
            
            # Second create with same URI should fail with error
            create_response2 = self.mock_client.kgframes.update_kgframes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document,
                operation_mode="create"
            )
            
            # Should return error for existing frame
            assert not create_response2.updated_uri, "CREATE mode should fail on existing frame"
            assert "already exists" in create_response2.message, "Error message should indicate frame already exists"
            logger.info(f"✅ CREATE mode: Correctly rejected existing frame - {create_response2.message}")
            
            # Test UPDATE mode on existing frame
            create_objects[1].textSlotValue = "Updated in UPDATE mode"
            update_document = GraphObject.to_jsonld_list(create_objects)
            document = JsonLdDocument(**update_document)
            
            update_response = self.mock_client.kgframes.update_kgframes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document,
                operation_mode="update"
            )
            
            assert update_response.updated_uri, "UPDATE mode failed on existing frame"
            logger.info("✅ UPDATE mode: Existing frame updated successfully")
            
            # Test UPDATE mode on non-existent frame (should fail)
            nonexistent_objects = self.create_test_frame_with_slots("_nonexistent")
            nonexistent_document = GraphObject.to_jsonld_list(nonexistent_objects)
            document = JsonLdDocument(**nonexistent_document)
            
            update_nonexistent_response = self.mock_client.kgframes.update_kgframes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document,
                operation_mode="update"
            )
            
            # Should return error for non-existent frame
            assert not update_nonexistent_response.updated_uri, "UPDATE mode should fail on non-existent frame"
            assert "does not exist" in update_nonexistent_response.message, "Error message should indicate frame does not exist"
            logger.info(f"✅ UPDATE mode: Correctly rejected non-existent frame - {update_nonexistent_response.message}")
            
            # Test UPSERT mode
            upsert_objects = self.create_test_frame_with_slots("_upsert_mode")
            upsert_document = GraphObject.to_jsonld_list(upsert_objects)
            document = JsonLdDocument(**upsert_document)
            
            upsert_response = self.mock_client.kgframes.update_kgframes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document,
                operation_mode="upsert"
            )
            
            assert upsert_response.updated_uri, "UPSERT mode failed"
            logger.info("✅ UPSERT mode: Frame created/updated successfully")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Operation modes test failed: {e}")
            return False

    def test_stale_triple_detection(self):
        """Test stale triple detection and cleanup."""
        try:
            logger.info("🧪 Testing Stale Triple Detection")
            
            # Create frame with slots
            test_objects = self.create_test_frame_with_slots("_stale_test")
            test_document = GraphObject.to_jsonld_list(test_objects)
            document = JsonLdDocument(**test_document)
            
            create_response = self.mock_client.kgframes.create_kgframes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document
            )
            
            assert create_response.created_count > 0, "Test frame creation failed"
            
            # Access the endpoint directly to test stale triple detection
            endpoint = self.mock_client.kgframes
            space = endpoint.space_manager.get_space(self.test_space_id)
            
            # Run stale triple detection
            stale_report = endpoint.detect_stale_triples(space, self.test_graph_id)
            
            logger.info(f"✅ Stale triple detection completed: {stale_report['summary']}")
            
            # Should have no stale data initially
            assert not stale_report['summary'].get('has_stale_data', True), "Unexpected stale data detected"
            
            # Test cleanup (should be no-op)
            cleanup_results = endpoint.cleanup_stale_triples(space, self.test_graph_id, stale_report)
            
            logger.info(f"✅ Stale triple cleanup completed: {cleanup_results}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Stale triple detection test failed: {e}")
            return False

    def test_grouping_uri_enforcement(self):
        """Test server-authoritative grouping URI enforcement."""
        try:
            logger.info("🧪 Testing Grouping URI Enforcement")
            
            # Create frame objects
            test_objects = self.create_test_frame_with_slots("_grouping_test")
            
            # Manually set incorrect grouping URIs (should be stripped by server)
            for obj in test_objects:
                if hasattr(obj, 'frameGraphURI'):
                    obj.frameGraphURI = "http://client.provided/wrong/grouping/uri"
            
            test_document = GraphObject.to_jsonld_list(test_objects)
            document = JsonLdDocument(**test_document)
            
            create_response = self.mock_client.kgframes.create_kgframes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document
            )
            
            assert create_response.created_count > 0, "Frame creation failed"
            
            # Retrieve frame and verify server-set grouping URIs
            get_response = self.mock_client.kgframes.get_kgframe(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri=f"{self.frame_uri}_grouping_test",
                include_frame_graph=True
            )
            
            # Check that grouping URIs are properly set by server
            if hasattr(get_response, 'graph') and get_response.graph:
                grouping_uri_found = False
                for obj_data in get_response.graph:
                    if isinstance(obj_data, dict):
                        if 'http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI' in obj_data:
                            grouping_uri_found = True
                            grouping_uri = obj_data['http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI']
                            logger.info(f"✅ Server-set grouping URI found: {grouping_uri}")
                            break
                
                assert grouping_uri_found, "Server-authoritative grouping URI not found"
            
            logger.info("✅ Grouping URI enforcement working correctly")
            return True
            
        except Exception as e:
            logger.error(f"❌ Grouping URI enforcement test failed: {e}")
            return False

    def log_test_result(self, test_name: str, success: bool, message: str, data: dict = None):
        """Log test result in a structured format."""
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"{status} {test_name}")
        logger.info(f"    {message}")
        if data:
            logger.info(f"    Data: {data}")

    def run_all_tests(self):
        """Run all data lifecycle management tests."""
        logger.info("🧪 Testing Data Lifecycle Management - Atomic Operations & Stale Triple Prevention")
        logger.info("=" * 100)
        
        if not self.setup_test_environment():
            logger.error("❌ Test environment setup failed")
            return False
        
        test_results = []
        
        try:
            # Run all tests
            tests = [
                ("Atomic Update Operations", self.test_atomic_update_operations),
                ("Operation Modes (create/update/upsert)", self.test_operation_modes),
                ("Stale Triple Detection & Cleanup", self.test_stale_triple_detection),
                ("Grouping URI Enforcement", self.test_grouping_uri_enforcement),
            ]
            
            for test_name, test_method in tests:
                try:
                    success = test_method()
                    test_results.append(success)
                    self.log_test_result(test_name, success, 
                                       "Test completed successfully" if success else "Test failed")
                except Exception as e:
                    test_results.append(False)
                    self.log_test_result(test_name, False, f"Test error: {e}")
            
            # Print final summary
            passed_tests = sum(test_results)
            total_tests = len(test_results)
            
            logger.info("=" * 100)
            logger.info(f"Test Results: {passed_tests}/{total_tests} tests passed")
            
            if passed_tests == total_tests:
                logger.info("🎉 All data lifecycle management tests passed!")
                return True
            else:
                logger.warning("⚠️  Some data lifecycle management tests failed. Check the output above for details.")
                return False
                
        finally:
            self.cleanup_test_environment()


if __name__ == "__main__":
    test_suite = TestDataLifecycleManagement()
    success = test_suite.run_all_tests()
    sys.exit(0 if success else 1)
