"""A second ANALYZE skips instead of queueing behind the first.

`issues/230`. ANALYZE takes a ShareUpdateExclusiveLock, which conflicts with
ITSELF, so concurrent ANALYZE on one table is strictly serial. `maybe_analyze`
had one guard — an in-process row-change counter — and reset it only when the
ANALYZE COMPLETED. Every writer in a burst therefore read the same
over-threshold count, every one started an ANALYZE, and they queued one at a
time, each holding a pooled connection.

Measured in production: six `ANALYZE "{space}_term"` stacked on each other, the
connection pool exhausted behind them, and ordinary queries going from 0.22s to
over 50s. `pg_locks` sampled through it showed 1,599 ungranted
ShareUpdateExclusiveLock and nothing else.

WAITING IS STRICTLY WORSE THAN NOT ANALYSING — the statistics a waiter would
produce are the ones the holder is already producing — so the lock is
`pg_try_advisory_lock` and a failure to get it returns immediately.

Two properties are pinned separately because the defect needed both:

  * a caller that cannot get the lock does NOT analyse, and
  * the counter is reset BEFORE the run, not after, so callers arriving during
    it are not still over threshold.

And the lock must be released on the SAME connection, or a session-scoped lock
rides a pooled connection back into the pool and blocks that space's ANALYZE
until the connection is recycled.
"""

import pytest

from vitalgraph.db.sparql_sql import auto_analyze
from vitalgraph.process.process_lock_manager import process_lock_key

SPACE = "sp_test"


class _Conn:
    """Records every statement; `lock_free` decides what try_advisory_lock says."""

    def __init__(self, lock_free=True):
        self.lock_free = lock_free
        self.calls = []

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args))
        if "pg_try_advisory_lock" in sql:
            return self.lock_free
        if "pg_advisory_unlock" in sql:
            return True
        return None

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        return "ANALYZE"

    def analyzes(self):
        return [s for s, _ in self.calls if s.startswith("ANALYZE")]

    def locked(self):
        return [a for s, a in self.calls if "pg_try_advisory_lock" in s]

    def unlocked(self):
        return [a for s, a in self.calls if "pg_advisory_unlock" in s]


@pytest.fixture(autouse=True)
def _over_threshold():
    auto_analyze._change_counts[SPACE] = auto_analyze.DEFAULT_ANALYZE_THRESHOLD + 1
    auto_analyze._last_analyze_time.pop(SPACE, None)
    yield
    auto_analyze._change_counts.pop(SPACE, None)
    auto_analyze._last_analyze_time.pop(SPACE, None)


@pytest.mark.asyncio
async def test_it_analyses_when_the_lock_is_free():
    conn = _Conn(lock_free=True)
    assert await auto_analyze.maybe_analyze(conn, SPACE) is True
    assert len(conn.analyzes()) == 7, "all per-space tables"


@pytest.mark.asyncio
async def test_a_held_lock_means_skip_not_wait():
    conn = _Conn(lock_free=False)
    assert await auto_analyze.maybe_analyze(conn, SPACE) is False
    assert conn.analyzes() == [], (
        "a caller that cannot take the lock must not ANALYZE — queueing is "
        "what exhausted the pool")


@pytest.mark.asyncio
async def test_the_lock_key_is_shared_with_the_store_path():
    """`_maybe_analyze_aux_tables` already used ('analyze', space_id). A
    different key here would mean the two paths never exclude each other."""
    conn = _Conn(lock_free=True)
    await auto_analyze.maybe_analyze(conn, SPACE)
    assert conn.locked() == [(process_lock_key("analyze", SPACE),)]


@pytest.mark.asyncio
async def test_the_lock_is_released_on_the_same_connection():
    conn = _Conn(lock_free=True)
    await auto_analyze.maybe_analyze(conn, SPACE)
    assert conn.unlocked() == [(process_lock_key("analyze", SPACE),)]


@pytest.mark.asyncio
async def test_the_lock_is_released_even_when_analyze_fails():
    conn = _Conn(lock_free=True)

    async def boom(sql, *args):
        conn.calls.append((sql, args))
        raise RuntimeError("ANALYZE exploded")
    conn.execute = boom

    assert await auto_analyze.maybe_analyze(conn, SPACE) is False
    assert conn.unlocked(), "a failure must not strand the lock on the pool"


@pytest.mark.asyncio
async def test_the_counter_is_reset_before_the_run():
    """Left over threshold for the duration, the next caller still arrives
    thinking it must analyse — which is how the pile-up formed."""
    seen = {}

    conn = _Conn(lock_free=True)
    orig = conn.execute

    async def spy(sql, *args):
        seen.setdefault("count_during_run", auto_analyze.get_counter(SPACE))
        return await orig(sql, *args)
    conn.execute = spy

    await auto_analyze.maybe_analyze(conn, SPACE)
    assert seen["count_during_run"] == 0


@pytest.mark.asyncio
async def test_below_threshold_touches_nothing():
    auto_analyze._change_counts[SPACE] = 1
    conn = _Conn(lock_free=True)
    assert await auto_analyze.maybe_analyze(conn, SPACE) is False
    assert conn.calls == [], "no lock probe, no round trip, below threshold"
