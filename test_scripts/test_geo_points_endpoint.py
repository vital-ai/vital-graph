#!/usr/bin/env python3
"""Test the geo points listing endpoint against a real database.

Uses the test space created by test_vector_geo_e2e.py.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")


async def main():
    import asyncpg
    from test_scripts.test_vector_geo_e2e import setup_test_space, SPACE_ID
    from vitalgraph.endpoint.geo_points_endpoint import GeoPointsEndpoint

    db_host = os.environ.get("LOCAL_DB_HOST", "localhost")
    if db_host == "host.docker.internal":
        db_host = "localhost"
    db_url = "postgresql://{}:{}@{}:{}/{}".format(
        os.environ.get("LOCAL_DB_USERNAME", "postgres"),
        os.environ.get("LOCAL_DB_PASSWORD", ""),
        db_host,
        os.environ.get("LOCAL_DB_PORT", "5432"),
        os.environ.get("LOCAL_DB_NAME", "sparql_sql_graph"),
    )

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)

    # Ensure test data exists
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'sp_vgeo_e2e_geo')"
        )
    if not exists:
        await setup_test_space(pool)

    # Wire up endpoint with a minimal fake app
    class FakePool:
        def __init__(self, p):
            self._pool = p
        async def acquire(self):
            return await self._pool.acquire()
        async def release(self, c):
            await self._pool.release(c)

    class FakeDB:
        def __init__(self, p):
            self.connection_pool = FakePool(p)

    class FakeApp:
        def __init__(self, p):
            self.db_impl = FakeDB(p)

    ep = GeoPointsEndpoint(FakeApp(pool), None)
    fake_user = {"username": "admin", "role": "admin"}

    # Test 1: List all geo points
    print("=" * 60)
    print("  Test 1: List all geo points")
    print("=" * 60)
    result = await ep.list_geo_points(SPACE_ID, fake_user)
    print(f"  total_count: {result.total_count}")
    for p in result.points:
        print(f"    {p.subject_uri}  lat={p.latitude}  lon={p.longitude}")
    assert result.total_count == 5, f"Expected 5, got {result.total_count}"
    print("  PASSED ✅\n")

    # Test 2: Spatial query — within 500km of NYC
    print("=" * 60)
    print("  Test 2: Spatial query (500km from Manhattan)")
    print("=" * 60)
    result = await ep.list_geo_points(
        SPACE_ID, fake_user, near_lat=40.758, near_lon=-73.985, radius_km=500
    )
    print(f"  total_count: {result.total_count}")
    for p in result.points:
        print(f"    {p.subject_uri}  dist={p.distance_m:.0f}m")
    assert result.total_count == 2, f"Expected 2 (NYC+Boston), got {result.total_count}"
    assert "nyc" in result.points[0].subject_uri, "NYC should be closest"
    assert "boston" in result.points[1].subject_uri, "Boston should be second"
    assert result.points[0].distance_m < result.points[1].distance_m, "Should be ordered by distance"
    print("  PASSED ✅\n")

    # Test 3: Spatial query — tight radius (50km from Manhattan, only NYC)
    print("=" * 60)
    print("  Test 3: Tight radius (50km, only NYC)")
    print("=" * 60)
    result = await ep.list_geo_points(
        SPACE_ID, fake_user, near_lat=40.758, near_lon=-73.985, radius_km=50
    )
    print(f"  total_count: {result.total_count}")
    for p in result.points:
        print(f"    {p.subject_uri}  dist={p.distance_m:.0f}m")
    assert result.total_count == 1, f"Expected 1 (only NYC), got {result.total_count}"
    assert "nyc" in result.points[0].subject_uri
    print("  PASSED ✅\n")

    # Test 4: Pagination
    print("=" * 60)
    print("  Test 4: Pagination (limit=2, offset=2)")
    print("=" * 60)
    result = await ep.list_geo_points(SPACE_ID, fake_user, limit=2, offset=2)
    print(f"  total_count: {result.total_count}, returned: {len(result.points)}")
    assert result.total_count == 5, "Total should still be 5"
    assert len(result.points) == 2, f"Expected 2 results, got {len(result.points)}"
    print("  PASSED ✅\n")

    # Summary
    print("=" * 60)
    print("  ALL TESTS PASSED ✅")
    print("=" * 60)

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
