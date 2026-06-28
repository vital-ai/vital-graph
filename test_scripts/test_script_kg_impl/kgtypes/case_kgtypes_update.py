#!/usr/bin/env python3
"""
KGTypes Update Test Module

Modular test implementation for KG type update operations.
Used by the main KGTypes endpoint test orchestrator.

Focuses on:
- KGType property updates
- Quad-based document processing for updates
- Response validation
- Update consistency verification
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

# Import VitalSigns for KGType objects
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGType import KGType

# Import models
from vitalgraph.model.kgtypes_model import KGTypeUpdateResponse

# Import shared utilities
from test_script_kg_impl.case_utils import quads_to_kgtypes
from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list

logger = logging.getLogger(__name__)


class KGTypesUpdateTester:
    """
    Modular test implementation for KG type update operations.
    
    Handles:
    - KGType property updates
    - Quad-based document processing for updates
    - Response validation
    - Update consistency verification
    """
    
    def __init__(self, endpoint):
        """
        Initialize the KGTypes update tester.
        
        Args:
            endpoint: KGTypesEndpoint instance
        """
        self.endpoint = endpoint
        self.vitalsigns = VitalSigns()
        
    
    
    async def test_update_kgtype(self, space_id: str, graph_id: str, created_kgtype_ids: List[str]) -> bool:
        """Test updating KGType properties."""
        try:
            logger.info("🧪 Testing KGType property updates...")
            
            if not created_kgtype_ids:
                logger.error("❌ No KGTypes available for update test")
                return False
            
            # Get the first created KGType for updating
            test_kgtype_uri = created_kgtype_ids[0]
            logger.info(f"Testing update of KGType: {test_kgtype_uri}")
            
            # First, retrieve the current KGType to get its current state
            get_response = await self.endpoint._get_kgtype_by_uri(
                space_id=space_id,
                graph_id=graph_id,
                uri=test_kgtype_uri,
                current_user={"username": "test_user", "user_id": "test_user_123"}
            )
            
            if not get_response.success:
                logger.error(f"Failed to retrieve KGType for update: {get_response.message}")
                return False
            
            # Convert quad results to KGType objects
            current_kgtypes = quads_to_kgtypes(get_response.results)
            if not current_kgtypes:
                logger.error("No KGType found in get response")
                return False
            
            current_kgtype = current_kgtypes[0]
            logger.info(f"🔍 DEBUG: Converted KGType count: {len(current_kgtypes)}")
            
            # Log the KGType before update
            logger.info(f"🔍 DEBUG: Before update - KGType JSON: {current_kgtype.to_json()}")
            
            # Update the KGType properties - use correct VitalSigns property names
            current_kgtype.name = "Updated Person Type"
            current_kgtype.kGraphDescription = "Updated description for person entity type"
            
            # Log the KGType after local update
            logger.info(f"🔍 DEBUG: After local update - KGType JSON: {current_kgtype.to_json()}")
            
            # Convert updated KGType to quads for the update endpoint
            quads = graphobjects_to_quad_list([current_kgtype], graph_id)
            logger.info(f"🔍 DEBUG: Quads being sent to endpoint: {len(quads)} quads")
            
            # Perform the update
            response = await self.endpoint._update_kgtypes(
                space_id,
                graph_id,
                quads,
                {"username": "test_user", "user_id": "test_user_123"}
            )
            
            if not isinstance(response, KGTypeUpdateResponse):
                logger.error("Expected KGTypeUpdateResponse")
                return False
            
            if not response.success:
                logger.error(f"Update operation failed: {response.message}")
                return False
            
            # Verify the update by retrieving the KGType again
            verify_response = await self.endpoint._get_kgtype_by_uri(
                space_id=space_id,
                graph_id=graph_id,
                uri=test_kgtype_uri,
                current_user={"username": "test_user", "user_id": "test_user_123"}
            )
            
            if not verify_response.success:
                logger.error(f"Failed to verify update: {verify_response.message}")
                return False
            
            # Check that the properties were updated
            updated_kgtypes = quads_to_kgtypes(verify_response.results)
            if not updated_kgtypes:
                logger.error("No KGType found in verification response")
                return False
            
            updated_kgtype = updated_kgtypes[0]
            
            # Log the updated KGType to see what we actually got back
            logger.info(f"🔍 DEBUG: Updated KGType JSON: {updated_kgtype.to_json()}")
            
            # Verify the updates - use VitalSigns property casting pattern
            # VitalSigns properties return Property objects, must cast to get actual values
            try:
                updated_name = str(updated_kgtype.name) if updated_kgtype.name else None
            except:
                updated_name = None
                
            try:
                updated_description = str(updated_kgtype.kGraphDescription) if updated_kgtype.kGraphDescription else None
            except:
                updated_description = None
            
            if updated_name != "Updated Person Type":
                logger.error(f"Name not updated correctly: expected 'Updated Person Type', got '{updated_name}'")
                return False
            
            if updated_description != "Updated description for person entity type":
                logger.error(f"Description not updated correctly: expected 'Updated description for person entity type', got '{updated_description}'")
                return False
            
            logger.info(f"✅ Successfully updated KGType: {test_kgtype_uri}")
            return True
                
        except Exception as e:
            logger.error(f"❌ KGType update test failed: {e}")
            return False
