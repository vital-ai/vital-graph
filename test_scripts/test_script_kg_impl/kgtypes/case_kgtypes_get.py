#!/usr/bin/env python3
"""
KGTypes Get Test Module

Modular test implementation for KG type retrieval operations.
Used by the main KGTypes endpoint test orchestrator.

Focuses on:
- Individual KGType retrieval by URI
- Response validation
- Error handling for non-existent KGTypes
- Quad-based conversion validation
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

# Import VitalSigns for KGType objects
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGType import KGType

# Import models
from vitalgraph.model.kgtypes_model import KGTypeGetResponse

# Import quad conversion utilities
from vitalgraph.utils.quad_format_utils import quad_list_to_graphobjects

logger = logging.getLogger(__name__)


class KGTypesGetTester:
    """
    Modular test implementation for KG type retrieval operations.
    
    Handles:
    - Individual KGType retrieval by URI
    - Response validation
    - Error handling for non-existent KGTypes
    - Quad-based conversion validation
    """
    
    def __init__(self, endpoint):
        """
        Initialize the KGTypes get tester.
        
        Args:
            endpoint: KGTypesEndpoint instance
        """
        self.endpoint = endpoint
        self.vitalsigns = VitalSigns()
        
    
    async def test_get_kgtype(self, space_id: str, graph_id: str, created_kgtype_ids: List[str]) -> bool:
        """Test getting individual KGType by URI."""
        try:
            logger.info("🧪 Testing individual KGType retrieval...")
            
            if not created_kgtype_ids:
                logger.error("❌ No KGTypes available for retrieval test")
                return False
            
            # Get the first created KGType
            test_kgtype_uri = created_kgtype_ids[0]
            logger.info(f"Testing retrieval of KGType: {test_kgtype_uri}")
            
            response = await self.endpoint._get_kgtype_by_uri(
                space_id=space_id,
                graph_id=graph_id,
                uri=test_kgtype_uri,
                current_user={"username": "test_user", "user_id": "test_user_123"}
            )
            
            # Check if response is valid - it should be a KGTypeGetResponse or similar response type
            if not response:
                logger.error("No response received from get_kgtype_by_uri")
                return False
            
            if not response.success:
                logger.error(f"Get operation failed: {response.message}")
                return False
            
            # Validate that we got the correct KGType
            if hasattr(response, 'results') and response.results:
                retrieved_objects = quad_list_to_graphobjects(response.results)
                retrieved_kgtypes = [obj for obj in retrieved_objects if isinstance(obj, KGType)]
                
                if len(retrieved_kgtypes) != 1:
                    logger.error(f"Expected 1 KGType, got {len(retrieved_kgtypes)}")
                    return False
                
                retrieved_kgtype = retrieved_kgtypes[0]
                retrieved_uri = str(retrieved_kgtype.URI)
                
                if retrieved_uri != test_kgtype_uri:
                    logger.error(f"URI mismatch: expected {test_kgtype_uri}, got {retrieved_uri}")
                    return False
                
                logger.info(f"✅ Successfully retrieved KGType: {retrieved_uri}")
                return True
            else:
                logger.error("No results in response")
                return False
                
        except Exception as e:
            logger.error(f"❌ KGType retrieval test failed: {e}")
            return False
    
    async def test_get_nonexistent_kgtype(self, space_id: str, graph_id: str) -> bool:
        """Test getting a non-existent KGType (should handle gracefully)."""
        try:
            logger.info("🧪 Testing non-existent KGType retrieval...")
            
            # Use a non-existent URI
            nonexistent_uri = f"http://vital.ai/test/kgtype/NonExistent_{uuid.uuid4().hex[:8]}"
            
            response = await self.endpoint._get_kgtype_by_uri(
                space_id=space_id,
                graph_id=graph_id,
                uri=nonexistent_uri,
                current_user={"username": "test_user", "user_id": "test_user_123"}
            )
            
            if not isinstance(response, KGTypeGetResponse):
                logger.error("Expected KGTypeGetResponse")
                return False
            
            # Should either return success=False or success=True with empty results
            if response.success:
                # If success, should have empty or no results
                if hasattr(response, 'results') and response.results:
                    retrieved_objects = quad_list_to_graphobjects(response.results)
                    retrieved_kgtypes = [obj for obj in retrieved_objects if isinstance(obj, KGType)]
                    if len(retrieved_kgtypes) > 0:
                        logger.error(f"Expected no KGTypes for non-existent URI, got {len(retrieved_kgtypes)}")
                        return False
                
                logger.info("✅ Non-existent KGType handled gracefully (empty result)")
                return True
            else:
                # Failure is also acceptable for non-existent KGType
                logger.info(f"✅ Non-existent KGType handled gracefully (failure): {response.message}")
                return True
                
        except Exception as e:
            logger.error(f"❌ Non-existent KGType retrieval test failed: {e}")
            return False
