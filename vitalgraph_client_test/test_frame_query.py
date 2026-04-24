#!/usr/bin/env python3
"""
Frame Query (query_type="frame_query") Smoke Test

Tests the new frame_query endpoint against the lead dataset.
The lead dataset has frames with text/boolean/double slots but no entity slots,
so entity_refs will be empty. This validates the endpoint plumbing, pagination,
and response shape.

Usage:
    /opt/homebrew/anaconda3/envs/vital-graph/bin/python vitalgraph_client_test/test_frame_query.py
"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Load .env
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria


SPACE_ID = "space_lead_dataset_test"
GRAPH_ID = "urn:lead_entity_graph_dataset"


class FrameQueryTester:
    """Smoke tests for query_type='frame_query'."""

    def __init__(self, client):
        self.client = client
        self.tests_run = 0
        self.tests_passed = 0
        self.errors = []

    def _record(self, name: str, passed: bool, error: str = None, ms: float = None):
        self.tests_run += 1
        if passed:
            self.tests_passed += 1
            suffix = f" ({ms:.0f}ms)" if ms else ""
            print(f"  ✅ {name}{suffix}")
        else:
            self.errors.append(error or name)
            print(f"  ❌ {name}")
            if error:
                print(f"     {error}")

    async def run_all(self) -> bool:
        print(f"\n{'=' * 70}")
        print(f"  Frame Query Smoke Tests (query_type='frame_query')")
        print(f"  Space: {SPACE_ID}  Graph: {GRAPH_ID}")
        print(f"{'=' * 70}\n")

        await self.test_basic_frame_query()
        await self.test_frame_query_with_frame_type_filter()
        await self.test_frame_query_pagination()
        await self.test_frame_query_empty_results()
        await self.test_response_shape()

        print(f"\n{'=' * 70}")
        passed = self.tests_passed == self.tests_run
        print(f"  {'✅ ALL PASSED' if passed else '❌ SOME FAILED'}: "
              f"{self.tests_passed}/{self.tests_run}")
        print(f"{'=' * 70}\n")
        return passed

    async def test_basic_frame_query(self):
        """Test 1: Basic frame query — find all LeadStatusFrame frames."""
        try:
            t0 = time.time()
            response = await self.client.kgqueries.query_frames(
                space_id=SPACE_ID,
                graph_id=GRAPH_ID,
                frame_type="urn:cardiff:kg:frame:LeadStatusFrame",
                page_size=10,
                offset=0
            )
            ms = (time.time() - t0) * 1000

            ok = (response.results is not None
                  and len(response.results) > 0
                  and response.total_count > 0)
            self._record(
                f"Basic frame query: {len(response.results or [])} frames, "
                f"total={response.total_count}",
                ok,
                f"results={response.results}" if not ok else None,
                ms=ms
            )
        except Exception as e:
            self._record("Basic frame query", False, str(e))

    async def test_frame_query_with_frame_type_filter(self):
        """Test 2: Frame query filtering by frame_type — CompanyFrame vs LeadStatusFrame."""
        try:
            t0 = time.time()
            r_company = await self.client.kgqueries.query_frames(
                space_id=SPACE_ID,
                graph_id=GRAPH_ID,
                frame_type="urn:cardiff:kg:frame:CompanyFrame",
                page_size=10,
                offset=0
            )
            r_status = await self.client.kgqueries.query_frames(
                space_id=SPACE_ID,
                graph_id=GRAPH_ID,
                frame_type="urn:cardiff:kg:frame:LeadStatusFrame",
                page_size=10,
                offset=0
            )
            ms = (time.time() - t0) * 1000

            # Both should return results, and totals should differ
            c_count = r_company.total_count
            s_count = r_status.total_count
            ok = (c_count > 0 and s_count > 0
                  and r_company.results is not None
                  and r_status.results is not None)
            self._record(
                f"Frame type filter: CompanyFrame={c_count}, LeadStatusFrame={s_count}",
                ok,
                f"Expected >0 for both types, got company={c_count} status={s_count}" if not ok else None,
                ms=ms
            )
        except Exception as e:
            self._record("Frame type filter", False, str(e))

    async def test_frame_query_pagination(self):
        """Test 3: Pagination — total_count consistent across pages."""
        try:
            t0 = time.time()
            r1 = await self.client.kgqueries.query_frames(
                space_id=SPACE_ID,
                graph_id=GRAPH_ID,
                frame_type="urn:cardiff:kg:frame:LeadStatusFrame",
                page_size=5,
                offset=0
            )
            r2 = await self.client.kgqueries.query_frames(
                space_id=SPACE_ID,
                graph_id=GRAPH_ID,
                frame_type="urn:cardiff:kg:frame:LeadStatusFrame",
                page_size=5,
                offset=5
            )
            ms = (time.time() - t0) * 1000

            p1 = len(r1.results or [])
            p2 = len(r2.results or [])
            ok = (r1.total_count == r2.total_count
                  and r1.total_count > p1
                  and p1 == 5
                  and p2 > 0)
            self._record(
                f"Pagination: page1={p1}, page2={p2}, total={r1.total_count}/{r2.total_count}",
                ok,
                f"total_count mismatch: {r1.total_count} vs {r2.total_count}" if not ok else None,
                ms=ms
            )
        except Exception as e:
            self._record("Pagination", False, str(e))

    async def test_frame_query_empty_results(self):
        """Test 4: Non-existent frame type returns 0 results."""
        try:
            t0 = time.time()
            response = await self.client.kgqueries.query_frames(
                space_id=SPACE_ID,
                graph_id=GRAPH_ID,
                frame_type="urn:nonexistent:frame:DoesNotExist",
                page_size=10,
                offset=0
            )
            ms = (time.time() - t0) * 1000

            ok = (response.total_count == 0
                  and len(response.results) == 0)
            self._record(
                f"Empty results: total={response.total_count}",
                ok,
                f"Expected 0 results, got total={response.total_count}" if not ok else None,
                ms=ms
            )
        except Exception as e:
            self._record("Empty results", False, str(e))

    async def test_response_shape(self):
        """Test 5: Response shape — each FrameQueryResult has correct fields."""
        try:
            t0 = time.time()
            response = await self.client.kgqueries.query_frames(
                space_id=SPACE_ID,
                graph_id=GRAPH_ID,
                frame_type="urn:cardiff:kg:frame:LeadStatusFrame",
                page_size=3,
                offset=0
            )
            ms = (time.time() - t0) * 1000

            errors = []
            if not response.results:
                errors.append("No results")
            else:
                for i, fr in enumerate(response.results):
                    if not fr.frame_uri:
                        errors.append(f"result[{i}].frame_uri is empty")
                    if not fr.frame_type_uri:
                        errors.append(f"result[{i}].frame_type_uri is empty")
                    if not isinstance(fr.entity_refs, list):
                        errors.append(f"result[{i}].entity_refs is not a list")
                    # frame_graph should be None since include_frame_graph=False
                    if fr.frame_graph is not None:
                        errors.append(f"result[{i}].frame_graph should be None")

            ok = len(errors) == 0
            if ok and response.results:
                fr = response.results[0]
                print(f"     Sample: frame_uri={fr.frame_uri[:60]}...")
                print(f"             frame_type_uri={fr.frame_type_uri}")
                print(f"             entity_refs={fr.entity_refs}")
            self._record(
                f"Response shape: {len(response.results or [])} results checked",
                ok,
                "; ".join(errors) if errors else None,
                ms=ms
            )
        except Exception as e:
            self._record("Response shape", False, str(e))


async def main():
    client = VitalGraphClient()
    await client.open()

    if not client.is_connected():
        logger.error("❌ Connection failed")
        return False

    try:
        tester = FrameQueryTester(client)
        return await tester.run_all()
    finally:
        await client.close()


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
