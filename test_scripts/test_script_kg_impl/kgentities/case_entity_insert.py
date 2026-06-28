#!/usr/bin/env python3
"""
KGEntity Insert Test Module

Modular test implementation for KG entity insertion operations.
Used by the main KGEntities endpoint test orchestrator.

Focuses on:
- Single entity insertion (no frames)
- VitalSigns object to quad conversion
- Direct endpoint method calls
- Proper grouping URI assignment
- Error handling and validation
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

# Import VitalSigns for KGEntity objects
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity

# Import models
from vitalgraph.model.kgentities_model import EntityCreateResponse

# Import quad conversion utilities
from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list


logger = logging.getLogger(__name__)


class KGEntityInsertTester:
    """
    Modular test implementation for KG entity insertion operations.
    
    Handles:
    - Single entity insertion (no frames)
    - VitalSigns object creation and quad conversion
    - Direct calls to endpoint private methods
    - Tracking of created entity URIs for cleanup
    """
    
    def __init__(self, endpoint, test_data_creator):
        """
        Initialize the entity insert tester.
        
        Args:
            endpoint: KGEntitiesEndpoint instance (initialized without REST setup)
            test_data_creator: KGEntityTestDataCreator instance for generating test data
        """
        self.endpoint = endpoint
        self.vitalsigns = VitalSigns()
        self.test_data_creator = test_data_creator
        self.created_entity_uris = []
        
    async def test_single_entity_insert(self, space_id: str, graph_id: str) -> bool:
        """
        Test insertion of a single KG entity (no frames).
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if insertion successful, False otherwise
        """
        try:
            logger.info("🧪 Testing single KG entity insertion...")
            
            # Create simple test entity (single object)
            entity = KGEntity()
            entity.URI = f"http://vital.ai/test/kgentity/person/{uuid.uuid4()}"
            entity.name = "Test Person"
            entity.kGEntityType = "Person"
            
            entity_objects = [entity]
            logger.info(f"📦 Created {len(entity_objects)} test objects")
            
            # Log object types for debugging
            for i, obj in enumerate(entity_objects):
                obj_type = type(obj).__name__
                obj_uri = getattr(obj, 'URI', 'N/A')
                logger.info(f"  [{i+1}] {obj_type}: {obj_uri}")
            
            # Convert VitalSigns objects to quads
            entity_quads = graphobjects_to_quad_list(entity_objects, graph_id)
            
            logger.info(f"📄 Created {len(entity_quads)} quads for single entity")
            
            # Call top-level endpoint function (_create_entities is the correct top-level method)
            from vitalgraph.endpoint.kgentities_endpoint import OperationMode
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            result = await self.endpoint._create_or_update_entities(
                space_id=space_id,
                graph_id=graph_id,
                quads=entity_quads,
                operation_mode=OperationMode.CREATE,
                parent_uri=None,
                current_user=current_user
            )
            
            if result and hasattr(result, 'message'):
                logger.info(f"✅ Entity insertion successful: {result.message}")
                
                # Track created entity URIs for cleanup
                if hasattr(result, 'created_uris'):
                    self.created_entity_uris.extend(result.created_uris)
                    logger.info(f"📝 Tracked {len(result.created_uris)} created entity URIs")
                
                return True
            else:
                logger.error(f"❌ Entity insertion failed: {result}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during single entity insertion test: {e}")
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
    
    def clear_created_entity_uris(self):
        """Clear the list of created entity URIs."""
        self.created_entity_uris.clear()
