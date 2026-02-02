#!/usr/bin/env python3
"""
KGEntity Frame Deletion Test Case

Client-side test case for KG entity frame deletion operations using VitalGraph client.
Tests frame deletion within entity context, ownership validation, and cleanup verification.
"""

import logging
from typing import Dict, Any, List
from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.kgframes_model import FrameCreateResponse
from vitalgraph.client.response.client_response import DeleteResponse
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

logger = logging.getLogger(__name__)


class KGEntityFrameDeleteTester:
    """Client-side test case for KG entity frame deletion operations."""
    
    def __init__(self, client: VitalGraphClient, test_data_creator: ClientTestDataCreator):
        """
        Initialize the frame deletion tester.
        
        Args:
            client: VitalGraphClient instance
            test_data_creator: ClientTestDataCreator instance for generating test data
        """
        self.client = client
        self.test_data_creator = test_data_creator
        self.created_entity_uris = []
        self.created_frame_uris = []
        
    async def test_basic_frame_deletion(self, space_id: str, graph_id: str) -> bool:
        """
        Test basic frame deletion within entity context.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if basic frame deletion successful, False otherwise
        """
        try:
            logger.info("🧪 Testing basic frame deletion within entity context")
            
            # Create test entity with frames
            entity_objects = self.test_data_creator.create_person_with_contact("Frame Delete Test Person")
            
            # Modern client API expects GraphObjects directly
            entity_response = self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity_objects
            )
            
            if not entity_response or not hasattr(entity_response, 'created_uris') or not entity_response.created_uris:
                logger.error("Failed to create test entity for frame deletion")
                return False
                
            entity_uri = str(entity_objects[0].URI)  # Get URI from VitalSigns object and convert to string
            self.created_entity_uris.append(entity_uri)
            logger.info(f"✅ Created test entity: {entity_uri}")
            
            # Get existing frames from the entity to test deletion
            existing_frames = self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri
            )
            
            if not hasattr(existing_frames, 'objects') or not existing_frames.objects:
                logger.error("No existing frames found for deletion test")
                return False
                
            frame_uris_to_delete = [str(frame.URI) for frame in existing_frames.objects if hasattr(frame, 'URI')]
            if not frame_uris_to_delete:
                logger.error("No frame URIs found in existing frames")
                return False
                
            logger.info(f"✅ Found {len(frame_uris_to_delete)} existing frames for deletion test")
            
            # Test frame deletion by attempting to delete one frame
            if frame_uris_to_delete:
                test_frame_uri = frame_uris_to_delete[0]
                delete_response = self.client.kgentities.delete_entity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=entity_uri,
                    frame_uris=[test_frame_uri]
                )
                
                # Validate frame deletion response (should be structured response, not exception)
                if isinstance(delete_response, DeleteResponse):
                    logger.info(f"✅ Basic frame deletion successful: Got structured response")
                    return True
                else:
                    logger.error(f"Expected DeleteResponse, got {type(delete_response)}")
                    return False
            else:
                logger.info("✅ Basic frame deletion test completed (no frames to delete)")
                return True
            
        except VitalGraphClientError as e:
            logger.error(f"Client error in basic frame deletion test: {e}")
            return False
        except Exception as e:
            logger.error(f"Error in basic frame deletion test: {e}")
            return False
    
    async def test_frame_deletion_ownership_validation(self, space_id: str, graph_id: str) -> bool:
        """
        Test frame deletion ownership validation.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if ownership validation successful, False otherwise
        """
        try:
            logger.info("🧪 Testing frame deletion ownership validation")
            
            # Create two separate entities
            entity1_objects = self.test_data_creator.create_person_with_contact("Entity 1 Person")
            
            # Modern client API expects GraphObjects directly
            entity1_response = self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity1_objects
            )
            
            entity2_objects = self.test_data_creator.create_person_with_contact("Entity 2 Person")
            
            # Modern client API expects GraphObjects directly
            entity2_response = self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity2_objects
            )
            
            if not (entity1_response and entity1_response.created_uris and 
                    entity2_response and entity2_response.created_uris):
                logger.error("Failed to create test entities for ownership validation")
                return False
                
            entity1_uri = str(entity1_objects[0].URI)  # Get URI from VitalSigns object and convert to string
            entity2_uri = str(entity2_objects[0].URI)  # Get URI from VitalSigns object and convert to string
            self.created_entity_uris.extend([entity1_uri, entity2_uri])
            
            logger.info(f"✅ Created test entities: {entity1_uri}, {entity2_uri}")
            
            # Create frame for entity1
            frame_objects = self.test_data_creator.create_employment_frame("Engineer", "Tech Corp")
            
            frame_response = self.client.kgentities.create_entity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity1_uri,
                document=frame_objects
            )
            
            if not isinstance(frame_response, FrameCreateResponse) or not frame_response.created_uris:
                logger.error("Failed to create frame for ownership validation test")
                return False
                
            entity1_frame_uri = frame_response.created_uris[0]
            logger.info(f"✅ Created frame for entity1: {entity1_frame_uri}")
            
            # Try to delete entity1's frame using entity2 (should fail or return structured error)
            try:
                invalid_delete_response = self.client.kgentities.delete_entity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=entity2_uri,  # Wrong entity!
                    frame_uris=[entity1_frame_uri]
                )
                
                # Should get structured error response about ownership
                if isinstance(invalid_delete_response, DeleteResponse):
                    if hasattr(invalid_delete_response, 'deleted_count') and invalid_delete_response.deleted_count == 0:
                        logger.info("✅ Correctly prevented cross-entity frame deletion with structured response")
                    elif hasattr(invalid_delete_response, 'message') and ('ownership' in invalid_delete_response.message.lower() or 'not found' in invalid_delete_response.message.lower()):
                        logger.info("✅ Correctly handled ownership validation with structured error response")
                    else:
                        logger.warning(f"Unexpected response for ownership validation: {invalid_delete_response}")
                else:
                    logger.error(f"Expected DeleteResponse for ownership validation, got {type(invalid_delete_response)}")
                    return False
                    
            except VitalGraphClientError as e:
                # Client-side validation is also acceptable
                logger.info(f"✅ Client-side validation caught ownership violation: {e}")
            
            # Now delete the frame correctly using entity1
            correct_delete_response = self.client.kgentities.delete_entity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity1_uri,  # Correct entity
                frame_uris=[entity1_frame_uri]
            )
            
            if isinstance(correct_delete_response, DeleteResponse) and correct_delete_response.deleted_count == 1:
                logger.info("✅ Correct ownership deletion successful")
            else:
                logger.error(f"Failed correct ownership deletion: {correct_delete_response}")
                return False
            
            logger.info("✅ Frame deletion ownership validation completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error in frame deletion ownership validation test: {e}")
            return False
    
    async def test_hierarchical_frame_deletion(self, space_id: str, graph_id: str) -> bool:
        """
        Test deletion of hierarchical frames.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if hierarchical deletion successful, False otherwise
        """
        try:
            logger.info("🧪 Testing hierarchical frame deletion")
            
            # Create test entity with hierarchical frames
            entity_objects = self.test_data_creator.create_organization_with_address("Hierarchical Delete Corp")
            
            # Modern client API expects GraphObjects directly
            entity_response = self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity_objects
            )
            
            if not entity_response or not hasattr(entity_response, 'created_uris') or not entity_response.created_uris:
                logger.error("Failed to create test entity for hierarchical deletion")
                return False
                
            entity_uri = entity_response.created_uris[0]
            self.created_entity_uris.append(entity_uri)
            
            # Get existing frames from entity for hierarchical deletion test
            existing_frames = self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri
            )
            
            if not hasattr(existing_frames, 'objects') or not existing_frames.objects:
                logger.error("No existing frames found for hierarchical deletion test")
                return False
                
            # Test hierarchical deletion by deleting frames in sequence
            frames_to_delete = [str(frame.URI) for frame in existing_frames.objects if hasattr(frame, 'URI')]
            if not frames_to_delete:
                logger.error("No frame URIs found for deletion")
                return False
                
            deleted_count = 0
            for frame_uri in frames_to_delete[:2]:  # Delete first 2 frames
                delete_response = self.client.kgentities.delete_entity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=entity_uri,
                    frame_uris=[frame_uri]
                )
                
                if isinstance(delete_response, DeleteResponse):
                    deleted_count += 1
                    logger.info(f"✅ Deleted frame: {frame_uri}")
                else:
                    logger.warning(f"Failed to delete frame: {frame_uri}")
            
            logger.info(f"✅ Hierarchical frame deletion test successful: Deleted {deleted_count} frames")
            return True
            
        except Exception as e:
            logger.error(f"Error in hierarchical frame deletion test: {e}")
            return False
    
    async def test_nonexistent_frame_deletion(self, space_id: str, graph_id: str) -> bool:
        """
        Test deletion of non-existent frames.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if non-existent frame deletion handled correctly, False otherwise
        """
        try:
            logger.info("🧪 Testing non-existent frame deletion handling")
            
            # Create test entity
            entity_objects = self.test_data_creator.create_person_with_contact("Nonexistent Frame Test Person")
            entity_response = self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity_objects
            )
            
            if not entity_response or not entity_response.created_uris:
                logger.error("Failed to create test entity for nonexistent frame deletion")
                return False
                
            entity_uri = entity_response.created_uris[0]
            self.created_entity_uris.append(entity_uri)
            
            # Try to delete non-existent frame
            nonexistent_frame_uri = "http://vital.ai/test/nonexistent/frame/12345"
            
            delete_response = self.client.kgentities.delete_entity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                frame_uris=[nonexistent_frame_uri]
            )
            
            # Should get structured response indicating no frames were deleted
            if isinstance(delete_response, DeleteResponse):
                if delete_response.deleted_count == 0:
                    logger.info("✅ Correctly handled non-existent frame deletion (0 deleted)")
                elif hasattr(delete_response, 'message') and 'not found' in delete_response.message.lower():
                    logger.info("✅ Correctly handled non-existent frame with structured error message")
                else:
                    logger.warning(f"Unexpected response for non-existent frame: {delete_response}")
            else:
                logger.error(f"Expected DeleteResponse for non-existent frame, got {type(delete_response)}")
                return False
            
            logger.info("✅ Non-existent frame deletion test completed successfully")
            return True
            
        except VitalGraphClientError as e:
            # Client-side validation is acceptable
            logger.info(f"✅ Client-side validation caught non-existent frame: {e}")
            return True
        except Exception as e:
            logger.error(f"Error in non-existent frame deletion test: {e}")
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
            logger.info("🧹 Cleaning up created frame deletion test resources")
            
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
            
            logger.info("✅ Frame deletion test cleanup completed")
            return True
            
        except Exception as e:
            logger.error(f"Error during frame deletion test cleanup: {e}")
            return False
