"""The WRITE half of SPARQL UPDATE: what an INSERT and a MODIFY cost.

`test_delete_throughput` benches the delete side — concrete `DELETE DATA`, the
WHERE-bound form, and the sweep that follows. The insert side had nothing, so
`issues/192`'s "SPARQL UPDATE / DELETE" row was half covered while reading as
though it were whole, and `issues/193` counted UPDATE forms at zero.

A write is not symmetric with a delete, which is why this is its own bench:

    INSERT DATA            concrete quads, so every derived-table hook fires
                           inline on subjects the statement already names
    INSERT ... WHERE       the subjects come from a query, so the cost includes
                           finding them before anything is written
    DELETE/INSERT ... WHERE   the MODIFY form — a delete and an insert in one
                           statement, over the same bound subjects

BENCHED TOGETHER FOR THE REASON THE DELETE BENCH GIVES: the interesting number
is the RELATIONSHIP. A modify that costs materially more than its delete plus
its insert is doing the binding work twice, and measuring any one of the three
alone would not show it.

`edge_rows` is recorded beside every timing because the derived tables are the
point. A write that got faster by not maintaining them is not faster, it is
broken — that is `issues/064`, where 20,461 edge rows were left behind and each
one answered a frame traversal with an edge to nowhere.

Ingest tier: it creates a space and writes to it.
"""
from __future__ import annotations

import time

import pytest
from rdflib import URIRef

from .conftest import skip_no_pg
# The fixtures are the delete bench's: a disposable space created through the
# space manager and dropped after. Imported rather than copied so the two write
# benches cannot drift into testing different setups.
from .test_delete_throughput import (  # noqa: F401
    delete_space_impl, delete_space, _edges, _edge_rows,
    VITALTYPE, SLOT_EDGE, HAS_EDGE_SOURCE, HAS_EDGE_DEST, PG)

pytestmark = [pytest.mark.performance, pytest.mark.ingest_bench, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

N_EDGES = 2_000
MARK = URIRef("http://vital.ai/ontology/vital-core#hasName")


def _triples_block(quads):
    """N-Triples-ish body for a concrete INSERT DATA."""
    return "\n".join(f"<{s}> <{p}> <{o}> ." for s, p, o, _g in quads)


@pytest.mark.bench("write.update.insert_vs_modify")
async def test_update_cost_across_the_three_forms(delete_space,
                                                  delete_space_impl,
                                                  perf_record):
    sid = delete_space
    graph = URIRef(f"urn:{sid}:g")
    impl = delete_space_impl

    quads, _uris = _edges(graph, "ins", N_EDGES)

    # 1. INSERT DATA — concrete subjects, hooks fire inline.
    t0 = time.perf_counter()
    await impl.execute_sparql_update(
        sid, f"INSERT DATA {{ GRAPH <{graph}> {{ {_triples_block(quads)} }} }}")
    insert_ms = (time.perf_counter() - t0) * 1000

    async with impl.db_impl.connection_pool.acquire() as conn:
        after_insert_edges = await _edge_rows(conn, sid)

    # 2. INSERT ... WHERE — the subjects come from a query, not the statement.
    t0 = time.perf_counter()
    await impl.execute_sparql_update(sid, f"""
        INSERT {{ GRAPH <{graph}> {{ ?e <{MARK}> "marked" }} }}
        WHERE  {{ GRAPH <{graph}> {{ ?e <{HAS_EDGE_SOURCE}> ?s }} }}""")
    insert_where_ms = (time.perf_counter() - t0) * 1000

    # 3. DELETE/INSERT ... WHERE — the modify form, same bound subjects.
    t0 = time.perf_counter()
    await impl.execute_sparql_update(sid, f"""
        DELETE {{ GRAPH <{graph}> {{ ?e <{MARK}> "marked" }} }}
        INSERT {{ GRAPH <{graph}> {{ ?e <{MARK}> "remarked" }} }}
        WHERE  {{ GRAPH <{graph}> {{ ?e <{MARK}> "marked" }} }}""")
    modify_ms = (time.perf_counter() - t0) * 1000

    async with impl.db_impl.connection_pool.acquire() as conn:
        final_edges = await _edge_rows(conn, sid)
        marked = await conn.fetchval(
            f"SELECT count(*) FROM {sid}_rdf_quad q "
            f"JOIN {sid}_term t ON t.term_uuid = q.object_uuid "
            f"WHERE t.term_text = 'remarked'")

    perf_record(
        kind="sql", dataset=sid,
        metrics={"insert_data_ms": round(insert_ms, 1),
                 "insert_where_ms": round(insert_where_ms, 1),
                 "modify_ms": round(modify_ms, 1),
                 "edges_after_insert": after_insert_edges,
                 "edges_after_modify": final_edges,
                 "remarked_quads": marked,
                 "n_edges": N_EDGES},
        notes=f"SPARQL UPDATE: INSERT DATA / INSERT WHERE / MODIFY over "
              f"{N_EDGES} edges — issues/192")

    # THE DERIVED TABLE IS THE POINT. An insert that did not maintain the edge
    # table would be faster and wrong (issues/064: 20,461 orphan edge rows, each
    # answering a traversal with an edge to nowhere).
    assert after_insert_edges >= N_EDGES, (
        f"INSERT DATA wrote {N_EDGES} edges but the edge table holds "
        f"{after_insert_edges} — the derived table was not maintained, which is "
        f"faster and wrong")
    assert final_edges == after_insert_edges, (
        f"the modify changed the edge count ({after_insert_edges} -> "
        f"{final_edges}); it touched only a name property and should not have")

    # The modify must actually have modified.
    assert marked == N_EDGES, (
        f"MODIFY left {marked} 'remarked' quads, expected {N_EDGES} — the "
        f"statement did not do what it says, so its timing means nothing")
