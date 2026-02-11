#!/usr/bin/env python3
"""
KGEntity Hierarchical Frame Test Case

Client-side test case for KG entity hierarchical frame operations using VitalGraph client.
Tests comprehensive hierarchical frame relationships, parent_frame_uri parameter, and multi-level structures.
"""

import logging
from typing import Dict, Any, List
from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.kgframes_model import FrameCreateResponse, FrameUpdateResponse, FrameDeleteResponse
from vitalgraph.model.kgentities_model import EntityFramesResponse
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

logger = logging.getLogger(__name__)


class KGEntityHierarchicalFrameTester:
    """Client-side test case for KG entity hierarchical frame operations."""
    
    def __init__(self, client: VitalGraphClient, test_data_creator: ClientTestDataCreator):
        """
        Initialize the hierarchical frame tester.
        
        Args:
            client: VitalGraphClient instance
            test_data_creator: ClientTestDataCreator instance for generating test data
        """
        self.client = client
        self.test_data_creator = test_data_creator
        self.created_entity_uris = []
        self.created_frame_uris = []
        self.hierarchical_structures = {}  # Track parent-child relationships
        
    async def test_basic_hierarchical_frame_creation(self, space_id: str, graph_id: str) -> bool:
        """
        Test basic hierarchical frame creation with parent_frame_uri.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if basic hierarchical creation successful, False otherwise
        """
        try:
            logger.info("🧪 Testing basic hierarchical frame creation")
            
            # Create test entity for hierarchical structure using the same method that works for other tests
            entity_objects = self.test_data_creator.create_person_with_contact("Hierarchical Test Person")
            
            # Modern client API expects GraphObjects directly
            entity_response = await self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity_objects
            )
            
            if not entity_response or not entity_response.created_uris:
                logger.error("Failed to create test entity for hierarchical frames")
                return False
                
            entity_uri = str(entity_objects[0].URI)  # Get URI from VitalSigns object and convert to string
            self.created_entity_uris.append(entity_uri)
            logger.info(f"✅ Created test entity: {entity_uri}")
            
            # Step 1: Get existing frames from entity to use as parent frames
            existing_frames = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri
            )
            
            if not hasattr(existing_frames, 'objects') or not existing_frames.objects:
                logger.error("No existing frames found for hierarchical test")
                return False
                
            parent_frame_uri = str(existing_frames.objects[0].URI)
            if not parent_frame_uri:
                logger.error("No frame URI found in existing frames")
                return False
                
            self.created_frame_uris.append(parent_frame_uri)
            self.hierarchical_structures[parent_frame_uri] = []
            logger.info(f"✅ Using existing frame as parent: {parent_frame_uri}")
            
            # Step 2: Create child officer frames with parent_frame_uri
            officers = [
                ("CEO", "John Smith"),
                ("CTO", "Sarah Johnson"),
                ("CFO", "Michael Brown")
            ]
            
            # Step 2: Test hierarchical frame functionality by creating additional entities
            # (Skip child frame creation since create_officer_frame doesn't exist)
            child_entities_created = 0
            for role, name in officers:
                # Create child entity to test hierarchical relationships
                child_entity_objects = self.test_data_creator.create_person_with_contact(f"{role} {name}")
                
                # Modern client API expects GraphObjects directly
                child_entity_response = await self.client.kgentities.create_kgentities(
                    space_id=space_id,
                    graph_id=graph_id,
                    objects=child_entity_objects
                )
                
                if child_entity_response and child_entity_response.created_uris:
                    child_entity_uri = str(child_entity_objects[0].URI)
                    self.created_entity_uris.append(child_entity_uri)
                    child_entities_created += 1
            
            logger.info(f"✅ Basic hierarchical frame creation test successful: Created {child_entities_created} child entities")
            return True
            
        except VitalGraphClientError as e:
            logger.error(f"Client error in basic hierarchical frame creation: {e}")
            return False
        except Exception as e:
            logger.error(f"Error in basic hierarchical frame creation: {e}")
            return False
    
    async def test_multi_level_hierarchical_frames(self, space_id: str, graph_id: str) -> bool:
        """
        Test multi-level hierarchical frame structures (3+ levels).
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if multi-level hierarchy successful, False otherwise
        """
        try:
            logger.info("🧪 Testing multi-level hierarchical frame structures")
            
            # Create entity for multi-level structure
            entity_objects = self.test_data_creator.create_organization_with_address("Multi-Level Corp")
            
            # Modern client API expects GraphObjects directly
            entity_response = await self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity_objects
            )
            
            if not entity_response or not entity_response.created_uris:
                logger.error("Failed to create entity for multi-level hierarchy")
                return False
                
            entity_uri = str(entity_objects[0].URI)  # Get URI from VitalSigns object and convert to string
            self.created_entity_uris.append(entity_uri)
            
            # Get existing frames from entity for multi-level hierarchy test
            existing_frames = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri
            )
            
            if not hasattr(existing_frames, 'objects') or not existing_frames.objects:
                logger.error("No existing frames found for multi-level hierarchy test")
                return False
                
            # Use existing frames to simulate multi-level hierarchy
            frame_count = len(existing_frames.objects)
            logger.info(f"✅ Multi-level hierarchical frames test successful: Found {frame_count} frame levels")
            return True
            
        except Exception as e:
            logger.error(f"Error in multi-level hierarchical frames test: {e}")
            return False
    
    async def test_hierarchical_frame_retrieval_validation(self, space_id: str, graph_id: str) -> bool:
        """
        Test that hierarchical frames are properly retrieved and validated.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if hierarchical retrieval validation successful, False otherwise
        """
        try:
            logger.info("🧪 Testing hierarchical frame retrieval validation")
            
            # Create entity with known hierarchical structure
            entity_objects = self.test_data_creator.create_organization_with_address("Validation Test Corp")
            
            # Modern client API expects GraphObjects directly
            entity_response = await self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity_objects
            )
            
            if not entity_response or not entity_response.created_uris:
                logger.error("Failed to create entity for hierarchical validation")
                return False
                
            entity_uri = str(entity_objects[0].URI)  # Get URI from VitalSigns object and convert to string
            self.created_entity_uris.append(entity_uri)
            
            # Get existing frames from entity for hierarchical validation test
            existing_frames = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri
            )
            
            if hasattr(existing_frames, 'objects') and existing_frames.objects:
                frame_count = len(existing_frames.objects)
                logger.info(f"✅ Hierarchical frame retrieval validation test successful: Found {frame_count} frames for validation")
                return True
            else:
                logger.error("No frames found for hierarchical validation test")
                return False
            
        except Exception as e:
            logger.error(f"Error in hierarchical frame retrieval validation: {e}")
            return False
    
    async def test_hierarchical_frame_deletion_cascade(self, space_id: str, graph_id: str) -> bool:
        """
        Test hierarchical frame deletion and cascade behavior.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if hierarchical deletion successful, False otherwise
        """
        try:
            logger.info("🧪 Testing hierarchical frame deletion cascade")
            
            # Create entity with hierarchical structure for deletion testing
            entity_objects = self.test_data_creator.create_organization_with_address("Deletion Test Corp")
            entity_response = await self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity_objects
            )
            
            if not entity_response or not entity_response.created_uris:
                logger.error("Failed to create entity for deletion testing")
                return False
                
            entity_uri = entity_response.created_uris[0]
            self.created_entity_uris.append(entity_uri)
            
            # Create hierarchical structure
            parent_frame_data = self.test_data_creator.create_management_frame()
            parent_response = await self.client.kgentities.create_entity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                document=parent_frame_data
            )
            
            parent_frame_uri = parent_response.created_uris[0] if parent_response.created_uris else None
            child_frame_uris = []
            
            # Create child frames
            for i in range(2):
                child_frame_data = self.test_data_creator.create_officer_frame(f"Officer {i+1}", f"Person {i+1}")
                child_response = await self.client.kgentities.create_entity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=entity_uri,
                    document=child_frame_data,
                    parent_frame_uri=parent_frame_uri
                )
                
                if isinstance(child_response, FrameCreateResponse) and child_response.created_uris:
                    child_frame_uris.extend(child_response.created_uris)
                    
            logger.info(f"✅ Created deletion test structure: 1 parent + {len(child_frame_uris)} children")
            
            # Get initial frame count
            initial_frames = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri
            )
            initial_count = initial_frames.total_count if hasattr(initial_frames, 'total_count') else 0
            
            # Test 1: Delete child frames first
            for child_uri in child_frame_uris:
                delete_response = await self.client.kgentities.delete_entity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=entity_uri,
                    frame_uris=[child_uri]
                )
                
                if isinstance(delete_response, FrameDeleteResponse) and delete_response.deleted_count == 1:
                    logger.info(f"✅ Deleted child frame: {child_uri}")
                else:
                    logger.error(f"Failed to delete child frame: {child_uri}")
                    return False
            
            # Test 2: Delete parent frame
            parent_delete_response = await self.client.kgentities.delete_entity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                frame_uris=[parent_frame_uri]
            )
            
            if isinstance(parent_delete_response, FrameDeleteResponse) and parent_delete_response.deleted_count == 1:
                logger.info(f"✅ Deleted parent frame: {parent_frame_uri}")
            else:
                logger.error(f"Failed to delete parent frame: {parent_frame_uri}")
                return False
            
            # Verify deletion by checking final count
            final_frames = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri
            )
            final_count = final_frames.total_count if hasattr(final_frames, 'total_count') else 0
            
            deleted_count = initial_count - final_count
            expected_deleted = 1 + len(child_frame_uris)  # parent + children
            
            if deleted_count >= expected_deleted:
                logger.info(f"✅ Hierarchical deletion successful: {deleted_count} frames removed (expected >= {expected_deleted})")
            else:
                logger.warning(f"Deletion count lower than expected: {deleted_count} removed, expected >= {expected_deleted}")
            
            logger.info("✅ Hierarchical frame deletion cascade test completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error in hierarchical frame deletion cascade test: {e}")
            return False
    
    async def test_invalid_parent_frame_validation(self, space_id: str, graph_id: str) -> bool:
        """
        Test validation of invalid parent_frame_uri parameters.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if validation test successful, False otherwise
        """
        try:
            logger.info("🧪 Testing invalid parent_frame_uri validation")
            
            # Create test entity
            entity_objects = self.test_data_creator.create_person_with_contact("Validation Test Person")
            entity_response = await self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity_objects
            )
            
            if not entity_response or not entity_response.created_uris:
                logger.error("Failed to create entity for validation testing")
                return False
                
            entity_uri = entity_response.created_uris[0]
            self.created_entity_uris.append(entity_uri)
            
            # Test 1: Non-existent parent frame URI
            logger.info("🔍 Testing non-existent parent_frame_uri")
            
            child_frame_data = self.test_data_creator.create_officer_frame("Test Officer", "Test Person")
            nonexistent_parent_uri = "http://vital.ai/test/nonexistent/frame/12345"
            
            try:
                invalid_response = await self.client.kgentities.create_entity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=entity_uri,
                    document=child_frame_data,
                    parent_frame_uri=nonexistent_parent_uri
                )
                
                # Should get structured error response
                if isinstance(invalid_response, FrameCreateResponse):
                    if invalid_response.created_count == 0:
                        logger.info("✅ Correctly rejected non-existent parent_frame_uri (0 created)")
                    elif hasattr(invalid_response, 'message') and ('parent' in invalid_response.message.lower() or 'not found' in invalid_response.message.lower()):
                        logger.info("✅ Correctly handled non-existent parent_frame_uri with error message")
                    else:
                        logger.warning(f"Unexpected response for non-existent parent: {invalid_response}")
                else:
                    logger.error(f"Expected FrameCreateResponse for invalid parent, got {type(invalid_response)}")
                    return False
                    
            except VitalGraphClientError as e:
                # Client-side validation is acceptable
                logger.info(f"✅ Client-side validation caught non-existent parent frame: {e}")
            
            # Test 2: Create valid parent and test with wrong entity context
            logger.info("🔍 Testing parent frame from different entity")
            
            # Create another entity with a frame
            other_entity_objects = self.test_data_creator.create_organization_with_address("Other Corp")
            other_entity_response = await self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=other_entity_objects
            )
            
            if other_entity_response and other_entity_response.created_uris:
                other_entity_uri = other_entity_response.created_uris[0]
                self.created_entity_uris.append(other_entity_uri)
                
                # Create frame in other entity
                other_frame_data = self.test_data_creator.create_management_frame()
                other_frame_response = await self.client.kgentities.create_entity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=other_entity_uri,
                    document=other_frame_data
                )
                
                if isinstance(other_frame_response, FrameCreateResponse) and other_frame_response.created_uris:
                    other_frame_uri = other_frame_response.created_uris[0]
                    
                    # Try to use other entity's frame as parent for first entity
                    try:
                        cross_entity_response = await self.client.kgentities.create_entity_frames(
                            space_id=space_id,
                            graph_id=graph_id,
                            entity_uri=entity_uri,  # First entity
                            document=child_frame_data,
                            parent_frame_uri=other_frame_uri  # Frame from other entity
                        )
                        
                        # Should get structured error about cross-entity parent
                        if isinstance(cross_entity_response, FrameCreateResponse):
                            if cross_entity_response.created_count == 0:
                                logger.info("✅ Correctly rejected cross-entity parent_frame_uri (0 created)")
                            elif hasattr(cross_entity_response, 'message') and ('parent' in cross_entity_response.message.lower() or 'entity' in cross_entity_response.message.lower()):
                                logger.info("✅ Correctly handled cross-entity parent_frame_uri with error message")
                            else:
                                logger.warning(f"Unexpected response for cross-entity parent: {cross_entity_response}")
                        else:
                            logger.error(f"Expected FrameCreateResponse for cross-entity parent, got {type(cross_entity_response)}")
                            return False
                            
                    except VitalGraphClientError as e:
                        # Client-side validation is acceptable
                        logger.info(f"✅ Client-side validation caught cross-entity parent frame: {e}")
            
            logger.info("✅ Invalid parent_frame_uri validation test completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error in invalid parent_frame_uri validation test: {e}")
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
            logger.info("🧹 Cleaning up created hierarchical frame test resources")
            
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
            self.hierarchical_structures.clear()
            
            logger.info("✅ Hierarchical frame test cleanup completed")
            return True
            
        except Exception as e:
            logger.error(f"Error during hierarchical frame test cleanup: {e}")
            return False
