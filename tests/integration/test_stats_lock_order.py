"""Integration: concurrent writers cannot deadlock on the stats tables.

issues/115. Two transactions holding the same predicates in different order
locked the same rdf_pred_stats / rdf_stats rows in different order and one was
aborted with SQLSTATE 40P01, its whole batch discarded. Nothing retried, so in
the segmentation worker (`_MAX_CONCURRENT = 4`, jobs claimed with FOR UPDATE
SKIP LOCKED) a transient abort was recorded as a permanent job failure.

HOW THIS FILE CHANGED. The fix at the time was to sort every parameter list,
giving all writers one global lock order. That fix — and the functions it lived
in — are gone: the write path no longer touches rdf_stats at all, because
`recompute_stats_tables` is now the only writer (`issues/142`). A deadlock needs
two transactions taking the same locks in different orders, and there is no
longer a second one to race.

So the tests below assert the STRUCTURAL property rather than the sort. That is
a stronger claim than "the lists are sorted" and a much cheaper one to check:
sorting had to be preserved by every future edit to a write path, while "the
write path does not write these tables" fails immediately if anyone reintroduces
incremental maintenance.

The original concurrency reproduction is kept, driven through the real write
path. It no longer exercises stats row locks — that is the point — but it is the
end-to-end behaviour the issue was actually reported as, and it costs one fixture
to keep honest.
"""

from __future__ import annotations

import asyncio
import uuid

import asyncpg
import pytest
import pytest_asyncio
from rdflib import Literal, URIRef

from .conftest import skip_no_infra, TEST_SPACE_PREFIX

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

N_PREDS = 60          # a wide enough window for the two batches to interleave
N_ROUNDS = 8
PREDS = [URIRef(f"urn:lockorder:p{i}") for i in range(N_PREDS)]
GRAPH = URIRef("urn:lockorder:g")


@pytest_asyncio.fixture(loop_scope="session")
async def lock_space(make_space):
    return await make_space(f"{TEST_SPACE_PREFIX}lockorder_{uuid.uuid4().hex[:8]}")


async def _writer(space_impl, sid, preds, tag, out):
    quads = [(URIRef(f"urn:lockorder:s:{tag}"), p, Literal("v"), GRAPH)
             for p in preds]
    try:
        await asyncio.wait_for(
            space_impl.add_rdf_quads_batch(sid, quads), timeout=20)
        out.append("ok")
    except asyncpg.DeadlockDetectedError:
        out.append("deadlock")
    except asyncio.TimeoutError:
        out.append("blocked")


async def test_two_batches_in_opposite_order_do_not_deadlock(
        space_impl, lock_space):
    """The issues/115 reproduction, through the real write path.

    Before the fix this deadlocked in 2 of 8 rounds — a rate that, spread across
    four segmentation workers under sustained load, is the intermittent job
    failure the issue describes. It is a race, so the count is probabilistic in
    the failing direction and exact in the passing one: the expected result is
    zero, always.
    """
    sid = lock_space
    results: list = []
    for r in range(N_ROUNDS):
        out: list = []
        await asyncio.gather(
            _writer(space_impl, sid, PREDS, f"a{r}", out),
            _writer(space_impl, sid, list(reversed(PREDS)), f"b{r}", out))
        results += out

    assert results.count("deadlock") == 0, results
    assert results.count("blocked") == 0, results


async def test_the_write_path_does_not_touch_the_stats_tables(
        space_impl, lock_space, pg_conn):
    """Guards the property itself, deterministically.

    The concurrency test above can only catch a regression when the race happens
    to land. This fails the moment any write path starts maintaining rdf_stats
    again — which is both how the deadlock returns and how the silent downward
    drift of `issues/142` returns, since the two share a cause: a second writer
    applying deltas.
    """
    sid = lock_space
    await pg_conn.execute(f"TRUNCATE {sid}_rdf_stats, {sid}_rdf_pred_stats")

    await space_impl.add_rdf_quads_batch(sid, [
        (URIRef("urn:lockorder:probe"), PREDS[0], Literal("v"), GRAPH)])

    for table in (f"{sid}_rdf_stats", f"{sid}_rdf_pred_stats"):
        assert 0 == await pg_conn.fetchval(f"SELECT count(*) FROM {table}"), (
            f"{table} gained rows from an insert. rdf_stats has exactly one "
            f"writer — recompute_stats_tables — and a second one reintroduces "
            f"both the issues/115 deadlock and the issues/142 drift.")


async def test_a_recompute_reconciles_what_the_write_path_left_alone(
        space_impl, make_space, pg_conn):
    """Leaving the tables stale is only correct if the recompute catches up.

    The previous version of this test compared deferred incremental stats
    against a full resync, because the risk then was two mechanisms disagreeing.
    With one writer the risk moves: the write path is now SUPPOSED to leave the
    tables stale, so the claim worth pinning is that an update — inserts and
    deletes together, the mode derived state actually breaks in — is fully
    reconciled by the next recompute.
    """
    from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables
    from vitalgraph.kg_impl.kg_backend_utils import SparqlSQLBackendAdapter

    sid = await make_space(f"{TEST_SPACE_PREFIX}defer_{uuid.uuid4().hex[:8]}")
    g = URIRef("urn:defer:g")

    def batch(tag, n):
        out = []
        for i in range(n):
            s = URIRef(f"urn:defer:{tag}:s{i}")
            out += [(s, URIRef("http://vital.ai/ontology/vital-core#vitaltype"),
                     URIRef("http://vital.ai/ontology/haley-ai-kg#KGEntity"), g),
                    (s, URIRef("urn:defer:p"), Literal(f"v{i % 3}"), g)]
        return out

    original = batch("a", 40)
    await space_impl.add_rdf_quads_batch_bulk(sid, original)

    adapter = SparqlSQLBackendAdapter(space_impl)
    assert await adapter.update_quads(sid, str(g), original[:20], batch("b", 30))

    await recompute_stats_tables(pg_conn, sid)

    # Against the quads themselves, not against a second implementation. The old
    # comparison could only show the two agreed, not that either was right.
    drift = await pg_conn.fetch(f"""
        SELECT COALESCE(t.rc, 0) AS truth, COALESCE(s.row_count, 0) AS stored
          FROM (SELECT predicate_uuid, object_uuid, count(*) AS rc
                  FROM {sid}_rdf_quad GROUP BY 1, 2 HAVING count(*) >= 2) t
          FULL JOIN {sid}_rdf_stats s USING (predicate_uuid, object_uuid)
         WHERE COALESCE(t.rc, 0) IS DISTINCT FROM COALESCE(s.row_count, 0)""")
    assert not drift, (
        f"recompute did not reconcile an update: {len(drift)} pair(s) differ, "
        f"e.g. truth={drift[0]['truth']} stored={drift[0]['stored']}")
