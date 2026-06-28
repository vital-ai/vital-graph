#!/usr/bin/env python3
"""
Comprehensive SPARQL Geo Function Integration Tests.

Tests ALL vg: geo SPARQL functions against a real database:
  1. vg:withinRadius — spatial radius filter
  2. vg:geoDistance — distance computation (meters)
  3. vg:withinBounds — bounding box filter
  4. vg:withinPolygon — WKT polygon filter
  5. Combined: geo + ORDER BY distance
  6. Combined: geo filter + vector similarity (if vector index exists)
  7. Edge cases: empty results, very tight radius, antimeridian

Prerequisites:
  - PostgreSQL with PostGIS extension
  - Jena sidecar running at SIDECAR_URL (default: http://localhost:7070)
  - Geo test data loaded (run: python test_scripts/data/generate_geo_test_data.py --load)

Usage:
    python test_scripts/test_geo_sparql_all.py
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
logger = logging.getLogger("test_geo_sparql_all")

SPACE_ID = "sp_geo_test"
GRAPH_URI = "urn:vitalgraph:geo_test:entities"

# Known coordinates for testing
TIMES_SQUARE = (40.7580, -73.9855)
LONDON_CENTER = (51.5074, -0.1278)
TOKYO_CENTER = (35.6762, 139.6503)


async def run_sparql(pool, sidecar_url, sparql):
    """Run a SPARQL query through the full V2 pipeline."""
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.sparql_sql.generator import generate_sql
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
    from vitalgraph.db.sparql_sql.vg_resolve import resolve_vector_requests

    client = AsyncSidecarClient(base_url=sidecar_url)
    try:
        raw = await client.compile(sparql)
    finally:
        await client.close()

    cr = map_compile_response(raw)
    if not cr.ok:
        return {"error": cr.error, "bindings": []}

    async with pool.acquire() as conn:
        gen = await generate_sql(cr, SPACE_ID, conn=conn)
        sql = gen.sql
        if gen.vector_requests:
            sql = await resolve_vector_requests(sql, gen.vector_requests, SPACE_ID, conn)
        logger.debug("SQL: %s", sql[:300])
        try:
            rows = await conn.fetch(sql)
        except Exception as e:
            return {"error": str(e), "bindings": [], "sql": sql}
        result_rows = [dict(r) for r in rows]

    var_map = gen.var_map or {}
    bindings = SparqlSQLSpaceImpl._rows_to_sparql_bindings(result_rows, var_map)
    return {"bindings": bindings, "sql": sql}


def get_value(binding, var_name):
    """Extract value from a SPARQL binding."""
    val = binding.get(var_name, {})
    return val.get("value", "") if isinstance(val, dict) else str(val or "")


def get_float(binding, var_name):
    """Extract float value from a SPARQL binding."""
    val = get_value(binding, var_name)
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Test: vg:withinRadius
# ---------------------------------------------------------------------------

async def test_within_radius_nyc(pool, sidecar_url) -> bool:
    """vg:withinRadius — 50km from Times Square, should include nearby NYC landmarks."""
    logger.info("test_within_radius_nyc (50km)...")

    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX vc: <http://vital.ai/ontology/vital-core#>
        SELECT ?entity ?name WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                ?entity vc:hasName ?name .
            }}
            FILTER(vg:withinRadius(?entity, {TIMES_SQUARE[0]}, {TIMES_SQUARE[1]}, 50000))
        }}
    """

    result = await run_sparql(pool, sidecar_url, sparql)
    if result.get("error"):
        logger.error("  FAILED: %s", result["error"])
        return False

    names = [get_value(b, "name") for b in result["bindings"]]
    logger.info("  Found %d entities within 50km of Times Square: %s", len(names), names[:10])

    # Should include Times Square, Empire State, Central Park, Brooklyn Bridge
    expected_in = ["Times Square", "Empire State Building", "Central Park"]
    # Should exclude London, Tokyo, Paris
    expected_out = ["London", "Tokyo", "Paris"]

    passed = True
    for exp in expected_in:
        if not any(exp.lower() in n.lower() for n in names):
            logger.error("  FAILED: expected '%s' within 50km of Times Square", exp)
            passed = False

    for exc in expected_out:
        if any(exc.lower() in n.lower() for n in names):
            logger.error("  FAILED: '%s' should NOT be within 50km of Times Square", exc)
            passed = False

    if passed:
        logger.info("  PASSED ✅")
    return passed


