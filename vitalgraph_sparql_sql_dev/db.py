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

# The stack every test suite targets. One set of variables decides it, and this
# module resolves them the same way `tests/{performance,integration,api}/
# conftest.py` do — so the conformance suites, which reach the database through
# here rather than through those conftests, cannot end up on a different stack
# from the rest.
#
# They did. This module defaulted to port 5432 (host cluster) while the fixture
# loaders and the other suites defaulted to 5433 (docker test stack), so the
# conformance suite ran against the dev database while its sidecar checks
# pointed at the test one. Nothing said so — the host cluster carries
# same-named spaces, so the queries answered (issues/099).
_STACK_DEFAULTS = {
    "host": "localhost",
    "port": "5433",          # docker test stack; 5432 is the host cluster
    "dbname": "sparql_sql_graph",
    "user": "postgres",
    "password": "testpass",
}


def get_connection_params() -> Dict[str, Any]:
    """Build connection parameters for the configured stack.

    Precedence, most specific first:

      1. ``VG_TEST_PG_*``   — the stack selector the test suites share
      2. ``PGHOST``/``PGPORT``/...  — standard libpq variables
      3. ``LOCAL_DB_*``     — the .env development profile
      4. the docker test stack

    An explicit setting always wins; the DEFAULT is what had to stop
    disagreeing, since with nothing set each caller silently chose its own.
    """
    def _pick(*names_then_key: str) -> str:
        *names, key = names_then_key
        for name in names:
            value = os.environ.get(name)
            if value is not None and value != "":
                return value
        return _STACK_DEFAULTS[key]

    return {
        "host": _pick("VG_TEST_PG_HOST", "VG_PG_HOST", "PGHOST",
                      "LOCAL_DB_HOST", "host"),
        "port": int(_pick("VG_TEST_PG_PORT", "VG_PG_PORT", "PGPORT",
                          "LOCAL_DB_PORT", "port")),
        "dbname": _pick("VG_TEST_PG_DATABASE", "VG_PG_DATABASE", "PGDATABASE",
                        "LOCAL_DB_NAME", "dbname"),
        "user": _pick("VG_TEST_PG_USER", "VG_PG_USER", "PGUSER",
                      "LOCAL_DB_USERNAME", "user"),
        # Password is the one field where an empty string is a legitimate value
        # (trust auth), so it is read separately rather than through the
        # non-empty filter above.
        "password": next(
            (os.environ[n] for n in ("VG_TEST_PG_PASSWORD", "VG_PG_PASSWORD",
                                     "PGPASSWORD", "LOCAL_DB_PASSWORD")
             if n in os.environ),
            _STACK_DEFAULTS["password"]),
    }


def pg_kwargs() -> Dict[str, Any]:
    """The resolved target as asyncpg keyword arguments.

    Same values as `get_connection_params`, with `dbname` spelled `database`,
    which is what `asyncpg.connect` and `create_pool` take. Scripts connect
    directly rather than through this module's pool, so they need the spelling
    asyncpg uses and should not each convert it.
    """
    p = get_connection_params()
    return {"host": p["host"], "port": p["port"], "database": p["dbname"],
            "user": p["user"], "password": p["password"]}


def add_pg_arguments(parser) -> None:
    """Give an ops script its `--host/--port/--database/--user/--password`.

    Every maintenance script had its own copy of these five defaults, and they
    did not agree: seventeen defaulted to port 5432 while everything that READS
    a fixture defaults to 5433, across TWO env families (`VG_TEST_PG_*` and
    `VG_PG_*`) that did not see each other's variables. Setting the one the
    tests use left half the scripts pointed at the other cluster.

    For a migration script that is worse than for a loader. A loader writes a
    fixture where nobody looks; a migration ALTERS whichever cluster it reached,
    and the host carries same-named spaces, so it succeeds and says so
    (`issues/055`, and `issues/099` one layer up).

    The default is the docker test stack, which is also the safe direction: an
    unset environment now reaches the disposable cluster rather than the one
    with real data on it.
    """
    d = get_connection_params()
    parser.add_argument("--host", default=d["host"])
    parser.add_argument("--port", type=int, default=d["port"])
    parser.add_argument("--database", default=d["dbname"])
    parser.add_argument("--user", default=d["user"])
    parser.add_argument("--password", default=d["password"])


def describe_target(args_or_params) -> str:
    """One line naming the cluster about to be touched, and which one it is.

    Printed rather than logged at debug: the whole failure mode here is a script
    doing the right thing to the wrong database and reporting success. Naming
    the target is what makes that visible without reading the code.
    """
    g = (args_or_params.get if isinstance(args_or_params, dict)
         else lambda k, _d=None: getattr(args_or_params, k, _d))
    host, port = g("host", "?"), int(g("port", 0) or 0)
    db = g("dbname", None) or g("database", "?")
    known = {5433: "docker test stack", 5432: "host cluster"}
    which = known.get(port, "unrecognised cluster")
    return f"{host}:{port}/{db} — {which}"


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
        "database": p.get("dbname", p.get("database", "sparql_sql_graph")),
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
        from vitalgraph_sparql_sql_dev.db import DevDbImpl
        from vitalgraph_sparql_sql_dev.sparql_sql import db_provider

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

