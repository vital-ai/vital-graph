#!/usr/bin/env python3
"""
KGTypes List Test Module

Modular test implementation for KG type listing operations.
Used by the main KGTypes endpoint test orchestrator.

Focuses on:
- KGType listing with pagination
- KGType filtering by various criteria
- KGType search functionality
- Empty state handling
- Response validation
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

# Import VitalSigns for KGType objects
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGType import KGType

# Import models
from vitalgraph.model.kgtypes_model import KGTypeListResponse

logger = logging.getLogger(__name__)


class KGTypesListTester:
    """
    Modular test implementation for KG type listing operations.
    
    Handles:
    - KGType listing with pagination
    - KGType filtering and search
    - Response validation
    - Empty state testing
    """
    
    def __init__(self, endpoint):
        """
        Initialize the KGTypes list tester.
        
        Args:
            endpoint: KGTypesEndpoint instance
        """
        self.endpoint = endpoint
        self.vitalsigns = VitalSigns()
        
    async def test_list_kgtypes_empty(self, space_id: str, graph_id: str) -> bool:
        """Test listing KGTypes when none exist."""
        try:
            logger.info("🧪 Testing empty KGTypes listing...")
            
            # List KGTypes in empty graph
            result = await self.endpoint._list_kgtypes(
                space_id=space_id,
                graph_id=graph_id,
                page_size=10,
                offset=0,
                filter=None,
                current_user={"username": "test_user", "user_id": "test_user_123"}
            )
            
            if not isinstance(result, KGTypeListResponse):
                logger.error("Expected KGTypeListResponse")
                return False
            
            # Validate empty response
            if not result.success:
                logger.error(f"List operation failed: {result.message}")
                return False
            
            # Check that no KGTypes are returned
            actual_count = len(result.results) if hasattr(result, 'results') and result.results else 0
            
            if actual_count != 0:
                logger.error(f"Expected 0 KGTypes in empty state, got {actual_count}")
                return False
            
            # Validate pagination fields
            if result.total_count != 0:
                logger.error(f"Expected total_count=0, got {result.total_count}")
                return False
            
            logger.info("✅ Empty KGTypes listing test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Empty KGTypes listing test failed: {e}")
            return False
    
    async def test_list_kgtypes_populated(self, space_id: str, graph_id: str, expected_count: int = None) -> bool:
        """Test listing KGTypes when they exist."""
        try:
            logger.info("🧪 Testing populated KGTypes listing...")
            
            # List KGTypes in populated graph
            result = await self.endpoint._list_kgtypes(
                space_id=space_id,
                graph_id=graph_id,
                page_size=25,  # Large enough to get all
                offset=0,
                filter=None,
                current_user={"username": "test_user", "user_id": "test_user_123"}
            )
            
            if not isinstance(result, KGTypeListResponse):
                logger.error("Expected KGTypeListResponse")
                return False
            
            # Validate successful response
            if not result.success:
                logger.error(f"List operation failed: {result.message}")
                return False
            
            # Check that KGTypes are returned
            actual_count = len(result.results) if hasattr(result, 'results') and result.results else 0
            
            if actual_count == 0:
                logger.error("Expected KGTypes in populated state, got 0")
                return False
            
            # Validate expected count if provided
            if expected_count is not None and actual_count != expected_count:
                logger.error(f"Expected {expected_count} KGTypes, got {actual_count}")
                return False
            
            # Validate pagination fields
            if result.total_count != actual_count:
                logger.error(f"Total count mismatch: total_count={result.total_count}, actual={actual_count}")
                return False
            
            logger.info(f"✅ Populated KGTypes listing test passed - found {actual_count} KGTypes")
            return True
            
        except Exception as e:
            logger.error(f"❌ Populated KGTypes listing test failed: {e}")
            return False
    
