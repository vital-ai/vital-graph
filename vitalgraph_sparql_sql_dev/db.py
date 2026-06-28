"""
PostgreSQL connection helpers for the SPARQL-to-SQL pipeline.

All database access uses **asyncpg** — async only.

Connection parameters are read from environment variables or passed directly.
"""

import os
import logging
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

import asyncpg

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection parameters
# ---------------------------------------------------------------------------

def get_connection_params() -> Dict[str, Any]:
    """
    Build connection parameters from environment variables.
    Falls back to local development defaults matching .env LOCAL_ config.
    """
    return {
        "host": os.environ.get("PGHOST", os.environ.get("LOCAL_DB_HOST", "localhost")),
        "port": int(os.environ.get("PGPORT", os.environ.get("LOCAL_DB_PORT", "5432"))),
        "dbname": os.environ.get("PGDATABASE", os.environ.get("LOCAL_DB_NAME", "sparql_sql_graph")),
        "user": os.environ.get("PGUSER", os.environ.get("LOCAL_DB_USERNAME", "postgres")),
        "password": os.environ.get("PGPASSWORD", os.environ.get("LOCAL_DB_PASSWORD", "")),
    }


def get_connection_string(params: Optional[Dict[str, Any]] = None) -> str:
    """Build a DSN-style connection string (for logging / display only)."""
    p = params or get_connection_params()
    return f"host={p['host']} port={p['port']} dbname={p['dbname']} user={p['user']}"


def _asyncpg_connect_kwargs(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Convert our standard params dict to asyncpg keyword arguments."""
    p = params or get_connection_params()
    return {
        "host": p.get("host", "localhost"),
        "port": int(p.get("port", 5432)),
        "database": p.get("dbname", p.get("database", "fuseki_sql_graph")),
        "user": p.get("user", p.get("username", "postgres")),
        "password": p.get("password", ""),
    }


# ---------------------------------------------------------------------------
# asyncpg connection pool
# ---------------------------------------------------------------------------

_pool: Optional[asyncpg.Pool] = None
_pool_key: Optional[str] = None


async def get_pool(params: Optional[Dict[str, Any]] = None) -> asyncpg.Pool:
    """Lazily initialize and return the module-level asyncpg connection pool."""
    global _pool, _pool_key
    kw = _asyncpg_connect_kwargs(params)
    key = f"{kw['host']}:{kw['port']}/{kw['database']}/{kw['user']}"
    if _pool is None or _pool_key != key:
        if _pool is not None:
            await _pool.close()
        _pool_key = key
        _pool = await asyncpg.create_pool(
            min_size=2,
            max_size=8,
            **kw,
        )
    return _pool


def _pg_params_to_asyncpg(sql: str, params: Optional[tuple] = None):
    """Convert %s-style placeholders to $1, $2, ... for asyncpg.

    Returns (converted_sql, args_list).  If params is None, returns
    the original SQL and an empty list.
    """
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
# Async API
# ---------------------------------------------------------------------------

@asynccontextmanager
async def get_connection(params: Optional[Dict[str, Any]] = None):
    """
    Async context manager for an asyncpg connection from the pool.

    Usage:
        async with get_connection() as conn:
            rows = await conn.fetch("SELECT 1 AS val")
    """
    pool = await get_pool(params)
    async with pool.acquire() as conn:
        yield conn


async def execute_query(sql: str, params: Optional[tuple] = None,
                        conn_params: Optional[Dict[str, Any]] = None,
                        conn=None) -> List[Dict[str, Any]]:
    """
    Execute a SQL query and return all rows as dicts.

    If *conn* is provided (an asyncpg connection), reuses it.
    """
    asql, args = _pg_params_to_asyncpg(sql, params)
    if conn is not None:
        rows = await conn.fetch(asql, *args)
        return [dict(r) for r in rows]
    async with get_connection(conn_params) as c:
        rows = await c.fetch(asql, *args)
        return [dict(r) for r in rows]


async def execute_scalar(sql: str, params: Optional[tuple] = None,
                         conn_params: Optional[Dict[str, Any]] = None,
                         conn=None):
    """Execute a SQL query and return a single scalar value."""
    asql, args = _pg_params_to_asyncpg(sql, params)
    if conn is not None:
        return await conn.fetchval(asql, *args)
    async with get_connection(conn_params) as c:
        return await c.fetchval(asql, *args)


async def close_pool():
    """Close the connection pool. Call on shutdown."""
    global _pool, _pool_key
    if _pool is not None:
        await _pool.close()
        _pool = None
        _pool_key = None


# ---------------------------------------------------------------------------
# DbImplInterface implementation for dev/test use
# ---------------------------------------------------------------------------

from vitalgraph.db.db_inf import DbImplInterface


class DevDbImpl(DbImplInterface):
    """DbImplInterface backed by the module-level asyncpg pool.

    Used by the standalone dev/test package (DAWG tests, benchmarks).
    The main VitalGraph service uses its own DbImplInterface implementation
    (e.g. FusekiPostgreSQLDbImpl) instead.

    Usage:
        from vitalgraph_sparql_sql.db import DevDbImpl
        from vitalgraph_sparql_sql.sparql_sql import db_provider

        dev_impl = DevDbImpl()
        await dev_impl.connect()
        db_provider.configure(dev_impl)
    """

    def __init__(self, params=None):
        self.params = params
        self.connection_pool = None  # asyncpg.Pool — set during connect()
        self._connected = False

    async def connect(self) -> bool:
        self.connection_pool = await get_pool(self.params)
        self._connected = True
        return True

    async def disconnect(self) -> bool:
        await close_pool()
        self.connection_pool = None
        self._connected = False
        return True

    async def is_connected(self) -> bool:
        return self._connected and self.connection_pool is not None

    async def execute_query(self, query, params=None):
        return await execute_query(query, params=params)

    async def execute_update(self, query, params=None):
        asql, args = _pg_params_to_asyncpg(query, params)
        async with get_connection(self.params) as conn:
            await conn.execute(asql, *args)
            return True

    async def begin_transaction(self):
        conn = await self.connection_pool.acquire()
        txn = conn.transaction()
        await txn.start()
        return (conn, txn)

    async def commit_transaction(self, transaction):
        conn, txn = transaction
        await txn.commit()
        await self.connection_pool.release(conn)
        return True

    async def rollback_transaction(self, transaction):
        conn, txn = transaction
        await txn.rollback()
        await self.connection_pool.release(conn)
        return True

    def get_connection_info(self):
        p = self.params or get_connection_params()
        return {
            'type': 'dev_asyncpg',
            'host': p.get('host', 'localhost'),
            'port': p.get('port', 5432),
            'database': p.get('dbname', p.get('database', '')),
            'connected': self._connected,
        }

