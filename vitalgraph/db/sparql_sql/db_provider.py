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

async def execute_query(sql, params=None, conn_params=None, conn=None):
    """Execute a SQL query and return rows as list of dicts.

    If *conn* is provided (an asyncpg connection), reuses it.
    Otherwise acquires from the implementation's pool.
    """
    asql, args = _pg_params_to_asyncpg(sql, params)
    if conn is not None:
        rows = await conn.fetch(asql, *args)
        return [dict(r) for r in rows]
    pool = get_pool()
    async with pool.acquire() as c:
        rows = await c.fetch(asql, *args)
        return [dict(r) for r in rows]


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
