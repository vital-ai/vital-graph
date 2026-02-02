#!/usr/bin/env python3
"""
Update Entities Test Case

Tests updating entity graphs by modifying slot values.
"""

import logging
from typing import Dict, Any, List
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot

logger = logging.getLogger(__name__)


class UpdateEntitiesTester:
    """Test case for updating entity graphs."""
    
    def __init__(self, client):
        self.client = client
        
    def run_tests(self, space_id: str, graph_id: str, entity_uris: List[str], 
                  entity_names: List[str]) -> Dict[str, Any]:
        """
        Run entity update tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uris: List of entity URIs
            entity_names: List of entity names
            
        Returns:
            Dict containing test results
        """
        results = {
            "test_name": "Update Organization Entities",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
            "updates": []
        }
        
        logger.info("=" * 80)
        logger.info("  Update Organization Entities")
        logger.info("=" * 80)
        
        # Define updates for first 3 entities
        updates = [
            {"index": 0, "field": "employees", "old": 500, "new": 750, "name": entity_names[0]},
            {"index": 1, "field": "employees", "old": 1200, "new": 1500, "name": entity_names[1]},
            {"index": 2, "field": "employees", "old": 800, "new": 950, "name": entity_names[2]}
        ]
        
        for update_info in updates:
            results["tests_run"] += 1
            idx = update_info["index"]
            entity_uri = entity_uris[idx]
            
            try:
                logger.info(f"\nUpdating {update_info['name']}...")
                logger.info(f"   Employee count: {update_info['old']} → {update_info['new']}")
                
                # Get entity with full graph
                response = self.client.kgentities.get_kgentity(
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
                
                # Find and update employee count slot
                updated = False
                for obj in entity_objects:
                    if isinstance(obj, KGIntegerSlot):
                        slot_type = str(obj.kGSlotType) if obj.kGSlotType else ''
                        if 'EmployeeCountSlot' in slot_type:
                            obj.integerSlotValue = update_info['new']
                            updated = True
                            break
                
                if updated:
                    # Update entity - pass GraphObjects directly
                    update_response = self.client.kgentities.update_kgentities(
                        space_id=space_id,
                        graph_id=graph_id,
                        objects=entity_objects
                    )
                    
                    if update_response.is_success:
                        logger.info(f"   ✅ Updated successfully")
                        logger.info(f"✅ PASS: Update {update_info['name']}")
                        results["tests_passed"] += 1
                        results["updates"].append(update_info)
                    else:
                        logger.error(f"   ❌ Update failed (error {update_response.error_code}): {update_response.error_message}")
                        logger.error(f"❌ FAIL: Update {update_info['name']}")
                        results["tests_failed"] += 1
                        results["errors"].append(f"Update failed for {update_info['name']}: {update_response.error_message}")
                else:
                    logger.warning(f"   ⚠️  Employee count slot not found")
                    logger.error(f"❌ FAIL: Update {update_info['name']}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Employee count slot not found for {update_info['name']}")
                    
            except Exception as e:
                logger.error(f"   ❌ Error: {e}")
                logger.error(f"❌ FAIL: Update {update_info['name']}")
                results["tests_failed"] += 1
                results["errors"].append(f"Error updating {update_info['name']}: {str(e)}")
        
        return results
