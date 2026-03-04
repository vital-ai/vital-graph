"""
Async and sync PostgreSQL connection helpers for the SPARQL-to-SQL pipeline.

Uses psycopg (psycopg3) to match the existing VitalGraph PostgreSQL backend.
Connection parameters are read from environment variables or passed directly.
"""

import os
import logging
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

# Module-level connection pool (lazy init)
_pool = None
_pool_conninfo = None


def get_connection_params() -> Dict[str, Any]:
    """
    Build connection parameters from environment variables.
    Falls back to local development defaults matching .env LOCAL_ config.
    """
    return {
        "host": os.environ.get("PGHOST", os.environ.get("LOCAL_DB_HOST", "localhost")),
        "port": int(os.environ.get("PGPORT", os.environ.get("LOCAL_DB_PORT", "5432"))),
        "dbname": os.environ.get("PGDATABASE", os.environ.get("LOCAL_DB_NAME", "fuseki_sql_graph")),
        "user": os.environ.get("PGUSER", os.environ.get("LOCAL_DB_USERNAME", "postgres")),
        "password": os.environ.get("PGPASSWORD", os.environ.get("LOCAL_DB_PASSWORD", "")),
    }


def get_connection_string(params: Optional[Dict[str, Any]] = None) -> str:
    """Build a psycopg connection string from parameters."""
    p = params or get_connection_params()
    parts = [f"host={p['host']}", f"port={p['port']}", f"dbname={p['dbname']}", f"user={p['user']}"]
    if p.get("password"):
        parts.append(f"password={p['password']}")
    return " ".join(parts)


def _get_pool(params: Optional[Dict[str, Any]] = None):
    """Lazily initialize and return the module-level connection pool."""
    global _pool, _pool_conninfo
    conninfo = get_connection_string(params)
    if _pool is None or _pool_conninfo != conninfo:
        if _pool is not None:
            _pool.close()
        from psycopg_pool import ConnectionPool
        _pool_conninfo = conninfo
        _pool = ConnectionPool(
            conninfo,
            min_size=2,
            max_size=8,
            kwargs={"row_factory": dict_row},
        )
    return _pool


@contextmanager
def get_connection(params: Optional[Dict[str, Any]] = None, row_factory=None):
    """
    Sync context manager for a psycopg connection from the pool.

    Usage:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                print(cur.fetchone())
    """
    pool = _get_pool(params)
    with pool.connection() as conn:
        if row_factory:
            conn.row_factory = row_factory
        yield conn


def execute_query(sql: str, params: Optional[tuple] = None,
                  conn_params: Optional[Dict[str, Any]] = None,
                  conn=None) -> List[Dict[str, Any]]:
    """
    Execute a SQL query and return all rows as dicts.
    Convenience function for one-shot queries.

    If *conn* is provided, reuses that connection (no pool checkout).
    """
    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    with get_connection(conn_params) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def execute_scalar(sql: str, params: Optional[tuple] = None,
                   conn_params: Optional[Dict[str, Any]] = None):
    """Execute a SQL query and return a single scalar value."""
    with get_connection(conn_params) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            if row is None:
                return None
            # dict_row returns a dict; get first value
            return next(iter(row.values()))
