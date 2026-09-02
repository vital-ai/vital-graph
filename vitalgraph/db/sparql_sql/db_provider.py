"""
Database provider for the sparql_sql pipeline.

Uses ``DbImplInterface`` from ``vitalgraph.db.db_inf`` as the accepted type.
Callers pass a concrete ``DbImplInterface`` implementation via
``configure(impl)``.  The pipeline accesses the implementation's
``connection_pool`` (asyncpg.Pool) for all SQL operations, including
connection reuse and raw connection access.

In the service, the implementation is ``SparqlSQLDbImpl`` — the new
pure-PostgreSQL backend that owns its own asyncpg pool.  In dev/test,
``DevDbImpl`` fills the same role.

Usage within the pipeline (unchanged):
    from . import db_provider as db
    rows = await db.execute_query(sql, conn_params=conn_params, conn=conn)

Setup (done once at startup):
    from vitalgraph.db.sparql_sql import db_provider
    db_provider.configure(db_impl)   # any DbImplInterface with connection_pool
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from ..db_inf import DbImplInterface

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# %s → $1 parameter conversion (psycopg convention → asyncpg convention)
# ---------------------------------------------------------------------------

def _pg_params_to_asyncpg(sql: str, params: Optional[tuple] = None):
    """Convert %s-style placeholders to $1, $2, ... for asyncpg."""
    if params is None:
        return sql, []
    args = list(params)
    result = []
    idx = 0
    i = 0
    while i < len(sql):
        if sql[i] == '%' and i + 1 < len(sql) and sql[i + 1] == 's':
            idx += 1
            result.append(f'${idx}')
            i += 2
        else:
            result.append(sql[i])
            i += 1
    return ''.join(result), args


# ---------------------------------------------------------------------------
# Module-level configured implementation
# ---------------------------------------------------------------------------

_impl: Optional[DbImplInterface] = None


def configure(impl: DbImplInterface) -> None:
    """Set the DbImplInterface implementation for the pipeline.

    The implementation must expose a ``connection_pool`` attribute
    (asyncpg.Pool) for raw connection access.
    """
    global _impl
    if not hasattr(impl, 'connection_pool'):
        raise TypeError(
            f"{type(impl).__name__} does not have a connection_pool attribute. "
            "The sparql_sql pipeline requires direct asyncpg pool access."
        )
    _impl = impl
    logger.info("db_provider configured with %s", type(impl).__name__)


def is_configured() -> bool:
    """Check whether an implementation has been configured."""
    return _impl is not None


def _get() -> DbImplInterface:
    if _impl is None:
        raise RuntimeError(
            "db_provider not configured. "
            "Call db_provider.configure(db_impl) before using the pipeline."
        )
    return _impl


def get_pool():
    """Return the asyncpg.Pool from the configured implementation."""
    return _get().connection_pool


# ---------------------------------------------------------------------------
# Async API — uses the configured implementation's connection_pool
# ---------------------------------------------------------------------------

# How long a STATS read may wait for a lock before giving up. These reads feed
# the join-reorder heuristic, the semi-join gate and the slot-type tautology
# check: they improve a plan, they are not part of the answer, and every caller
# already runs without them. Waiting the pool-wide 10s to maybe improve a plan is
# never the right trade -- after 10s you get the worse plan anyway, having paid
# 10s for it. Measured in `issues/145`: two such waits turned a 1,851ms request
# into 21,980ms.
STATS_LOCK_TIMEOUT_MS = 100


@asynccontextmanager
async def bounded_lock_wait(conn, lock_timeout_ms: int = STATS_LOCK_TIMEOUT_MS):
    """Bound how long statements on *conn* wait for a lock, then restore.

    For reads that are an optimisation input rather than part of the answer, so
    they fail fast instead of parking behind a writer (`issues/145`).

    NOT `SET LOCAL` in a transaction of our own: `create_transaction()` hands
    callers a connection with one already open, asyncpg nests as a savepoint,
    and SET LOCAL survives a savepoint RELEASE to the end of the OUTER
    transaction — silently imposing this timeout on the caller's remaining
    statements. Save/restore is correct whether or not a transaction is open.
    """
    prev = await conn.fetchval("SHOW lock_timeout")
    await conn.execute(f"SET lock_timeout = '{int(lock_timeout_ms)}ms'")
    try:
        yield
    finally:
        try:
            await conn.execute(f"SET lock_timeout = '{prev}'")
        except Exception:  # pragma: no cover - abort path
            # The statement failed inside the caller's transaction, so the
            # restore fails too. Their ROLLBACK reverts the SET, and a
            # connection returned to the pool is reset regardless; masking the
            # real error with this one would be strictly worse.
            logger.debug("could not restore lock_timeout to %s", prev)


async def execute_query(sql, params=None, conn_params=None, conn=None,
                        *, lock_timeout_ms: Optional[int] = None):
    """Execute a SQL query and return rows as list of dicts.

    If *conn* is provided (an asyncpg connection), reuses it.
    Otherwise acquires from the implementation's pool.

    *lock_timeout_ms* bounds how long the statement will WAIT FOR A LOCK before
    giving up; it does not bound execution. Pass it for reads that are an
    optimisation input rather than part of the answer, so they fail fast instead
    of parking behind a writer — see `issues/145`, where two such reads each
    waited the pool-wide `lock_timeout` of 10s behind a `TRUNCATE`, turning a
    1.9s request into 22s and then planning without the stats anyway.

    The previous value is restored afterwards, so it cannot leak to the next
    user of a pooled connection nor to the rest of a caller's transaction. The
    wait can happen at PREPARE, not just execute — that is where asyncpg raised
    in `issues/145` — and the timeout is in force before the statement is sent.
    """
    asql, args = _pg_params_to_asyncpg(sql, params)

    async def _run(c):
        if lock_timeout_ms is None:
            rows = await c.fetch(asql, *args)
            return [dict(r) for r in rows]
        # Save and restore rather than SET LOCAL in a transaction of our own.
        # `sparql_sql_space_impl.create_transaction()` hands callers a connection
        # with a transaction already open, and asyncpg would nest ours as a
        # savepoint -- but SET LOCAL survives the RELEASE of a savepoint and
        # persists to the end of the OUTER transaction. That would silently
        # impose a 100ms lock timeout on the caller's remaining statements.
        # This form is correct whether or not a transaction is open.
        async with bounded_lock_wait(c, lock_timeout_ms):
            rows = await c.fetch(asql, *args)
        return [dict(r) for r in rows]

    if conn is not None:
        return await _run(conn)
    pool = get_pool()
    async with pool.acquire() as c:
        return await _run(c)


async def execute_scalar(sql, params=None, conn_params=None, conn=None):
    """Execute a SQL query and return a single scalar value."""
    asql, args = _pg_params_to_asyncpg(sql, params)
    if conn is not None:
        return await conn.fetchval(asql, *args)
    pool = get_pool()
    async with pool.acquire() as c:
        return await c.fetchval(asql, *args)


@asynccontextmanager
async def get_connection(params=None):
    """Async context manager — yield a connection from the implementation's pool."""
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn
