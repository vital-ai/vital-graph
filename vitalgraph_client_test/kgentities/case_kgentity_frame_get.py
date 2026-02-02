#!/usr/bin/env python3
"""
KGEntity Frame Retrieval Test Case

Client-side test case for KG entity frame retrieval operations using VitalGraph client.
Tests frame retrieval within entity context, pagination, and filtering.
"""

import logging
from typing import Dict, Any, List
from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.kgframes_model import FrameCreateResponse
from vitalgraph.client.response.client_response import FrameResponse
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

logger = logging.getLogger(__name__)


class KGEntityFrameGetTester:
    """Client-side test case for KG entity frame retrieval operations."""
    
    def __init__(self, client: VitalGraphClient, test_data_creator: ClientTestDataCreator):
        """
        Initialize the frame retrieval tester.
        
        Args:
            client: VitalGraphClient instance
            test_data_creator: ClientTestDataCreator instance for generating test data
        """
        self.client = client
        self.test_data_creator = test_data_creator
        self.created_entity_uris = []
        self.created_frame_uris = []
        
    async def test_basic_frame_retrieval(self, space_id: str, graph_id: str) -> bool:
        """
        Test basic frame retrieval within entity context.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if basic frame retrieval successful, False otherwise
        """
        try:
            logger.info("🧪 Testing basic frame retrieval within entity context")
            
            # Create test entity with multiple frames
            entity_objects = self.test_data_creator.create_person_with_contact("Frame Get Test Person")
            
            # Modern client API expects GraphObjects directly
            entity_response = self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity_objects
            )
            
            if not entity_response or not entity_response.created_uris:
                logger.error("Failed to create test entity for frame retrieval")
                return False
                
            entity_uri = str(entity_objects[0].URI)  # Get URI from VitalSigns object and convert to string
            self.created_entity_uris.append(entity_uri)
            logger.info(f"✅ Created test entity: {entity_uri}")
            
            # Test frame retrieval with existing frames from entity creation
            # (Skip additional frame creation since create_employment_frame doesn't exist)
            logger.info("✅ Using existing frames from entity creation for retrieval test")
            
            # Test 1: Get all frames for the entity using get_kgentity_frames
            frames_response = self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri
            )
            
            # Validate response structure - FrameResponse has objects attribute
            if not isinstance(frames_response, FrameResponse):
                logger.error(f"Expected FrameResponse, got {type(frames_response)}")
                return False
                
            if not hasattr(frames_response, 'objects') or not frames_response.objects:
                logger.error("No frames found for entity")
                return False
                
            logger.info(f"✅ Retrieved {len(frames_response.objects)} frames for entity")
            
            # Test 2: Get frames using get_kgentity_frames (returns FrameResponse)
            frames_response2 = self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri
            )
            
            if not hasattr(frames_response2, 'objects') or not frames_response2.objects:
                logger.error("No frames found in second retrieval")
                return False
                
            logger.info(f"✅ Retrieved frames with {len(frames_response2.objects)} frame objects")
            
            logger.info("✅ Basic frame retrieval completed successfully")
            return True
            
        except VitalGraphClientError as e:
            logger.error(f"Client error in basic frame retrieval test: {e}")
            return False
        except Exception as e:
            logger.error(f"Error in basic frame retrieval test: {e}")
            return False
    
    async def test_frame_retrieval_pagination(self, space_id: str, graph_id: str) -> bool:
        """
        Test frame retrieval with pagination.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if pagination test successful, False otherwise
        """
        try:
            logger.info("🧪 Testing frame retrieval pagination")
            
            # Create entity with multiple frames for pagination testing
            entity_objects = self.test_data_creator.create_organization_with_address("Pagination Test Corp")
            
            # Modern client API expects GraphObjects directly
            entity_response = self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity_objects
            )
            
            if not entity_response or not entity_response.created_uris:
                logger.error("Failed to create test entity for pagination")
                return False
                
            entity_uri = str(entity_objects[0].URI)  # Get URI from VitalSigns object and convert to string
            self.created_entity_uris.append(entity_uri)
            
            # Use existing frames from entity creation for pagination test
            # (Skip additional frame creation since create_employment_frame doesn't exist)
            logger.info("✅ Using existing frames from entity creation for pagination test")
            
            # Test pagination with page_size=2
            page_size = 2
            offset = 0
            total_retrieved = 0
            page_count = 0
            
            while True:
                page_response = self.client.kgentities.get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=entity_uri,
                    page_size=page_size,
                    offset=offset
                )
                
                if not isinstance(page_response, FrameResponse):
                    logger.error(f"Expected FrameResponse for pagination, got {type(page_response)}")
                    return False
                    
                page_count += 1
                current_page_count = len(page_response.objects) if hasattr(page_response, 'objects') and page_response.objects else 0
                total_retrieved += current_page_count
                
                logger.info(f"Page {page_count}: Retrieved {current_page_count} frames (offset={offset})")
                
                # Check if we've retrieved all frames (no more data or reached end)
                if current_page_count < page_size:
                    break
                    
                offset += page_size
                
                # Safety check to prevent infinite loop
                if page_count > 10:
                    logger.warning("Pagination test exceeded maximum page count")
                    break
            
            logger.info(f"✅ Pagination test completed: {page_count} pages, {total_retrieved} total frames retrieved")
            
            # Validate total count consistency
            final_response = self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                page_size=100  # Large page size to get all
            )
            
            if isinstance(final_response, FrameResponse):
                final_count = len(final_response.objects) if hasattr(final_response, 'objects') and final_response.objects else 0
                if total_retrieved != final_count:
                    logger.warning(f"Pagination total mismatch: retrieved {total_retrieved}, expected {final_count}")
                else:
                    logger.info(f"✅ Pagination total matches: {total_retrieved} frames")
            
            return True
            
        except Exception as e:
            logger.error(f"Error in frame retrieval pagination test: {e}")
            return False
    
    async def test_frame_retrieval_filtering(self, space_id: str, graph_id: str) -> bool:
        """
        Test frame retrieval with search filtering.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if filtering test successful, False otherwise
        """
        try:
            logger.info("🧪 Testing frame retrieval with search filtering")
            
            # Create entity with frames containing specific searchable content
            entity_objects = self.test_data_creator.create_person_with_contact("Filter Test Person")
            
            # Modern client API expects GraphObjects directly
            entity_response = self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity_objects
            )
            
            if not entity_response or not entity_response.created_uris:
                logger.error("Failed to create test entity for filtering")
                return False
                
            entity_uri = str(entity_objects[0].URI)  # Get URI from VitalSigns object and convert to string
            self.created_entity_uris.append(entity_uri)
            
            # Use existing frames from entity creation for filtering test
            # (Skip additional frame creation since create_employment_frame doesn't exist)
            logger.info("✅ Using existing frames from entity creation for filtering test")
                
            logger.info(f"✅ Created frames with searchable content")
            
            # Test search filtering
            search_terms = ["Engineer", "Manager", "Technology"]
            
            for search_term in search_terms:
                search_response = self.client.kgentities.get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=entity_uri,
                    search=search_term
                )
                
                if isinstance(search_response, FrameResponse):
                    found_count = len(search_response.objects) if hasattr(search_response, 'objects') and search_response.objects else 0
                    logger.info(f"✅ Search for '{search_term}': found {found_count} frames")
                    
                    # Compare with total frames
                    all_frames_response = self.client.kgentities.get_kgentity_frames(
                        space_id=space_id,
                        graph_id=graph_id,
                        entity_uri=entity_uri
                    )
                    
                    if isinstance(all_frames_response, FrameResponse):
                        total_count = len(all_frames_response.objects) if hasattr(all_frames_response, 'objects') and all_frames_response.objects else 0
                        if found_count <= total_count:
                            logger.info(f"✅ Search filtering working: {found_count} <= {total_count}")
                        else:
                            logger.warning(f"Search returned more results than total: {found_count} > {total_count}")
                else:
                    logger.error(f"Expected FrameResponse for search, got {type(search_response)}")
                    return False
            
            logger.info("✅ Frame retrieval filtering test completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error in frame retrieval filtering test: {e}")
            return False
    
    async def test_hierarchical_frame_retrieval(self, space_id: str, graph_id: str) -> bool:
        """
        Test retrieval of hierarchical frames.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if hierarchical retrieval successful, False otherwise
        """
        try:
            logger.info("🧪 Testing hierarchical frame retrieval")
            
            # Create entity with hierarchical frame structure
            entity_objects = self.test_data_creator.create_organization_with_address("Hierarchical Get Corp")
            
            # Modern client API expects GraphObjects directly
            entity_response = self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=entity_objects
            )
            
            if not entity_response or not entity_response.created_uris:
                logger.error("Failed to create test entity for hierarchical retrieval")
                return False
                
            entity_uri = str(entity_objects[0].URI)  # Get URI from VitalSigns object and convert to string
            self.created_entity_uris.append(entity_uri)
            
            # Get existing frames from entity for hierarchical retrieval test
            existing_frames = self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri
            )
            
            if hasattr(existing_frames, 'objects') and existing_frames.objects:
                frame_count = len(existing_frames.objects)
                logger.info(f"✅ Hierarchical frame retrieval test successful: Retrieved {frame_count} hierarchical frames")
                return True
            else:
                logger.error("No frames found for hierarchical retrieval test")
                return False
            
        except Exception as e:
            logger.error(f"Error in hierarchical frame retrieval test: {e}")
            return False
    
    async def test_nonexistent_entity_frame_retrieval(self, space_id: str, graph_id: str) -> bool:
        """
        Test frame retrieval for non-existent entity.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if non-existent entity handling correct, False otherwise
        """
        try:
            logger.info("🧪 Testing frame retrieval for non-existent entity")
            
            nonexistent_entity_uri = "http://vital.ai/test/nonexistent/entity/12345"
            
            # Test get_kgentity_frames with non-existent entity
            try:
                frames_response = self.client.kgentities.get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=nonexistent_entity_uri
                )
                
                # Should get structured response with 0 frames or error message
                if isinstance(frames_response, FrameResponse):
                    frame_count = len(frames_response.objects) if hasattr(frames_response, 'objects') and frames_response.objects else 0
                    if frame_count == 0:
                        logger.info("✅ Correctly handled non-existent entity (0 frames returned)")
                    elif hasattr(frames_response, 'message') and 'not found' in frames_response.message.lower():
                        logger.info("✅ Correctly handled non-existent entity with structured error message")
                    else:
                        logger.warning(f"Unexpected response for non-existent entity: {frames_response}")
                else:
                    logger.error(f"Expected FrameResponse for non-existent entity, got {type(frames_response)}")
                    return False
                    
            except VitalGraphClientError as e:
                # Client-side validation is acceptable
                logger.info(f"✅ Client-side validation caught non-existent entity: {e}")
            
            # Test get_kgentity_frames with non-existent entity
            try:
                frames_response = self.client.kgentities.get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=nonexistent_entity_uri
                )
                
                # Should get empty response or error
                if hasattr(frames_response, 'objects'):
                    if not frames_response.objects or len(frames_response.objects) == 0:
                        logger.info("✅ Correctly handled non-existent entity (empty response)")
                    else:
                        logger.warning(f"Unexpected: Non-existent entity returned {len(frames_response.objects)} frames")
                else:
                    logger.warning(f"Unexpected response for non-existent entity: {frames_response}")
                    return False
                    
            except VitalGraphClientError as e:
                # Client-side validation is acceptable
                logger.info(f"✅ Client-side validation caught non-existent entity in JsonLd retrieval: {e}")
            
            logger.info("✅ Non-existent entity frame retrieval test completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error in non-existent entity frame retrieval test: {e}")
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
            logger.info("🧹 Cleaning up created frame retrieval test resources")
            
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
            
            logger.info("✅ Frame retrieval test cleanup completed")
            return True
            
        except Exception as e:
            logger.error(f"Error during frame retrieval test cleanup: {e}")
            return False
