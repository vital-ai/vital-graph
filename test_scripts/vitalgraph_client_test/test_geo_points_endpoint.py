#!/usr/bin/env python3
"""
VitalGraph Geo Points Endpoint Integration Test (JWT Client)

Integration test for:
  - List geo points (all)
  - Spatial query (near_lat, near_lon, radius_km)
  - Graph URI filtering
  - Pagination (limit, offset)
  - Error cases (missing spatial params, non-existent space)

Architecture:
  1. Creates a test space via the client
  2. Enables geo config (enabled=True, auto_sync=True)
  3. Creates KGEntities with KGGeoLocationSlot children → triggers auto-sync geo population
  4. Tests the geo points REST endpoint via the client
  5. Cleans up the test space

Usage:
    python vitalgraph_client_test/test_geo_points_endpoint.py
"""

import sys
import logging
import asyncio
import uuid
from pathlib import Path
from typing import Dict, Any, List

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.spaces_model import Space

# VitalSigns model imports
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGGeoLocationSlot import KGGeoLocationSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

TEST_SPACE_ID = "geo_client_test"
TEST_GRAPH_URI = "urn:vitalgraph:geo_client_test:graph1"
BASE_URI = "http://vital.ai/test/geo_client"

# Test locations with known coordinates
TEST_LOCATIONS = [
    {"name": "Times Square", "lat": 40.7580, "lon": -73.9855},
    {"name": "Empire State Building", "lat": 40.7484, "lon": -73.9857},
    {"name": "Central Park", "lat": 40.7829, "lon": -73.9654},
    {"name": "Brooklyn Bridge", "lat": 40.7061, "lon": -73.9969},
    {"name": "JFK Airport", "lat": 40.6413, "lon": -73.7781},
    {"name": "London Tower Bridge", "lat": 51.5055, "lon": -0.0754},
    {"name": "Paris Eiffel Tower", "lat": 48.8584, "lon": 2.2945},
    {"name": "Tokyo Tower", "lat": 35.6586, "lon": 139.7454},
]


def _make_uri(suffix: str) -> str:
    return f"{BASE_URI}/{suffix}"


def create_entity_with_geo(name: str, lat: float, lon: float, idx: int) -> List:
    """Create a KGEntity with a KGGeoLocationSlot containing WKT geo value."""
    slug = name.lower().replace(" ", "_")

    entity = KGEntity()
    entity.URI = _make_uri(f"entity/{slug}")
    entity.name = name

    frame = KGFrame()
    frame.URI = _make_uri(f"frame/{slug}_geo")

    slot = KGGeoLocationSlot()
    slot.URI = _make_uri(f"slot/{slug}_location")
    # WKT: POINT(longitude latitude)
    wkt_value = f"POINT({lon} {lat})"
    slot['http://vital.ai/ontology/haley-ai-kg#hasGeoLocationSlotValue'] = wkt_value

    # Edges
    entity_frame_edge = Edge_hasEntityKGFrame()
    entity_frame_edge.URI = _make_uri(f"edge/{slug}_entity_frame")
    entity_frame_edge.edgeSource = entity.URI
    entity_frame_edge.edgeDestination = frame.URI

    frame_slot_edge = Edge_hasKGSlot()
    frame_slot_edge.URI = _make_uri(f"edge/{slug}_frame_slot")
    frame_slot_edge.edgeSource = frame.URI
    frame_slot_edge.edgeDestination = slot.URI

    return [entity, frame, slot, entity_frame_edge, frame_slot_edge]


