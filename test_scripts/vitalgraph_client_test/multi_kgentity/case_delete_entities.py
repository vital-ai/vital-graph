#!/usr/bin/env python3
"""
Delete Entities Test Case

Tests deleting entities and verifying deletions.
"""

import logging
from typing import Dict, Any, List
from ai_haley_kg_domain.model.KGEntity import KGEntity

logger = logging.getLogger(__name__)


class DeleteEntitiesTester:
    """Test case for deleting entities."""
    
    def __init__(self, client):
        self.client = client
        
    async def run_tests(self, space_id: str, graph_id: str, entity_uris: List[str], 
                  entity_names: List[str], expected_remaining: int = None) -> Dict[str, Any]:
        """
        Run entity deletion tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uris: List of entity URIs
            entity_names: List of entity names
            expected_remaining: Expected number of remaining entities after deletion (optional)
            
        Returns:
            Dict containing test results
        """
        results = {
            "test_name": "Delete Organization Entities",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": []
        }
        
        logger.info("=" * 80)
        logger.info("  Delete Organization Entities")
        logger.info("=" * 80)
        
        # Delete last 3 entities
        entities_to_delete = [
            {"index": 7, "name": entity_names[7]},
            {"index": 8, "name": entity_names[8]},
            {"index": 9, "name": entity_names[9]}
        ]
        
        for delete_info in entities_to_delete:
            results["tests_run"] += 1
            idx = delete_info["index"]
            entity_uri = entity_uris[idx]
            
            try:
                logger.info(f"\nDeleting {delete_info['name']}...")
                
                response = await self.client.kgentities.delete_kgentity(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri=entity_uri
                )
                
                if response.is_success:
                    logger.info(f"   ✅ Deleted successfully (deleted {response.deleted_count} items)")
                    logger.info(f"✅ PASS: Delete {delete_info['name']}")
                    results["tests_passed"] += 1
                else:
                    logger.error(f"   ❌ Delete failed (error {response.error_code}): {response.error_message}")
                    logger.error(f"❌ FAIL: Delete {delete_info['name']}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Delete failed for {delete_info['name']}: {response.error_message}")
                    
            except Exception as e:
                logger.error(f"   ❌ Error: {e}")
                logger.error(f"❌ FAIL: Delete {delete_info['name']}")
                results["tests_failed"] += 1
                results["errors"].append(f"Error deleting {delete_info['name']}: {str(e)}")
        
        # Verify deletions
        logger.info("\n" + "=" * 80)
        logger.info("  Verify Deletions")
        logger.info("=" * 80)
        
        # Test 1: Verify count
        results["tests_run"] += 1
        try:
            response = await self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=20
            )
            
            remaining_count = response.total_count if response.is_success else 0
            # Use provided expected_remaining if available, otherwise calculate
            expected_count = expected_remaining if expected_remaining is not None else (len(entity_uris) - len(entities_to_delete))
            
            if remaining_count == expected_count:
                logger.info(f"✅ PASS: Verify entity count after deletions")
                logger.info(f"   Found {remaining_count} entities (expected {expected_count})")
                results["tests_passed"] += 1
            else:
                logger.error(f"❌ FAIL: Verify entity count after deletions")
                logger.error(f"   Found {remaining_count} entities (expected {expected_count})")
                results["tests_failed"] += 1
                results["errors"].append(f"Entity count mismatch after deletion: {remaining_count} vs {expected_count}")
                
        except Exception as e:
            logger.error(f"❌ Error verifying count: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Error verifying count: {str(e)}")
        
        # Test 2: Verify individual deletions
        for delete_info in entities_to_delete:
            results["tests_run"] += 1
            idx = delete_info["index"]
            entity_uri = entity_uris[idx]
            
            try:
                logger.info(f"\nVerifying {delete_info['name']} is deleted...")
                
                response = await self.client.kgentities.get_kgentity(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri=entity_uri,
                    include_entity_graph=False
                )
                
                # Check if entity was found - expect error or no objects
                entity_found = response.is_success and response.objects and len(response.objects) > 0
                
                if not entity_found:
                    logger.info(f"   ✅ Entity not found (as expected)")
                    logger.info(f"✅ PASS: Verify deletion of {delete_info['name']}")
                    results["tests_passed"] += 1
                else:
                    logger.error(f"   ⚠️  Entity still exists (unexpected)")
                    logger.error(f"❌ FAIL: Verify deletion of {delete_info['name']}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Entity {delete_info['name']} still exists after deletion")
                    
            except Exception as e:
                logger.error(f"❌ Error verifying deletion: {e}")
                results["tests_failed"] += 1
                results["errors"].append(f"Error verifying deletion of {delete_info['name']}: {str(e)}")
        
        return results
