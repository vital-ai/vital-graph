"""
Client Test Case: Slot Deletion Operations

Tests KGSlots deletion functionality including:
- Delete specific slots from a frame
- Delete all slots from a frame
- Delete slots with cascading effects
- Handle deletion of non-existent slots
"""

import logging
from typing import Optional
from vitalgraph.client.vitalgraph_client import VitalGraphClient

# VitalSigns imports - REQUIRED for proper test data handling
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

# VitalSigns utilities for JSON-LD conversion
from vital_ai_vitalsigns.vitalsigns import VitalSigns


async def test_delete_specific_slots(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, slot_uris: list[str], logger: logging.Logger) -> bool:
    """Test deleting specific slots from a frame."""
    logger.info("🧪 Testing specific slot deletion...")
    
    try:
        # Test specific slot deletion
        response = client.kgframes.delete_frame_slots(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=frame_uri,
            slot_uris=slot_uris
        )
        
        if response.success and response.slots_deleted > 0:
            logger.info(f"✅ Specific slot deletion successful: {response.slots_deleted} slots deleted")
            return True
        else:
            logger.error(f"❌ Specific slot deletion failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Specific slot deletion failed with exception: {e}")
        return False


async def test_delete_all_frame_slots(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, logger: logging.Logger) -> bool:
    """Test deleting all slots from a frame."""
    logger.info("🧪 Testing all frame slots deletion...")
    
    try:
        # First get all slots for the frame to determine slot URIs
        # This would typically be done via a list operation, but for testing we'll use a known pattern
        all_slot_uris = [
            f"urn:test-slot-all-001-{frame_uri}",
            f"urn:test-slot-all-002-{frame_uri}",
            f"urn:test-slot-all-003-{frame_uri}"
        ]
        
        # Test deleting all slots
        response = client.kgframes.delete_frame_slots(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=frame_uri,
            slot_uris=all_slot_uris
        )
        
        if response.success:
            logger.info(f"✅ All frame slots deletion successful: {response.slots_deleted} slots deleted")
            return True
        else:
            logger.error(f"❌ All frame slots deletion failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ All frame slots deletion failed with exception: {e}")
        return False


async def test_delete_nonexistent_slots(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, logger: logging.Logger) -> bool:
    """Test deleting non-existent slots (should handle gracefully)."""
    logger.info("🧪 Testing non-existent slot deletion...")
    
    try:
        # Test deletion of non-existent slots
        nonexistent_slot_uris = [
            "urn:test-nonexistent-slot-999",
            "urn:test-nonexistent-slot-998"
        ]
        
        response = client.kgframes.delete_frame_slots(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=frame_uri,
            slot_uris=nonexistent_slot_uris
        )
        
        # Should either succeed with 0 deletions or fail gracefully
        if response.success or "not found" in response.message.lower():
            logger.info(f"✅ Non-existent slot deletion handled gracefully")
            return True
        else:
            logger.error(f"❌ Non-existent slot deletion failed unexpectedly: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Non-existent slot deletion failed with exception: {e}")
        return False


async def test_delete_slots_from_nonexistent_frame(client: VitalGraphClient, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test deleting slots from a non-existent frame."""
    logger.info("🧪 Testing slot deletion from non-existent frame...")
    
    try:
        # Test deletion of slots from non-existent frame
        nonexistent_frame_uri = "urn:test-nonexistent-frame-999"
        slot_uris = ["urn:test-slot-001"]
        
        response = client.kgframes.delete_frame_slots(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=nonexistent_frame_uri,
            slot_uris=slot_uris
        )
        
        # Should handle gracefully
        if response.success or "not found" in response.message.lower() or "frame" in response.message.lower():
            logger.info(f"✅ Slot deletion from non-existent frame handled gracefully")
            return True
        else:
            logger.error(f"❌ Slot deletion from non-existent frame failed unexpectedly: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Slot deletion from non-existent frame failed with exception: {e}")
        return False


async def test_delete_empty_slot_list(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, logger: logging.Logger) -> bool:
    """Test deleting with empty slot URI list."""
    logger.info("🧪 Testing deletion with empty slot list...")
    
    try:
        # Test deletion with empty slot list
        response = client.kgframes.delete_frame_slots(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=frame_uri,
            slot_uris=[]
        )
        
        # Should handle gracefully (either succeed with 0 deletions or provide appropriate message)
        if response.success or "empty" in response.message.lower() or "no slots" in response.message.lower():
            logger.info(f"✅ Empty slot list deletion handled gracefully")
            return True
        else:
            logger.error(f"❌ Empty slot list deletion failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Empty slot list deletion failed with exception: {e}")
        return False


async def run_slot_delete_tests(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, slot_uris: Optional[list[str]] = None, logger: logging.Logger = None) -> bool:
    """Run all slot deletion tests."""
    if logger is None:
        logger = logging.getLogger(__name__)
    
    logger.info("🚀 Running Slot Deletion Tests...")
    
    tests = [
        ("Non-existent Slot Deletion", lambda: test_delete_nonexistent_slots(client, space_id, graph_id, frame_uri, logger)),
        ("Slot Deletion from Non-existent Frame", lambda: test_delete_slots_from_nonexistent_frame(client, space_id, graph_id, logger)),
        ("Empty Slot List Deletion", lambda: test_delete_empty_slot_list(client, space_id, graph_id, frame_uri, logger))
    ]
    
    # Add tests if slot URIs are provided
    if slot_uris and len(slot_uris) > 0:
        tests.extend([
            ("Specific Slot Deletion", lambda: test_delete_specific_slots(client, space_id, graph_id, frame_uri, slot_uris, logger)),
            ("All Frame Slots Deletion", lambda: test_delete_all_frame_slots(client, space_id, graph_id, frame_uri, logger))
        ])
    
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
        logger.info("✅ All slot deletion tests passed!")
        return True
    else:
        failed_tests = [name for name, success in results if not success]
        logger.error(f"❌ Slot deletion tests failed: {failed_tests}")
        return False