class GeoPointsEndpointTester:
    """Integration test runner for geo points endpoint."""

    def __init__(self, client: VitalGraphClient, space_id: str):
        self.client = client
        self.space_id = space_id
        self.results: List[Dict[str, Any]] = []

    def _record(self, name: str, passed: bool, details: str = ""):
        self.results.append({"name": name, "passed": passed, "error": details if not passed else ""})
        status = "✅ PASS" if passed else "❌ FAIL"
        msg = f"   {status}: {name}"
        if details:
            msg += f" — {details}"
        if passed:
            logger.info(msg)
        else:
            logger.error(msg)

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    async def test_list_all_points(self) -> int:
        """List all geo points — should return all populated test entities."""
        try:
            result = await self.client.geo_points.list_points(self.space_id)
            count = result.total_count
            self._record(
                "List all geo points",
                count > 0,
                details=f"total_count={count}, returned={len(result.points)}"
            )
            return count
        except Exception as e:
            self._record("List all geo points", False, details=str(e)[:120])
            return 0

    async def test_spatial_query_nearby(self):
        """Spatial query: 10km from Times Square — should include nearby Manhattan landmarks."""
        try:
            result = await self.client.geo_points.list_points(
                self.space_id,
                near_lat=40.7580,
                near_lon=-73.9855,
                radius_km=10.0,
            )
            count = result.total_count
            uris = [p.subject_uri for p in result.points]

            # Should include Times Square, Empire State, Central Park, Brooklyn Bridge
            # (all within ~10km of Times Square)
            has_results = count >= 3
            # Distances should be populated and ordered ascending
            has_distances = all(p.distance_m is not None for p in result.points)
            distances = [p.distance_m for p in result.points]
            ordered = all(distances[i] <= distances[i + 1] for i in range(len(distances) - 1)) if len(distances) > 1 else True

            passed = has_results and has_distances and ordered
            self._record(
                "Spatial query 10km from Times Square",
                passed,
                details=f"count={count}, has_distances={has_distances}, ordered={ordered}"
            )
        except Exception as e:
            self._record("Spatial query 10km from Times Square", False, details=str(e)[:120])

    async def test_spatial_query_tight_radius(self):
        """Spatial query: 2km from Times Square — only nearest landmarks."""
        try:
            result = await self.client.geo_points.list_points(
                self.space_id,
                near_lat=40.7580,
                near_lon=-73.9855,
                radius_km=2.0,
            )
            has_results = result.total_count > 0
            # All distances should be < 2000m
            within_bound = all(
                p.distance_m is not None and p.distance_m < 2000
                for p in result.points
            )
            # Should NOT include JFK (~20km away)
            no_jfk = not any("jfk" in p.subject_uri.lower() for p in result.points)

            self._record(
                "Spatial query 2km tight radius",
                has_results and within_bound and no_jfk,
                details=f"count={result.total_count}, within_2km={within_bound}, no_jfk={no_jfk}"
            )
        except Exception as e:
            self._record("Spatial query 2km tight radius", False, details=str(e)[:120])

    async def test_spatial_query_excludes_far(self):
        """Spatial query: 500km from NYC — should exclude London/Paris/Tokyo."""
        try:
            result = await self.client.geo_points.list_points(
                self.space_id,
                near_lat=40.7580,
                near_lon=-73.9855,
                radius_km=500.0,
            )
            uris = [p.subject_uri.lower() for p in result.points]
            # Should NOT include London, Paris, or Tokyo
            no_london = not any("london" in u for u in uris)
            no_paris = not any("paris" in u for u in uris)
            no_tokyo = not any("tokyo" in u for u in uris)
            # Should include NYC area (Times Square, Empire State, etc.)
            has_nyc = any("times_square" in u or "empire" in u for u in uris)

            passed = no_london and no_paris and no_tokyo and has_nyc
            self._record(
                "500km radius excludes overseas",
                passed,
                details=f"count={result.total_count}, no_london={no_london}, no_paris={no_paris}, no_tokyo={no_tokyo}"
            )
        except Exception as e:
            self._record("500km radius excludes overseas", False, details=str(e)[:120])

    async def test_graph_uri_filter(self):
        """Filter by graph URI — should return points from that graph."""
        try:
            result = await self.client.geo_points.list_points(
                self.space_id,
                graph_uri=TEST_GRAPH_URI,
            )
            passed = result.total_count > 0
            self._record(
                "Filter by graph URI",
                passed,
                details=f"count={result.total_count}"
            )
        except Exception as e:
            self._record("Filter by graph URI", False, details=str(e)[:120])

    async def test_graph_uri_nonexistent(self):
        """Filter by non-existent graph URI — should return 0 results."""
        try:
            result = await self.client.geo_points.list_points(
                self.space_id,
                graph_uri="urn:nonexistent:graph:xyz",
            )
            passed = result.total_count == 0
            self._record(
                "Non-existent graph URI → 0 results",
                passed,
                details=f"count={result.total_count}"
            )
        except Exception as e:
            self._record("Non-existent graph URI → 0 results", False, details=str(e)[:120])

    async def test_pagination(self):
        """Pagination: limit=3, offset=0, then offset=3."""
        try:
            page1 = await self.client.geo_points.list_points(
                self.space_id, limit=3, offset=0
            )
            page2 = await self.client.geo_points.list_points(
                self.space_id, limit=3, offset=3
            )

            p1_ok = len(page1.points) <= 3
            p1_uris = {p.subject_uri for p in page1.points}
            p2_uris = {p.subject_uri for p in page2.points}
            no_overlap = p1_uris.isdisjoint(p2_uris) if page2.points else True
            same_total = page1.total_count == page2.total_count

            passed = p1_ok and no_overlap and same_total
            self._record(
                "Pagination (limit=3, two pages)",
                passed,
                details=f"page1={len(page1.points)}, page2={len(page2.points)}, total={page1.total_count}, no_overlap={no_overlap}"
            )
        except Exception as e:
            self._record("Pagination (limit=3, two pages)", False, details=str(e)[:120])

    async def test_spatial_partial_params_error(self):
        """Spatial query with incomplete params — should error."""
        try:
            await self.client.geo_points.list_points(
                self.space_id,
                near_lat=40.7580,
            )
            self._record("Incomplete spatial params → error", False, details="No error raised")
        except (VitalGraphClientError, Exception) as e:
            err_msg = str(e).lower()
            passed = "400" in err_msg or "spatial" in err_msg or "requires" in err_msg
            self._record("Incomplete spatial params → error", passed, details=str(e)[:100])

    async def test_nonexistent_space(self):
        """Query non-existent space — should get 404."""
        try:
            await self.client.geo_points.list_points("nonexistent_space_xyz")
            self._record("Non-existent space → 404", False, details="No error raised")
        except (VitalGraphClientError, Exception) as e:
            err_msg = str(e)
            passed = "404" in err_msg or "not found" in err_msg.lower()
            self._record("Non-existent space → 404", passed, details=err_msg[:100])


