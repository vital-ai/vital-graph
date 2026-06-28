#!/usr/bin/env python3
"""
KGEntity List Test Module

Modular test implementation for KG entity listing operations.
Used by the main KGEntities endpoint test orchestrator.

Focuses on:
- Entity listing with pagination
- Entity filtering by type
- Entity search functionality
- Empty state handling
- Response validation
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

# Import VitalSigns for KGEntity objects
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity

# Import models
from vitalgraph.model.kgentities_model import EntitiesResponse

logger = logging.getLogger(__name__)


class KGEntityListTester:
    """
    Modular test implementation for KG entity listing operations.
    
    Handles:
    - Entity listing with pagination
    - Entity filtering and search
    - Response validation
    - Empty state testing
    """
    
    def __init__(self, endpoint, test_data_creator):
        """
        Initialize the entity list tester.
        
        Args:
            endpoint: KGEntitiesEndpoint instance (initialized without REST setup)
            test_data_creator: KGEntityTestDataCreator instance for generating test data
        """
        self.endpoint = endpoint
        self.vitalsigns = VitalSigns()
        self.test_data_creator = test_data_creator
        self.created_entity_uris = []
        
    async def test_list_entities_empty(self, space_id: str, graph_id: str) -> bool:
        """Test listing entities when no entities exist."""
        try:
            logger.info("🧪 Testing empty entity listing...")
            
            # List entities in empty graph
            result = await self.endpoint._list_entities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=10,
                offset=0,
                entity_type_uri=None,
                search=None,
                include_entity_graph=False,
                current_user={"username": "test_user"}
            )
            
            if not isinstance(result, EntitiesResponse):
                logger.error("Expected EntitiesResponse")
                return False
            
            # Check results from quad-based response
            actual_count = len(result.results) if hasattr(result, 'results') and result.results else 0
            
            if actual_count != 0:
                logger.error(f"Expected empty entity list, got {actual_count}")
                return False
            
            logger.info("✅ Empty entity listing test passed")
            return True
            
        except Exception as e:
            logger.error(f"Error in empty entity listing test: {e}")
            return False
    
    async def test_list_entities_populated(self, space_id: str, graph_id: str, expected_count: int) -> bool:
        """Test listing entities when entities exist."""
        try:
            logger.info(f"🧪 Testing populated entity listing (expecting {expected_count} entities)...")
            
            # List entities
            result = await self.endpoint._list_entities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=10,
                offset=0,
                entity_type_uri=None,
                search=None,
                include_entity_graph=False,
                current_user={"username": "test_user"}
            )
            
            if not isinstance(result, EntitiesResponse):
                logger.error("Expected EntitiesResponse")
                return False
            
            # Check results from quad-based response
            actual_count = len(result.results) if hasattr(result, 'results') and result.results else 0
            
            if actual_count != expected_count:
                logger.error(f"Expected {expected_count} entities, got {actual_count}")
                return False
            
            logger.info("✅ Populated entity listing test passed")
            return True
            
        except Exception as e:
            logger.error(f"Error in populated entity listing test: {e}")
            return False
    
    async def test_list_entities_with_pagination(self, space_id: str, graph_id: str) -> bool:
        """Test entity listing with pagination."""
        try:
            logger.info("🧪 Testing entity listing with pagination...")
            
            # Test first page
            page1_result = await self.endpoint._list_entities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=2,
                offset=0,
                entity_type_uri=None,
                search=None,
                include_entity_graph=False,
                current_user={"username": "test_user"}
            )
            
            if not isinstance(page1_result, EntitiesResponse):
                logger.error("Expected EntitiesResponse for page 1")
                return False
            
            # Test second page
            page2_result = await self.endpoint._list_entities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=2,
                offset=2,
                entity_type_uri=None,
                search=None,
                include_entity_graph=False,
                current_user={"username": "test_user"}
            )
            
            if not isinstance(page2_result, EntitiesResponse):
                logger.error("Expected EntitiesResponse for page 2")
                return False
            
            logger.info("✅ Pagination test passed")
            return True
            
        except Exception as e:
            logger.error(f"Error in pagination test: {e}")
            return False
    
    async def test_list_entities_with_search(self, space_id: str, graph_id: str, search_term: str) -> bool:
        """Test entity listing with search functionality."""
        try:
            logger.info(f"🧪 Testing entity listing with search term: '{search_term}'...")
            
            # Search for entities
            result = await self.endpoint._list_entities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=10,
                offset=0,
                entity_type_uri=None,
                search=search_term,
                include_entity_graph=False,
                current_user={"username": "test_user"}
            )
            
            if not isinstance(result, EntitiesResponse):
                logger.error("Expected EntitiesResponse")
                return False
            
            # Validate search results
            actual_count = len(result.results) if hasattr(result, 'results') and result.results else 0
            
            logger.info(f"Search returned {actual_count} entities")
            
            logger.info("✅ Search test passed")
            return True
            
        except Exception as e:
            logger.error(f"Error in search test: {e}")
            return False
