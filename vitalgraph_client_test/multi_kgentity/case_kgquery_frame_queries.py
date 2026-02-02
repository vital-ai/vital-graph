#!/usr/bin/env python3
"""
KGQuery Frame Queries Test Case

Test case for querying entities using frame-based criteria.
Tests multi-frame slot criteria queries on business events and organizations.
"""

import logging
import time
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class KGQueryFrameQueriesTester:
    """Test case for KGQuery frame-based entity queries."""
    
    def __init__(self, client):
        self.client = client
        
    def run_tests(self, space_id: str, graph_id: str, organization_uris: List[str], 
                  event_uris: List[str], file_uris: Dict[str, str] = None) -> Dict[str, Any]:
        """
        Run KGQuery frame query tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            organization_uris: List of organization entity URIs
            event_uris: List of business event entity URIs
            file_uris: Optional dictionary of file URIs for file reference queries
            
        Returns:
            Test results dictionary
        """
        logger.info("=" * 80)
        logger.info("  Testing KGQuery Frame-Based Queries")
        logger.info("=" * 80)
        
        results = []
        errors = []
        
        # Test 1: Find events for a specific organization
        test1 = self._test_find_events_for_organization(space_id, graph_id, organization_uris)
        results.append(test1)
        if not test1['passed']:
            errors.append(test1.get('error', 'Find events for organization failed'))
        
        # Test 2: Find events with multiple frame slot criteria
        test2 = self._test_multi_frame_query(space_id, graph_id, organization_uris)
        results.append(test2)
        if not test2['passed']:
            errors.append(test2.get('error', 'Multi-frame query failed'))
        
        # Test 3: Filter by entity type
        test3 = self._test_filter_by_entity_type(space_id, graph_id)
        results.append(test3)
        if not test3['passed']:
            errors.append(test3.get('error', 'Entity type filter failed'))
        
        # Test 4: Filter by frame type
        test4 = self._test_filter_by_frame_type(space_id, graph_id)
        results.append(test4)
        if not test4['passed']:
            errors.append(test4.get('error', 'Frame type filter failed'))
        
        # File reference tests (if file_uris provided)
        if file_uris:
            # Test 5: Find organizations with contract documents
            test5 = self._test_find_orgs_with_contracts(space_id, graph_id)
            results.append(test5)
            if not test5['passed']:
                errors.append(test5.get('error', 'Find orgs with contracts failed'))
            
            # Test 6: Find organizations with specific file URI
            test6 = self._test_find_orgs_with_file_uri(space_id, graph_id, file_uris)
            results.append(test6)
            if not test6['passed']:
                errors.append(test6.get('error', 'Find orgs with file URI failed'))
        
        passed_tests = sum(1 for r in results if r['passed'])
        
        # Aggregate timing data
        total_time = sum(r.get('elapsed_time', 0) for r in results)
        avg_time = total_time / len(results) if results else 0
        min_time = min((r.get('elapsed_time', 0) for r in results), default=0)
        max_time = max((r.get('elapsed_time', 0) for r in results), default=0)
        
        logger.info(f"\n✅ KGQuery tests completed: {passed_tests}/{len(results)} passed")
        logger.info(f"⏱️  Query Performance:")
        logger.info(f"   Total time: {total_time:.3f}s")
        logger.info(f"   Average:    {avg_time:.3f}s")
        logger.info(f"   Min:        {min_time:.3f}s")
        logger.info(f"   Max:        {max_time:.3f}s")
        
        return {
            'test_name': 'KGQuery Frame-Based Queries',
            'tests_run': len(results),
            'tests_passed': passed_tests,
            'tests_failed': len(results) - passed_tests,
            'errors': errors,
            'results': results,
            'timing': {
                'total_time': total_time,
                'avg_time': avg_time,
                'min_time': min_time,
                'max_time': max_time
            }
        }
    
    def _test_find_events_for_organization(self, space_id: str, graph_id: str, 
                                          organization_uris: List[str]) -> Dict[str, Any]:
        """Test finding events that reference a specific organization."""
        logger.info("\n  Test 1: Find events for specific organization...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria
            
            # Use first organization
            org_uri = organization_uris[0]
            org_short = org_uri.split('/')[-1] if '/' in org_uri else org_uri
            logger.info(f"    Querying events that reference: {org_short}")
            
            # Create query: entity -> SourceBusinessFrame -> BusinessEntityURISlot (with org URI)
            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#BusinessEventEntity"
            )
            
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
                query_mode="direct",  # Use materialized properties (vg-direct:hasEntityFrame)
                source_entity_criteria=source_criteria,
                frame_criteria=frame_criteria_list,
                exclude_self_connections=True
            )
            
            start_time = time.time()
            response = self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=10
            )
            elapsed = time.time() - start_time
            
            logger.info(f"    ⏱️  KGQuery execution time: {elapsed:.3f}s")
            
            if response.query_type == "frame" and response.frame_connections:
                result_count = len(response.frame_connections)
                logger.info(f"    ✅ Found {result_count} event(s) referencing organization")
                
                return {
                    'name': 'Find Events for Organization',
                    'passed': True,
                    'details': f"Found {result_count} events",
                    'result_count': result_count,
                    'elapsed_time': elapsed
                }
            else:
                logger.warning(f"    ⚠️  No events found")
                return {
                    'name': 'Find Events for Organization',
                    'passed': False,
                    'error': 'No events found for organization',
                    'elapsed_time': elapsed
                }
                
        except Exception as e:
            logger.error(f"    ❌ Error: {e}")
            return {
                'name': 'Find Events for Organization',
                'passed': False,
                'error': str(e),
                'elapsed_time': 0
            }
    
    def _test_multi_frame_query(self, space_id: str, graph_id: str,
                                organization_uris: List[str]) -> Dict[str, Any]:
        """Test finding events with multiple slot criteria across different frames."""
        logger.info("\n  Test 2: Multi-frame query (org URI + event type)...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria
            
            org_uri = organization_uris[0]
            org_short = org_uri.split('/')[-1] if '/' in org_uri else org_uri
            logger.info(f"    Querying events that reference: {org_short}")
            logger.info(f"    AND have event type 'NewCustomer'")
            
            # Two separate paths:
            # Path 1: entity -> SourceBusinessFrame -> BusinessEntityURISlot
            # Path 2: entity -> EventDetailsFrame -> EventTypeSlot
            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#BusinessEventEntity"
            )
            
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
            
            criteria = KGQueryCriteria(
                query_type="frame",
                query_mode="direct",  # Use materialized properties
                source_entity_criteria=source_criteria,
                frame_criteria=frame_criteria_list,
                exclude_self_connections=True
            )
            
            start_time = time.time()
            response = self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=20
            )
            elapsed = time.time() - start_time
            
            logger.info(f"    ⏱️  KGQuery execution time: {elapsed:.3f}s")
            
            if response.query_type == "frame":
                result_count = len(response.frame_connections) if response.frame_connections else 0
                logger.info(f"    ✅ Found {result_count} event(s) matching BOTH criteria")
                
                # Pretty print matching events
                if response.frame_connections:
                    logger.info(f"\n    Matching Events:")
                    for i, conn in enumerate(response.frame_connections, 1):
                        entity_uri = conn.source_entity_uri
                        entity_short = entity_uri.split('/')[-1] if '/' in entity_uri else entity_uri
                        logger.info(f"      {i}. {entity_short}")
                    
                    logger.info(f"\n    These events have:")
                    logger.info(f"      ✓ SourceBusinessFrame → BusinessEntityURISlot = org")
                    logger.info(f"      ✓ EventDetailsFrame → EventTypeSlot = 'NewCustomer'")
                
                return {
                    'name': 'Multi-Frame Query',
                    'passed': True,
                    'details': f"Found {result_count} events matching both criteria",
                    'result_count': result_count,
                    'elapsed_time': elapsed
                }
            else:
                logger.error(f"    ❌ Query failed or wrong type")
                return {
                    'name': 'Multi-Frame Query',
                    'passed': False,
                    'error': 'Query failed or returned wrong type',
                    'elapsed_time': elapsed
                }
                
        except Exception as e:
            logger.error(f"    ❌ Error: {e}")
            return {
                'name': 'Multi-Frame Query',
                'passed': False,
                'error': str(e),
                'elapsed_time': 0
            }
    
    def _test_filter_by_entity_type(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test filtering by entity type."""
        logger.info("\n  Test 3: Filter by entity type...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria
            
            logger.info(f"    Filtering by entity type: BusinessEventEntity")
            
            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#BusinessEventEntity"
            )
            
            criteria = KGQueryCriteria(
                query_type="frame",
                query_mode="direct",  # Use materialized properties
                source_entity_criteria=source_criteria,
                exclude_self_connections=True
            )
            
            start_time = time.time()
            response = self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=20
            )
            elapsed = time.time() - start_time
            
            logger.info(f"    ⏱️  KGQuery execution time: {elapsed:.3f}s")
            
            if response.query_type == "frame":
                result_count = len(response.frame_connections) if response.frame_connections else 0
                logger.info(f"    ✅ Found {result_count} result(s) with entity type filter")
                
                return {
                    'name': 'Filter by Entity Type',
                    'passed': True,
                    'details': f"Found {result_count} BusinessEventEntity results",
                    'result_count': result_count,
                    'elapsed_time': elapsed
                }
            else:
                logger.error(f"    ❌ Query failed or wrong type")
                return {
                    'name': 'Filter by Entity Type',
                    'passed': False,
                    'error': 'Query failed or returned wrong type',
                    'elapsed_time': elapsed
                }
                
        except Exception as e:
            logger.error(f"    ❌ Error: {e}")
            return {
                'name': 'Filter by Entity Type',
                'passed': False,
                'error': str(e),
                'elapsed_time': 0
            }
    
    def _test_filter_by_frame_type(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test filtering by frame type."""
        logger.info("\n  Test 4: Filter by frame type...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import FrameCriteria
            
            logger.info(f"    Filtering by frame type: SourceBusinessFrame")
            
            frame_criteria_list = [
                FrameCriteria(
                    frame_type="http://vital.ai/ontology/haley-ai-kg#SourceBusinessFrame",
                    slot_criteria=None  # No slot filtering, just frame type
                )
            ]
            
            criteria = KGQueryCriteria(
                query_type="frame",
                query_mode="direct",  # Use materialized properties
                frame_criteria=frame_criteria_list,
                exclude_self_connections=True
            )
            
            start_time = time.time()
            response = self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=20
            )
            elapsed = time.time() - start_time
            
            logger.info(f"    ⏱️  KGQuery execution time: {elapsed:.3f}s")
            
            if response.query_type == "frame":
                result_count = len(response.frame_connections) if response.frame_connections else 0
                logger.info(f"    ✅ Found {result_count} result(s) with frame type filter")
                
                # We expect 10 events, each with SourceBusinessFrame
                expected_count = 10
                if result_count == expected_count:
                    return {
                        'name': 'Filter by Frame Type',
                        'passed': True,
                        'details': f"Found {result_count} SourceBusinessFrame results (expected {expected_count})",
                        'result_count': result_count,
                        'elapsed_time': elapsed
                    }
                else:
                    return {
                        'name': 'Filter by Frame Type',
                        'passed': False,
                        'error': f"Expected {expected_count} results, found {result_count}",
                        'elapsed_time': elapsed
                    }
            else:
                logger.error(f"    ❌ Query failed or wrong type")
                return {
                    'name': 'Filter by Frame Type',
                    'passed': False,
                    'error': 'Query failed or returned wrong type',
                    'elapsed_time': elapsed
                }
                
        except Exception as e:
            logger.error(f"    ❌ Error: {e}")
            return {
                'name': 'Filter by Frame Type',
                'passed': False,
                'error': str(e),
                'elapsed_time': 0
            }
    
    def _test_find_orgs_with_contracts(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test finding organizations with contract documents."""
        logger.info("\n  Test 5: Find organizations with contract documents...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria
            
            logger.info(f"    Querying organizations with BusinessContractFrame")
            
            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#OrganizationEntity"
            )
            
            frame_criteria_list = [
                FrameCriteria(
                    frame_type="http://vital.ai/test/kgtype/BusinessContractFrame",
                    slot_criteria=None  # Just check for frame existence
                )
            ]
            
            criteria = KGQueryCriteria(
                query_type="frame",
                query_mode="direct",  # Use materialized properties
                source_entity_criteria=source_criteria,
                frame_criteria=frame_criteria_list,
                exclude_self_connections=True
            )
            
            start_time = time.time()
            response = self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=20
            )
            elapsed = time.time() - start_time
            
            logger.info(f"    ⏱️  KGQuery execution time: {elapsed:.3f}s")
            
            if response.query_type == "frame":
                result_count = len(response.frame_connections) if response.frame_connections else 0
                logger.info(f"    ✅ Found {result_count} organization(s) with contracts")
                
                return {
                    'name': 'Find Orgs with Contracts',
                    'passed': True,
                    'details': f"Found {result_count} orgs with contracts",
                    'result_count': result_count,
                    'elapsed_time': elapsed
                }
            else:
                logger.error(f"    ❌ Query failed or wrong type")
                return {
                    'name': 'Find Organizations with Contracts',
                    'passed': False,
                    'error': 'Query failed or returned wrong type',
                    'elapsed_time': elapsed
                }
                
        except Exception as e:
            logger.error(f"    ❌ Error: {e}")
            return {
                'name': 'Find Orgs with Contracts',
                'passed': False,
                'error': str(e),
                'elapsed_time': 0
            }
    
    def _test_find_orgs_with_file_uri(self, space_id: str, graph_id: str, 
                                      file_uris: Dict[str, str]) -> Dict[str, Any]:
        """Test finding organizations with a specific file URI."""
        logger.info("\n  Test 6: Find organizations with specific file URI...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria
            
            # Use first contract file
            file_uri = file_uris.get("contract_1")
            if not file_uri:
                return {
                    'name': 'Find Organizations with File URI',
                    'passed': False,
                    'error': 'No contract_1 file URI available',
                    'elapsed_time': 0
                }
            
            logger.info(f"    Querying organizations with file: {file_uri}")
            
            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#OrganizationEntity"
            )
            
            frame_criteria_list = [
                FrameCriteria(
                    frame_type="http://vital.ai/test/kgtype/BusinessContractFrame",
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="http://vital.ai/test/kgtype/DocumentFileURISlot",
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGURISlot",
                            value=file_uri,
                            comparator="eq"
                        )
                    ]
                )
            ]
            
            criteria = KGQueryCriteria(
                query_type="frame",
                query_mode="direct",  # Use materialized properties
                source_entity_criteria=source_criteria,
                frame_criteria=frame_criteria_list,
                exclude_self_connections=True
            )
            
            start_time = time.time()
            response = self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=20
            )
            elapsed = time.time() - start_time
            
            logger.info(f"    ⏱️  KGQuery execution time: {elapsed:.3f}s")
            
            if response.query_type == "frame":
                result_count = len(response.frame_connections) if response.frame_connections else 0
                logger.info(f"    ✅ Found {result_count} organization(s) with this file")
                
                return {
                    'name': 'Find Orgs with File URI',
                    'passed': True,
                    'details': f"Found {result_count} orgs with file {file_uri}",
                    'result_count': result_count,
                    'elapsed_time': elapsed
                }
            else:
                logger.error(f"    ❌ Query failed or wrong type")
                return {
                    'name': 'Find Organizations with File URI',
                    'passed': False,
                    'error': 'Query failed or returned wrong type',
                    'elapsed_time': elapsed
                }
                
        except Exception as e:
            logger.error(f"    ❌ Error: {e}")
            return {
                'name': 'Find Orgs with File URI',
                'passed': False,
                'error': str(e),
                'elapsed_time': 0
            }
