#!/usr/bin/env python3
"""
List Business Events Test Case

Tests listing and searching business event entities.
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class ListBusinessEventsTester:
    """Test case for listing and searching business event entities."""
    
    def __init__(self, client):
        self.client = client
        
    async def run_tests(self, space_id: str, graph_id: str, expected_event_count: int = 10) -> Dict[str, Any]:
        """
        Run business event listing tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            expected_event_count: Expected number of events
            
        Returns:
            Dict containing test results
        """
        results = {
            "test_name": "List Business Events",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": []
        }
        
        logger.info("=" * 80)
        logger.info("  Listing Business Events")
        logger.info("=" * 80)
        
        # Test 1: List all business events by entity type
        results["tests_run"] += 1
        try:
            logger.info("Test 1: List all business events by entity type...")
            
            response = await self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type_uri="http://vital.ai/ontology/haley-ai-kg#BusinessEventEntity",
                page_size=100
            )
            
            if response.is_success:
                event_count = response.count
                logger.info(f"   Listed {event_count} business events")
                logger.info(f"      Expected: {expected_event_count}, Got: {event_count}")
                
                if event_count == expected_event_count:
                    logger.info(f"   ✅ Event count matches expected")
                    results["tests_passed"] += 1
                else:
                    logger.error(f"   ❌ Event count mismatch: expected {expected_event_count}, got {event_count}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Event count mismatch: expected {expected_event_count}, got {event_count}")
            else:
                logger.error(f"   ❌ Failed to list events: {response.error_message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Failed to list events: {response.error_message}")
                
        except Exception as e:
            logger.error(f"   ❌ Error listing events: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Error listing events: {str(e)}")
        
        # Test 2: Search for specific event types
        results["tests_run"] += 1
        try:
            logger.info("Test 2: Search for 'NewCustomer' events...")
            
            response = await self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type_uri="http://vital.ai/ontology/haley-ai-kg#BusinessEventEntity",
                search="NewCustomer",
                page_size=100
            )
            
            if response.is_success:
                found_count = response.count
                logger.info(f"   ✅ Found {found_count} 'NewCustomer' events")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ Failed to search events: {response.error_message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Failed to search events: {response.error_message}")
                
        except Exception as e:
            logger.error(f"   ❌ Error searching events: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Error searching events: {str(e)}")
        
        logger.info(f"\n✅ Completed {results['tests_passed']}/{results['tests_run']} list tests")
        
        return results
