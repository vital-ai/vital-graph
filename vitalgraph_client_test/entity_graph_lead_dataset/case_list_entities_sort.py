#!/usr/bin/env python3
"""
List Entities Sorting Test Case

Tests the sort_by / sort_order query parameters on the list_kgentities endpoint
using the lead entity graph dataset.

Sort Scenarios:
1. Sort by hasName ASC — alphabetical entity name ordering
2. Sort by hasName DESC — reverse alphabetical ordering
3. Sort by hasName with pagination — verify ordering across pages
4. No sort (default) — baseline comparison
5. Invalid sort_by — expect 400 error
"""

import time
from typing import List, Optional


class ListEntitiesSortTester:
    """Test case for list entities sorting functionality."""

    def __init__(self, client):
        self.client = client
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
            print(f"  ✅ PASS: {test_name}{suffix}")
        else:
            self.errors.append(error or test_name)
            print(f"  ❌ FAIL: {test_name}")
            if error:
                print(f"     Error: {error}")
        if query_time is not None:
            self.query_times.append({
                "test_name": test_name,
                "query_time": query_time,
                "passed": passed,
                "result_count": result_count,
            })

    async def run_tests(self, space_id: str, graph_id: str) -> dict:
        """Run all list entities sorting tests."""
        print(f"\n{'=' * 80}")
        print(f"  List Entities Sorting Tests")
        print(f"{'=' * 80}")

        await self._test_sort_by_name_asc(space_id, graph_id)
        await self._test_sort_by_name_desc(space_id, graph_id)
        await self._test_sort_pagination_consistency(space_id, graph_id)
        await self._test_no_sort_baseline(space_id, graph_id)
        await self._test_invalid_sort_by(space_id, graph_id)

        if self.query_times:
            total_time = sum(qt["query_time"] for qt in self.query_times)
            print(f"\n  📊 Total query time: {total_time:.3f}s")
            print(f"  📊 Average: {total_time / len(self.query_times):.3f}s")

        return {
            "test_name": "List Entities Sorting",
            "tests_run": self.tests_run,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_run - self.tests_passed,
            "errors": self.errors,
        }

    # ------------------------------------------------------------------

    async def _test_sort_by_name_asc(self, space_id: str, graph_id: str):
        """Test 1: Sort by hasName ASC."""
        print(f"\n  Test 1: List entities sorted by hasName ASC...")
        try:
            t0 = time.time()
            response = await self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=20,
                offset=0,
                include_entity_graph=False,
                sort_by="http://vital.ai/ontology/vital-core#hasName",
                sort_order="asc",
            )
            qt = time.time() - t0

            from ai_haley_kg_domain.model.KGEntity import KGEntity
            names = []
            if response.is_success and response.objects:
                for obj in response.objects:
                    if isinstance(obj, KGEntity) and hasattr(obj, 'name') and obj.name:
                        names.append(str(obj.name))

            if len(names) >= 2:
                is_sorted = all(names[i] <= names[i + 1] for i in range(len(names) - 1))
                print(f"     Got {len(names)} entities: first='{names[0][:40]}', last='{names[-1][:40]}'")
                self._record_test(
                    "Sort by hasName ASC", is_sorted,
                    error=None if is_sorted else f"Names not in ASC order: {names[:5]}",
                    query_time=qt, result_count=len(names),
                )
            else:
                self._record_test("Sort by hasName ASC", False,
                                  error=f"Expected >=2 entities with names, got {len(names)}",
                                  query_time=qt)
        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Sort by hasName ASC", False, error=str(e))

    async def _test_sort_by_name_desc(self, space_id: str, graph_id: str):
        """Test 2: Sort by hasName DESC."""
        print(f"\n  Test 2: List entities sorted by hasName DESC...")
        try:
            t0 = time.time()
            response = await self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=20,
                offset=0,
                include_entity_graph=False,
                sort_by="http://vital.ai/ontology/vital-core#hasName",
                sort_order="desc",
            )
            qt = time.time() - t0

            from ai_haley_kg_domain.model.KGEntity import KGEntity
            names = []
            if response.is_success and response.objects:
                for obj in response.objects:
                    if isinstance(obj, KGEntity) and hasattr(obj, 'name') and obj.name:
                        names.append(str(obj.name))

            if len(names) >= 2:
                is_sorted = all(names[i] >= names[i + 1] for i in range(len(names) - 1))
                print(f"     Got {len(names)} entities: first='{names[0][:40]}', last='{names[-1][:40]}'")
                self._record_test(
                    "Sort by hasName DESC", is_sorted,
                    error=None if is_sorted else f"Names not in DESC order: {names[:5]}",
                    query_time=qt, result_count=len(names),
                )
            else:
                self._record_test("Sort by hasName DESC", False,
                                  error=f"Expected >=2 entities with names, got {len(names)}",
                                  query_time=qt)
        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Sort by hasName DESC", False, error=str(e))

    async def _test_sort_pagination_consistency(self, space_id: str, graph_id: str):
        """Test 3: Sort by hasName ASC across two pages — last of page 1 <= first of page 2."""
        print(f"\n  Test 3: Sorted pagination consistency (page 1 vs page 2)...")
        try:
            sort_uri = "http://vital.ai/ontology/vital-core#hasName"

            t0 = time.time()
            r1 = await self.client.kgentities.list_kgentities(
                space_id=space_id, graph_id=graph_id,
                page_size=10, offset=0,
                include_entity_graph=False,
                sort_by=sort_uri, sort_order="asc",
            )
            r2 = await self.client.kgentities.list_kgentities(
                space_id=space_id, graph_id=graph_id,
                page_size=10, offset=10,
                include_entity_graph=False,
                sort_by=sort_uri, sort_order="asc",
            )
            qt = time.time() - t0

            from ai_haley_kg_domain.model.KGEntity import KGEntity

            def _names(resp):
                out = []
                if resp.is_success and resp.objects:
                    for obj in resp.objects:
                        if isinstance(obj, KGEntity) and hasattr(obj, 'name') and obj.name:
                            out.append(str(obj.name))
                return out

            names1 = _names(r1)
            names2 = _names(r2)

            if names1 and names2:
                cross_ok = names1[-1] <= names2[0]
                print(f"     Page 1 last: '{names1[-1][:40]}', Page 2 first: '{names2[0][:40]}'")
                self._record_test(
                    "Sorted pagination consistency", cross_ok,
                    error=None if cross_ok else f"Page boundary broken: '{names1[-1]}' > '{names2[0]}'",
                    query_time=qt, result_count=len(names1) + len(names2),
                )
            else:
                self._record_test("Sorted pagination consistency", False,
                                  error=f"Need data on both pages: p1={len(names1)}, p2={len(names2)}",
                                  query_time=qt)
        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Sorted pagination consistency", False, error=str(e))

    async def _test_no_sort_baseline(self, space_id: str, graph_id: str):
        """Test 4: No sort_by — verify default listing still works."""
        print(f"\n  Test 4: Default listing (no sort_by)...")
        try:
            t0 = time.time()
            response = await self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=10,
                offset=0,
                include_entity_graph=False,
            )
            qt = time.time() - t0

            count = len(response.objects) if response.is_success and response.objects else 0
            self._record_test(
                "Default listing (no sort)", count > 0,
                error=f"Expected >0 entities, got {count}" if count == 0 else None,
                query_time=qt, result_count=count,
            )
        except Exception as e:
            print(f"     ❌ Exception: {e}")
            self._record_test("Default listing (no sort)", False, error=str(e))

    async def _test_invalid_sort_by(self, space_id: str, graph_id: str):
        """Test 5: Invalid sort_by property URI — expect 400 error."""
        print(f"\n  Test 5: Invalid sort_by (expect 400 error)...")
        try:
            response = await self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=10,
                offset=0,
                include_entity_graph=False,
                sort_by="http://nonexistent.property/fooBar",
                sort_order="asc",
            )
            # If we get here without error, the server didn't reject it
            self._record_test("Invalid sort_by rejected", False,
                              error="Expected error for invalid sort_by but got success")
        except Exception as e:
            err_str = str(e).lower()
            is_400 = "400" in err_str or "not a sortable property" in err_str or "bad request" in err_str
            self._record_test(
                "Invalid sort_by rejected", is_400,
                error=None if is_400 else f"Expected 400 error, got: {e}",
            )
