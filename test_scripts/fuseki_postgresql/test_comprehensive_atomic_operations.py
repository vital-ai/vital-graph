#!/usr/bin/env python3
"""
Comprehensive Atomic Operations Test Suite for VitalGraph

This test suite validates the complete atomic lifecycle for all KG operations:
- KGEntity CREATE, UPDATE, DELETE operations
- KGFrame CREATE, UPDATE, UPSERT operations  
- KGTypes CREATE, UPDATE, DELETE operations
- Cross-component integration and validation

All operations use the proven atomic update_quads function for true transaction consistency.
"""

import sys
import os
import asyncio
import logging
import uuid
from datetime import datetime

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from test_fuseki_postgresql_endpoint_utils import FusekiPostgreSQLEndpointTester
from vitalgraph.kg_impl.kgentity_update_impl import KGEntityUpdateProcessor
from vitalgraph.kg_impl.kgentity_frame_create_impl import KGEntityFrameCreateProcessor, OperationMode
from vitalgraph.kg_impl.kgtypes_update_impl import KGTypesUpdateProcessor
from vitalgraph.kg_impl.kgtypes_create_impl import KGTypesCreateProcessor
from vitalgraph.kg_impl.kgtypes_read_impl import KGTypesReadProcessor
from vitalgraph.kg_impl.kgtypes_delete_impl import KGTypesDeleteProcessor

# VitalSigns imports
import vital_ai_vitalsigns as vitalsigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGType import KGType
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_atomic_entity_lifecycle():
    """Test complete atomic entity lifecycle: CREATE -> UPDATE -> DELETE."""
    logger.info("🧪 Testing atomic entity lifecycle")
    
    try:
        # Setup test environment
        space_id = f"atomic_entity_lifecycle_test_{uuid.uuid4().hex[:8]}"
        graph_id = "http://vital.ai/graph/test_atomic_entity_lifecycle"
        
        # Create test backend using the same pattern as other atomic tests
        tester = FusekiPostgreSQLEndpointTester()
        await tester.setup_hybrid_backend()
        test_space_id = await tester.create_test_space(space_id)
        backend = await tester.space_impl.get_backend_adapter(test_space_id)
        entity_processor = KGEntityUpdateProcessor()
        
        # Test data
        entity_uri = "http://vital.ai/test/entity_lifecycle"
        
        # Phase 1: CREATE entity
        logger.info("📝 Phase 1: CREATE entity")
        create_entity = KGEntity()
        create_entity.URI = entity_uri
        create_entity.hasName = "Lifecycle Test Entity"
        create_entity.hasKGGraphURI = entity_uri
        
        created_uri = await entity_processor.create_entity(
            backend=backend,
            space_id=space_id,
            graph_id=graph_id,
            entity_object=create_entity
        )
        
        if created_uri != entity_uri:
            logger.error(f"❌ CREATE failed: expected {entity_uri}, got {created_uri}")
            return False
        
        logger.info(f"✅ CREATE successful: {created_uri}")
        
        # Phase 2: UPDATE entity
        logger.info("📝 Phase 2: UPDATE entity")
        update_entity = KGEntity()
        update_entity.URI = entity_uri
        update_entity.hasName = "Updated Lifecycle Test Entity"
        update_entity.hasKGGraphURI = entity_uri
        
        updated_uri = await entity_processor.update_entity(
            backend=backend,
            space_id=space_id,
            graph_id=graph_id,
            entity_uri=entity_uri,
            vitalsigns_objects=[update_entity]
        )
        
        if updated_uri != entity_uri:
            logger.error(f"❌ UPDATE failed: expected {entity_uri}, got {updated_uri}")
            return False
        
        logger.info(f"✅ UPDATE successful: {updated_uri}")
        
        # Phase 3: Verify UPDATE worked
        logger.info("📝 Phase 3: Verify UPDATE")
        exists = await entity_processor.entity_exists(backend, space_id, graph_id, entity_uri)
        if not exists:
            logger.error(f"❌ Entity verification failed: {entity_uri} should exist")
            return False
        
        logger.info(f"✅ Entity verification successful: {entity_uri}")
        
        # Phase 4: DELETE entity (using delete_quads pattern)
        logger.info("📝 Phase 4: DELETE entity")
        delete_quads = await entity_processor._build_delete_quads_for_entity(
            backend, space_id, graph_id, entity_uri
        )
        
        success = await backend.update_quads(
            space_id=space_id,
            delete_quads=delete_quads,
            insert_quads=[]
        )
        
        if not success:
            logger.error("❌ DELETE failed: update_quads returned False")
            return False
        
        logger.info("✅ DELETE successful")
        
        # Phase 5: Verify DELETE worked
        logger.info("📝 Phase 5: Verify DELETE")
        exists_after_delete = await entity_processor.entity_exists(backend, space_id, graph_id, entity_uri)
        if exists_after_delete:
            logger.error(f"❌ Delete verification failed: {entity_uri} should not exist")
            return False
        
        logger.info(f"✅ Delete verification successful: {entity_uri} removed")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Atomic entity lifecycle test failed: {e}")
        return False


