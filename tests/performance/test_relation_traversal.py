"""Relations — the model shape where fan-out INVERTS, and the only one with no bench.

`sp_kg_rel` holds 16,043 `Edge_hasKGRelation` against 96 in the entire rest of
the database, and until now it was referenced by one integration test and no
performance test at all. That matters more than an ordinary coverage gap,
because every traversal decision in `issues/059`-`061` was measured on the
CONTAINMENT half of the model, where backward-is-safe holds by construction — a
slot has one parent, a frame none or one:

    containment (Edge_hasKGSlot)   forward 2.00   backward 1.00
    worksFor                       forward 1.00   backward 39.00, p99 468, max 886

MEASURED 2026-08-12, and the direction machinery is CORRECT on relation data:

    worksFor    backward REJECTED (tail 468 > 16)   forward safe   -> forward
    reportsTo   both safe (4.8 / 1.0)                              -> backward
    friendOf    both safe (3.0 / 3.0)                              -> backward
    mentions    both safe (1.4 / 1.5)                              -> backward

That is the assertion the tree-only fixtures could not make, and it is the main
thing this file exists to keep true.

WHAT THE MEASUREMENT ALSO FOUND. A shape the fan-out model does not describe:

    worksFor 1 hop, complete            21 ms         4,875 rows
    reportsTo -> worksFor, 2 hops       41 ms         4,750 rows
    worksFor -> worksFor (convergent) 4,860 ms     1,313,755 rows

The last is two edges CONVERGING on a shared destination — "everyone who shares
an employer" — not a chain. `assess_traversal` models chains and calls it
amplification 1.0, correctly for what it models. The cost is real, it is not a
defect (1.3M pairs is the right answer), and it is quadratic in fan-in: one
employer with 886 employees contributes 886^2 pairs by itself. On a fixture with
4,875 such edges. That is the relation-specific scaling hazard, and it is
recorded here rather than fixed because the query is correct.
"""

from __future__ import annotations

import time

import pytest

from .test_kgquery_growth_curve import SIDECAR_URL, skip_no_pg

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

SPACE = "sp_kg_rel"
GRAPH = "urn:sp_kg_rel"
CORE = "http://vital.ai/ontology/vital-core#"
KG = "http://vital.ai/ontology/haley-ai-kg#"
REL_EDGE = f"{KG}Edge_hasKGRelation"

# Fan-in on this fixture: one employer has 886 employees, so the convergent
# two-hop shape produces ~1.3M pairs. Gated on ROWS, not milliseconds — the row
# count is the property that is quadratic and it does not move with the machine.
CONVERGENT_ROWS_ALARM = 3_000_000


async def _skip_unless_fixture(conn):
    exists = await conn.fetchval(
        "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
        f"{SPACE}_rdf_quad")
    if not exists:
        pytest.skip(f"{SPACE} not loaded — the only fixture with relation edges")
    n = await conn.fetchval(f"SELECT count(*) FROM {SPACE}_edge_fanout")
    if not n:
        pytest.skip(f"{SPACE} has no recorded fan-out; run the fan-out sync first")


def _hop(e, src, dst, rel):
    R = f"<urn:acme:kg:rel_type:{rel}>"
    return (f"?{e} <{CORE}vitaltype> <{REL_EDGE}> . "
            f"?{e} <{KG}hasKGRelationType> {R} . "
            f"?{e} <{CORE}hasEdgeSource> ?{src} . "
            f"?{e} <{CORE}hasEdgeDestination> ?{dst} . ")


async def _run(conn, sparql):
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
        pytest.fail(f"relation traversal failed to compile: {cr.error}")
    gen = await generate_sql(cr, SPACE, conn=conn)
    if not gen.ok:
        pytest.fail(f"relation traversal failed to generate SQL: {gen.error}")

    await conn.fetch(gen.sql)                       # warm
    runs = []
    for _ in range(3):
        t0 = time.perf_counter()
        rows = await conn.fetch(gen.sql)
        runs.append((time.perf_counter() - t0) * 1000.0)
    return sorted(runs)[1], len(rows)


