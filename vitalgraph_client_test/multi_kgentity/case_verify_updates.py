#!/usr/bin/env python3
"""
Verify Updates Test Case

Verifies that entity updates were applied correctly by re-getting entities.
"""

import logging
from typing import Dict, Any, List
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot

logger = logging.getLogger(__name__)


class VerifyUpdatesTester:
    """Test case for verifying entity updates."""
    
    def __init__(self, client):
        self.client = client
        
    async def run_tests(self, space_id: str, graph_id: str, entity_uris: List[str], 
                  updates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Run update verification tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uris: List of entity URIs
            updates: List of update info dicts from update test
            
        Returns:
            Dict containing test results
        """
        results = {
            "test_name": "Verify Updates",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": []
        }
        
        logger.info("=" * 80)
        logger.info("  Verify Updates")
        logger.info("=" * 80)
        
        for update_info in updates:
            results["tests_run"] += 1
            idx = update_info["index"]
            entity_uri = entity_uris[idx]
            
            try:
                logger.info(f"\nVerifying {update_info['name']}...")
                
                # Get entity with full graph
                response = await self.client.kgentities.get_kgentity(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri=entity_uri,
                    include_entity_graph=True
                )
                
                # Direct access to GraphObjects via EntityGraph
                entity_objects = []
                if response.is_success and response.objects:
                    entity_graph = response.objects
                    entity_objects = entity_graph.objects
                
                # Find employee count slot
                current_count = None
                for obj in entity_objects:
                    if isinstance(obj, KGIntegerSlot):
                        slot_type = str(obj.kGSlotType) if obj.kGSlotType else ''
                        if 'EmployeeCountSlot' in slot_type:
                            current_count = obj.integerSlotValue
                            break
                
                update_verified = (current_count == update_info['new'])
                
                if update_verified:
                    logger.info(f"✅ PASS: Verify update for {update_info['name']}")
                    logger.info(f"   Employee count: {current_count} (expected {update_info['new']})")
                    results["tests_passed"] += 1
                else:
                    logger.error(f"❌ FAIL: Verify update for {update_info['name']}")
                    logger.error(f"   Employee count: {current_count} (expected {update_info['new']})")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Update verification failed for {update_info['name']}: {current_count} vs {update_info['new']}")
                    
            except Exception as e:
                logger.error(f"❌ Error verifying {update_info['name']}: {e}")
                results["tests_failed"] += 1
                results["errors"].append(f"Error verifying {update_info['name']}: {str(e)}")
        
        return results
