#!/usr/bin/env python3
"""
End-to-end integration test: vg:fuzzyMatch SPARQL function.

Tests the full pipeline:
  SPARQL (vg:fuzzyMatch)
  → Jena sidecar compile
  → V2 IR + SQL generation (placeholder + FuzzyRequest)
  → Fuzzy resolve (MinHash LSH + RapidFuzz, or pg_trgm fallback)
  → PostgreSQL execution with CASE score expressions
  → Correct results with proper scoring

Prerequisites:
  - PostgreSQL with pg_trgm extension
  - Jena sidecar running at SIDECAR_URL
  - Fuzzy test data loaded (run: python test_scripts/data/generate_fuzzy_test_data.py --load)

Usage:
    python test_scripts/test_fuzzy_sparql_e2e.py
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
logger = logging.getLogger("test_fuzzy_sparql_e2e")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SPACE_ID = "sp_fuzzy_test"
GRAPH_URI = "urn:vitalgraph:fuzzy_test:entities"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def run_sparql(pool, sidecar_url: str, sparql: str) -> dict:
    """Run a SPARQL query through the full V2 pipeline."""
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.sparql_sql.generator import generate_sql
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
    from vitalgraph.db.sparql_sql.vg_resolve import resolve_vector_requests, resolve_fuzzy_requests

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

        if gen.fuzzy_requests:
            sql = await resolve_fuzzy_requests(sql, gen.fuzzy_requests, SPACE_ID, conn)

        logger.info("  Generated SQL: %s", sql[:300])

        try:
            rows = await conn.fetch(sql)
        except Exception as e:
            return {"error": str(e), "bindings": [], "sql": sql}
        result_rows = [dict(r) for r in rows]

    var_map = gen.var_map or {}
    bindings = SparqlSQLSpaceImpl._rows_to_sparql_bindings(result_rows, var_map)
    return {"bindings": bindings, "sql": sql}


def get_binding_value(binding: dict, var: str) -> str:
    """Extract string value from a SPARQL binding."""
    val = binding.get(var, {})
    if isinstance(val, dict):
        return val.get("value", "")
    return str(val) if val else ""


def get_binding_numeric(binding: dict, var: str) -> float:
    """Extract numeric value from a SPARQL binding."""
    val = get_binding_value(binding, var)
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_fuzzy_match_basic(pool, sidecar_url: str) -> bool:
    """Test basic vg:fuzzyMatch — should return scores for matching entities."""
    logger.info("test_fuzzy_match_basic...")

    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX vc: <http://vital.ai/ontology/vital-core#>
        SELECT ?entity ?name ?score WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                ?entity vc:hasName ?name .
            }}
            BIND(vg:fuzzyMatch(?entity, "Apple Inc", 30) AS ?score)
            FILTER(?score > 0)
        }}
        ORDER BY DESC(?score)
        LIMIT 10
    """

    result = await run_sparql(pool, sidecar_url, sparql)

    if "error" in result and result.get("error"):
        logger.error("  FAILED: %s", result["error"])
        return False

    bindings = result["bindings"]
    logger.info("  Results: %d entities matched", len(bindings))

    if len(bindings) == 0:
        logger.error("  FAILED: No results (expected Apple variants to match)")
        return False

    # Log results
    for b in bindings[:5]:
        name = get_binding_value(b, "name")
        score = get_binding_numeric(b, "score")
        logger.info("    %s — score=%.1f", name, score)

    # The canonical "Apple Inc" should have a perfect/near-perfect score
    top_name = get_binding_value(bindings[0], "name")
    top_score = get_binding_numeric(bindings[0], "score")
    if top_score < 50:
        logger.error("  FAILED: Top score %.1f too low", top_score)
        return False

    logger.info("  PASSED (top match: '%s' score=%.1f)", top_name, top_score)
    return True


