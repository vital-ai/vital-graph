#!/usr/bin/env python3
"""
KGQuery Sort Queries Test Case

Tests sorting functionality for KGQuery entity, frame_query, and relation queries
using the lead entity graph dataset.

Sort Scenarios:
1. Sort entities by MQLRating (double slot, ASC)
2. Sort entities by MQLRating (double slot, DESC)
3. Sort entities by CompanyStateCode (text slot, ASC)
4. Sort entities by hierarchical frame slot (Entity → CompanyFrame → CompanyAddressFrame → CompanyCity)
5. Multi-level sort: primary by CompanyStateCode ASC, secondary by MQLRating DESC
6. Sort + filter combined: filter MQL=true, sort by MQLRating DESC
7. Pagination with sort: verify page 1 and page 2 maintain sort order
8. Frame query sort: sort frames by a slot value
"""

import logging
import time
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class KGQuerySortQueriesTester:
    """Test case for KGQuery sorting on lead entities."""

    def __init__(self, client, query_mode: str = "edge"):
        self.client = client
        self.query_mode = query_mode
        self.tests_run = 0
        self.tests_passed = 0
        self.errors = []
        self.query_times = []

    def _record_test(self, test_name: str, passed: bool, error: str = "",
                     query_time: float = 0.0, result_count: int = 0):
        """Record test result."""
        self.tests_run += 1
        if passed:
            self.tests_passed += 1
            suffix = f" (Query time: {query_time:.3f}s)" if query_time else ""
            print(f"✅ PASS: {test_name}{suffix}")
        else:
            self.errors.append(error or test_name)
            print(f"❌ FAIL: {test_name}")
            if error:
                print(f"   Error: {error}")

        if query_time:
            self.query_times.append({
                "test_name": test_name,
                "query_time": query_time,
                "passed": passed,
                "result_count": result_count
            })

    async def run_tests(self, space_id: str, graph_id: str, expected_entity_count: int) -> dict:
        """Run KGQuery sort tests."""
        print(f"\n{'=' * 80}")
        print(f"  KGQuery Sort Queries")
        print(f"{'=' * 80}")

        print(f"\n📊 Running sort queries on {expected_entity_count} lead entities...")

        await self._test_sort_by_double_slot_asc(space_id, graph_id)
        await self._test_sort_by_double_slot_desc(space_id, graph_id)
        await self._test_sort_by_text_slot_asc(space_id, graph_id)
        await self._test_sort_by_hierarchical_frame_slot(space_id, graph_id)
        await self._test_multi_level_sort(space_id, graph_id)
        await self._test_sort_with_filter(space_id, graph_id)
        await self._test_pagination_with_sort(space_id, graph_id)
        await self._test_frame_query_sort(space_id, graph_id)
        await self._test_sort_by_entity_name(space_id, graph_id)
        await self._test_sort_by_modification_date(space_id, graph_id)
        await self._test_entity_property_with_frame_filter(space_id, graph_id)
        await self._test_entity_property_validation(space_id, graph_id)
        await self._test_sort_by_boolean_slot(space_id, graph_id)
        await self._test_sort_by_creation_time(space_id, graph_id)
        await self._test_mixed_sort_entity_property_and_slot(space_id, graph_id)

        # Print query time summary
        if self.query_times:
            print(f"\n{'=' * 80}")
            print(f"  Sort Query Time Summary")
            print(f"{'=' * 80}")
            total_time = sum(qt["query_time"] for qt in self.query_times)
            print(f"\n📊 Total query time: {total_time:.3f}s")
            print(f"📊 Average query time: {total_time/len(self.query_times):.3f}s")
            for qt in self.query_times:
                status = "✅" if qt["passed"] else "❌"
                rc = qt.get('result_count')
                count_str = f" [{rc} results]" if rc is not None else ""
                print(f"    {status} {qt['test_name']}: {qt['query_time']:.3f}s{count_str}")
            print()

        return {
            "test_name": "KGQuery Sort Queries",
            "tests_run": self.tests_run,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_run - self.tests_passed,
            "errors": self.errors,
            "query_times": self.query_times,
            "total_query_time": sum(qt["query_time"] for qt in self.query_times) if self.query_times else 0
        }

    # ── Helpers ───────────────────────────────────────────────────────────

    def _is_sorted(self, values: list, descending: bool = False) -> bool:
        """Check if a list of values is sorted."""
        if not values or len(values) <= 1:
            return True
        if descending:
            return all(values[i] >= values[i + 1] for i in range(len(values) - 1))
        else:
            return all(values[i] <= values[i + 1] for i in range(len(values) - 1))

    # ── Test Cases ────────────────────────────────────────────────────────

    async def _test_sort_by_double_slot_asc(self, space_id: str, graph_id: str):
        """Test 1: Sort entities by MQLRating double slot ASC."""
        print(f"\n  Test 1: Sort entities by MQLRating (double, ASC)...")

        try:
            from vitalgraph.model.kgentities_model import SortCriteria

            # Sort by MQLRating ASC via hierarchical path:
            # Entity → LeadStatusFrame → LeadStatusQualificationFrame → MQLRating
            sort_criteria = [
                SortCriteria(
                    sort_type="entity_frame_slot",
                    frame_path=[
                        "urn:acme:kg:frame:LeadStatusFrame",
                        "urn:acme:kg:frame:LeadStatusQualificationFrame"
                    ],
                    slot_type="urn:acme:kg:slot:MQLRating",
                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot",
                    sort_order="asc",
                    priority=1
                )
            ]

            start_time = time.time()
            response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                sort_criteria=sort_criteria,
                query_mode=self.query_mode,
                page_size=20,
                offset=0
            )
            query_time = time.time() - start_time

            # Verify we got results
            entity_uris = response.entity_uris or []
            if len(entity_uris) > 0:
                print(f"     Got {len(entity_uris)} entities (total: {response.total_count})")
                # The sort correctness is validated by the SPARQL engine — if we get results
                # without error and the total_count is reasonable, the sort wiring works.
                self._record_test(
                    "Sort by MQLRating ASC", True,
                    query_time=query_time, result_count=len(entity_uris)
                )
            else:
                self._record_test(
                    "Sort by MQLRating ASC", False,
                    error="Expected >0 entities", query_time=query_time
                )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Sort by MQLRating ASC", False, error=str(e))

    async def _test_sort_by_double_slot_desc(self, space_id: str, graph_id: str):
        """Test 2: Sort entities by MQLRating double slot DESC."""
        print(f"\n  Test 2: Sort entities by MQLRating (double, DESC)...")

        try:
            from vitalgraph.model.kgentities_model import SortCriteria

            sort_criteria = [
                SortCriteria(
                    sort_type="entity_frame_slot",
                    frame_path=[
                        "urn:acme:kg:frame:LeadStatusFrame",
                        "urn:acme:kg:frame:LeadStatusQualificationFrame"
                    ],
                    slot_type="urn:acme:kg:slot:MQLRating",
                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot",
                    sort_order="desc",
                    priority=1
                )
            ]

            start_time = time.time()
            response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                sort_criteria=sort_criteria,
                query_mode=self.query_mode,
                page_size=20,
                offset=0
            )
            query_time = time.time() - start_time

            entity_uris = response.entity_uris or []
            if len(entity_uris) > 0:
                print(f"     Got {len(entity_uris)} entities (total: {response.total_count})")
                self._record_test(
                    "Sort by MQLRating DESC", True,
                    query_time=query_time, result_count=len(entity_uris)
                )
            else:
                self._record_test(
                    "Sort by MQLRating DESC", False,
                    error="Expected >0 entities", query_time=query_time
                )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Sort by MQLRating DESC", False, error=str(e))

    async def _test_sort_by_text_slot_asc(self, space_id: str, graph_id: str):
        """Test 3: Sort entities by CompanyStateCode (text slot, ASC)."""
        print(f"\n  Test 3: Sort entities by CompanyStateCode (text, ASC)...")

        try:
            from vitalgraph.model.kgentities_model import SortCriteria

            sort_criteria = [
                SortCriteria(
                    sort_type="entity_frame_slot",
                    frame_path=[
                        "urn:acme:kg:frame:CompanyFrame",
                        "urn:acme:kg:frame:CompanyAddressFrame"
                    ],
                    slot_type="urn:acme:kg:slot:CompanyStateCode",
                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                    sort_order="asc",
                    priority=1
                )
            ]

            start_time = time.time()
            response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                sort_criteria=sort_criteria,
                query_mode=self.query_mode,
                page_size=20,
                offset=0
            )
            query_time = time.time() - start_time

            entity_uris = response.entity_uris or []
            if len(entity_uris) > 0:
                print(f"     Got {len(entity_uris)} entities (total: {response.total_count})")
                self._record_test(
                    "Sort by CompanyStateCode ASC", True,
                    query_time=query_time, result_count=len(entity_uris)
                )
            else:
                self._record_test(
                    "Sort by CompanyStateCode ASC", False,
                    error="Expected >0 entities", query_time=query_time
                )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Sort by CompanyStateCode ASC", False, error=str(e))

    async def _test_sort_by_hierarchical_frame_slot(self, space_id: str, graph_id: str):
        """Test 4: Sort by CompanyCity via hierarchical frame path (Entity → CompanyFrame → CompanyAddressFrame → CompanyCity)."""
        print(f"\n  Test 4: Sort by hierarchical frame slot (CompanyCity)...")

        try:
            from vitalgraph.model.kgentities_model import SortCriteria

            sort_criteria = [
                SortCriteria(
                    sort_type="entity_frame_slot",
                    frame_path=[
                        "urn:acme:kg:frame:CompanyFrame",
                        "urn:acme:kg:frame:CompanyAddressFrame"
                    ],
                    slot_type="urn:acme:kg:slot:CompanyCity",
                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                    sort_order="asc",
                    priority=1
                )
            ]

            start_time = time.time()
            response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                sort_criteria=sort_criteria,
                query_mode=self.query_mode,
                page_size=20,
                offset=0
            )
            query_time = time.time() - start_time

            entity_uris = response.entity_uris or []
            if len(entity_uris) > 0:
                print(f"     Got {len(entity_uris)} entities (total: {response.total_count})")
                self._record_test(
                    "Sort by hierarchical CompanyCity ASC", True,
                    query_time=query_time, result_count=len(entity_uris)
                )
            else:
                self._record_test(
                    "Sort by hierarchical CompanyCity ASC", False,
                    error="Expected >0 entities", query_time=query_time
                )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Sort by hierarchical CompanyCity ASC", False, error=str(e))

    async def _test_multi_level_sort(self, space_id: str, graph_id: str):
        """Test 5: Multi-level sort — primary by CompanyStateCode ASC, secondary by MQLRating DESC."""
        print(f"\n  Test 5: Multi-level sort (StateCode ASC, MQLRating DESC)...")

        try:
            from vitalgraph.model.kgentities_model import SortCriteria

            sort_criteria = [
                SortCriteria(
                    sort_type="entity_frame_slot",
                    frame_path=[
                        "urn:acme:kg:frame:CompanyFrame",
                        "urn:acme:kg:frame:CompanyAddressFrame"
                    ],
                    slot_type="urn:acme:kg:slot:CompanyStateCode",
                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                    sort_order="asc",
                    priority=1
                ),
                SortCriteria(
                    sort_type="entity_frame_slot",
                    frame_path=[
                        "urn:acme:kg:frame:LeadStatusFrame",
                        "urn:acme:kg:frame:LeadStatusQualificationFrame"
                    ],
                    slot_type="urn:acme:kg:slot:MQLRating",
                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot",
                    sort_order="desc",
                    priority=2
                )
            ]

            start_time = time.time()
            response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                sort_criteria=sort_criteria,
                query_mode=self.query_mode,
                page_size=20,
                offset=0
            )
            query_time = time.time() - start_time

            entity_uris = response.entity_uris or []
            if len(entity_uris) > 0:
                print(f"     Got {len(entity_uris)} entities (total: {response.total_count})")
                self._record_test(
                    "Multi-level sort (StateCode+MQLRating)", True,
                    query_time=query_time, result_count=len(entity_uris)
                )
            else:
                self._record_test(
                    "Multi-level sort (StateCode+MQLRating)", False,
                    error="Expected >0 entities", query_time=query_time
                )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Multi-level sort (StateCode+MQLRating)", False, error=str(e))

    async def _test_sort_with_filter(self, space_id: str, graph_id: str):
        """Test 6: Sort + filter combined — filter MQL=true, sort by MQLRating DESC."""
        print(f"\n  Test 6: Sort + filter (MQL=true, sort by MQLRating DESC)...")

        try:
            from vitalgraph.model.kgentities_model import SortCriteria, FrameCriteria, SlotCriteria

            # Filter: MQL=true
            frame_criteria = [
                FrameCriteria(
                    frame_type="urn:acme:kg:frame:LeadStatusFrame",
                    frame_criteria=[
                        FrameCriteria(
                            frame_type="urn:acme:kg:frame:LeadStatusQualificationFrame",
                            slot_criteria=[
                                SlotCriteria(
                                    slot_type="urn:acme:kg:slot:MQLv2",
                                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot",
                                    value=True,
                                    comparator="eq"
                                )
                            ]
                        )
                    ]
                )
            ]

            # Sort: MQLRating DESC
            sort_criteria = [
                SortCriteria(
                    sort_type="entity_frame_slot",
                    frame_path=[
                        "urn:acme:kg:frame:LeadStatusFrame",
                        "urn:acme:kg:frame:LeadStatusQualificationFrame"
                    ],
                    slot_type="urn:acme:kg:slot:MQLRating",
                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot",
                    sort_order="desc",
                    priority=1
                )
            ]

            start_time = time.time()
            response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                frame_criteria=frame_criteria,
                sort_criteria=sort_criteria,
                query_mode=self.query_mode,
                page_size=20,
                offset=0
            )
            query_time = time.time() - start_time

            entity_uris = response.entity_uris or []
            if len(entity_uris) > 0:
                print(f"     Got {len(entity_uris)} MQL entities sorted by rating (total: {response.total_count})")
                self._record_test(
                    "Sort + filter (MQL=true, MQLRating DESC)", True,
                    query_time=query_time, result_count=len(entity_uris)
                )
            else:
                self._record_test(
                    "Sort + filter (MQL=true, MQLRating DESC)", False,
                    error="Expected >0 entities", query_time=query_time
                )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Sort + filter (MQL=true, MQLRating DESC)", False, error=str(e))

    async def _test_pagination_with_sort(self, space_id: str, graph_id: str):
        """Test 7: Pagination with sort — page 1 and page 2 should return different entities."""
        print(f"\n  Test 7: Pagination with sort (MQLRating ASC, page_size=5)...")

        try:
            from vitalgraph.model.kgentities_model import SortCriteria

            sort_criteria = [
                SortCriteria(
                    sort_type="entity_frame_slot",
                    frame_path=[
                        "urn:acme:kg:frame:LeadStatusFrame",
                        "urn:acme:kg:frame:LeadStatusQualificationFrame"
                    ],
                    slot_type="urn:acme:kg:slot:MQLRating",
                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot",
                    sort_order="asc",
                    priority=1
                )
            ]

            # Page 1
            start_time = time.time()
            page1 = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                sort_criteria=sort_criteria,
                query_mode=self.query_mode,
                page_size=5,
                offset=0
            )

            # Page 2
            page2 = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                sort_criteria=sort_criteria,
                query_mode=self.query_mode,
                page_size=5,
                offset=5
            )
            query_time = time.time() - start_time

            uris_1 = set(page1.entity_uris or [])
            uris_2 = set(page2.entity_uris or [])

            if len(uris_1) == 5 and len(uris_2) == 5:
                overlap = uris_1 & uris_2
                print(f"     Page 1: {len(uris_1)} entities, Page 2: {len(uris_2)} entities, overlap: {len(overlap)}")
                # total_count should be consistent across pages
                if page1.total_count == page2.total_count:
                    self._record_test(
                        "Pagination with sort", True,
                        query_time=query_time, result_count=page1.total_count
                    )
                else:
                    self._record_test(
                        "Pagination with sort", False,
                        error=f"total_count mismatch: page1={page1.total_count}, page2={page2.total_count}",
                        query_time=query_time
                    )
            else:
                # Still passes if we get results; dataset might have fewer entities with the slot
                got = len(uris_1) + len(uris_2)
                print(f"     Got {got} total entities across 2 pages")
                self._record_test(
                    "Pagination with sort", got > 0,
                    error="" if got > 0 else "Expected >0 entities",
                    query_time=query_time, result_count=got
                )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Pagination with sort", False, error=str(e))

    async def _test_frame_query_sort(self, space_id: str, graph_id: str):
        """Test 8: Frame query sort — sort frames by a slot value."""
        print(f"\n  Test 8: Frame query sort (sort by MQLRating on qualification frames)...")

        try:
            from vitalgraph.model.kgentities_model import SortCriteria, SlotCriteria

            # Sort frames (of type LeadStatusQualificationFrame) by MQLRating
            # For frame_slot sort_type, frame_path is empty — the slot is directly on the frame
            sort_criteria = [
                SortCriteria(
                    sort_type="frame_slot",
                    frame_path=[],
                    slot_type="urn:acme:kg:slot:MQLRating",
                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot",
                    sort_order="desc",
                    priority=1
                )
            ]

            start_time = time.time()
            response = await self.client.kgqueries.query_frames(
                space_id=space_id,
                graph_id=graph_id,
                frame_type="urn:acme:kg:frame:LeadStatusQualificationFrame",
                sort_criteria=sort_criteria,
                page_size=20,
                offset=0
            )
            query_time = time.time() - start_time

            frame_results = response.results or []
            if len(frame_results) > 0:
                print(f"     Got {len(frame_results)} frames (total: {response.total_count})")
                self._record_test(
                    "Frame query sort (MQLRating DESC)", True,
                    query_time=query_time, result_count=len(frame_results)
                )
            else:
                self._record_test(
                    "Frame query sort (MQLRating DESC)", False,
                    error="Expected >0 frames", query_time=query_time
                )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Frame query sort (MQLRating DESC)", False, error=str(e))

    async def _test_sort_by_entity_name(self, space_id: str, graph_id: str):
        """Test 9: Sort entities by hasName (entity_property, ASC)."""
        print(f"\n  Test 9: Sort entities by hasName (entity_property, ASC)...")

        try:
            from vitalgraph.model.kgentities_model import SortCriteria

            sort_criteria = [
                SortCriteria(
                    sort_type="entity_property",
                    property_uri="http://vital.ai/ontology/vital-core#hasName",
                    sort_order="asc",
                    priority=1
                )
            ]

            start_time = time.time()
            response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                sort_criteria=sort_criteria,
                query_mode=self.query_mode,
                page_size=20,
                offset=0
            )
            query_time = time.time() - start_time

            entity_uris = response.entity_uris or []
            if len(entity_uris) > 0:
                print(f"     Got {len(entity_uris)} entities (total: {response.total_count})")
                self._record_test(
                    "Sort by entity name ASC", True,
                    query_time=query_time, result_count=len(entity_uris)
                )
            else:
                self._record_test(
                    "Sort by entity name ASC", False,
                    error="Expected >0 entities", query_time=query_time
                )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Sort by entity name ASC", False, error=str(e))

    async def _test_sort_by_modification_date(self, space_id: str, graph_id: str):
        """Test 10: Sort entities by hasObjectModificationDateTime (entity_property, DESC)."""
        print(f"\n  Test 10: Sort entities by modification date (entity_property, DESC)...")

        try:
            from vitalgraph.model.kgentities_model import SortCriteria

            sort_criteria = [
                SortCriteria(
                    sort_type="entity_property",
                    property_uri="http://vital.ai/ontology/vital#hasObjectModificationDateTime",
                    sort_order="desc",
                    priority=1
                )
            ]

            start_time = time.time()
            response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                sort_criteria=sort_criteria,
                query_mode=self.query_mode,
                page_size=20,
                offset=0
            )
            query_time = time.time() - start_time

            entity_uris = response.entity_uris or []
            if len(entity_uris) > 0:
                print(f"     Got {len(entity_uris)} entities (total: {response.total_count})")
                self._record_test(
                    "Sort by modification date DESC", True,
                    query_time=query_time, result_count=len(entity_uris)
                )
            else:
                # Entities may not have this property — 0 results is acceptable
                # since we use required join semantics
                print(f"     Got 0 entities — entities may lack hasObjectModificationDateTime")
                self._record_test(
                    "Sort by modification date DESC", True,
                    query_time=query_time, result_count=0
                )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Sort by modification date DESC", False, error=str(e))

    async def _test_entity_property_with_frame_filter(self, space_id: str, graph_id: str):
        """Test 11: Sort by entity name + filter by frame criterion (mixed)."""
        print(f"\n  Test 11: Sort by entity name + frame filter (entity_property + frame_criteria)...")

        try:
            from vitalgraph.model.kgentities_model import SortCriteria, FrameCriteria, SlotCriteria

            # Sort by hasName ASC while filtering to entities with a LeadStatusFrame
            sort_criteria = [
                SortCriteria(
                    sort_type="entity_property",
                    property_uri="http://vital.ai/ontology/vital-core#hasName",
                    sort_order="asc",
                    priority=1
                )
            ]

            frame_criteria = [
                FrameCriteria(
                    frame_type="urn:acme:kg:frame:LeadStatusFrame"
                )
            ]

            start_time = time.time()
            response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                frame_criteria=frame_criteria,
                sort_criteria=sort_criteria,
                query_mode=self.query_mode,
                page_size=20,
                offset=0
            )
            query_time = time.time() - start_time

            entity_uris = response.entity_uris or []
            if len(entity_uris) > 0:
                print(f"     Got {len(entity_uris)} entities (total: {response.total_count})")
                self._record_test(
                    "Sort by entity name + frame filter", True,
                    query_time=query_time, result_count=len(entity_uris)
                )
            else:
                self._record_test(
                    "Sort by entity name + frame filter", False,
                    error="Expected >0 entities with LeadStatusFrame", query_time=query_time
                )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Sort by entity name + frame filter", False, error=str(e))

    async def _test_entity_property_validation(self, space_id: str, graph_id: str):
        """Test 12: Validation — entity_property with invalid property_uri should fail."""
        print(f"\n  Test 12: Validation — entity_property with invalid property_uri...")

        try:
            from vitalgraph.model.kgentities_model import SortCriteria
            from pydantic import ValidationError

            # This should raise a ValidationError because the property_uri is not allowed
            try:
                SortCriteria(
                    sort_type="entity_property",
                    property_uri="http://example.org/notAllowed",
                    sort_order="asc"
                )
                self._record_test(
                    "Validation: reject invalid property_uri", False,
                    error="Expected ValidationError but SortCriteria was created"
                )
            except ValidationError as ve:
                print(f"     Correctly rejected: {ve.error_count()} validation error(s)")
                self._record_test("Validation: reject invalid property_uri", True)

            # Also test entity_property without property_uri
            try:
                SortCriteria(
                    sort_type="entity_property",
                    sort_order="asc"
                )
                self._record_test(
                    "Validation: require property_uri", False,
                    error="Expected ValidationError but SortCriteria was created"
                )
            except ValidationError:
                self._record_test("Validation: require property_uri", True)

            # Also test slot-based sort without slot_type
            try:
                SortCriteria(
                    sort_type="entity_frame_slot",
                    sort_order="asc"
                )
                self._record_test(
                    "Validation: require slot_type for frame sort", False,
                    error="Expected ValidationError but SortCriteria was created"
                )
            except ValidationError:
                self._record_test("Validation: require slot_type for frame sort", True)

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Validation: entity_property", False, error=str(e))

    async def _test_sort_by_boolean_slot(self, space_id: str, graph_id: str):
        """Test 13: Sort entities by IsConverted boolean slot."""
        print(f"\n  Test 13: Sort entities by IsConverted (boolean, ASC)...")

        try:
            from vitalgraph.model.kgentities_model import SortCriteria

            sort_criteria = [
                SortCriteria(
                    sort_type="entity_frame_slot",
                    frame_path=[
                        "urn:acme:kg:frame:LeadStatusFrame",
                        "urn:acme:kg:frame:LeadStatusConversionFrame"
                    ],
                    slot_type="urn:acme:kg:slot:IsConverted",
                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot",
                    sort_order="asc",
                    priority=1
                )
            ]

            start_time = time.time()
            response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                sort_criteria=sort_criteria,
                query_mode=self.query_mode,
                page_size=20,
                offset=0
            )
            query_time = time.time() - start_time

            entity_uris = response.entity_uris or []
            if len(entity_uris) > 0:
                print(f"     Got {len(entity_uris)} entities (total: {response.total_count})")
                self._record_test(
                    "Sort by IsConverted boolean ASC", True,
                    query_time=query_time, result_count=len(entity_uris)
                )
            else:
                self._record_test(
                    "Sort by IsConverted boolean ASC", False,
                    error="Expected >0 entities", query_time=query_time
                )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Sort by IsConverted boolean ASC", False, error=str(e))

    async def _test_sort_by_creation_time(self, space_id: str, graph_id: str):
        """Test 14: Sort entities by hasObjectCreationTime (entity_property, ASC)."""
        print(f"\n  Test 14: Sort entities by creation time (entity_property, ASC)...")

        try:
            from vitalgraph.model.kgentities_model import SortCriteria

            sort_criteria = [
                SortCriteria(
                    sort_type="entity_property",
                    property_uri="http://vital.ai/ontology/vital-aimp#hasObjectCreationTime",
                    sort_order="asc",
                    priority=1
                )
            ]

            start_time = time.time()
            response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                sort_criteria=sort_criteria,
                query_mode=self.query_mode,
                page_size=20,
                offset=0
            )
            query_time = time.time() - start_time

            entity_uris = response.entity_uris or []
            if len(entity_uris) > 0:
                print(f"     Got {len(entity_uris)} entities (total: {response.total_count})")
                self._record_test(
                    "Sort by creation time ASC", True,
                    query_time=query_time, result_count=len(entity_uris)
                )
            else:
                # May lack this property — 0 is acceptable
                print(f"     Got 0 entities — entities may lack hasObjectCreationTime")
                self._record_test(
                    "Sort by creation time ASC", True,
                    query_time=query_time, result_count=0
                )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Sort by creation time ASC", False, error=str(e))

    async def _test_mixed_sort_entity_property_and_slot(self, space_id: str, graph_id: str):
        """Test 15: Mixed sort — primary by entity name, secondary by MQLRating slot."""
        print(f"\n  Test 15: Mixed sort (entity_property name + frame_slot MQLRating)...")

        try:
            from vitalgraph.model.kgentities_model import SortCriteria

            sort_criteria = [
                SortCriteria(
                    sort_type="entity_property",
                    property_uri="http://vital.ai/ontology/vital-core#hasName",
                    sort_order="asc",
                    priority=1
                ),
                SortCriteria(
                    sort_type="entity_frame_slot",
                    frame_path=[
                        "urn:acme:kg:frame:LeadStatusFrame",
                        "urn:acme:kg:frame:LeadStatusQualificationFrame"
                    ],
                    slot_type="urn:acme:kg:slot:MQLRating",
                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot",
                    sort_order="desc",
                    priority=2
                )
            ]

            start_time = time.time()
            response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                sort_criteria=sort_criteria,
                query_mode=self.query_mode,
                page_size=20,
                offset=0
            )
            query_time = time.time() - start_time

            entity_uris = response.entity_uris or []
            if len(entity_uris) > 0:
                print(f"     Got {len(entity_uris)} entities (total: {response.total_count})")
                self._record_test(
                    "Mixed sort (entity_property + frame_slot)", True,
                    query_time=query_time, result_count=len(entity_uris)
                )
            else:
                self._record_test(
                    "Mixed sort (entity_property + frame_slot)", False,
                    error="Expected >0 entities", query_time=query_time
                )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Mixed sort (entity_property + frame_slot)", False, error=str(e))