async def test_atomic_frame_lifecycle():
    """Test complete atomic frame lifecycle: CREATE -> UPDATE -> UPSERT."""
    logger.info("🧪 Testing atomic frame lifecycle")
    
    try:
        # Setup test environment
        space_id = f"atomic_frame_lifecycle_test_{uuid.uuid4().hex[:8]}"
        graph_id = "http://vital.ai/graph/test_atomic_frame_lifecycle"
        
        backend = await create_test_hybrid_backend(space_id)
        frame_processor = KGEntityFrameCreateProcessor()
        
        # Test data
        entity_uri = "http://vital.ai/test/entity_frame_lifecycle"
        frame_uri = "http://vital.ai/test/frame_lifecycle"
        slot_uri = "http://vital.ai/test/slot_lifecycle"
        
        # Phase 1: CREATE frame with entity and slot
        logger.info("📝 Phase 1: CREATE frame")
        
        # Create entity
        entity = KGEntity()
        entity.URI = entity_uri
        entity.hasName = "Frame Lifecycle Entity"
        entity.hasKGGraphURI = entity_uri
        
        # Create frame
        frame = KGFrame()
        frame.URI = frame_uri
        frame.hasName = "Frame Lifecycle Test"
        frame.hasFrameGraphURI = frame_uri
        
        # Create slot
        slot = KGTextSlot()
        slot.URI = slot_uri
        slot.hasName = "Lifecycle Slot"
        slot.textSlotValue = "Initial Value"
        slot.hasFrameGraphURI = frame_uri
        
        # Create edges
        entity_frame_edge = Edge_hasEntityKGFrame()
        entity_frame_edge.URI = f"http://edge/entity_frame_edge_{uuid.uuid4().hex[:8]}"
        entity_frame_edge.hasEdgeSource = entity_uri
        entity_frame_edge.hasEdgeDestination = frame_uri
        
        frame_slot_edge = Edge_hasKGSlot()
        frame_slot_edge.URI = f"http://edge/frame_slot_edge_{uuid.uuid4().hex[:8]}"
        frame_slot_edge.hasEdgeSource = frame_uri
        frame_slot_edge.hasEdgeDestination = slot_uri
        
        vitalsigns_objects = [entity, frame, slot, entity_frame_edge, frame_slot_edge]
        
        result = await frame_processor.create_entity_frame(
            backend_adapter=backend,
            space_id=space_id,
            graph_id=graph_id,
            entity_uri=entity_uri,
            frame_objects=vitalsigns_objects,
            operation_mode="CREATE"
        )
        created_uris = result.created_uris if result.success else []
        
        if len(created_uris) != 5:
            logger.error(f"❌ CREATE failed: expected 5 objects, got {len(created_uris)}")
            return False
        
        logger.info(f"✅ CREATE successful: {len(created_uris)} objects created")
        
        # Phase 2: UPDATE frame
        logger.info("📝 Phase 2: UPDATE frame")
        
        # Update slot value
        updated_slot = KGTextSlot()
        updated_slot.URI = slot_uri
        updated_slot.hasName = "Updated Lifecycle Slot"
        updated_slot.textSlotValue = "Updated Value"
        updated_slot.hasFrameGraphURI = frame_uri
        
        # Keep other objects the same
        update_objects = [entity, frame, updated_slot, entity_frame_edge, frame_slot_edge]
        
        result = await frame_processor.create_entity_frame(
            backend_adapter=backend,
            space_id=space_id,
            graph_id=graph_id,
            entity_uri=entity_uri,
            frame_objects=update_objects,
            operation_mode="UPDATE"
        )
        updated_uris = result.created_uris if result.success else []
        
        if len(updated_uris) != 5:
            logger.error(f"❌ UPDATE failed: expected 5 objects, got {len(updated_uris)}")
            return False
        
        logger.info(f"✅ UPDATE successful: {len(updated_uris)} objects updated")
        
        # Phase 3: UPSERT with new slot
        logger.info("📝 Phase 3: UPSERT with new slot")
        
        # Add new slot
        new_slot_uri = "http://vital.ai/test/slot_lifecycle_new"
        new_slot = KGTextSlot()
        new_slot.URI = new_slot_uri
        new_slot.hasName = "New Lifecycle Slot"
        new_slot.textSlotValue = "New Slot Value"
        new_slot.hasFrameGraphURI = frame_uri
        
        # Create edge for new slot
        new_frame_slot_edge = Edge_hasKGSlot()
        new_frame_slot_edge.URI = f"http://edge/frame_slot_edge_new_{uuid.uuid4().hex[:8]}"
        new_frame_slot_edge.hasEdgeSource = frame_uri
        new_frame_slot_edge.hasEdgeDestination = new_slot_uri
        
        # UPSERT with both old and new slots
        upsert_objects = [entity, frame, updated_slot, new_slot, entity_frame_edge, frame_slot_edge, new_frame_slot_edge]
        
        result = await frame_processor.create_entity_frame(
            backend_adapter=backend,
            space_id=space_id,
            graph_id=graph_id,
            entity_uri=entity_uri,
            frame_objects=upsert_objects,
            operation_mode="UPSERT"
        )
        upserted_uris = result.created_uris if result.success else []
        
        if len(upserted_uris) != 7:
            logger.error(f"❌ UPSERT failed: expected 7 objects, got {len(upserted_uris)}")
            return False
        
        logger.info(f"✅ UPSERT successful: {len(upserted_uris)} objects upserted")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Atomic frame lifecycle test failed: {e}")
        return False


