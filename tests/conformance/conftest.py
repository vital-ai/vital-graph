"""Conformance test configuration.

Provides fixtures and markers for DAWG/ARQ SPARQL conformance tests.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Add vitalgraph_sparql_sql_dev to import path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEV_PKG = _PROJECT_ROOT / "vitalgraph_sparql_sql_dev"
if str(_DEV_PKG) not in sys.path:
    sys.path.insert(0, str(_DEV_PKG))


# ---------------------------------------------------------------------------
# Infrastructure gate
# ---------------------------------------------------------------------------
#
# ONE probe, because there were three, and they disagreed. `test_dawg_sql_v2`'s
# said "Check if DB + sidecar are available" and only ever checked the sidecar;
# all three reported "localhost:7070" in the skip reason while reading 7071.
#
# WHY THIS CAN FAIL RATHER THAN SKIP. A skip is right on a laptop with no stack
# and wrong in CI, where the stack is the point of the job — an unreachable
# sidecar there means the suite silently measures nothing and the job passes.
# That is the corpus problem again: absence and success look identical. Set
# `VG_REQUIRE_INFRA=1` (the e2e workflow does) and a missing dependency is a
# hard failure naming what was unreachable.

SIDECAR_URL = os.environ.get("VG_TEST_SIDECAR_URL", "http://localhost:7071")


def _sidecar_reason() -> str | None:
    """None when reachable, else why not."""
    import urllib.error
    import urllib.request

    url = f"{SIDECAR_URL}/v1/sparql/compile"
    try:
        req = urllib.request.Request(
            url,
            data=b'{"sparql":"SELECT ?s WHERE { ?s ?p ?o } LIMIT 1"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                return f"sidecar at {url} returned HTTP {resp.status}"
            return None
    except (urllib.error.URLError, OSError) as exc:
        return f"sidecar at {url} unreachable: {exc}"


def _pg_reason() -> str | None:
    import asyncio

    try:
        import asyncpg

        from devtools.target import describe_target, get_connection_params, pg_kwargs
    except ImportError as exc:            # pragma: no cover - dependency missing
        return f"cannot import the postgres client: {exc}"

    async def _try():
        conn = await asyncpg.connect(**pg_kwargs())
        await conn.close()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_try())
        return None
    except Exception as exc:
        return f"postgres at {describe_target(get_connection_params())} unreachable: {exc}"
    finally:
        loop.close()


_REASON_CACHE: dict = {}


def _missing(need_pg: bool) -> str | None:
    if need_pg not in _REASON_CACHE:
        reason = _sidecar_reason()
        if reason is None and need_pg:
            reason = _pg_reason()
        _REASON_CACHE[need_pg] = reason
    return _REASON_CACHE[need_pg]


@pytest.fixture
def dawg_infrastructure(request):
    """Skip locally, FAIL in CI, when the stack this suite needs is missing.

    A module opts in with `DAWG_NEEDS_PG = True`; the sidecar is always required.
    """
    need_pg = getattr(request.module, "DAWG_NEEDS_PG", False)
    reason = _missing(need_pg)
    if reason is None:
        return
    if os.environ.get("VG_REQUIRE_INFRA", "").lower() in ("1", "true", "yes"):
        pytest.fail(
            f"VG_REQUIRE_INFRA is set, so this suite must run: {reason}. "
            f"Skipping here would report success for a suite that measured "
            f"nothing.",
            pytrace=False,
        )
    pytest.skip(reason)


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
