"""
Delete Lead Entity Graph Test Case

Tests deleting a lead entity graph and verifying deletion.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class DeleteLeadGraphTester:
    """Test case for deleting lead entity graphs."""
    
    def __init__(self, client):
        self.client = client
    
    def run_tests(self, space_id: str, graph_id: str, entity_uri: str) -> Dict[str, Any]:
        """
        Run lead entity graph deletion tests.
        
        Args:
            space_id: Space ID
            graph_id: Graph ID
            entity_uri: URI of the entity to delete
            
        Returns:
            Dict with test results
        """
        results = {
            "test_name": "Delete Lead Entity Graph",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": []
        }
        
        logger.info(f"\n{'='*100}")
        logger.info(f"  Delete Lead Entity Graph")
        logger.info(f"{'='*100}")
        logger.info(f"Entity URI: {entity_uri}")
        
        # Test 1: Delete entity graph
        results["tests_run"] += 1
        
        try:
            logger.info(f"\n--- Delete Entity Graph ---\n")
            
            # Delete the entity with full graph
            response = self.client.kgentities.delete_kgentity(
                space_id=space_id,
                graph_id=graph_id,
                uri=entity_uri,
                delete_entity_graph=True
            )
            
            if response.is_success:
                logger.info(f"   ✅ Entity graph deleted successfully")
                logger.info(f"   Deleted {response.deleted_count} items")
                logger.info(f"✅ PASS: Delete entity graph")
                results["tests_passed"] += 1
            else:
                logger.error(f"❌ FAIL: Delete entity graph")
                logger.error(f"   Delete failed (error {response.error_code}): {response.error_message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Entity delete failed: {response.error_message}")
                
        except Exception as e:
            logger.error(f"❌ Error deleting entity graph: {e}")
            import traceback
            logger.error(traceback.format_exc())
            results["tests_failed"] += 1
            results["errors"].append(f"Error deleting entity graph: {str(e)}")
        
        # Test 2: Verify deletion via get
        results["tests_run"] += 1
        
        try:
            logger.info(f"\n--- Verify Deletion (Get) ---\n")
            
            # Try to get the deleted entity
            logger.info(f"   Attempting to get deleted entity...")
            try:
                response = self.client.kgentities.get_kgentity(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri=entity_uri
                )
                
                # Check if entity was found - expect error or no objects
                entity_found = response.is_success and response.objects and len(response.objects) > 0
                
                if not entity_found:
                    logger.info(f"   ✅ Get deleted entity returned no data (as expected)")
                    logger.info(f"✅ PASS: Verify deletion (get)")
                    results["tests_passed"] += 1
                else:
                    logger.error(f"   ❌ Deleted entity still exists with {len(response.objects)} objects")
                    results["tests_failed"] += 1
                    results["errors"].append("Deleted entity still returned by get operation")
            except Exception as get_error:
                # Entity not found - this is also expected
                logger.info(f"   ✅ Get deleted entity failed (as expected): {get_error}")
                logger.info(f"✅ PASS: Verify deletion (get)")
                results["tests_passed"] += 1
                
        except Exception as e:
            logger.error(f"❌ Error verifying deletion via get: {e}")
            import traceback
            logger.error(traceback.format_exc())
            results["tests_failed"] += 1
            results["errors"].append(f"Error verifying deletion via get: {str(e)}")
        
        # Test 3: Verify deletion via list
        results["tests_run"] += 1
        
        try:
            logger.info(f"\n--- Verify Deletion (List) ---\n")
            
            # List all entities to verify deletion
            logger.info(f"   Verifying deletion by listing all entities...")
            list_response = self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=100
            )
            
            # Check that the deleted entity is not in the list
            entity_uris_in_list = [str(e.URI) for e in list_response.objects if hasattr(e, 'URI')]
            
            if entity_uri not in entity_uris_in_list:
                logger.info(f"   ✅ Deleted entity not in entity list (as expected)")
                logger.info(f"   Remaining entities: {len(entity_uris_in_list)}")
                logger.info(f"✅ PASS: Verify deletion (list)")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ Deleted entity still in entity list")
                logger.error(f"❌ FAIL: Verify deletion (list)")
                results["tests_failed"] += 1
                results["errors"].append("Deleted entity still appears in entity list")
                
        except Exception as e:
            logger.error(f"❌ Error verifying deletion via list: {e}")
            import traceback
            logger.error(traceback.format_exc())
            results["tests_failed"] += 1
            results["errors"].append(f"Error verifying deletion via list: {str(e)}")
        
        return results