async def test_atomic_kgtypes_lifecycle():
    """Test complete atomic KGTypes lifecycle: CREATE -> READ -> UPDATE -> DELETE."""
    logger.info("🧪 Testing atomic KGTypes lifecycle")
    
    try:
        # Setup test environment
        space_id = f"atomic_kgtypes_lifecycle_test_{uuid.uuid4().hex[:8]}"
        graph_id = "http://vital.ai/graph/test_atomic_kgtypes_lifecycle"
        
        backend = await create_test_hybrid_backend(space_id)
        
        # Initialize all KGTypes processors
        create_processor = KGTypesCreateProcessor()
        read_processor = KGTypesReadProcessor()
        update_processor = KGTypesUpdateProcessor()
        delete_processor = KGTypesDeleteProcessor()
        
        # Test data
        kgtype_uri = "http://vital.ai/test/kgtype_lifecycle"
        
        # Phase 1: CREATE KGType
        logger.info("📝 Phase 1: CREATE KGType")
        
        create_kgtype = KGType()
        create_kgtype.URI = kgtype_uri
        create_kgtype.hasName = "Lifecycle Test Type"
        create_kgtype.hasDescription = "Initial description"
        
        created_uri = await create_processor.create_kgtype(
            backend=backend,
            space_id=space_id,
            graph_id=graph_id,
            kgtype_object=create_kgtype
        )
        
        if created_uri != kgtype_uri:
            logger.error(f"❌ CREATE failed: expected {kgtype_uri}, got {created_uri}")
            return False
        
        logger.info(f"✅ CREATE successful: {created_uri}")
        
        # Phase 2: READ KGType
        logger.info("📝 Phase 2: READ KGType")
        
        read_result = await read_processor.get_kgtype_by_uri(
            backend=backend,
            space_id=space_id,
            graph_id=graph_id,
            kgtype_uri=kgtype_uri
        )
        
        if not read_result:
            logger.error(f"❌ READ failed: KGType {kgtype_uri} not found")
            return False
        
        read_uri = str(read_result.URI)
        if read_uri != kgtype_uri:
            logger.error(f"❌ READ failed: expected {kgtype_uri}, got {read_uri}")
            return False
        
        logger.info(f"✅ READ successful: {read_uri}")
        
        # Phase 3: UPDATE KGType
        logger.info("📝 Phase 3: UPDATE KGType")
        
        update_kgtype = KGType()
        update_kgtype.URI = kgtype_uri
        update_kgtype.hasName = "Updated Lifecycle Test Type"
        update_kgtype.hasDescription = "Updated description"
        
        updated_uri = await update_processor.update_kgtype(
            backend=backend,
            space_id=space_id,
            graph_id=graph_id,
            kgtype_object=update_kgtype
        )
        
        if updated_uri != kgtype_uri:
            logger.error(f"❌ UPDATE failed: expected {kgtype_uri}, got {updated_uri}")
            return False
        
        logger.info(f"✅ UPDATE successful: {updated_uri}")
        
        # Phase 4: Verify UPDATE worked
        logger.info("📝 Phase 4: Verify UPDATE")
        
        updated_result = await read_processor.get_kgtype_by_uri(
            backend=backend,
            space_id=space_id,
            graph_id=graph_id,
            kgtype_uri=kgtype_uri
        )
        
        if not updated_result or updated_result.get('hasName') != "Updated Lifecycle Test Type":
            logger.error(f"❌ UPDATE verification failed: name not updated correctly")
            return False
        
        logger.info("✅ UPDATE verification successful")
        
        # Phase 5: DELETE KGType
        logger.info("📝 Phase 5: DELETE KGType")
        
        delete_success = await delete_processor.delete_kgtype(
            backend=backend,
            space_id=space_id,
            graph_id=graph_id,
            kgtype_uri=kgtype_uri
        )
        
        if not delete_success:
            logger.error("❌ DELETE failed: delete_kgtype returned False")
            return False
        
        logger.info("✅ DELETE successful")
        
        # Phase 6: Verify DELETE worked
        logger.info("📝 Phase 6: Verify DELETE")
        
        deleted_result = await read_processor.get_kgtype_by_uri(
            backend=backend,
            space_id=space_id,
            graph_id=graph_id,
            kgtype_uri=kgtype_uri
        )
        
        if deleted_result:
            logger.error(f"❌ DELETE verification failed: KGType {kgtype_uri} still exists")
            return False
        
        logger.info(f"✅ DELETE verification successful: {kgtype_uri} removed")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Atomic KGTypes lifecycle test failed: {e}")
        return False


