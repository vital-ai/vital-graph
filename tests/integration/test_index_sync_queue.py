"""The index sync queue and its consumers (`issues/291`).

Auto-sync used to be one fire-and-forget task per write. Each held an
internal-pool connection across the embedding call, nothing bounded how many
ran, and an acquire that waited out its 15 s failed the sync with nothing to
retry it. On the vg test stack the 3-connection internal pool logged waits of
up to 5.1 s at 3/3 in use while 26 request connections sat idle.

These pin the replacement: a per-space queue table whose rows merge per
subject, survive a write landing mid-sync, are claimed by any number of
consumers without overlap, and are retried on failure -- and consumers that do
not hold a connection while the provider works.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio

from .conftest import (PG_DATABASE, PG_HOST, PG_PASSWORD, PG_PORT, PG_USER,
                       skip_no_infra)
from vitalgraph.db.sparql_sql.space_names import space_prefix

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]


def _ctx(i=0):
    return uuid.uuid5(uuid.NAMESPACE_URL, f"http://example.org/isq/graph/{i}")


async def _rows(conn, space):
    return await conn.fetch(f"SELECT * FROM {space_prefix(space)}_index_sync_queue "
                            f"ORDER BY context_uuid, subject_uuid")


async def _clear(conn, space):
    await conn.execute(f"DELETE FROM {space_prefix(space)}_index_sync_queue")


# ---------------------------------------------------------------------------
# The queue's own rules
# ---------------------------------------------------------------------------

async def test_a_second_write_merges_into_one_row(test_space, pg_conn):
    from vitalgraph.vectorization import index_sync_queue as q
    await _clear(pg_conn, test_space)
    s = uuid.uuid4()
    await q.enqueue(pg_conn, test_space, _ctx(), [s], "upsert")
    await q.enqueue(pg_conn, test_space, _ctx(), [s, s], "delete")
    rows = await _rows(pg_conn, test_space)
    assert len(rows) == 1
    assert rows[0]["generation"] == 2 and rows[0]["operation"] == "delete", (
        "the latest write's operation, and one generation per write")


async def test_completing_removes_the_row(test_space, pg_conn):
    from vitalgraph.vectorization import index_sync_queue as q
    await _clear(pg_conn, test_space)
    await q.enqueue(pg_conn, test_space, _ctx(), [uuid.uuid4()], "upsert")
    claimed = await q.claim(pg_conn, test_space, "c1", 10)
    assert len(claimed) == 1
    assert await q.complete(pg_conn, test_space, "c1", claimed) == 0
    assert await _rows(pg_conn, test_space) == []


async def test_a_write_during_a_sync_leaves_the_row_for_another_pass(test_space, pg_conn):
    """What lets a consumer release its connection across the embedding: what
    it read may be overtaken, but the newer write is never lost."""
    from vitalgraph.vectorization import index_sync_queue as q
    await _clear(pg_conn, test_space)
    s = uuid.uuid4()
    await q.enqueue(pg_conn, test_space, _ctx(), [s], "upsert")
    claimed = await q.claim(pg_conn, test_space, "c1", 10)
    await q.enqueue(pg_conn, test_space, _ctx(), [s], "upsert")     # mid-sync
    assert await q.complete(pg_conn, test_space, "c1", claimed) == 1
    [row] = await _rows(pg_conn, test_space)
    assert row["generation"] == 2 and row["claimed_by"] is None
    assert [c.subject_uuid for c in await q.claim(pg_conn, test_space, "c2", 10)] == [s], (
        "the overtaken row must be claimable again at once")


async def test_two_consumers_never_claim_the_same_rows(test_space, pg_pool):
    from vitalgraph.vectorization import index_sync_queue as q
    async with pg_pool.acquire() as conn:
        await _clear(conn, test_space)
        await q.enqueue(conn, test_space, _ctx(), [uuid.uuid4() for _ in range(40)], "upsert")

    async def take(name):
        async with pg_pool.acquire() as conn:
            return await q.claim(conn, test_space, name, 25)
    a, b = await asyncio.gather(take("a"), take("b"))
    ka, kb = {c.subject_uuid for c in a}, {c.subject_uuid for c in b}
    assert not ka & kb and len(ka | kb) == 40


async def test_an_expired_lease_gives_the_rows_back(test_space, pg_conn):
    """A consumer that dies mid-batch: its rows return when the lease ends."""
    from vitalgraph.vectorization import index_sync_queue as q
    await _clear(pg_conn, test_space)
    await q.enqueue(pg_conn, test_space, _ctx(), [uuid.uuid4()], "upsert")
    assert await q.claim(pg_conn, test_space, "dead", 10, lease_seconds=1)
    assert await q.claim(pg_conn, test_space, "live", 10) == [], "held by its lease"
    await asyncio.sleep(1.2)
    assert len(await q.claim(pg_conn, test_space, "live", 10)) == 1


async def test_a_failure_backs_off_and_a_new_write_cuts_it_short(test_space, pg_conn):
    from vitalgraph.vectorization import index_sync_queue as q
    await _clear(pg_conn, test_space)
    s = uuid.uuid4()
    await q.enqueue(pg_conn, test_space, _ctx(), [s], "upsert")
    claimed = await q.claim(pg_conn, test_space, "c1", 10)
    await q.fail(pg_conn, test_space, "c1", claimed, "TimeoutError: pool")
    [row] = await _rows(pg_conn, test_space)
    assert row["last_error"] == "TimeoutError: pool" and row["claimed_by"] is None
    assert await q.claim(pg_conn, test_space, "c2", 10) == [], "backing off"
    await q.enqueue(pg_conn, test_space, _ctx(), [s], "upsert")
    assert len(await q.claim(pg_conn, test_space, "c2", 10)) == 1, (
        "a new write is a new request, not the failed one")


async def test_release_gives_back_only_this_consumers_rows(test_space, pg_conn):
    from vitalgraph.vectorization import index_sync_queue as q
    await _clear(pg_conn, test_space)
    await q.enqueue(pg_conn, test_space, _ctx(), [uuid.uuid4(), uuid.uuid4()], "upsert")
    await q.claim(pg_conn, test_space, "mine", 1)
    await q.claim(pg_conn, test_space, "theirs", 1)
    assert await q.release(pg_conn, test_space, "mine") == 1
    held = {r["claimed_by"] for r in await _rows(pg_conn, test_space)}
    assert held == {None, "theirs"}


# ---------------------------------------------------------------------------
# A consumer never waits on a writer (`issues/294`)
#
# A frame delete queues its frames' rows in one statement and, later in the
# same transaction, its owner entity's row (the modification stamp). A
# consumer finishing a batch with both used a plain DELETE: it took the entity
# row, waited on a frame row the writer held, and the writer's stamp then
# waited on the entity row. 15 deadlocks in two days on the test stack, one
# of them a user's frame delete rolled back.
# ---------------------------------------------------------------------------

async def _writer_holding(pg_pool, space, subjects):
    """A writer mid-transaction: its first statement has queued `subjects`."""
    from vitalgraph.vectorization import index_sync_queue as q
    conn = await pg_pool.acquire()
    tx = conn.transaction()
    await tx.start()
    await q.enqueue(conn, space, _ctx(), subjects, "upsert")
    return conn, tx


async def test_complete_does_not_wait_on_a_row_a_writer_holds(test_space, pg_pool):
    from vitalgraph.vectorization import index_sync_queue as q
    entity, frame = sorted([uuid.uuid4(), uuid.uuid4()])
    async with pg_pool.acquire() as conn:
        await _clear(conn, test_space)
        await q.enqueue(conn, test_space, _ctx(), [entity, frame], "upsert")
        claimed = await q.claim(conn, test_space, "c1", 10)
    w, tx = await _writer_holding(pg_pool, test_space, [frame])
    try:
        async with pg_pool.acquire() as conn:
            # Old code: blocks until the writer commits. Bounded here so a
            # regression fails rather than hangs.
            await asyncio.wait_for(q.complete(conn, test_space, "c1", claimed), 10)
            rows = {r["subject_uuid"]: r for r in await _rows(conn, test_space)}
        assert entity not in rows, "the row it could lock is finished"
        assert rows[frame]["claimed_by"] == "c1", (
            "the held row keeps its claim: left to the lease, never lost")
        # The writer's later statement, the stamp, now takes the entity row
        # without waiting on the consumer. Before the fix, the deadlock.
        await asyncio.wait_for(
            q.enqueue(w, test_space, _ctx(), [entity], "upsert"), 10)
    finally:
        await tx.commit()
        await pg_pool.release(w)
    async with pg_pool.acquire() as conn:
        rows = {r["subject_uuid"]: r for r in await _rows(conn, test_space)}
    assert rows[frame]["generation"] == 2 and rows[entity]["generation"] == 1


async def test_a_writer_committing_during_the_retries_is_released_not_lost(
        test_space, pg_pool):
    from vitalgraph.vectorization import index_sync_queue as q
    frame = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await _clear(conn, test_space)
        await q.enqueue(conn, test_space, _ctx(), [frame], "upsert")
        claimed = await q.claim(conn, test_space, "c1", 10)
    w, tx = await _writer_holding(pg_pool, test_space, [frame])

    async def commit_soon():
        await asyncio.sleep(0.08)
        await tx.commit()
    try:
        async with pg_pool.acquire() as conn:
            overtaken, _ = await asyncio.gather(
                q.complete(conn, test_space, "c1", claimed), commit_soon())
            [row] = await _rows(conn, test_space)
    finally:
        await pg_pool.release(w)
    assert overtaken == 1
    assert row["generation"] == 2 and row["claimed_by"] is None, (
        "the writer's bump survives, and the row is claimable again at once")


async def test_fail_and_release_do_not_wait_on_a_writer(test_space, pg_pool):
    from vitalgraph.vectorization import index_sync_queue as q
    a, b = sorted([uuid.uuid4(), uuid.uuid4()])
    async with pg_pool.acquire() as conn:
        await _clear(conn, test_space)
        await q.enqueue(conn, test_space, _ctx(), [a, b], "upsert")
        claimed = await q.claim(conn, test_space, "c1", 10)
    w, tx = await _writer_holding(pg_pool, test_space, [b])
    try:
        async with pg_pool.acquire() as conn:
            await asyncio.wait_for(q.fail(conn, test_space, "c1", claimed, "boom"), 10)
            rows = {r["subject_uuid"]: r for r in await _rows(conn, test_space)}
            assert rows[a]["claimed_by"] is None and rows[a]["last_error"] == "boom"
            assert rows[b]["claimed_by"] == "c1"
            assert await asyncio.wait_for(q.release(conn, test_space, "c1"), 10) == 0
    finally:
        await tx.rollback()
        await pg_pool.release(w)
    async with pg_pool.acquire() as conn:
        assert await q.release(conn, test_space, "c1") == 1, (
            "once the writer is gone, the held row is released")


# ---------------------------------------------------------------------------
# The consumers
# ---------------------------------------------------------------------------

class _Provider:
    """Slow, and counts how many embedding calls run at once."""

    def __init__(self, seconds=1.0, fail=False):
        self.seconds, self.fail = seconds, fail
        self.now = self.peak = 0

    async def vectorize_texts(self, texts):
        self.now += 1
        self.peak = max(self.peak, self.now)
        try:
            await asyncio.sleep(self.seconds)
            if self.fail:
                raise RuntimeError("provider down")
            return [[0.0] for _ in texts]
        finally:
            self.now -= 1

    async def vectorize_text(self, text):
        raise RuntimeError("provider down")


def _space_manager(space, pool):
    class _DB:
        internal_pool = pool

    class _Backend:
        db_impl = _DB()

    class _Impl:
        def get_db_space_impl(self):
            return _Backend()

    class _Record:
        space_impl = _Impl()

    class _SM:
        def list_active_spaces(self):
            return [space]

        async def get_space_or_load(self, space_id):
            return _Record() if space_id == space else None

    return _SM()


@pytest_asyncio.fixture(loop_scope="session")
async def pool3():
    """A 3-connection pool: the internal pool's default size."""
    from vitalgraph.db.pool import create_pool
    pool = await create_pool(host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
                             user=PG_USER, password=PG_PASSWORD,
                             min_size=3, max_size=3)
    yield pool
    await pool.close()


