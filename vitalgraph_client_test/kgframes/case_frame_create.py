"""
Client Test Case: Frame Creation Operations

Tests KGFrames creation functionality including:
- Basic frame creation
- Frame creation with entity URI
- Frame creation with parent URI
- Frame creation with operation modes
"""

import logging
from typing import Optional
from vitalgraph.client.vitalgraph_client import VitalGraphClient

# VitalSigns imports - REQUIRED for proper test data creation
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

# VitalSigns utilities for JSON-LD conversion
from vital_ai_vitalsigns.vitalsigns import VitalSigns

# Import test utilities
from .test_utils import convert_to_jsonld_request


async def test_frame_creation_basic(client: VitalGraphClient, space_id: str, graph_id: str, entity_uri: Optional[str], logger: logging.Logger) -> bool:
    """Test basic frame creation for an entity."""
    logger.info("🧪 Testing basic frame creation...")
    
    try:
        # Create test data using ClientTestDataCreator rich methods - BEST APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Use the rich test data creation method to get complete entity with frames
        person_objects = test_data_creator.create_person_with_contact("Test Person")
        
        # Extract just the frames from the complete entity structure
        frames = [obj for obj in person_objects if isinstance(obj, KGFrame)]
        
        # Convert VitalSigns objects to JSON-LD using helper function
        document = convert_to_jsonld_request(frames)
        
        # Test frame creation
        response = client.kgframes.create_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            data=document,
            entity_uri=entity_uri
        )
        
        if response.success and response.frames_created > 0:
            logger.info(f"✅ Basic frame creation successful: {response.frames_created} frames created")
            logger.info(f"   Created frames: {[str(frame.name) for frame in frames]}")
            return True
        else:
            logger.error(f"❌ Basic frame creation failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Basic frame creation failed with exception: {e}")
        return False


async def test_frame_creation_with_entity_uri(client: VitalGraphClient, space_id: str, graph_id: str, entity_uri: str, logger: logging.Logger) -> bool:
    """Test frame creation with entity URI parameter."""
    logger.info("🧪 Testing frame creation with entity URI...")
    
    try:
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create a KGFrame using VitalSigns
        frame = KGFrame()
        frame.URI = test_data_creator.generate_test_uri("frame", "entity_001")
        frame.name = "Test Frame with Entity"
        frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#EntityFrame"
        
        # Convert VitalSigns objects to JSON-LD using helper function
        document = convert_to_jsonld_request(frame)
        
        # Test frame creation with entity URI
        response = client.kgframes.create_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            data=document,
            entity_uri=entity_uri
        )
        
        if response.success and response.frames_created > 0:
            logger.info(f"✅ Frame creation with entity URI successful: {response.frames_created} frames created")
            return True
        else:
            logger.error(f"❌ Frame creation with entity URI failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Frame creation with entity URI failed with exception: {e}")
        return False


async def test_frame_creation_with_parent_uri(client: VitalGraphClient, space_id: str, graph_id: str, parent_uri: str, logger: logging.Logger) -> bool:
    """Test frame creation with parent URI parameter."""
    logger.info("🧪 Testing frame creation with parent URI...")
    
    try:
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create a KGFrame using VitalSigns
        frame = KGFrame()
        frame.URI = test_data_creator.generate_test_uri("frame", "child_001")
        frame.name = "Test Child Frame"
        frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#ChildFrame"
        
        # Convert VitalSigns objects to JSON-LD using helper function
        document = convert_to_jsonld_request(frame)
        
        # Test frame creation with parent URI
        response = client.kgframes.create_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            data=document,
            parent_uri=parent_uri
        )
        
        if response.success and response.frames_created > 0:
            logger.info(f"✅ Frame creation with parent URI successful: {response.frames_created} frames created")
            return True
        else:
            logger.error(f"❌ Frame creation with parent URI failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Frame creation with parent URI failed with exception: {e}")
        return False


async def test_frame_creation_with_operation_modes(client: VitalGraphClient, space_id: str, graph_id: str, entity_uri: str, logger: logging.Logger) -> bool:
    """Test frame creation with different operation modes."""
    logger.info("🧪 Testing frame creation with operation modes...")
    
    try:
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create a KGFrame using VitalSigns
        frame = KGFrame()
        frame.URI = test_data_creator.generate_test_uri("frame", "mode_001")
        frame.name = "Test Frame with Mode"
        frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#ModeFrame"
        
        # Convert VitalSigns objects to JSON-LD using helper function
        document = convert_to_jsonld_request(frame)
        
        # Test CREATE mode
        logger.info(f"   Testing operation mode: create")
        create_response = client.kgframes.create_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            data=document,
            entity_uri=entity_uri,
            operation_mode="create"
        )
        
        if not create_response.success:
            logger.error(f"❌ Frame creation with mode create failed: {create_response.message}")
            return False
        
        # Test UPDATE mode
        logger.info(f"   Testing operation mode: update")
        update_response = client.kgframes.update_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            data=document,
            entity_uri=entity_uri
        )
        
        if not update_response.success:
            logger.error(f"❌ Frame creation with mode update failed: {update_response.message}")
            return False
        
        # Test UPSERT mode
        logger.info(f"   Testing operation mode: upsert")
        upsert_response = client.kgframes.create_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            data=document,
            entity_uri=entity_uri,
            operation_mode="upsert"
        )
        
        if not upsert_response.success:
            logger.error(f"❌ Frame creation with mode upsert failed: {upsert_response.message}")
            return False
        
        logger.info("✅ Frame creation with operation modes successful")
        return True
        
    except Exception as e:
        logger.error(f"❌ Frame creation with operation modes failed with exception: {e}")
        return False


async def run_frame_creation_tests(client: VitalGraphClient, space_id: str, graph_id: str, entity_uri: Optional[str] = None, parent_uri: Optional[str] = None, logger: logging.Logger = None) -> bool:
    """Run all frame creation tests."""
    if logger is None:
        logger = logging.getLogger(__name__)
    
    logger.info("🚀 Running Frame Creation Tests...")
    
    tests = [
        ("Basic Frame Creation", lambda: test_frame_creation_basic(client, space_id, graph_id, entity_uri, logger)),
    ]
    
    # Only run operation modes test if entity_uri is provided
    if entity_uri:
        tests.append(("Frame Creation with Operation Modes", lambda: test_frame_creation_with_operation_modes(client, space_id, graph_id, entity_uri, logger)))
    
    # Add optional tests if URIs are provided
    if entity_uri:
        tests.append(("Frame Creation with Entity URI", lambda: test_frame_creation_with_entity_uri(client, space_id, graph_id, entity_uri, logger)))
    
    if parent_uri:
        tests.append(("Frame Creation with Parent URI", lambda: test_frame_creation_with_parent_uri(client, space_id, graph_id, parent_uri, logger)))
    
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
        logger.info("✅ All frame creation tests passed!")
        return True
    else:
        failed_tests = [name for name, success in results if not success]
        logger.error(f"❌ Frame creation tests failed: {failed_tests}")
        return False