# ==================================================================
# Main test orchestration
# ==================================================================

async def test_geo_points_endpoint() -> bool:
    """Run geo points endpoint integration tests."""

    logger.info("=" * 80)
    logger.info("Geo Points Endpoint Integration Tests (Client-based)")
    logger.info("=" * 80)

    client = None

    try:
        # 1. Connect
        logger.info("\n1. Connecting to VitalGraph server...")
        client = VitalGraphClient()
        await client.open()
        logger.info("   ✓ Connected")

        # 2. Create test space
        logger.info(f"\n2. Creating test space: {TEST_SPACE_ID}")
        try:
            spaces_response = await client.list_spaces()
            existing = next((s for s in spaces_response.spaces if s.space == TEST_SPACE_ID), None)
            if existing:
                await client.delete_space(TEST_SPACE_ID)
                logger.info("   Deleted existing test space")
        except Exception:
            pass

        await client.add_space(Space(
            space=TEST_SPACE_ID,
            space_name="Geo Client Integration Test",
            space_description="Auto-created for geo points endpoint testing",
            tenant="test_tenant",
        ))
        logger.info(f"   ✓ Space created")

        # 3. Enable geo config
        logger.info("\n3. Enabling geo config (enabled=True, auto_sync=True)...")
        await client.geo_config.update_config(
            TEST_SPACE_ID,
            enabled=True,
            auto_sync=True,
        )
        logger.info("   ✓ Geo config enabled")

        # 4. Create entities with geo slots
        logger.info(f"\n4. Creating {len(TEST_LOCATIONS)} entities with geo locations...")
        all_objects = []
        for i, loc in enumerate(TEST_LOCATIONS):
            objects = create_entity_with_geo(loc["name"], loc["lat"], loc["lon"], i)
            all_objects.extend(objects)

        resp = await client.kgentities.create_kgentities(
            space_id=TEST_SPACE_ID,
            graph_id=TEST_GRAPH_URI,
            objects=all_objects,
        )
        logger.info(f"   ✓ Created {resp.created_count} objects")

        # 5. Wait for auto-sync to populate geo table
        logger.info("\n5. Waiting for geo auto-sync (2s)...")
        await asyncio.sleep(2)

        # 6. Run tests
        tester = GeoPointsEndpointTester(client, TEST_SPACE_ID)

        logger.info("\n6. Running geo endpoint tests...")

        total_count = await tester.test_list_all_points()
        if total_count == 0:
            logger.warning("   ⚠️  No geo points found — auto-sync may not have completed")
            logger.info("   Waiting additional 3s...")
            await asyncio.sleep(3)
            total_count = await tester.test_list_all_points()

        await tester.test_spatial_query_nearby()
        await tester.test_spatial_query_tight_radius()
        await tester.test_spatial_query_excludes_far()
        await tester.test_graph_uri_filter()
        await tester.test_graph_uri_nonexistent()
        await tester.test_pagination()
        await tester.test_spatial_partial_params_error()
        await tester.test_nonexistent_space()

        # 7. Cleanup
        logger.info(f"\n7. Cleanup...")
        try:
            await client.delete_space(TEST_SPACE_ID)
            logger.info("   ✓ Space deleted")
        except Exception as e:
            logger.warning(f"   ⚠️  Cleanup: {e}")

        await client.close()

        # Summary
        passed = sum(1 for r in tester.results if r['passed'])
        failed = [r for r in tester.results if not r['passed']]
        total = len(tester.results)

        logger.info(f"\n{'=' * 80}")
        logger.info(f"📊 Test Summary: {passed}/{total} passed")
        if failed:
            for r in failed:
                logger.error(f"   ❌ {r['name']}: {r.get('error', '')}")
            logger.info(f"\n❌ {len(failed)} test(s) FAILED")
        else:
            logger.info(f"\n🎉 All geo points endpoint tests PASSED!")

        return len(failed) == 0

    except VitalGraphClientError as e:
        logger.error(f"\n❌ Client error: {e}")
        return False
    except Exception as e:
        logger.error(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if client:
            try:
                # Attempt cleanup even on failure
                try:
                    await client.delete_space(TEST_SPACE_ID)
                except Exception:
                    pass
                await client.close()
            except Exception:
                pass


async def main():
    success = await test_geo_points_endpoint()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
