"""
Entity Graph Operations Test Case

Tests for entity graph retrieval and deletion operations.
"""

import logging
from typing import Dict, Any
from vital_ai_vitalsigns.vitalsigns import VitalSigns

logger = logging.getLogger(__name__)


class EntityGraphOperationsTester:
    """Test entity graph operations (get, delete, verify)."""
    
    def __init__(self, client):
        self.client = client
    
    def run_tests(self, space_id: str, graph_id: str, test_entity_uri: str) -> Dict[str, Any]:
        """
        Run entity graph operation tests.
        
        Args:
            space_id: Space ID
            graph_id: Graph ID
            test_entity_uri: URI of test entity to operate on
            
        Returns:
            Dict with test results
        """
        results = {
            "test_name": "Entity Graph Operations",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": []
        }
        
        vs = VitalSigns()
        
        logger.info(f"\n{'='*100}")
        logger.info(f"  Entity Graph Operations")
        logger.info(f"{'='*100}")
        logger.info(f"Testing entity graph operations on: {test_entity_uri.split('/')[-1].replace('_', ' ').title()}")
        logger.info(f"Entity URI: {test_entity_uri}")
        
        # Test 1: Get Entity Graph
        results["tests_run"] += 1
        
        try:
            logger.info(f"\n--- Get Entity Graph ---\n")
            
            # Get the complete entity graph
            response = self.client.kgentities.get_kgentity(
                space_id=space_id,
                graph_id=graph_id,
                uri=test_entity_uri,
                include_entity_graph=True
            )
            
            # EntityGraphResponse has objects (EntityGraph container)
            if response.is_success and response.objects:
                entity_graph = response.objects
                entity_graph_objects = entity_graph.objects
                
                logger.info(f"   Retrieved entity graph with {len(entity_graph_objects)} objects")
                
                # Count object types
                object_types = {}
                for obj in entity_graph_objects:
                    obj_type = type(obj).__name__
                    object_types[obj_type] = object_types.get(obj_type, 0) + 1
                
                logger.info(f"   Object types: {object_types}")
                logger.info(f"✅ PASS: Get entity graph")
                results["tests_passed"] += 1
            else:
                logger.error(f"❌ FAIL: Get entity graph")
                logger.error(f"   No entity graph returned")
                results["tests_failed"] += 1
                results["errors"].append("No entity graph returned")
                
        except Exception as e:
            logger.error(f"❌ Error getting entity graph: {e}")
            import traceback
            logger.error(traceback.format_exc())
            results["tests_failed"] += 1
            results["errors"].append(f"Error getting entity graph: {str(e)}")
        
        # Test 2: Delete Entity Graph
        results["tests_run"] += 1
        
        try:
            logger.info(f"\n--- Delete Entity Graph ---\n")
            
            # Delete the entity
            delete_response = self.client.kgentities.delete_kgentity(
                space_id=space_id,
                graph_id=graph_id,
                uri=test_entity_uri,
                delete_entity_graph=True
            )
            
            if delete_response.is_success:
                logger.info(f"   ✅ Entity deleted successfully")
                logger.info(f"✅ PASS: Delete entity graph")
                results["tests_passed"] += 1
            else:
                logger.error(f"❌ FAIL: Delete entity graph")
                logger.error(f"   Delete failed: {delete_response.message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Entity delete failed: {delete_response.message}")
                
        except Exception as e:
            logger.error(f"❌ Error deleting entity graph: {e}")
            import traceback
            logger.error(traceback.format_exc())
            results["tests_failed"] += 1
            results["errors"].append(f"Error deleting entity graph: {str(e)}")
        
        # Test 3: Verify Entity Deletion
        results["tests_run"] += 1
        
        try:
            logger.info(f"\n--- Verify Entity Deletion ---\n")
            
            # Try to get the deleted entity
            logger.info(f"   Attempting to get deleted entity...")
            try:
                get_deleted_response = self.client.kgentities.get_kgentity(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri=test_entity_uri
                )
                
                # Check if response is empty or has no data
                if get_deleted_response:
                    entity_dict = get_deleted_response.model_dump(by_alias=True) if hasattr(get_deleted_response, 'model_dump') else get_deleted_response
                    objects_in_graph = entity_dict.get('@graph', [])
                    if not objects_in_graph or len(objects_in_graph) == 0:
                        logger.info(f"   ✅ Get deleted entity returned empty graph (as expected)")
                    else:
                        logger.error(f"   ❌ Deleted entity still exists with {len(objects_in_graph)} objects")
                        results["tests_failed"] += 1
                        results["errors"].append("Deleted entity still returned by get operation")
                else:
                    logger.info(f"   ✅ Get deleted entity returned None (as expected)")
            except Exception as get_error:
                # Entity not found - this is also expected
                logger.info(f"   ✅ Get deleted entity failed (as expected): {get_error}")
            
            # List all entities to verify deletion
            logger.info(f"   Verifying deletion by listing all entities...")
            list_response = self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=100
            )
            
            # Check that the deleted entity is not in the list
            entity_uris_in_list = [str(e.URI) for e in list_response.objects if hasattr(e, 'URI')] if list_response.objects else []
            
            if test_entity_uri not in entity_uris_in_list:
                logger.info(f"   ✅ Deleted entity not in entity list (as expected)")
                logger.info(f"   Remaining entities: {len(entity_uris_in_list)}")
                logger.info(f"✅ PASS: Verify entity deletion")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ Deleted entity still in entity list")
                logger.error(f"❌ FAIL: Verify entity deletion")
                results["tests_failed"] += 1
                results["errors"].append("Deleted entity still appears in entity list")
                
        except Exception as e:
            logger.error(f"❌ Error verifying entity deletion: {e}")
            import traceback
            logger.error(traceback.format_exc())
            results["tests_failed"] += 1
            results["errors"].append(f"Error verifying entity deletion: {str(e)}")
        
        return results
