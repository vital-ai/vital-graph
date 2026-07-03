"""Tier 4 API test fixtures.

Tests in this directory exercise the full VitalGraph REST API via the
VitalGraphClient.  They require a running VitalGraph server (typically
launched via docker-compose).  If the server is unreachable, tests fail.

Configuration is driven by environment variables:
    VITALGRAPH_CLIENT_ENVIRONMENT  — profile name (default: "local")
    LOCAL_CLIENT_SERVER_URL        — server URL  (default: http://localhost:8001)
    LOCAL_CLIENT_AUTH_USERNAME     — login user  (default: admin)
    LOCAL_CLIENT_AUTH_PASSWORD     — login pass  (default: admin)
"""

from __future__ import annotations

import os
import uuid
import pytest
import pytest_asyncio
import asyncpg

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SERVER_URL = os.getenv("LOCAL_CLIENT_SERVER_URL", "http://localhost:8001")

# Direct PostgreSQL access (for DB-level verification tests)
PG_HOST = os.getenv("VG_TEST_PG_HOST", "localhost")
PG_PORT = int(os.getenv("VG_TEST_PG_PORT", "5432"))
PG_DATABASE = os.getenv("VG_TEST_PG_DATABASE", "sparql_sql_graph")
PG_USER = os.getenv("VG_TEST_PG_USER", "postgres")
PG_PASSWORD = os.getenv("VG_TEST_PG_PASSWORD", "")

TEST_SPACE_PREFIX = "apitest_"

pytestmark = pytest.mark.api


# ---------------------------------------------------------------------------
# Client fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def vg_client():
    """Session-scoped authenticated VitalGraphClient.

    Opens a client connection (JWT login) against the running server and
    closes it at session teardown.
    """
    from vitalgraph.client.vitalgraph_client import VitalGraphClient

    client = VitalGraphClient()
    await client.open()
    yield client
    await client.close()


# ---------------------------------------------------------------------------
# Ephemeral test space + graph (module-scoped)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def test_space(vg_client):
    """Create an ephemeral space for the test module, delete at teardown."""
    from vitalgraph.model.spaces_model import Space

    space_id = f"{TEST_SPACE_PREFIX}{uuid.uuid4().hex[:8]}"

    # Clean up if pre-existing (from a crashed run)
    resp = await vg_client.spaces.list_spaces()
    if resp.is_success:
        existing = [s.space for s in resp.spaces]
        if space_id in existing:
            await vg_client.spaces.delete_space(space_id)

    space = Space(
        space=space_id,
        space_name=f"API Test {space_id}",
        space_description="Ephemeral Tier 4 API test space",
    )
    cr = await vg_client.spaces.create_space(space)
    assert cr.is_success, f"Failed to create test space: {cr.error_message}"

    yield space_id

    await vg_client.spaces.delete_space(space_id)


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def test_graph(vg_client, test_space):
    """Create a named graph in the test space."""
    graph_id = f"urn:apitest:{uuid.uuid4().hex[:8]}"
    await vg_client.graphs.create_graph(test_space, graph_id)
    yield graph_id


# ---------------------------------------------------------------------------
# Direct PostgreSQL connection (for DB-level verification)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def pg_conn():
    """Direct asyncpg connection for verifying database state.

    Skips the test module if PostgreSQL is unreachable.
    """
    try:
        conn = await asyncpg.connect(
            host=PG_HOST, port=PG_PORT,
            database=PG_DATABASE, user=PG_USER, password=PG_PASSWORD,
        )
    except Exception:
        pytest.skip("PostgreSQL not reachable for DB verification")
        return
    yield conn
    await conn.close()