@pytest.mark.bench("query.relation.direction_choice")
async def test_the_inverted_relation_is_not_walked_backward(perf_conn, perf_record):
    """`worksFor` backward must be REJECTED, and forward chosen.

    This is the assertion `issues/061` says could not be made: backward-is-safe
    is true for containment BY CONSTRUCTION and FALSE for relations, and every
    direction decision was validated on containment only. On real relation data
    the gate does the right thing — `worksFor` has backward p99 468 against a
    threshold of 16, so backward is unsafe and forward (1.0) is taken.

    A regression here is silent and expensive: walking backward would probe up
    to 886 rows per node where forward probes one.
    """
    from vitalgraph.db.sparql_sql.sync_edge_fanout import (
        load_edge_fanout, assess_traversal, choose_direction)

    await _skip_unless_fixture(perf_conn)
    fanout = await load_edge_fanout(perf_conn, SPACE)

    rows = await perf_conn.fetch(
        f"SELECT term_uuid, term_text FROM {SPACE}_term "
        f"WHERE term_text LIKE '%rel_type:%'")
    by_name = {r["term_text"].split(":")[-1]: r["term_uuid"] for r in rows}
    edge_uuid = await perf_conn.fetchval(
        f"SELECT term_uuid FROM {SPACE}_term WHERE term_text = $1", REL_EDGE)
    if "worksFor" not in by_name or edge_uuid is None:
        pytest.skip("fixture does not carry the worksFor relation type")

    hops = [(edge_uuid, by_name["worksFor"])]
    back = assess_traversal(fanout, hops, "backward")
    fwd = assess_traversal(fanout, hops, "forward")
    chosen = choose_direction(fanout, hops)

    perf_record(kind="sql", dataset=SPACE,
                metrics={"worksfor_backward_safe": int(bool(back["safe"])),
                         "worksfor_forward_safe": int(bool(fwd["safe"]))},
                notes="relation direction choice — issues/061")

    assert not back["safe"], (
        f"worksFor BACKWARD was judged safe ({back['reason']}). Its fan-in is "
        f"39 average, p99 468, max 886 — walking it backward probes up to 886 "
        f"rows per node. Backward-is-safe holds for containment by "
        f"construction and is false here (issues/061).")
    assert fwd["safe"], (
        f"worksFor FORWARD was judged unsafe ({fwd['reason']}) — its fan-out is "
        f"1.0, so if this direction is refused the traversal has no safe option "
        f"at all and every relation query declines the fast path.")
    assert chosen["direction"] == "forward"


@pytest.mark.bench("query.relation.single_hop")
@pytest.mark.parametrize("rel", ["worksFor", "reportsTo", "friendOf"])
async def test_a_complete_single_hop_traversal(perf_conn, perf_record, rel):
    """One hop, no LIMIT — the whole relation walked.

    Deliberately unbounded: with a `LIMIT` these all return in ~1 ms because
    the scan stops, which measures early termination rather than traversal.
    """
    await _skip_unless_fixture(perf_conn)
    ms, rows = await _run(perf_conn,
        f"SELECT ?s ?d WHERE {{ GRAPH <{GRAPH}> {{ {_hop('e','s','d',rel)} }} }}")

    perf_record(kind="sql", dataset=SPACE,
                metrics={f"rel_{rel.lower()}_ms": round(ms, 1),
                         f"rel_{rel.lower()}_rows": rows},
                notes=f"complete single-hop {rel} traversal")
    assert rows > 0, (
        f"{rel} returned no rows — the fixture or the relation type changed, "
        f"and a traversal bench that matches nothing looks like a speed-up")


@pytest.mark.bench("query.relation.convergent_fan_in")
async def test_convergent_two_hop_is_quadratic_in_fan_in(perf_conn, perf_record):
    """Two edges CONVERGING on one destination — "who shares my employer".

    Not a chain, so `assess_traversal` does not model it and calls the path
    amplification 1.0 — correctly, for what it models. The cost is real and is
    quadratic in fan-in: one employer with 886 employees contributes 886^2 pairs
    on its own, and 4,875 edges produce 1,313,755 rows.

    Gated on ROW COUNT rather than time, because the row count is the quadratic
    property and it does not move with the machine or the buffer pool. A jump
    here means the fixture's fan-in distribution changed, which would silently
    invalidate every direction assertion above it.
    """
    await _skip_unless_fixture(perf_conn)
    ms, rows = await _run(perf_conn,
        f"SELECT ?a ?c WHERE {{ GRAPH <{GRAPH}> {{ "
        f"{_hop('e1','a','b','worksFor')}{_hop('e2','c','b','worksFor')} }} }}")

    perf_record(kind="sql", dataset=SPACE,
                metrics={"convergent_ms": round(ms, 1), "convergent_rows": rows},
                notes="convergent two-hop, quadratic in fan-in — relations")

    assert rows > 0, "the convergent shape returned nothing; fixture changed"
    assert rows < CONVERGENT_ROWS_ALARM, (
        f"the convergent two-hop shape produced {rows:,} rows (was 1,313,755). "
        f"This is quadratic in fan-in, so a change in the fixture's employer "
        f"distribution moves it sharply — and every direction threshold in "
        f"sync_edge_fanout was chosen against the old distribution.")
