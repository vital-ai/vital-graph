"""The `rdf_quad` trigger queues every write's subjects in the write's own
transaction (`issues/291` step 2).

Step 1 enqueued after the write returned, so a crash, deploy or cancelled task
in between lost the sync. With the trigger, the sync request commits with the
write or not at all, on every path -- including SPARQL UPDATE, whose WHERE-bound
subjects Python never sees.
"""

from __future__ import annotations

import uuid

import pytest

from .conftest import skip_no_infra
from vitalgraph.db.sparql_sql.space_names import space_prefix

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

KG = "http://vital.ai/ontology/haley-ai-kg#"
CORE = "http://vital.ai/ontology/vital-core#"
EX = "http://example.org/isqtrg/"
GRAPH = "http://example.org/isqtrg/graph"


def _u(text: str) -> uuid.UUID:
    from vitalgraph.vectorization.auto_sync import _generate_term_uuid
    return _generate_term_uuid(text)


def _entity(name: str, extra=()):
    from rdflib import Literal, URIRef
    g, s = URIRef(GRAPH), URIRef(f"{EX}{name}")
    return [(s, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGEntity"), g),
            (s, URIRef(f"{CORE}hasName"), Literal(name), g), *extra]


async def _queued(conn, space):
    return {(r["context_uuid"], r["subject_uuid"]): r["generation"]
            for r in await conn.fetch(f"SELECT * FROM {space_prefix(space)}_index_sync_queue")}


async def _clear(conn, space):
    await conn.execute(f"DELETE FROM {space_prefix(space)}_index_sync_queue")


async def test_new_spaces_have_the_trigger(test_space, pg_conn):
    from vitalgraph.vectorization.index_sync_trigger import installed
    assert await installed(pg_conn, test_space)


async def test_an_insert_queues_its_subjects(test_space, space_impl, pg_conn):
    await _clear(pg_conn, test_space)
    await space_impl.add_rdf_quads_batch_bulk(test_space, _entity("a") + _entity("b"))
    q = await _queued(pg_conn, test_space)
    assert set(q) == {(_u(GRAPH), _u(f"{EX}a")), (_u(GRAPH), _u(f"{EX}b"))}


async def test_a_delete_queues_its_subjects(test_space, space_impl, pg_conn):
    await space_impl.add_rdf_quads_batch_bulk(test_space, _entity("del"))
    await _clear(pg_conn, test_space)
    await space_impl.remove_rdf_quads_batch_bulk(test_space, _entity("del"))
    assert set(await _queued(pg_conn, test_space)) == {(_u(GRAPH), _u(f"{EX}del"))}


async def test_sparql_update_with_a_where_clause_is_covered(test_space, space_impl, pg_conn):
    """The case no Python hook could reach: subjects bound by WHERE."""
    await space_impl.add_rdf_quads_batch_bulk(test_space, _entity("w1") + _entity("w2"))
    await _clear(pg_conn, test_space)
    ok = await space_impl.execute_sparql_update(test_space, f"""
        DELETE {{ GRAPH <{GRAPH}> {{ ?s <{CORE}hasName> ?n }} }}
        WHERE  {{ GRAPH <{GRAPH}> {{ ?s <{CORE}hasName> ?n .
                                    FILTER(?n IN ("w1", "w2")) }} }}""")
    assert ok
    left = await pg_conn.fetchval(
        f"SELECT count(*) FROM {space_prefix(test_space)}_rdf_quad WHERE subject_uuid = ANY($1::uuid[]) "
        f"AND predicate_uuid = $2", [_u(f"{EX}w1"), _u(f"{EX}w2")], _u(f"{CORE}hasName"))
    assert left == 0, "precondition: the update deleted the names"
    assert set(await _queued(pg_conn, test_space)) == {
        (_u(GRAPH), _u(f"{EX}w1")), (_u(GRAPH), _u(f"{EX}w2"))}


async def test_a_rolled_back_write_queues_nothing(test_space, pg_pool):
    await_ctx = _u(GRAPH)
    async with pg_pool.acquire() as conn:
        await _clear(conn, test_space)
        tr = conn.transaction()
        await tr.start()
        await conn.execute(
            f"INSERT INTO {space_prefix(test_space)}_rdf_quad (subject_uuid, predicate_uuid, "
            f"object_uuid, context_uuid) VALUES ($1, $1, $1, $2)", uuid.uuid4(), await_ctx)
        assert len(await _queued(conn, test_space)) == 1, "queued inside the write"
        await tr.rollback()
        assert await _queued(conn, test_space) == {}, "and gone with it"


async def test_a_suppressed_transaction_queues_nothing(test_space, pg_pool):
    from vitalgraph.vectorization.index_sync_trigger import suppress
    async with pg_pool.acquire() as conn:
        await _clear(conn, test_space)
        async with conn.transaction():
            await suppress(conn)
            await conn.execute(
                f"INSERT INTO {space_prefix(test_space)}_rdf_quad (subject_uuid, predicate_uuid, "
                f"object_uuid, context_uuid) VALUES ($1, $1, $1, $2)",
                uuid.uuid4(), _u(GRAPH))
        assert await _queued(conn, test_space) == {}
        # ...and only that transaction: the next write queues again.
        await conn.execute(
            f"INSERT INTO {space_prefix(test_space)}_rdf_quad (subject_uuid, predicate_uuid, "
            f"object_uuid, context_uuid) VALUES ($1, $1, $1, $2)", uuid.uuid4(), _u(GRAPH))
        assert len(await _queued(conn, test_space)) == 1


async def test_the_consumer_decides_the_operation_from_the_data(test_space, space_impl, pg_conn):
    from vitalgraph.vectorization.index_sync_worker import resolve
    await space_impl.add_rdf_quads_batch_bulk(test_space, _entity("here"))
    gone = _u(f"{EX}never-written")
    upsert, delete = await resolve(pg_conn, test_space, _u(GRAPH), [_u(f"{EX}here"), gone])
    assert upsert == [_u(f"{EX}here")] and delete == [gone]


async def test_an_edge_change_reaches_the_geo_slot_it_points_at(test_space, space_impl, pg_conn):
    """Geo attribution walks edges; an edge-only change must re-derive the slot."""
    from rdflib import URIRef
    from vitalgraph.vectorization.index_sync_worker import resolve
    g = URIRef(GRAPH)
    frame, slot, edge = URIRef(f"{EX}f"), URIRef(f"{EX}geo_slot"), URIRef(f"{EX}e_slot")
    await space_impl.add_rdf_quads_batch_bulk(test_space, [
        (slot, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGGeoLocationSlot"), g),
        (edge, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}Edge_hasKGSlot"), g),
        (edge, URIRef(f"{CORE}hasEdgeSource"), frame, g),
        (edge, URIRef(f"{CORE}hasEdgeDestination"), slot, g)])
    upsert, delete = await resolve(pg_conn, test_space, _u(GRAPH), [_u(str(edge))])
    assert set(upsert) == {_u(str(edge)), _u(str(slot))} and delete == []


async def test_after_a_write_schedule_sync_leaves_it_to_the_trigger(test_space, pg_pool, monkeypatch):
    """The post-commit enqueue is skipped where the trigger already queued
    the write; `rederive=True` still enqueues, for changes no trigger sees."""
    from vitalgraph.vectorization import auto_sync

    class _DB:
        internal_pool = pg_pool
    async with pg_pool.acquire() as conn:
        await _clear(conn, test_space)
    await auto_sync._enqueue_sync(_DB(), test_space, [f"{EX}x"], GRAPH, "upsert")
    async with pg_pool.acquire() as conn:
        assert await _queued(conn, test_space) == {}
    await auto_sync._enqueue_sync(_DB(), test_space, [f"{EX}x"], GRAPH, "upsert",
                                  rederive=True)
    async with pg_pool.acquire() as conn:
        assert set(await _queued(conn, test_space)) == {(_u(GRAPH), _u(f"{EX}x"))}
