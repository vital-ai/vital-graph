"""Run on a caller's connection, or acquire one. `issues/175` class 2.

Write and read methods each acquired their own connection, so two of them could
not be composed into one unit of work: a lock taken in one was invisible to the
other, a caller could not abort a sequence it had begun, and a read could not be
made atomic with the write that acted on it.

Lives here rather than beside its first caller because both the db layer and the
kg_impl layer need it, and kg_impl already depends on this package — putting it
the other way round would invert that.
"""
from __future__ import annotations

import contextlib

__all__ = ["write_conn"]


@contextlib.asynccontextmanager
async def write_conn(pool, conn=None):
    """Yield *conn* if given, otherwise acquire one from *pool* for the block.

    `conn=None` behaves exactly as the original acquire did, so nothing that
    does not opt in changes — which matters because the callers are on live
    read and write paths.

    THE TRANSACTION STAYS WITH THE CALLER OF THIS, not here. Nested on a
    supplied connection a `conn.transaction()` becomes a SAVEPOINT, which
    preserves what each block was written for — a failure rolls back only its own
    work — while the commit boundary moves to whoever owns the unit of work.
    Opening the transaction here would take that choice away from them.
    """
    if conn is not None:
        yield conn
    else:
        async with pool.acquire() as owned:
            yield owned
