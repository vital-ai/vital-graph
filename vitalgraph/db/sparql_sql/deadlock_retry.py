"""Bounded retry for transactions Postgres aborts as a deadlock victim.

`40P01` is not a failure of the work — it is Postgres picking one of two
transactions to abort so the other can proceed. The right response is to run
it again. Nothing on the write path did, so the victim's whole batch was
discarded and, in the segmentation worker, stored as a permanent job failure
(`issues/115`).

Deterministic lock ordering in the stats sync removes the common case. This
covers what ordering cannot: a transaction that also locks rows elsewhere, or
two paths whose orders have drifted apart again.

Retry is only correct where WE own the transaction. When a caller passes its
own connection it owns the transaction boundary, and re-running the body
inside an already-aborted transaction cannot work — those paths propagate.
"""

from __future__ import annotations

import asyncio
import logging

import asyncpg

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
# Deadlock resolution is immediate — the backoff exists to break the symmetry
# of two writers retrying in lockstep, not to wait for a lock to clear.
BASE_BACKOFF_SECONDS = 0.05


async def with_deadlock_retry(pool, body, *, what: str, attempts: int = MAX_ATTEMPTS):
    """Run ``await body(conn)`` in a transaction, retrying deadlock victims.

    Each attempt acquires its own connection and opens its own transaction, so
    a retry starts from a clean one. ``body`` must therefore be repeatable:
    everything it does is rolled back before it runs again.
    """
    for attempt in range(1, attempts + 1):
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    return await body(conn)
        except asyncpg.DeadlockDetectedError:
            if attempt == attempts:
                logger.error(
                    "%s: deadlock victim %d times, giving up. Two writers are "
                    "taking the same locks in different orders and retrying "
                    "has not separated them; see issues/115.", what, attempts)
                raise
            delay = BASE_BACKOFF_SECONDS * attempt
            logger.warning(
                "%s: chosen as deadlock victim (attempt %d/%d), retrying in "
                "%.0fms", what, attempt, attempts, delay * 1000)
            await asyncio.sleep(delay)
