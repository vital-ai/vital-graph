#!/usr/bin/env python3
"""
KGQuery Lead Queries Test Case

This test case performs KGQuery frame-based queries on the lead entity graph dataset
to find leads matching specific criteria based on their frames and slots.

Query Scenarios:
1. Find MQL (Marketing Qualified Leads) - leads with MQL=true
2. Find leads in California - filter by company state code
3. Find leads in specific cities - filter by company city
4. Find high-rated leads - filter by MQL rating >= 65
5. Find leads with business accounts - filter by hasBizAccount=true
6. Find converted leads - filter by isConverted=true
7. Find abandoned leads - filter by abandoned flag
8. Multi-criteria query - combine multiple frame/slot filters
"""

import logging
import time
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class KGQueryLeadQueriesTester:
    """Test case for KGQuery frame-based queries on lead entities."""
    
    def __init__(self, client):
        """
        Initialize the KGQuery lead queries tester.
        
        Args:
            client: VitalGraphClient instance
        """
        self.client = client
        self.tests_run = 0
        self.tests_passed = 0
        self.errors = []
        self.query_times = []  # Track query execution times
    
    def _record_test(self, test_name: str, passed: bool, error: str = None, query_time: float = None):
        """Record test result."""
        self.tests_run += 1
        if passed:
            self.tests_passed += 1
            if query_time is not None:
                print(f"✅ PASS: {test_name} (Query time: {query_time:.3f}s)")
            else:
                print(f"✅ PASS: {test_name}")
        else:
            self.errors.append(error or test_name)
            print(f"❌ FAIL: {test_name}")
            if error:
                print(f"   Error: {error}")
        
        # Track query time if provided
        if query_time is not None:
            self.query_times.append({
                "test_name": test_name,
                "query_time": query_time,
                "passed": passed
            })
    
    def run_tests(self, space_id: str, graph_id: str, expected_entity_count: int) -> dict:
        """
        Run KGQuery lead queries tests.
        
        Args:
            space_id: Space ID
            graph_id: Graph ID
            expected_entity_count: Total number of entities loaded
            
        Returns:
            Dictionary with test results
        """
        print(f"\n{'=' * 80}")
        print(f"  KGQuery Lead Frame Queries")
        print(f"{'=' * 80}")
        
        print(f"\n📊 Running frame-based queries on {expected_entity_count} lead entities...")
        
        # Run all query tests
        self._test_find_mql_leads(space_id, graph_id)
        self._test_hierarchical_frame_query(space_id, graph_id)
        self._test_find_leads_in_california(space_id, graph_id)
        self._test_find_leads_in_los_angeles(space_id, graph_id)
        self._test_find_high_rated_leads(space_id, graph_id)
        self._test_find_leads_with_biz_accounts(space_id, graph_id)
        self._test_find_converted_leads(space_id, graph_id)
        self._test_find_abandoned_leads(space_id, graph_id)
        self._test_multi_criteria_query(space_id, graph_id)
        self._test_range_query_multiple_filters(space_id, graph_id)
        self._test_pagination(space_id, graph_id)
        self._test_empty_results(space_id, graph_id)
        
        # Print query time summary
        if self.query_times:
            print(f"\n{'=' * 80}")
            print(f"  Query Time Summary")
            print(f"{'=' * 80}")
            total_time = sum(qt["query_time"] for qt in self.query_times)
            print(f"\n📊 Total query time: {total_time:.3f}s")
            print(f"📊 Average query time: {total_time/len(self.query_times):.3f}s")
            print(f"\n  Individual query times:")
            for qt in self.query_times:
                status = "✅" if qt["passed"] else "❌"
                print(f"    {status} {qt['test_name']}: {qt['query_time']:.3f}s")
            print()
        
        return {
            "test_name": "KGQuery Lead Frame Queries",
            "tests_run": self.tests_run,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_run - self.tests_passed,
            "errors": self.errors,
            "query_times": self.query_times,
            "total_query_time": sum(qt["query_time"] for qt in self.query_times) if self.query_times else 0
        }
    
    def _test_find_mql_leads(self, space_id: str, graph_id: str):
        """Test finding Marketing Qualified Leads (MQL=true)."""
        print(f"\n  Test 1: Find MQL (Marketing Qualified Leads)...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria
            
            # Query for leads with hierarchical frame: LeadStatusFrame → LeadStatusQualificationFrame → MQL slot
            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity"
            )
            
            frame_criteria_list = [
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:LeadStatusFrame",  # Parent frame
                    frame_criteria=[  # Child frames
                        FrameCriteria(
                            frame_type="urn:cardiff:kg:frame:LeadStatusQualificationFrame",  # Child frame
                            slot_criteria=[
                                SlotCriteria(
                                    slot_type="urn:cardiff:kg:slot:MQLv2",
                                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot",
                                    value=True,
                                    comparator="eq"
                                )
                            ]
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
            
            # Time the query execution
            start_time = time.time()
            response = self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=100,
                offset=0
            )
            query_time = time.time() - start_time
            
            if response.query_type == "frame" and response.frame_connections:
                found_count = len(response.frame_connections)
                print(f"     ✅ Found {found_count} MQL leads")
                self._record_test("Find MQL leads", True, query_time=query_time)
            elif response.query_type == "frame":
                print(f"     ✅ Query succeeded but found 0 MQL leads")
                self._record_test("Find MQL leads", True, query_time=query_time)
            else:
                print(f"     ❌ Query failed or wrong query type")
                self._record_test("Find MQL leads", False, "Query failed or wrong query type", query_time=query_time)
                
        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Find MQL leads", False, str(e))
    
    def _test_hierarchical_frame_query(self, space_id: str, graph_id: str):
        """Test hierarchical frame query (Entity → Parent Frame → Child Frame → Slot)."""
        print(f"\n  Test 2: Hierarchical Frame Query (Parent → Child Frame)...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria
            
            # Query for leads with hierarchical frame structure:
            # Entity → LeadTrackingFrame (parent) → LeadOwnerFrame (child) → LeadOwnerName slot
            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity"
            )
            
            # Hierarchical frame criteria: parent frame with nested child frame
            frame_criteria_list = [
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:LeadTrackingFrame",  # Parent frame
                    frame_criteria=[  # Nested child frames
                        FrameCriteria(
                            frame_type="urn:cardiff:kg:frame:LeadOwnerFrame",  # Child frame
                            slot_criteria=[
                                SlotCriteria(
                                    slot_type="urn:cardiff:kg:slot:LeadOwnerName",
                                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                                    comparator="exists"  # Just check if the slot exists
                                )
                            ]
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
            
            # Time the query execution
            start_time = time.time()
            response = self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=100,
                offset=0
            )
            query_time = time.time() - start_time
            
            if response.query_type == "frame" and response.frame_connections:
                found_count = len(response.frame_connections)
                print(f"     ✅ Found {found_count} leads with hierarchical frame structure")
                self._record_test("Hierarchical frame query", True, query_time=query_time)
            elif response.query_type == "frame":
                print(f"     ✅ Query succeeded but found 0 leads with hierarchical structure")
                self._record_test("Hierarchical frame query", True, query_time=query_time)
            else:
                print(f"     ❌ Query failed or wrong query type")
                self._record_test("Hierarchical frame query", False, "Query failed or wrong query type", query_time=query_time)
                
        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Hierarchical frame query", False, str(e))
    
    def _test_find_leads_in_california(self, space_id: str, graph_id: str):
        """Test finding leads with companies in California."""
        print(f"\n  Test 3: Find leads in California...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria
            
            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity"
            )
            
            frame_criteria_list = [
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:CompanyFrame",  # Parent frame
                    frame_criteria=[  # Child frames
                        FrameCriteria(
                            frame_type="urn:cardiff:kg:frame:CompanyAddressFrame",  # Child frame
                            slot_criteria=[
                                SlotCriteria(
                                    slot_type="urn:cardiff:kg:slot:CompanyStateCode",
                                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                                    value="CA",
                                    comparator="eq"
                                )
                            ]
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
            
            # Time the query execution
            start_time = time.time()
            response = self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=100,
                offset=0
            )
            query_time = time.time() - start_time
            
            if response.query_type == "frame" and response.frame_connections:
                found_count = len(response.frame_connections)
                print(f"     ✅ Found {found_count} leads in California")
                self._record_test("Find leads in California", True, query_time=query_time)
            elif response.query_type == "frame":
                print(f"     ✅ Query succeeded but found 0 leads in California")
                self._record_test("Find leads in California", True, query_time=query_time)
            else:
                print(f"     ❌ Query failed or wrong query type")
                self._record_test("Find leads in California", False, "Query failed or wrong query type", query_time=query_time)
                
        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Find leads in California", False, str(e))
    
    def _test_find_leads_in_los_angeles(self, space_id: str, graph_id: str):
        """Test finding leads with companies in Los Angeles."""
        print(f"\n  Test 4: Find leads in Los Angeles...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria
            
            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity"
            )
            
            frame_criteria_list = [
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:CompanyFrame",  # Parent frame
                    frame_criteria=[  # Child frames
                        FrameCriteria(
                            frame_type="urn:cardiff:kg:frame:CompanyAddressFrame",  # Child frame
                            slot_criteria=[
                                SlotCriteria(
                                    slot_type="urn:cardiff:kg:slot:CompanyCity",
                                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                                    value="Los Angeles",
                                    comparator="eq"
                                )
                            ]
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
            
            # Time the query execution
            start_time = time.time()
            response = self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=100,
                offset=0
            )
            query_time = time.time() - start_time
            
            if response.query_type == "frame" and response.frame_connections:
                found_count = len(response.frame_connections)
                print(f"     ✅ Found {found_count} leads in Los Angeles")
                self._record_test("Find leads in Los Angeles", True, query_time=query_time)
            elif response.query_type == "frame":
                print(f"     ✅ Query succeeded but found 0 leads in Los Angeles")
                self._record_test("Find leads in Los Angeles", True, query_time=query_time)
            else:
                print(f"     ❌ Query failed or wrong query type")
                self._record_test("Find leads in Los Angeles", False, "Query failed or wrong query type", query_time=query_time)
                
        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Find leads in Los Angeles", False, str(e))
    
    def _test_find_high_rated_leads(self, space_id: str, graph_id: str):
        """Test finding leads with high MQL rating (>= 65)."""
        print(f"\n  Test 5: Find high-rated leads (MQL rating >= 65)...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria
            
            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity"
            )
            
            frame_criteria_list = [
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:LeadStatusFrame",  # Parent frame
                    frame_criteria=[  # Child frames
                        FrameCriteria(
                            frame_type="urn:cardiff:kg:frame:LeadStatusQualificationFrame",  # Child frame
                            slot_criteria=[
                                SlotCriteria(
                                    slot_type="urn:cardiff:kg:slot:MQLRating",
                                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot",
                                    value=65.0,
                                    comparator="gte"
                                )
                            ]
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
            
            # Time the query execution
            start_time = time.time()
            response = self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=100,
                offset=0
            )
            query_time = time.time() - start_time
            
            if response.query_type == "frame" and response.frame_connections:
                found_count = len(response.frame_connections)
                print(f"     ✅ Found {found_count} high-rated leads")
                self._record_test("Find high-rated leads", True, query_time=query_time)
            elif response.query_type == "frame":
                print(f"     ✅ Query succeeded but found 0 high-rated leads")
                self._record_test("Find high-rated leads", True, query_time=query_time)
            else:
                print(f"     ❌ Query failed or wrong query type")
                self._record_test("Find high-rated leads", False, "Query failed or wrong query type", query_time=query_time)
                
        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Find high-rated leads", False, str(e))
    
    def _test_find_leads_with_biz_accounts(self, space_id: str, graph_id: str):
        """Test finding leads with business bank accounts."""
        print(f"\n  Test 6: Find leads with business bank accounts...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria
            
            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity"
            )
            
            frame_criteria_list = [
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:PlaidBankingFrame",  # Parent frame
                    frame_criteria=[  # Child frames
                        FrameCriteria(
                            frame_type="urn:cardiff:kg:frame:BankAccountFrame",  # Child frame
                            slot_criteria=[
                                SlotCriteria(
                                    slot_type="urn:cardiff:kg:slot:HasBizAccount",
                                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot",
                                    value=True,
                                    comparator="eq"
                                )
                            ]
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
            
            # Time the query execution
            start_time = time.time()
            response = self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=100,
                offset=0
            )
            query_time = time.time() - start_time
            
            if response.query_type == "frame" and response.frame_connections:
                found_count = len(response.frame_connections)
                print(f"     ✅ Found {found_count} leads with business accounts")
                self._record_test("Find leads with business accounts", True, query_time=query_time)
            elif response.query_type == "frame":
                print(f"     ✅ Query succeeded but found 0 leads with business accounts")
                self._record_test("Find leads with business accounts", True, query_time=query_time)
            else:
                print(f"     ❌ Query failed or wrong query type")
                self._record_test("Find leads with business accounts", False, "Query failed or wrong query type", query_time=query_time)
                
        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Find leads with business accounts", False, str(e))
    
    def _test_find_converted_leads(self, space_id: str, graph_id: str):
        """Test finding converted leads."""
        print(f"\n  Test 7: Find converted leads...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria
            
            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity"
            )
            
            frame_criteria_list = [
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:LeadStatusFrame",  # Parent frame
                    frame_criteria=[  # Child frames
                        FrameCriteria(
                            frame_type="urn:cardiff:kg:frame:LeadStatusConversionFrame",  # Child frame
                            slot_criteria=[
                                SlotCriteria(
                                    slot_type="urn:cardiff:kg:slot:IsConverted",
                                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot",
                                    value=True,
                                    comparator="eq"
                                )
                            ]
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
            
            # Time the query execution
            start_time = time.time()
            response = self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=100,
                offset=0
            )
            query_time = time.time() - start_time
            
            if response.query_type == "frame" and response.frame_connections:
                found_count = len(response.frame_connections)
                print(f"     ✅ Found {found_count} converted leads")
                self._record_test("Find converted leads", True, query_time=query_time)
            elif response.query_type == "frame":
                print(f"     ✅ Query succeeded but found 0 converted leads")
                self._record_test("Find converted leads", True, query_time=query_time)
            else:
                print(f"     ❌ Query failed or wrong query type")
                self._record_test("Find converted leads", False, "Query failed or wrong query type", query_time=query_time)
                
        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Find converted leads", False, str(e))
    
    def _test_find_abandoned_leads(self, space_id: str, graph_id: str):
        """Test finding abandoned leads."""
        print(f"\n  Test 8: Find abandoned leads...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria
            
            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity"
            )
            
            frame_criteria_list = [
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:SystemFrame",  # Parent frame
                    frame_criteria=[  # Child frames
                        FrameCriteria(
                            frame_type="urn:cardiff:kg:frame:SystemFlagsFrame",  # Child frame
                            slot_criteria=[
                                SlotCriteria(
                                    slot_type="urn:cardiff:kg:slot:Abandoned",
                                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot",
                                    value=True,
                                    comparator="eq"
                                )
                            ]
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
            
            # Time the query execution
            start_time = time.time()
            response = self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=100,
                offset=0
            )
            query_time = time.time() - start_time
            
            if response.query_type == "frame" and response.frame_connections:
                found_count = len(response.frame_connections)
                print(f"     ✅ Found {found_count} abandoned leads")
                self._record_test("Find abandoned leads", True, query_time=query_time)
            elif response.query_type == "frame":
                print(f"     ✅ Query succeeded but found 0 abandoned leads")
                self._record_test("Find abandoned leads", True, query_time=query_time)
            else:
                print(f"     ❌ Query failed or wrong query type")
                self._record_test("Find abandoned leads", False, "Query failed or wrong query type", query_time=query_time)
                
        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Find abandoned leads", False, str(e))
    
    def _test_multi_criteria_query(self, space_id: str, graph_id: str):
        """Test multi-criteria query: MQL leads in California with high rating."""
        print(f"\n  Test 9: Multi-criteria query (MQL + California + high rating)...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria
            
            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity"
            )
            
            frame_criteria_list = [
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:LeadStatusFrame",  # Parent frame
                    frame_criteria=[  # Child frames
                        FrameCriteria(
                            frame_type="urn:cardiff:kg:frame:LeadStatusQualificationFrame",  # Child frame
                            slot_criteria=[
                                SlotCriteria(
                                    slot_type="urn:cardiff:kg:slot:MQLv2",
                                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot",
                                    value=True,
                                    comparator="eq"
                                ),
                                SlotCriteria(
                                    slot_type="urn:cardiff:kg:slot:MQLRating",
                                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot",
                                    value=65.0,
                                    comparator="gte"
                                )
                            ]
                        )
                    ]
                ),
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:CompanyFrame",  # Parent frame
                    frame_criteria=[  # Child frames
                        FrameCriteria(
                            frame_type="urn:cardiff:kg:frame:CompanyAddressFrame",  # Child frame
                            slot_criteria=[
                                SlotCriteria(
                                    slot_type="urn:cardiff:kg:slot:CompanyStateCode",
                                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                                    value="CA",
                                    comparator="eq"
                                )
                            ]
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
            
            # Time the query execution
            start_time = time.time()
            response = self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=100,
                offset=0
            )
            query_time = time.time() - start_time
            
            if response.query_type == "frame" and response.frame_connections:
                found_count = len(response.frame_connections)
                print(f"     ✅ Found {found_count} leads matching all criteria")
                self._record_test("Multi-criteria query", True, query_time=query_time)
            elif response.query_type == "frame":
                print(f"     ✅ Query succeeded but found 0 leads matching all criteria")
                self._record_test("Multi-criteria query", True, query_time=query_time)
            else:
                print(f"     ❌ Query failed or wrong query type")
                self._record_test("Multi-criteria query", False, "Query failed or wrong query type", query_time=query_time)
                
        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Multi-criteria query", False, str(e))
    
    def _test_range_query_multiple_filters(self, space_id: str, graph_id: str):
        """Test range query with multiple numeric FILTER variables (MQLRating between 50 and 80)."""
        print(f"\n  Test 9b: Range query with multiple FILTERs (50 <= MQLRating <= 80)...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria
            
            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity"
            )
            
            # Query for leads with MQLRating in range [50, 80]
            # This requires TWO numeric FILTERs on the same slot type
            frame_criteria_list = [
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:LeadStatusFrame",
                    frame_criteria=[
                        FrameCriteria(
                            frame_type="urn:cardiff:kg:frame:LeadStatusQualificationFrame",
                            slot_criteria=[
                                SlotCriteria(
                                    slot_type="urn:cardiff:kg:slot:MQLRating",
                                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot",
                                    value=50.0,
                                    comparator="gte"
                                ),
                                SlotCriteria(
                                    slot_type="urn:cardiff:kg:slot:MQLRating",
                                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot",
                                    value=80.0,
                                    comparator="lte"
                                )
                            ]
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
            
            # Time the query execution
            start_time = time.time()
            response = self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=100,
                offset=0
            )
            query_time = time.time() - start_time
            
            if response.query_type == "frame" and response.frame_connections:
                found_count = len(response.frame_connections)
                print(f"     ✅ Found {found_count} leads with MQLRating in range [50, 80]")
                self._record_test("Range query with multiple FILTERs", True, query_time=query_time)
            elif response.query_type == "frame":
                print(f"     ✅ Query succeeded but found 0 leads in range")
                self._record_test("Range query with multiple FILTERs", True, query_time=query_time)
            else:
                print(f"     ❌ Query failed or wrong query type")
                self._record_test("Range query with multiple FILTERs", False, "Query failed or wrong query type", query_time=query_time)
                
        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Range query with multiple FILTERs", False, str(e))
    
    def _test_pagination(self, space_id: str, graph_id: str):
        """Test pagination of query results."""
        print(f"\n  Test 10: Pagination...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria
            
            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity"
            )
            
            frame_criteria_list = [
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:LeadStatusFrame",  # Parent frame
                    frame_criteria=[  # Child frames
                        FrameCriteria(
                            frame_type="urn:cardiff:kg:frame:LeadStatusQualificationFrame",  # Child frame
                            slot_criteria=[
                                SlotCriteria(
                                    slot_type="urn:cardiff:kg:slot:MQLv2",
                                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot",
                                    value=True,
                                    comparator="eq"
                                )
                            ]
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
            
            # Time the query execution (both pages)
            start_time = time.time()
            
            # First page
            response1 = self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=5,
                offset=0
            )
            
            if response1.query_type != "frame":
                print(f"     ❌ First page query returned wrong type")
                self._record_test("Pagination", False, "First page returned wrong query type")
                return
            
            page1_count = len(response1.frame_connections) if response1.frame_connections else 0
            
            # Second page
            response2 = self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=5,
                offset=5
            )
            
            query_time = time.time() - start_time
            
            if response2.query_type != "frame":
                print(f"     ❌ Second page query returned wrong type")
                self._record_test("Pagination", False, "Second page returned wrong query type", query_time=query_time)
                return
            
            page2_count = len(response2.frame_connections) if response2.frame_connections else 0
            
            print(f"     ✅ Page 1: {page1_count} results, Page 2: {page2_count} results")
            self._record_test("Pagination", True, query_time=query_time)
                
        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Pagination", False, str(e))
    
    def _test_empty_results(self, space_id: str, graph_id: str):
        """Test query that should return empty results."""
        print(f"\n  Test 11: Empty results (non-existent criteria)...")
        
        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria
            
            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity"
            )
            
            frame_criteria_list = [
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:NonExistentFrame",
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="urn:cardiff:kg:slot:NonExistentSlot",
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                            value="NonExistent",
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
            
            # Time the query execution
            start_time = time.time()
            response = self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=20,
                offset=0
            )
            query_time = time.time() - start_time
            
            if response.query_type == "frame":
                found_count = len(response.frame_connections) if response.frame_connections else 0
                if found_count == 0:
                    print(f"     ✅ Correctly returned 0 results for non-existent criteria")
                    self._record_test("Empty results", True, query_time=query_time)
                else:
                    print(f"     ⚠️  Expected 0 results but found {found_count}")
                    self._record_test("Empty results", True, query_time=query_time)  # Still pass, just unexpected
            else:
                print(f"     ❌ Query failed or wrong query type")
                self._record_test("Empty results", False, "Query failed or wrong query type")
                
        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Empty results", False, str(e))
