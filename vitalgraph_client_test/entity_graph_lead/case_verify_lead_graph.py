"""
Verify Lead Entity Graph Test Case

Tests verifying the structure and content of a loaded lead entity graph.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class VerifyLeadGraphTester:
    """Test case for verifying lead entity graph structure."""
    
    def __init__(self, client):
        self.client = client
    
    def run_tests(self, space_id: str, graph_id: str, entity_uri: str, 
                  expected_triple_count: int = None) -> Dict[str, Any]:
        """
        Run lead entity graph verification tests.
        
        Args:
            space_id: Space ID
            graph_id: Graph ID
            entity_uri: URI of the entity to verify
            expected_triple_count: Expected number of triples (optional)
            
        Returns:
            Dict with test results
        """
        results = {
            "test_name": "Verify Lead Entity Graph",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
            "object_counts": {}
        }
        
        logger.info(f"\n{'='*100}")
        logger.info(f"  Verify Lead Entity Graph")
        logger.info(f"{'='*100}")
        logger.info(f"Entity URI: {entity_uri}")
        
        # Test 1: Get entity graph
        results["tests_run"] += 1
        
        try:
            logger.info(f"\n--- Get Entity Graph ---\n")
            
            # Get the complete entity graph
            response = self.client.kgentities.get_kgentity(
                space_id=space_id,
                graph_id=graph_id,
                uri=entity_uri,
                include_entity_graph=True
            )
            
            if response.is_success and response.objects:
                # Direct access to EntityGraph
                entity_graph = response.objects
                entity_graph_objects = entity_graph.objects
                
                logger.info(f"   Retrieved entity graph with {len(entity_graph_objects)} objects")
                
                # Count object types
                object_types = {}
                for obj in entity_graph_objects:
                    obj_type = type(obj).__name__
                    object_types[obj_type] = object_types.get(obj_type, 0) + 1
                
                results["object_counts"] = object_types
                
                logger.info(f"   Object type breakdown:")
                for obj_type, count in sorted(object_types.items(), key=lambda x: x[1], reverse=True):
                    logger.info(f"      {obj_type}: {count}")
                
                logger.info(f"✅ PASS: Get entity graph")
                results["tests_passed"] += 1
            else:
                logger.error(f"❌ FAIL: Get entity graph")
                if response.is_error:
                    logger.error(f"   Error {response.error_code}: {response.error_message}")
                else:
                    logger.error(f"   No entity graph returned")
                results["tests_failed"] += 1
                results["errors"].append("No entity graph returned")
                
        except Exception as e:
            logger.error(f"❌ Error getting entity graph: {e}")
            import traceback
            logger.error(traceback.format_exc())
            results["tests_failed"] += 1
            results["errors"].append(f"Error getting entity graph: {str(e)}")
        
        # Test 2: Verify entity exists
        results["tests_run"] += 1
        
        try:
            logger.info(f"\n--- Verify Entity Exists ---\n")
            
            # Get just the entity (without full graph)
            entity_response = self.client.kgentities.get_kgentity(
                space_id=space_id,
                graph_id=graph_id,
                uri=entity_uri,
                include_entity_graph=False
            )
            
            if entity_response:
                logger.info(f"   ✅ Entity exists and is retrievable")
                logger.info(f"✅ PASS: Verify entity exists")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ Entity not found")
                results["tests_failed"] += 1
                results["errors"].append("Entity not found")
                
        except Exception as e:
            logger.error(f"❌ Error verifying entity: {e}")
            import traceback
            logger.error(traceback.format_exc())
            results["tests_failed"] += 1
            results["errors"].append(f"Error verifying entity: {str(e)}")
        
        # Test 3: Verify entity in list
        results["tests_run"] += 1
        
        try:
            logger.info(f"\n--- Verify Entity in List ---\n")
            
            # List entities to confirm it's there
            list_response = self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=100
            )
            
            logger.info(f"   Verifying entity in list...")
            logger.info(f"   Total entities in graph: {list_response.total_count}")
            
            # Extract entity URIs from response
            entity_uris_in_list = []
            
            # PaginatedGraphObjectResponse.objects contains List[GraphObject]
            if list_response.objects:
                for obj in list_response.objects:
                    if hasattr(obj, 'URI'):
                        entity_uris_in_list.append(str(obj.URI))
            
            logger.info(f"   Found {len(entity_uris_in_list)} entity URI(s) in list")
            logger.info(f"   Looking for entity URI: {entity_uri}")
            
            if entity_uri in entity_uris_in_list:
                logger.info(f"   ✅ Entity found in list")
                logger.info(f"   Total entities in graph: {list_response.total_count}")
                logger.info(f"✅ PASS: Verify entity in list")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ Entity not found in list")
                logger.error(f"   Total entities in graph: {list_response.total_count}")
                results["tests_failed"] += 1
                results["errors"].append("Entity not found in list")
                
        except Exception as e:
            logger.error(f"❌ Error verifying entity in list: {e}")
            import traceback
            logger.error(traceback.format_exc())
            results["tests_failed"] += 1
            results["errors"].append(f"Error verifying entity in list: {str(e)}")
        
        return results
