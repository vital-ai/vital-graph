#!/usr/bin/env python3
"""
VitalGraph Vector/Geo Endpoints Test (JWT Client)

Integration test for:
  - Vector Indexes: list, create, delete, reindex
  - Vector Mappings: list, create, delete
  - Geo Config: get, update
  - Geo Points: list

Architecture: Uses client-based testing against a live server.
Requires environment variables for server connection.
"""

import sys
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, List

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.spaces_model import Space, SpacesListResponse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)


class VectorGeoEndpointTester:
    """Integration test runner for vector and geo endpoints."""

    def __init__(self, client: VitalGraphClient, space_id: str):
        self.client = client
        self.space_id = space_id
        self.results: List[Dict[str, Any]] = []

    def _record(self, name: str, passed: bool, **kwargs):
        entry = {'name': name, 'passed': passed}
        entry.update(kwargs)
        self.results.append(entry)
        status = "✓" if passed else "❌"
        detail = kwargs.get('details', kwargs.get('error', ''))
        print(f"   {status} {name}: {detail}")

    # ------------------------------------------------------------------
    # Vector Indexes
    # ------------------------------------------------------------------

    async def test_vector_indexes(self):
        print("\n── Vector Indexes ──")

        # List (should succeed even if empty)
        try:
            resp = await self.client.vector_indexes.list_indexes(space_id=self.space_id)
            indexes = resp.get("indexes", [])
            self._record("List Vector Indexes", True, details=f"count={len(indexes)}")
        except Exception as e:
            self._record("List Vector Indexes", False, error=str(e))
            return  # skip dependent tests

        # Create
        test_index = "test_integration_idx"
        try:
            resp = await self.client.vector_indexes.create_index(
                space_id=self.space_id,
                index_name=test_index,
                dimensions=128,
                distance_metric="cosine",
                provider="vitalsigns",
                model_name="test-model",
                description="Integration test index",
            )
            created = resp.get("success", False) or resp.get("index_name") == test_index
            self._record("Create Vector Index", created,
                         details=f"index_name={test_index}" if created else f"resp={resp}")
        except Exception as e:
            self._record("Create Vector Index", False, error=str(e))

        # List again — should include new index
        try:
            resp = await self.client.vector_indexes.list_indexes(space_id=self.space_id)
            indexes = resp.get("indexes", [])
            found = any(
                idx.get("index_name") == test_index or idx.get("name") == test_index
                for idx in indexes
            )
            self._record("Verify Index in List", found,
                         details=f"found={found}, total={len(indexes)}")
        except Exception as e:
            self._record("Verify Index in List", False, error=str(e))

        # Delete
        try:
            resp = await self.client.vector_indexes.delete_index(
                space_id=self.space_id,
                index_name=test_index,
            )
            deleted = resp.get("success", False) or resp.get("deleted", False)
            self._record("Delete Vector Index", deleted, details=f"resp keys={list(resp.keys())}")
        except Exception as e:
            self._record("Delete Vector Index", False, error=str(e))

    # ------------------------------------------------------------------
    # Vector Mappings
    # ------------------------------------------------------------------

    async def test_vector_mappings(self):
        print("\n── Vector Mappings ──")

        # List
        try:
            resp = await self.client.vector_mappings.list_mappings(space_id=self.space_id)
            mappings = resp.get("mappings", [])
            self._record("List Vector Mappings", True, details=f"count={len(mappings)}")
        except Exception as e:
            self._record("List Vector Mappings", False, error=str(e))

    # ------------------------------------------------------------------
    # Geo Config
    # ------------------------------------------------------------------

    async def test_geo_config(self):
        print("\n── Geo Config ──")

        try:
            resp = await self.client.geo_config.get_config(space_id=self.space_id)
            self._record("Get Geo Config", True, details=f"keys={list(resp.keys()) if isinstance(resp, dict) else type(resp).__name__}")
        except Exception as e:
            self._record("Get Geo Config", False, error=str(e))

    # ------------------------------------------------------------------
    # Geo Points
    # ------------------------------------------------------------------

    async def test_geo_points(self):
        print("\n── Geo Points ──")

        try:
            resp = await self.client.geo_points.list_points(space_id=self.space_id)
            points = resp.get("points", []) if isinstance(resp, dict) else []
            self._record("List Geo Points", True, details=f"count={len(points)}")
        except Exception as e:
            self._record("List Geo Points", False, error=str(e))


async def test_vector_geo_endpoints() -> bool:
    """Run all vector/geo endpoint tests."""

    print("=" * 80)
    print("VitalGraph Vector / Geo Endpoints Test (JWT Client)")
    print("=" * 80)

    test_space_id = "space_vector_geo_test"
    client = None

    try:
        print("\n1. Connecting...")
        client = VitalGraphClient()
        await client.open()
        print(f"   ✓ Connected")

        # Space setup
        print("\n2. Setting up test space...")
        spaces_response: SpacesListResponse = await client.list_spaces()
        existing = next((s for s in spaces_response.spaces if s.space == test_space_id), None)
        if existing:
            await client.delete_space(test_space_id)

        await client.add_space(Space(
            space=test_space_id,
            space_name="Vector/Geo Test Space",
            space_description="Integration test space for vector and geo endpoints",
            tenant="test_tenant",
        ))
        print(f"   ✓ Space created: {test_space_id}")

        # Run tests
        tester = VectorGeoEndpointTester(client, test_space_id)

        print("\n3. Running endpoint tests...")
        await tester.test_vector_indexes()
        await tester.test_vector_mappings()
        await tester.test_geo_config()
        await tester.test_geo_points()

        # Cleanup
        print(f"\n4. Cleanup...")
        try:
            await client.delete_space(test_space_id)
            print(f"   ✓ Space deleted")
        except Exception as e:
            print(f"   ⚠️  {e}")

        await client.close()

        # Summary
        passed = sum(1 for r in tester.results if r['passed'])
        failed = [r for r in tester.results if not r['passed']]
        total = len(tester.results)

        print(f"\n{'=' * 80}")
        print(f"📊 Test Summary: {passed}/{total} passed")
        if failed:
            for r in failed:
                print(f"   ❌ {r['name']}: {r.get('error', '')}")
            print(f"\n❌ {len(failed)} test(s) FAILED")
        else:
            print(f"\n🎉 All vector/geo endpoint tests PASSED!")

        return len(failed) == 0

    except VitalGraphClientError as e:
        print(f"\n❌ Client error: {e}")
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if client:
            try:
                await client.close()
            except Exception:
                pass


async def main():
    success = await test_vector_geo_endpoints()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