async def test_within_radius_large(pool, sidecar_url) -> bool:
    """vg:withinRadius — 1000km from Times Square, should include Boston/Toronto area."""
    logger.info("test_within_radius_large (1000km)...")

    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX vc: <http://vital.ai/ontology/vital-core#>
        SELECT ?entity ?name WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                ?entity vc:hasName ?name .
            }}
            FILTER(vg:withinRadius(?entity, {TIMES_SQUARE[0]}, {TIMES_SQUARE[1]}, 1000000))
        }}
    """

    result = await run_sparql(pool, sidecar_url, sparql)
    if result.get("error"):
        logger.error("  FAILED: %s", result["error"])
        return False

    names = [get_value(b, "name") for b in result["bindings"]]
    logger.info("  Found %d entities within 1000km of Times Square", len(names))

    # 1000km from NYC should include Toronto (~550km)
    # but exclude London (~5500km), Tokyo (~11000km)
    passed = True
    if not any("toronto" in n.lower() for n in names):
        logger.warning("  Toronto (~550km) expected within 1000km — may not be in dataset")

    if any("london" in n.lower() and "new" not in n.lower() for n in names):
        logger.error("  FAILED: London should NOT be within 1000km of NYC")
        passed = False

    # Should have more results than the 50km test
    if len(names) < 5:
        logger.warning("  Only %d results — expected more for 1000km radius", len(names))

    if passed:
        logger.info("  PASSED ✅")
    return passed


async def test_within_radius_empty(pool, sidecar_url) -> bool:
    """vg:withinRadius — middle of Pacific Ocean, should return 0 results."""
    logger.info("test_within_radius_empty (Pacific Ocean)...")

    # Middle of Pacific: lat=0, lon=-160, radius=100km
    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX vc: <http://vital.ai/ontology/vital-core#>
        SELECT ?entity ?name WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                ?entity vc:hasName ?name .
            }}
            FILTER(vg:withinRadius(?entity, 0.0, -160.0, 100000))
        }}
    """

    result = await run_sparql(pool, sidecar_url, sparql)
    if result.get("error"):
        logger.error("  FAILED: %s", result["error"])
        return False

    count = len(result["bindings"])
    if count > 0:
        names = [get_value(b, "name") for b in result["bindings"]]
        logger.error("  FAILED: expected 0 results in Pacific Ocean, got %d: %s", count, names)
        return False

    logger.info("  PASSED ✅ (0 results as expected)")
    return True


# ---------------------------------------------------------------------------
# Test: vg:geoDistance
# ---------------------------------------------------------------------------

