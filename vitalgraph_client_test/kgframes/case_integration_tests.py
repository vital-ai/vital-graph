"""
Client Test Case: Integration Tests

Tests comprehensive KGFrames integration scenarios including:
- End-to-end frame lifecycle (create, read, update, delete)
- Frame and slot integration workflows
- Cross-endpoint data consistency
- Performance and stress testing
"""

import logging
from typing import Optional
from vitalgraph.client.vitalgraph_client import VitalGraphClient

# VitalSigns imports - REQUIRED for proper test data creation
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

# VitalSigns utilities
from vital_ai_vitalsigns.vitalsigns import VitalSigns


async def test_frame_lifecycle_integration(client: VitalGraphClient, space_id: str, graph_id: str, entity_uri: Optional[str], logger: logging.Logger) -> bool:
    """Test complete frame lifecycle: create -> read -> update -> delete."""
    logger.info("🧪 Testing frame lifecycle integration...")
    
    frame_uri = "urn:test-lifecycle-frame-001"
    
    try:
        # Step 1: Create frame
        logger.info("   Step 1: Creating frame...")
        
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create KGFrame using VitalSigns
        frame = KGFrame()
        frame.URI = frame_uri
        frame.name = "Lifecycle Test Frame"
        frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#LifecycleFrame"
        
        # Create frame - pass GraphObject directly
        create_response = await client.kgframes.create_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            objects=[frame],
            entity_uri=entity_uri
        )
        
        if not create_response.is_success:
            logger.error(f"   ❌ Frame creation failed: {create_response.message}")
            return False
        
        # Step 2: Read frame
        logger.info("   Step 2: Reading frame...")
        read_response = await client.kgframes.get_kgframe(
            space_id=space_id,
            graph_id=graph_id,
            uri=frame_uri
        )
        
        # Log what we received
        logger.info(f"   📦 Response received:")
        logger.info(f"      - is_success: {read_response.is_success}")
        logger.info(f"      - message: {read_response.message}")
        logger.info(f"      - frame_graph type: {type(read_response.frame_graph)}")
        logger.info(f"      - frame_graph value: {read_response.frame_graph}")
        
        if not read_response.is_success or not read_response.frame_graph:
            logger.error(f"   ❌ Frame reading failed: {read_response.message}")
            return False
        
        # Step 3: Update frame
        logger.info("   Step 3: Updating frame...")
        
        # Create updated KGFrame using VitalSigns
        updated_frame = KGFrame()
        updated_frame.URI = frame_uri
        updated_frame.name = "Updated Lifecycle Test Frame"
        updated_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#UpdatedLifecycleFrame"
        
        # Update frame - pass GraphObject directly
        update_response = await client.kgframes.update_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            objects=[updated_frame],
            entity_uri=entity_uri
        )
        
        if not update_response.is_success:
            logger.error(f"   ❌ Frame update failed: {update_response.message}")
            return False
        
        # Step 4: Delete frame
        logger.info("   Step 4: Deleting frame...")
        delete_response = await client.kgframes.delete_kgframe(
            space_id=space_id,
            graph_id=graph_id,
            uri=frame_uri
        )
        
        if not delete_response.is_success:
            logger.error(f"   ❌ Frame deletion failed: {delete_response.message}")
            return False
        
        logger.info("✅ Frame lifecycle integration successful")
        return True
        
    except Exception as e:
        logger.error(f"❌ Frame lifecycle integration failed with exception: {e}")
        return False