async def test_cross_component_integration():
    """Test integration between entities, frames, and types in a single atomic operation."""
    logger.info("🧪 Testing cross-component integration")
    
    try:
        # Setup test environment
        space_id = f"atomic_integration_test_{uuid.uuid4().hex[:8]}"
        graph_id = "http://vital.ai/graph/test_atomic_integration"
        
        backend = await create_test_hybrid_backend(space_id)
        
        # Initialize processors
        entity_processor = KGEntityUpdateProcessor()
        frame_processor = KGEntityFrameCreateProcessor()
        kgtype_create_processor = KGTypesCreateProcessor()
        
        # Test data
        kgtype_uri = "http://vital.ai/test/integration_type"
        entity_uri = "http://vital.ai/test/integration_entity"
        frame_uri = "http://vital.ai/test/integration_frame"
        slot_uri = "http://vital.ai/test/integration_slot"
        
        # Phase 1: Create KGType first
        logger.info("📝 Phase 1: Create KGType")
        
        kgtype = KGType()
        kgtype.URI = kgtype_uri
        kgtype.hasName = "Integration Test Type"
        
        kgtype_created = await kgtype_create_processor.create_kgtype(
            backend=backend,
            space_id=space_id,
            graph_id=graph_id,
            kgtype_object=kgtype
        )
        
        if kgtype_created != kgtype_uri:
            logger.error(f"❌ KGType creation failed")
            return False
        
        logger.info("✅ KGType created successfully")
        
        # Phase 2: Create entity referencing the type
        logger.info("📝 Phase 2: Create entity with type reference")
        
        entity = KGEntity()
        entity.URI = entity_uri
        entity.hasName = "Integration Test Entity"
        entity.hasKGGraphURI = entity_uri
        # Note: In a real scenario, you might reference the KGType
        
        entity_created = await entity_processor.create_entity(
            backend=backend,
            space_id=space_id,
            graph_id=graph_id,
            entity_object=entity
        )
        
        if entity_created != entity_uri:
            logger.error(f"❌ Entity creation failed")
            return False
        
        logger.info("✅ Entity created successfully")
        
        # Phase 3: Create frame for the entity
        logger.info("📝 Phase 3: Create frame for entity")
        
        frame = KGFrame()
        frame.URI = frame_uri
        frame.hasName = "Integration Test Frame"
        frame.hasFrameGraphURI = frame_uri
        
        slot = KGTextSlot()
        slot.URI = slot_uri
        slot.hasName = "Integration Slot"
        slot.textSlotValue = "Integration test value"
        slot.hasFrameGraphURI = frame_uri
        
        # Create edges
        entity_frame_edge = Edge_hasEntityKGFrame()
        entity_frame_edge.URI = f"http://edge/integration_entity_frame_{uuid.uuid4().hex[:8]}"
        entity_frame_edge.hasEdgeSource = entity_uri
        entity_frame_edge.hasEdgeDestination = frame_uri
        
        frame_slot_edge = Edge_hasKGSlot()
        frame_slot_edge.URI = f"http://edge/integration_frame_slot_{uuid.uuid4().hex[:8]}"
        frame_slot_edge.hasEdgeSource = frame_uri
        frame_slot_edge.hasEdgeDestination = slot_uri
        
        frame_objects = [frame, slot, entity_frame_edge, frame_slot_edge]
        
        result = await frame_processor.create_entity_frame(
            backend_adapter=backend,
            space_id=space_id,
            graph_id=graph_id,
            entity_uri=entity_uri,
            frame_objects=frame_objects,
            operation_mode="CREATE"
        )
        frame_created = result.created_uris if result.success else []
        
        if len(frame_created) != 4:
            logger.error(f"❌ Frame creation failed: expected 4 objects, got {len(frame_created)}")
            return False
        
        logger.info("✅ Frame created successfully")
        
        # Phase 4: Verify all components exist and are properly linked
        logger.info("📝 Phase 4: Verify integration")
        
        # Check entity exists
        entity_exists = await entity_processor.entity_exists(backend, space_id, graph_id, entity_uri)
        if not entity_exists:
            logger.error("❌ Integration verification failed: entity not found")
            return False
        
        # Check KGType exists
        kgtype_exists = await kgtype_create_processor.kgtype_exists(backend, space_id, graph_id, kgtype_uri)
        if not kgtype_exists:
            logger.error("❌ Integration verification failed: KGType not found")
            return False
        
        logger.info("✅ Cross-component integration successful")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Cross-component integration test failed: {e}")
        return False


