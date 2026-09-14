"""L2 delete-throughput benchmark: the derived-table cost of removing quads.

`issues/192` ranks this highest of the unbenched surfaces, and the reason is
recorded in two incidents rather than argued:

  * `issues/064` — edge rows left behind on delete: **20,461 orphans across four
    spaces**, 20,306 of them (5.3%) in a production-shaped space, each answering
    frame traversals with an edge to nowhere.
  * `issues/079` — the cleanup that fixes them is O(edge table) and ran INLINE:
    **181,212 ms over 4.98M rows** against a 60 s `command_timeout`, so it was
    cancelled every time and cleaned nothing. It is deferred to `MaintenanceJob`
    now.

A delete is therefore THREE costs, and only the first is visible to the caller:

    concrete DELETE DATA   subjects are enumerable, so the hooks fire inline
    WHERE-bound DELETE     subjects are not, so the space is MARKED and swept later
    the sweep itself       O(edge table), and the one that has surprised us

Benched together because the interesting number is the RELATIONSHIP. A change
that makes the inline path faster by deferring more work to the sweep is not an
improvement, and measuring either alone would report it as one.

WHY BOTH DELETE FORMS. `_concrete_subjects_from_update_ops` enumerates concrete
subjects and syncs them directly; only WHERE-bound subjects defer. A bench that
deleted by concrete URI alone would measure the path that already worked — which
is, per `test_edge_table_sync_on_delete`, why a correctness test for the broken
half was never written either.
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
import pytest_asyncio
from rdflib import URIRef

from .conftest import skip_no_pg

# Mutates: creates a space, writes quads, deletes them. Ingest tier.
pytestmark = [pytest.mark.performance, pytest.mark.ingest_bench, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

PG = dict(
    host=os.environ.get("VG_TEST_PG_HOST", "localhost"),
    port=int(os.environ.get("VG_TEST_PG_PORT", "5433")),
    database=os.environ.get("VG_TEST_PG_DATABASE", "sparql_sql_graph"),
    user=os.environ.get("VG_TEST_PG_USER", "postgres"),
    password=os.environ.get("VG_TEST_PG_PASSWORD", "testpass"),
)

CORE = "http://vital.ai/ontology/vital-core#"
HALEY = "http://vital.ai/ontology/haley-ai-kg#"
VITALTYPE = URIRef(f"{CORE}vitaltype")
HAS_EDGE_SOURCE = URIRef(f"{CORE}hasEdgeSource")
HAS_EDGE_DEST = URIRef(f"{CORE}hasEdgeDestination")
SLOT_EDGE = URIRef(f"{HALEY}Edge_hasKGSlot")

# Enough that the sweep's O(edge table) shape is visible above fixed costs, and
# small enough that the bench is not itself a load test. 2,000 edges is 6,000
# quads and ~2,000 edge rows.
N_EDGES = 2_000


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def delete_space_impl():
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
    impl = SparqlSQLSpaceImpl(
        postgresql_config={"host": PG["host"], "port": PG["port"],
                           "database": PG["database"], "username": PG["user"],
                           "password": PG["password"],
                           "min_pool_size": 1, "max_pool_size": 4},
        sidecar_config={"url": os.environ.get("VG_TEST_SIDECAR_URL",
                                              "http://localhost:7071")})
    await impl.connect()
    yield impl
    await impl.disconnect()


@pytest_asyncio.fixture(loop_scope="session")
async def delete_space(delete_space_impl):
    from vitalgraph.space.space_manager import SpaceManager
    mgr = SpaceManager(db_impl=getattr(delete_space_impl, "db_impl", None),
                       space_backend=delete_space_impl)
    sid = f"perfdel_{uuid.uuid4().hex[:8]}"
    ok = await mgr.create_space_with_tables(sid, sid)
    if not ok:
        pytest.skip(f"space manager failed to create {sid}")
    yield sid
    try:
        await mgr.delete_space_with_tables(sid)
    except Exception:
        pass


def _edges(graph, tag, n):
    quads, uris = [], []
    for i in range(n):
        e = URIRef(f"urn:perfdel:{tag}:edge:{i}")
        uris.append(str(e))
        quads += [
            (e, VITALTYPE, SLOT_EDGE, graph),
            (e, HAS_EDGE_SOURCE, URIRef(f"urn:perfdel:{tag}:src:{i}"), graph),
            (e, HAS_EDGE_DEST, URIRef(f"urn:perfdel:{tag}:dst:{i}"), graph),
        ]
    return quads, uris


async def _edge_rows(conn, sid):
    return await conn.fetchval(f"SELECT count(*) FROM {sid}_edge")


async def _orphans(conn, sid):
    """Edge rows whose defining quads are gone. Referential, never by count —
    an orphan is an EXTRA row, so a count check reads it as healthy."""
    return await conn.fetchval(f"""
        SELECT count(*) FROM {sid}_edge e
        WHERE NOT EXISTS (
            SELECT 1 FROM {sid}_rdf_quad q
            JOIN {sid}_term p ON p.term_uuid = q.predicate_uuid
            WHERE q.subject_uuid = e.edge_uuid
              AND q.context_uuid = e.context_uuid
              AND p.term_text = '{CORE}hasEdgeSource')""")


@pytest.mark.bench("write.delete.concrete_vs_deferred")
async def test_delete_cost_across_both_paths(delete_space, delete_space_impl,
                                             perf_pool, perf_record):
    from vitalgraph.db.sparql_sql.sync_edge_table import (
        take_sweep_pending, cleanup_orphan_edges)

    sid = delete_space
    graph = URIRef(f"urn:{sid}:g")
    impl = delete_space_impl

    quads_c, uris_c = _edges(graph, "conc", N_EDGES // 2)
    quads_w, _uris_w = _edges(graph, "where", N_EDGES // 2)
    t0 = time.perf_counter()
    await impl.add_rdf_quads_batch(sid, quads_c + quads_w)
    seed_s = time.perf_counter() - t0

    async with perf_pool.acquire() as conn:
        seeded_edges = await _edge_rows(conn, sid)
    assert seeded_edges >= N_EDGES * 0.9, (
        f"seed produced {seeded_edges} edge rows for {N_EDGES} edges — the "
        f"bench would measure deleting nothing")
    take_sweep_pending()                      # discard marks from seeding

    # 1. CONCRETE: subjects are enumerable, so the sync runs inline.
    triples = " ".join(
        f"<{u}> <{HAS_EDGE_SOURCE}> <urn:perfdel:conc:src:{i}> . "
        f"<{u}> <{HAS_EDGE_DEST}> <urn:perfdel:conc:dst:{i}> ."
        for i, u in enumerate(uris_c))
    t0 = time.perf_counter()
    await impl.execute_sparql_update(
        sid, f"DELETE DATA {{ GRAPH <{graph}> {{ {triples} }} }}")
    concrete_s = time.perf_counter() - t0

    async with perf_pool.acquire() as conn:
        after_concrete = await _orphans(conn, sid)

    # 2. WHERE-BOUND: nothing can enumerate the subjects, so the space is marked
    #    and the orphans survive until the sweep.
    t0 = time.perf_counter()
    await impl.execute_sparql_update(sid, f"""
        DELETE {{ GRAPH <{graph}> {{ ?e <{HAS_EDGE_SOURCE}> ?s }} }}
        WHERE  {{ GRAPH <{graph}> {{ ?e <{HAS_EDGE_SOURCE}> ?s .
                                     ?e <{VITALTYPE}> <{SLOT_EDGE}> }} }}""")
    where_s = time.perf_counter() - t0
    marked = sid in take_sweep_pending()

    async with perf_pool.acquire() as conn:
        before_sweep = await _orphans(conn, sid)
        # 3. THE SWEEP — O(edge table), and the cost issues/079 records at
        #    181,212 ms over 4.98M rows when it ran inline.
        t0 = time.perf_counter()
        await cleanup_orphan_edges(conn, sid)
        sweep_s = time.perf_counter() - t0
        after_sweep = await _orphans(conn, sid)

    n_c, n_w = len(quads_c), len(quads_w)
    perf_record(
        kind="write", dataset=f"synthetic:{N_EDGES}edges",
        metrics={
            "seed_quads_per_sec": round((n_c + n_w) / seed_s),
            "concrete_quads_per_sec": round(n_c / concrete_s),
            "where_bound_quads_per_sec": round(n_w / where_s),
            "concrete_s": round(concrete_s, 3),
            "where_bound_s": round(where_s, 3),
            "sweep_s": round(sweep_s, 3),
            # What the caller pays against what is deferred. A change that makes
            # the WHERE path look fast by deferring more work moves this, and
            # neither half alone would show it.
            "deferred_share": round(sweep_s / (where_s + sweep_s), 3)
            if (where_s + sweep_s) else 0.0,
            "orphans_before_sweep": before_sweep,
        },
        notes="issues/192 — concrete vs WHERE-bound delete and the deferred "
              "referential sweep (issues/064, issues/079)")

    assert after_concrete == 0, (
        f"{after_concrete} orphan(s) after a CONCRETE delete — that path syncs "
        f"inline, so orphans here mean the inline hooks stopped firing "
        f"(issues/064)")
    assert marked, (
        "the WHERE-bound delete did not mark the space for the sweep, so its "
        "orphans would never be cleaned (issues/064)")
    assert after_sweep == 0, (
        f"the sweep left {after_sweep} orphan(s) of {before_sweep}")
