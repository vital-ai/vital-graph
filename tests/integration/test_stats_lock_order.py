"""Integration: concurrent writers do not deadlock on the stats tables.

issues/115. Two transactions holding the same predicates in different order
locked the same rdf_pred_stats / rdf_stats rows in different order and one was
aborted with SQLSTATE 40P01, its whole batch discarded. Nothing retried, so in
the segmentation worker (`_MAX_CONCURRENT = 4`, jobs claimed with FOR UPDATE
SKIP LOCKED) a transient abort was recorded as a permanent job failure.

The sync functions now sort every parameter list, giving all writers one
global lock order.
"""

from __future__ import annotations

import asyncio
import uuid

import asyncpg
import pytest
import pytest_asyncio

from .conftest import skip_no_infra, TEST_SPACE_PREFIX

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

N_PREDS = 60          # a wide enough window for the two batches to interleave
N_ROUNDS = 8
PREDS = [uuid.uuid5(uuid.NAMESPACE_URL, f"lockorder:p{i}") for i in range(N_PREDS)]
OBJ = uuid.uuid5(uuid.NAMESPACE_URL, "lockorder:obj")
GRAPH = uuid.uuid5(uuid.NAMESPACE_URL, "lockorder:g")
SUBJ = uuid.uuid5(uuid.NAMESPACE_URL, "lockorder:s")


@pytest_asyncio.fixture(loop_scope="session")
async def lock_space(make_space):
    return await make_space(f"{TEST_SPACE_PREFIX}lockorder_{uuid.uuid4().hex[:8]}")


async def _writer(pool, sid, preds, out):
    from vitalgraph.db.sparql_sql.sync_stats_tables import sync_stats_after_insert

    rows = [(SUBJ, p, OBJ, GRAPH) for p in preds]
    async with pool.acquire() as conn:
        try:
            tx = conn.transaction()
            await tx.start()
            await asyncio.wait_for(
                sync_stats_after_insert(conn, sid, rows), timeout=20)
            await tx.commit()
            out.append("ok")
        except asyncpg.DeadlockDetectedError:
            out.append("deadlock")
        except asyncio.TimeoutError:
            out.append("blocked")


async def test_two_batches_in_opposite_order_do_not_deadlock(space_impl, lock_space):
    """The issues/115 reproduction.

    Two writers hold the same predicates in opposite order. Before the sort
    this deadlocked in 2 of 8 rounds — a rate that, spread across four
    segmentation workers under sustained load, is the intermittent job failure
    the issue describes. It is a race, so the count is probabilistic in the
    failing direction and exact in the passing one: with one global lock order
    there is no cycle to find, and the expected result is zero, always.
    """
    sid = lock_space
    pool = space_impl.db_impl.connection_pool
    async with pool.acquire() as conn:
        for p in PREDS:
            await conn.execute(
                f"INSERT INTO {sid}_rdf_pred_stats (predicate_uuid, row_count) "
                f"VALUES ($1, 0) ON CONFLICT DO NOTHING", p)

    results: list = []
    for _ in range(N_ROUNDS):
        out: list = []
        await asyncio.gather(_writer(pool, sid, PREDS, out),
                             _writer(pool, sid, list(reversed(PREDS)), out))
        results += out

    assert results.count("deadlock") == 0, results
    assert results.count("blocked") == 0, results


async def test_the_sync_functions_take_their_locks_in_sorted_order(space_impl, lock_space):
    """Guards the property itself, deterministically.

    The concurrency test above can only catch a lost sort when the race
    happens to land; this fails the moment any parameter list stops being
    sorted, which is the thing that actually has to hold.
    """
    from vitalgraph.db.sparql_sql import sync_stats_tables

    sid = lock_space
    seen: list = []

    class Recorder:
        async def executemany(self, sql, args):
            if "_rdf_pred_stats" in sql or "_rdf_stats" in sql:
                seen.append([a[:2] for a in args])

        async def fetch(self, sql, *a):
            return []

    rows = [(SUBJ, p, OBJ, GRAPH) for p in reversed(PREDS)]   # deliberately unsorted
    await sync_stats_tables.sync_stats_after_insert(Recorder(), sid, rows)

    assert seen, "no stats statements were issued"
    for args in seen:
        assert args == sorted(args), f"unsorted lock order: {args[:4]}..."


async def test_deferred_stats_match_an_inline_sync_exactly(space_impl, make_space):
    """Deferring the sync must not change the numbers it writes.

    update_quads now takes the deltas back from both halves and applies them
    once at the end, so the hot predicate rows are locked for the tail of the
    transaction instead of all of it (98.4% -> 8.6% measured). The counts have
    to come out where a full resync puts them, or the join reorder is planning
    against fiction.
    """
    from vitalgraph.db.sparql_sql.sync_stats_tables import resync_stats_tables
    from vitalgraph.kg_impl.kg_backend_utils import SparqlSQLBackendAdapter
    from rdflib import URIRef, Literal

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

    async def stats(conn):
        return {(r["predicate_uuid"], r["object_uuid"]): r["row_count"]
                for r in await conn.fetch(f"SELECT * FROM {sid}_rdf_stats")}

    async with space_impl.db_impl.connection_pool.acquire() as conn:
        incremental = await stats(conn)
        await resync_stats_tables(conn, sid)
        resynced = await stats(conn)

    assert incremental == resynced, (
        f"deferred stats diverged from a resync: "
        f"only-incremental={set(incremental) - set(resynced)}, "
        f"only-resynced={set(resynced) - set(incremental)}, "
        f"differing={{k: (incremental[k], resynced[k]) for k in "
        f"set(incremental) & set(resynced) if incremental[k] != resynced[k]}}")
