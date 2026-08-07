"""API latency benches for the WordNet SPARQL queries.

Ported from `test_scripts/vitalgraph_client_test/sparql/case_wordnet_*.py`,
which stay in place as manual exploration tools.

The two graph-traversal queries are **imported** from the case module rather
than copied, so they cannot drift from the originals. The aggregate queries are
one-liners defined here.

Two bench groups, deliberately separate — they have different expected shapes
and should never share a threshold:

  query.wordnet.traversal.*   graph traversal over frames (~0.1s)
  query.wordnet.aggregate.*   whole-space scans over 8.58M quads (~1-3s)

Measured at time of writing on the .vital-sourced space (8,582,356 quads /
1,851,810 terms / 285,348 KGFrames): relationships 0.107s, frame UNION 0.162s
(425 rows), triple count 1.136s, entity type counts 2.621s.
"""

from __future__ import annotations

import os
import sys
import time

import pytest

from .conftest import skip_no_api, api_space_exists

pytestmark = [pytest.mark.performance, skip_no_api,
              pytest.mark.asyncio(loop_scope="session")]

SPACE_ID = "wordnet_frames"
GRAPH_URI = "urn:wordnet_frames"

# Import the traversal queries from the original case module so the two cannot
# diverge.  The directory is appended (not inserted) so `sparql` here resolves
# to vitalgraph_client_test/sparql/ and not test_scripts/sparql/ — the same
# shadowing that broke test_sparql_wordnet.py.
_CASE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "test_scripts", "vitalgraph_client_test")
if _CASE_DIR not in sys.path:
    sys.path.append(_CASE_DIR)

try:
    from sparql.case_wordnet_relationship_queries import (  # noqa: E402
        RELATIONSHIPS_SPARQL, FRAME_UNION_SPARQL)
    _HAVE_CASE_QUERIES = True
except Exception as _e:  # pragma: no cover - depends on test_scripts layout
    RELATIONSHIPS_SPARQL = FRAME_UNION_SPARQL = None
    _HAVE_CASE_QUERIES = False

TRIPLE_COUNT_SPARQL = "SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }"
ENTITY_TYPE_COUNTS_SPARQL = (
    "SELECT ?type (COUNT(?s) AS ?count) WHERE { "
    "?s <http://vital.ai/ontology/vital-core#vitaltype> ?type } "
    "GROUP BY ?type ORDER BY DESC(?count)")


async def _query(client, sparql: str):
    """Issue one SPARQL query, return (wall_ms, row_count)."""
    from vitalgraph.model.sparql_model import SPARQLQueryRequest
    req = SPARQLQueryRequest(query=sparql, format="json")
    t0 = time.perf_counter()
    result = await client.execute_sparql_query(SPACE_ID, req)
    wall_ms = (time.perf_counter() - t0) * 1000.0
    bindings = result.results.get("bindings", []) if result.results else []
    return wall_ms, len(bindings)


async def _require_space(client):
    if not await api_space_exists(client, SPACE_ID):
        pytest.skip(f"space {SPACE_ID} not loaded")


# --------------------------------------------------------------------------
# Traversal — the queries the frames dataset exists to exercise
# --------------------------------------------------------------------------

@pytest.mark.bench("query.wordnet.traversal.relationships")
async def test_wordnet_relationships(perf_client, perf_record):
    await _require_space(perf_client)
    if not _HAVE_CASE_QUERIES:
        pytest.skip("case_wordnet_relationship_queries not importable")

    wall_ms, rows = await _query(perf_client, RELATIONSHIPS_SPARQL)
    perf_record(kind="api", dataset=SPACE_ID,
                metrics={"wall_ms": round(wall_ms, 1), "rows": rows},
                notes="happy_words_v2 relationship traversal")
    assert rows > 0, "relationship traversal matched nothing"


@pytest.mark.bench("query.wordnet.traversal.frame_union")
async def test_wordnet_frame_union(perf_client, perf_record):
    await _require_space(perf_client)
    if not _HAVE_CASE_QUERIES:
        pytest.skip("case_wordnet_relationship_queries not importable")

    wall_ms, rows = await _query(perf_client, FRAME_UNION_SPARQL)
    perf_record(kind="api", dataset=SPACE_ID,
                metrics={"wall_ms": round(wall_ms, 1), "rows": rows},
                notes="happy_words_v2 frame UNION")
    assert rows > 0, "frame UNION matched nothing"


# --------------------------------------------------------------------------
# Aggregates — whole-space scans; seconds-scale by nature, not a regression
# --------------------------------------------------------------------------

@pytest.mark.bench("query.wordnet.aggregate.triple_count")
async def test_wordnet_triple_count(perf_client, perf_record):
    await _require_space(perf_client)
    wall_ms, rows = await _query(perf_client, TRIPLE_COUNT_SPARQL)
    perf_record(kind="api", dataset=SPACE_ID,
                metrics={"wall_ms": round(wall_ms, 1), "rows": rows},
                notes="COUNT(*) over the whole space")
    assert rows > 0, "triple count returned no binding"


@pytest.mark.bench("query.wordnet.aggregate.entity_type_counts")
async def test_wordnet_entity_type_counts(perf_client, perf_record):
    await _require_space(perf_client)
    wall_ms, rows = await _query(perf_client, ENTITY_TYPE_COUNTS_SPARQL)
    perf_record(kind="api", dataset=SPACE_ID,
                metrics={"wall_ms": round(wall_ms, 1), "rows": rows},
                notes="GROUP BY vitaltype over the whole space")
    assert rows > 0, "entity type counts matched nothing"
