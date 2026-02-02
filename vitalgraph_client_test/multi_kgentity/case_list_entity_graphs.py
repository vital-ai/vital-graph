#!/usr/bin/env python3
"""
List Entity Graphs Test Case

Tests listing entities with complete entity graphs (include_entity_graph=True).
This returns MultiEntityGraphResponse with graph_list containing EntityGraph containers.
"""

import logging
from typing import Dict, Any
from ai_haley_kg_domain.model.KGEntity import KGEntity

logger = logging.getLogger(__name__)


class ListEntityGraphsTester:
    """Test case for listing entities with complete graphs."""
    
    def __init__(self, client):
        self.client = client
    
    def run_tests(
        self,
        space_id: str,
        graph_id: str,
        test_entity_uris: list
    ) -> Dict[str, Any]:
        """
        Run list entity graphs tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            test_entity_uris: List of entity URIs to test with
            
        Returns:
            Dictionary with test results
        """
        results = {
            "test_name": "List Entity Graphs",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": []
        }
        
        logger.info(f"\n{'='*100}")
        logger.info(f"List Entity Graphs")
        logger.info(f"{'='*100}")
        
        if not test_entity_uris or len(test_entity_uris) < 3:
            logger.error("Need at least 3 test entities")
            return results
        
        # ========================================================================
        # TEST: List entities with complete graphs (MultiEntityGraphResponse)
        # ========================================================================
        results["tests_run"] += 1
        
        try:
            logger.info(f"\n--- List Entities with Complete Graphs ---\n")
            logger.info(f"Listing entities with include_entity_graph=True")
            
            # List entities with complete graphs - returns MultiEntityGraphResponse
            response = self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=5,
                include_entity_graph=True
            )
            
            logger.info(f"   Response type: {type(response).__name__}")
            logger.info(f"   Response success: {response.is_success}")
            logger.info(f"   Response has graph_list: {hasattr(response, 'graph_list')}")
            if hasattr(response, 'graph_list'):
                logger.info(f"   graph_list value: {response.graph_list}")
            
            if response.is_success and hasattr(response, 'graph_list') and response.graph_list:
                # MultiEntityGraphResponse.graph_list is List[EntityGraph]
                entity_graphs = response.graph_list
                logger.info(f"   Retrieved {len(entity_graphs)} entity graphs")
                
                # Verify each EntityGraph has entity_uri and objects
                valid_graphs = 0
                for entity_graph in entity_graphs:
                    if entity_graph.entity_uri and entity_graph.objects:
                        valid_graphs += 1
                        
                        # Count objects in this graph
                        entity_count = sum(1 for obj in entity_graph.objects if isinstance(obj, KGEntity))
                        frame_count = sum(1 for obj in entity_graph.objects if 'Frame' in type(obj).__name__)
                        slot_count = sum(1 for obj in entity_graph.objects if 'Slot' in type(obj).__name__)
                        
                        logger.info(f"   Graph {entity_graph.entity_uri}:")
                        logger.info(f"     - Total objects: {len(entity_graph.objects)}")
                        logger.info(f"     - Entities: {entity_count}, Frames: {frame_count}, Slots: {slot_count}")
                
                if valid_graphs >= 3:
                    logger.info(f"✅ PASS: List entities with complete graphs")
                    logger.info(f"   Retrieved {valid_graphs} valid entity graphs")
                    results["tests_passed"] += 1
                else:
                    logger.error(f"❌ FAIL: Expected at least 3 entity graphs, got {valid_graphs}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Insufficient entity graphs: {valid_graphs}")
            else:
                logger.error(f"❌ FAIL: No entity graphs returned")
                results["tests_failed"] += 1
                results["errors"].append("No entity graphs in response")
                
        except Exception as e:
            logger.error(f"❌ FAIL: List entity graphs test")
            logger.error(f"   Error: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"List entity graphs error: {str(e)}")
        
        # ========================================================================
        # TEST: Access individual graphs from MultiEntityGraphResponse
        # ========================================================================
        results["tests_run"] += 1
        
        try:
            logger.info(f"\n--- Access Individual Entity Graphs ---\n")
            
            # Get entity graphs again
            response = self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=3,
                include_entity_graph=True
            )
            
            if response.is_success and response.graph_list and len(response.graph_list) > 0:
                # Access first entity graph
                first_graph = response.graph_list[0]
                logger.info(f"   First entity graph URI: {first_graph.entity_uri}")
                logger.info(f"   Objects in first graph: {len(first_graph.objects)}")
                
                # Verify we can iterate and access objects
                entity_found = False
                for obj in first_graph.objects:
                    if isinstance(obj, KGEntity):
                        entity_found = True
                        entity_name = str(obj.name) if hasattr(obj, 'name') and obj.name else 'Unknown'
                        logger.info(f"   Entity name: {entity_name}")
                        break
                
                if entity_found:
                    logger.info(f"✅ PASS: Access individual entity graphs")
                    results["tests_passed"] += 1
                else:
                    logger.error(f"❌ FAIL: No entity found in graph")
                    results["tests_failed"] += 1
                    results["errors"].append("No entity in first graph")
            else:
                logger.error(f"❌ FAIL: No graphs to access")
                results["tests_failed"] += 1
                results["errors"].append("No graphs in response")
                
        except Exception as e:
            logger.error(f"❌ FAIL: Access individual graphs test")
            logger.error(f"   Error: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Access graphs error: {str(e)}")
        
        return results
