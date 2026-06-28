#!/usr/bin/env python3
"""
Geo semantic quality test — validates real-world correctness of geo search
using known distances between landmarks.

Tests:
  1. Entities within radius ARE returned
  2. Entities outside radius ARE excluded
  3. Distance ordering is correct (closest first)
  4. Known distances match within acceptable tolerance

Prerequisites:
  - PostgreSQL with PostGIS extension
  - Jena sidecar running
  - Geo test data loaded (run: python test_scripts/data/generate_geo_test_data.py --load)

Usage:
    python test_scripts/test_geo_semantic_quality.py
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
logger = logging.getLogger("test_geo_semantic_quality")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SPACE_ID = "sp_geo_test"
GRAPH_URI = "urn:vitalgraph:geo_test:entities"

# Tolerance for distance assertions (±15% — accounts for Earth model differences)
DISTANCE_TOLERANCE = 0.15


# ---------------------------------------------------------------------------
# Test scenarios: (query_lat, query_lon, radius_km, expected_in, expected_out)
# ---------------------------------------------------------------------------

RADIUS_TESTS = [
    {
        "name": "Times Square 5km",
        "lat": 40.7580,
        "lon": -73.9855,
        "radius_m": 5000,
        "expected_in": ["Empire State Building", "Central Park"],
        "expected_out": ["JFK Airport", "LaGuardia Airport", "White Plains NY"],
    },
    {
        "name": "Times Square 25km",
        "lat": 40.7580,
        "lon": -73.9855,
        "radius_m": 25000,
        "expected_in": ["Empire State Building", "JFK Airport", "LaGuardia Airport", "Coney Island", "Wall Street"],
        "expected_out": ["White Plains NY", "Stamford CT"],
    },
    {
        "name": "Tower Bridge 5km",
        "lat": 51.5055,
        "lon": -0.0754,
        "radius_m": 5000,
        "expected_in": ["Westminster Abbey", "Canary Wharf"],
        "expected_out": ["Heathrow Airport", "Gatwick Airport", "Wimbledon"],
    },
    {
        "name": "Imperial Palace 5km",
        "lat": 35.6852,
        "lon": 139.7528,
        "radius_m": 5000,
        "expected_in": ["Ginza", "Akihabara"],
        "expected_out": ["Narita Airport", "Yokohama", "Kamakura"],
    },
]

# Known distances to validate (location_name, query_lat, query_lon, expected_km, tolerance_pct)
DISTANCE_CHECKS = [
    ("Empire State Building", 40.7580, -73.9855, 1.1, 0.5),  # from Times Square
    ("JFK Airport", 40.7580, -73.9855, 19.2, DISTANCE_TOLERANCE),
    ("Narita Airport", 35.6852, 139.7528, 60.0, DISTANCE_TOLERANCE),
    ("Gatwick Airport", 51.5055, -0.0754, 39.0, DISTANCE_TOLERANCE),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def run_sparql(pool, sidecar_url: str, sparql: str) -> dict:
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

        rows = await conn.fetch(sql)
        result_rows = [dict(r) for r in rows]

    var_map = gen.var_map or {}
    bindings = SparqlSQLSpaceImpl._rows_to_sparql_bindings(result_rows, var_map)
    return {"bindings": bindings, "sql": sql}


def get_entity_name(binding: dict) -> str:
    """Extract entity name from binding."""
    name_val = binding.get("name", {})
    if isinstance(name_val, dict):
        return name_val.get("value", "")
    return str(name_val) if name_val else ""


def get_numeric(binding: dict, var: str) -> float:
    """Extract numeric value from binding."""
    val = binding.get(var, {})
    if isinstance(val, dict):
        val = val.get("value", "0")
    try:
        return float(val)
    except (ValueError, TypeError):
        return float("inf")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_radius_filtering(pool, sidecar_url: str) -> bool:
    """Test that vg:withinRadius correctly includes/excludes entities."""
    logger.info("test_radius_filtering...")
    all_passed = True

    for tc in RADIUS_TESTS:
        sparql = f"""
            PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
            PREFIX vc: <http://vital.ai/ontology/vital-core#>
            SELECT ?entity ?name WHERE {{
                GRAPH <{GRAPH_URI}> {{
                    ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                    ?entity vc:hasName ?name .
                }}
                FILTER(vg:withinRadius(?entity, {tc['lat']}, {tc['lon']}, {tc['radius_m']}))
            }}
        """

        result = await run_sparql(pool, sidecar_url, sparql)
        if "error" in result:
            logger.error("  FAILED [%s]: %s", tc["name"], result.get("error"))
            all_passed = False
            continue

        names = [get_entity_name(b) for b in result["bindings"]]

        # Check expected IN
        for expected in tc["expected_in"]:
            if not any(expected.lower() in n.lower() for n in names):
                logger.error("  FAILED [%s]: expected '%s' IN radius, got: %s",
                             tc["name"], expected, names[:10])
                all_passed = False

        # Check expected OUT
        for excluded in tc["expected_out"]:
            if any(excluded.lower() in n.lower() for n in names):
                logger.error("  FAILED [%s]: expected '%s' OUT of radius, but found it",
                             tc["name"], excluded)
                all_passed = False

        logger.info("  [%s] %d results - checks passed", tc["name"], len(names))

    if all_passed:
        logger.info("  PASSED")
    return all_passed


async def test_distance_ordering(pool, sidecar_url: str) -> bool:
    """Test that vg:geoDistance returns correctly ordered results."""
    logger.info("test_distance_ordering...")

    # Query from Times Square, all entities sorted by distance
    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX vc: <http://vital.ai/ontology/vital-core#>
        SELECT ?entity ?name ?dist WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                ?entity vc:hasName ?name .
            }}
            BIND(vg:geoDistance(?entity, 40.7580, -73.9855) AS ?dist)
        }}
        ORDER BY ?dist
        LIMIT 20
    """

    result = await run_sparql(pool, sidecar_url, sparql)
    if "error" in result:
        logger.error("  FAILED: %s", result.get("error"))
        return False

    bindings = result["bindings"]
    if len(bindings) < 2:
        logger.error("  FAILED: Need at least 2 results")
        return False

    # Verify ascending order
    distances = [get_numeric(b, "dist") for b in bindings]
    for i in range(len(distances) - 1):
        if distances[i] > distances[i + 1]:
            logger.error("  FAILED: Distance not ascending at position %d: %.0f > %.0f",
                         i, distances[i], distances[i + 1])
            return False

    # Log first few results
    for i, b in enumerate(bindings[:8]):
        name = get_entity_name(b)
        dist = get_numeric(b, "dist")
        logger.info("    %d. %s — %.0fm", i + 1, name, dist)

    logger.info("  PASSED (distances ascending)")
    return True


