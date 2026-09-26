"""`asyncio.gather` with a ceiling on how many legs run at once.

`issues/231`, step 2. The endpoints fan out one transaction PER URI THE CALLER
SUPPLIED::

    gather(*[_delete_one(u)  for u in uris])          # kgentities_endpoint
    gather(*[_fetch_quads(i) for i in identifiers])   # kgentities_endpoint
    gather(*[_fetch_frame(u) for u in frame_uris])    # kgframes_endpoint

so a client passing 500 URIs opens 500 concurrent transactions against a pool
of 30. That is `issues/229` seen from the other side — one request monopolising
the pool until everything else queues — and it is how `--batch 10` in the
archive migration became 100 concurrent server-side deletes: the script bounded
its own concurrency and the server multiplied it back out.

THE LIMIT IS NOT AN OPTIMISATION. Beyond the pool size, extra legs cannot make
progress — they queue on `acquire()` — so the only thing unbounded fan-out buys
over a bounded one is the ability to starve every other request while doing it.
Work queued in the application is cheap, cancellable and observable; work queued
inside PostgreSQL holds a connection and is invisible until someone samples
`pg_stat_activity`.

WHY FACTORIES, NOT COROUTINES. `gather(*[f(x) for x in xs])` has already
CREATED every coroutine before the semaphore is consulted, and each holds its
arguments alive; more importantly a coroutine that is never awaited (because an
earlier leg failed and the gather was cancelled) emits "coroutine was never
awaited". Taking zero-argument callables means nothing is constructed until a
slot is free.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, List, Optional, Sequence, TypeVar

T = TypeVar("T")

# Concurrent database legs allowed within ONE request.
#
# Deliberately well under the pool: a single request must not be ABLE to take
# the whole pool, or one caller's 500-URI batch is indistinguishable from an
# outage for everyone else. The point is to leave room, not to use it all.
DEFAULT_FANOUT = 8


async def bounded_gather(
    factories: Sequence[Callable[[], Awaitable[T]]],
    limit: Optional[int] = None,
    *,
    return_exceptions: bool = False,
) -> List[T]:
    """Run *factories* with at most *limit* in flight, preserving input order.

    A drop-in for ``asyncio.gather(*[f(x) for x in xs])`` where the list length
    is caller-controlled. Order of results matches order of *factories*, as
    ``gather`` does — several call sites zip the results back against their
    input list, so this is load-bearing, not incidental.
    """
    if limit is None:
        limit = DEFAULT_FANOUT
    if not factories:
        return []
    # Below the limit there is nothing to bound, and a semaphore that is never
    # contended is pure overhead on the common small-batch path.
    if limit <= 0 or len(factories) <= limit:
        return await asyncio.gather(
            *[f() for f in factories], return_exceptions=return_exceptions)

    sem = asyncio.Semaphore(limit)

    async def _run(factory):
        async with sem:
            return await factory()

    return await asyncio.gather(
        *[_run(f) for f in factories], return_exceptions=return_exceptions)