def _fake_vectors(monkeypatch, provider, written):
    from vitalgraph.vectorization import auto_sync

    async def plan(conn, space_id, subject_uuids, context_uuid, operation):
        await conn.fetchval("SELECT 1")     # the SQL half holds a connection
        return [auto_sync._VectorPlan("fake", provider, "", [(s, "t") for s in subject_uuids])]

    async def write(conn, space_id, context_uuid, plans):
        for p in plans:
            written.extend(s for s, _ in p.to_embed)

    monkeypatch.setattr(auto_sync, "_plan_vectors", plan)
    monkeypatch.setattr(auto_sync, "_write_vectors", write)


async def _max_wait_while(pool, done, interval=0.1):
    loop = asyncio.get_running_loop()
    worst = 0.0
    while not done():
        t0 = loop.time()
        async with pool.acquire():
            worst = max(worst, loop.time() - t0)
        await asyncio.sleep(interval)
    return worst


async def test_holding_the_connection_across_the_embedding_starves_the_pool(
        test_space, pool3, monkeypatch):
    """The control: the single-connection form, ten at once, as the
    fire-and-forget tasks ran. Another acquire waits for an embedding."""
    from vitalgraph.vectorization import auto_sync
    provider, written = _Provider(seconds=1.0), []
    _fake_vectors(monkeypatch, provider, written)

    async def held(i):
        async with pool3.acquire() as conn:
            await auto_sync._sync_vectors_for_subjects(
                conn, test_space, [uuid.uuid4()], _ctx(i), "upsert")
    tasks = [asyncio.create_task(held(i)) for i in range(10)]
    await asyncio.sleep(0.2)
    worst = await _max_wait_while(pool3, lambda: all(t.done() for t in tasks))
    await asyncio.gather(*tasks)
    assert worst >= 0.8, f"expected starvation, worst acquire waited {worst:.2f}s"


