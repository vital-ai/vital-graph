"""Fixtures for scaling/performance tests (L1/L2).

Connects to PostgreSQL via env vars — defaults to the host PG, but the
`scripts/run-perf-tests.sh` runner points these at the ephemeral vg-test
container DB (port 5433):

    VG_TEST_PG_HOST / VG_TEST_PG_PORT / VG_TEST_PG_DATABASE /
    VG_TEST_PG_USER / VG_TEST_PG_PASSWORD

Auto-skips if PostgreSQL is unreachable. Tests that need a specific pre-loaded
space (e.g. wordnet_frames) skip themselves via `require_space`.
"""

from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio
import asyncpg

PG_HOST = os.environ.get("VG_TEST_PG_HOST", "localhost")
PG_PORT = int(os.environ.get("VG_TEST_PG_PORT", "5432"))
PG_DATABASE = os.environ.get("VG_TEST_PG_DATABASE", "sparql_sql_graph")
PG_USER = os.environ.get("VG_TEST_PG_USER", "postgres")
PG_PASSWORD = os.environ.get("VG_TEST_PG_PASSWORD", "")

pytestmark = pytest.mark.performance


def _check_pg() -> bool:
    try:
        loop = asyncio.new_event_loop()
        conn = loop.run_until_complete(asyncpg.connect(
            host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
            user=PG_USER, password=PG_PASSWORD))
        loop.run_until_complete(conn.close())
        loop.close()
        return True
    except Exception:
        return False


HAS_PG = _check_pg()
skip_no_pg = pytest.mark.skipif(not HAS_PG, reason="Requires PostgreSQL")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def perf_pool():
    pool = await asyncpg.create_pool(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD, min_size=1, max_size=4)
    yield pool
    await pool.close()


@pytest_asyncio.fixture(loop_scope="session")
async def perf_conn(perf_pool):
    async with perf_pool.acquire() as conn:
        yield conn


async def space_exists(conn, space_id: str) -> bool:
    """True if the space's rdf_quad table exists (i.e. the space is loaded)."""
    return bool(await conn.fetchval(
        "SELECT 1 FROM pg_tables WHERE tablename = $1", f"{space_id}_rdf_quad"))