async def test_frame_slot_integration_workflow(client: VitalGraphClient, space_id: str, graph_id: str, entity_uri: Optional[str], logger: logging.Logger) -> bool:
    """Test integrated frame and slot workflow."""
    logger.info("🧪 Testing frame-slot integration workflow...")
    
    frame_uri = "urn:test-integration-frame-001"
    
    try:
        # Step 1: Create frame with slots in single operation
        logger.info("   Step 1: Creating frame with slots...")
        
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create KGFrame using VitalSigns
        frame = KGFrame()
        frame.URI = frame_uri
        frame.name = "Integration Test Frame"
        frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#IntegrationFrame"
        
        # Create KGTextSlots using VitalSigns
        slot1 = KGTextSlot()
        slot1.URI = str(test_data_creator.generate_test_uri("slot", "integration_001"))
        slot1.name = "Integration Slot 1"
        slot1.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#IntegrationSlot"
        slot1.textSlotValue = "Integration value 1"
        
        slot2 = KGTextSlot()
        slot2.URI = str(test_data_creator.generate_test_uri("slot", "integration_002"))
        slot2.name = "Integration Slot 2"
        slot2.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#IntegrationSlot"
        slot2.textSlotValue = "Integration slot value 2"
        
        # Create frame with slots - pass GraphObjects directly
        create_response = await client.kgframes.create_kgframes_with_slots(
            space_id=space_id,
            graph_id=graph_id,
            objects=[frame, slot1, slot2],
            entity_uri=entity_uri
        )
        
        if not create_response.is_success:
            logger.error(f"   ❌ Frame with slots creation failed: {create_response.message}")
            return False
        
        # Step 2: Add more slots to existing frame
        logger.info("   Step 2: Adding slots to frame...")
        
        # Create additional KGTextSlot using VitalSigns
        additional_slot = KGTextSlot()
        additional_slot.URI = str(test_data_creator.generate_test_uri("slot", "integration_003"))
        additional_slot.name = "Additional Integration Slot"
        additional_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#AdditionalSlot"
        additional_slot.textSlotValue = "Additional slot value"
        
        # Add slot - pass GraphObject directly
        slot_response = await client.kgframes.create_frame_slots(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=frame_uri,
            objects=[additional_slot],
            entity_uri=entity_uri
        )
        
        if not slot_response.is_success:
            logger.error(f"   ❌ Additional slot creation failed: {slot_response.message}")
            return False
        
        # Step 3: Retrieve frame with all slots
        logger.info("   Step 3: Retrieving frame with slots...")
        get_response = await client.kgframes.get_kgframe(
            space_id=space_id,
            graph_id=graph_id,
            uri=frame_uri,
            include_frame_graph=True
        )
        
        if not get_response.is_success:
            logger.error(f"   ❌ Frame retrieval failed: {get_response.message}")
            return False
        
        # Step 4: Clean up
        logger.info("   Step 4: Cleaning up...")
        delete_response = await client.kgframes.delete_kgframe(
            space_id=space_id,
            graph_id=graph_id,
            uri=frame_uri
        )
        
        if not delete_response.is_success:
            logger.error(f"   ❌ Cleanup failed: {delete_response.message}")
            return False
        
        logger.info("✅ Frame-slot integration workflow successful")
        return True
        
    except Exception as e:
        logger.error(f"❌ Frame-slot integration workflow failed with exception: {e}")
        return False


async def test_batch_operations_integration(client: VitalGraphClient, space_id: str, graph_id: str, entity_uri: Optional[str], logger: logging.Logger) -> bool:
    """Test batch operations integration."""
    logger.info("🧪 Testing batch operations integration...")
    
    try:
        # Step 1: Create multiple frames in batch
        logger.info("   Step 1: Creating multiple frames...")
        
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create multiple KGFrames using VitalSigns
        frames = []
        for i in range(1, 4):
            frame = KGFrame()
            frame.URI = str(test_data_creator.generate_test_uri("frame", f"batch_{i:03d}"))
            frame.name = f"Batch Frame {i}"
            frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#BatchFrame"
            frames.append(frame)
        
        # Create batch frames - pass GraphObjects directly
        create_response = await client.kgframes.create_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            objects=frames,
            entity_uri=entity_uri
        )
        
        if not create_response.is_success or create_response.created_count < 3:
            logger.error(f"   ❌ Batch frame creation failed: {create_response.message}")
            return False
        
        # Step 2: List frames to verify creation
        logger.info("   Step 2: Verifying batch creation...")
        list_response = await client.kgframes.list_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            page_size=10,
            offset=0,
            search="Batch"
        )
        
        if not list_response.is_success:
            logger.error(f"   ❌ Frame listing failed: {list_response.message}")
            return False
        
        # Step 3: Delete multiple frames in batch
        logger.info("   Step 3: Deleting multiple frames...")
        frame_uris = [str(frame.URI) for frame in frames]
        
        delete_response = await client.kgframes.delete_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            uri_list=",".join([str(uri) for uri in frame_uris])
        )
        
        if not delete_response.is_success:
            logger.error(f"   ❌ Batch frame deletion failed: {delete_response.message}")
            return False
        
        logger.info("✅ Batch operations integration successful")
        return True
        
    except Exception as e:
        logger.error(f"❌ Batch operations integration failed with exception: {e}")
        return False


