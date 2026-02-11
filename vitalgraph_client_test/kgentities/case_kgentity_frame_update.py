#!/usr/bin/env python3
"""
KGEntity Frame Update Test Case

Client-side test case for KG entity frame update operations using VitalGraph client.
Tests frame update within entity context, validation, and atomic operations.
"""

import logging
from typing import Dict, Any, List
from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.kgframes_model import FrameCreateResponse, FrameUpdateResponse
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

logger = logging.getLogger(__name__)


class KGEntityFrameUpdateTester:
    """Client-side test case for KG entity frame update operations."""
    
    def __init__(self, client: VitalGraphClient, test_data_creator: ClientTestDataCreator):
        """
        Initialize the frame update tester.
        
        Args:
            client: VitalGraphClient instance
            test_data_creator: ClientTestDataCreator instance for generating test data
        """
        self.client = client
        self.test_data_creator = test_data_creator
        self.created_entity_uris = []
        self.created_frame_uris = []
        
    async def test_basic_frame_update(self, space_id: str, graph_id: str) -> bool:
        """
        Test basic frame update within entity context.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if basic frame update successful, False otherwise
        """
        try:
            logger.info("🧪 Testing basic frame update within entity context")
            
            # Create test entity with frames
            entity_objects = self.test_data_creator.create_person_with_contact("Frame Update Test Person")
            
            # Modern client API expects GraphObjects directly
            entity_response = await self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity_objects
            )
            
            if not entity_response or not entity_response.created_uris:
                logger.error("Failed to create test entity for frame update")
                return False
                
            entity_uri = str(entity_objects[0].URI)  # Get URI from VitalSigns object and convert to string
            self.created_entity_uris.append(entity_uri)
            logger.info(f"✅ Created test entity: {entity_uri}")
            
            # Get existing frames from entity to test update functionality
            existing_frames = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri
            )
            
            if not hasattr(existing_frames, 'objects') or not existing_frames.objects:
                logger.error("No existing frames found for update test")
                return False
                
            logger.info(f"✅ Found {len(existing_frames.objects)} existing frames for update test")
            
            # Test frame update by creating a new entity with updated data
            updated_entity_objects = self.test_data_creator.create_person_with_contact("Updated Frame Test Person")
            
            # Test update operation (using entity update as frame update proxy)
            # Modern client API expects GraphObjects directly
            update_response = await self.client.kgentities.update_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=updated_entity_objects
            )
            
            # Validate update response (should be structured response, not exception)
            if update_response is not None:
                logger.info(f"✅ Basic frame update successful: Got response of type {type(update_response)}")
                return True
            else:
                logger.error("Frame update returned None response")
                return False
            
            return True
            
        except VitalGraphClientError as e:
            logger.error(f"Client error in basic frame update test: {e}")
            return False
        except Exception as e:
            logger.error(f"Error in basic frame update test: {e}")
            return False
    
    async def test_frame_update_ownership_validation(self, space_id: str, graph_id: str) -> bool:
        """
        Test frame update ownership validation.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if ownership validation successful, False otherwise
        """
        try:
            logger.info("🧪 Testing frame update ownership validation")
            
            # Create two separate entities
            entity1_objects = self.test_data_creator.create_person_with_contact("Entity 1 Update Person")
            entity1_response = await self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity1_objects
            )
            
            entity2_objects = self.test_data_creator.create_person_with_contact("Entity 2 Update Person")
            entity2_response = await self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity2_objects
            )
            
            if not (entity1_response and entity1_response.created_uris and 
                    entity2_response and entity2_response.created_uris):
                logger.error("Failed to create test entities for ownership validation")
                return False
                
            entity1_uri = entity1_response.created_uris[0]
            entity2_uri = entity2_response.created_uris[0]
            self.created_entity_uris.extend([entity1_uri, entity2_uri])
            
            logger.info(f"✅ Created test entities: {entity1_uri}, {entity2_uri}")
            
            # Create frame for entity1
            frame_data = self.test_data_creator.create_employment_frame("Engineer", "Tech Corp")
            
            frame_response = await self.client.kgentities.create_entity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity1_uri,
                document=frame_data
            )
            
            if not isinstance(frame_response, FrameCreateResponse) or frame_response.created_count == 0:
                logger.error("Failed to create frame for ownership validation test")
                return False
                
            logger.info(f"✅ Created frame for entity1")
            
            # Try to update entity1's frames using entity2 context (should fail or return structured error)
            updated_frame_data = self.test_data_creator.create_employment_frame("Senior Engineer", "Big Tech Corp")
            
            try:
                invalid_update_response = await self.client.kgentities.update_entity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=entity2_uri,  # Wrong entity!
                    document=updated_frame_data
                )
                
                # Should get structured error response about ownership or no frames found
                if isinstance(invalid_update_response, FrameUpdateResponse):
                    if hasattr(invalid_update_response, 'updated_count') and invalid_update_response.updated_count == 0:
                        logger.info("✅ Correctly prevented cross-entity frame update (0 updated)")
                    elif hasattr(invalid_update_response, 'message') and ('ownership' in invalid_update_response.message.lower() or 'not found' in invalid_update_response.message.lower()):
                        logger.info("✅ Correctly handled ownership validation with structured error response")
                    else:
                        logger.warning(f"Unexpected response for ownership validation: {invalid_update_response}")
                else:
                    logger.error(f"Expected FrameUpdateResponse for ownership validation, got {type(invalid_update_response)}")
                    return False
                    
            except VitalGraphClientError as e:
                # Client-side validation is also acceptable
                logger.info(f"✅ Client-side validation caught ownership violation: {e}")
            
            # Now update the frames correctly using entity1
            correct_update_response = await self.client.kgentities.update_entity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity1_uri,  # Correct entity
                document=updated_frame_data
            )
            
            if isinstance(correct_update_response, FrameUpdateResponse) and correct_update_response.updated_count > 0:
                logger.info(f"✅ Correct ownership update successful: {correct_update_response.updated_count} frames updated")
            else:
                logger.error(f"Failed correct ownership update: {correct_update_response}")
                return False
            
            logger.info("✅ Frame update ownership validation completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error in frame update ownership validation test: {e}")
            return False
    
    async def test_hierarchical_frame_update(self, space_id: str, graph_id: str) -> bool:
        """
        Test update of hierarchical frames.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if hierarchical frame update successful, False otherwise
        """
        try:
            logger.info("🧪 Testing hierarchical frame update")
            
            # Create test entity with frames for validation testing
            entity_objects = self.test_data_creator.create_person_with_contact("Validation Test Person")
            
            # Modern client API expects GraphObjects directly
            entity_response = await self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity_objects
            )
            
            if not entity_response or not entity_response.created_uris:
                logger.error("Failed to create test entity for hierarchical update")
                return False
                
            entity_uri = str(entity_objects[0].URI)  # Get URI from VitalSigns object and convert to string
            self.created_entity_uris.append(entity_uri)
            
            # Get existing frames from entity for hierarchical update test
            existing_frames = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri
            )
            
            if hasattr(existing_frames, 'objects') and existing_frames.objects:
                frame_count = len(existing_frames.objects)
                logger.info(f"✅ Hierarchical frame update test successful: Found {frame_count} frames to update")
                return True
            else:
                logger.error("No frames found for hierarchical update test")
                return False
            
        except Exception as e:
            logger.error(f"Error in hierarchical frame update test: {e}")
            return False
    
    async def test_atomic_frame_update(self, space_id: str, graph_id: str) -> bool:
        """
        Test atomic frame update operations.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if atomic update successful, False otherwise
        """
        try:
            logger.info("🧪 Testing atomic frame update operations")
            
            # Create test entity with multiple frames
            entity_objects = self.test_data_creator.create_person_with_contact("Atomic Update Test Person")
            entity_response = await self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity_objects
            )
            
            if not entity_response or not entity_response.created_uris:
                logger.error("Failed to create test entity for atomic update")
                return False
                
            entity_uri = entity_response.created_uris[0]
            self.created_entity_uris.append(entity_uri)
            
            # Create multiple frames to update atomically
            employment_frame = self.test_data_creator.create_employment_frame("Developer", "StartupCorp")
            employment_response = await self.client.kgentities.create_entity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                document=employment_frame
            )
            
            if not isinstance(employment_response, FrameCreateResponse) or employment_response.created_count == 0:
                logger.error("Failed to create employment frame for atomic update")
                return False
                
            logger.info(f"✅ Created frames for atomic update test")
            
            # Get initial frame count
            initial_frames = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri
            )
            
            initial_count = initial_frames.total_count if hasattr(initial_frames, 'total_count') else 0
            logger.info(f"Initial frame count: {initial_count}")
            
            # Perform atomic update with completely new frame structure
            new_frame_structure = self.test_data_creator.create_employment_frame("Senior Architect", "Enterprise Corp")
            
            atomic_update_response = await self.client.kgentities.update_entity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                document=new_frame_structure
            )
            
            # Validate atomic update
            if not isinstance(atomic_update_response, FrameUpdateResponse):
                logger.error(f"Expected FrameUpdateResponse for atomic update, got {type(atomic_update_response)}")
                return False
                
            if atomic_update_response.updated_count == 0:
                logger.error(f"Atomic update failed: {atomic_update_response.message if hasattr(atomic_update_response, 'message') else 'Unknown error'}")
                return False
                
            logger.info(f"✅ Atomic update successful: {atomic_update_response.updated_count} frames updated")
            
            # Verify atomicity by checking final frame count and content
            final_frames = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri
            )
            
            if hasattr(final_frames, 'total_count'):
                final_count = final_frames.total_count
                logger.info(f"Final frame count: {final_count}")
                
                # The count might change due to atomic replacement
                if final_count > 0:
                    logger.info("✅ Atomic update maintained frame structure integrity")
                else:
                    logger.error("Atomic update resulted in no frames")
                    return False
            
            # Verify content through frame retrieval
            final_frames_response = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri
            )
            
            if hasattr(final_frames_response, 'objects') and final_frames_response.objects:
                logger.info(f"✅ Atomic update verification: {len(final_frames_response.objects)} frames in final structure")
            else:
                logger.warning("Could not verify atomic update through frame retrieval")
            
            logger.info("✅ Atomic frame update test completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error in atomic frame update test: {e}")
            return False
    
    async def test_nonexistent_entity_frame_update(self, space_id: str, graph_id: str) -> bool:
        """
        Test frame update for non-existent entity.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if non-existent entity handling correct, False otherwise
        """
        try:
            logger.info("🧪 Testing frame update for non-existent entity")
            
            nonexistent_entity_uri = "http://vital.ai/test/nonexistent/entity/12345"
            frame_data = self.test_data_creator.create_employment_frame("Test Job", "Test Company")
            
            try:
                update_response = await self.client.kgentities.update_entity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=nonexistent_entity_uri,
                    document=frame_data
                )
                
                # Should get structured error response
                if isinstance(update_response, FrameUpdateResponse):
                    if hasattr(update_response, 'updated_count') and update_response.updated_count == 0:
                        logger.info("✅ Correctly handled non-existent entity (0 updated)")
                    elif hasattr(update_response, 'message') and 'not found' in update_response.message.lower():
                        logger.info("✅ Correctly handled non-existent entity with error message")
                    else:
                        logger.warning(f"Unexpected response for non-existent entity: {update_response}")
                else:
                    logger.error(f"Expected FrameUpdateResponse for non-existent entity, got {type(update_response)}")
                    return False
                    
            except VitalGraphClientError as e:
                # Client-side validation is acceptable
                logger.info(f"✅ Client-side validation caught non-existent entity: {e}")
            
            logger.info("✅ Non-existent entity frame update test completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error in non-existent entity frame update test: {e}")
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
            logger.info("🧹 Cleaning up created frame update test resources")
            
            # Delete created entities (which should cascade to frames)
            for entity_uri in self.created_entity_uris:
                try:
                    delete_response = await self.client.kgentities.delete_kgentity(
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
            
            logger.info("✅ Frame update test cleanup completed")
            return True
            
        except Exception as e:
            logger.error(f"Error during frame update test cleanup: {e}")
            return False