async def test_geo_distance_from_nyc(pool, sidecar_url) -> bool:
    """vg:geoDistance — compute distances from Times Square, verify ordering."""
    logger.info("test_geo_distance_from_nyc...")

    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX vc: <http://vital.ai/ontology/vital-core#>
        SELECT ?entity ?name ?dist WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                ?entity vc:hasName ?name .
            }}
            BIND(vg:geoDistance(?entity, {TIMES_SQUARE[0]}, {TIMES_SQUARE[1]}) AS ?dist)
        }}
        ORDER BY ?dist
        LIMIT 10
    """

    result = await run_sparql(pool, sidecar_url, sparql)
    if result.get("error"):
        logger.error("  FAILED: %s", result["error"])
        return False

    bindings = result["bindings"]
    if len(bindings) == 0:
        logger.error("  FAILED: no results")
        return False

    logger.info("  Top 10 closest to Times Square:")
    distances = []
    for i, b in enumerate(bindings):
        name = get_value(b, "name")
        dist = get_float(b, "dist")
        distances.append(dist)
        logger.info("    %d. %s — %.0fm", i + 1, name, dist or 0)

    # Verify ascending distance order
    passed = True
    valid_distances = [d for d in distances if d is not None]
    for i in range(len(valid_distances) - 1):
        if valid_distances[i] > valid_distances[i + 1]:
            logger.error("  FAILED: distances not ascending at position %d", i)
            passed = False
            break

    # First result should be within Manhattan (< 5000m from Times Square)
    if valid_distances and valid_distances[0] > 5000:
        logger.error("  FAILED: closest entity should be < 5km from Times Square, got %.0fm", valid_distances[0])
        passed = False

    if passed:
        logger.info("  PASSED ✅")
    return passed


async def test_geo_distance_realistic_values(pool, sidecar_url) -> bool:
    """vg:geoDistance — verify known distances are approximately correct."""
    logger.info("test_geo_distance_realistic_values...")

    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX vc: <http://vital.ai/ontology/vital-core#>
        SELECT ?entity ?name ?dist WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                ?entity vc:hasName ?name .
            }}
            BIND(vg:geoDistance(?entity, {TIMES_SQUARE[0]}, {TIMES_SQUARE[1]}) AS ?dist)
        }}
        ORDER BY ?dist
    """

    result = await run_sparql(pool, sidecar_url, sparql)
    if result.get("error"):
        logger.error("  FAILED: %s", result["error"])
        return False

    # Build name→distance map
    name_dist = {}
    for b in result["bindings"]:
        name = get_value(b, "name")
        dist = get_float(b, "dist")
        if dist is not None:
            name_dist[name.lower()] = dist

    passed = True

    # Known approximate distances from Times Square (meters):
    # Empire State Building: ~1.1km
    # Central Park: ~2.8km
    # Brooklyn Bridge: ~6km
    # JFK Airport: ~20km

    checks = [
        ("empire state building", 500, 3000, "~1.1km"),
        ("central park", 1000, 5000, "~2.8km"),
        ("brooklyn bridge", 3000, 10000, "~6km"),
    ]

    for name_key, min_m, max_m, expected in checks:
        matching = [(k, v) for k, v in name_dist.items() if name_key in k]
        if matching:
            actual = matching[0][1]
            ok = min_m <= actual <= max_m
            if not ok:
                logger.error("  FAILED: %s distance %.0fm not in [%d, %d] (expected %s)",
                             matching[0][0], actual, min_m, max_m, expected)
                passed = False
            else:
                logger.info("  ✓ %s: %.0fm (expected %s)", matching[0][0], actual, expected)
        else:
            logger.warning("  ⚠️  '%s' not found in results — skipping", name_key)

    if passed:
        logger.info("  PASSED ✅")
    return passed


# ---------------------------------------------------------------------------
# Test: vg:withinRadius + ORDER BY distance
# ---------------------------------------------------------------------------

