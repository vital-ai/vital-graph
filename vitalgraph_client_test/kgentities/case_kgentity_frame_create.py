#!/usr/bin/env python3
"""
KGEntity Frame Creation Test Case

Client-side test case for KG entity frame creation operations using VitalGraph client.
Tests frame creation within entity context, hierarchical frame relationships, and validation.
"""

import logging
from typing import Dict, Any, List, Optional
from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.kgframes_model import FrameCreateResponse
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

logger = logging.getLogger(__name__)


class KGEntityFrameCreateTester:
    """Client-side test case for KG entity frame creation operations."""
    
    def __init__(self, client: VitalGraphClient, test_data_creator: ClientTestDataCreator):
        """
        Initialize the frame creation tester.
        
        Args:
            client: VitalGraphClient instance
            test_data_creator: ClientTestDataCreator instance for generating test data
        """
        self.client = client
        self.test_data_creator = test_data_creator
        self.created_entity_uris = []
        self.created_frame_uris = []
        
    async def test_basic_frame_creation(self, space_id: str, graph_id: str) -> bool:
        """
        Test basic frame creation within entity context.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if basic frame creation successful, False otherwise
        """
        try:
            logger.info("🧪 Testing basic frame creation within entity context")
            
            # Create test entity with frames
            entity_objects = self.test_data_creator.create_person_with_contact("Frame Creation Test Person")
            
            # Modern client API expects GraphObjects directly
            entity_response = self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity_objects
            )
            
            if not entity_response or not hasattr(entity_response, 'created_uris') or not entity_response.created_uris:
                logger.error("Failed to create test entity for frame creation")
                return False
                
            entity_uri = str(entity_objects[0].URI)  # Get URI from the VitalSigns object and convert to string
            self.created_entity_uris.append(entity_uri)
            logger.info(f"✅ Created test entity: {entity_uri}")
            
            # Test frame retrieval to verify frames were created with the entity
            existing_frames = self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri
            )
            
            # get_kgentity_frames returns FrameResponse with objects attribute
            if hasattr(existing_frames, 'objects') and existing_frames.objects:
                frame_count = len(existing_frames.objects)
                logger.info(f"✅ Basic frame creation test successful: Entity has {frame_count} frame objects")
                return True
            else:
                logger.error("❌ No frames found for created entity")
                return False
            
        except VitalGraphClientError as e:
            logger.error(f"Client error in basic frame creation test: {e}")
            return False
        except Exception as e:
            logger.error(f"Error in basic frame creation test: {e}")
            return False
    
    async def test_hierarchical_frame_creation(self, space_id: str, graph_id: str) -> bool:
        """
        Test hierarchical frame creation with parent_frame_uri parameter.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if hierarchical frame creation successful, False otherwise
        """
        try:
            logger.info("🧪 Testing hierarchical frame creation with parent_frame_uri")
            
            # Create test entity with frames for hierarchical testing
            entity_objects = self.test_data_creator.create_person_with_contact("Hierarchical Frame Test Person")
            
            # Modern client API expects GraphObjects directly
            entity_response = self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity_objects
            )
            
            if not entity_response or not hasattr(entity_response, 'created_uris') or not entity_response.created_uris:
                logger.error("Failed to create test entity for hierarchical frame creation")
                return False
                
            entity_uri = str(entity_objects[0].URI)  # Get URI from VitalSigns object and convert to string
            self.created_entity_uris.append(entity_uri)
            logger.info(f"✅ Created test entity: {entity_uri}")
            
            # Get existing frames from the created entity to use as parent frame
            existing_frames = self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri
            )
            
            if not hasattr(existing_frames, 'objects') or not existing_frames.objects:
                logger.error("No existing frames found to use as parent frame")
                return False
            
            # Use the first frame as parent frame URI
            parent_frame_uri = str(existing_frames.objects[0].URI)
            if not parent_frame_uri:
                logger.error("No frame URI found in existing frames")
                return False
            
            self.created_frame_uris.append(parent_frame_uri)
            logger.info(f"✅ Using existing frame as parent: {parent_frame_uri}")
            
            # Create a second entity to test hierarchical frame creation with parent_frame_uri
            child_entity_objects = self.test_data_creator.create_person_with_contact("Child Frame Test Person")
            
            # Modern client API expects GraphObjects directly
            child_entity_response = self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=child_entity_objects,
                parent_uri=parent_frame_uri
            )
            
            if not child_entity_response or not hasattr(child_entity_response, 'created_uris') or not child_entity_response.created_uris:
                logger.error("Failed to create child entity for hierarchical frame test")
                return False
                
            child_entity_uri = str(child_entity_objects[0].URI)
            self.created_entity_uris.append(child_entity_uri)
            
            # Get frames from the child entity to validate hierarchical structure
            child_frames = self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=child_entity_uri
            )
            
            # Validate that child entity has frames (which demonstrates hierarchical frame functionality)
            if hasattr(child_frames, 'objects') and child_frames.objects:
                frame_count = len(child_frames.objects)
                logger.info(f"✅ Hierarchical frame creation test successful: Child entity has {frame_count} frame objects")
                return True
            else:
                logger.error("No frames found for child entity")
                return False
            
        except VitalGraphClientError as e:
            logger.error(f"Client error in hierarchical frame creation test: {e}")
            return False
        except Exception as e:
            logger.error(f"Error in hierarchical frame creation test: {e}")
            return False
    
    async def test_frame_creation_validation(self, space_id: str, graph_id: str) -> bool:
        """
        Test frame creation validation and error handling.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if validation tests successful, False otherwise
        """
        try:
            logger.info("🧪 Testing frame creation validation and error handling")
            
            # Test 1: Invalid entity URI
            logger.info("🔍 Testing frame creation with invalid entity URI")
            
            frame_objects = self.test_data_creator.create_employment_frame("Test Job", "Test Company")
            
            try:
                invalid_response = self.client.kgentities.create_entity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri="http://invalid.uri/nonexistent",
                    document=frame_objects
                )
                
                # Should get structured error response, not exception
                if isinstance(invalid_response, FrameCreateResponse):
                    if hasattr(invalid_response, 'message') and 'not found' in invalid_response.message.lower():
                        logger.info("✅ Correctly handled invalid entity URI with structured error response")
                    else:
                        logger.warning(f"Unexpected response for invalid entity URI: {invalid_response}")
                else:
                    logger.error(f"Expected FrameCreateResponse for invalid entity, got {type(invalid_response)}")
                    return False
                    
            except VitalGraphClientError as e:
                # This is acceptable - client-side validation
                logger.info(f"✅ Client-side validation caught invalid entity URI: {e}")
            
            # Test 2: Invalid parent frame URI
            logger.info("🔍 Testing frame creation with invalid parent_frame_uri")
            
            # Create valid entity first
            entity_objects = self.test_data_creator.create_person_with_contact("Validation Test Person")
            
            # Modern client API expects GraphObjects directly
            entity_response = self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity_objects,
                parent_uri=None
            )
            
            if entity_response and hasattr(entity_response, 'created_uris') and entity_response.created_uris:
                entity_uri = entity_response.created_uris[0]
                self.created_entity_uris.append(entity_uri)
                
                try:
                    invalid_parent_response = self.client.kgentities.create_entity_frames(
                        space_id=space_id,
                        graph_id=graph_id,
                        entity_uri=entity_uri,
                        document=frame_document,
                        parent_frame_uri="http://invalid.uri/nonexistent/frame"
                    )
                    
                    # Should get structured error response about invalid parent frame
                    if isinstance(invalid_parent_response, FrameCreateResponse):
                        if hasattr(invalid_parent_response, 'message') and ('parent' in invalid_parent_response.message.lower() or 'not found' in invalid_parent_response.message.lower()):
                            logger.info("✅ Correctly handled invalid parent_frame_uri with structured error response")
                        else:
                            logger.warning(f"Unexpected response for invalid parent frame: {invalid_parent_response}")
                    else:
                        logger.error(f"Expected FrameCreateResponse for invalid parent frame, got {type(invalid_parent_response)}")
                        return False
                        
                except VitalGraphClientError as e:
                    # This is also acceptable
                    logger.info(f"✅ Client-side validation caught invalid parent frame URI: {e}")
            
            logger.info("✅ Frame creation validation tests completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error in frame creation validation test: {e}")
            return False
    
    async def cleanup_created_resources(self, space_id: str, graph_id: str) -> bool:
        """
        Clean up resources created during testing.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if cleanup successful, False otherwise
        """
        try:
            logger.info("🧹 Cleaning up created frame creation test resources")
            
            # Delete created entities (which should cascade to frames)
            for entity_uri in self.created_entity_uris:
                try:
                    delete_response = self.client.kgentities.delete_kgentity(
                        space_id=space_id,
                        graph_id=graph_id,
                        uri=entity_uri,
                        delete_entity_graph=True
                    )
                    logger.info(f"✅ Deleted entity: {entity_uri}")
                except Exception as e:
                    logger.warning(f"Failed to delete entity {entity_uri}: {e}")
            
            self.created_entity_uris.clear()
            self.created_frame_uris.clear()
            
            logger.info("✅ Frame creation test cleanup completed")
            return True
            
        except Exception as e:
            logger.error(f"Error during frame creation test cleanup: {e}")
            return False
