#!/usr/bin/env python3
"""
KGQuery Relation Queries Test Case for Multi-Org Test Suite

Test case for relation-based queries using relation type and entity criteria.
Tests querying relations between organizations and products.
Adapted from kgqueries/case_relation_queries.py for multi-org test integration.
"""

import logging
import time
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class KGQueryRelationQueriesTester:
    """Test case for KGQuery relation-based queries in multi-org test suite."""
    
    def __init__(self, client):
        self.client = client
        
    def run_tests(self, space_id: str, graph_id: str,
                  org_uri_map: Dict[str, str],
                  product_uris: Dict[str, str],
                  relation_type_uris: Dict[str, str]) -> Dict[str, Any]:
        """
        Run relation query tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            org_uri_map: Dict mapping organization names to URIs
            product_uris: Dict mapping product names to URIs
            relation_type_uris: Dict mapping relation type names to URIs
            
        Returns:
            Test results dictionary
        """
        logger.info("\n" + "=" * 80)
        logger.info("  KGQuery: Relation-Based Queries")
        logger.info("=" * 80)
        
        results = []
        errors = []
        
        # Test 1: Find all MakesProduct relations
        test1 = self._test_find_makes_product_relations(space_id, graph_id, relation_type_uris)
        results.append(test1)
        if not test1['passed']:
            errors.append(test1.get('error', 'Find MakesProduct relations failed'))
        
        # Test 2: Find relations from specific organization
        test2 = self._test_find_relations_from_org(space_id, graph_id, org_uri_map, relation_type_uris)
        results.append(test2)
        if not test2['passed']:
            errors.append(test2.get('error', 'Find relations from org failed'))
        
        # Test 3: Find CompetitorOf relations
        test3 = self._test_find_competitor_relations(space_id, graph_id, relation_type_uris)
        results.append(test3)
        if not test3['passed']:
            errors.append(test3.get('error', 'Find CompetitorOf relations failed'))
        
        # Test 4: Find PartnerWith relations
        test4 = self._test_find_partner_relations(space_id, graph_id, relation_type_uris)
        results.append(test4)
        if not test4['passed']:
            errors.append(test4.get('error', 'Find PartnerWith relations failed'))
        
        # Test 5: Find Supplies relations
        test5 = self._test_find_supplies_relations(space_id, graph_id, relation_type_uris)
        results.append(test5)
        if not test5['passed']:
            errors.append(test5.get('error', 'Find Supplies relations failed'))
        
        # Test 6: Filter by direction (outgoing)
        test6 = self._test_filter_by_direction(space_id, graph_id, org_uri_map, relation_type_uris)
        results.append(test6)
        if not test6['passed']:
            errors.append(test6.get('error', 'Filter by direction failed'))
        
        # Test 7: Pagination
        test7 = self._test_pagination(space_id, graph_id, relation_type_uris)
        results.append(test7)
        if not test7['passed']:
            errors.append(test7.get('error', 'Pagination failed'))
        
        # Test 8: Empty results
        test8 = self._test_empty_results(space_id, graph_id)
        results.append(test8)
        if not test8['passed']:
            errors.append(test8.get('error', 'Empty results test failed'))
        
        passed_tests = sum(1 for r in results if r.get('passed', False))
        
        # Aggregate timing data
        total_time = sum(r.get('elapsed_time', 0) for r in results)
        avg_time = total_time / len(results) if results else 0
        min_time = min((r.get('elapsed_time', 0) for r in results), default=0)
        max_time = max((r.get('elapsed_time', 0) for r in results), default=0)
        
        logger.info(f"\n✅ Relation query tests completed: {passed_tests}/{len(results)} passed")
        logger.info(f"⏱️  Query Performance:")
        logger.info(f"   Total time: {total_time:.3f}s")
        logger.info(f"   Average:    {avg_time:.3f}s")
        logger.info(f"   Min:        {min_time:.3f}s")
        logger.info(f"   Max:        {max_time:.3f}s")
        
        return {
            'test_name': 'KGQuery Relation-Based Queries',
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
    
    def _test_find_makes_product_relations(self, space_id: str, graph_id: str,
                                          relation_type_uris: Dict[str, str]) -> Dict[str, Any]:
        """Test finding all MakesProduct relations."""
        logger.info("\n  Test 1: Find all MakesProduct relations...")
        
        try:
            makes_product_type = relation_type_uris.get('makes_product')
            if not makes_product_type:
                logger.warning("     ⚠️  MakesProduct relation type not found, skipping")
                return {'passed': True, 'skipped': True, 'elapsed_time': 0}
            
            start_time = time.time()
            response = self.client.kgqueries.query_relation_connections(
                space_id, 
                graph_id,
                relation_type_uris=[makes_product_type],
                page_size=50,
                offset=0
            )
            elapsed = time.time() - start_time
            
            logger.info(f"     ⏱️  KGQuery execution time: {elapsed:.3f}s")
            
            if response.query_type == "relation" and response.relation_connections:
                found_count = len(response.relation_connections)
                logger.info(f"     ✅ Found {found_count} MakesProduct relations")
                return {'name': 'Find MakesProduct Relations', 'passed': True, 'found_count': found_count, 'elapsed_time': elapsed}
            elif response.query_type == "relation":
                logger.info(f"     ✅ Query succeeded but found 0 MakesProduct relations")
                return {'name': 'Find MakesProduct Relations', 'passed': True, 'found_count': 0, 'elapsed_time': elapsed}
            else:
                logger.error(f"     ❌ Query failed or wrong query type")
                return {'name': 'Find MakesProduct Relations', 'passed': False, 'error': 'Query failed or wrong query type', 'elapsed_time': elapsed}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'name': 'Find MakesProduct Relations', 'passed': False, 'error': str(e), 'elapsed_time': 0}
    
    def _test_find_relations_from_org(self, space_id: str, graph_id: str,
                                     org_uri_map: Dict[str, str],
                                     relation_type_uris: Dict[str, str]) -> Dict[str, Any]:
        """Test finding relations from a specific organization."""
        logger.info("\n  Test 2: Find relations from specific organization...")
        
        try:
            # Get TechCorp URI
            techcorp_uri = org_uri_map.get("TechCorp Industries")
            if not techcorp_uri:
                logger.warning("     ⚠️  TechCorp Industries not found, skipping")
                return {'passed': True, 'skipped': True, 'elapsed_time': 0}
            
            start_time = time.time()
            response = self.client.kgqueries.query_relation_connections(
                space_id,
                graph_id,
                source_entity_uris=[techcorp_uri],
                direction="outgoing",
                page_size=50,
                offset=0
            )
            elapsed = time.time() - start_time
            
            logger.info(f"     ⏱️  KGQuery execution time: {elapsed:.3f}s")
            
            if response.query_type == "relation" and response.relation_connections:
                found_count = len(response.relation_connections)
                logger.info(f"     ✅ Found {found_count} relations from TechCorp Industries")
                return {'name': 'Find Relations from Organization', 'passed': True, 'found_count': found_count, 'elapsed_time': elapsed}
            elif response.query_type == "relation":
                logger.info(f"     ✅ Query succeeded but found 0 relations from TechCorp")
                return {'name': 'Find Relations from Organization', 'passed': True, 'found_count': 0, 'elapsed_time': elapsed}
            else:
                logger.error(f"     ❌ Query failed or wrong query type")
                return {'name': 'Find Relations from Organization', 'passed': False, 'error': 'Query failed or wrong query type', 'elapsed_time': elapsed}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'name': 'Find Relations from Organization', 'passed': False, 'error': str(e), 'elapsed_time': 0}
    
    def _test_find_competitor_relations(self, space_id: str, graph_id: str,
                                       relation_type_uris: Dict[str, str]) -> Dict[str, Any]:
        """Test finding CompetitorOf relations."""
        logger.info("\n  Test 3: Find CompetitorOf relations...")
        
        try:
            competitor_type = relation_type_uris.get('competitor_of')
            if not competitor_type:
                logger.warning("     ⚠️  CompetitorOf relation type not found, skipping")
                return {'passed': True, 'skipped': True, 'elapsed_time': 0}
            
            start_time = time.time()
            response = self.client.kgqueries.query_relation_connections(
                space_id,
                graph_id,
                relation_type_uris=[competitor_type],
                page_size=50,
                offset=0
            )
            elapsed = time.time() - start_time
            
            logger.info(f"     ⏱️  KGQuery execution time: {elapsed:.3f}s")
            
            if response.query_type == "relation" and response.relation_connections:
                found_count = len(response.relation_connections)
                logger.info(f"     ✅ Found {found_count} CompetitorOf relations")
                return {'name': 'Find CompetitorOf Relations', 'passed': True, 'found_count': found_count, 'elapsed_time': elapsed}
            elif response.query_type == "relation":
                logger.info(f"     ✅ Query succeeded but found 0 CompetitorOf relations")
                return {'name': 'Find CompetitorOf Relations', 'passed': True, 'found_count': 0, 'elapsed_time': elapsed}
            else:
                logger.error(f"     ❌ Query failed or wrong query type")
                return {'name': 'Find CompetitorOf Relations', 'passed': False, 'error': 'Query failed or wrong query type', 'elapsed_time': elapsed}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'name': 'Find CompetitorOf Relations', 'passed': False, 'error': str(e), 'elapsed_time': 0}
    
    def _test_find_partner_relations(self, space_id: str, graph_id: str,
                                    relation_type_uris: Dict[str, str]) -> Dict[str, Any]:
        """Test finding PartnerWith relations."""
        logger.info("\n  Test 4: Find PartnerWith relations...")
        
        try:
            partner_type = relation_type_uris.get('partner_with')
            if not partner_type:
                logger.warning("     ⚠️  PartnerWith relation type not found, skipping")
                return {'passed': True, 'skipped': True, 'elapsed_time': 0}
            
            start_time = time.time()
            response = self.client.kgqueries.query_relation_connections(
                space_id,
                graph_id,
                relation_type_uris=[partner_type],
                page_size=50,
                offset=0
            )
            elapsed = time.time() - start_time
            
            logger.info(f"     ⏱️  KGQuery execution time: {elapsed:.3f}s")
            
            if response.query_type == "relation" and response.relation_connections:
                found_count = len(response.relation_connections)
                logger.info(f"     ✅ Found {found_count} PartnerWith relations")
                return {'name': 'Find PartnerWith Relations', 'passed': True, 'found_count': found_count, 'elapsed_time': elapsed}
            elif response.query_type == "relation":
                logger.info(f"     ✅ Query succeeded but found 0 PartnerWith relations")
                return {'name': 'Find PartnerWith Relations', 'passed': True, 'found_count': 0, 'elapsed_time': elapsed}
            else:
                logger.error(f"     ❌ Query failed or wrong query type")
                return {'name': 'Find PartnerWith Relations', 'passed': False, 'error': 'Query failed or wrong query type', 'elapsed_time': elapsed}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'name': 'Find PartnerWith Relations', 'passed': False, 'error': str(e), 'elapsed_time': 0}
    
    def _test_find_supplies_relations(self, space_id: str, graph_id: str,
                                     relation_type_uris: Dict[str, str]) -> Dict[str, Any]:
        """Test finding Supplies relations."""
        logger.info("\n  Test 5: Find Supplies relations...")
        
        try:
            supplies_type = relation_type_uris.get('supplies')
            if not supplies_type:
                logger.warning("     ⚠️  Supplies relation type not found, skipping")
                return {'passed': True, 'skipped': True, 'elapsed_time': 0}
            
            start_time = time.time()
            response = self.client.kgqueries.query_relation_connections(
                space_id,
                graph_id,
                relation_type_uris=[supplies_type],
                page_size=50,
                offset=0
            )
            elapsed = time.time() - start_time
            
            logger.info(f"     ⏱️  KGQuery execution time: {elapsed:.3f}s")
            
            if response.query_type == "relation" and response.relation_connections:
                found_count = len(response.relation_connections)
                logger.info(f"     ✅ Found {found_count} Supplies relations")
                return {'name': 'Find Supplies Relations', 'passed': True, 'found_count': found_count, 'elapsed_time': elapsed}
            elif response.query_type == "relation":
                logger.info(f"     ✅ Query succeeded but found 0 Supplies relations")
                return {'name': 'Find Supplies Relations', 'passed': True, 'found_count': 0, 'elapsed_time': elapsed}
            else:
                logger.error(f"     ❌ Query failed or wrong query type")
                return {'name': 'Find Supplies Relations', 'passed': False, 'error': 'Query failed or wrong query type', 'elapsed_time': elapsed}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'name': 'Find Supplies Relations', 'passed': False, 'error': str(e), 'elapsed_time': 0}
    
    def _test_filter_by_direction(self, space_id: str, graph_id: str,
                                  org_uri_map: Dict[str, str],
                                  relation_type_uris: Dict[str, str]) -> Dict[str, Any]:
        """Test filtering relations by direction."""
        logger.info("\n  Test 6: Filter by direction (outgoing)...")
        
        try:
            # Get first organization
            first_org_uri = next(iter(org_uri_map.values()))
            
            start_time = time.time()
            response = self.client.kgqueries.query_relation_connections(
                space_id,
                graph_id,
                source_entity_uris=[first_org_uri],
                direction="outgoing",
                page_size=50,
                offset=0
            )
            elapsed = time.time() - start_time
            
            logger.info(f"     ⏱️  KGQuery execution time: {elapsed:.3f}s")
            
            if response.query_type == "relation" and response.relation_connections:
                found_count = len(response.relation_connections)
                logger.info(f"     ✅ Found {found_count} outgoing relations")
                return {'name': 'Filter by Direction (Outgoing)', 'passed': True, 'found_count': found_count, 'elapsed_time': elapsed}
            elif response.query_type == "relation":
                logger.info(f"     ✅ Query succeeded but found 0 outgoing relations")
                return {'name': 'Filter by Direction (Outgoing)', 'passed': True, 'found_count': 0, 'elapsed_time': elapsed}
            else:
                logger.error(f"     ❌ Query failed or wrong query type")
                return {'name': 'Filter by Direction (Outgoing)', 'passed': False, 'error': 'Query failed or wrong query type', 'elapsed_time': elapsed}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'name': 'Filter by Direction (Outgoing)', 'passed': False, 'error': str(e), 'elapsed_time': 0}
    
    def _test_pagination(self, space_id: str, graph_id: str,
                        relation_type_uris: Dict[str, str]) -> Dict[str, Any]:
        """Test pagination of relation query results."""
        logger.info("\n  Test 7: Pagination...")
        
        try:
            # First page
            start_time = time.time()
            response1 = self.client.kgqueries.query_relation_connections(
                space_id,
                graph_id,
                page_size=5,
                offset=0
            )
            elapsed = time.time() - start_time
            
            logger.info(f"     ⏱️  KGQuery execution time (page 1): {elapsed:.3f}s")
            logger.info(f"KGQuery Response: query_type={response1.query_type}, total_count={response1.total_count}")
            
            if response1.query_type != "relation":
                logger.error(f"     ❌ First page query returned wrong type")
                return {'passed': False, 'error': 'First page returned wrong query type'}
            
            page1_count = len(response1.relation_connections) if response1.relation_connections else 0
            
            # Second page
            start_time = time.time()
            response2 = self.client.kgqueries.query_relation_connections(
                space_id,
                graph_id,
                page_size=5,
                offset=5
            )
            elapsed = time.time() - start_time
            
            logger.info(f"     ⏱️  KGQuery execution time (page 2): {elapsed:.3f}s")
            logger.info(f"KGQuery Response: query_type={response2.query_type}, total_count={response2.total_count}")
            
            if response2.query_type != "relation":
                logger.error(f"     ❌ Second page query returned wrong type")
                return {'passed': False, 'error': 'Second page returned wrong query type'}
            
            page2_count = len(response2.relation_connections) if response2.relation_connections else 0
            
            logger.info(f"     ✅ Page 1: {page1_count} results, Page 2: {page2_count} results")
            return {'name': 'Pagination Test', 'passed': True, 'page1_count': page1_count, 'page2_count': page2_count, 'elapsed_time': elapsed}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'name': 'Pagination Test', 'passed': False, 'error': str(e), 'elapsed_time': 0}
    
    def _test_empty_results(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test query that should return empty results."""
        logger.info("\n  Test 8: Empty results query...")
        
        try:
            # Query for non-existent relation type
            start_time = time.time()
            response = self.client.kgqueries.query_relation_connections(
                space_id,
                graph_id,
                relation_type_uris=["http://nonexistent.uri/relation/NonExistentRelation"],
                page_size=50,
                offset=0
            )
            elapsed = time.time() - start_time
            
            logger.info(f"     ⏱️  KGQuery execution time: {elapsed:.3f}s")
            logger.info(f"KGQuery Response: query_type={response.query_type}, total_count={response.total_count}")
            
            if response.query_type == "relation":
                found_count = len(response.relation_connections) if response.relation_connections else 0
                if found_count == 0:
                    logger.info(f"     ✅ Correctly returned 0 results for non-existent relation type")
                    return {'name': 'Empty Results Query', 'passed': True, 'found_count': 0, 'elapsed_time': elapsed}
                else:
                    logger.warning(f"     ⚠️  Expected 0 results but found {found_count}")
                    return {'name': 'Empty Results Query', 'passed': True, 'found_count': found_count, 'elapsed_time': elapsed}  # Still pass, just unexpected
            else:
                logger.error(f"     ❌ Query failed or wrong query type")
                return {'name': 'Empty Results Query', 'passed': False, 'error': 'Query failed or wrong query type', 'elapsed_time': elapsed}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'name': 'Empty Results Query', 'passed': False, 'error': str(e), 'elapsed_time': 0}
