"""Workload-class pools, and the one number that can overturn the design.

`issues/231`. Three classes reach PostgreSQL — QUERY (read-only, must never
starve), MUTATION (request-driven writes), INTERNAL (ANALYZE, VACUUM, backfill,
segmentation, auto-sync; always deferrable). Each gets its own pool, so a class
that misbehaves exhausts only its own share.

SEPARATE POOLS WERE CHOSEN OVER A SHARED LIMITER on manageability, accepting a
known cost: the budget is partitioned statically, so QUERY can wait while
INTERNAL sits idle. `other_classes_idle` exists to measure exactly that cost —
it is the capacity a limiter could have lent — so the decision can be revisited
on evidence.

That makes these tests load-bearing in an unusual way: if `other_classes_idle`
is wrong, the later analysis is wrong, and the wrong architecture gets chosen
from data that looked fine. The specific failure to guard against is reading it
at the WRONG MOMENT — after the wait rather than before — because by then the
capacity that would have answered the question has usually been handed over.
"""

import asyncio
import logging

import pytest

from vitalgraph.db import pool as poolmod
from vitalgraph.db.pool import PoolClass, other_classes_idle, register_pool


class _FakePool:
    """Only what the accounting reads: max, current size, idle."""

    def __init__(self, max_size, size, idle):
        self._max, self._size, self._idle = max_size, size, idle
        self.pool_class = None

    def get_max_size(self):
        return self._max

    def get_size(self):
        return self._size

    def get_idle_size(self):
        return self._idle


@pytest.fixture(autouse=True)
def _clean_registry():
    poolmod._REGISTRY.clear()
    _KEEP.clear()
    yield
    poolmod._REGISTRY.clear()
    _KEEP.clear()


# The registry holds WEAK references, so every pool a test registers must stay
# bound for the life of the test. An unbound one is collected before the
# assertion runs and reads as "no such class" — which is correct behaviour, and
# was the first thing these tests caught (in themselves).
_KEEP = []


def _register(cls, max_size, size, idle):
    p = _FakePool(max_size, size, idle)
    register_pool(p, cls)
    _KEEP.append(p)
    return p


# --------------------------------------------------------------------------
# the accounting
# --------------------------------------------------------------------------

def test_idle_excludes_the_asking_class():
    """A waiter's own free capacity is not capacity a limiter could lend it —
    it is capacity it already has."""
    _register(PoolClass.QUERY, 10, 10, 4)       # 6 in use, 4 free
    _register(PoolClass.INTERNAL, 3, 3, 3)      # 0 in use, 3 free
    assert other_classes_idle(PoolClass.QUERY) == 3


def test_idle_sums_across_every_other_class():
    _register(PoolClass.QUERY, 10, 10, 2)
    _register(PoolClass.MUTATION, 5, 5, 1)
    _register(PoolClass.INTERNAL, 3, 3, 3)
    assert other_classes_idle(PoolClass.QUERY) == 4      # 1 + 3


def test_unopened_connections_count_as_idle():
    """A pool at size 1 of max 3 can still open two more. Counting only
    `get_idle_size()` would under-report lendable capacity by the amount the
    pool has not bothered to open yet — which at low traffic is most of it."""
    _register(PoolClass.QUERY, 10, 10, 0)
    _register(PoolClass.INTERNAL, 3, 1, 1)      # 0 in use, 3 lendable
    assert other_classes_idle(PoolClass.QUERY) == 3


def test_a_fully_busy_sibling_lends_nothing():
    """The case that means the static partition cost NOTHING: everyone is
    busy, so a limiter would have had nothing to hand over."""
    _register(PoolClass.QUERY, 10, 10, 0)
    _register(PoolClass.INTERNAL, 3, 3, 0)
    assert other_classes_idle(PoolClass.QUERY) == 0


def test_a_broken_sibling_does_not_break_the_probe():
    """Diagnostics must never mask the real path."""
    class _Broken(_FakePool):
        def get_size(self):
            raise RuntimeError("pool is closing")

    _register(PoolClass.QUERY, 10, 10, 0)
    b = _Broken(3, 3, 3)
    register_pool(b, PoolClass.INTERNAL)
    assert other_classes_idle(PoolClass.QUERY) == 0     # skipped, not raised


def test_an_unclassed_pool_is_not_in_the_registry():
    assert other_classes_idle(None) == 0


