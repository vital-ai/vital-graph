"""Integration: a stats recompute invalidates every serving process's stats cache.

`issues/300`. The generator caches `rdf_stats` / `rdf_pred_stats` per space in
`_stats_cache` for the life of the process. `recompute_stats_tables` is the only
writer of both, and most of its callers -- the hourly maintenance recompute,
`StatsRebuildOp` (the `issues/139` repair), the incremental imports -- never
invalidated it, so a server kept planning on the counts it loaded first.

Pinned here, on the function itself so that no caller can skip it:

  * the calling process's cache entries for the space are dropped;
  * a `CHANNEL_CACHE_INVALIDATE` NOTIFY reaches other connections -- and is
    delivered at COMMIT, not before, and never on rollback. The rollback case is
    the one that matters: a NOTIFY sent outside the transaction would tell every
    server to reload counts that were then thrown away.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
import pytest_asyncio
from rdflib import Literal, URIRef

from .conftest import skip_no_infra, TEST_SPACE_PREFIX

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

GRAPH = URIRef("urn:stats_inval:g")
P = URIRef("urn:stats_inval:p")


@pytest_asyncio.fixture(loop_scope="session")
async def inval_space(make_space, space_impl):
    sid = await make_space(f"{TEST_SPACE_PREFIX}statsinv_{uuid.uuid4().hex[:7]}")
    await space_impl.add_rdf_quads_batch(
        sid, [(URIRef(f"urn:stats_inval:s{i}"), P, Literal(f"v{i % 3}"), GRAPH)
              for i in range(30)])
    return sid


async def test_the_recompute_drops_this_processs_cache(inval_space, pg_conn):
    from vitalgraph.db.sparql_sql import generator as G
    from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables

    G._stats_cache[(inval_space, None)] = ({}, {"stale": 1}, {})
    G._stats_cache[(inval_space, str(GRAPH))] = ({}, {"stale": 1}, {})
    await recompute_stats_tables(pg_conn, inval_space)
    left = [k for k in G._stats_cache if k[0] == inval_space]
    assert not left, (
        f"cache entries {left} survived a recompute: the process keeps planning "
        f"on the counts it loaded before it (issues/300)")


async def _listening(pg_pool):
    from vitalgraph.signal.signal_manager import CHANNEL_CACHE_INVALIDATE
    conn = await pg_pool.acquire()
    heard: list = []
    arrived = asyncio.Event()

    def _cb(_conn, _pid, _channel, payload):
        heard.append(json.loads(payload))
        arrived.set()

    await conn.add_listener(CHANNEL_CACHE_INVALIDATE, _cb)
    return conn, heard, arrived, lambda: conn.remove_listener(
        CHANNEL_CACHE_INVALIDATE, _cb)


async def test_other_processes_hear_it_at_commit(inval_space, pg_pool):
    from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables

    listener, heard, arrived, unlisten = await _listening(pg_pool)
    try:
        async with pg_pool.acquire() as writer:
            tx = writer.transaction()
            await tx.start()
            try:
                await recompute_stats_tables(writer, inval_space)
                await asyncio.sleep(0.3)
                assert not heard, (
                    "the invalidation was delivered before the recompute "
                    "committed; a server reloading now re-caches the OLD counts")
            except BaseException:
                await tx.rollback()
                raise
            await tx.commit()

        await asyncio.wait_for(arrived.wait(), timeout=5)
        mine = [h for h in heard if h.get("space_id") == inval_space]
        assert mine and mine[0]["cache_type"] == "stats", heard
    finally:
        await unlisten()
        await pg_pool.release(listener)


async def test_a_rolled_back_recompute_tells_no_one(inval_space, pg_pool):
    from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables

    listener, heard, _, unlisten = await _listening(pg_pool)
    try:
        async with pg_pool.acquire() as writer:
            tx = writer.transaction()
            await tx.start()
            await recompute_stats_tables(writer, inval_space)
            await tx.rollback()
        await asyncio.sleep(0.5)
        mine = [h for h in heard if h.get("space_id") == inval_space]
        assert not mine, (
            f"a rolled-back recompute sent {mine}: every server would reload "
            f"counts that were never committed")
    finally:
        await unlisten()
        await pg_pool.release(listener)