async def test_known_distances(pool, sidecar_url: str) -> bool:
    """Test that computed distances match known real-world values."""
    logger.info("test_known_distances...")
    all_passed = True

    for (loc_name, qlat, qlon, expected_km, tolerance) in DISTANCE_CHECKS:
        sparql = f"""
            PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
            PREFIX vc: <http://vital.ai/ontology/vital-core#>
            SELECT ?dist WHERE {{
                GRAPH <{GRAPH_URI}> {{
                    ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                    ?entity vc:hasName ?name .
                    FILTER(CONTAINS(?name, "{loc_name}"))
                }}
                BIND(vg:geoDistance(?entity, {qlat}, {qlon}) AS ?dist)
            }}
            LIMIT 1
        """

        result = await run_sparql(pool, sidecar_url, sparql)
        if "error" in result:
            logger.error("  FAILED [%s]: %s", loc_name, result.get("error"))
            all_passed = False
            continue

        bindings = result["bindings"]
        if not bindings:
            logger.warning("  SKIP [%s]: no result (entity may not exist)", loc_name)
            continue

        actual_m = get_numeric(bindings[0], "dist")
        actual_km = actual_m / 1000.0
        expected_m = expected_km * 1000.0

        diff_pct = abs(actual_km - expected_km) / expected_km if expected_km > 0 else 0

        if diff_pct > tolerance:
            logger.error("  FAILED [%s]: expected ~%.1fkm, got %.1fkm (%.0f%% off)",
                         loc_name, expected_km, actual_km, diff_pct * 100)
            all_passed = False
        else:
            logger.info("  OK [%s]: expected ~%.1fkm, got %.1fkm (%.0f%% off)",
                        loc_name, expected_km, actual_km, diff_pct * 100)

    if all_passed:
        logger.info("  PASSED")
    return all_passed


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
        results["radius_filtering"] = await test_radius_filtering(pool, sidecar_url)
        results["distance_ordering"] = await test_distance_ordering(pool, sidecar_url)
        results["known_distances"] = await test_known_distances(pool, sidecar_url)

        # Summary
        passed = sum(1 for v in results.values() if v)
        total = len(results)
        logger.info("")
        logger.info("=" * 60)
        logger.info("  GEO SEMANTIC QUALITY: %d/%d passed", passed, total)
        logger.info("=" * 60)
        for name, ok in results.items():
            logger.info("  %s %s", "PASS" if ok else "FAIL", name)

        if passed < total:
            sys.exit(1)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
