#!/usr/bin/env python3
"""
Integration test for vg:withinBounds and vg:withinPolygon SPARQL functions.

Tests:
  1. vg:withinBounds — bounding box spatial filter
  2. vg:withinPolygon — WKT polygon spatial filter
  3. vg:withinPolygon — GeoJSON polygon spatial filter

Prerequisites:
  - PostgreSQL with PostGIS extension
  - Jena sidecar running
  - Geo test data loaded (run: python test_scripts/data/generate_geo_test_data.py --load)

Usage:
    python test_scripts/test_geo_bounds_polygon.py
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
logger = logging.getLogger("test_geo_bounds_polygon")

SPACE_ID = "sp_geo_test"
GRAPH_URI = "urn:vitalgraph:geo_test:entities"


async def run_sparql(pool, sidecar_url, sparql):
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


def get_name(b):
    val = b.get("name", {})
    return val.get("value", "") if isinstance(val, dict) else str(val or "")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_within_bounds_manhattan(pool, sidecar_url) -> bool:
    """Test vg:withinBounds with a box around Manhattan."""
    logger.info("test_within_bounds_manhattan...")

    # Bounding box roughly covering Manhattan
    # SW corner: (40.70, -74.02), NE corner: (40.83, -73.93)
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

    names = [get_name(b) for b in result["bindings"]]
    logger.info("  Found %d entities in Manhattan box: %s", len(names), names)

    # Should include Times Square, Empire State, Central Park, etc.
    expected_in = ["Times Square", "Empire State Building", "Central Park"]
    # Should exclude JFK, LaGuardia, London, Tokyo
    expected_out = ["JFK Airport", "London", "Tokyo"]

    passed = True
    for exp in expected_in:
        if not any(exp.lower() in n.lower() for n in names):
            logger.error("  FAILED: expected '%s' inside Manhattan box", exp)
            passed = False

    for exc in expected_out:
        if any(exc.lower() in n.lower() for n in names):
            logger.error("  FAILED: expected '%s' outside Manhattan box", exc)
            passed = False

    if passed:
        logger.info("  PASSED")
    return passed


async def test_within_bounds_london(pool, sidecar_url) -> bool:
    """Test vg:withinBounds with a box around central London."""
    logger.info("test_within_bounds_london...")

    # Box around central London: SW (51.45, -0.20), NE (51.56, 0.01)
    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX vc: <http://vital.ai/ontology/vital-core#>
        SELECT ?entity ?name WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                ?entity vc:hasName ?name .
            }}
            FILTER(vg:withinBounds(?entity, 51.45, -0.20, 51.56, 0.01))
        }}
    """

    result = await run_sparql(pool, sidecar_url, sparql)
    if result.get("error"):
        logger.error("  FAILED: %s", result["error"])
        return False

    names = [get_name(b) for b in result["bindings"]]
    logger.info("  Found %d entities in London box: %s", len(names), names)

    expected_in = ["Tower Bridge London", "Westminster Abbey", "Canary Wharf"]
    expected_out = ["Times Square", "Heathrow Airport", "Gatwick Airport"]

    passed = True
    for exp in expected_in:
        if not any(exp.lower() in n.lower() for n in names):
            logger.error("  FAILED: expected '%s' inside London box", exp)
            passed = False
    for exc in expected_out:
        if any(exc.lower() in n.lower() for n in names):
            logger.error("  FAILED: expected '%s' outside London box", exc)
            passed = False

    if passed:
        logger.info("  PASSED")
    return passed


