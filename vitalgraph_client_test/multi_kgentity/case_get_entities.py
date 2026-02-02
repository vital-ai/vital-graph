#!/usr/bin/env python3
"""
Get Individual Entities Test Case

Tests retrieving individual entities by URI.
"""

import logging
from typing import Dict, Any, List
from ai_haley_kg_domain.model.KGEntity import KGEntity

logger = logging.getLogger(__name__)


class GetEntitiesTester:
    """Test case for getting individual entities."""
    
    def __init__(self, client):
        self.client = client
        
    def run_tests(self, space_id: str, graph_id: str, entity_uris: List[str], 
                  entity_names: List[str]) -> Dict[str, Any]:
        """
        Run individual entity retrieval tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uris: List of entity URIs to retrieve
            entity_names: List of entity names (for display)
            
        Returns:
            Dict containing test results
        """
        results = {
            "test_name": "Get Individual Entities",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": []
        }
        
        logger.info("=" * 80)
        logger.info("  Get Individual Entities")
        logger.info("=" * 80)
        
        # Test first 3 entities
        for i in range(min(3, len(entity_uris))):
            results["tests_run"] += 1
            entity_uri = entity_uris[i]
            org_name = entity_names[i]
            
            try:
                logger.info(f"\nGetting entity {i+1}: {org_name}...")
                
                response = self.client.kgentities.get_kgentity(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri=entity_uri,
                    include_entity_graph=False
                )
                
                # Direct GraphObject access
                entity_retrieved = False
                retrieved_name = None
                
                if response.is_success and response.objects:
                    for obj in response.objects:
                        if isinstance(obj, KGEntity):
                            entity_retrieved = True
                            retrieved_name = str(obj.name) if obj.name else 'Unknown'
                            break
                
                if entity_retrieved:
                    logger.info(f"   ✅ Retrieved: {retrieved_name}")
                    logger.info(f"✅ PASS: Get entity: {org_name}")
                    results["tests_passed"] += 1
                else:
                    logger.error(f"   ❌ Failed to retrieve entity")
                    logger.error(f"❌ FAIL: Get entity: {org_name}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Failed to retrieve {org_name}")
                    
            except Exception as e:
                logger.error(f"   ❌ Error: {e}")
                logger.error(f"❌ FAIL: Get entity: {org_name}")
                results["tests_failed"] += 1
                results["errors"].append(f"Error getting {org_name}: {str(e)}")
        
        return results
