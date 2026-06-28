#!/usr/bin/env python3
"""
Combined geo + vector SPARQL integration test.

Tests SPARQL queries that combine geo and vector functions in a single query,
validating that:
  1. Both geo and vector functions resolve in the same query
  2. Filtering on both dimensions works correctly
  3. Combined ORDER BY works
  4. Results satisfy both spatial and semantic constraints

Prerequisites:
  - PostgreSQL with pgvector and PostGIS extensions
  - Jena sidecar running
  - Geo test data loaded with vector embeddings
    (run: python test_scripts/data/generate_geo_test_data.py --load)

Usage:
    python test_scripts/test_geo_vector_combined_sparql.py
"""

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("test_geo_vector_combined_sparql")

# ---------------------------------------------------------------------------
# Configuration — uses the sp_vgeo_e2e space from test_vector_geo_e2e.py
# which has both vector embeddings AND geo coordinates
# ---------------------------------------------------------------------------

SPACE_ID = "sp_vgeo_e2e"
GRAPH_URI = "urn:test:vector_geo_e2e"
INDEX_NAME = "e2e_default"

# Query point: Manhattan
QUERY_LAT = 40.7580
QUERY_LON = -73.9855
QUERY_RADIUS_M = 500_000  # 500km — NYC + Boston

# Query vector: most similar to NYC/Boston embeddings
QUERY_VECTOR = "[1.0,0.0,0.0,0.0]"


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

        logger.debug("  SQL: %s", sql[:400])

        try:
            rows = await conn.fetch(sql)
        except Exception as e:
            return {"error": str(e), "bindings": [], "sql": sql}
        result_rows = [dict(r) for r in rows]

    var_map = gen.var_map or {}
    bindings = SparqlSQLSpaceImpl._rows_to_sparql_bindings(result_rows, var_map)
    return {"bindings": bindings, "sql": sql}


def get_val(binding: dict, var: str) -> str:
    val = binding.get(var, {})
    return val.get("value", "") if isinstance(val, dict) else str(val or "")


def get_num(binding: dict, var: str) -> float:
    try:
        return float(get_val(binding, var))
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_geo_plus_vector_filter(pool, sidecar_url: str) -> bool:
    """Test combining withinRadius filter with vectorNearby score."""
    logger.info("test_geo_plus_vector_filter...")

    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX vc: <http://vital.ai/ontology/vital-core#>
        SELECT ?entity ?score ?dist WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
            }}
            BIND(vg:vectorNearby(?entity, "{QUERY_VECTOR}", "{INDEX_NAME}") AS ?score)
            BIND(vg:geoDistance(?entity, {QUERY_LAT}, {QUERY_LON}) AS ?dist)
            FILTER(vg:withinRadius(?entity, {QUERY_LAT}, {QUERY_LON}, {QUERY_RADIUS_M}))
        }}
        ORDER BY DESC(?score)
    """

    result = await run_sparql(pool, sidecar_url, sparql)

    if "error" in result and result.get("error"):
        logger.error("  FAILED: %s", result["error"])
        return False

    bindings = result["bindings"]
    logger.info("  Results: %d entities (within %dkm with vector scores)",
                len(bindings), QUERY_RADIUS_M // 1000)

    if len(bindings) == 0:
        logger.error("  FAILED: No results")
        return False

    # Verify all results have both score and distance
    for b in bindings:
        uri = get_val(b, "entity")
        score = get_num(b, "score")
        dist = get_num(b, "dist")
        name = uri.split("/")[-1]
        logger.info("    %s — score=%.4f, dist=%.0fm", name, score, dist)

        # Distance should be within radius
        if dist > QUERY_RADIUS_M * 1.01:  # 1% tolerance
            logger.error("  FAILED: %s distance %.0fm exceeds radius %dm",
                         name, dist, QUERY_RADIUS_M)
            return False

    # Verify score ordering
    scores = [get_num(b, "score") for b in bindings]
    for i in range(len(scores) - 1):
        if scores[i] < scores[i + 1] - 0.0001:  # tolerance for float
            logger.error("  FAILED: Scores not descending at %d", i)
            return False

    logger.info("  PASSED")
    return True


async def test_geo_distance_with_vector_threshold(pool, sidecar_url: str) -> bool:
    """Test geo distance ordering with vector similarity threshold."""
    logger.info("test_geo_distance_with_vector_threshold...")

    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX vc: <http://vital.ai/ontology/vital-core#>
        SELECT ?entity ?score ?dist WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
            }}
            BIND(vg:vectorNearby(?entity, "{QUERY_VECTOR}", "{INDEX_NAME}") AS ?score)
            BIND(vg:geoDistance(?entity, {QUERY_LAT}, {QUERY_LON}) AS ?dist)
            FILTER(?score > 0.5)
        }}
        ORDER BY ?dist
    """

    result = await run_sparql(pool, sidecar_url, sparql)

    if "error" in result and result.get("error"):
        logger.error("  FAILED: %s", result["error"])
        return False

    bindings = result["bindings"]
    logger.info("  Results: %d entities (score > 0.5, ordered by distance)", len(bindings))

    if len(bindings) == 0:
        logger.error("  FAILED: No results")
        return False

    # Verify all scores > 0.5
    for b in bindings:
        score = get_num(b, "score")
        if score <= 0.5:
            logger.error("  FAILED: score %.4f not > 0.5", score)
            return False

    # Verify distance ordering
    distances = [get_num(b, "dist") for b in bindings]
    for i in range(len(distances) - 1):
        if distances[i] > distances[i + 1] + 1:  # 1m tolerance
            logger.error("  FAILED: Distances not ascending at %d", i)
            return False

    for b in bindings:
        uri = get_val(b, "entity")
        name = uri.split("/")[-1]
        score = get_num(b, "score")
        dist = get_num(b, "dist")
        logger.info("    %s — dist=%.0fm, score=%.4f", name, dist, score)

    logger.info("  PASSED")
    return True


