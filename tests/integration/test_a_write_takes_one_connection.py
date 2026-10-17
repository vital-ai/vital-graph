"""A write holding a pooled connection does not ask the pool for another — issues/274.

`_ensure_graphs_registered` used to register graphs through the request pool
while the write held its own connection for its transaction. With a request pool
of one connection every upsert waited the 15 s acquire timeout and then wrote
without registering its graph (16-19 s against ~1 s); with N concurrent writers
on a pool of N, production would do the same.

Driven with a space impl whose request pool is ONE connection, so a second
acquisition cannot succeed: any write that needs one hangs for the acquire
timeout. Each write here must finish quickly AND register its graph — and a
rolled-back write must not leave its graph registered, which it did when the
registration ran on a different connection.
"""

from __future__ import annotations

import time
import uuid

import pytest
import pytest_asyncio
from rdflib import Literal, URIRef

from .conftest import (PG_DATABASE, PG_HOST, PG_PASSWORD, PG_PORT, PG_USER,
                       SIDECAR_URL, skip_no_infra)

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

# Well under the 15 s acquire timeout a nested acquisition would wait.
FAST_S = 5.0


@pytest_asyncio.fixture(loop_scope="session")
async def one_connection_impl():
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
    impl = SparqlSQLSpaceImpl(
        postgresql_config={"host": PG_HOST, "port": PG_PORT, "database": PG_DATABASE,
                           "username": PG_USER, "password": PG_PASSWORD,
                           "min_pool_size": 1, "max_pool_size": 3},
        sidecar_config={"url": SIDECAR_URL})
    assert await impl.connect()
    assert impl.db_impl.connection_pool.get_max_size() == 1, (
        "the fixture needs a request pool of exactly one connection")
    yield impl
    await impl.disconnect()


async def _registered(pg_conn, space_id, graph_uri) -> bool:
    return bool(await pg_conn.fetchval(
        "SELECT 1 FROM graph WHERE space_id = $1 AND graph_uri = $2",
        space_id, graph_uri))


def _quads(graph_uri, n=600):
    g = URIRef(graph_uri)
    return [(URIRef(f"urn:t274:s{i}"), URIRef("urn:t274:p"), Literal(f"v{i}"), g)
            for i in range(n)]


async def test_an_entity_upsert_completes_on_one_connection(
        one_connection_impl, test_space, pg_conn):
    from ai_haley_kg_domain.model.KGEntity import KGEntity
    from vitalgraph.kg_impl.kg_backend_utils import create_backend_adapter
    graph = f"urn:t274:g:{uuid.uuid4().hex[:8]}"
    uri = f"urn:t274:e:{uuid.uuid4().hex[:8]}"
    e = KGEntity(); e.URI = uri; e.name = "t274"; e.kGGraphURI = uri
    t0 = time.perf_counter()
    assert await create_backend_adapter(one_connection_impl).upsert_objects_atomic(
        test_space, graph, [uri], [e]) is True
    assert time.perf_counter() - t0 < FAST_S, "the write waited for a second connection"
    assert await _registered(pg_conn, test_space, graph)


@pytest.mark.parametrize("writer", ["add_rdf_quads_batch_bulk", "add_rdf_quads_batch"])
async def test_a_batch_write_on_a_caller_connection_completes(
        one_connection_impl, test_space, pg_conn, writer):
    graph = f"urn:t274:g:{uuid.uuid4().hex[:8]}"
    pool = one_connection_impl.db_impl.connection_pool
    t0 = time.perf_counter()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await getattr(one_connection_impl, writer)(
                test_space, _quads(graph), connection=conn)
    assert time.perf_counter() - t0 < FAST_S, "the write waited for a second connection"
    assert await _registered(pg_conn, test_space, graph)


async def test_a_rolled_back_write_does_not_register_its_graph(
        space_impl, test_space, pg_conn):
    # A NORMAL pool here: with one connection the old code's second
    # acquisition timed out and registered nothing, so this would pass on it
    # vacuously. With room to spare it registered on another connection, and
    # the graph outlived the rollback.
    graph = f"urn:t274:g:{uuid.uuid4().hex[:8]}"
    pool = space_impl.db_impl.connection_pool
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        await space_impl.add_rdf_quads_batch_bulk(
            test_space, _quads(graph), connection=conn)
        await tr.rollback()
    assert not await _registered(pg_conn, test_space, graph), (
        "the graph outlived the write that created it")
