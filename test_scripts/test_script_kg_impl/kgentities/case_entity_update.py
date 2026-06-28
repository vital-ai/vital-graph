#!/usr/bin/env python3
"""
KGEntity Update Test Module

Modular test implementation for KG entity update operations.
Used by the main KGEntities endpoint test orchestrator.

Focuses on:
- Single entity update operations
- Batch entity update operations
- Atomic update validation
- VitalSigns object modification
- Error handling for non-existent entities
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

# Import VitalSigns for KGEntity objects
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity

# Import models
from vitalgraph.model.kgentities_model import EntityUpdateResponse

# Import quad conversion utilities
from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list

logger = logging.getLogger(__name__)


class KGEntityUpdateTester:
    """
    Modular test implementation for KG entity update operations.
    
    Handles:
    - Single entity updates using atomic processors
    - Batch entity updates
    - Update validation and verification
    - Error handling for invalid updates
    """
    
    def __init__(self, endpoint, test_data_creator):
        """
        Initialize the entity update tester.
        
        Args:
            endpoint: KGEntitiesEndpoint instance (initialized without REST setup)
            test_data_creator: KGEntityTestDataCreator instance for generating test data
        """
        self.endpoint = endpoint
        self.vitalsigns = VitalSigns()
        self.test_data_creator = test_data_creator
        self.created_entity_uris = []
        
    async def test_single_entity_update(self, space_id: str, graph_id: str, entity_uri: str) -> bool:
        """Test updating a single entity."""
        try:
            logger.info(f"🧪 Testing single entity update for {entity_uri}...")
            
            # Create updated entity
            updated_entity = KGEntity()
            updated_entity.URI = entity_uri
            updated_entity.name = f"Updated Entity {uuid.uuid4().hex[:8]}"
            updated_entity.kGGraphURI = entity_uri
            
            # Convert to quads
            entity_quads = graphobjects_to_quad_list([updated_entity], graph_id)
            
            # Update entity via top-level endpoint function
            # Use the endpoint's _create_or_update_entities method with UPDATE mode
            from vitalgraph.endpoint.kgentities_endpoint import OperationMode
            
            result = await self.endpoint._create_or_update_entities(
                space_id=space_id,
                graph_id=graph_id,
                quads=entity_quads,
                operation_mode=OperationMode.UPDATE,
                parent_uri=None,
                current_user={"username": "test_user"}
            )
            
            if not isinstance(result, EntityUpdateResponse):
                logger.error("Expected EntityUpdateResponse")
                return False
            
            if not result.updated_uri:
                logger.error(f"Update failed: {result.message}")
                return False
            
            logger.info("✅ Single entity update test passed")
            return True
            
        except Exception as e:
            logger.error(f"Error in single entity update test: {e}")
            return False
    
    async def test_batch_entity_update(self, space_id: str, graph_id: str, entity_uris: List[str]) -> bool:
        """Test updating multiple entities in batch."""
        try:
            logger.info(f"🧪 Testing batch entity update for {len(entity_uris)} entities...")
            
            # Create updated entities
            updated_entities = []
            for i, entity_uri in enumerate(entity_uris):
                entity = KGEntity()
                entity.URI = entity_uri
                entity.name = f"Batch Updated Entity {i+1}"
                entity.kGGraphURI = entity_uri
                updated_entities.append(entity)
            
            # Convert to quads
            entity_quads = graphobjects_to_quad_list(updated_entities, graph_id)
            
            # Update entities via endpoint
            from vitalgraph.endpoint.kgentities_endpoint import OperationMode
            
            result = await self.endpoint._create_or_update_entities(
                space_id=space_id,
                graph_id=graph_id,
                quads=entity_quads,
                operation_mode=OperationMode.UPDATE,
                parent_uri=None,
                current_user={"username": "test_user"}
            )
            
            if not isinstance(result, EntityUpdateResponse):
                logger.error("Expected EntityUpdateResponse")
                return False
            
            if not result.updated_uri:
                logger.error(f"Batch update failed: {result.message}")
                return False
            
            logger.info("✅ Batch entity update test passed")
            return True
            
        except Exception as e:
            logger.error(f"Error in batch entity update test: {e}")
            return False
    
    async def test_update_nonexistent_entity(self, space_id: str, graph_id: str) -> bool:
        """Test updating a non-existent entity (should fail)."""
        try:
            logger.info("🧪 Testing update of non-existent entity...")
            
            # Create entity with non-existent URI
            nonexistent_entity = KGEntity()
            nonexistent_entity.URI = f"urn:test:nonexistent_{uuid.uuid4()}"
            nonexistent_entity.name = "Non-existent Entity"
            nonexistent_entity.kGGraphURI = nonexistent_entity.URI
            
            # Convert to quads
            entity_quads = graphobjects_to_quad_list([nonexistent_entity], graph_id)
            
            # Try to update non-existent entity
            from vitalgraph.endpoint.kgentities_endpoint import OperationMode
            
            result = await self.endpoint._create_or_update_entities(
                space_id=space_id,
                graph_id=graph_id,
                quads=entity_quads,
                operation_mode=OperationMode.UPDATE,
                parent_uri=None,
                current_user={"username": "test_user"}
            )
            
            # Should fail or return error
            if isinstance(result, EntityUpdateResponse) and result.updated_uri:
                logger.error("Update of non-existent entity should have failed")
                return False
            
            logger.info("✅ Non-existent entity update test passed (correctly failed)")
            return True
            
        except Exception as e:
            # Expected to fail
            logger.info("✅ Non-existent entity update test passed (correctly threw exception)")
            return True
    
    async def test_upsert_entity(self, space_id: str, graph_id: str, entity_uri: str) -> bool:
        """Test UPSERT operation (create or update)."""
        try:
            logger.info(f"🧪 Testing entity UPSERT for {entity_uri}...")
            
            # Create entity for UPSERT
            upsert_entity = KGEntity()
            upsert_entity.URI = entity_uri
            upsert_entity.name = f"UPSERT Entity {uuid.uuid4().hex[:8]}"
            upsert_entity.kGGraphURI = entity_uri
            
            # Convert to quads
            entity_quads = graphobjects_to_quad_list([upsert_entity], graph_id)
            
            # UPSERT entity via endpoint
            from vitalgraph.endpoint.kgentities_endpoint import OperationMode
            
            result = await self.endpoint._create_or_update_entities(
                space_id=space_id,
                graph_id=graph_id,
                quads=entity_quads,
                operation_mode=OperationMode.UPSERT,
                parent_uri=None,
                current_user={"username": "test_user"}
            )
            
            # UPSERT should always succeed
            if not result:
                logger.error("UPSERT operation failed")
                return False
            
            logger.info("✅ Entity UPSERT test passed")
            return True
            
        except Exception as e:
            logger.error(f"Error in entity UPSERT test: {e}")
            return False