async def test_a_burst_is_bounded_and_does_not_starve_the_pool(
        test_space, pg_pool, pool3, monkeypatch):
    from vitalgraph.vectorization import index_sync_queue as q
    from vitalgraph.vectorization.index_sync_worker import IndexSyncWorker
    provider, written = _Provider(seconds=1.0), []
    _fake_vectors(monkeypatch, provider, written)
    subjects = [uuid.uuid4() for _ in range(10)]
    async with pg_pool.acquire() as conn:
        await _clear(conn, test_space)
        for i, s in enumerate(subjects):          # ten graphs: ten batches
            await q.enqueue(conn, test_space, _ctx(i), [s], "upsert")

    worker = IndexSyncWorker(_space_manager(test_space, pool3), consumers=2,
                             batch_size=1, sweep_seconds=0.2)
    run = asyncio.create_task(worker.run())
    try:
        worst = await asyncio.wait_for(
            _max_wait_while(pool3, lambda: len(written) >= len(subjects)), 60)
    finally:
        worker.stop()
        await run
    assert sorted(written) == sorted(subjects)
    assert provider.peak <= 2, f"{provider.peak} embeddings ran at once with 2 consumers"
    assert worst < 0.5, f"an unrelated acquire waited {worst:.2f}s"
    async with pg_pool.acquire() as conn:
        assert await _rows(conn, test_space) == []


async def test_a_provider_outage_is_retried_not_recorded_as_done(
        test_space, pg_pool, pool3, monkeypatch):
    from vitalgraph.vectorization import index_sync_queue as q
    from vitalgraph.vectorization.index_sync_worker import IndexSyncWorker
    provider, written = _Provider(seconds=0.0, fail=True), []
    _fake_vectors(monkeypatch, provider, written)
    s = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await _clear(conn, test_space)
        await q.enqueue(conn, test_space, _ctx(), [s], "upsert")
    worker = IndexSyncWorker(_space_manager(test_space, pool3), consumers=1)
    assert await worker.drain_once(test_space) == 1
    async with pg_pool.acquire() as conn:
        [row] = await _rows(conn, test_space)
    assert row["subject_uuid"] == s and "EmbeddingUnavailable" in row["last_error"]
    assert row["claimed_by"] is None and row["attempts"] == 1
    assert written == []
