#!/usr/bin/env python3
"""
KGEntity List Test Case

Client-based test case for KGEntity listing operations using VitalGraph client.
"""

import logging
from typing import Dict, Any, Union
from vitalgraph.utils.graph_utils import sort_objects_into_dag, pretty_print_dag
from vital_ai_vitalsigns.model.GraphObject import GraphObject

logger = logging.getLogger(__name__)


class KGEntityListTester:
    """Test case for KGEntity listing operations."""
    
    def __init__(self, client):
        self.client = client
        
    async def run_tests(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """
        Run KGEntity listing tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            
        Returns:
            Dict containing test results
        """
        results = {
            "test_name": "KGEntity List Tests",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": []
        }
        
        # Test 1: Basic listing with pagination
        logger.info("🔍 Testing basic KGEntity listing...")
        try:
            response = await self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=5,
                offset=0
            )
            
            results["tests_run"] += 1
            
            # Modern client returns PaginatedGraphObjectResponse with GraphObjects
            if response.is_success and hasattr(response, 'objects'):
                entities = response.objects
                from ai_haley_kg_domain.model.KGEntity import KGEntity
                entity_count = sum(1 for obj in entities if isinstance(obj, KGEntity))
                logger.info(f"✅ Basic listing successful - PaginatedGraphObjectResponse with {entity_count} entities")
                logger.info(f"   Total count: {response.total_count if hasattr(response, 'total_count') else 'N/A'}")
                logger.info(f"   Page size: {response.page_size if hasattr(response, 'page_size') else 'N/A'}")
                results["tests_passed"] += 1
            else:
                logger.error(f"❌ Unexpected response type: {type(response)}")
                results["tests_failed"] += 1
                results["errors"].append(f"Unexpected response type: {type(response)}")
                
        except Exception as e:
            logger.error(f"❌ Basic listing failed: {e}")
            results["tests_run"] += 1
            results["tests_failed"] += 1
            results["errors"].append(f"Basic listing error: {str(e)}")
        
        # Test 2: Search functionality
        logger.info("🔍 Testing KGEntity search...")
        try:
            search_response = await self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=3,
                search="test"
            )
            
            results["tests_run"] += 1
            
            # Modern client returns PaginatedGraphObjectResponse
            if search_response.is_success and hasattr(search_response, 'objects'):
                entities = search_response.objects
                from ai_haley_kg_domain.model.KGEntity import KGEntity
                entity_count = sum(1 for obj in entities if isinstance(obj, KGEntity))
                logger.info(f"✅ Search successful - PaginatedGraphObjectResponse with {entity_count} matching entities")
                logger.info(f"   Total count: {search_response.total_count if hasattr(search_response, 'total_count') else 'N/A'}")
            else:
                logger.error(f"❌ Unexpected search response type: {type(search_response)}")
                results["tests_failed"] += 1
                results["errors"].append(f"Unexpected search response type: {type(search_response)}")
                return results
                
            results["tests_passed"] += 1
            
        except Exception as e:
            logger.error(f"❌ Search failed: {e}")
            results["tests_run"] += 1
            results["tests_failed"] += 1
            results["errors"].append(f"Search error: {str(e)}")
        
        # Test 3: Entity type filtering
        logger.info("🔍 Testing entity type filtering...")
        try:
            filter_response = await self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=5,
                entity_type_uri="http://vital.ai/ontology/haley-ai-kg#KGEntity"
            )
            
            results["tests_run"] += 1
            
            # Modern client returns PaginatedGraphObjectResponse
            if filter_response.is_success and hasattr(filter_response, 'objects'):
                entities = filter_response.objects
                from ai_haley_kg_domain.model.KGEntity import KGEntity
                entity_count = sum(1 for obj in entities if isinstance(obj, KGEntity))
                logger.info(f"✅ Entity type filtering successful - {entity_count} entities")
                results["tests_passed"] += 1
            else:
                logger.error(f"❌ Unexpected filter response type: {type(filter_response)}")
                results["tests_failed"] += 1
                results["errors"].append(f"Unexpected filter response type: {type(filter_response)}")
                
        except Exception as e:
            logger.error(f"❌ Entity type filtering failed: {e}")
            results["tests_run"] += 1
            results["tests_failed"] += 1
            results["errors"].append(f"Entity type filtering error: {str(e)}")
        
        # Test 4: Include entity graph parameter
        logger.info("🔍 Testing include_entity_graph parameter...")
        try:
            graph_response = await self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=2,
                include_entity_graph=True
            )
            
            results["tests_run"] += 1
            
            # Should return MultiEntityGraphResponse when include_entity_graph=True
            if graph_response.is_success and hasattr(graph_response, 'graph_list'):
                entity_graphs = graph_response.graph_list if graph_response.graph_list else []
                logger.info(f"✅ Include entity graph successful - MultiEntityGraphResponse with {len(entity_graphs)} entity graphs")
                
                if entity_graphs:
                    # Verify each EntityGraph has entity_uri and objects
                    valid_graphs = 0
                    total_objects = 0
                    for entity_graph in entity_graphs:
                        if entity_graph.entity_uri and entity_graph.objects:
                            valid_graphs += 1
                            total_objects += len(entity_graph.objects)
                            
                            # Count objects in this graph
                            from ai_haley_kg_domain.model.KGEntity import KGEntity
                            entity_count = sum(1 for obj in entity_graph.objects if isinstance(obj, KGEntity))
                            frame_count = sum(1 for obj in entity_graph.objects if 'Frame' in type(obj).__name__)
                            slot_count = sum(1 for obj in entity_graph.objects if 'Slot' in type(obj).__name__)
                            
                            logger.info(f"   Graph {entity_graph.entity_uri}:")
                            logger.info(f"     - Total objects: {len(entity_graph.objects)}")
                            logger.info(f"     - Entities: {entity_count}, Frames: {frame_count}, Slots: {slot_count}")
                    
                    logger.info(f"✅ PASS: Retrieved {valid_graphs} valid entity graphs with {total_objects} total objects")
                else:
                    logger.info(f"✅ PASS: MultiEntityGraphResponse returned (empty - no test entities created yet)")
                
                results["tests_passed"] += 1
            else:
                logger.warning(f"⚠️ Expected MultiEntityGraphResponse with graph_list but got {type(graph_response)}")
                results["tests_failed"] += 1
                results["errors"].append(f"Unexpected response type: {type(graph_response)}")
                
        except Exception as e:
            logger.error(f"❌ Include entity graph failed: {e}")
            results["tests_run"] += 1
            results["tests_failed"] += 1
            results["errors"].append(f"Include entity graph error: {str(e)}")
        
        # Test 5: Pagination with different page sizes
        logger.info("🔍 Testing pagination...")
        results["tests_run"] += 1
        pagination_passed = True
        
        for page_size in [1, 5, 10]:
            try:
                page_response = await self.client.kgentities.list_kgentities(
                    space_id=space_id,
                    graph_id=graph_id,
                    page_size=page_size,
                    offset=0
                )
                
                # Modern client returns PaginatedGraphObjectResponse
                if page_response.is_success and hasattr(page_response, 'objects'):
                    entities = page_response.objects
                    logger.info(f"✅ Pagination (page_size={page_size}) successful - {len(entities)} entities")
                else:
                    logger.error(f"❌ Unexpected pagination response type: {type(page_response)}")
                    pagination_passed = False
                    results["errors"].append(f"Unexpected pagination response type: {type(page_response)}")
                    
            except Exception as e:
                logger.error(f"❌ Pagination (page_size={page_size}) failed: {e}")
                pagination_passed = False
                results["errors"].append(f"Pagination error (page_size={page_size}): {str(e)}")
        
        # Record pagination test result
        if pagination_passed:
            results["tests_passed"] += 1
        else:
            results["tests_failed"] += 1
        
        logger.info(f"📊 KGEntity List Tests Summary: {results['tests_passed']}/{results['tests_run']} passed")
        return results
