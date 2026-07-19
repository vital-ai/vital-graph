"""Integration test fixtures — requires PostgreSQL + Jena sidecar.

Provides:
- ``pg_conn``: raw asyncpg connection to the test database
- ``test_space``: auto-created/destroyed ephemeral space for test isolation
- ``sparql_execute``: helper to run SPARQL SELECT end-to-end and return bindings
- ``sparql_update``: helper to run SPARQL UPDATE end-to-end

Skip conditions:
- All tests auto-skip if PostgreSQL or the sidecar are unreachable.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict, List, Optional

import pytest
import pytest_asyncio
import asyncpg
import httpx


# ---------------------------------------------------------------------------
# Environment / configuration
# ---------------------------------------------------------------------------

PG_HOST = os.environ.get("VG_TEST_PG_HOST", "localhost")
PG_PORT = int(os.environ.get("VG_TEST_PG_PORT", "5432"))
PG_DATABASE = os.environ.get("VG_TEST_PG_DATABASE", "sparql_sql_graph")
PG_USER = os.environ.get("VG_TEST_PG_USER", "postgres")
PG_PASSWORD = os.environ.get("VG_TEST_PG_PASSWORD", "")

SIDECAR_URL = os.environ.get("VG_TEST_SIDECAR_URL", "http://localhost:7070")


# ---------------------------------------------------------------------------
# Infrastructure availability checks
# ---------------------------------------------------------------------------

def _check_pg() -> bool:
    """Return True if PostgreSQL is reachable."""
    try:
        loop = asyncio.new_event_loop()
        conn = loop.run_until_complete(
            asyncpg.connect(
                host=PG_HOST, port=PG_PORT,
                database=PG_DATABASE, user=PG_USER, password=PG_PASSWORD,
            )
        )
        loop.run_until_complete(conn.close())
        loop.close()
        return True
    except Exception:
        return False


def _check_sidecar() -> bool:
    """Return True if Jena sidecar responds to compile requests."""
    import urllib.request
    try:
        req = urllib.request.Request(
            f"{SIDECAR_URL}/v1/sparql/compile",
            data=b'{"sparql":"SELECT ?s WHERE { ?s ?p ?o } LIMIT 1"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


HAS_PG = _check_pg()
HAS_SIDECAR = _check_sidecar()

pytestmark = pytest.mark.integration

skip_no_infra = pytest.mark.skipif(
    not (HAS_PG and HAS_SIDECAR),
    reason="Requires PostgreSQL + Jena sidecar",
)



# ---------------------------------------------------------------------------
# Database connection fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def pg_pool():
    """Session-scoped asyncpg connection pool."""
    pool = await asyncpg.create_pool(
        host=PG_HOST, port=PG_PORT,
        database=PG_DATABASE, user=PG_USER, password=PG_PASSWORD,
        min_size=2, max_size=5,
    )
    yield pool
    await pool.close()


@pytest_asyncio.fixture(loop_scope="session")
async def pg_conn(pg_pool):
    """Per-test asyncpg connection (auto-released)."""
    async with pg_pool.acquire() as conn:
        yield conn


# ---------------------------------------------------------------------------
# Test space fixture — creates an isolated space per test module
# ---------------------------------------------------------------------------

# System/global spaces that must NEVER be dropped by tests:
#   sp_kg_types — centralized KG type definitions used by all spaces
#   dawg_test   — shared conformance test data
PROTECTED_SPACES = frozenset({"sp_kg_types", "dawg_test"})

# All integration test spaces use this prefix for easy identification/cleanup.
TEST_SPACE_PREFIX = "inttest_"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def space_manager(space_impl):
    """SpaceManager over the test backend — the ONLY sanctioned way to create a
    space in tests. Spaces are explicitly created/managed via the space table;
    never call SparqlSQLSchema.create_space directly (it makes per-space tables
    but no `space` catalog row, so quad inserts hit graph_space_id_fkey)."""
    from vitalgraph.space.space_manager import SpaceManager
    return SpaceManager(db_impl=getattr(space_impl, "db_impl", None),
                        space_backend=space_impl)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def make_space(space_manager):
    """Factory: create a space via the space manager (catalog row + tables),
    dropped at session end. Session-scoped so fixtures of any scope can use it;
    spaces are uniquely named so tests never collide. Returns an async
    callable -> space_id."""
    created = []

    async def _make(space_id: str = None, partition_quads: int = 0) -> str:
        sid = space_id or f"{TEST_SPACE_PREFIX}{uuid.uuid4().hex[:12]}"
        ok = await space_manager.create_space_with_tables(
            sid, sid, partition_quads=partition_quads)
        assert ok, f"space manager failed to create {sid}"
        created.append(sid)
        return sid

    yield _make

    for sid in created:
        try:
            await space_manager.delete_space_with_tables(sid)
        except Exception:
            pass


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def test_space(space_manager):
    """Create an ephemeral test space via the space manager, yield its id, drop it.

    Uses prefix 'inttest_' to distinguish from production/system spaces.
    """
    space_id = f"{TEST_SPACE_PREFIX}{uuid.uuid4().hex[:12]}"
    await space_manager.create_space_with_tables(space_id, space_id)
    yield space_id
    try:
        await space_manager.delete_space_with_tables(space_id)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# SparqlSQLSpaceImpl + BackendAdapter fixture (for KG CRUD tests)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def space_impl():
    """Session-scoped SparqlSQLSpaceImpl connected to the test database."""
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl

    pg_config = {
        "host": PG_HOST,
        "port": PG_PORT,
        "database": PG_DATABASE,
        "username": PG_USER,
        "password": PG_PASSWORD,
        "min_pool_size": 2,
        "max_pool_size": 5,
    }
    sidecar_config = {"url": SIDECAR_URL}

    impl = SparqlSQLSpaceImpl(
        postgresql_config=pg_config,
        sidecar_config=sidecar_config,
    )
    ok = await impl.connect()
    assert ok, "SparqlSQLSpaceImpl failed to connect"
    yield impl
    await impl.disconnect()


@pytest.fixture
def backend_adapter(space_impl):
    """Per-test SparqlSQLBackendAdapter wrapping the session space_impl."""
    from vitalgraph.kg_impl.kg_backend_utils import create_backend_adapter
    return create_backend_adapter(space_impl)


# ---------------------------------------------------------------------------
# SPARQL execution helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def sparql_execute(pg_pool):  # noqa: F811
    """Return an async callable: sparql_execute(sparql, space_id) → list[dict].

    Returns SPARQL JSON-style bindings.
    """

    async def _execute(sparql: str, space_id: str) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(base_url=SIDECAR_URL, timeout=10.0) as client:
            resp = await client.post(
                "/v1/sparql/compile",
                json={"sparql": sparql},
            )
            resp.raise_for_status()
            raw = resp.json()

        from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
        from vitalgraph.db.sparql_sql.generator import generate_sql

        cr = map_compile_response(raw)
        if not cr.ok:
            raise RuntimeError(f"SPARQL compile error: {cr.error}")

        async with pg_pool.acquire() as conn:
            gen = await generate_sql(cr, space_id, conn=conn)
            if not gen.ok:
                raise RuntimeError(f"SQL generation error: {gen.error}")

            rows = await conn.fetch(gen.sql)
            result_rows = [dict(r) for r in rows]

        # Convert to SPARQL bindings format
        from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
        bindings = SparqlSQLSpaceImpl._rows_to_sparql_bindings(
            result_rows, gen.var_map or {}
        )
        return bindings

    return _execute


@pytest.fixture
def sparql_update(pg_pool):  # noqa: F811
    """Return an async callable: sparql_update(sparql, space_id) → None.

    Executes a SPARQL UPDATE (INSERT DATA, DELETE DATA, etc.)
    """

    async def _update(sparql: str, space_id: str) -> None:
        async with httpx.AsyncClient(base_url=SIDECAR_URL, timeout=10.0) as client:
            resp = await client.post(
                "/v1/sparql/compile",
                json={"sparql": sparql},
            )
            resp.raise_for_status()
            raw = resp.json()

        from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
        from vitalgraph.db.sparql_sql.generator import generate_sql

        cr = map_compile_response(raw)
        if not cr.ok:
            raise RuntimeError(f"SPARQL compile error: {cr.error}")

        async with pg_pool.acquire() as conn:
            gen = await generate_sql(cr, space_id, conn=conn)
            if not gen.ok:
                raise RuntimeError(f"SQL generation error: {gen.error}")
            if gen.sql:
                # Updates may contain multiple statements separated by ;
                statements = [s.strip() for s in gen.sql.split(";") if s.strip()]
                async with conn.transaction():
                    for stmt in statements:
                        await conn.execute(stmt)

    return _update


@pytest.fixture
def sparql_query_sql(pg_pool):  # noqa: F811
    """Return an async callable: sparql_query_sql(sparql, space_id) → str.

    Returns the generated SQL without executing it. Useful for debugging.
    """

    async def _sql(sparql: str, space_id: str) -> str:
        async with httpx.AsyncClient(base_url=SIDECAR_URL, timeout=10.0) as client:
            resp = await client.post(
                "/v1/sparql/compile",
                json={"sparql": sparql},
            )
            resp.raise_for_status()
            raw = resp.json()

        from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
        from vitalgraph.db.sparql_sql.generator import generate_sql

        cr = map_compile_response(raw)
        if not cr.ok:
            raise RuntimeError(f"SPARQL compile error: {cr.error}")

        async with pg_pool.acquire() as conn:
            gen = await generate_sql(cr, space_id, conn=conn)
            if not gen.ok:
                raise RuntimeError(f"SQL generation error: {gen.error}")
            return gen.sql

    return _sql
