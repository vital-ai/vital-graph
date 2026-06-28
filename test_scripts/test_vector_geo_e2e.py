#!/usr/bin/env python3
"""
End-to-end integration test: SPARQL vector/geo queries → SQL → real database results.

Tests the full pipeline:
  SPARQL (vg:vectorNearby, vg:geoDistance, vg:withinRadius)
  → Jena sidecar compile
  → V2 IR + SQL generation (vg_functions + vg_resolve)
  → PostgreSQL execution (pgvector + PostGIS)
  → Correct results with proper ordering

Prerequisites:
  - PostgreSQL with pgvector and PostGIS extensions
  - Jena sidecar running at SIDECAR_URL (default: http://localhost:7070)
  - Database: sparql_sql_graph (local default)
  - A space with test data (created by this script)

Usage:
    python test_scripts/test_vector_geo_e2e.py
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
logger = logging.getLogger("test_vector_geo_e2e")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SPACE_ID = "sp_vgeo_e2e"
GRAPH_URI = "urn:test:vector_geo_e2e"
INDEX_NAME = "e2e_default"
DIMENSIONS = 4  # Small for testing

# Test entities with known embeddings and geo locations
# Embeddings: 4-dimensional unit vectors for controlled similarity testing
TEST_DATA = [
    {
        "uri": "http://example.org/entity/nyc",
        "name": "New York City",
        "embedding": [0.9, 0.1, 0.1, 0.1],  # Most similar to query [1,0,0,0]
        "lat": 40.7128,
        "lon": -74.0060,
    },
    {
        "uri": "http://example.org/entity/london",
        "name": "London",
        "embedding": [0.5, 0.5, 0.5, 0.5],  # Medium similarity
        "lat": 51.5074,
        "lon": -0.1278,
    },
    {
        "uri": "http://example.org/entity/tokyo",
        "name": "Tokyo",
        "embedding": [0.1, 0.1, 0.9, 0.1],  # Low similarity to [1,0,0,0]
        "lat": 35.6762,
        "lon": 139.6503,
    },
    {
        "uri": "http://example.org/entity/paris",
        "name": "Paris",
        "embedding": [0.8, 0.2, 0.1, 0.1],  # High similarity to [1,0,0,0]
        "lat": 48.8566,
        "lon": 2.3522,
    },
    {
        "uri": "http://example.org/entity/boston",
        "name": "Boston",
        "embedding": [0.85, 0.15, 0.1, 0.1],  # High similarity, near NYC
        "lat": 42.3601,
        "lon": -71.0589,
    },
]

# Query vector for similarity tests — most similar to NYC and Boston
QUERY_VECTOR = "[1.0,0.0,0.0,0.0]"

# Geo query point: near NYC (Manhattan)
QUERY_LAT = 40.7580
QUERY_LON = -73.9855
QUERY_RADIUS_M = 500_000  # 500km — should include NYC and Boston


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

URL_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def uri_to_uuid(uri: str) -> uuid.UUID:
    """Deterministic UUID from URI (same as VitalGraph)."""
    return uuid.uuid5(URL_NS, uri)


async def run_sparql_v2(pool, sidecar_url: str, sparql: str) -> dict:
    """Run a SPARQL query through the full V2 pipeline, returning SQL + bindings."""
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
        var_map = gen.var_map or {}

        # Resolve vector placeholders
        if gen.vector_requests:
            sql = await resolve_vector_requests(sql, gen.vector_requests, SPACE_ID, conn)

        rows = await conn.fetch(sql)
        result_rows = [dict(r) for r in rows]

    bindings = SparqlSQLSpaceImpl._rows_to_sparql_bindings(result_rows, var_map)

    return {
        "sql": sql,
        "var_map": var_map,
        "row_count": len(result_rows),
        "bindings": bindings,
    }


# ---------------------------------------------------------------------------
# Setup: Create test space with vector + geo data
# ---------------------------------------------------------------------------

async def setup_test_space(pool):
    """Create test space tables and populate with test data."""
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

    schema = SparqlSQLSchema()
    context_uuid = uri_to_uuid(GRAPH_URI)

    async with pool.acquire() as conn:
        # Check if extensions are available
        ext_check = await conn.fetchval("SELECT COUNT(*) FROM pg_extension WHERE extname = 'vector'")
        if ext_check == 0:
            logger.error("pgvector extension not installed! Run: CREATE EXTENSION vector;")
            return False

        ext_check = await conn.fetchval("SELECT COUNT(*) FROM pg_extension WHERE extname = 'postgis'")
        if ext_check == 0:
            logger.error("PostGIS extension not installed! Run: CREATE EXTENSION postgis;")
            return False

        # Drop old test space if exists
        drop_stmts = schema.drop_space_tables_sql(SPACE_ID)
        for stmt in drop_stmts:
            try:
                await conn.execute(stmt)
            except Exception:
                pass

        # Also drop vector data table
        vec_table = schema.vec_table_name(SPACE_ID, INDEX_NAME)
        await conn.execute(f"DROP TABLE IF EXISTS {vec_table} CASCADE")

        # Create space schema (tables + indexes)
        create_stmts = schema.create_space_tables_sql(SPACE_ID)
        for stmt in create_stmts:
            await conn.execute(stmt)
        index_stmts = schema.create_space_indexes_sql(SPACE_ID)
        for stmt in index_stmts:
            await conn.execute(stmt)

        # Create vector data table
        vec_stmts = schema.create_vector_data_table_sql(
            SPACE_ID, INDEX_NAME, DIMENSIONS, "cosine"
        )
        for stmt in vec_stmts:
            await conn.execute(stmt)

        # Register the vector index in the catalog
        await conn.execute(f"""
            INSERT INTO {SPACE_ID}_vector_index (index_name, dimensions, distance_metric, provider, provider_config)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (index_name) DO NOTHING
        """, INDEX_NAME, DIMENSIONS, "cosine", "test", json.dumps({}))

        # Insert context (graph URI) into term table
        await conn.execute(f"""
            INSERT INTO {SPACE_ID}_term (term_uuid, term_text, term_type)
            VALUES ($1, $2, 'U')
            ON CONFLICT DO NOTHING
        """, context_uuid, GRAPH_URI)

        # Insert RDF type predicate term
        rdf_type = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
        rdf_type_uuid = uri_to_uuid(rdf_type)
        await conn.execute(f"""
            INSERT INTO {SPACE_ID}_term (term_uuid, term_text, term_type)
            VALUES ($1, $2, 'U')
            ON CONFLICT DO NOTHING
        """, rdf_type_uuid, rdf_type)

        # Insert vitaltype predicate term
        vitaltype = "http://vital.ai/ontology/vital-core#vitaltype"
        vitaltype_uuid = uri_to_uuid(vitaltype)
        await conn.execute(f"""
            INSERT INTO {SPACE_ID}_term (term_uuid, term_text, term_type)
            VALUES ($1, $2, 'U')
            ON CONFLICT DO NOTHING
        """, vitaltype_uuid, vitaltype)

        # KGEntity type URI
        kgentity_type = "http://vital.ai/ontology/haley-ai-kg#KGEntity"
        kgentity_uuid = uri_to_uuid(kgentity_type)
        await conn.execute(f"""
            INSERT INTO {SPACE_ID}_term (term_uuid, term_text, term_type)
            VALUES ($1, $2, 'U')
            ON CONFLICT DO NOTHING
        """, kgentity_uuid, kgentity_type)

        # hasName predicate
        has_name = "http://vital.ai/ontology/vital-core#hasName"
        has_name_uuid = uri_to_uuid(has_name)
        await conn.execute(f"""
            INSERT INTO {SPACE_ID}_term (term_uuid, term_text, term_type)
            VALUES ($1, $2, 'U')
            ON CONFLICT DO NOTHING
        """, has_name_uuid, has_name)

        # Insert test entities
        for ent in TEST_DATA:
            subj_uuid = uri_to_uuid(ent["uri"])

            # Subject term
            await conn.execute(f"""
                INSERT INTO {SPACE_ID}_term (term_uuid, term_text, term_type)
                VALUES ($1, $2, 'U')
                ON CONFLICT DO NOTHING
            """, subj_uuid, ent["uri"])

            # Name literal term
            name_uuid = uri_to_uuid(f"{ent['uri']}#name#{ent['name']}")
            await conn.execute(f"""
                INSERT INTO {SPACE_ID}_term (term_uuid, term_text, term_type)
                VALUES ($1, $2, 'L')
                ON CONFLICT DO NOTHING
            """, name_uuid, ent["name"])

            # RDF quad: entity rdf:type KGEntity
            await conn.execute(f"""
                INSERT INTO {SPACE_ID}_rdf_quad (subject_uuid, predicate_uuid, object_uuid, context_uuid)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING
            """, subj_uuid, vitaltype_uuid, kgentity_uuid, context_uuid)

            # RDF quad: entity hasName name
            await conn.execute(f"""
                INSERT INTO {SPACE_ID}_rdf_quad (subject_uuid, predicate_uuid, object_uuid, context_uuid)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING
            """, subj_uuid, has_name_uuid, name_uuid, context_uuid)

            # Vector embedding
            embedding_str = "[" + ",".join(str(v) for v in ent["embedding"]) + "]"
            await conn.execute(f"""
                INSERT INTO {vec_table} (subject_uuid, context_uuid, embedding, search_text)
                VALUES ($1, $2, $3::vector, $4)
                ON CONFLICT (subject_uuid, context_uuid)
                DO UPDATE SET embedding = $3::vector, search_text = $4
            """, subj_uuid, context_uuid, embedding_str, ent["name"])

            # Geo point
            await conn.execute(f"""
                INSERT INTO {SPACE_ID}_geo (subject_uuid, predicate_uuid, latitude, longitude, location, context_uuid)
                VALUES ($1, NULL, $2, $3, ST_MakePoint($3, $2)::geography, $4)
                ON CONFLICT (subject_uuid, context_uuid)
                DO UPDATE SET latitude = $2, longitude = $3, location = ST_MakePoint($3, $2)::geography
            """, subj_uuid, ent["lat"], ent["lon"], context_uuid)

        logger.info("Setup complete: %d entities with vector + geo data", len(TEST_DATA))
        return True


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_vector_nearby(pool, sidecar_url: str) -> bool:
    """Test vg:vectorNearby — should rank entities by cosine similarity to query vector."""
    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        SELECT ?entity ?score
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity <http://vital.ai/ontology/vital-core#vitaltype> <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
            }}
            BIND(vg:vectorNearby(?entity, "{QUERY_VECTOR}", "{INDEX_NAME}") AS ?score)
        }}
        ORDER BY DESC(?score)
    """

    result = await run_sparql_v2(pool, sidecar_url, sparql)

    if "error" in result and result["error"]:
        logger.error("test_vector_nearby FAILED: %s", result["error"])
        return False

    bindings = result["bindings"]
    logger.info("test_vector_nearby: %d results", len(bindings))
    logger.info("  SQL: %s", result["sql"][:200])
    logger.info("  var_map: %s", result["var_map"])
    if bindings:
        logger.info("  binding[0] keys: %s", list(bindings[0].keys()))
        logger.info("  binding[0]: %s", bindings[0])

    if len(bindings) == 0:
        logger.error("test_vector_nearby FAILED: no results")
        return False

    # Verify ordering: NYC (0.9,0.1,0.1,0.1) should be most similar to (1,0,0,0)
    # Expected order: NYC > Boston > Paris > London > Tokyo
    entity_order = [b.get("entity", {}).get("value", "") for b in bindings]
    scores = [float(b.get("score", {}).get("value", "0")) for b in bindings]

    logger.info("  Results:")
    for i, (uri, score) in enumerate(zip(entity_order, scores)):
        name = uri.split("/")[-1]
        logger.info("    %d. %s  score=%.4f", i + 1, name, score)

    # Basic ordering check: first should be most similar
    if len(scores) >= 2:
        assert scores[0] >= scores[1], f"Scores not descending: {scores[0]} < {scores[1]}"

    # NYC should be first (highest cosine similarity to [1,0,0,0])
    if "nyc" not in entity_order[0]:
        logger.warning("  Expected NYC first, got: %s", entity_order[0])

    logger.info("test_vector_nearby PASSED ✅")
    return True


