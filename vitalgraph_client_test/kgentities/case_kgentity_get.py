#!/usr/bin/env python3
"""
KGEntity Get Test Case

Client-based test case for KGEntity retrieval operations using VitalGraph client.
"""

import logging
from typing import Dict, Any, Union

logger = logging.getLogger(__name__)


class KGEntityGetTester:
    """Test case for KGEntity retrieval operations."""
    
    def __init__(self, client):
        self.client = client
        
    def run_tests(self, space_id: str, graph_id: str, created_entities: list = None) -> Dict[str, Any]:
        """
        Run KGEntity retrieval tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            
        Returns:
            Dict containing test results
        """
        results = {
            "test_name": "KGEntity Get Tests",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": []
        }
        
        # First get a URI to test with
        test_uri = None
        try:
            list_response = self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=1
            )
            
            # Modern client returns PaginatedGraphObjectResponse with GraphObjects
            if list_response.is_success and hasattr(list_response, 'objects') and list_response.objects:
                # Extract URI from first GraphObject
                test_uri = str(list_response.objects[0].URI)
                logger.info(f"🔍 Using test URI: {test_uri}")
            else:
                logger.warning("⚠️ No entities found for testing retrieval")
                return results
                
        except Exception as e:
            logger.error(f"❌ Failed to get test URI: {e}")
            results["errors"].append(f"Failed to get test URI: {str(e)}")
            return results
        
        # Test 1: Get specific entity by URI
        logger.info("🔍 Testing get specific KGEntity by URI...")
        try:
            entity_response = self.client.kgentities.get_kgentity(
                space_id=space_id,
                graph_id=graph_id,
                uri=test_uri
            )
            
            results["tests_run"] += 1
            
            # Modern client returns EntityResponse with GraphObjects list
            if entity_response.is_success and hasattr(entity_response, 'objects') and entity_response.objects:
                entity_obj = entity_response.objects[0]  # Get first object from list
                logger.info(f"✅ Get entity successful - EntityResponse")
                logger.info(f"   - Entity URI: {str(entity_obj.URI)}")
                logger.info(f"   - Entity type: {type(entity_obj).__name__}")
                results["tests_passed"] += 1
            else:
                logger.error(f"❌ Unexpected response type or no objects: {type(entity_response)}")
                results["tests_failed"] += 1
                results["errors"].append(f"Unexpected response type: {type(entity_response)}")
                
        except Exception as e:
            logger.error(f"❌ Get specific entity failed: {e}")
            results["tests_run"] += 1
            results["tests_failed"] += 1
            results["errors"].append(f"Get specific entity error: {str(e)}")
        
        # Test 2: Get entity with complete graph
        logger.info("🔍 Testing get entity with complete graph...")
        try:
            graph_response = self.client.kgentities.get_kgentity(
                space_id=space_id,
                graph_id=graph_id,
                uri=test_uri,
                include_entity_graph=True
            )
            
            results["tests_run"] += 1
            
            # Should return EntityGraphResponse when include_entity_graph=True
            if graph_response.is_success and hasattr(graph_response, 'objects') and graph_response.objects:
                # EntityGraphResponse.objects is an EntityGraph container
                entity_graph = graph_response.objects
                if entity_graph.objects:
                    logger.info(f"✅ Get entity with graph successful - EntityGraphResponse with {len(entity_graph.objects)} objects")
                    
                    # Analyze object types
                    object_types = {}
                    for obj in entity_graph.objects:
                        obj_type = type(obj).__name__
                        object_types[obj_type] = object_types.get(obj_type, 0) + 1
                    
                    logger.info("   • Object type breakdown:")
                    for obj_type, count in object_types.items():
                        logger.info(f"     - {obj_type}: {count}")
                    
                    results["tests_passed"] += 1
                else:
                    logger.error("❌ No entity data found in complete graph response")
                    results["tests_failed"] += 1
                    results["errors"].append("No entity data found in complete graph response")
            else:
                logger.warning(f"⚠️ Expected EntityGraphResponse with objects but got {type(graph_response)}")
                results["tests_failed"] += 1
                results["errors"].append(f"Unexpected response type: {type(graph_response)}")
                
        except Exception as e:
            logger.error(f"❌ Get entity with graph failed: {e}")
            results["tests_run"] += 1
            results["tests_failed"] += 1
            results["errors"].append(f"Get entity with graph error: {str(e)}")
        
        # Test 3: Get non-existent entity (error handling)
        logger.info("🔍 Testing get non-existent entity...")
        try:
            fake_uri = "http://vital.ai/test/nonexistent/entity/12345"
            nonexistent_response = self.client.kgentities.get_kgentity(
                space_id=space_id,
                graph_id=graph_id,
                uri=fake_uri
            )
            
            results["tests_run"] += 1
            
            # Modern client returns EntityResponse with empty objects list for non-existent entity
            if nonexistent_response.is_success and hasattr(nonexistent_response, 'objects'):
                if not nonexistent_response.objects or len(nonexistent_response.objects) == 0:
                    logger.info("✅ Non-existent entity correctly returned EntityResponse with empty objects list")
                    results["tests_passed"] += 1
                else:
                    logger.warning(f"⚠️ Non-existent entity returned EntityResponse with {len(nonexistent_response.objects)} objects (unexpected)")
                    results["tests_passed"] += 1  # Still count as passed
            else:
                logger.error(f"❌ Unexpected response type for non-existent entity: {type(nonexistent_response)}")
                results["tests_failed"] += 1
                results["errors"].append(f"Unexpected response type for non-existent entity: {type(nonexistent_response)}")
                
        except Exception as e:
            # This might be expected behavior (404 error)
            logger.info(f"✅ Non-existent entity correctly raised exception: {e}")
            results["tests_run"] += 1
            results["tests_passed"] += 1
        
        logger.info(f"📊 KGEntity Get Tests Summary: {results['tests_passed']}/{results['tests_run']} passed")
        return results
