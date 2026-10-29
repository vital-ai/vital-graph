"""Integration: a value-histogram rebuild is atomic and tells every process (`issues/305`).

`resync_value_stats` rebuilds `{space}_rdf_value_stats`. Each server caches the
histograms (`generator._value_stats_cache`) and their freshness verdicts for the
life of the process. Two of its three callers (a large bulk insert, the
maintenance refresh) only invalidated their OWN process, so another serving
process kept the old histograms. And the rebuild was a TRUNCATE followed by
per-predicate inserts with no transaction, so a reader in between saw an empty
or partial table, and cached that.

Pinned on the function itself, so no caller can skip it, as `issues/300` did for
the stats recompute:

  * a reader running during the rebuild never sees the table emptier than it
    was before or after (the old rows until COMMIT, then the new ones);
  * a `CHANNEL_CACHE_INVALIDATE` "stats" NOTIFY reaches other connections at
    COMMIT, and never on rollback;
  * this process's cache entry is dropped.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
import pytest_asyncio
from rdflib import Literal, URIRef
from rdflib.namespace import XSD

from .conftest import skip_no_infra, TEST_SPACE_PREFIX

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

GRAPH = URIRef("urn:vstats:g")
PREDS = [URIRef(f"urn:vstats:p{k}") for k in range(12)]


@pytest_asyncio.fixture(loop_scope="session")
async def vstats_space(make_space, space_impl, pg_conn):
    from vitalgraph.db.sparql_sql.sync_value_stats import resync_value_stats
    sid = await make_space(f"{TEST_SPACE_PREFIX}vstats_{uuid.uuid4().hex[:7]}")
    await space_impl.add_rdf_quads_batch(
        sid, [(URIRef(f"urn:vstats:s{i}"), p, Literal(i * (k + 1), datatype=XSD.integer), GRAPH)
              for k, p in enumerate(PREDS) for i in range(400)])
    await resync_value_stats(pg_conn, sid)
    return sid


def _table(space):
    from vitalgraph.db.sparql_sql.space_names import space_prefix
    return f"{space_prefix(space)}_rdf_value_stats"


async def test_a_reader_never_sees_the_table_emptied(vstats_space, pg_pool):
    from vitalgraph.db.sparql_sql.sync_value_stats import resync_value_stats
    table = _table(vstats_space)
    async with pg_pool.acquire() as c:
        full = await c.fetchval(f"SELECT count(*) FROM {table}")
    assert full > 0, "the fixture built no histograms"

    seen: list = []
    done = asyncio.Event()

    async def reader():
        async with pg_pool.acquire() as c:
            while not done.is_set():
                seen.append(await c.fetchval(f"SELECT count(*) FROM {table}"))
                await asyncio.sleep(0)

    task = asyncio.create_task(reader())
    try:
        for _ in range(3):
            async with pg_pool.acquire() as w:
                await resync_value_stats(w, vstats_space)
    finally:
        done.set()
        await task
    assert len(seen) > 20, f"the reader only got {len(seen)} reads in"
    short = [n for n in seen if n < full]
    assert not short, (
        f"{len(short)} of {len(seen)} reads saw fewer than {full} rows "
        f"(min {min(short)}): the rebuild exposes an empty or partial table")


async def _listening(pg_pool):
    from vitalgraph.signal.signal_manager import CHANNEL_CACHE_INVALIDATE
    conn = await pg_pool.acquire()
    heard: list = []

    def _cb(_conn, _pid, _channel, payload):
        heard.append(json.loads(payload))

    await conn.add_listener(CHANNEL_CACHE_INVALIDATE, _cb)
    return conn, heard, lambda: conn.remove_listener(CHANNEL_CACHE_INVALIDATE, _cb)


async def test_other_processes_hear_it_at_commit_not_on_rollback(vstats_space, pg_pool):
    from vitalgraph.db.sparql_sql.sync_value_stats import resync_value_stats

    def _mine(heard):
        return [h for h in heard
                if h.get("cache_type") == "stats" and h.get("space_id") == vstats_space]

    listener, heard, unlisten = await _listening(pg_pool)
    try:
        async with pg_pool.acquire() as w:
            tx = w.transaction()
            await tx.start()
            await resync_value_stats(w, vstats_space)
            await asyncio.sleep(0.3)
            assert not _mine(heard), "heard before COMMIT"
            await tx.rollback()
        await asyncio.sleep(0.3)
        assert not _mine(heard), "heard a rebuild that was rolled back"

        async with pg_pool.acquire() as w:
            await resync_value_stats(w, vstats_space)
        for _ in range(30):
            if _mine(heard):
                break
            await asyncio.sleep(0.1)
        assert _mine(heard), "no 'stats' NOTIFY: other processes keep the old histograms"
    finally:
        await unlisten()
        await pg_pool.release(listener)


async def test_this_processs_cache_is_dropped(vstats_space, pg_conn):
    from vitalgraph.db.sparql_sql import generator as G
    from vitalgraph.db.sparql_sql.sync_value_stats import resync_value_stats
    G._value_stats_cache[vstats_space] = {"stale": True}
    await resync_value_stats(pg_conn, vstats_space)
    assert vstats_space not in G._value_stats_cache