async def test_geo_distance(pool, sidecar_url: str) -> bool:
    """Test vg:geoDistance — should return distance in meters from query point."""
    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        SELECT ?entity ?dist
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity <http://vital.ai/ontology/vital-core#vitaltype> <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
            }}
            BIND(vg:geoDistance(?entity, {QUERY_LAT}, {QUERY_LON}) AS ?dist)
        }}
        ORDER BY ?dist
    """

    result = await run_sparql_v2(pool, sidecar_url, sparql)

    if "error" in result and result["error"]:
        logger.error("test_geo_distance FAILED: %s", result["error"])
        return False

    bindings = result["bindings"]
    logger.info("test_geo_distance: %d results", len(bindings))
    logger.info("  SQL: %s", result["sql"][:200])

    if len(bindings) == 0:
        logger.error("test_geo_distance FAILED: no results")
        return False

    # Verify ordering: closest to Manhattan should be NYC, then Boston
    entity_order = [b.get("entity", {}).get("value", "") for b in bindings]
    distances = []
    for b in bindings:
        d = b.get("dist", {}).get("value", "0")
        try:
            distances.append(float(d))
        except ValueError:
            distances.append(float("inf"))

    logger.info("  Results:")
    for i, (uri, dist) in enumerate(zip(entity_order, distances)):
        name = uri.split("/")[-1]
        logger.info("    %d. %s  dist=%.0fm", i + 1, name, dist)

    # NYC should be closest to Manhattan
    if "nyc" not in entity_order[0]:
        logger.warning("  Expected NYC first, got: %s", entity_order[0])

    # Distances should be ascending
    for i in range(len(distances) - 1):
        if distances[i] > distances[i + 1]:
            logger.error("  Distances not ascending at position %d", i)
            return False

    logger.info("test_geo_distance PASSED ✅")
    return True


async def test_within_radius(pool, sidecar_url: str) -> bool:
    """Test vg:withinRadius — should filter to entities within 500km of Manhattan."""
    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        SELECT ?entity
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity <http://vital.ai/ontology/vital-core#vitaltype> <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
            }}
            FILTER(vg:withinRadius(?entity, {QUERY_LAT}, {QUERY_LON}, {QUERY_RADIUS_M}))
        }}
    """

    result = await run_sparql_v2(pool, sidecar_url, sparql)

    if "error" in result and result["error"]:
        logger.error("test_within_radius FAILED: %s", result["error"])
        return False

    bindings = result["bindings"]
    logger.info("test_within_radius: %d results", len(bindings))
    logger.info("  SQL: %s", result["sql"][:200])

    entity_uris = [b.get("entity", {}).get("value", "") for b in bindings]
    entity_names = [u.split("/")[-1] for u in entity_uris]
    logger.info("  Entities within %dkm: %s", QUERY_RADIUS_M // 1000, entity_names)

    # NYC (~5km) and Boston (~300km) should be within 500km
    # London (~5500km), Tokyo (~11000km), Paris (~5800km) should be OUT
    found_nyc = any("nyc" in u for u in entity_uris)
    found_boston = any("boston" in u for u in entity_uris)
    found_london = any("london" in u for u in entity_uris)
    found_tokyo = any("tokyo" in u for u in entity_uris)

    if not found_nyc:
        logger.error("  NYC should be within radius!")
        return False
    if not found_boston:
        logger.error("  Boston should be within radius!")
        return False
    if found_london:
        logger.error("  London should NOT be within radius!")
        return False
    if found_tokyo:
        logger.error("  Tokyo should NOT be within radius!")
        return False

    logger.info("test_within_radius PASSED ✅")
    return True


async def test_combined_vector_geo(pool, sidecar_url: str) -> bool:
    """Test combining vector similarity with geo distance filter."""
    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        SELECT ?entity ?score ?dist
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity <http://vital.ai/ontology/vital-core#vitaltype> <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
            }}
            BIND(vg:vectorNearby(?entity, "{QUERY_VECTOR}", "{INDEX_NAME}") AS ?score)
            BIND(vg:geoDistance(?entity, {QUERY_LAT}, {QUERY_LON}) AS ?dist)
            FILTER(vg:withinRadius(?entity, {QUERY_LAT}, {QUERY_LON}, {QUERY_RADIUS_M}))
        }}
        ORDER BY DESC(?score)
    """

    result = await run_sparql_v2(pool, sidecar_url, sparql)

    if "error" in result and result["error"]:
        logger.error("test_combined_vector_geo FAILED: %s", result["error"])
        return False

    bindings = result["bindings"]
    logger.info("test_combined_vector_geo: %d results", len(bindings))
    logger.info("  SQL: %s", result["sql"][:200])

    if len(bindings) == 0:
        logger.error("test_combined_vector_geo FAILED: no results")
        return False

    logger.info("  Results (within %dkm, sorted by vector similarity):", QUERY_RADIUS_M // 1000)
    for i, b in enumerate(bindings):
        uri = b.get("entity", {}).get("value", "")
        score = b.get("score", {}).get("value", "?")
        dist = b.get("dist", {}).get("value", "?")
        name = uri.split("/")[-1]
        logger.info("    %d. %s  score=%s  dist=%sm", i + 1, name, score, dist)

    # Should only include NYC and Boston (within 500km)
    entity_uris = [b.get("entity", {}).get("value", "") for b in bindings]
    if len(entity_uris) != 2:
        logger.warning("  Expected 2 results (NYC, Boston), got %d", len(entity_uris))

    # Should be ordered by score DESC (NYC > Boston since NYC embedding is more similar)
    if len(bindings) >= 2:
        s1 = float(bindings[0].get("score", {}).get("value", "0"))
        s2 = float(bindings[1].get("score", {}).get("value", "0"))
        if s1 < s2:
            logger.error("  Scores not descending!")
            return False

    logger.info("test_combined_vector_geo PASSED ✅")
    return True


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

async def cleanup_test_space(pool):
    """Drop all test space tables."""
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    schema = SparqlSQLSchema()

    async with pool.acquire() as conn:
        vec_table = schema.vec_table_name(SPACE_ID, INDEX_NAME)
        await conn.execute(f"DROP TABLE IF EXISTS {vec_table} CASCADE")

        drop_stmts = schema.drop_space_tables_sql(SPACE_ID)
        for stmt in drop_stmts:
            try:
                await conn.execute(stmt)
            except Exception:
                pass

    logger.info("Cleanup complete")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    import asyncpg

    db_host = os.environ.get("LOCAL_DB_HOST", "localhost")
    if db_host == "host.docker.internal":
        db_host = "localhost"  # Running outside Docker
    db_port = os.environ.get("LOCAL_DB_PORT", "5432")
    db_name = os.environ.get("LOCAL_DB_NAME", "sparql_sql_graph")
    db_user = os.environ.get("LOCAL_DB_USERNAME", "postgres")
    db_pass = os.environ.get("LOCAL_DB_PASSWORD", "")
    sidecar_url = os.environ.get("SIDECAR_URL", "http://localhost:7070")

    db_url = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
    logger.info("Connecting to %s (sidecar: %s)", db_url.split("@")[1], sidecar_url)

    pool = await asyncpg.create_pool(db_url, min_size=2, max_size=4)

    try:
        # Setup
        ok = await setup_test_space(pool)
        if not ok:
            logger.error("Setup failed — aborting")
            return

        # Run tests
        results = {}
        results["vector_nearby"] = await test_vector_nearby(pool, sidecar_url)
        results["geo_distance"] = await test_geo_distance(pool, sidecar_url)
        results["within_radius"] = await test_within_radius(pool, sidecar_url)
        results["combined_vector_geo"] = await test_combined_vector_geo(pool, sidecar_url)

        # Summary
        passed = sum(1 for v in results.values() if v)
        total = len(results)
        logger.info("")
        logger.info("=" * 60)
        logger.info("  RESULTS: %d/%d passed", passed, total)
        logger.info("=" * 60)
        for name, ok in results.items():
            logger.info("  %s %s", "✅" if ok else "❌", name)

        if passed < total:
            sys.exit(1)

    finally:
        # Cleanup
        await cleanup_test_space(pool)
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