async def test_all_three_functions(pool, sidecar_url: str) -> bool:
    """Test using geoDistance, withinRadius, and vectorNearby all together."""
    logger.info("test_all_three_functions...")

    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX vc: <http://vital.ai/ontology/vital-core#>
        SELECT ?entity ?score ?dist WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
            }}
            BIND(vg:vectorNearby(?entity, "{QUERY_VECTOR}", "{INDEX_NAME}") AS ?score)
            BIND(vg:geoDistance(?entity, {QUERY_LAT}, {QUERY_LON}) AS ?dist)
            FILTER(vg:withinRadius(?entity, {QUERY_LAT}, {QUERY_LON}, {QUERY_RADIUS_M}))
            FILTER(?score > 0.3)
            FILTER(?dist < 400000)
        }}
        ORDER BY DESC(?score)
    """

    result = await run_sparql(pool, sidecar_url, sparql)

    if "error" in result and result.get("error"):
        logger.error("  FAILED: %s", result["error"])
        return False

    bindings = result["bindings"]
    logger.info("  Results: %d entities (radius + score + distance filters)", len(bindings))

    # Verify constraints
    for b in bindings:
        score = get_num(b, "score")
        dist = get_num(b, "dist")
        if score <= 0.3:
            logger.error("  FAILED: score constraint violated")
            return False
        if dist >= 400000:
            logger.error("  FAILED: distance constraint violated")
            return False

    for b in bindings:
        uri = get_val(b, "entity")
        name = uri.split("/")[-1]
        score = get_num(b, "score")
        dist = get_num(b, "dist")
        logger.info("    %s — score=%.4f, dist=%.0fm", name, score, dist)

    logger.info("  PASSED")
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
        results["geo_plus_vector_filter"] = await test_geo_plus_vector_filter(pool, sidecar_url)
        results["geo_distance_vector_threshold"] = await test_geo_distance_with_vector_threshold(pool, sidecar_url)
        results["all_three_functions"] = await test_all_three_functions(pool, sidecar_url)

        # Summary
        passed = sum(1 for v in results.values() if v)
        total = len(results)
        logger.info("")
        logger.info("=" * 60)
        logger.info("  GEO + VECTOR COMBINED: %d/%d passed", passed, total)
        logger.info("=" * 60)
        for name, ok in results.items():
            logger.info("  %s %s", "PASS" if ok else "FAIL", name)

        if passed < total:
            sys.exit(1)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
