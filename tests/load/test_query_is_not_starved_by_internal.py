"""QUERY keeps serving while INTERNAL and MUTATION are saturated.

`issues/231`. This is the test that would have caught 2026-09-24, when six
stacked `ANALYZE` held six of thirty REQUEST connections and production stopped
answering. Nothing in the unit suite could see it: every part worked, and the
failure was one class consuming another's capacity.

RUN IT LOCALLY against the docker test stack:

    python -m pytest tests/load/test_query_is_not_starved_by_internal.py -q -s

WHAT IT ASSERTS, and why each is a separate test rather than one big one:

  * the harness can actually starve a shared pool — if this fails the rest
    prove nothing, because a test that cannot reproduce the failure cannot
    demonstrate the fix;
  * a saturated INTERNAL pool does not slow QUERY;
  * QUERY's own exhaustion is still reported, so isolation has not been bought
    by making saturation invisible.

The load is `pg_sleep`, deliberately: it holds a connection for a known
duration without depending on any schema, so the harness measures POOL
behaviour and not query-plan behaviour.
"""

from __future__ import annotations

import asyncio
import statistics
import time

import pytest

# Connection settings come from the integration conftest, which OWNS them
# (including the `issues/099` port-5433 correction). A second copy here would
# drift and end up measuring a different cluster.
from tests.integration.conftest import (
    PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD,
)
from vitalgraph.db.pool import PoolClass, create_pool, register_pool

pytestmark = pytest.mark.asyncio(loop_scope="function")

PG = {
    "host": PG_HOST, "port": PG_PORT, "database": PG_DATABASE,
    "user": PG_USER, "password": PG_PASSWORD,
}

HOLD_SECONDS = 1.5          # how long each background hog holds a connection
QUERY_BUDGET_SECONDS = 0.5  # a read must complete within this while hogs run


async def _pool(max_size, cls=None, acquire_timeout=5.0):
    p = await create_pool(min_size=1, max_size=max_size,
                          acquire_timeout=acquire_timeout, **PG)
    if cls is not None:
        register_pool(p, cls)
    return p


async def _reachable() -> bool:
    try:
        p = await _pool(1)
        async with p.acquire() as c:
            await c.fetchval("SELECT 1")
        await p.close()
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
async def _skip_without_pg():
    if not await _reachable():
        pytest.skip(f"PostgreSQL not reachable at {PG['host']}:{PG['port']}")


async def _hog(pool, seconds=HOLD_SECONDS):
    """Occupy one connection for `seconds`, as ANALYZE or a bulk write does."""
    async with pool.acquire() as c:
        await c.fetchval("SELECT pg_sleep($1)", seconds)


async def _timed_read(pool):
    t0 = time.monotonic()
    async with pool.acquire() as c:
        await c.fetchval("SELECT 1")
    return time.monotonic() - t0


async def _read_repeatedly(pool, stop_at, out):
    while time.monotonic() < stop_at:
        out.append(await _timed_read(pool))
        await asyncio.sleep(0.02)


# --------------------------------------------------------------------------

async def test_the_harness_can_starve_a_shared_pool():
    """THE CONTROL. Without this, the isolation tests below prove nothing —
    a harness that cannot reproduce starvation cannot demonstrate its absence.

    One pool, every connection taken by background work: reads must suffer.
    This is 2026-09-24 in miniature.
    """
    shared = await _pool(4, acquire_timeout=10.0)
    try:
        hogs = [asyncio.create_task(_hog(shared)) for _ in range(4)]
        await asyncio.sleep(0.15)          # let them take every connection
        waited = await _timed_read(shared)
        await asyncio.gather(*hogs)
    finally:
        await shared.close()

    print(f"\n  shared pool, reader waited {waited*1000:.0f}ms")
    assert waited > QUERY_BUDGET_SECONDS, (
        "the harness did not starve a shared pool, so it cannot prove the "
        "separated pools are better")


async def test_query_is_unaffected_by_a_saturated_internal_pool():
    """The fix, stated as an experiment: same load, separate pools."""
    query = await _pool(4, PoolClass.QUERY)
    internal = await _pool(3, PoolClass.INTERNAL)
    try:
        hogs = [asyncio.create_task(_hog(internal)) for _ in range(6)]
        await asyncio.sleep(0.15)
        latencies: list[float] = []
        await _read_repeatedly(query, time.monotonic() + HOLD_SECONDS, latencies)
        await asyncio.gather(*hogs)
    finally:
        await query.close()
        await internal.close()

    p99 = max(latencies)
    print(f"\n  INTERNAL saturated: {len(latencies)} reads, "
          f"median {statistics.median(latencies)*1000:.1f}ms, max {p99*1000:.1f}ms")
    assert latencies, "no reads completed"
    assert p99 < QUERY_BUDGET_SECONDS, (
        f"QUERY waited {p99:.2f}s while only INTERNAL was saturated — the "
        f"pools are not isolated")


async def test_query_is_unaffected_by_a_saturated_mutation_pool():
    """Writers hold connections longer than readers, which is why a shared
    pool degrades to starvation under sustained write load."""
    query = await _pool(4, PoolClass.QUERY)
    mutation = await _pool(3, PoolClass.MUTATION)
    try:
        hogs = [asyncio.create_task(_hog(mutation)) for _ in range(6)]
        await asyncio.sleep(0.15)
        latencies: list[float] = []
        await _read_repeatedly(query, time.monotonic() + HOLD_SECONDS, latencies)
        await asyncio.gather(*hogs)
    finally:
        await query.close()
        await mutation.close()

    assert latencies
    assert max(latencies) < QUERY_BUDGET_SECONDS


async def test_both_other_classes_saturated_at_once():
    """The real shape of the incident: a bulk copy (MUTATION) whose
    consequences (INTERNAL) are still running."""
    query = await _pool(4, PoolClass.QUERY)
    mutation = await _pool(3, PoolClass.MUTATION)
    internal = await _pool(3, PoolClass.INTERNAL)
    try:
        hogs = [asyncio.create_task(_hog(p))
                for p in (mutation, internal) for _ in range(6)]
        await asyncio.sleep(0.15)
        latencies: list[float] = []
        await _read_repeatedly(query, time.monotonic() + HOLD_SECONDS, latencies)
        await asyncio.gather(*hogs)
    finally:
        for p in (query, mutation, internal):
            await p.close()

    print(f"\n  both saturated: {len(latencies)} reads, "
          f"max {max(latencies)*1000:.1f}ms")
    assert latencies
    assert max(latencies) < QUERY_BUDGET_SECONDS


async def test_query_exhaustion_is_still_reported(caplog):
    """ISOLATION MUST NOT BE BOUGHT WITH SILENCE.

    If QUERY itself is saturated that is a real problem and has to be visible —
    `issues/229` was exactly a saturation that produced a quiet wrong answer.
    """
    import logging
    query = await _pool(2, PoolClass.QUERY, acquire_timeout=10.0)
    internal = await _pool(3, PoolClass.INTERNAL)
    try:
        hogs = [asyncio.create_task(_hog(query, 2.0)) for _ in range(2)]
        await asyncio.sleep(0.15)
        with caplog.at_level(logging.WARNING):
            await _timed_read(query)
        await asyncio.gather(*hogs)
    finally:
        await query.close()
        await internal.close()

    assert "pool_wait" in caplog.text, "a starved QUERY pool must say so"
    assert "'class': 'query'" in caplog.text
    # And the record must carry what the other classes had free at that moment
    # — the number the separate-pools decision is revisited on.
    assert "other_classes_idle" in caplog.text
