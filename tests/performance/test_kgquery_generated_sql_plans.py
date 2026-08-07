"""Plan-shape gates for the SQL a KGQuery ends up producing.

Closes the last uncovered link in the chain. Three benches now watch different
segments of it:

    KGQueryCriteria ──► SPARQL ──► SQL ──► plan
    └───────────────── this file ────────────────┘
                       └── test_generated_sql_plans.py ──┘  (SPARQL written by hand)
    └── test_lead_kgquery_bench.py ──┘                      (wall_ms + result count)

`test_generated_sql_plans.py` starts from hand-written SPARQL, so it cannot see
a regression in `KGQueryCriteria` → SPARQL translation. `test_lead_kgquery_bench.py`
drives the real API but records only `wall_ms` and result counts, so a plan
regression there shows up as timing noise at best. This file mirrors
`KGQueryEndpoint._execute_frame_query` — converting KGQueryCriteria to the
builder's own types and calling `KGQueryCriteriaBuilder.build_entity_query_sparql`
— then compiles that SPARQL and asserts on the resulting plan.

Note it is *not* `KGConnectionQueryBuilder.build_frame_query`, despite the name
matching `query_type="frame"`. That builder ignores nested frame/slot criteria:
driving it here produced byte-identical SPARQL for three different criteria and
matched zero rows. The endpoint does not use it for this query type either.

What that catches: a criteria change that emits a pattern the generator can no
longer push down, a lost graph constraint, a slot filter that stops reaching an
index — none of which alter the result count, so none of which the API bench
would flag.

The criteria mirror `test_lead_kgquery_bench.py`, which mirrors
`test_scripts/vitalgraph_client_test/entity_graph_lead_dataset/case_kgquery_lead_queries.py`.
Change one, change the others.
"""

from __future__ import annotations

import os

import pytest

from .conftest import skip_no_pg, space_exists
from .harness import assert_plan, node_types

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

SPACE_ID = "sp_sql_lead_dataset"
GRAPH_ID = "urn:sql_lead_dataset"
SIDECAR_URL = os.environ.get("VG_TEST_SIDECAR_URL", "http://localhost:7071")

NS = "urn:acme:kg"
BOOLEAN_SLOT = "http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot"
TEXT_SLOT = "http://vital.ai/ontology/haley-ai-kg#KGTextSlot"
DOUBLE_SLOT = "http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot"
KGENTITY = "http://vital.ai/ontology/haley-ai-kg#KGEntity"


def _slot(slot_type, slot_class_uri, value, comparator="eq"):
    from vitalgraph.model.kgentities_model import SlotCriteria
    return SlotCriteria(slot_type=slot_type, slot_class_uri=slot_class_uri,
                        value=value, comparator=comparator)


def _frame(frame_type, slots=None, children=None):
    from vitalgraph.model.kgentities_model import FrameCriteria
    kw = {"frame_type": frame_type}
    if slots:
        kw["slot_criteria"] = slots
    if children:
        kw["frame_criteria"] = children
    return FrameCriteria(**kw)


def _criteria(frame_criteria):
    from vitalgraph.model.kgqueries_model import KGQueryCriteria
    from vitalgraph.model.kgentities_model import EntityQueryCriteria
    return KGQueryCriteria(
        query_type="frame",
        query_mode="edge",
        source_entity_criteria=EntityQueryCriteria(entity_type=KGENTITY),
        frame_criteria=frame_criteria,
        exclude_self_connections=True,
    )


CASES = [
    (
        "mql",
        "MQL boolean slot under a nested frame",
        lambda: [_frame(f"{NS}:frame:LeadStatusFrame", children=[
            _frame(f"{NS}:frame:LeadStatusQualificationFrame",
                   slots=[_slot(f"{NS}:slot:MQLv2", BOOLEAN_SLOT, True)])])],
    ),
    (
        "state_ca",
        "text slot under a nested frame",
        lambda: [_frame(f"{NS}:frame:CompanyFrame", children=[
            _frame(f"{NS}:frame:CompanyAddressFrame",
                   slots=[_slot(f"{NS}:slot:CompanyStateCode",
                                TEXT_SLOT, "CA")])])],
    ),
    (
        "high_rated",
        "double slot with a range comparator (gte)",
        lambda: [_frame(f"{NS}:frame:LeadStatusFrame", children=[
            _frame(f"{NS}:frame:LeadStatusQualificationFrame",
                   slots=[_slot(f"{NS}:slot:MQLRating", DOUBLE_SLOT, 65.0,
                                comparator="gte")])])],
    ),
]