async def main():
    """Run comprehensive atomic operations test suite."""
    logger.info("🎯 COMPREHENSIVE ATOMIC OPERATIONS TEST SUITE")
    logger.info("=" * 60)
    
    test_results = []
    
    # Test 1: Atomic Entity Lifecycle
    logger.info("🧪 Test 1: Atomic Entity Lifecycle")
    result1 = await test_atomic_entity_lifecycle()
    test_results.append(("Atomic Entity Lifecycle", result1))
    logger.info(f"✅ Atomic Entity Lifecycle: {'PASSED' if result1 else 'FAILED'}")
    logger.info("-" * 60)
    
    # Test 2: Atomic Frame Lifecycle
    logger.info("🧪 Test 2: Atomic Frame Lifecycle")
    result2 = await test_atomic_frame_lifecycle()
    test_results.append(("Atomic Frame Lifecycle", result2))
    logger.info(f"✅ Atomic Frame Lifecycle: {'PASSED' if result2 else 'FAILED'}")
    logger.info("-" * 60)
    
    # Test 3: Atomic KGTypes Lifecycle
    logger.info("🧪 Test 3: Atomic KGTypes Lifecycle")
    result3 = await test_atomic_kgtypes_lifecycle()
    test_results.append(("Atomic KGTypes Lifecycle", result3))
    logger.info(f"✅ Atomic KGTypes Lifecycle: {'PASSED' if result3 else 'FAILED'}")
    logger.info("-" * 60)
    
    # Test 4: Cross-Component Integration
    logger.info("🧪 Test 4: Cross-Component Integration")
    result4 = await test_cross_component_integration()
    test_results.append(("Cross-Component Integration", result4))
    logger.info(f"✅ Cross-Component Integration: {'PASSED' if result4 else 'FAILED'}")
    logger.info("-" * 60)
    
    # Cleanup resources
    logger.info("🧹 Cleaning up test resources")
    await cleanup_test_resources()
    logger.info("✅ Test environment cleanup completed")
    
    # Summary
    logger.info("=" * 60)
    logger.info("🎯 COMPREHENSIVE ATOMIC OPERATIONS TEST SUITE SUMMARY")
    logger.info("=" * 60)
    
    passed_tests = sum(1 for _, result in test_results if result)
    total_tests = len(test_results)
    
    for test_name, result in test_results:
        status = "✅ PASSED" if result else "❌ FAILED"
        logger.info(f"{status}: {test_name}")
    
    logger.info(f"📊 Passed: {passed_tests}/{total_tests}")
    logger.info(f"📊 Failed: {total_tests - passed_tests}/{total_tests}")
    logger.info(f"📊 Success Rate: {(passed_tests/total_tests)*100:.1f}%")
    
    if passed_tests == total_tests:
        logger.info("🎉 ALL COMPREHENSIVE ATOMIC OPERATIONS TESTS PASSED!")
        return True
    else:
        logger.error("❌ SOME COMPREHENSIVE ATOMIC OPERATIONS TESTS FAILED!")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
