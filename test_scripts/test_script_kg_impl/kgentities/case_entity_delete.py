#!/usr/bin/env python3
"""
KGEntity Delete Test Module

Modular test implementation for KG entity deletion operations.
Used by the main KGEntities endpoint test orchestrator.

Focuses on:
- Single entity deletion
- Batch entity deletion
- Entity graph deletion (cascade)
- Deletion validation
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
from vitalgraph.model.kgentities_model import EntityDeleteResponse

logger = logging.getLogger(__name__)


class KGEntityDeleteTester:
    """
    Modular test implementation for KG entity deletion operations.
    
    Handles:
    - Single entity deletion
    - Batch entity deletion
    - Entity graph deletion with cascade
    - Deletion validation and verification
    """
    
    def __init__(self, endpoint, test_data_creator):
        """
        Initialize the entity delete tester.
        
        Args:
            endpoint: KGEntitiesEndpoint instance
            test_data_creator: KGEntityTestDataCreator instance for generating test data
        """
        self.endpoint = endpoint
        self.vitalsigns = VitalSigns()
        self.test_data_creator = test_data_creator
        self.created_entity_uris = []
        
    async def test_single_entity_delete(self, space_id: str, graph_id: str, entity_uri: str) -> bool:
        """Test deleting a single entity."""
        try:
            logger.info(f"🧪 Testing single entity deletion for {entity_uri}...")
            
            # Delete entity via endpoint
            result = await self.endpoint._delete_entity_by_uri(
                space_id=space_id,
                graph_id=graph_id,
                uri=entity_uri,
                delete_entity_graph=False,
                current_user={"username": "test_user"}
            )
            
            if not isinstance(result, EntityDeleteResponse):
                logger.error("Expected EntityDeleteResponse")
                return False
            
            logger.info(f"🔍 DEBUG: EntityDeleteResponse - message: {result.message}, deleted_count: {result.deleted_count}, deleted_uris: {result.deleted_uris}")
            
            if result.deleted_count != 1:
                logger.error(f"Expected 1 deleted entity, got {result.deleted_count}")
                return False
            
            logger.info("✅ Single entity deletion test passed")
            return True
            
        except Exception as e:
            logger.error(f"Error in single entity deletion test: {e}")
            return False
    
    async def test_batch_entity_delete(self, space_id: str, graph_id: str, entity_uris: List[str]) -> bool:
        """Test deleting multiple entities in batch."""
        try:
            logger.info(f"🧪 Testing batch entity deletion for {len(entity_uris)} entities...")
            
            # Delete entities via endpoint
            result = await self.endpoint._delete_entities_by_uris(
                space_id=space_id,
                graph_id=graph_id,
                uris=entity_uris,
                delete_entity_graph=False,
                current_user={"username": "test_user"}
            )
            
            if not isinstance(result, EntityDeleteResponse):
                logger.error("Expected EntityDeleteResponse")
                return False
            
            if result.deleted_count != len(entity_uris):
                logger.error(f"Expected {len(entity_uris)} deleted entities, got {result.deleted_count}")
                return False
            
            logger.info("✅ Batch entity deletion test passed")
            return True
            
        except Exception as e:
            logger.error(f"Error in batch entity deletion test: {e}")
            return False
    
    async def test_entity_graph_delete(self, space_id: str, graph_id: str, entity_uri: str) -> bool:
        """Test deleting entity with complete graph (cascade deletion)."""
        try:
            logger.info(f"🧪 Testing entity graph deletion for {entity_uri}...")
            
            # Delete entity with complete graph
            result = await self.endpoint._delete_entity_by_uri(
                space_id=space_id,
                graph_id=graph_id,
                uri=entity_uri,
                delete_entity_graph=True,  # Cascade deletion
                current_user={"username": "test_user"}
            )
            
            if not isinstance(result, EntityDeleteResponse):
                logger.error("Expected EntityDeleteResponse")
                return False
            
            if result.deleted_count < 1:
                logger.error(f"Expected at least 1 deleted entity, got {result.deleted_count}")
                return False
            
            logger.info("✅ Entity graph deletion test passed")
            return True
            
        except Exception as e:
            logger.error(f"Error in entity graph deletion test: {e}")
            return False
    
    async def test_delete_nonexistent_entity(self, space_id: str, graph_id: str) -> bool:
        """Test deleting a non-existent entity (should handle gracefully)."""
        try:
            logger.info("🧪 Testing deletion of non-existent entity...")
            
            # Try to delete non-existent entity
            nonexistent_uri = f"urn:test:nonexistent_{uuid.uuid4()}"
            result = await self.endpoint._delete_entity_by_uri(
                space_id=space_id,
                graph_id=graph_id,
                uri=nonexistent_uri,
                delete_entity_graph=False,
                current_user={"username": "test_user"}
            )
            
            if not isinstance(result, EntityDeleteResponse):
                logger.error("Expected EntityDeleteResponse")
                return False
            
            # Should handle gracefully (0 deleted is acceptable)
            if result.deleted_count < 0:
                logger.error("Deleted count should not be negative")
                return False
            
            logger.info("✅ Non-existent entity deletion test passed")
            return True
            
        except Exception as e:
            logger.error(f"Error in non-existent entity deletion test: {e}")
            return False
    
    async def verify_entity_deleted(self, space_id: str, graph_id: str, entity_uri: str) -> bool:
        """Verify that an entity has been successfully deleted."""
        try:
            logger.info(f"🔍 Verifying entity {entity_uri} is deleted...")
            
            # Try to get the deleted entity
            try:
                result = await self.endpoint._get_entity_by_uri(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri=entity_uri,
                    include_entity_graph=False,
                    current_user={"username": "test_user"}
                )
                
                # If we get a result, the entity wasn't deleted
                if result:
                    logger.error("Entity still exists after deletion")
                    return False
                    
            except Exception:
                # Expected - entity should not exist
                pass
            
            logger.info("✅ Entity deletion verified")
            return True
            
        except Exception as e:
            logger.error(f"Error verifying entity deletion: {e}")
            return False