def test_the_registry_holds_weak_references():
    """A closed pool kept alive by the registry would be counted as lendable
    capacity that does not exist."""
    import gc
    p = _register(PoolClass.INTERNAL, 3, 3, 3)
    assert other_classes_idle(PoolClass.QUERY) == 3
    _KEEP.remove(p)
    del p
    gc.collect()
    assert other_classes_idle(PoolClass.QUERY) == 0


# --------------------------------------------------------------------------
# the record
# --------------------------------------------------------------------------

def _ctx_for(pool):
    return poolmod._LoggingAcquireContext(pool, None)


def test_a_fast_acquire_writes_nothing(caplog):
    """The fast path must not pay for the diagnostics."""
    p = _register(PoolClass.QUERY, 10, 10, 5)
    with caplog.at_level(logging.WARNING):
        _ctx_for(p)._report_slow(0.001, other_idle=3)
    assert "pool_wait" not in caplog.text


def test_a_slow_acquire_records_the_class_and_the_sibling_idle(caplog):
    p = _register(PoolClass.QUERY, 10, 10, 0)
    with caplog.at_level(logging.WARNING):
        _ctx_for(p)._report_slow(2.5, other_idle=3)
    assert "pool_wait" in caplog.text
    assert "'class': 'query'" in caplog.text
    assert "'waited_ms': 2500" in caplog.text
    assert "'other_classes_idle': 3" in caplog.text


def test_the_record_survives_a_pool_that_cannot_report_state(caplog):
    class _Broken(_FakePool):
        def get_size(self):
            raise RuntimeError("closing")

    b = _Broken(10, 10, 0)
    register_pool(b, PoolClass.QUERY)
    with caplog.at_level(logging.WARNING):
        _ctx_for(b)._report_slow(2.0, other_idle=1)
    assert "state unavailable" in caplog.text


@pytest.mark.asyncio
async def test_sibling_idle_is_read_before_the_wait_not_after():
    """THE ORDERING THAT MAKES THE NUMBER MEAN ANYTHING.

    Read after the wait, it describes the world at the moment the wait ENDED —
    by which time the sibling capacity that would have answered the question
    has usually been handed over. This drives a real acquire through the
    context manager with a sibling that empties while the wait is in progress,
    and asserts the recorded value is the one from the START.
    """
    query = _register(PoolClass.QUERY, 10, 10, 0)
    sibling = _register(PoolClass.INTERNAL, 3, 3, 3)    # 3 lendable at t0

    class _SlowCtx:
        async def __aenter__(self):
            sibling._idle = 0      # sibling fills up DURING the wait
            sibling._size = 3
            await asyncio.sleep(0)
            return "conn"

        async def __aexit__(self, *a):
            return False

    class _Recorder(poolmod._LoggingAcquireContext):
        # `_LoggingAcquireContext` uses __slots__, so the override has to be a
        # subclass rather than an attribute assignment.
        __slots__ = ("seen",)

        def _report_slow(self, waited, other=None):
            self.seen = other

    ctx = _Recorder(query, _SlowCtx())
    async with ctx:
        pass
    assert ctx.seen == 3, (
        "the sibling had 3 free when the wait began; reading after the wait "
        "would record 0 and understate the limiter's upside")


def test_the_mixed_request_pool_is_not_labelled_query():
    """Until step 3 splits them, one pool serves reads AND writes.

    Labelling it QUERY would file every mutation's wait as a query wait, and
    the analysis would then report reader starvation that is really writers
    queueing behind each other — leading to the wrong fix, from data that
    looked authoritative. The mixed pool gets its own name until it is
    genuinely split.
    """
    from vitalgraph.db.sparql_sql import sparql_sql_db_impl
    import inspect

    src = inspect.getsource(sparql_sql_db_impl)
    assert "register_pool(self.connection_pool, PoolClass.REQUEST)" in src
    assert "register_pool(self.connection_pool, PoolClass.QUERY)" not in src, (
        "the shared read+write pool must not claim to be the QUERY pool")


def test_request_and_internal_are_distinct_classes():
    """They must key the registry separately, or one overwrites the other and
    `other_classes_idle` silently reads from a single pool."""
    _register(PoolClass.REQUEST, 30, 30, 0)
    _register(PoolClass.INTERNAL, 3, 3, 3)
    assert other_classes_idle(PoolClass.REQUEST) == 3
    assert other_classes_idle(PoolClass.INTERNAL) == 0
