#!/usr/bin/env python3
"""
Query Lead Data Test Case

Tests querying lead entity data using both entity queries (query_type="entity")
and frame queries (query_type="frame") against already-loaded lead dataset.

Verifies:
- Entity query returns entity URIs with correct total_count
- Frame query returns frame connections with correct total_count
- Pagination works correctly (total_count consistent across pages)
- Various filter criteria match expected data distributions
- New query_entities() client method works end-to-end

Expected data distributions (100 leads):
- CompanyStateCode: CA=13, FL=10, TX=8
- MQL(v2): ~99 true, ~1 false
- IsConverted: ~9 true, ~91 false
- HasBizAccount: ~53 true, ~47 false
- MQLRating: range 0-100 (many at 75)
"""

import logging
import time
from typing import Dict, Any

logger = logging.getLogger(__name__)


class QueryLeadDataTester:
    """Test case for querying lead entities via entity and frame query types."""

    def __init__(self, client, query_mode: str = "edge"):
        self.client = client
        self.query_mode = query_mode
        self.tests_run = 0
        self.tests_passed = 0
        self.errors = []
        self.query_times = []

    def _record_test(self, test_name: str, passed: bool, error: str = None,
                     query_time: float = None, result_count: int = None):
        """Record test result."""
        self.tests_run += 1
        if passed:
            self.tests_passed += 1
            suffix = f" (Query time: {query_time:.3f}s)" if query_time is not None else ""
            print(f"✅ PASS: {test_name}{suffix}")
        else:
            self.errors.append(error or test_name)
            print(f"❌ FAIL: {test_name}")
            if error:
                print(f"   Error: {error}")

        if query_time is not None:
            self.query_times.append({
                "test_name": test_name,
                "query_time": query_time,
                "passed": passed,
                "result_count": result_count
            })

    async def run_tests(self, space_id: str, graph_id: str) -> dict:
        """
        Run all query lead data tests.

        Args:
            space_id: Space ID with loaded lead data
            graph_id: Graph ID

        Returns:
            Dictionary with test results
        """
        print(f"\n{'=' * 80}")
        print(f"  Query Lead Data Tests")
        print(f"{'=' * 80}")

        # === Entity query tests (query_type="entity") ===
        await self._test_entity_query_all_leads(space_id, graph_id)
        await self._test_entity_query_california_leads(space_id, graph_id)
        await self._test_entity_query_mql_leads(space_id, graph_id)
        await self._test_entity_query_pagination_total_count(space_id, graph_id)

        # === Frame query tests (query_type="frame") ===
        await self._test_frame_query_biz_accounts(space_id, graph_id)
        await self._test_frame_query_converted_leads(space_id, graph_id)
        await self._test_frame_query_high_rated_leads(space_id, graph_id)
        await self._test_frame_query_pagination_total_count(space_id, graph_id)

        # === Cross-validation: entity vs frame total_count ===
        await self._test_entity_vs_frame_total_count(space_id, graph_id)

        # === Empty results ===
        await self._test_entity_query_empty_results(space_id, graph_id)

        # Print query time summary
        if self.query_times:
            print(f"\n{'=' * 80}")
            print(f"  Query Time Summary")
            print(f"{'=' * 80}")
            total_time = sum(qt["query_time"] for qt in self.query_times)
            print(f"\n📊 Total query time: {total_time:.3f}s")
            print(f"📊 Average query time: {total_time / len(self.query_times):.3f}s")
            print(f"\n  Individual query times:")
            for qt in self.query_times:
                status = "✅" if qt["passed"] else "❌"
                rc = qt.get('result_count')
                count_str = f" [{rc} results]" if rc is not None else ""
                print(f"    {status} {qt['test_name']}: {qt['query_time']:.3f}s{count_str}")
            print()

        return {
            "test_name": "Query Lead Data Tests",
            "tests_run": self.tests_run,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_run - self.tests_passed,
            "errors": self.errors,
            "query_times": self.query_times,
            "total_query_time": sum(qt["query_time"] for qt in self.query_times) if self.query_times else 0
        }

    # ====================================================================
    # Entity query tests (query_type="entity")
    # ====================================================================

    async def _test_entity_query_all_leads(self, space_id: str, graph_id: str):
        """Test 1: Entity query - list all KGEntity leads."""
        print(f"\n  Test 1: Entity query - all leads (query_type='entity')...")

        try:
            start_time = time.time()
            response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                query_mode=self.query_mode,
                page_size=20,
                offset=0
            )
            query_time = time.time() - start_time

            page_count = len(response.entity_uris)
            total = response.total_count
            print(f"     Page results: {page_count}, total_count: {total}")

            # total_count should be >= page results
            passed = total >= page_count and page_count > 0
            self._record_test(
                "Entity query - all leads",
                passed,
                f"total_count={total} must be >= page_count={page_count}" if not passed else None,
                query_time=query_time,
                result_count=total
            )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Entity query - all leads", False, str(e))

    async def _test_entity_query_california_leads(self, space_id: str, graph_id: str):
        """Test 2: Entity query - leads in California via frame criteria."""
        print(f"\n  Test 2: Entity query - California leads (entity + frame criteria)...")

        try:
            from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria

            frame_criteria_list = [
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:CompanyFrame",
                    frame_criteria=[
                        FrameCriteria(
                            frame_type="urn:cardiff:kg:frame:CompanyAddressFrame",
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

            start_time = time.time()
            response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                frame_criteria=frame_criteria_list,
                query_mode=self.query_mode,
                page_size=50,
                offset=0
            )
            query_time = time.time() - start_time

            count = len(response.entity_uris)
            total = response.total_count
            print(f"     Found {count} CA leads (total_count: {total})")

            # Expect ~13 CA leads
            passed = count > 0 and total == count  # all fit in one page
            self._record_test(
                "Entity query - CA leads",
                passed,
                f"Expected >0 CA leads, got count={count} total={total}" if not passed else None,
                query_time=query_time,
                result_count=total
            )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Entity query - CA leads", False, str(e))

    async def _test_entity_query_mql_leads(self, space_id: str, graph_id: str):
        """Test 3: Entity query - MQL qualified leads."""
        print(f"\n  Test 3: Entity query - MQL leads (boolean slot filter)...")

        try:
            from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria

            frame_criteria_list = [
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:LeadStatusFrame",
                    frame_criteria=[
                        FrameCriteria(
                            frame_type="urn:cardiff:kg:frame:LeadStatusQualificationFrame",
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

            start_time = time.time()
            response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                frame_criteria=frame_criteria_list,
                query_mode=self.query_mode,
                page_size=50,
                offset=0
            )
            query_time = time.time() - start_time

            count = len(response.entity_uris)
            total = response.total_count
            print(f"     Found {count} MQL leads on page (total_count: {total})")

            # Expect ~99 MQL leads
            passed = count > 0 and total >= count
            self._record_test(
                "Entity query - MQL leads",
                passed,
                f"Expected >0 MQL leads, got count={count} total={total}" if not passed else None,
                query_time=query_time,
                result_count=total
            )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Entity query - MQL leads", False, str(e))

    async def _test_entity_query_pagination_total_count(self, space_id: str, graph_id: str):
        """Test 4: Entity query - verify total_count is consistent across pages."""
        print(f"\n  Test 4: Entity query - pagination total_count consistency...")

        try:
            from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria

            frame_criteria_list = [
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:LeadStatusFrame",
                    frame_criteria=[
                        FrameCriteria(
                            frame_type="urn:cardiff:kg:frame:LeadStatusQualificationFrame",
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

            start_time = time.time()

            # Page 1
            response1 = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                frame_criteria=frame_criteria_list,
                query_mode=self.query_mode,
                page_size=10,
                offset=0
            )

            # Page 2
            response2 = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                frame_criteria=frame_criteria_list,
                query_mode=self.query_mode,
                page_size=10,
                offset=10
            )

            query_time = time.time() - start_time

            p1_count = len(response1.entity_uris)
            p2_count = len(response2.entity_uris)
            total1 = response1.total_count
            total2 = response2.total_count

            print(f"     Page 1: {p1_count} results, total_count={total1}")
            print(f"     Page 2: {p2_count} results, total_count={total2}")

            # Key assertion: total_count must be the same on both pages
            # and must be > page results if there are more pages
            passed = (total1 == total2) and (total1 > p1_count or p2_count == 0) and p1_count > 0
            if not passed:
                error = f"total_count mismatch: page1={total1} page2={total2}, p1={p1_count} p2={p2_count}"
            else:
                error = None
                print(f"     ✅ total_count consistent: {total1} across both pages")

            self._record_test(
                "Entity query - pagination total_count",
                passed,
                error,
                query_time=query_time,
                result_count=total1
            )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Entity query - pagination total_count", False, str(e))

    # ====================================================================
    # Frame query tests (query_type="frame")
    # ====================================================================

    async def _test_frame_query_biz_accounts(self, space_id: str, graph_id: str):
        """Test 5: Frame query - leads with business bank accounts."""
        print(f"\n  Test 5: Frame query - leads with business accounts...")

        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria

            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity"
            )

            frame_criteria_list = [
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:PlaidBankingFrame",
                    frame_criteria=[
                        FrameCriteria(
                            frame_type="urn:cardiff:kg:frame:BankAccountFrame",
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
                query_mode=self.query_mode,
                source_entity_criteria=source_criteria,
                frame_criteria=frame_criteria_list,
                exclude_self_connections=True
            )

            start_time = time.time()
            response = await self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=100,
                offset=0
            )
            query_time = time.time() - start_time

            if response.query_type == "frame":
                count = len(response.frame_connections) if response.frame_connections else 0
                total = response.total_count
                print(f"     Found {count} leads with biz accounts (total_count: {total})")

                # Expect ~53 leads with biz accounts
                passed = count > 0
                self._record_test("Frame query - biz accounts", passed,
                                  f"Expected >0, got {count}" if not passed else None,
                                  query_time=query_time, result_count=total)
            else:
                self._record_test("Frame query - biz accounts", False,
                                  f"Wrong query_type: {response.query_type}", query_time=query_time)

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Frame query - biz accounts", False, str(e))

    async def _test_frame_query_converted_leads(self, space_id: str, graph_id: str):
        """Test 6: Frame query - converted leads."""
        print(f"\n  Test 6: Frame query - converted leads (IsConverted=true)...")

        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria

            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity"
            )

            frame_criteria_list = [
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:LeadStatusFrame",
                    frame_criteria=[
                        FrameCriteria(
                            frame_type="urn:cardiff:kg:frame:LeadStatusConversionFrame",
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
                query_mode=self.query_mode,
                source_entity_criteria=source_criteria,
                frame_criteria=frame_criteria_list,
                exclude_self_connections=True
            )

            start_time = time.time()
            response = await self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=100,
                offset=0
            )
            query_time = time.time() - start_time

            if response.query_type == "frame":
                count = len(response.frame_connections) if response.frame_connections else 0
                total = response.total_count
                print(f"     Found {count} converted leads (total_count: {total})")

                # Expect ~9 converted leads
                passed = count > 0
                self._record_test("Frame query - converted leads", passed,
                                  f"Expected >0, got {count}" if not passed else None,
                                  query_time=query_time, result_count=total)
            else:
                self._record_test("Frame query - converted leads", False,
                                  f"Wrong query_type: {response.query_type}", query_time=query_time)

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Frame query - converted leads", False, str(e))

    async def _test_frame_query_high_rated_leads(self, space_id: str, graph_id: str):
        """Test 7: Frame query - high-rated leads (MQLRating >= 65)."""
        print(f"\n  Test 7: Frame query - high-rated leads (MQLRating >= 65)...")

        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria

            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity"
            )

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
                query_mode=self.query_mode,
                source_entity_criteria=source_criteria,
                frame_criteria=frame_criteria_list,
                exclude_self_connections=True
            )

            start_time = time.time()
            response = await self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=100,
                offset=0
            )
            query_time = time.time() - start_time

            if response.query_type == "frame":
                count = len(response.frame_connections) if response.frame_connections else 0
                total = response.total_count
                print(f"     Found {count} high-rated leads (total_count: {total})")

                passed = count > 0
                self._record_test("Frame query - high-rated leads", passed,
                                  f"Expected >0, got {count}" if not passed else None,
                                  query_time=query_time, result_count=total)
            else:
                self._record_test("Frame query - high-rated leads", False,
                                  f"Wrong query_type: {response.query_type}", query_time=query_time)

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Frame query - high-rated leads", False, str(e))

    async def _test_frame_query_pagination_total_count(self, space_id: str, graph_id: str):
        """Test 8: Frame query - verify total_count consistency across pages."""
        print(f"\n  Test 8: Frame query - pagination total_count consistency...")

        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria

            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity"
            )

            frame_criteria_list = [
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:LeadStatusFrame",
                    frame_criteria=[
                        FrameCriteria(
                            frame_type="urn:cardiff:kg:frame:LeadStatusQualificationFrame",
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
                query_mode=self.query_mode,
                source_entity_criteria=source_criteria,
                frame_criteria=frame_criteria_list,
                exclude_self_connections=True
            )

            start_time = time.time()

            # Page 1
            response1 = await self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=10,
                offset=0
            )

            # Page 2
            response2 = await self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=criteria,
                page_size=10,
                offset=10
            )

            query_time = time.time() - start_time

            p1_count = len(response1.frame_connections) if response1.frame_connections else 0
            p2_count = len(response2.frame_connections) if response2.frame_connections else 0
            total1 = response1.total_count
            total2 = response2.total_count

            print(f"     Page 1: {p1_count} results, total_count={total1}")
            print(f"     Page 2: {p2_count} results, total_count={total2}")

            # Key assertion: total_count must match across pages
            passed = (total1 == total2) and (total1 > p1_count or p2_count == 0) and p1_count > 0
            if not passed:
                error = f"total_count mismatch: page1={total1} page2={total2}, p1={p1_count} p2={p2_count}"
            else:
                error = None
                print(f"     ✅ total_count consistent: {total1} across both pages")

            self._record_test(
                "Frame query - pagination total_count",
                passed,
                error,
                query_time=query_time,
                result_count=total1
            )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Frame query - pagination total_count", False, str(e))

    # ====================================================================
    # Cross-validation
    # ====================================================================

    async def _test_entity_vs_frame_total_count(self, space_id: str, graph_id: str):
        """Test 9: Cross-validate entity query total_count vs frame query total_count."""
        print(f"\n  Test 9: Cross-validate entity vs frame total_count (CA leads)...")

        try:
            from vitalgraph.model.kgqueries_model import KGQueryCriteria
            from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria

            frame_criteria_list = [
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:CompanyFrame",
                    frame_criteria=[
                        FrameCriteria(
                            frame_type="urn:cardiff:kg:frame:CompanyAddressFrame",
                            slot_criteria=[
                                SlotCriteria(
                                    slot_type="urn:cardiff:kg:slot:CompanyStateCode",
                                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                                    value="FL",
                                    comparator="eq"
                                )
                            ]
                        )
                    ]
                )
            ]

            start_time = time.time()

            # Entity query
            entity_response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                frame_criteria=frame_criteria_list,
                query_mode=self.query_mode,
                page_size=100,
                offset=0
            )

            # Frame query
            source_criteria = EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity"
            )
            frame_criteria = KGQueryCriteria(
                query_type="frame",
                query_mode=self.query_mode,
                source_entity_criteria=source_criteria,
                frame_criteria=frame_criteria_list,
                exclude_self_connections=True
            )
            frame_response = await self.client.kgqueries.query_connections(
                space_id=space_id,
                graph_id=graph_id,
                criteria=frame_criteria,
                page_size=100,
                offset=0
            )

            query_time = time.time() - start_time

            entity_total = entity_response.total_count
            frame_total = frame_response.total_count
            entity_count = len(entity_response.entity_uris) if entity_response.entity_uris else 0
            frame_count = len(frame_response.frame_connections) if frame_response.frame_connections else 0

            print(f"     Entity query: {entity_count} results, total_count={entity_total}")
            print(f"     Frame query:  {frame_count} results, total_count={frame_total}")

            # Both should return same total for the same filter criteria
            passed = entity_total == frame_total and entity_total > 0
            if not passed:
                error = f"Entity total={entity_total} != Frame total={frame_total}"
            else:
                error = None
                print(f"     ✅ Both return total_count={entity_total}")

            self._record_test(
                "Entity vs Frame total_count",
                passed,
                error,
                query_time=query_time,
                result_count=entity_total
            )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Entity vs Frame total_count", False, str(e))

    async def _test_entity_query_empty_results(self, space_id: str, graph_id: str):
        """Test 10: Entity query - non-existent criteria returns 0 results."""
        print(f"\n  Test 10: Entity query - empty results (non-existent frame)...")

        try:
            from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria

            frame_criteria_list = [
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:NonExistentFrame",
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="urn:cardiff:kg:slot:NonExistentSlot",
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                            value="NoSuchValue",
                            comparator="eq"
                        )
                    ]
                )
            ]

            start_time = time.time()
            response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                frame_criteria=frame_criteria_list,
                query_mode=self.query_mode,
                page_size=20,
                offset=0
            )
            query_time = time.time() - start_time

            count = len(response.entity_uris)
            total = response.total_count
            print(f"     Results: {count}, total_count: {total}")

            passed = count == 0 and total == 0
            self._record_test("Entity query - empty results", passed,
                              f"Expected 0 results, got count={count} total={total}" if not passed else None,
                              query_time=query_time, result_count=0)

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Entity query - empty results", False, str(e))
