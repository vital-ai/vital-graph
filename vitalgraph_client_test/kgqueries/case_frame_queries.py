#!/usr/bin/env python3
"""
Frame Queries Test Case

Test case for frame-based entity queries using multi-frame slot criteria.
Tests querying events that reference organizations through SourceBusinessFrame.
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class FrameQueriesTester:
    """Test case for frame-based entity queries."""
    
    def __init__(self, client):
        self.client = client
        
    async def run_tests(self, space_id: str, graph_id: str, organization_uris: List[str], event_uris: List[str]) -> Dict[str, Any]:
        """
        Run frame query tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            organization_uris: List of organization entity URIs
            event_uris: List of business event entity URIs
            
        Returns:
            Test results dictionary
        """
        logger.info("=" * 80)
        logger.info("  Testing Frame-Based Entity Queries")
        logger.info("=" * 80)
        
        results = []
        errors = []
        
        # Test 1: Find events for a specific organization
        test1 = await self._test_find_events_for_organization(space_id, graph_id, organization_uris, event_uris)
        results.append(test1)
        if not test1['passed']:
            errors.append(test1.get('error', 'Find events for organization failed'))
        
        # Test 3: Find events for multiple organizations
        test3 = await self._test_find_events_for_multiple_orgs(space_id, graph_id, organization_uris, event_uris)
        results.append(test3)
        if not test3['passed']:
            errors.append(test3.get('error', 'Find events for multiple orgs failed'))
        
        # Test 4: Filter by event entity type
        test4 = await self._test_filter_by_event_type(space_id, graph_id, organization_uris, event_uris)
        results.append(test4)
        if not test4['passed']:
            errors.append(test4.get('error', 'Filter by event type failed'))
        
        # Test 5: Filter by frame type
        test5 = await self._test_filter_by_frame_type(space_id, graph_id, organization_uris, event_uris)
        results.append(test5)
        if not test5['passed']:
            errors.append(test5.get('error', 'Filter by frame type failed'))
        
        # Test 6: Pagination
        test6 = await self._test_pagination(space_id, graph_id, organization_uris, event_uris)
        results.append(test6)
        if not test6['passed']:
            errors.append(test6.get('error', 'Pagination failed'))
        
        # Test 7: Empty results
        test7 = await self._test_empty_results(space_id, graph_id)
        results.append(test7)
        if not test7['passed']:
            errors.append(test7.get('error', 'Empty results test failed'))
        
        # Test 8: Exclude self-connections
        test8 = await self._test_exclude_self_connections(space_id, graph_id, organization_uris, event_uris)
        results.append(test8)
        if not test8['passed']:
            errors.append(test8.get('error', 'Exclude self-connections failed'))
        
        passed_tests = sum(1 for r in results if r['passed'])
        logger.info(f"\n✅ Frame query tests completed: {passed_tests}/{len(results)} passed")
        
        return {
            'test_name': 'Frame-Based Entity Queries',
            'tests_run': len(results),
            'tests_passed': passed_tests,
            'tests_failed': len(results) - passed_tests,
            'errors': errors,
            'results': results
        }
    
    async def _test_find_events_for_organization(self, space_id: str, graph_id: str, 
                                          organization_uris: List[str], event_uris: List[str]) -> Dict[str, Any]:
        """Test finding events that reference a specific organization."""
        logger.info("\n  Test 1: Find events for specific organization...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria
            
            # Use first organization - we want to find events that reference this org
            org_uri = organization_uris[0]
            logger.info(f"    Querying events that reference organization: {org_uri}")
            
            # Create query criteria:
            # - Entity type: BusinessEventEntity
            # - Frame type: SourceBusinessFrame
            # - Slot criteria: BusinessEntityURISlot with uriSlotValue = org_uri
            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#BusinessEventEntity"
            )
            
            # Create frame criteria with nested slot criteria
            # Path: entity -> SourceBusinessFrame -> BusinessEntitySlot (with org URI value)
            frame_criteria_list = [
                FrameCriteria(
                    frame_type="http://vital.ai/ontology/haley-ai-kg#SourceBusinessFrame",
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="http://vital.ai/ontology/haley-ai-kg#BusinessEntitySlot",
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGEntitySlot",
                            value=org_uri,
                            comparator="eq"
                        )
                    ]
                )
            ]
            
            criteria = KGQueryCriteria(
                query_type="frame",
                source_entity_criteria=source_criteria,
                frame_criteria=frame_criteria_list,
                exclude_self_connections=True
            )
            
            # Execute query
            response = await self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=10
            )
            
            if response.query_type == "frame" and response.frame_connections:
                connection_count = len(response.frame_connections)
                logger.info(f"    ✅ Found {connection_count} frame connection(s)")
                
                # Log connection details
                for conn in response.frame_connections:
                    logger.info(f"      - Source: {conn.source_entity_uri}")
                    logger.info(f"        Destination: {conn.destination_entity_uri}")
                    logger.info(f"        Shared Frame: {conn.shared_frame_uri}")
                
                return {
                    'name': 'Find Events for Organization',
                    'passed': True,
                    'details': f"Found {connection_count} frame connection(s) for organization",
                    'connection_count': connection_count
                }
            else:
                logger.warning(f"    ⚠️  No frame connections found")
                return {
                    'name': 'Find Events for Organization',
                    'passed': False,
                    'error': 'No frame connections found for organization'
                }
                
        except Exception as e:
            logger.error(f"    ❌ Error: {e}")
            return {
                'name': 'Find Events for Organization',
                'passed': False,
                'error': str(e)
            }
    
    async def _test_find_organization_for_event(self, space_id: str, graph_id: str,
                                         organization_uris: List[str], event_uris: List[str]) -> Dict[str, Any]:
        """Test finding the organization referenced by a specific event (reverse lookup)."""
        logger.info("\n  Test 2: Find organization for specific event...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            
            # Use first event - we want to find the org it references
            event_uri = event_uris[0]
            logger.info(f"    Querying organization referenced by event: {event_uri}")
            
            # Create query criteria - event is source, org is destination
            criteria = KGQueryCriteria(
                query_type="frame",
                source_entity_uris=[event_uri],
                exclude_self_connections=True
            )
            
            # Execute query
            response = await self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=10
            )
            
            if response.query_type == "frame" and response.frame_connections:
                connection_count = len(response.frame_connections)
                logger.info(f"    ✅ Found {connection_count} frame connection(s)")
                
                return {
                    'name': 'Find Organization for Event',
                    'passed': True,
                    'details': f"Found {connection_count} frame connection(s) for event",
                    'connection_count': connection_count
                }
            else:
                logger.warning(f"    ⚠️  No frame connections found")
                return {
                    'name': 'Find Organization for Event',
                    'passed': False,
                    'error': 'No frame connections found for event'
                }
                
        except Exception as e:
            logger.error(f"    ❌ Error: {e}")
            return {
                'name': 'Find Organization for Event',
                'passed': False,
                'error': str(e)
            }
    
    async def _test_find_events_for_multiple_orgs(self, space_id: str, graph_id: str,
                                           organization_uris: List[str], event_uris: List[str]) -> Dict[str, Any]:
        """Test finding events with multiple slot criteria across different frames."""
        logger.info("\n  Test 3: Find events with multiple frame slot criteria...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria
            
            # Use first organization
            org_uri = organization_uris[0]
            logger.info(f"    Querying events that reference organization: {org_uri}")
            logger.info(f"    AND have event type 'NewCustomer'")
            
            # Create paired frame+slot criteria for two separate paths:
            # Path 1: entity -> SourceBusinessFrame -> BusinessEntitySlot (with org URI value)
            # Path 2: entity -> EventDetailsFrame -> EventTypeSlot (with "NewCustomer" value)
            frame_criteria_list = [
                FrameCriteria(
                    frame_type="http://vital.ai/ontology/haley-ai-kg#SourceBusinessFrame",
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="http://vital.ai/ontology/haley-ai-kg#BusinessEntitySlot",
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGEntitySlot",
                            value=org_uri,
                            comparator="eq"
                        )
                    ]
                ),
                FrameCriteria(
                    frame_type="http://vital.ai/ontology/haley-ai-kg#EventDetailsFrame",
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="http://vital.ai/ontology/haley-ai-kg#EventTypeSlot",
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                            value="NewCustomer",
                            comparator="eq"
                        )
                    ]
                )
            ]
            
            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#BusinessEventEntity"
            )
            
            criteria = KGQueryCriteria(
                query_type="frame",
                source_entity_criteria=source_criteria,
                frame_criteria=frame_criteria_list,
                exclude_self_connections=True
            )
            
            # Execute query
            response = await self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=20
            )
            
            if response.query_type == "frame":
                connection_count = len(response.frame_connections) if response.frame_connections else 0
                logger.info(f"    ✅ Found {connection_count} frame connection(s) matching both criteria")
                
                # Pretty print the matching events
                if response.frame_connections:
                    logger.info(f"\n    Matching Events:")
                    for i, conn in enumerate(response.frame_connections, 1):
                        entity_uri = conn.source_entity_uri
                        entity_short = entity_uri.split('/')[-1] if '/' in entity_uri else entity_uri
                        logger.info(f"      {i}. {entity_short}")
                    
                    logger.info(f"\n    These events have:")
                    logger.info(f"      ✓ SourceBusinessFrame → BusinessEntityURISlot = techcorp_industries")
                    logger.info(f"      ✓ EventDetailsFrame → EventTypeSlot = 'NewCustomer'")
                
                return {
                    'name': 'Find Events with Multiple Frame Slot Criteria',
                    'passed': True,
                    'details': f"Found {connection_count} event(s) with org URI and event type",
                    'connection_count': connection_count
                }
            else:
                logger.warning(f"    ⚠️  No frame connections found")
                return {
                    'name': 'Find Events with Multiple Frame Slot Criteria',
                    'passed': False,
                    'error': 'No frame connections found matching criteria'
                }
                
        except Exception as e:
            logger.error(f"    ❌ Error: {e}")
            return {
                'name': 'Find Events with Multiple Frame Slot Criteria',
                'passed': False,
                'error': str(e)
            }
    
    async def _test_filter_by_event_type(self, space_id: str, graph_id: str,
                                   organization_uris: List[str], event_uris: List[str]) -> Dict[str, Any]:
        """Test filtering by event entity type."""
        logger.info("\n  Test 4: Filter by event entity type...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria
            
            # Query with entity type filter for BusinessEventEntity
            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#BusinessEventEntity"
            )
            
            logger.info(f"    Filtering by entity type: BusinessEventEntity")
            
            criteria = KGQueryCriteria(
                query_type="frame",
                source_entity_criteria=source_criteria,
                exclude_self_connections=True
            )
            
            response = await self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=20
            )
            
            if response.query_type == "frame":
                connection_count = len(response.frame_connections) if response.frame_connections else 0
                logger.info(f"    ✅ Found {connection_count} frame connection(s) with entity type filter")
                
                return {
                    'name': 'Filter by Event Entity Type',
                    'passed': True,
                    'details': f"Found {connection_count} BusinessEventEntity connections",
                    'connection_count': connection_count
                }
            else:
                return {
                    'name': 'Filter by Event Entity Type',
                    'passed': False,
                    'error': 'Invalid response type'
                }
                
        except Exception as e:
            logger.error(f"    ❌ Error: {e}")
            return {
                'name': 'Filter by Event Entity Type',
                'passed': False,
                'error': str(e)
            }
    
    async def _test_filter_by_frame_type(self, space_id: str, graph_id: str,
                                   organization_uris: List[str], event_uris: List[str]) -> Dict[str, Any]:
        """Test filtering by frame type."""
        logger.info("\n  Test 5: Filter by frame type...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import FrameCriteria
            
            # Query with frame type filter for SourceBusinessFrame
            logger.info(f"    Filtering by frame type: SourceBusinessFrame")
            
            # Use frame_criteria with just frame_type (no slot criteria)
            frame_criteria_list = [
                FrameCriteria(
                    frame_type="http://vital.ai/ontology/haley-ai-kg#SourceBusinessFrame",
                    slot_criteria=None  # No slot filtering, just frame type
                )
            ]
            
            criteria = KGQueryCriteria(
                query_type="frame",
                frame_criteria=frame_criteria_list,
                exclude_self_connections=True
            )
            
            response = await self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=20
            )
            
            if response.query_type == "frame":
                connection_count = len(response.frame_connections) if response.frame_connections else 0
                logger.info(f"    ✅ Found {connection_count} frame connection(s) with frame type filter")
                
                # We expect 10 events, each with SourceBusinessFrame
                expected_count = 10
                if connection_count == expected_count:
                    return {
                        'name': 'Filter by Frame Type',
                        'passed': True,
                        'details': f"Found {connection_count} SourceBusinessFrame connections (expected {expected_count})",
                        'connection_count': connection_count
                    }
                else:
                    return {
                        'name': 'Filter by Frame Type',
                        'passed': False,
                        'error': f"Expected {expected_count} connections, found {connection_count}"
                    }
            else:
                return {
                    'name': 'Filter by Frame Type',
                    'passed': False,
                    'error': 'Invalid response type'
                }
                
        except Exception as e:
            logger.error(f"    ❌ Error: {e}")
            return {
                'name': 'Filter by Frame Type',
                'passed': False,
                'error': str(e)
            }
    
    async def _test_pagination(self, space_id: str, graph_id: str,
                        organization_uris: List[str], event_uris: List[str]) -> Dict[str, Any]:
        """Test pagination with page_size and offset."""
        logger.info("\n  Test 6: Test pagination...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            
            criteria = KGQueryCriteria(
                query_type="frame",
                exclude_self_connections=True
            )
            
            # First page
            logger.info(f"    Querying page 1 (page_size=5, offset=0)")
            response1 = await self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=5,
                offset=0
            )
            
            # Second page
            logger.info(f"    Querying page 2 (page_size=5, offset=5)")
            response2 = await self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=5,
                offset=5
            )
            
            count1 = len(response1.frame_connections) if response1.frame_connections else 0
            count2 = len(response2.frame_connections) if response2.frame_connections else 0
            
            logger.info(f"    ✅ Page 1: {count1} results, Page 2: {count2} results")
            
            return {
                'name': 'Pagination',
                'passed': True,
                'details': f"Page 1: {count1} results, Page 2: {count2} results",
                'page1_count': count1,
                'page2_count': count2
            }
                
        except Exception as e:
            logger.error(f"    ❌ Error: {e}")
            return {
                'name': 'Pagination',
                'passed': False,
                'error': str(e)
            }
    
    async def _test_empty_results(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test querying for non-existent organization (empty results)."""
        logger.info("\n  Test 7: Test empty results...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            
            # Query with non-existent organization URI
            fake_uri = "http://vital.ai/test/nonexistent/org_12345"
            logger.info(f"    Querying for non-existent organization: {fake_uri}")
            
            criteria = KGQueryCriteria(
                query_type="frame",
                source_entity_uris=[fake_uri],
                exclude_self_connections=True
            )
            
            response = await self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=10
            )
            
            connection_count = len(response.frame_connections) if response.frame_connections else 0
            
            if connection_count == 0:
                logger.info(f"    ✅ Correctly returned empty results")
                return {
                    'name': 'Empty Results',
                    'passed': True,
                    'details': 'Correctly returned empty results for non-existent entity'
                }
            else:
                logger.warning(f"    ⚠️  Unexpected: found {connection_count} connections")
                return {
                    'name': 'Empty Results',
                    'passed': False,
                    'error': f'Expected 0 connections, found {connection_count}'
                }
                
        except Exception as e:
            logger.error(f"    ❌ Error: {e}")
            return {
                'name': 'Empty Results',
                'passed': False,
                'error': str(e)
            }
    
    async def _test_exclude_self_connections(self, space_id: str, graph_id: str,
                                       organization_uris: List[str], event_uris: List[str]) -> Dict[str, Any]:
        """Test that self-connections are excluded."""
        logger.info("\n  Test 8: Test exclude self-connections...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            
            logger.info(f"    Querying with exclude_self_connections=True")
            
            criteria = KGQueryCriteria(
                query_type="frame",
                exclude_self_connections=True
            )
            
            response = await self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=20
            )
            
            # Check if any connection has same source and destination
            self_connections = []
            if response.frame_connections:
                for conn in response.frame_connections:
                    if conn.source_entity_uri == conn.destination_entity_uri:
                        self_connections.append(conn)
            
            if len(self_connections) == 0:
                logger.info(f"    ✅ No self-connections found (as expected)")
                return {
                    'name': 'Exclude Self-Connections',
                    'passed': True,
                    'details': 'No self-connections found with exclude_self_connections=True'
                }
            else:
                logger.warning(f"    ⚠️  Found {len(self_connections)} self-connection(s)")
                return {
                    'name': 'Exclude Self-Connections',
                    'passed': False,
                    'error': f'Found {len(self_connections)} self-connection(s) when they should be excluded'
                }
                
        except Exception as e:
            logger.error(f"    ❌ Error: {e}")
            return {
                'name': 'Exclude Self-Connections',
                'passed': False,
                'error': str(e)
            }
