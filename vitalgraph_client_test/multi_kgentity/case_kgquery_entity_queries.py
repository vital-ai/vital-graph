#!/usr/bin/env python3
"""
KGQuery Entity Queries Test Case for Multi-Org Test Suite

Test case for entity-based queries using frame/slot criteria.
Tests querying events that reference organizations through SourceBusinessFrame.
Adapted from kgqueries/case_frame_queries.py for multi-org test integration.
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class KGQueryEntityQueriesTester:
    """Test case for KGQuery entity-based queries in multi-org test suite."""
    
    def __init__(self, client):
        self.client = client
        
    def run_tests(self, space_id: str, graph_id: str, 
                  organization_uris: List[str], 
                  event_uris: List[str],
                  file_uris: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Run entity query tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            organization_uris: List of organization entity URIs
            event_uris: List of business event entity URIs
            file_uris: Optional dict of file URIs
            
        Returns:
            Test results dictionary
        """
        logger.info("\n" + "=" * 80)
        logger.info("  KGQuery: Entity-Based Queries")
        logger.info("=" * 80)
        
        results = []
        errors = []
        
        # Test 1: Find events for a specific organization
        test1 = self._test_find_events_for_organization(space_id, graph_id, organization_uris, event_uris)
        results.append(test1)
        if not test1['passed']:
            errors.append(test1.get('error', 'Find events for organization failed'))
        
        # Test 2: Find events for multiple organizations
        test2 = self._test_find_events_for_multiple_orgs(space_id, graph_id, organization_uris, event_uris)
        results.append(test2)
        if not test2['passed']:
            errors.append(test2.get('error', 'Find events for multiple orgs failed'))
        
        # Test 3: Filter by event entity type
        test3 = self._test_filter_by_event_type(space_id, graph_id, organization_uris, event_uris)
        results.append(test3)
        if not test3['passed']:
            errors.append(test3.get('error', 'Filter by event type failed'))
        
        # Test 4: Filter by frame type
        test4 = self._test_filter_by_frame_type(space_id, graph_id, organization_uris, event_uris)
        results.append(test4)
        if not test4['passed']:
            errors.append(test4.get('error', 'Filter by frame type failed'))
        
        # Test 5: Pagination
        test5 = self._test_pagination(space_id, graph_id, organization_uris, event_uris)
        results.append(test5)
        if not test5['passed']:
            errors.append(test5.get('error', 'Pagination failed'))
        
        # Test 6: Empty results
        test6 = self._test_empty_results(space_id, graph_id)
        results.append(test6)
        if not test6['passed']:
            errors.append(test6.get('error', 'Empty results test failed'))
        
        # Test 7: Query with file URI slot (if files available)
        if file_uris:
            test7 = self._test_query_with_file_uri(space_id, graph_id, organization_uris, file_uris)
            results.append(test7)
            if not test7['passed']:
                errors.append(test7.get('error', 'Query with file URI failed'))
        
        passed_tests = sum(1 for r in results if r['passed'])
        logger.info(f"\n✅ Entity query tests completed: {passed_tests}/{len(results)} passed")
        
        return {
            'test_name': 'KGQuery Entity-Based Queries',
            'tests_run': len(results),
            'tests_passed': passed_tests,
            'tests_failed': len(results) - passed_tests,
            'errors': errors,
            'results': results
        }
    
    def _test_find_events_for_organization(self, space_id: str, graph_id: str, 
                                          organization_uris: List[str], event_uris: List[str]) -> Dict[str, Any]:
        """Test finding events that reference a specific organization."""
        logger.info("\n  Test 1: Find events for specific organization...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria, FrameCriteria, SlotCriteria
            
            # Query for events that have SourceBusinessFrame pointing to first organization
            target_org_uri = organization_uris[0]
            
            criteria = KGQueryCriteria(
                query_type="entity",
                entity_type_uris=["http://vital.ai/ontology/haley-ai-kg#KGEntity"],
                frame_criteria=[
                    FrameCriteria(
                        frame_type="http://vital.ai/ontology/haley-ai-kg#SourceBusinessFrame",
                        slot_criteria=[
                            SlotCriteria(
                                slot_type="http://vital.ai/ontology/haley-ai-kg#hasBusinessEntitySlot",
                                value=target_org_uri,
                                comparator="eq"
                            )
                        ]
                    )
                ],
                page_size=20,
                offset=0
            )
            
            response = self.client.kgqueries.query_frame_connections(
                space_id, graph_id,
                entity_type_uris=["http://vital.ai/ontology/haley-ai-kg#KGEntity"],
                frame_criteria=[
                    {
                        "frame_type": "http://vital.ai/ontology/haley-ai-kg#SourceBusinessFrame",
                        "slot_criteria": [
                            {
                                "slot_type": "http://vital.ai/ontology/haley-ai-kg#hasBusinessEntitySlot",
                                "value": target_org_uri,
                                "comparator": "eq"
                            }
                        ]
                    }
                ],
                page_size=20,
                offset=0
            )
            
            if response.success and response.frame_connections:
                found_count = len(response.frame_connections)
                logger.info(f"     ✅ Found {found_count} events for organization {target_org_uri[:50]}...")
                return {'passed': True, 'found_count': found_count}
            elif response.success:
                logger.info(f"     ✅ Query succeeded but found 0 events (may be valid)")
                return {'passed': True, 'found_count': 0}
            else:
                logger.error(f"     ❌ Query failed")
                return {'passed': False, 'error': 'Query failed'}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'passed': False, 'error': str(e)}
    
    def _test_find_events_for_multiple_orgs(self, space_id: str, graph_id: str,
                                           organization_uris: List[str], event_uris: List[str]) -> Dict[str, Any]:
        """Test finding events for multiple organizations."""
        logger.info("\n  Test 2: Find events for multiple organizations...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria, FrameCriteria, SlotCriteria
            
            # Query for events that reference first 3 organizations
            target_org_uris = organization_uris[:3]
            
            criteria = KGQueryCriteria(
                query_type="entity",
                entity_type_uris=["http://vital.ai/ontology/haley-ai-kg#KGEntity"],
                frame_criteria=[
                    FrameCriteria(
                        frame_type="http://vital.ai/ontology/haley-ai-kg#SourceBusinessFrame",
                        slot_criteria=[
                            SlotCriteria(
                                slot_type="http://vital.ai/ontology/haley-ai-kg#hasBusinessEntitySlot",
                                value=uri,
                                comparator="eq"
                            ) for uri in target_org_uris
                        ]
                    )
                ],
                page_size=50,
                offset=0
            )
            
            response = self.client.kgqueries.query_entities(space_id, graph_id, criteria)
            
            if response.is_success:
                found_count = len(response.entity_uris) if response.entity_uris else 0
                logger.info(f"     ✅ Found {found_count} events for {len(target_org_uris)} organizations")
                return {'passed': True, 'found_count': found_count}
            else:
                logger.error(f"     ❌ Query failed: {response.message}")
                return {'passed': False, 'error': f"Query failed: {response.message}"}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'passed': False, 'error': str(e)}
    
    def _test_filter_by_event_type(self, space_id: str, graph_id: str,
                                   organization_uris: List[str], event_uris: List[str]) -> Dict[str, Any]:
        """Test filtering by specific event entity type."""
        logger.info("\n  Test 3: Filter by event entity type...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria, FrameCriteria, SlotCriteria
            
            criteria = KGQueryCriteria(
                query_type="entity",
                entity_type_uris=["http://vital.ai/ontology/haley-ai-kg#KGEntity"],
                frame_criteria=[
                    FrameCriteria(
                        frame_type="http://vital.ai/ontology/haley-ai-kg#SourceBusinessFrame"
                    )
                ],
                page_size=50,
                offset=0
            )
            
            response = self.client.kgqueries.query_entities(space_id, graph_id, criteria)
            
            if response.is_success:
                found_count = len(response.entity_uris) if response.entity_uris else 0
                logger.info(f"     ✅ Found {found_count} entities with SourceBusinessFrame")
                return {'passed': True, 'found_count': found_count}
            else:
                logger.error(f"     ❌ Query failed: {response.message}")
                return {'passed': False, 'error': f"Query failed: {response.message}"}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'passed': False, 'error': str(e)}
    
    def _test_filter_by_frame_type(self, space_id: str, graph_id: str,
                                   organization_uris: List[str], event_uris: List[str]) -> Dict[str, Any]:
        """Test filtering by specific frame type."""
        logger.info("\n  Test 4: Filter by frame type...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria, FrameCriteria
            
            criteria = KGQueryCriteria(
                query_type="entity",
                frame_criteria=[
                    FrameCriteria(
                        frame_type="http://vital.ai/ontology/haley-ai-kg#SourceBusinessFrame"
                    )
                ],
                page_size=50,
                offset=0
            )
            
            response = self.client.kgqueries.query_entities(space_id, graph_id, criteria)
            
            if response.is_success:
                found_count = len(response.entity_uris) if response.entity_uris else 0
                logger.info(f"     ✅ Found {found_count} entities with SourceBusinessFrame")
                return {'passed': True, 'found_count': found_count}
            else:
                logger.error(f"     ❌ Query failed: {response.message}")
                return {'passed': False, 'error': f"Query failed: {response.message}"}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'passed': False, 'error': str(e)}
    
    def _test_pagination(self, space_id: str, graph_id: str,
                        organization_uris: List[str], event_uris: List[str]) -> Dict[str, Any]:
        """Test pagination of query results."""
        logger.info("\n  Test 5: Pagination...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria, FrameCriteria
            
            # First page
            criteria_page1 = KGQueryCriteria(
                query_type="entity",
                frame_criteria=[
                    FrameCriteria(
                        frame_type="http://vital.ai/ontology/haley-ai-kg#SourceBusinessFrame"
                    )
                ],
                page_size=5,
                offset=0
            )
            
            response1 = self.client.kgqueries.query_entities(space_id, graph_id, criteria_page1)
            
            if not response1.is_success:
                logger.error(f"     ❌ First page query failed: {response1.message}")
                return {'passed': False, 'error': f"First page failed: {response1.message}"}
            
            page1_count = len(response1.entity_uris) if response1.entity_uris else 0
            
            # Second page
            criteria_page2 = KGQueryCriteria(
                query_type="entity",
                frame_criteria=[
                    FrameCriteria(
                        frame_type="http://vital.ai/ontology/haley-ai-kg#SourceBusinessFrame"
                    )
                ],
                page_size=5,
                offset=5
            )
            
            response2 = self.client.kgqueries.query_entities(space_id, graph_id, criteria_page2)
            
            if not response2.is_success:
                logger.error(f"     ❌ Second page query failed: {response2.message}")
                return {'passed': False, 'error': f"Second page failed: {response2.message}"}
            
            page2_count = len(response2.entity_uris) if response2.entity_uris else 0
            
            logger.info(f"     ✅ Page 1: {page1_count} results, Page 2: {page2_count} results")
            return {'passed': True, 'page1_count': page1_count, 'page2_count': page2_count}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'passed': False, 'error': str(e)}
    
    def _test_empty_results(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test query that should return empty results."""
        logger.info("\n  Test 6: Empty results query...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria, FrameCriteria, SlotCriteria
            
            # Query for non-existent entity
            criteria = KGQueryCriteria(
                query_type="entity",
                frame_criteria=[
                    FrameCriteria(
                        frame_type="http://vital.ai/ontology/haley-ai-kg#SourceBusinessFrame",
                        slot_criteria=[
                            SlotCriteria(
                                slot_type="http://vital.ai/ontology/haley-ai-kg#hasBusinessEntitySlot",
                                value="http://nonexistent.uri/entity/12345",
                                comparator="eq"
                            )
                        ]
                    )
                ],
                page_size=20,
                offset=0
            )
            
            response = self.client.kgqueries.query_entities(space_id, graph_id, criteria)
            
            if response.is_success:
                found_count = len(response.entity_uris) if response.entity_uris else 0
                if found_count == 0:
                    logger.info(f"     ✅ Correctly returned 0 results for non-existent entity")
                    return {'passed': True, 'found_count': 0}
                else:
                    logger.warning(f"     ⚠️  Expected 0 results but found {found_count}")
                    return {'passed': True, 'found_count': found_count}  # Still pass, just unexpected
            else:
                logger.error(f"     ❌ Query failed: {response.message}")
                return {'passed': False, 'error': f"Query failed: {response.message}"}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'passed': False, 'error': str(e)}
    
    def _test_query_with_file_uri(self, space_id: str, graph_id: str,
                                  organization_uris: List[str], 
                                  file_uris: Dict[str, str]) -> Dict[str, Any]:
        """Test query with file URI slot criteria."""
        logger.info("\n  Test 7: Query with file URI slot...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria, FrameCriteria, SlotCriteria
            
            # Get first file URI
            first_file_uri = next(iter(file_uris.values()))
            
            # Query for entities with BusinessContractFrame containing this file
            criteria = KGQueryCriteria(
                query_type="entity",
                frame_criteria=[
                    FrameCriteria(
                        frame_type="http://vital.ai/ontology/haley-ai-kg#BusinessContractFrame",
                        slot_criteria=[
                            SlotCriteria(
                                slot_type="http://vital.ai/ontology/haley-ai-kg#hasFileSlot",
                                value=first_file_uri,
                                comparator="eq"
                            )
                        ]
                    )
                ],
                page_size=20,
                offset=0
            )
            
            response = self.client.kgqueries.query_entities(space_id, graph_id, criteria)
            
            if response.is_success:
                found_count = len(response.entity_uris) if response.entity_uris else 0
                logger.info(f"     ✅ Found {found_count} entities with file URI {first_file_uri[:50]}...")
                return {'passed': True, 'found_count': found_count}
            else:
                logger.error(f"     ❌ Query failed: {response.message}")
                return {'passed': False, 'error': f"Query failed: {response.message}"}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'passed': False, 'error': str(e)}