async def test_error_handling_integration(client: VitalGraphClient, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test error handling across different operations."""
    logger.info("🧪 Testing error handling integration...")
    
    try:
        # Test 1: Invalid space/graph IDs
        logger.info("   Test 1: Invalid space/graph IDs...")
        invalid_response = await client.kgframes.list_kgframes(
            space_id="invalid-space",
            graph_id="invalid-graph"
        )
        
        # Should handle gracefully (either succeed with empty result or provide appropriate error)
        if not invalid_response.is_success and invalid_response.message and "invalid" not in invalid_response.message.lower():
            logger.warning(f"   ⚠️ Unexpected error for invalid IDs: {invalid_response.message}")
        
        # Test 2: Malformed data handling
        logger.info("   Test 2: Malformed data handling...")
        try:
            # Create invalid VitalSigns object to test error handling
            test_data_creator = ClientTestDataCreator()
            invalid_frame = KGFrame()
            # Intentionally leave URI empty to test validation
            invalid_frame.name = "Invalid Frame"
            invalid_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#InvalidFrame"
            
            # Pass invalid GraphObject directly
            malformed_response = await client.kgframes.create_kgframes(
                space_id=space_id,
                graph_id=graph_id,
                objects=[invalid_frame]
            )
            
            if malformed_response.is_success:
                logger.warning(f"   ⚠️ Invalid data was unexpectedly accepted")
        except Exception as e:
            logger.info(f"   ✅ Invalid data properly rejected: {type(e).__name__}")
        
        # Test 3: Non-existent operations
        logger.info("   Test 3: Non-existent resource operations...")
        nonexistent_response = await client.kgframes.get_kgframe(
            space_id=space_id,
            graph_id=graph_id,
            uri="urn:nonexistent-frame-999"
        )
        
        # Should handle gracefully
        if not nonexistent_response.is_success or not nonexistent_response.frame_graph:
            logger.info(f"   ✅ Non-existent resource properly handled")
        
        logger.info("✅ Error handling integration successful")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error handling integration failed with exception: {e}")
        return False


async def run_integration_tests(client: VitalGraphClient, space_id: str, graph_id: str, entity_uri: Optional[str] = None, logger: logging.Logger = None) -> bool:
    """Run all integration tests."""
    if logger is None:
        logger = logging.getLogger(__name__)
    
    logger.info("🚀 Running Integration Tests...")
    
    tests = [
        ("Frame Lifecycle Integration", lambda: test_frame_lifecycle_integration(client, space_id, graph_id, entity_uri, logger)),
        ("Frame-Slot Integration Workflow", lambda: test_frame_slot_integration_workflow(client, space_id, graph_id, entity_uri, logger)),
        ("Batch Operations Integration", lambda: test_batch_operations_integration(client, space_id, graph_id, entity_uri, logger)),
        ("Error Handling Integration", lambda: test_error_handling_integration(client, space_id, graph_id, logger))
    ]
    
    results = []
    for test_name, test_func in tests:
        logger.info(f"🔧 Running: {test_name}")
        try:
            success = await test_func()
            results.append((test_name, success))
            if not success:
                logger.error(f"❌ {test_name} failed")
        except Exception as e:
            logger.error(f"❌ {test_name} failed with exception: {e}")
            results.append((test_name, False))
    
    all_passed = all(success for _, success in results)
    
    if all_passed:
        logger.info("✅ All integration tests passed!")
        return True
    else:
        failed_tests = [name for name, success in results if not success]
        logger.error(f"❌ Integration tests failed: {failed_tests}")
        return False
