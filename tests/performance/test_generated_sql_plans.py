"""Plan-shape gates for the SQL the SPARQL generator emits.

This is the coverage hole the rest of the suite left open. Every other
plan-shape bench here asserts on **hand-written** SQL that mirrors what a fast
path does — none of them touch the SQL that SPARQL→SQL generation actually
produces. So a generator regression (an index dropped from a join, a seq scan
creeping in, a filter stopping its push-down) would show up only as `exec_ms`
drifting on the API benches, which is report-only and after the fact.

This closes it the same way the rest of the suite works: compile the query
in-process, then run the existing `assert_plan` harness over the generated SQL.
The gate is the plan *shape*, which is size-independent and deterministic —
not wall-clock.

Why in-process rather than through the REST endpoint: the generated SQL is not
exposed in the response (deliberately — it can run to thousands of characters),
and EXPLAIN needs a database connection anyway. This is the layer the assertion
belongs at.

This supersedes reviving `vitalgraph_sparql_sql_dev/scripts/kgquery_perf_bench.py`,
which measured the same pipeline in-process but is dead on the
`vitalgraph_sparql_sql` → `_dev` package rename and additionally references
modules that have since moved into `vitalgraph/db/`. The per-stage attribution
that script provided now comes from `SPARQLQueryResponse.timing`; what it could
not give — a gated plan assertion — is what this file adds.
"""

from __future__ import annotations

import os

import pytest

from .conftest import skip_no_pg, space_exists
from .harness import (assert_plan, explain_json, node_types,
                      total_shared_buffers, has_seq_scan_on)

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

SPACE_ID = "wordnet_frames"
GRAPH_URI = "urn:wordnet_frames"
SIDECAR_URL = os.environ.get("VG_TEST_SIDECAR_URL", "http://localhost:7071")

VITALTYPE = "http://vital.ai/ontology/vital-core#vitaltype"
KGENTITY = "http://vital.ai/ontology/haley-ai-kg#KGEntity"
HASNAME = "http://vital.ai/ontology/vital-core#hasName"

LEAD_SPACE = "sp_sql_lead_dataset"
LEAD_GRAPH = "urn:sql_lead_dataset"
BOOL_SLOT_VALUE = "http://vital.ai/ontology/haley-ai-kg#hasBooleanSlotValue"
KG_ENTITY_TYPE = "http://vital.ai/ontology/haley-ai-kg#hasKGEntityType"

# (bench_suffix, description, space_id, sparql)
#
# Kept small and representative rather than exhaustive: a typed listing page, a
# single-predicate scan, and a two-hop join. These are the shapes whose plans
# matter, and each would show a different generator regression.
#
# The lead cases exist because the API benches for the same queries record
# `wall_ms` only, so a structural improvement there was invisible — the
# idx_*_quad_ctx_pred fix (issues/039) took that shape to 5 buffers and no
# bench could see it. Buffers are captured here, exactly, rather than
# approximated with pg_stat deltas around a REST call.
CASES = [
    (
        "typed_listing",
        "typed subject page (the KGEntity listing shape)",
        SPACE_ID,
        f"""SELECT ?s WHERE {{ GRAPH <{GRAPH_URI}> {{
                ?s <{VITALTYPE}> <{KGENTITY}> .
            }} }} LIMIT 25""",
    ),
    (
        "predicate_scan",
        "single bound predicate with a variable object",
        SPACE_ID,
        f"""SELECT ?s ?o WHERE {{ GRAPH <{GRAPH_URI}> {{
                ?s <{HASNAME}> ?o .
            }} }} LIMIT 25""",
    ),
    (
        "two_hop_join",
        "two bound predicates on one subject (join shape)",
        SPACE_ID,
        f"""SELECT ?s ?name WHERE {{ GRAPH <{GRAPH_URI}> {{
                ?s <{VITALTYPE}> <{KGENTITY}> .
                ?s <{HASNAME}> ?name .
            }} }} LIMIT 25""",
    ),
    (
        "lead_slot_value",
        "slot-value filter — graph+predicate+object all bound (issues/039)",
        LEAD_SPACE,
        f"""SELECT ?s WHERE {{ GRAPH <{LEAD_GRAPH}> {{
                ?s <{BOOL_SLOT_VALUE}> true .
            }} }} LIMIT 25""",
    ),
    (
        "lead_entity_type",
        "entity-type filter — the other object-bound listing shape",
        LEAD_SPACE,
        f"""SELECT ?s ?t WHERE {{ GRAPH <{LEAD_GRAPH}> {{
                ?s <{KG_ENTITY_TYPE}> ?t .
            }} }} LIMIT 25""",
    ),
]


async def _generate_sql(conn, sparql: str, space_id: str) -> str:
    """Compile SPARQL → SQL through the real pipeline, returning the SQL."""
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    client = AsyncSidecarClient(SIDECAR_URL)
    try:
        raw = await client.compile(sparql)
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res
    cr = map_compile_response(raw)
    if not cr.ok:
        pytest.skip(f"sidecar could not compile the query: {cr.error}")
    gen = await generate_sql(cr, space_id, conn=conn)
    return gen.sql


@pytest.mark.bench("query.generated_sql.plan")
@pytest.mark.parametrize("suffix,description,space_id,sparql", CASES,
                         ids=[c[0] for c in CASES])
async def test_generated_sql_plan_shape(perf_conn, perf_record, suffix,
                                        description, space_id, sparql):
    if not await space_exists(perf_conn, space_id):
        pytest.skip(f"space {space_id} not loaded")

    sql = await _generate_sql(perf_conn, sparql, space_id)

    # The gate: whatever the generator emits must not seq-scan the quad table
    # and must not spill. Buffer counts are recorded rather than bounded — the
    # baseline detects drift, and a bound tuned on one query shape would be
    # arbitrary across the others.
    plan = await assert_plan(
        perf_conn, sql,
        no_seq_scan_on=[f"{space_id}_rdf_quad"],
        no_spill=True,
        min_actual_rows=1,
    )

    perf_record(plan=plan, dataset=space_id,
                metrics={"sql_chars": len(sql),
                         "joins": sql.upper().count(" JOIN ")},
                notes=description)
