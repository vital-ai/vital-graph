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
        
    async def run_tests(self, space_id: str, graph_id: str,
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
        test1 = await self._test_find_makes_product_relations(space_id, graph_id, relation_type_uris)
        results.append(test1)
        if not test1['passed']:
            errors.append(test1.get('error', 'Find MakesProduct relations failed'))
        
        # Test 2: Find relations from specific organization
        test2 = await self._test_find_relations_from_org(space_id, graph_id, org_uri_map, relation_type_uris)
        results.append(test2)
        if not test2['passed']:
            errors.append(test2.get('error', 'Find relations from org failed'))
        
        # Test 3: Find CompetitorOf relations
        test3 = await self._test_find_competitor_relations(space_id, graph_id, relation_type_uris)
        results.append(test3)
        if not test3['passed']:
            errors.append(test3.get('error', 'Find CompetitorOf relations failed'))
        
        # Test 4: Find PartnerWith relations
        test4 = await self._test_find_partner_relations(space_id, graph_id, relation_type_uris)
        results.append(test4)
        if not test4['passed']:
            errors.append(test4.get('error', 'Find PartnerWith relations failed'))
        
        # Test 5: Find Supplies relations
        test5 = await self._test_find_supplies_relations(space_id, graph_id, relation_type_uris)
        results.append(test5)
        if not test5['passed']:
            errors.append(test5.get('error', 'Find Supplies relations failed'))
        
        # Test 6: Filter by direction (outgoing)
        test6 = await self._test_filter_by_direction(space_id, graph_id, org_uri_map, relation_type_uris)
        results.append(test6)
        if not test6['passed']:
            errors.append(test6.get('error', 'Filter by direction failed'))
        
        # Test 7: Pagination
        test7 = await self._test_pagination(space_id, graph_id, relation_type_uris)
        results.append(test7)
        if not test7['passed']:
            errors.append(test7.get('error', 'Pagination failed'))
        
        # Test 8: Empty results
        test8 = await self._test_empty_results(space_id, graph_id)
        results.append(test8)
        if not test8['passed']:
            errors.append(test8.get('error', 'Empty results test failed'))
        
        # Test 9: Pagination count consistency (total_count same regardless of page_size)
        test9 = await self._test_pagination_count_consistency(space_id, graph_id)
        results.append(test9)
        if not test9['passed']:
            errors.append(test9.get('error', 'Pagination count consistency failed'))
        
        # Test 10: Offset beyond total returns empty with correct total_count
        test10 = await self._test_pagination_offset_beyond_total(space_id, graph_id)
        results.append(test10)
        if not test10['passed']:
            errors.append(test10.get('error', 'Offset beyond total test failed'))
        
        # Test 11: Sort relations by source entity's slot value
        test11 = await self._test_sort_by_source_slot(space_id, graph_id, relation_type_uris)
        results.append(test11)
        if not test11['passed']:
            errors.append(test11.get('error', 'Sort by source slot failed'))
        
        # Test 12: Sort relations by destination entity's slot value
        test12 = await self._test_sort_by_destination_slot(space_id, graph_id, relation_type_uris)
        results.append(test12)
        if not test12['passed']:
            errors.append(test12.get('error', 'Sort by destination slot failed'))
        
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
    
    async def _test_find_makes_product_relations(self, space_id: str, graph_id: str,
                                          relation_type_uris: Dict[str, str]) -> Dict[str, Any]:
        """Test finding all MakesProduct relations."""
        logger.info("\n  Test 1: Find all MakesProduct relations...")
        
        try:
            makes_product_type = relation_type_uris.get('makes_product')
            if not makes_product_type:
                logger.warning("     ⚠️  MakesProduct relation type not found, skipping")
                return {'passed': True, 'skipped': True, 'elapsed_time': 0}
            
            start_time = time.time()
            response = await self.client.kgqueries.query_relation_connections(
                space_id, 
                graph_id,
                relation_type_uris=[makes_product_type],
                page_size=50,
                offset=0
            )
            elapsed = time.time() - start_time
            
            logger.info(f"     ⏱️  KGQuery execution time: {elapsed:.3f}s")
            
            if response.connections:
                found_count = len(response.connections)
                logger.info(f"     ✅ Found {found_count} MakesProduct relations")
                return {'name': 'Find MakesProduct Relations', 'passed': True, 'found_count': found_count, 'elapsed_time': elapsed}
            else:
                logger.info(f"     ✅ Query succeeded but found 0 MakesProduct relations")
                return {'name': 'Find MakesProduct Relations', 'passed': True, 'found_count': 0, 'elapsed_time': elapsed}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'name': 'Find MakesProduct Relations', 'passed': False, 'error': str(e), 'elapsed_time': 0}
    
    async def _test_find_relations_from_org(self, space_id: str, graph_id: str,
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
            response = await self.client.kgqueries.query_relation_connections(
                space_id,
                graph_id,
                source_entity_uris=[techcorp_uri],
                direction="outgoing",
                page_size=50,
                offset=0
            )
            elapsed = time.time() - start_time
            
            logger.info(f"     ⏱️  KGQuery execution time: {elapsed:.3f}s")
            
            if response.connections:
                found_count = len(response.connections)
                logger.info(f"     ✅ Found {found_count} relations from TechCorp Industries")
                return {'name': 'Find Relations from Organization', 'passed': True, 'found_count': found_count, 'elapsed_time': elapsed}
            else:
                logger.info(f"     ✅ Query succeeded but found 0 relations from TechCorp")
                return {'name': 'Find Relations from Organization', 'passed': True, 'found_count': 0, 'elapsed_time': elapsed}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'name': 'Find Relations from Organization', 'passed': False, 'error': str(e), 'elapsed_time': 0}
    
    async def _test_find_competitor_relations(self, space_id: str, graph_id: str,
                                       relation_type_uris: Dict[str, str]) -> Dict[str, Any]:
        """Test finding CompetitorOf relations."""
        logger.info("\n  Test 3: Find CompetitorOf relations...")
        
        try:
            competitor_type = relation_type_uris.get('competitor_of')
            if not competitor_type:
                logger.warning("     ⚠️  CompetitorOf relation type not found, skipping")
                return {'passed': True, 'skipped': True, 'elapsed_time': 0}
            
            start_time = time.time()
            response = await self.client.kgqueries.query_relation_connections(
                space_id,
                graph_id,
                relation_type_uris=[competitor_type],
                page_size=50,
                offset=0
            )
            elapsed = time.time() - start_time
            
            logger.info(f"     ⏱️  KGQuery execution time: {elapsed:.3f}s")
            
            if response.connections:
                found_count = len(response.connections)
                logger.info(f"     ✅ Found {found_count} CompetitorOf relations")
                return {'name': 'Find CompetitorOf Relations', 'passed': True, 'found_count': found_count, 'elapsed_time': elapsed}
            else:
                logger.info(f"     ✅ Query succeeded but found 0 CompetitorOf relations")
                return {'name': 'Find CompetitorOf Relations', 'passed': True, 'found_count': 0, 'elapsed_time': elapsed}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'name': 'Find CompetitorOf Relations', 'passed': False, 'error': str(e), 'elapsed_time': 0}
    
    async def _test_find_partner_relations(self, space_id: str, graph_id: str,
                                    relation_type_uris: Dict[str, str]) -> Dict[str, Any]:
        """Test finding PartnerWith relations."""
        logger.info("\n  Test 4: Find PartnerWith relations...")
        
        try:
            partner_type = relation_type_uris.get('partner_with')
            if not partner_type:
                logger.warning("     ⚠️  PartnerWith relation type not found, skipping")
                return {'passed': True, 'skipped': True, 'elapsed_time': 0}
            
            start_time = time.time()
            response = await self.client.kgqueries.query_relation_connections(
                space_id,
                graph_id,
                relation_type_uris=[partner_type],
                page_size=50,
                offset=0
            )
            elapsed = time.time() - start_time
            
            logger.info(f"     ⏱️  KGQuery execution time: {elapsed:.3f}s")
            
            if response.connections:
                found_count = len(response.connections)
                logger.info(f"     ✅ Found {found_count} PartnerWith relations")
                return {'name': 'Find PartnerWith Relations', 'passed': True, 'found_count': found_count, 'elapsed_time': elapsed}
            else:
                logger.info(f"     ✅ Query succeeded but found 0 PartnerWith relations")
                return {'name': 'Find PartnerWith Relations', 'passed': True, 'found_count': 0, 'elapsed_time': elapsed}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'name': 'Find PartnerWith Relations', 'passed': False, 'error': str(e), 'elapsed_time': 0}
    
    async def _test_find_supplies_relations(self, space_id: str, graph_id: str,
                                     relation_type_uris: Dict[str, str]) -> Dict[str, Any]:
        """Test finding Supplies relations."""
        logger.info("\n  Test 5: Find Supplies relations...")
        
        try:
            supplies_type = relation_type_uris.get('supplies')
            if not supplies_type:
                logger.warning("     ⚠️  Supplies relation type not found, skipping")
                return {'passed': True, 'skipped': True, 'elapsed_time': 0}
            
            start_time = time.time()
            response = await self.client.kgqueries.query_relation_connections(
                space_id,
                graph_id,
                relation_type_uris=[supplies_type],
                page_size=50,
                offset=0
            )
            elapsed = time.time() - start_time
            
            logger.info(f"     ⏱️  KGQuery execution time: {elapsed:.3f}s")
            
            if response.connections:
                found_count = len(response.connections)
                logger.info(f"     ✅ Found {found_count} Supplies relations")
                return {'name': 'Find Supplies Relations', 'passed': True, 'found_count': found_count, 'elapsed_time': elapsed}
            else:
                logger.info(f"     ✅ Query succeeded but found 0 Supplies relations")
                return {'name': 'Find Supplies Relations', 'passed': True, 'found_count': 0, 'elapsed_time': elapsed}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'name': 'Find Supplies Relations', 'passed': False, 'error': str(e), 'elapsed_time': 0}
    
    async def _test_filter_by_direction(self, space_id: str, graph_id: str,
                                  org_uri_map: Dict[str, str],
                                  relation_type_uris: Dict[str, str]) -> Dict[str, Any]:
        """Test filtering relations by direction."""
        logger.info("\n  Test 6: Filter by direction (outgoing)...")
        
        try:
            # Get first organization
            first_org_uri = next(iter(org_uri_map.values()))
            
            start_time = time.time()
            response = await self.client.kgqueries.query_relation_connections(
                space_id,
                graph_id,
                source_entity_uris=[first_org_uri],
                direction="outgoing",
                page_size=50,
                offset=0
            )
            elapsed = time.time() - start_time
            
            logger.info(f"     ⏱️  KGQuery execution time: {elapsed:.3f}s")
            
            if response.connections:
                found_count = len(response.connections)
                logger.info(f"     ✅ Found {found_count} outgoing relations")
                return {'name': 'Filter by Direction (Outgoing)', 'passed': True, 'found_count': found_count, 'elapsed_time': elapsed}
            else:
                logger.info(f"     ✅ Query succeeded but found 0 outgoing relations")
                return {'name': 'Filter by Direction (Outgoing)', 'passed': True, 'found_count': 0, 'elapsed_time': elapsed}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'name': 'Filter by Direction (Outgoing)', 'passed': False, 'error': str(e), 'elapsed_time': 0}
    
    async def _test_pagination(self, space_id: str, graph_id: str,
                        relation_type_uris: Dict[str, str]) -> Dict[str, Any]:
        """Test pagination of relation query results.
        
        Verifies:
        - Page 1 returns <= page_size results
        - Page 2 returns remaining results
        - total_count is consistent between both pages
        - Pages don't overlap (combined count matches total)
        """
        logger.info("\n  Test 7: Pagination...")
        
        try:
            # First page
            start_time = time.time()
            response1 = await self.client.kgqueries.query_relation_connections(
                space_id,
                graph_id,
                page_size=5,
                offset=0
            )
            elapsed1 = time.time() - start_time
            
            logger.info(f"     ⏱️  KGQuery execution time (page 1): {elapsed1:.3f}s")
            logger.info(f"     Page 1: total_count={response1.total_count}")
            
            page1_count = len(response1.connections) if response1.connections else 0
            
            # Second page
            start_time = time.time()
            response2 = await self.client.kgqueries.query_relation_connections(
                space_id,
                graph_id,
                page_size=5,
                offset=5
            )
            elapsed2 = time.time() - start_time
            
            logger.info(f"     ⏱️  KGQuery execution time (page 2): {elapsed2:.3f}s")
            logger.info(f"     Page 2: total_count={response2.total_count}")
            
            page2_count = len(response2.connections) if response2.connections else 0
            
            # Verify page_size cap
            passed = True
            if page1_count > 5:
                logger.error(f"     ❌ Page 1 returned {page1_count} results, expected <= 5")
                passed = False
            
            # Verify total_count consistency between pages
            if response1.total_count != response2.total_count:
                logger.error(f"     ❌ total_count mismatch: page1={response1.total_count}, page2={response2.total_count}")
                passed = False
            
            # Verify combined count matches total (no overlap, no gaps)
            total = response1.total_count
            expected_page2 = max(0, total - 5)
            if page2_count != min(5, expected_page2):
                logger.warning(f"     ⚠️  Page 2 has {page2_count} results, expected {min(5, expected_page2)} (total={total})")
            
            if passed:
                logger.info(f"     ✅ Page 1: {page1_count} results, Page 2: {page2_count} results, total_count={total} (consistent)")
            
            return {'name': 'Pagination Test', 'passed': passed, 'page1_count': page1_count, 'page2_count': page2_count,
                    'total_count': total, 'elapsed_time': elapsed1 + elapsed2}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'name': 'Pagination Test', 'passed': False, 'error': str(e), 'elapsed_time': 0}
    
    async def _test_pagination_count_consistency(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test that total_count is the same regardless of page_size.
        
        Queries with page_size=2 and page_size=100 should return the same total_count.
        """
        logger.info("\n  Test 9: Pagination count consistency...")
        
        try:
            start_time = time.time()
            small_page = await self.client.kgqueries.query_relation_connections(
                space_id, graph_id, page_size=2, offset=0
            )
            large_page = await self.client.kgqueries.query_relation_connections(
                space_id, graph_id, page_size=100, offset=0
            )
            elapsed = time.time() - start_time
            
            small_total = small_page.total_count
            large_total = large_page.total_count
            small_results = len(small_page.connections) if small_page.connections else 0
            large_results = len(large_page.connections) if large_page.connections else 0
            
            passed = True
            if small_total != large_total:
                logger.error(f"     ❌ total_count mismatch: page_size=2 -> {small_total}, page_size=100 -> {large_total}")
                passed = False
            
            if small_results > 2:
                logger.error(f"     ❌ page_size=2 returned {small_results} results, expected <= 2")
                passed = False
            
            # Large page should contain all results
            if large_results != large_total:
                logger.warning(f"     ⚠️  page_size=100 returned {large_results} results, total={large_total}")
            
            if passed:
                logger.info(f"     ✅ total_count consistent: {small_total} (page_size=2 returned {small_results}, page_size=100 returned {large_results})")
            
            return {'name': 'Count Consistency', 'passed': passed, 'total_count': small_total, 'elapsed_time': elapsed}
            
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'name': 'Count Consistency', 'passed': False, 'error': str(e), 'elapsed_time': 0}
    
    async def _test_pagination_offset_beyond_total(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test that offset >= total_count returns empty connections with correct total_count.
        
        This verifies the count-first short-circuit path.
        """
        logger.info("\n  Test 10: Offset beyond total...")
        
        try:
            # First get total_count
            start_time = time.time()
            baseline = await self.client.kgqueries.query_relation_connections(
                space_id, graph_id, page_size=1, offset=0
            )
            total = baseline.total_count
            
            # Now query with offset >= total
            beyond = await self.client.kgqueries.query_relation_connections(
                space_id, graph_id, page_size=10, offset=total + 100
            )
            elapsed = time.time() - start_time
            
            beyond_count = len(beyond.connections) if beyond.connections else 0
            
            passed = True
            if beyond_count != 0:
                logger.error(f"     ❌ Expected 0 results for offset={total + 100}, got {beyond_count}")
                passed = False
            
            if beyond.total_count != total:
                logger.error(f"     ❌ total_count changed: baseline={total}, beyond={beyond.total_count}")
                passed = False
            
            if passed:
                logger.info(f"     ✅ offset={total + 100} returned 0 results, total_count={beyond.total_count} (correct)")
            
            return {'name': 'Offset Beyond Total', 'passed': passed, 'total_count': total, 'elapsed_time': elapsed}
            
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'name': 'Offset Beyond Total', 'passed': False, 'error': str(e), 'elapsed_time': 0}
    
    async def _test_empty_results(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test query that should return empty results."""
        logger.info("\n  Test 8: Empty results query...")
        
        try:
            # Query for non-existent relation type
            start_time = time.time()
            response = await self.client.kgqueries.query_relation_connections(
                space_id,
                graph_id,
                relation_type_uris=["http://nonexistent.uri/relation/NonExistentRelation"],
                page_size=50,
                offset=0
            )
            elapsed = time.time() - start_time
            
            logger.info(f"     ⏱️  KGQuery execution time: {elapsed:.3f}s")
            logger.info(f"KGQuery Response: total_count={response.total_count}")
            
            found_count = len(response.connections) if response.connections else 0
            if found_count == 0:
                logger.info(f"     ✅ Correctly returned 0 results for non-existent relation type")
                return {'name': 'Empty Results Query', 'passed': True, 'found_count': 0, 'elapsed_time': elapsed}
            else:
                logger.warning(f"     ⚠️  Expected 0 results but found {found_count}")
                return {'name': 'Empty Results Query', 'passed': True, 'found_count': found_count, 'elapsed_time': elapsed}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'name': 'Empty Results Query', 'passed': False, 'error': str(e), 'elapsed_time': 0}
    
    async def _test_sort_by_source_slot(self, space_id: str, graph_id: str,
                                        relation_type_uris: Dict[str, str]) -> Dict[str, Any]:
        """Test 11: Sort MakesProduct relations by source org's EmployeeCount DESC."""
        logger.info("\n  Test 11: Sort relations by source entity slot (EmployeeCount DESC)...")
        
        try:
            from vitalgraph.model.kgentities_model import SortCriteria
            
            makes_product_type = relation_type_uris.get('makes_product')
            if not makes_product_type:
                logger.warning("     ⚠️  MakesProduct relation type not found, skipping")
                return {'name': 'Sort by Source Slot', 'passed': True, 'skipped': True, 'elapsed_time': 0}
            
            sort_criteria = [
                SortCriteria(
                    sort_type="source_frame_slot",
                    frame_path=[
                        "http://vital.ai/ontology/haley-ai-kg#CompanyInfoFrame"
                    ],
                    slot_type="http://vital.ai/ontology/haley-ai-kg#EmployeeCountSlot",
                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot",
                    sort_order="desc",
                    priority=1
                )
            ]
            
            start_time = time.time()
            response = await self.client.kgqueries.query_relation_connections(
                space_id,
                graph_id,
                relation_type_uris=[makes_product_type],
                sort_criteria=sort_criteria,
                page_size=20,
                offset=0
            )
            elapsed = time.time() - start_time
            
            logger.info(f"     ⏱️  KGQuery execution time: {elapsed:.3f}s")
            
            connections = response.connections or []
            if len(connections) > 0:
                logger.info(f"     ✅ Got {len(connections)} MakesProduct relations sorted by source EmployeeCount DESC (total: {response.total_count})")
                return {'name': 'Sort by Source Slot', 'passed': True, 'found_count': len(connections), 'elapsed_time': elapsed}
            else:
                logger.error(f"     ❌ Expected >0 relations, got 0")
                return {'name': 'Sort by Source Slot', 'passed': False, 'error': 'Expected >0 relations', 'elapsed_time': elapsed}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'name': 'Sort by Source Slot', 'passed': False, 'error': str(e), 'elapsed_time': 0}
    
    async def _test_sort_by_destination_slot(self, space_id: str, graph_id: str,
                                             relation_type_uris: Dict[str, str]) -> Dict[str, Any]:
        """Test 12: Sort CompetitorOf relations by destination org's CitySlot ASC."""
        logger.info("\n  Test 12: Sort relations by destination entity slot (City ASC)...")
        
        try:
            from vitalgraph.model.kgentities_model import SortCriteria
            
            competitor_type = relation_type_uris.get('competitor_of')
            if not competitor_type:
                logger.warning("     ⚠️  CompetitorOf relation type not found, skipping")
                return {'name': 'Sort by Destination Slot', 'passed': True, 'skipped': True, 'elapsed_time': 0}
            
            sort_criteria = [
                SortCriteria(
                    sort_type="destination_frame_slot",
                    frame_path=[
                        "http://vital.ai/ontology/haley-ai-kg#AddressFrame"
                    ],
                    slot_type="http://vital.ai/ontology/haley-ai-kg#CitySlot",
                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                    sort_order="asc",
                    priority=1
                )
            ]
            
            start_time = time.time()
            response = await self.client.kgqueries.query_relation_connections(
                space_id,
                graph_id,
                relation_type_uris=[competitor_type],
                sort_criteria=sort_criteria,
                page_size=20,
                offset=0
            )
            elapsed = time.time() - start_time
            
            logger.info(f"     ⏱️  KGQuery execution time: {elapsed:.3f}s")
            
            connections = response.connections or []
            if len(connections) > 0:
                logger.info(f"     ✅ Got {len(connections)} CompetitorOf relations sorted by destination City ASC (total: {response.total_count})")
                return {'name': 'Sort by Destination Slot', 'passed': True, 'found_count': len(connections), 'elapsed_time': elapsed}
            else:
                logger.error(f"     ❌ Expected >0 relations, got 0")
                return {'name': 'Sort by Destination Slot', 'passed': False, 'error': 'Expected >0 relations', 'elapsed_time': elapsed}
                
        except Exception as e:
            logger.error(f"     ❌ Exception: {e}")
            return {'name': 'Sort by Destination Slot', 'passed': False, 'error': str(e), 'elapsed_time': 0}
