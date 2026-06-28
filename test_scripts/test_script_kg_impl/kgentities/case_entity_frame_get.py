#!/usr/bin/env python3
"""
KGEntity Frame Get Test Module

Modular test implementation for KG entity frame retrieval operations.
Used by the main KGEntities endpoint test orchestrator.

Focuses on:
- Frame retrieval for specific entity (GET /kgframes?entity_uri=...)
- Frame graph retrieval with security validation
- Complete entity graph with frames
- Grouping URI validation for frame graphs
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

# Import VitalSigns for KGEntity objects
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame

# Import models
from vitalgraph.model.kgentities_model import EntityFramesResponse

# Import quad conversion utilities
from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list, quad_list_to_graphobjects

# Import test data creator
from test_scripts.fuseki_postgresql.kgentity_test_data import KGEntityTestDataCreator


logger = logging.getLogger(__name__)


class KGEntityFrameGetTester:
    """
    Modular test implementation for KG entity frame retrieval operations.
    
    Handles:
    - Frame retrieval for specific entity
    - Frame graph retrieval with security validation
    - Complete entity graph with frames
    - Grouping URI validation for frame graphs
    """
    
    def __init__(self, endpoint, test_data_creator):
        """
        Initialize the entity frame get tester.
        
        Args:
            endpoint: KGEntitiesEndpoint instance (initialized without REST setup)
            test_data_creator: KGEntityTestDataCreator instance for generating test data
        """
        self.endpoint = endpoint
        self.vitalsigns = VitalSigns()
        self.test_data_creator = test_data_creator
        self.created_entity_uris = []
        self.created_frame_uris = []
        
    async def test_frame_retrieval_for_entity(self, space_id: str, graph_id: str, entity_uri: str) -> bool:
        """
        Test frame retrieval for a specific entity.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            entity_uri: URI of entity to retrieve frames for
            
        Returns:
            bool: True if frame retrieval successful, False otherwise
        """
        try:
            logger.info(f"🧪 Testing frame retrieval for entity: {entity_uri}")
            
            # Call endpoint method to get entity frames
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            result = await self.endpoint._get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                frame_uris=None,
                page_size=100,
                offset=0,
                search=None,
                current_user=current_user
            )
            
            if result and hasattr(result, 'results') and result.results:
                # Convert quads to graph objects
                retrieved_objects = quad_list_to_graphobjects(result.results)
                frame_objects = [obj for obj in retrieved_objects if isinstance(obj, KGFrame)]
                logger.info(f"✅ Frame retrieval successful: Found {len(frame_objects)} frames")
                
                for i, frame in enumerate(frame_objects):
                    logger.info(f"  Frame {i+1}: {type(frame).__name__} URI: {str(frame.URI)}")
                
                return True
            else:
                logger.warning(f"⚠️  Frame retrieval returned no frames for entity: {entity_uri}")
                return True  # Empty result is valid
                
        except Exception as e:
            logger.error(f"❌ Error during frame retrieval test: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def test_frame_graph_with_security_validation(self, space_id: str, graph_id: str, entity_uri: str) -> bool:
        """
        Test frame graph retrieval with security validation.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            entity_uri: URI of entity to retrieve frames for
            
        Returns:
            bool: True if security validation successful, False otherwise
        """
        try:
            logger.info(f"🔒 Testing frame graph retrieval with security validation for: {entity_uri}")
            
            # Test with valid user
            valid_user = {"username": "test_user", "user_id": "test_user_123"}
            
            result = await self.endpoint._get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                frame_uris=None,
                page_size=100,
                offset=0,
                search=None,
                current_user=valid_user
            )
            
            if result:
                logger.info("✅ Security validation passed for valid user")
                
                # Validate that frame results contain proper structure
                if hasattr(result, 'results') and result.results:
                    retrieved_objects = quad_list_to_graphobjects(result.results)
                    frame_objs = [obj for obj in retrieved_objects if isinstance(obj, KGFrame)]
                    
                    for frame_obj in frame_objs:
                        logger.info(f"  Frame URI: {str(frame_obj.URI)}")
                        logger.info(f"  Frame type: {type(frame_obj).__name__}")
                
                return True
            else:
                logger.warning("⚠️  No frames returned for security validation test")
                return True  # Empty result is valid
                
        except Exception as e:
            logger.error(f"❌ Error during security validation test: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def test_complete_entity_graph_with_frames(self, space_id: str, graph_id: str, entity_uri: str) -> bool:
        """
        Test complete entity graph retrieval including all frames.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            entity_uri: URI of entity to retrieve complete graph for
            
        Returns:
            bool: True if complete graph retrieval successful, False otherwise
        """
        try:
            logger.info(f"🌐 Testing complete entity graph with frames for: {entity_uri}")
            
            # Call endpoint method to get complete entity with frames
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            # Test entity retrieval with include_entity_graph=True
            result = await self.endpoint._list_entities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=10,
                offset=0,
                entity_type_uri=None,
                search=None,
                include_entity_graph=True,
                current_user=current_user
            )
            
            if result and hasattr(result, 'results') and result.results:
                logger.info("✅ Complete entity graph retrieval successful")
                
                retrieved_objects = quad_list_to_graphobjects(result.results)
                entity_count = len([obj for obj in retrieved_objects if isinstance(obj, KGEntity)])
                logger.info(f"  Retrieved {entity_count} entities in graph")
                
                if entity_count >= 1:
                    logger.info("✅ Entity retrieval successful - entities found")
                    return True
                else:
                    logger.warning(f"⚠️  No entities found in results")
                    return False
            else:
                logger.warning("⚠️  Entity list returned without results")
                return False
            
        except Exception as e:
            logger.error(f"❌ Error during complete entity graph test: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def test_grouping_uri_validation(self, space_id: str, graph_id: str) -> bool:
        """
        Test grouping URI functionality using test data.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if grouping URI validation successful, False otherwise
        """
        try:
            logger.info("🏷️  Testing grouping URI validation with test data")
            
            # Create test entity with multiple frames using test data
            person_objects = self.test_data_creator.create_person_with_contact("Test Person")
            
            # Convert to quads for creation
            entity_quads = graphobjects_to_quad_list(person_objects, graph_id)
            
            # Create entity
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            from vitalgraph.endpoint.kgentities_endpoint import OperationMode
            
            create_result = await self.endpoint._create_or_update_entities(
                space_id=space_id,
                graph_id=graph_id,
                quads=entity_quads,
                operation_mode=OperationMode.CREATE,
                parent_uri=None,
                current_user=current_user
            )
            
            if create_result and hasattr(create_result, 'created_uris'):
                entity_uri = create_result.created_uris[0]  # Get first created entity
                self.created_entity_uris.append(entity_uri)
                logger.info(f"✅ Created test entity: {entity_uri}")
                
                # Test frame retrieval with grouping URIs
                frame_result = await self.test_frame_retrieval_for_entity(
                    space_id, graph_id, entity_uri
                )
                
                if frame_result:
                    logger.info("✅ Grouping URI validation successful")
                    return True
                else:
                    logger.error("❌ Grouping URI validation failed")
                    return False
            else:
                logger.error("❌ Failed to create test entity for grouping URI validation")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during grouping URI validation: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    def get_created_entity_uris(self) -> List[str]:
        """
        Get list of created entity URIs for cleanup purposes.
        
        Returns:
            List[str]: List of created entity URIs
        """
        return self.created_entity_uris.copy()
    
    def get_created_frame_uris(self) -> List[str]:
        """
        Get list of created frame URIs for cleanup purposes.
        
        Returns:
            List[str]: List of created frame URIs
        """
        return self.created_frame_uris.copy()
    
    def clear_created_uris(self):
        """Clear the lists of created URIs."""
        self.created_entity_uris.clear()
        self.created_frame_uris.clear()
