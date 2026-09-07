"""Write methods accept a caller's connection. `issues/175` class 2.

Each write method acquired its own connection, so two of them could not be
composed into one unit of work and a lock taken in one was invisible to the
other. `conn=None` still behaves exactly as before; supplying one puts the write
inside the caller's transaction.

The transaction stays inside the write method. Nested on a caller's connection
it becomes a SAVEPOINT, which preserves what it was written for — a failure
rolls back only its own work, and the commit boundary belongs to the caller.
"""
from __future__ import annotations

import uuid

import pytest
from rdflib import URIRef

from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid

pytestmark = pytest.mark.asyncio(loop_scope="session")

P = "http://vital.ai/ontology/vital-core#hasName"


async def _count(space_impl, space_id, graph, subj):
    async with space_impl.db_impl.connection_pool.acquire() as c:
        return await c.fetchval(
            f"SELECT count(*) FROM {space_id}_rdf_quad "
            f" WHERE subject_uuid = $1 AND context_uuid = $2",
            _generate_term_uuid(subj, "U"), _generate_term_uuid(graph, "U"))


def _quads(graph, subj, value):
    return [(URIRef(subj), URIRef(P), URIRef(value), URIRef(graph))]


async def test_without_a_connection_it_commits_as_before(space_impl, test_space, backend_adapter):
    """The default path is unchanged — nothing that does not opt in is affected."""
    sp, graph = test_space, f"urn:test:{test_space}"
    subj = f"urn:test:s:{uuid.uuid4().hex[:8]}"
    ok = await backend_adapter.update_subjects_graph(
        sp, graph, [subj], _quads(graph, subj, "urn:v:1"))
    assert ok
    assert await _count(space_impl, sp, graph, subj) == 1


async def test_a_caller_rollback_takes_the_write_with_it(space_impl, test_space, backend_adapter):
    """The point of the change: the write joins the caller's unit of work.

    Before this, the write committed on its own connection regardless of what
    the caller did, so a caller could not abort a sequence it had begun.
    """
    sp, graph = test_space, f"urn:test:{test_space}"
    subj = f"urn:test:s:{uuid.uuid4().hex[:8]}"
    conn = await space_impl.db_impl.connection_pool.acquire()
    try:
        tx = conn.transaction()
        await tx.start()
        ok = await backend_adapter.update_subjects_graph(
            sp, graph, [subj], _quads(graph, subj, "urn:v:1"), conn=conn)
        assert ok
        await tx.rollback()
    finally:
        await space_impl.db_impl.connection_pool.release(conn)

    assert await _count(space_impl, sp, graph, subj) == 0, (
        "the write survived the caller's rollback — it ran on its own "
        "connection rather than joining the caller's transaction")


async def test_two_writes_commit_or_abort_together(space_impl, test_space, backend_adapter):
    """Composition, which is what class 2 exists for.

    Two writes that should be one unit: the second failing must undo the first.
    """
    sp, graph = test_space, f"urn:test:{test_space}"
    a = f"urn:test:s:{uuid.uuid4().hex[:8]}"
    b = f"urn:test:s:{uuid.uuid4().hex[:8]}"
    conn = await space_impl.db_impl.connection_pool.acquire()
    try:
        tx = conn.transaction()
        await tx.start()
        await backend_adapter.update_subjects_graph(
            sp, graph, [a], _quads(graph, a, "urn:v:a"), conn=conn)
        await backend_adapter.update_subjects_graph(
            sp, graph, [b], _quads(graph, b, "urn:v:b"), conn=conn)
        await tx.rollback()                      # stands in for the second failing
    finally:
        await space_impl.db_impl.connection_pool.release(conn)

    assert await _count(space_impl, sp, graph, a) == 0
    assert await _count(space_impl, sp, graph, b) == 0


async def test_a_caller_commit_persists_the_write(space_impl, test_space, backend_adapter):
    """The other half: rollback undoing everything would be easy to achieve by
    breaking the write entirely, so assert the committing case too."""
    sp, graph = test_space, f"urn:test:{test_space}"
    subj = f"urn:test:s:{uuid.uuid4().hex[:8]}"
    conn = await space_impl.db_impl.connection_pool.acquire()
    try:
        tx = conn.transaction()
        await tx.start()
        await backend_adapter.update_subjects_graph(
            sp, graph, [subj], _quads(graph, subj, "urn:v:1"), conn=conn)
        await tx.commit()
    finally:
        await space_impl.db_impl.connection_pool.release(conn)

    assert await _count(space_impl, sp, graph, subj) == 1


class TestReadAndWriteInOneTransaction:
    """A read can now join the write's transaction. `issues/175` class 2.

    This is what frame Phase 2 needs. `validate_frame_ownership` reads through
    the SPARQL query path on its own connection, then the write happens later on
    another — so the validation is a snapshot the write no longer agrees with,
    and locking the write cannot fix that. Both on one connection makes the pair
    atomic.
    """

    async def test_a_read_on_the_same_connection_sees_the_uncommitted_write(
            self, space_impl, test_space, backend_adapter):
        sp, graph = test_space, f"urn:test:{test_space}"
        subj = f"urn:test:s:{uuid.uuid4().hex[:8]}"
        q = f'SELECT ?o WHERE {{ GRAPH <{graph}> {{ <{subj}> <{P}> ?o }} }}'
        conn = await space_impl.db_impl.connection_pool.acquire()
        try:
            tx = conn.transaction()
            await tx.start()
            await backend_adapter.update_subjects_graph(
                sp, graph, [subj], _quads(graph, subj, "urn:v:1"), conn=conn)

            same = await space_impl.execute_sparql_query(sp, q, conn=conn)
            other = await space_impl.execute_sparql_query(sp, q)

            assert len(same.get("results", {}).get("bindings", [])) == 1, (
                "a read on the writer's own connection did not see its "
                "uncommitted write — the query path ignored the supplied "
                "connection and acquired its own")
            assert len(other.get("results", {}).get("bindings", [])) == 0, (
                "a read on a DIFFERENT connection saw an uncommitted write, "
                "which would mean the write had already committed")
            await tx.rollback()
        finally:
            await space_impl.db_impl.connection_pool.release(conn)

        assert await _count(space_impl, sp, graph, subj) == 0
