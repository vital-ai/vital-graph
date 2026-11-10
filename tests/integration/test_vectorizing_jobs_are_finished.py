"""Segmentation jobs in 'vectorizing' reach 'completed', and leave with their graph.

Under load, one poller per job on an internal pool of 3 timed out: jobs
were recorded 'completed' with the empty error "Vectorization task failed: ",
or stayed 'vectorizing' for good when the status write timed out too,
although the index sync had embedded every segment. Now one completer per
space checks every waiting job on one connection per tick, a sweep
finishes jobs no waiter is left for, and a dropped graph takes its job rows.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from vitalgraph.db.sparql_sql.space_names import space_prefix
from vitalgraph.document import vectorization_completer as vc
from vitalgraph.vectorization.auto_sync import _generate_term_uuid

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

G = "urn:inttest:vectorizing:g"
G2 = "urn:inttest:vectorizing:g2"


async def _job(conn, space, graph, doc, *, status="vectorizing", age_s=0):
    return await conn.fetchval(
        f"INSERT INTO {space_prefix(space)}_segmentation_jobs "
        f"(space_id, graph_id, document_uri, status, updated_at) "
        f"VALUES ($1, $2, $3, $4, NOW() - make_interval(secs => $5)) RETURNING job_id",
        space, graph, doc, status, float(age_s))


async def _queue(conn, space, graph, subject):
    await conn.execute(
        f"INSERT INTO {space_prefix(space)}_index_sync_queue "
        f"(context_uuid, subject_uuid, operation) VALUES ($1, $2, 'upsert')",
        _generate_term_uuid(graph), _generate_term_uuid(subject))


async def _state(conn, space, job_id):
    r = await conn.fetchrow(
        f"SELECT status, error_message FROM {space_prefix(space)}_segmentation_jobs "
        f"WHERE job_id = $1", job_id)
    return (r["status"], r["error_message"]) if r else None


def _completer(pg_pool, **kw):
    async def pool_for(_space):
        return pg_pool
    return vc.VectorizationCompleter(pool_for, **kw)


async def test_many_jobs_one_connection_per_tick(make_space, pg_pool, pg_conn):
    """300 jobs, half with a subject still queued: one tick completes exactly
    the drained half, on one connection, and leaves the rest waiting."""
    space = await make_space()
    c = _completer(pg_pool)
    jobs = {}
    for i in range(300):
        doc = f"urn:inttest:doc:{i}"
        segs = [f"{doc}_seg_{k}" for k in range(3)]
        jobs[i] = await _job(pg_conn, space, G, doc)
        if i % 2:
            await _queue(pg_conn, space, G, segs[1])
        c.register(space, jobs[i], G, [doc] + segs)

    acquires = 0

    class _Counting:
        def acquire(self):
            nonlocal acquires
            acquires += 1
            return pg_pool.acquire()

    async def pool_for(_space):
        return _Counting()

    c._pool_for = pool_for
    try:
        finished = await c.tick(space)
    finally:
        await c.stop()
    assert acquires == 1
    assert finished == 150
    for i, job_id in jobs.items():
        assert await _state(pg_conn, space, job_id) == (
            ("vectorizing", None) if i % 2 else ("completed", None))
    assert len(c.tracked(space)) == 150


async def test_the_loop_finishes_when_the_queue_drains(make_space, pg_pool, pg_conn):
    space = await make_space()
    c = _completer(pg_pool, poll=0.05)
    job_id = await _job(pg_conn, space, G, "urn:inttest:doc:a")
    await _queue(pg_conn, space, G, "urn:inttest:doc:a_seg_1")
    c.register(space, job_id, G, ["urn:inttest:doc:a", "urn:inttest:doc:a_seg_1"])
    await asyncio.sleep(0.3)
    assert await _state(pg_conn, space, job_id) == ("vectorizing", None)
    await pg_conn.execute(f"DELETE FROM {space_prefix(space)}_index_sync_queue")
    for _ in range(40):
        if c.waiting() == 0:
            break
        await asyncio.sleep(0.05)
    await c.stop()
    assert await _state(pg_conn, space, job_id) == ("completed", None)


async def test_a_failed_tick_keeps_the_jobs(make_space, pg_pool, pg_conn):
    """A pool that cannot give a connection: the jobs stay registered and the
    next tick completes them. Nothing is lost to a timeout."""
    space = await make_space()
    fail = {"on": True}

    class _Flaky:
        def acquire(self):
            if fail["on"]:
                raise TimeoutError()
            return pg_pool.acquire()

    async def pool_for(_space):
        return _Flaky()

    c = vc.VectorizationCompleter(pool_for, poll=0.05)
    job_id = await _job(pg_conn, space, G, "urn:inttest:doc:b")
    c.register(space, job_id, G, ["urn:inttest:doc:b"])
    await asyncio.sleep(0.3)
    assert c.tracked(space) == [job_id]
    assert await _state(pg_conn, space, job_id) == ("vectorizing", None)
    fail["on"] = False
    for _ in range(40):
        if c.waiting() == 0:
            break
        await asyncio.sleep(0.05)
    await c.stop()
    assert await _state(pg_conn, space, job_id) == ("completed", None)


async def test_errors_and_deadlines_are_recorded_with_their_type(
        make_space, pg_pool, pg_conn):
    space = await make_space()
    c = _completer(pg_pool, wait=0)
    failed = await _job(pg_conn, space, G, "urn:inttest:doc:c")
    stuck = await _job(pg_conn, space, G, "urn:inttest:doc:d")
    await _queue(pg_conn, space, G, "urn:inttest:doc:d")
    c.register(space, failed, G, [],
               error=vc.error_text("Vectorization task failed", TimeoutError()))
    c.register(space, stuck, G, ["urn:inttest:doc:d"])
    assert await c.tick(space) == 2
    await c.stop()
    assert await _state(pg_conn, space, failed) == (
        "completed", "Vectorization task failed: TimeoutError")
    assert await _state(pg_conn, space, stuck) == (
        "completed", "vectorization still queued after 0s")


async def test_the_sweep_finishes_stale_jobs_whose_graph_drained(
        make_space, pg_pool, pg_conn):
    space = await make_space()
    old = vc.SWEEP_AFTER_SECONDS + 60
    drained = await _job(pg_conn, space, G, "urn:inttest:doc:e", age_s=old)
    busy = await _job(pg_conn, space, G2, "urn:inttest:doc:f", age_s=old)
    fresh = await _job(pg_conn, space, G, "urn:inttest:doc:g")
    tracked = await _job(pg_conn, space, G, "urn:inttest:doc:h", age_s=old)
    await _queue(pg_conn, space, G2, "urn:inttest:doc:other")
    assert await vc.sweep(pg_conn, space, tracked=[tracked]) == 1
    assert await _state(pg_conn, space, drained) == ("completed", None)
    assert await _state(pg_conn, space, busy) == ("vectorizing", None)
    assert await _state(pg_conn, space, fresh) == ("vectorizing", None)
    assert await _state(pg_conn, space, tracked) == ("vectorizing", None)


async def test_dropping_a_graph_takes_its_job_rows(make_space, space_impl, pg_conn):
    from rdflib import Literal, URIRef
    space = await make_space()
    doc = f"urn:inttest:doc:{uuid.uuid4().hex[:8]}"
    await space_impl.add_rdf_quads_batch(
        space, [(URIRef(doc), URIRef("urn:p"), Literal("x"), URIRef(G))])
    await space_impl.add_rdf_quads_batch(
        space, [(URIRef(doc), URIRef("urn:p"), Literal("x"), URIRef(G2))])
    gone = await _job(pg_conn, space, G, doc)
    kept = await _job(pg_conn, space, G2, doc, status="completed")
    assert await space_impl.drop_graph(space, G)
    assert await _state(pg_conn, space, gone) is None
    assert await _state(pg_conn, space, kept) == ("completed", None)


async def test_a_sparql_drop_graph_takes_its_job_rows(make_space, space_impl, pg_conn):
    from rdflib import Literal, URIRef
    space = await make_space()
    doc = f"urn:inttest:doc:{uuid.uuid4().hex[:8]}"
    await space_impl.add_rdf_quads_batch(
        space, [(URIRef(doc), URIRef("urn:p"), Literal("x"), URIRef(G))])
    gone = await _job(pg_conn, space, G, doc)
    assert await space_impl.execute_sparql_update(space, f"DROP GRAPH <{G}>")
    assert await _state(pg_conn, space, gone) is None