def _to_builder_frame(frame_crit):
    """Mirror the endpoint's KGQueryCriteria → builder-type conversion.

    `KGQueryEndpoint._execute_frame_query` does exactly this before calling
    `build_entity_query_sparql`. Note it does NOT use
    `KGConnectionQueryBuilder.build_frame_query`, despite the name — that
    builder ignores nested frame/slot criteria entirely, so driving it here
    produced identical SPARQL for three different criteria and zero rows.
    """
    from vitalgraph.sparql.kg_query_builder import (
        FrameCriteria as BuilderFrameCriteria,
        SlotCriteria as BuilderSlotCriteria)

    slots = None
    if frame_crit.slot_criteria:
        slots = [BuilderSlotCriteria(
            slot_type=s.slot_type, slot_class_uri=s.slot_class_uri,
            value=s.value,
            comparator=s.comparator or ("eq" if s.value else None))
            for s in frame_crit.slot_criteria]

    nested = None
    if frame_crit.frame_criteria:
        nested = [_to_builder_frame(f) for f in frame_crit.frame_criteria]

    return BuilderFrameCriteria(
        frame_type=frame_crit.frame_type,
        negate=getattr(frame_crit, "negate", False),
        slot_criteria=slots,
        frame_criteria=nested)


async def _criteria_to_sql(conn, frame_criteria) -> tuple[str, str]:
    """KGQueryCriteria → SPARQL → SQL. Returns (sparql, sql)."""
    from vitalgraph.sparql.kg_query_builder import (
        KGQueryCriteriaBuilder, EntityQueryCriteria as BuilderEntityQueryCriteria)
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    entity_criteria = BuilderEntityQueryCriteria(
        entity_type=KGENTITY,
        entity_uris=None,
        frame_criteria=[_to_builder_frame(f) for f in frame_criteria],
        use_edge_pattern=True,          # query_mode="edge", as the API benches use
    )
    sparql = KGQueryCriteriaBuilder().build_entity_query_sparql(
        entity_criteria, GRAPH_ID, 25, 0)

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
        # A builder change that emits SPARQL the sidecar rejects is a real
        # regression, not a reason to skip — fail loudly.
        pytest.fail(f"KGQuery SPARQL failed to compile: {cr.error}\n\n{sparql}")

    gen = await generate_sql(cr, SPACE_ID, conn=conn)
    return sparql, gen.sql


@pytest.mark.bench("query.kgquery.generated_sql.plan")
@pytest.mark.parametrize("suffix,description,factory", CASES,
                         ids=[c[0] for c in CASES])
async def test_kgquery_plan_shape(perf_conn, perf_record, suffix,
                                  description, factory):
    if not await space_exists(perf_conn, SPACE_ID):
        pytest.skip(f"space {SPACE_ID} not loaded")

    sparql, sql = await _criteria_to_sql(perf_conn, factory())

    # Without this the bench is worthless: driving the wrong builder produced
    # SPARQL that ignored the criteria and matched nothing, and every upper-bound
    # assertion passed happily on an empty result.
    assert f"{NS}:slot:" in sparql, (
        f"generated SPARQL contains no slot constraint — the criteria are not "
        f"reaching the builder:\n{sparql[:500]}")

    plan = await assert_plan(
        perf_conn, sql,
        no_seq_scan_on=[f"{SPACE_ID}_rdf_quad"],
        no_spill=True,
        min_actual_rows=1,
    )

    perf_record(plan=plan, dataset=SPACE_ID,
                metrics={"sparql_chars": len(sparql),
                         "sql_chars": len(sql),
                         "joins": sql.upper().count(" JOIN ")},
                notes=description)