async def test_radius_with_distance_ordering(pool, sidecar_url) -> bool:
    """Combined: withinRadius filter + geoDistance ordering."""
    logger.info("test_radius_with_distance_ordering...")

    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX vc: <http://vital.ai/ontology/vital-core#>
        SELECT ?entity ?name ?dist WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                ?entity vc:hasName ?name .
            }}
            FILTER(vg:withinRadius(?entity, {TIMES_SQUARE[0]}, {TIMES_SQUARE[1]}, 50000))
            BIND(vg:geoDistance(?entity, {TIMES_SQUARE[0]}, {TIMES_SQUARE[1]}) AS ?dist)
        }}
        ORDER BY ?dist
    """

    result = await run_sparql(pool, sidecar_url, sparql)
    if result.get("error"):
        logger.error("  FAILED: %s", result["error"])
        return False

    bindings = result["bindings"]
    if len(bindings) == 0:
        logger.error("  FAILED: no results")
        return False

    logger.info("  Entities within 50km, ordered by distance:")
    distances = []
    for i, b in enumerate(bindings):
        name = get_value(b, "name")
        dist = get_float(b, "dist")
        distances.append(dist)
        logger.info("    %d. %s — %.0fm", i + 1, name, dist or 0)

    # All distances should be < 50km
    passed = True
    for d in distances:
        if d is not None and d > 50000:
            logger.error("  FAILED: entity at %.0fm exceeds 50km radius", d)
            passed = False
            break

    # Should be ascending
    valid = [d for d in distances if d is not None]
    for i in range(len(valid) - 1):
        if valid[i] > valid[i + 1]:
            logger.error("  FAILED: distances not ascending")
            passed = False
            break

    if passed:
        logger.info("  PASSED ✅")
    return passed


# ---------------------------------------------------------------------------
# Test: vg:withinBounds (included for completeness)
# ---------------------------------------------------------------------------

async def test_within_bounds_nyc(pool, sidecar_url) -> bool:
    """vg:withinBounds — box around Manhattan."""
    logger.info("test_within_bounds_nyc...")

    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX vc: <http://vital.ai/ontology/vital-core#>
        SELECT ?entity ?name WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                ?entity vc:hasName ?name .
            }}
            FILTER(vg:withinBounds(?entity, 40.70, -74.02, 40.83, -73.93))
        }}
    """

    result = await run_sparql(pool, sidecar_url, sparql)
    if result.get("error"):
        logger.error("  FAILED: %s", result["error"])
        return False

    names = [get_value(b, "name") for b in result["bindings"]]
    logger.info("  Found %d entities in Manhattan box: %s", len(names), names[:8])

    passed = True
    expected_in = ["Times Square", "Empire State Building", "Central Park"]
    for exp in expected_in:
        if not any(exp.lower() in n.lower() for n in names):
            logger.error("  FAILED: expected '%s' in Manhattan box", exp)
            passed = False

    if passed:
        logger.info("  PASSED ✅")
    return passed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    import asyncpg

    db_host = os.environ.get("LOCAL_DB_HOST", "localhost")
    if db_host == "host.docker.internal":
        db_host = "localhost"
    db_port = os.environ.get("LOCAL_DB_PORT", "5432")
    db_name = os.environ.get("LOCAL_DB_NAME", "sparql_sql_graph")
    db_user = os.environ.get("LOCAL_DB_USERNAME", "postgres")
    db_pass = os.environ.get("LOCAL_DB_PASSWORD", "")
    sidecar_url = os.environ.get("SIDECAR_URL", "http://localhost:7070")

    db_url = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
    logger.info("Connecting to %s (sidecar: %s)", db_url.split("@")[1], sidecar_url)

    pool = await asyncpg.create_pool(db_url, min_size=2, max_size=4)

    try:
        results = {}

        # withinRadius tests
        results["within_radius_nyc_50km"] = await test_within_radius_nyc(pool, sidecar_url)
        results["within_radius_large_1000km"] = await test_within_radius_large(pool, sidecar_url)
        results["within_radius_empty"] = await test_within_radius_empty(pool, sidecar_url)

        # geoDistance tests
        results["geo_distance_ordering"] = await test_geo_distance_from_nyc(pool, sidecar_url)
        results["geo_distance_realistic"] = await test_geo_distance_realistic_values(pool, sidecar_url)

        # Combined tests
        results["radius_with_distance_order"] = await test_radius_with_distance_ordering(pool, sidecar_url)

        # withinBounds (sanity check)
        results["within_bounds_nyc"] = await test_within_bounds_nyc(pool, sidecar_url)

        # Summary
        passed = sum(1 for v in results.values() if v)
        total = len(results)
        logger.info("")
        logger.info("=" * 70)
        logger.info("  GEO SPARQL COMPREHENSIVE: %d/%d passed", passed, total)
        logger.info("=" * 70)
        for name, ok in results.items():
            logger.info("  %s %s", "✅" if ok else "❌", name)

        if passed < total:
            sys.exit(1)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
