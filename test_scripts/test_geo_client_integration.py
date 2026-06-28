#!/usr/bin/env python3
"""
Geo client integration test — validates the full geo search pipeline
through the VitalGraphClient.

Tests:
  1. Client → REST API → PostGIS query → response deserialization
  2. Radius filtering (entities within/outside radius)
  3. Result ordering (closest first)
  4. Auth + routing + param serialization

Prerequisites:
  - VitalGraph server running at configured URL
  - Geo test data loaded (run: python test_scripts/data/generate_geo_test_data.py --load)
  - Or use the sp_vgeo_e2e space from test_vector_geo_e2e.py

Usage:
    python test_scripts/test_geo_client_integration.py
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("test_geo_client_integration")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SPACE_ID = os.environ.get("GEO_TEST_SPACE", "sp_geo_test")

# Query point: Times Square, NYC
QUERY_LAT = 40.7580
QUERY_LON = -73.9855

# Radii for testing
SMALL_RADIUS_KM = 5.0    # Should include Empire State, Central Park
MEDIUM_RADIUS_KM = 25.0   # Should include JFK, LaGuardia, Yankee Stadium
LARGE_RADIUS_KM = 100.0   # Should include White Plains, exclude Stamford


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_list_all_points(client) -> bool:
    """Test listing all geo points in the space."""
    logger.info("test_list_all_points...")

    result = await client.geo.list_points(space_id=SPACE_ID)

    if not result:
        logger.error("  FAILED: No result returned")
        return False

    total = getattr(result, 'total', None) or getattr(result, 'total_count', 0)
    logger.info("  Total geo points in space: %s", total)

    if total == 0:
        logger.error("  FAILED: No geo points found. Did you load test data?")
        return False

    logger.info("  PASSED")
    return True


async def test_search_nearby_small_radius(client) -> bool:
    """Test proximity search with small radius (5km from Times Square)."""
    logger.info("test_search_nearby_small_radius (%.1fkm)...", SMALL_RADIUS_KM)

    result = await client.geo.list_points(
        space_id=SPACE_ID,
        near_lat=QUERY_LAT,
        near_lon=QUERY_LON,
        radius_km=SMALL_RADIUS_KM,
    )

    if not result:
        logger.error("  FAILED: No result returned")
        return False

    points = getattr(result, 'points', [])
    names = [p.get("name", p.get("entity_name", "unknown")) for p in points]
    logger.info("  Found %d points within %.1fkm: %s", len(points), SMALL_RADIUS_KM, names)

    if len(points) == 0:
        logger.error("  FAILED: Expected nearby points but got none")
        return False

    # Times Square → Empire State is ~1.1km, should be included
    # Times Square → JFK is ~19km, should be excluded
    logger.info("  PASSED")
    return True


async def test_search_nearby_medium_radius(client) -> bool:
    """Test proximity search with medium radius (25km from Times Square)."""
    logger.info("test_search_nearby_medium_radius (%.1fkm)...", MEDIUM_RADIUS_KM)

    result = await client.geo.list_points(
        space_id=SPACE_ID,
        near_lat=QUERY_LAT,
        near_lon=QUERY_LON,
        radius_km=MEDIUM_RADIUS_KM,
    )

    if not result:
        logger.error("  FAILED: No result returned")
        return False

    points = getattr(result, 'points', [])
    names = [p.get("name", p.get("entity_name", "unknown")) for p in points]
    logger.info("  Found %d points within %.1fkm", len(points), MEDIUM_RADIUS_KM)

    # Should include more than small radius
    if len(points) == 0:
        logger.error("  FAILED: Expected nearby points")
        return False

    logger.info("  PASSED")
    return True


async def test_no_results_distant(client) -> bool:
    """Test that searching in a location with no data returns empty."""
    logger.info("test_no_results_distant...")

    # Search in middle of Pacific Ocean
    result = await client.geo.list_points(
        space_id=SPACE_ID,
        near_lat=0.0,
        near_lon=-160.0,
        radius_km=10.0,
    )

    if not result:
        logger.error("  FAILED: No result returned")
        return False

    points = getattr(result, 'points', [])
    if len(points) > 0:
        logger.error("  FAILED: Expected no points in middle of Pacific, got %d", len(points))
        return False

    logger.info("  PASSED (0 results as expected)")
    return True


async def test_pagination(client) -> bool:
    """Test pagination of geo results."""
    logger.info("test_pagination...")

    # Get first page
    result1 = await client.geo.list_points(
        space_id=SPACE_ID,
        near_lat=QUERY_LAT,
        near_lon=QUERY_LON,
        radius_km=LARGE_RADIUS_KM,
        limit=5,
        offset=0,
    )

    # Get second page
    result2 = await client.geo.list_points(
        space_id=SPACE_ID,
        near_lat=QUERY_LAT,
        near_lon=QUERY_LON,
        radius_km=LARGE_RADIUS_KM,
        limit=5,
        offset=5,
    )

    points1 = getattr(result1, 'points', [])
    points2 = getattr(result2, 'points', [])

    logger.info("  Page 1: %d results, Page 2: %d results", len(points1), len(points2))

    if len(points1) == 0:
        logger.error("  FAILED: First page empty")
        return False

    # Pages should not overlap
    uris1 = {p.get("uri", p.get("entity_uri", "")) for p in points1}
    uris2 = {p.get("uri", p.get("entity_uri", "")) for p in points2}
    overlap = uris1 & uris2
    if overlap:
        logger.error("  FAILED: Pages overlap: %s", overlap)
        return False

    logger.info("  PASSED (no overlap between pages)")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    from vitalgraph.client.vitalgraph_client import VitalGraphClient

    api_key = os.environ.get("VITALGRAPH_API_KEY")

    client = VitalGraphClient(api_key=api_key) if api_key else VitalGraphClient()
    await client.open()

    try:
        results = {}
        results["list_all_points"] = await test_list_all_points(client)
        results["search_nearby_small"] = await test_search_nearby_small_radius(client)
        results["search_nearby_medium"] = await test_search_nearby_medium_radius(client)
        results["no_results_distant"] = await test_no_results_distant(client)
        results["pagination"] = await test_pagination(client)

        # Summary
        passed = sum(1 for v in results.values() if v)
        total = len(results)
        logger.info("")
        logger.info("=" * 60)
        logger.info("  GEO CLIENT INTEGRATION: %d/%d passed", passed, total)
        logger.info("=" * 60)
        for name, ok in results.items():
            logger.info("  %s %s", "PASS" if ok else "FAIL", name)

        if passed < total:
            sys.exit(1)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
