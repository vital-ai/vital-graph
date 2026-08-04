"""Conformance test configuration.

Provides fixtures and markers for DAWG/ARQ SPARQL conformance tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add vitalgraph_sparql_sql_dev to import path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEV_PKG = _PROJECT_ROOT / "vitalgraph_sparql_sql_dev"
if str(_DEV_PKG) not in sys.path:
    sys.path.insert(0, str(_DEV_PKG))


@pytest.fixture(scope="session")
def dawg_loop():
    """One event loop for every DAWG SQL suite in the session.

    Must be session-scoped and shared: ``vitalgraph_sparql_sql_dev.db``
    memoizes a module-level asyncpg pool, and an asyncpg pool is bound to the
    loop that created it. A per-module loop makes the second module fail with
    "got Future attached to a different loop".
    """
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def dawg_conn(dawg_loop):
    """asyncpg connection with the ``dawg_test`` space provisioned.

    The space is created explicitly here — it is the conformance suites' own
    scratch space — and left in place afterwards. Per-test isolation comes from
    the runners, which truncate and reload it for each case.
    """
    from vitalgraph_sparql_sql_dev import db as devdb
    from vitalgraph_sparql_sql_dev.dawg_test_impl.dawg_space_manager import (
        SPACE_ID, create_space,
    )
    from vitalgraph.db.sparql_sql import db_provider

    async def _setup():
        if not db_provider.is_configured():
            from vitalgraph_sparql_sql_dev.db import DevDbImpl
            impl = DevDbImpl()
            await impl.connect()
            db_provider.configure(impl)
        pool = await devdb.get_pool()
        conn = await pool.acquire()
        await create_space(conn, SPACE_ID)
        return pool, conn

    pool, conn = dawg_loop.run_until_complete(_setup())
    yield conn
    dawg_loop.run_until_complete(pool.release(conn))


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "dawg: DAWG SPARQL 1.1 conformance test"
    )
    config.addinivalue_line(
        "markers", "jena_arq: Apache Jena ARQ test suite"
    )
    config.addinivalue_line(
        "markers", "sql_v2: Requires PostgreSQL + Jena sidecar"
    )
