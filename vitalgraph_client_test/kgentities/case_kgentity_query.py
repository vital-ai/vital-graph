#!/usr/bin/env python3
"""
KGEntity Query Test Case

Client-based test case for KGEntity query operations using VitalGraph client.
"""

import logging
from typing import Dict, Any
from vitalgraph.model.kgentities_model import (
    EntityQueryRequest, EntityQueryCriteria, QueryFilter
)
from vitalgraph.client.response.client_response import QueryResponse

logger = logging.getLogger(__name__)


class KGEntityQueryTester:
    """Test case for KGEntity query operations."""
    
    def __init__(self, client):
        self.client = client
        
    def run_tests(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """
        Run KGEntity query tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            
        Returns:
            Dict containing test results
        """
        results = {
            "test_name": "KGEntity Query Tests",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": []
        }
        
        # Test 1: Basic entity query with search string
        logger.info("🔍 Testing basic entity query with search string...")
        try:
            # Server expects EntityQueryRequest format with nested criteria
            query_criteria = {
                "criteria": {
                    "search_string": "Test",
                    "entity_type": None,
                    "frame_type": None
                },
                "page_size": 5,
                "offset": 0
            }
            
            query_response = self.client.kgentities.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                query_criteria=query_criteria
            )
            
            results["tests_run"] += 1
            
            if isinstance(query_response, QueryResponse):
                if hasattr(query_response, 'objects'):
                    logger.info(f"✅ Basic query successful - Found {len(query_response.objects)} entities")
                    for i, obj in enumerate(query_response.objects[:3]):
                        logger.info(f"   - Entity {i+1}: {obj.URI if hasattr(obj, 'URI') else obj}")
                    results["tests_passed"] += 1
                else:
                    logger.error("❌ Query response missing objects field")
                    results["tests_failed"] += 1
                    results["errors"].append("Query response missing objects field")
            else:
                logger.error(f"❌ Unexpected query response type: {type(query_response)}")
                results["tests_failed"] += 1
                results["errors"].append(f"Unexpected query response type: {type(query_response)}")
                
        except Exception as e:
            logger.error(f"❌ Basic entity query failed: {e}")
            results["tests_run"] += 1
            results["tests_failed"] += 1
            results["errors"].append(f"Basic entity query error: {str(e)}")
        
        # Test 2: Query with entity type filter
        logger.info("🔍 Testing entity query with entity type filter...")
        try:
            # Server expects EntityQueryRequest format with nested criteria
            query_criteria = {
                "criteria": {
                    "search_string": None,
                    "entity_type": "http://vital.ai/ontology/haley-ai-kg#KGEntity",
                    "frame_type": None
                },
                "page_size": 10,
                "offset": 0
            }
            
            type_response = self.client.kgentities.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                query_criteria=query_criteria
            )
            
            results["tests_run"] += 1
            
            if isinstance(type_response, QueryResponse) and hasattr(type_response, 'objects'):
                logger.info(f"✅ Entity type query successful - Found {len(type_response.objects)} KGEntities")
                results["tests_passed"] += 1
            else:
                logger.error(f"❌ Entity type query failed - response type: {type(type_response)}")
                results["tests_failed"] += 1
                results["errors"].append(f"Entity type query failed - response type: {type(type_response)}")
                
        except Exception as e:
            logger.error(f"❌ Entity type query failed: {e}")
            results["tests_run"] += 1
            results["tests_failed"] += 1
            results["errors"].append(f"Entity type query error: {str(e)}")
        
        # Test 3: Query with QueryFilter (property-based filtering)
        logger.info("🔍 Testing QueryFilter functionality...")
        try:
            # Server expects EntityQueryRequest format with nested criteria
            query_criteria = {
                "criteria": {
                    "search_string": None,
                    "entity_type": None,
                    "frame_type": None,
                    "filters": [{
                        "property_name": "name",
                        "value": "Test",
                        "operator": "contains"
                    }]
                },
                "page_size": 5,
                "offset": 0
            }
            
            filter_response = self.client.kgentities.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                query_criteria=query_criteria
            )
            
            results["tests_run"] += 1
            
            if isinstance(filter_response, QueryResponse) and hasattr(filter_response, 'objects'):
                entity_count = len(filter_response.objects)
                # Should find at least "Test Person" or "Test Organization"
                if entity_count >= 1:
                    logger.info(f"✅ QueryFilter test successful - Found {entity_count} filtered entities")
                    results["tests_passed"] += 1
                else:
                    logger.error(f"❌ QueryFilter test failed - Expected at least 1 entity but found {entity_count}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"QueryFilter test failed - Expected at least 1 entity but found {entity_count}")
            else:
                logger.error(f"❌ QueryFilter test failed - response type: {type(filter_response)}")
                results["tests_failed"] += 1
                results["errors"].append(f"QueryFilter test failed - response type: {type(filter_response)}")
                
        except Exception as e:
            logger.error(f"❌ QueryFilter test failed: {e}")
            results["tests_run"] += 1
            results["tests_failed"] += 1
            results["errors"].append(f"QueryFilter test error: {str(e)}")
        
        # Test 4: Query with multiple filters
        logger.info("🔍 Testing multiple QueryFilters...")
        try:
            # Server expects EntityQueryRequest format with nested criteria
            query_criteria = {
                "criteria": {
                    "search_string": None,
                    "entity_type": None,
                    "frame_type": None,
                    "filters": [
                        {
                            "property_name": "name",
                            "value": "Test",
                            "operator": "contains"
                        },
                        {
                            "property_name": "name",
                            "value": "Person",
                            "operator": "contains"
                        }
                    ]
                },
                "page_size": 5,
                "offset": 0
            }
            
            multi_filter_response = self.client.kgentities.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                query_criteria=query_criteria
            )
            
            results["tests_run"] += 1
            
            if isinstance(multi_filter_response, QueryResponse) and hasattr(multi_filter_response, 'objects'):
                entity_count = len(multi_filter_response.objects)
                # Should find "Test Person" entity which contains both "Test" and "Person"
                if entity_count >= 1:
                    logger.info(f"✅ Multiple QueryFilters test successful - Found {entity_count} entities matching filters")
                    results["tests_passed"] += 1
                else:
                    logger.error(f"❌ Multiple QueryFilters test failed - Expected at least 1 entity but found {entity_count}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Multiple QueryFilters test failed - Expected at least 1 entity but found {entity_count}")
            else:
                logger.error(f"❌ Multiple QueryFilters test failed - response type: {type(multi_filter_response)}")
                results["tests_failed"] += 1
                results["errors"].append(f"Multiple QueryFilters test failed - response type: {type(multi_filter_response)}")
                
        except Exception as e:
            logger.error(f"❌ Multiple QueryFilters test failed: {e}")
            results["tests_run"] += 1
            results["tests_failed"] += 1
            results["errors"].append(f"Multiple QueryFilters test error: {str(e)}")
        
        # Test 5: Query with pagination
        logger.info("🔍 Testing query pagination...")
        try:
            # Server expects EntityQueryRequest format with nested criteria
            # First page
            query_criteria_page1 = {
                "criteria": {
                    "search_string": "test",
                    "entity_type": None,
                    "frame_type": None
                },
                "page_size": 3,
                "offset": 0
            }
            
            page1_response = self.client.kgentities.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                query_criteria=query_criteria_page1
            )
            
            # Second page
            query_criteria_page2 = {
                "criteria": {
                    "search_string": "test",
                    "entity_type": None,
                    "frame_type": None
                },
                "page_size": 3,
                "offset": 3
            }
            
            page2_response = self.client.kgentities.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                query_criteria=query_criteria_page2
            )
            
            results["tests_run"] += 1
            
            if (isinstance(page1_response, QueryResponse) and hasattr(page1_response, 'objects') and
                isinstance(page2_response, QueryResponse) and hasattr(page2_response, 'objects')):
                
                page1_count = len(page1_response.objects)
                page2_count = len(page2_response.objects)
                
                logger.info(f"✅ Query pagination successful - Page 1: {page1_count}, Page 2: {page2_count}")
                results["tests_passed"] += 1
            else:
                logger.error("❌ Query pagination failed - invalid response types")
                results["tests_failed"] += 1
                results["errors"].append("Query pagination failed - invalid response types")
                
        except Exception as e:
            logger.error(f"❌ Query pagination failed: {e}")
            results["tests_run"] += 1
            results["tests_failed"] += 1
            results["errors"].append(f"Query pagination error: {str(e)}")
        
        logger.info(f"📊 KGEntity Query Tests Summary: {results['tests_passed']}/{results['tests_run']} passed")
        return results