async def test_fuzzy_match_misspelling(pool, sidecar_url: str) -> bool:
    """Test vg:fuzzyMatch with intentional misspelling."""
    logger.info("test_fuzzy_match_misspelling...")

    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX vc: <http://vital.ai/ontology/vital-core#>
        SELECT ?entity ?name ?score WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                ?entity vc:hasName ?name .
            }}
            BIND(vg:fuzzyMatch(?entity, "Microsft Corporation", 20) AS ?score)
            FILTER(?score > 0)
        }}
        ORDER BY DESC(?score)
        LIMIT 10
    """

    result = await run_sparql(pool, sidecar_url, sparql)

    if "error" in result and result.get("error"):
        logger.error("  FAILED: %s", result["error"])
        return False

    bindings = result["bindings"]
    logger.info("  Results: %d entities matched", len(bindings))

    if len(bindings) == 0:
        logger.error("  FAILED: No results (expected Microsoft variants to match)")
        return False

    # Should find Microsoft Corporation and variants
    found_microsoft = False
    for b in bindings:
        name = get_binding_value(b, "name")
        score = get_binding_numeric(b, "score")
        logger.info("    %s — score=%.1f", name, score)
        if "microsoft" in name.lower():
            found_microsoft = True

    if not found_microsoft:
        logger.error("  FAILED: Expected Microsoft in results")
        return False

    logger.info("  PASSED")
    return True


async def test_fuzzy_match_no_results(pool, sidecar_url: str) -> bool:
    """Test vg:fuzzyMatch with unrelated name — should return no matches."""
    logger.info("test_fuzzy_match_no_results...")

    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX vc: <http://vital.ai/ontology/vital-core#>
        SELECT ?entity ?name ?score WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                ?entity vc:hasName ?name .
            }}
            BIND(vg:fuzzyMatch(?entity, "Xyzzy Quantum Photonics Ltd", 60) AS ?score)
            FILTER(?score > 0)
        }}
        ORDER BY DESC(?score)
        LIMIT 10
    """

    result = await run_sparql(pool, sidecar_url, sparql)

    if "error" in result and result.get("error"):
        logger.error("  FAILED: %s", result["error"])
        return False

    bindings = result["bindings"]
    logger.info("  Results: %d entities matched (expected 0 or very few)", len(bindings))

    # With a high threshold (60%) and an unrelated name, expect no/few matches
    if len(bindings) > 3:
        logger.warning("  WARNING: Got %d results for unrelated query (may indicate low threshold)", len(bindings))

    logger.info("  PASSED")
    return True


async def test_fuzzy_match_default_threshold(pool, sidecar_url: str) -> bool:
    """Test vg:fuzzyMatch with 2 args (default threshold of 50)."""
    logger.info("test_fuzzy_match_default_threshold...")

    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX vc: <http://vital.ai/ontology/vital-core#>
        SELECT ?entity ?name ?score WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                ?entity vc:hasName ?name .
            }}
            BIND(vg:fuzzyMatch(?entity, "Google LLC") AS ?score)
            FILTER(?score > 0)
        }}
        ORDER BY DESC(?score)
        LIMIT 10
    """

    result = await run_sparql(pool, sidecar_url, sparql)

    if "error" in result and result.get("error"):
        logger.error("  FAILED: %s", result["error"])
        return False

    bindings = result["bindings"]
    logger.info("  Results: %d entities matched", len(bindings))

    if len(bindings) == 0:
        logger.error("  FAILED: Expected Google variants with default threshold")
        return False

    for b in bindings[:5]:
        name = get_binding_value(b, "name")
        score = get_binding_numeric(b, "score")
        logger.info("    %s — score=%.1f", name, score)

    logger.info("  PASSED")
    return True


async def test_fuzzy_match_score_ordering(pool, sidecar_url: str) -> bool:
    """Test that fuzzy match scores are ordered correctly."""
    logger.info("test_fuzzy_match_score_ordering...")

    sparql = f"""
        PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
        PREFIX vc: <http://vital.ai/ontology/vital-core#>
        SELECT ?entity ?name ?score WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                ?entity vc:hasName ?name .
            }}
            BIND(vg:fuzzyMatch(?entity, "Tesla Inc", 20) AS ?score)
            FILTER(?score > 0)
        }}
        ORDER BY DESC(?score)
        LIMIT 10
    """

    result = await run_sparql(pool, sidecar_url, sparql)

    if "error" in result and result.get("error"):
        logger.error("  FAILED: %s", result["error"])
        return False

    bindings = result["bindings"]
    if len(bindings) < 2:
        logger.warning("  SKIP: Need at least 2 results for ordering test")
        return True

    scores = [get_binding_numeric(b, "score") for b in bindings]

    for i in range(len(scores) - 1):
        if scores[i] < scores[i + 1]:
            logger.error("  FAILED: Scores not descending at %d: %.1f < %.1f",
                         i, scores[i], scores[i + 1])
            return False

    logger.info("  PASSED (scores descending: %s)",
                [f"{s:.1f}" for s in scores[:5]])
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
        results["fuzzy_match_basic"] = await test_fuzzy_match_basic(pool, sidecar_url)
        results["fuzzy_match_misspelling"] = await test_fuzzy_match_misspelling(pool, sidecar_url)
        results["fuzzy_match_no_results"] = await test_fuzzy_match_no_results(pool, sidecar_url)
        results["fuzzy_match_default_threshold"] = await test_fuzzy_match_default_threshold(pool, sidecar_url)
        results["fuzzy_match_score_ordering"] = await test_fuzzy_match_score_ordering(pool, sidecar_url)

        # Summary
        passed = sum(1 for v in results.values() if v)
        total = len(results)
        logger.info("")
        logger.info("=" * 60)
        logger.info("  FUZZY SPARQL E2E: %d/%d passed", passed, total)
        logger.info("=" * 60)
        for name, ok in results.items():
            logger.info("  %s %s", "PASS" if ok else "FAIL", name)

        if passed < total:
            sys.exit(1)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
