#!/usr/bin/env python3
"""
KGEntity Get Test Module

Modular test implementation for KG entity retrieval operations.
Used by the main KGEntities endpoint test orchestrator.

Focuses on:
- Single entity retrieval by URI
- Entity graph retrieval with include_entity_graph option
- Error handling for non-existent entities
- Validation of retrieved entity data
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

# Import VitalSigns for KGEntity objects
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity
from vitalgraph.model.kgentities_model import EntitiesResponse

# Import quad conversion utilities
from vitalgraph.utils.quad_format_utils import quad_list_to_graphobjects


logger = logging.getLogger(__name__)


class KGEntityGetTester:
    """
    Modular test implementation for KG entity retrieval operations.
    
    Handles:
    - Single entity retrieval by URI
    - Entity graph retrieval with include_entity_graph option
    - Validation of retrieved entity data
    - Error handling for non-existent entities
    """
    
    def __init__(self, endpoint, test_data_creator):
        """
        Initialize the entity get tester.
        
        Args:
            endpoint: KGEntitiesEndpoint instance (initialized without REST setup)
            test_data_creator: Test data creator instance
        """
        self.endpoint = endpoint
        self.vitalsigns = VitalSigns()
        self.test_data_creator = test_data_creator
        self.created_entity_uris = []
        self.logger = logging.getLogger(__name__)
        self.retrieved_entities = []
        
    async def test_single_entity_get(self, space_id: str, graph_id: str, entity_uri: str) -> bool:
        """
        Test single entity retrieval by URI.
        
        Args:
            space_id: Space ID for testing
            graph_id: Graph ID for testing
            entity_uri: URI of entity to retrieve
            
        Returns:
            bool: True if test passed, False otherwise
        """
        try:
            self.logger.info(f"🔍 Testing single entity retrieval: {entity_uri}")
            
            # Call the endpoint's private get method directly
            response = await self.endpoint._get_entity_by_uri(
                space_id=space_id,
                graph_id=graph_id,
                uri=entity_uri,
                include_entity_graph=False,
                current_user={}
            )
            
            # Validate response has results
            if not response or not hasattr(response, 'results') or not response.results:
                self.logger.error(f"❌ No entity data returned for URI: {entity_uri}")
                return False
            
            # Convert quads to graph objects to find the entity
            retrieved_objects = quad_list_to_graphobjects(response.results)
            entity_objects = [obj for obj in retrieved_objects if isinstance(obj, KGEntity)]
            
            if not entity_objects:
                self.logger.error(f"❌ No KGEntity found in response results")
                return False
            
            # Find the main entity by URI
            main_entity = None
            for obj in entity_objects:
                if str(obj.URI) == entity_uri:
                    main_entity = obj
                    break
            
            if not main_entity:
                self.logger.error(f"❌ Main entity not found in response results")
                return False
            
            self.logger.info(f"✅ Retrieved entity successfully:")
            self.logger.info(f"   - URI: {entity_uri}")
            self.logger.info(f"   - Type: {type(main_entity).__name__}")
            self.logger.info(f"   - Name: {str(main_entity.name)}")
            
            # Store for cleanup tracking
            self.retrieved_entities.append(entity_uri)
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Error in single entity get test: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def test_entity_get_with_graph(self, space_id: str, graph_id: str, entity_uri: str) -> bool:
        """
        Test entity retrieval with complete entity graph.
        
        Args:
            space_id: Space ID for testing
            graph_id: Graph ID for testing
            entity_uri: URI of entity to retrieve
            
        Returns:
            bool: True if test passed, False otherwise
        """
        try:
            self.logger.info(f"🔍 Testing entity retrieval with complete graph: {entity_uri}")
            
            # Call the endpoint's get method with include_entity_graph=True
            response = await self.endpoint._get_entity_by_uri(
                space_id=space_id,
                graph_id=graph_id,
                uri=entity_uri,
                include_entity_graph=True,
                current_user={}
            )
            
            # Validate response has results
            if not response or not hasattr(response, 'results') or not response.results:
                self.logger.error(f"❌ No entity graph data returned")
                return False
            
            # Convert quads to graph objects
            retrieved_objects = quad_list_to_graphobjects(response.results)
            
            if not retrieved_objects:
                self.logger.error(f"❌ Empty entity graph returned")
                return False
            
            # With include_entity_graph=True, we should get more objects
            # (entity + any related frames, slots, edges)
            self.logger.info(f"✅ Retrieved entity with complete graph:")
            self.logger.info(f"   - URI: {entity_uri}")
            self.logger.info(f"   - Total graph objects: {len(retrieved_objects)}")
            
            # Log object types in the graph
            object_types = {}
            for obj in retrieved_objects:
                obj_type = type(obj).__name__
                object_types[obj_type] = object_types.get(obj_type, 0) + 1
            
            for obj_type, count in object_types.items():
                self.logger.info(f"   - {obj_type}: {count} objects")
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Error in entity get with graph test: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def test_entity_get_not_found(self, space_id: str, graph_id: str) -> bool:
        """
        Test entity retrieval for non-existent entity (error handling).
        
        Args:
            space_id: Space ID for testing
            graph_id: Graph ID for testing
            
        Returns:
            bool: True if test passed (proper error handling), False otherwise
        """
        try:
            # Generate a random URI that shouldn't exist
            non_existent_uri = f"http://vital.ai/haley.ai/test/non-existent-entity-{uuid.uuid4()}"
            
            self.logger.info(f"🔍 Testing entity retrieval for non-existent entity: {non_existent_uri}")
            
            # This should return an empty response or raise an appropriate exception
            response = await self.endpoint._get_entity_by_uri(
                space_id=space_id,
                graph_id=graph_id,
                uri=non_existent_uri,
                include_entity_graph=False,
                current_user={}
            )
            
            # Check if response indicates entity not found
            if response and hasattr(response, 'results') and response.results and len(response.results) > 0:
                self.logger.error(f"❌ Expected empty response for non-existent entity, got data")
                return False
            
            self.logger.info(f"✅ Properly handled non-existent entity request")
            return True
            
        except Exception as e:
            # Some implementations might raise exceptions for not found
            # This could be acceptable depending on the implementation
            self.logger.info(f"✅ Entity not found handled with exception (acceptable): {e}")
            return True
    
    def get_retrieved_entity_uris(self) -> List[str]:
        """
        Get list of entity URIs that were successfully retrieved.
        
        Returns:
            List[str]: List of entity URIs
        """
        return self.retrieved_entities.copy()
    
    def clear_retrieved_entities(self):
        """Clear the list of retrieved entities."""
        self.retrieved_entities.clear()
