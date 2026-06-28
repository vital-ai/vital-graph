#!/usr/bin/env python3
"""
KGQuery Property Filter Test Case

Tests Phase 6 entity property filters on the KG query POST endpoint
and Phase 6b list endpoint convenience parameters.

Property Filter Scenarios (KG query POST):
1. Filter by status URI (eq)
2. Filter by status URI (ne / exclude)
3. Filter by name contains
4. Filter by creation time range (gte + lte)
5. Filter by modification time (gt)
6. Combined: property filter + frame filter
7. count_only with property filter

List Endpoint Convenience Parameters:
8. list_kgentities with status filter
9. list_kgentities with created_after
10. list_kgentities with exclude_status

Count Endpoints:
11. count_kgentities — single count
12. batch_count_kgentities — multiple counts
"""

import logging
import time
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class KGQueryPropertyFiltersTester:
    """Test case for Phase 6 entity property filters and Phase 7a count endpoints."""

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
        """Run property filter and count tests."""
        print(f"\n{'=' * 80}")
        print(f"  KGQuery Property Filters & Count Endpoints")
        print(f"{'=' * 80}")

        print(f"\n📊 Running property filter tests on {expected_entity_count} lead entities...")

        # Phase 6a: KG query POST property filters
        await self._test_filter_by_name_contains(space_id, graph_id)
        await self._test_filter_by_status_eq(space_id, graph_id)
        await self._test_filter_by_status_ne(space_id, graph_id)
        await self._test_filter_combined_property_and_frame(space_id, graph_id)
        await self._test_count_only_with_property_filter(space_id, graph_id)

        # Phase 6b: List endpoint convenience parameters
        await self._test_list_with_status_filter(space_id, graph_id)
        await self._test_list_with_exclude_status(space_id, graph_id)

        # Phase 7a: Count endpoints
        await self._test_count_endpoint(space_id, graph_id)
        await self._test_batch_count_endpoint(space_id, graph_id)

        # Print query time summary
        if self.query_times:
            avg_ms = sum(qt["query_time"] for qt in self.query_times) / len(self.query_times) * 1000
            max_ms = max(qt["query_time"] for qt in self.query_times) * 1000
            print(f"\n  ⏱ Query times: avg={avg_ms:.0f}ms, max={max_ms:.0f}ms")

        return {
            "test_name": "KGQuery Property Filters",
            "tests_run": self.tests_run,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_run - self.tests_passed,
            "errors": self.errors,
        }

    # ------------------------------------------------------------------
    # Phase 6a: KG query POST property filters
    # ------------------------------------------------------------------

    async def _test_filter_by_name_contains(self, space_id: str, graph_id: str):
        """Test 1: Filter entities by name contains substring."""
        print(f"\n  Test 1: Filter entities by name CONTAINS ...")

        try:
            from vitalgraph.model.kgentities_model import EntityPropertyFilter

            # First, get a real name substring from the dataset
            baseline = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                query_mode=self.query_mode,
                page_size=1,
                offset=0
            )
            # Use a common letter as a safe substring
            search_val = "a"

            start_time = time.time()
            response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                entity_property_filters=[
                    EntityPropertyFilter(
                        property_uri="http://vital.ai/ontology/vital-core#hasName",
                        operator="contains",
                        value=search_val
                    )
                ],
                query_mode=self.query_mode,
                page_size=100,
                offset=0
            )
            query_time = time.time() - start_time

            entity_uris = response.entity_uris or []
            total = response.total_count
            baseline_total = baseline.total_count
            print(f"     Got {len(entity_uris)} entities (total: {total}, baseline: {baseline_total})")

            # Filtered count should be <= baseline and > 0 (most names contain 'a')
            passed = total <= baseline_total and total > 0
            self._record_test(
                "Property filter: name contains", passed,
                error="" if passed else f"Expected 0 < total <= {baseline_total}, got {total}",
                query_time=query_time, result_count=len(entity_uris)
            )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Property filter: name contains", False, error=str(e))

    async def _test_filter_by_status_eq(self, space_id: str, graph_id: str):
        """Test 2: Filter entities by status URI eq."""
        print(f"\n  Test 2: Filter entities by status URI (eq) ...")

        try:
            from vitalgraph.model.kgentities_model import EntityPropertyFilter

            # First get baseline count
            baseline = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                query_mode=self.query_mode,
                page_size=1,
                offset=0,
                count_only=True
            )
            baseline_total = baseline.total_count

            start_time = time.time()
            response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                entity_property_filters=[
                    EntityPropertyFilter(
                        property_uri="http://vital.ai/ontology/vital-aimp#hasObjectStatusType",
                        operator="eq",
                        value="http://vital.ai/ontology/vital-aimp#ObjectStatusType_Active"
                    )
                ],
                query_mode=self.query_mode,
                page_size=100,
                offset=0
            )
            query_time = time.time() - start_time

            total = response.total_count
            print(f"     Filtered: {total} / baseline: {baseline_total}")

            # Filtered count should be <= baseline (could be 0 if no active entities)
            passed = total <= baseline_total
            self._record_test(
                "Property filter: status eq", passed,
                error="" if passed else f"Filtered ({total}) > baseline ({baseline_total})",
                query_time=query_time, result_count=total
            )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Property filter: status eq", False, error=str(e))

    async def _test_filter_by_status_ne(self, space_id: str, graph_id: str):
        """Test 3: Filter entities by status URI ne (exclude)."""
        print(f"\n  Test 3: Filter entities by status URI (ne) ...")

        try:
            from vitalgraph.model.kgentities_model import EntityPropertyFilter

            start_time = time.time()
            response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                entity_property_filters=[
                    EntityPropertyFilter(
                        property_uri="http://vital.ai/ontology/vital-aimp#hasObjectStatusType",
                        operator="ne",
                        value="http://vital.ai/ontology/vital-aimp#ObjectStatusType_Deleted"
                    )
                ],
                query_mode=self.query_mode,
                page_size=100,
                offset=0
            )
            query_time = time.time() - start_time

            total = response.total_count
            print(f"     Entities excluding Deleted status: {total}")

            passed = True  # Just verify no error
            self._record_test(
                "Property filter: status ne", passed,
                query_time=query_time, result_count=total
            )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Property filter: status ne", False, error=str(e))

    async def _test_filter_combined_property_and_frame(self, space_id: str, graph_id: str):
        """Test 4: Combine entity property filter with frame criteria."""
        print(f"\n  Test 4: Combined property filter + frame criteria ...")

        try:
            from vitalgraph.model.kgentities_model import EntityPropertyFilter, FrameCriteria, SlotCriteria

            start_time = time.time()
            response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                entity_property_filters=[
                    EntityPropertyFilter(
                        property_uri="http://vital.ai/ontology/vital-core#hasName",
                        operator="contains",
                        value="Lead"
                    )
                ],
                frame_criteria=[
                    FrameCriteria(
                        frame_type="http://vital.ai/ontology/haley-ai-kg#KGFrame",
                        slot_criteria=[
                            SlotCriteria(
                                slot_type="http://vital.ai/ontology/haley-ai-kg#KGSlot",
                                slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot",
                                comparator="eq",
                                value="true"
                            )
                        ]
                    )
                ],
                query_mode=self.query_mode,
                page_size=100,
                offset=0
            )
            query_time = time.time() - start_time

            total = response.total_count
            print(f"     Combined filter results: {total}")

            passed = True  # Verify no error
            self._record_test(
                "Combined property + frame filter", passed,
                query_time=query_time, result_count=total
            )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Combined property + frame filter", False, error=str(e))

    async def _test_count_only_with_property_filter(self, space_id: str, graph_id: str):
        """Test 5: count_only=True with property filter."""
        print(f"\n  Test 5: count_only with property filter ...")

        try:
            from vitalgraph.model.kgentities_model import EntityPropertyFilter

            start_time = time.time()
            response = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                entity_property_filters=[
                    EntityPropertyFilter(
                        property_uri="http://vital.ai/ontology/vital-core#hasName",
                        operator="contains",
                        value="a"
                    )
                ],
                query_mode=self.query_mode,
                page_size=10,
                offset=0,
                count_only=True
            )
            query_time = time.time() - start_time

            total = response.total_count
            entity_uris = response.entity_uris or []
            print(f"     count_only total: {total}, entity_uris returned: {len(entity_uris)}")

            # count_only should return total but empty entity_uris
            passed = total > 0 and len(entity_uris) == 0
            self._record_test(
                "count_only with property filter", passed,
                error="" if passed else f"Expected total>0 and empty uris, got total={total} uris={len(entity_uris)}",
                query_time=query_time, result_count=total
            )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("count_only with property filter", False, error=str(e))

    # ------------------------------------------------------------------
    # Phase 6b: List endpoint convenience parameters
    # ------------------------------------------------------------------

    async def _test_list_with_status_filter(self, space_id: str, graph_id: str):
        """Test 6: list_kgentities with status filter."""
        print(f"\n  Test 6: list_kgentities with status filter ...")

        try:
            start_time = time.time()
            response = await self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=10,
                offset=0,
                status="http://vital.ai/ontology/vital-aimp#ObjectStatusType_Active"
            )
            query_time = time.time() - start_time

            print(f"     list with status filter returned successfully (time: {query_time:.3f}s)")

            passed = True  # No exception = pass (may return 0 if no matching status)
            self._record_test(
                "List with status filter", passed,
                query_time=query_time
            )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("List with status filter", False, error=str(e))

    async def _test_list_with_exclude_status(self, space_id: str, graph_id: str):
        """Test 7: list_kgentities with exclude_status."""
        print(f"\n  Test 7: list_kgentities with exclude_status ...")

        try:
            start_time = time.time()
            response = await self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=10,
                offset=0,
                exclude_status="http://vital.ai/ontology/vital-aimp#ObjectStatusType_Deleted"
            )
            query_time = time.time() - start_time

            print(f"     list with exclude_status returned successfully (time: {query_time:.3f}s)")

            passed = True
            self._record_test(
                "List with exclude_status", passed,
                query_time=query_time
            )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("List with exclude_status", False, error=str(e))

    # ------------------------------------------------------------------
    # Phase 7a: Count endpoints
    # ------------------------------------------------------------------

    async def _test_count_endpoint(self, space_id: str, graph_id: str):
        """Test 8: GET /kgentities/count."""
        print(f"\n  Test 8: count_kgentities endpoint ...")

        try:
            start_time = time.time()
            count = await self.client.kgentities.count_kgentities(
                space_id=space_id,
                graph_id=graph_id,
            )
            query_time = time.time() - start_time

            print(f"     Total entity count: {count} (time: {query_time:.3f}s)")

            passed = isinstance(count, int) and count >= 0
            self._record_test(
                "Count endpoint (total)", passed,
                error="" if passed else f"Expected int >= 0, got {count}",
                query_time=query_time, result_count=count
            )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Count endpoint (total)", False, error=str(e))

    async def _test_batch_count_endpoint(self, space_id: str, graph_id: str):
        """Test 9: POST /kgentities/counts (batch)."""
        print(f"\n  Test 9: batch_count_kgentities endpoint ...")

        try:
            start_time = time.time()
            results = await self.client.kgentities.batch_count_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                count_requests=[
                    {"label": "all"},
                    {"label": "name_has_lead", "search": "Lead"},
                ]
            )
            query_time = time.time() - start_time

            print(f"     Batch results: {results}")

            passed = (
                isinstance(results, list)
                and len(results) == 2
                and all("label" in r and "count" in r for r in results)
            )
            self._record_test(
                "Batch count endpoint", passed,
                error="" if passed else f"Unexpected shape: {results}",
                query_time=query_time
            )

        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Batch count endpoint", False, error=str(e))
