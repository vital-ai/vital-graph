#!/usr/bin/env python3
"""
List Entities Test Case

Tests listing all entities and searching with filters.
"""

import logging
from typing import Dict, Any
from ai_haley_kg_domain.model.KGEntity import KGEntity

logger = logging.getLogger(__name__)


class ListEntitiesTester:
    """Test case for listing and searching entities."""
    
    def __init__(self, client):
        self.client = client
        
    async def run_tests(self, space_id: str, graph_id: str, expected_count: int = 10) -> Dict[str, Any]:
        """
        Run entity listing tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            expected_count: Expected number of entities
            
        Returns:
            Dict containing test results
        """
        results = {
            "test_name": "List and Search Entities",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": []
        }
        
        logger.info("=" * 80)
        logger.info("  List All Organization Entities")
        logger.info("=" * 80)
        
        # Test 1: List all entities
        results["tests_run"] += 1
        try:
            response = await self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=20
            )
            
            entities_found = response.total_count if response.is_success else 0
            logger.info(f"\nFound {entities_found} entities (expected {expected_count})")
            
            if entities_found == expected_count:
                logger.info("✅ PASS: List all entities")
                results["tests_passed"] += 1
            else:
                logger.error(f"❌ FAIL: Expected {expected_count} entities, found {entities_found}")
                results["tests_failed"] += 1
                results["errors"].append(f"Entity count mismatch: {entities_found} vs {expected_count}")
            
            # Display entities - direct GraphObject access
            if response.is_success and response.objects:
                logger.info("\n📋 Organizations in system:")
                i = 1
                for obj in response.objects:
                    if isinstance(obj, KGEntity):
                        name = str(obj.name) if obj.name else 'Unknown'
                        uri = str(obj.URI)
                        logger.info(f"   {i}. {name}")
                        logger.info(f"      URI: {uri}")
                        i += 1
                        
        except Exception as e:
            logger.error(f"❌ Error listing entities: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Error listing entities: {str(e)}")
        
        # Test 2: Search with filter (searches entity name only)
        results["tests_run"] += 1
        try:
            logger.info("\n" + "=" * 80)
            logger.info("  Query Entities - Search by Name")
            logger.info("=" * 80)
            
            response = await self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                search="Corp",  # Search for "Corp" which appears in multiple entity names
                page_size=20
            )
            
            search_count = response.total_count if response.is_success else 0
            logger.info(f"\nFound {search_count} matching entities")
            
            if search_count >= 1:
                logger.info("✅ PASS: Search for 'Corp' in entity names")
                results["tests_passed"] += 1
                
                if response.is_success and response.objects:
                    logger.info("\n📋 Organizations with 'Corp' in name:")
                    for obj in response.objects:
                        if isinstance(obj, KGEntity):
                            name = str(obj.name) if obj.name else 'Unknown'
                            logger.info(f"   • {name}")
            else:
                logger.error("❌ FAIL: No entities found with 'Corp' in name")
                results["tests_failed"] += 1
                results["errors"].append("Search returned no results for 'Corp'")
                
        except Exception as e:
            logger.error(f"❌ Error searching entities: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Error searching entities: {str(e)}")
        
        return results