async def test_within_polygon_wkt(pool, sidecar_url) -> bool:
    """Test vg:withinPolygon with a WKT polygon around NYC area."""
    logger.info("test_within_polygon_wkt...")

    # Triangle polygon covering Manhattan + parts of Brooklyn
    # Points: NW Manhattan, SE Brooklyn, SW Manhattan
    wkt = "POLYGON((-74.05 40.70, -73.92 40.70, -73.92 40.84, -74.05 40.84, -74.05 40.70))"

    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX vc: <http://vital.ai/ontology/vital-core#>
        SELECT ?entity ?name WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                ?entity vc:hasName ?name .
            }}
            FILTER(vg:withinPolygon(?entity, "{wkt}"))
        }}
    """

    result = await run_sparql(pool, sidecar_url, sparql)
    if result.get("error"):
        logger.error("  FAILED: %s", result["error"])
        return False

    names = [get_name(b) for b in result["bindings"]]
    logger.info("  Found %d entities in WKT polygon: %s", len(names), names)

    if len(names) == 0:
        logger.error("  FAILED: No entities found in NYC polygon")
        return False

    # Should include Manhattan landmarks
    if not any("times square" in n.lower() for n in names):
        logger.error("  FAILED: expected Times Square in polygon")
        return False

    # Should exclude Tokyo, London
    if any("tokyo" in n.lower() or "london" in n.lower() for n in names):
        logger.error("  FAILED: found non-NYC entities in polygon")
        return False

    logger.info("  PASSED")
    return True


async def test_within_polygon_geojson(pool, sidecar_url) -> bool:
    """Test vg:withinPolygon with a GeoJSON polygon around Tokyo."""
    logger.info("test_within_polygon_geojson...")

    import json
    geojson = json.dumps({
        "type": "Polygon",
        "coordinates": [[
            [139.65, 35.60],
            [139.85, 35.60],
            [139.85, 35.75],
            [139.65, 35.75],
            [139.65, 35.60],
        ]]
    })

    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX vc: <http://vital.ai/ontology/vital-core#>
        SELECT ?entity ?name WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                ?entity vc:hasName ?name .
            }}
            FILTER(vg:withinPolygon(?entity, '{geojson}'))
        }}
    """

    result = await run_sparql(pool, sidecar_url, sparql)
    if result.get("error"):
        logger.error("  FAILED: %s", result["error"])
        return False

    names = [get_name(b) for b in result["bindings"]]
    logger.info("  Found %d entities in Tokyo GeoJSON polygon: %s", len(names), names)

    if len(names) == 0:
        logger.error("  FAILED: No entities found in Tokyo polygon")
        return False

    # Should include Tokyo landmarks
    expected_in = ["Imperial Palace Tokyo", "Ginza", "Shibuya Crossing"]
    found_any = False
    for exp in expected_in:
        if any(exp.lower() in n.lower() for n in names):
            found_any = True
            break
    if not found_any:
        logger.error("  FAILED: no Tokyo landmarks found, got: %s", names)
        return False

    # Should not include NYC or London
    if any("times square" in n.lower() or "london" in n.lower() for n in names):
        logger.error("  FAILED: found non-Tokyo entities in polygon")
        return False

    logger.info("  PASSED")
    return True


async def test_bounds_empty_result(pool, sidecar_url) -> bool:
    """Test that a bounding box with no entities returns empty."""
    logger.info("test_bounds_empty_result...")

    # Middle of the Pacific Ocean
    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX vc: <http://vital.ai/ontology/vital-core#>
        SELECT ?entity ?name WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                ?entity vc:hasName ?name .
            }}
            FILTER(vg:withinBounds(?entity, 0.0, -170.0, 5.0, -160.0))
        }}
    """

    result = await run_sparql(pool, sidecar_url, sparql)
    if result.get("error"):
        logger.error("  FAILED: %s", result["error"])
        return False

    names = [get_name(b) for b in result["bindings"]]
    if len(names) > 0:
        logger.error("  FAILED: expected 0 results in Pacific Ocean, got %d: %s", len(names), names)
        return False

    logger.info("  PASSED (0 results as expected)")
    return True


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
        results["within_bounds_manhattan"] = await test_within_bounds_manhattan(pool, sidecar_url)
        results["within_bounds_london"] = await test_within_bounds_london(pool, sidecar_url)
        results["within_polygon_wkt"] = await test_within_polygon_wkt(pool, sidecar_url)
        results["within_polygon_geojson"] = await test_within_polygon_geojson(pool, sidecar_url)
        results["bounds_empty_result"] = await test_bounds_empty_result(pool, sidecar_url)

        passed = sum(1 for v in results.values() if v)
        total = len(results)
        logger.info("")
        logger.info("=" * 60)
        logger.info("  GEO BOUNDS + POLYGON: %d/%d passed", passed, total)
        logger.info("=" * 60)
        for name, ok in results.items():
            logger.info("  %s %s", "PASS" if ok else "FAIL", name)

        if passed < total:
            sys.exit(1)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
