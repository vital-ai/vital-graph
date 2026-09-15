"""Benches for the SPARQL shapes nothing else measures (`issues/193`).

`issues/193` counted the operators appearing anywhere in `tests/performance`:
`OPTIONAL`, `MINUS`, `BIND`, sub-SELECT, property paths and `REGEX`/`CONTAINS`/
`LCASE` appeared **zero** times. The optimiser work lands in the SPARQL->SQL
pipeline and the recent defects are all SHAPE defects — `178` (a CONSTRUCT
losing half its triples and spending 58 s in generation), `179` (LCASE defeating
the trigram index), `180` (a union-bound variable forcing a null-tolerant join),
`182` (a CONSTRUCT enumerating every frame). Every one was found by hand, on a
real query, after it was already slow, and not one could regress into a red cell.

This does not try to cover SPARQL. It covers the shapes with a defect history,
so the fixes have something holding them.

WHY BUFFERS AND ROWS, NOT MILLISECONDS. Buffers are a property of the plan and
do not move with what else the machine is doing, which is what makes them
comparable across runs — the fence bench uses them for the same reason. Rows are
recorded and ASSERTED because a shape that matches nothing is fast and tells you
nothing: this suite has repeatedly produced "improvements" that were queries
quietly matching zero rows, which is why every case here carries a floor.

The floors are deliberately loose. They exist to catch a query that stopped
matching, not to pin a count that moves with the fixture.
"""
from __future__ import annotations

import pytest

from .conftest import skip_no_pg
from .harness import explain_json, total_shared_buffers
from .test_generated_sql_plans import _generate_sql

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

SPACE = "sp_lead_synth_10k"
GRAPH = "urn:sp_lead_synth_10k"

KG = "http://vital.ai/ontology/haley-ai-kg#"
CORE = "http://vital.ai/ontology/vital-core#"
PREFIXES = f"""
PREFIX haley: <{KG}>
PREFIX vital-core: <{CORE}>
"""


def _q(body: str) -> str:
    return f"{PREFIXES}\nSELECT * WHERE {{ GRAPH <{GRAPH}> {{\n{body}\n}} }} LIMIT 25"


# (id, min_rows, body). `min_rows` is the floor described above.
SHAPES = [
    ("optional", 1, """
        ?f vital-core:vitaltype haley:KGFrame .
        OPTIONAL { ?f haley:hasKGFrameType ?ft }
    """),
    ("minus", 1, """
        ?s vital-core:vitaltype haley:KGTextSlot .
        MINUS { ?s haley:hasBooleanSlotValue ?b }
    """),
    ("bind", 1, """
        ?s haley:hasTextSlotValue ?v .
        BIND(UCASE(?v) AS ?upper)
    """),
    ("subselect", 1, """
        { SELECT ?f WHERE { ?f vital-core:vitaltype haley:KGFrame } LIMIT 50 }
        ?f haley:hasKGFrameType ?ft .
    """),
    ("property_path_alt", 1, """
        ?e vital-core:hasEdgeSource|vital-core:hasEdgeDestination ?n .
    """),
    # issues/179: LCASE around the searched variable defeats the trigram index
    # that exists to serve CONTAINS. Recorded rather than asserted fast -- the
    # point is that a change in either direction becomes visible.
    ("lcase_contains", 1, """
        ?s haley:hasTextSlotValue ?v .
        FILTER(CONTAINS(LCASE(?v), "a"))
    """),
    # issues/180: a variable bound in both arms of a UNION.
    ("union_bound_var", 1, """
        { ?s haley:hasTextSlotValue ?v } UNION { ?s haley:hasDoubleSlotValue ?v }
    """),
]


@pytest.mark.bench("query.sparql_shape")
@pytest.mark.parametrize("shape_id,min_rows,body", SHAPES,
                         ids=[s[0] for s in SHAPES])
async def test_sparql_shape_is_measured(perf_conn, perf_record, shape_id,
                                        min_rows, body):
    sql = await _generate_sql(perf_conn, _q(body), SPACE)

    # Warmed before it is measured, so the buffer count describes the PLAN and
    # not which of its pages happened to be resident.
    await perf_conn.fetch(sql)
    doc = await explain_json(perf_conn, sql)
    buffers = total_shared_buffers(doc)
    rows = doc["Plan"].get("Actual Rows")

    perf_record(kind="sql", dataset=SPACE,
                metrics={"buffers": buffers, "rows": rows,
                         "sql_chars": len(sql)},
                notes=f"{shape_id} — issues/193 shape coverage")

    assert rows is not None and rows >= min_rows, (
        f"{shape_id} matched {rows} rows (< {min_rows}). A shape that matches "
        f"nothing is fast and measures nothing — check the fixture's predicates "
        f"before reading the buffer count as an improvement.")
