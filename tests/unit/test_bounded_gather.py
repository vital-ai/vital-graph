"""Per-request database fan-out has a ceiling. `issues/231`, step 2.

The endpoints open one transaction per URI THE CALLER SUPPLIED, so a client
passing 500 URIs opened 500 concurrent transactions against a pool of 30 — one
request able to monopolise the pool, which is `issues/229` from the other side.
It is also how the archive script's `--batch 10` became 100 concurrent
server-side deletes: the client bounded itself and the server multiplied it
back out.

THE ASSERTION THAT MATTERS is `test_it_never_exceeds_the_limit`, which observes
PEAK CONCURRENCY rather than trusting that a semaphore is present. A semaphore
acquired in the wrong place — after the awaitable is created, or released too
early — still reads as "bounded" in the source and bounds nothing.
"""

import asyncio

import pytest

from vitalgraph.utils.bounded_gather import DEFAULT_FANOUT, bounded_gather


class _Tracker:
    """Records the high-water mark of simultaneously-running legs."""

    def __init__(self):
        self.now = 0
        self.peak = 0
        self.order = []

    def leg(self, i, delay=0.01):
        async def _run():
            self.now += 1
            self.peak = max(self.peak, self.now)
            try:
                await asyncio.sleep(delay)
                self.order.append(i)
                return i
            finally:
                self.now -= 1
        return _run


@pytest.mark.asyncio
async def test_it_never_exceeds_the_limit():
    """THE POINT. Peak observed concurrency, not the presence of a semaphore."""
    t = _Tracker()
    out = await bounded_gather([t.leg(i) for i in range(50)], limit=4)
    assert t.peak <= 4, f"{t.peak} legs ran at once against a limit of 4"
    assert out == list(range(50))


@pytest.mark.asyncio
async def test_it_actually_runs_concurrently():
    """A limit of 1 would also pass the test above. Bounded is not serial —
    serialising these would turn a 500-URI request into 500 round trips."""
    t = _Tracker()
    await bounded_gather([t.leg(i) for i in range(20)], limit=5)
    assert t.peak == 5, f"peak was {t.peak}; the limit is a ceiling, not a target"


@pytest.mark.asyncio
async def test_results_keep_input_order():
    """Load-bearing: several call sites `zip(uris, results)`. Order coming back
    in COMPLETION order there would attribute each result to the wrong URI —
    a silent data-corruption bug, not a visible failure."""
    async def _slow(): await asyncio.sleep(0.03); return "slow"
    async def _fast(): return "fast"
    out = await bounded_gather([lambda: _slow(), lambda: _fast()], limit=2)
    assert out == ["slow", "fast"]


@pytest.mark.asyncio
async def test_a_short_list_skips_the_semaphore_entirely():
    t = _Tracker()
    out = await bounded_gather([t.leg(i) for i in range(3)], limit=8)
    assert out == [0, 1, 2]
    assert t.peak == 3, "a batch under the limit must not be throttled"


@pytest.mark.asyncio
async def test_an_empty_list_is_not_an_error():
    assert await bounded_gather([]) == []


@pytest.mark.asyncio
async def test_exceptions_propagate_by_default():
    """Matching `gather`. `issues/229` was a swallowed failure; this must not
    become another place one can hide."""
    async def _boom(): raise ValueError("leg failed")
    with pytest.raises(ValueError, match="leg failed"):
        await bounded_gather([lambda: _boom()] * 3, limit=2)


@pytest.mark.asyncio
async def test_return_exceptions_is_honoured():
    async def _boom(): raise ValueError("x")
    async def _ok(): return 1
    out = await bounded_gather([lambda: _boom(), lambda: _ok()],
                               limit=2, return_exceptions=True)
    assert isinstance(out[0], ValueError) and out[1] == 1


@pytest.mark.asyncio
async def test_the_default_leaves_room_in_the_pool():
    """A single request must not be ABLE to take the whole pool. The default
    is checked against the smallest pool the service configures, because a
    default above it makes the bound decorative."""
    t = _Tracker()
    await bounded_gather([t.leg(i) for i in range(40)])
    assert t.peak <= DEFAULT_FANOUT
    assert DEFAULT_FANOUT < 10, (
        "the per-request fan-out must stay well under the pool size, or one "
        "caller's batch is indistinguishable from an outage for everyone else")
