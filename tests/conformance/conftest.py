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
    if os.environ.get("VG_CONFORMANCE_PLANNER", "").lower() in ("1", "true", "yes"):
        _route_through_planner()


# ---------------------------------------------------------------------------
# VG_CONFORMANCE_PLANNER=1: the suite through the qtree PLANNER
# ---------------------------------------------------------------------------
#
# The planner's correctness had been checked only against our own dashboard and
# KG corpora. Run through it, the W3C suite found SELECT * answered with an EMPTY
# select list (rows, no bindings) on its second test. With this set, every query
# the SQL-v2 tests generate goes through `generate_sql(..., planner_ext=True)`
# and runs with the planner's advice, as the executor runs it; the tests' own
# verdicts are the check. It needs a database with the `vg_planner` extension
# (the planner stack: VG_TEST_PG_PORT=5434, VG_TEST_SIDECAR_URL=:7072) and
# VG_PLANNER_FEATURES=qtree,...; queries the planner declines run as today.
# VG_CONFORMANCE_PLANNER_LOG=<file> also records, per generated query, whether
# the planner planned it and why not (the coverage matrix).

def _route_through_planner():
    import json
    from vitalgraph.db.sparql_sql import generator as G
    real = G.generate_sql
    log = os.environ.get("VG_CONFORMANCE_PLANNER_LOG")

    async def planned(compile_result, space_id, *a, **kw):
        kw["planner_ext"] = True
        g = await real(compile_result, space_id, *a, **kw)
        if log:
            d = g.plan_decisions or {}
            with open(log, "a") as f:
                f.write(json.dumps({"test": os.environ.get("PYTEST_CURRENT_TEST", ""),
                                    "source": g.plan_source,
                                    "declined": (d.get("declined") or {}).get("qtree_plan")}) + "\n")
        if g.ok and g.plan_advice:
            g.sql = g.plan_advice + "\n" + g.sql
        return g

    G.generate_sql = planned

    # ... and run a planner statement as the executor does: its written join order
    # IS the plan (`sparql_sql_space_impl._apply_join_order`). Without the pin
    # PostgreSQL re-orders it and the advice's per-step sizes match no join.
    from vitalgraph.db.sparql_sql import db_provider as dbp
    real_exec = dbp.execute_query

    async def execute(sql, params=None, conn_params=None, conn=None, **kw):
        if conn is not None and isinstance(sql, str) and sql.lstrip().startswith("/*vg:plan"):
            async with conn.transaction():
                await conn.execute("SET LOCAL join_collapse_limit = 1")
                return await real_exec(sql, params, conn_params, conn, **kw)
        return await real_exec(sql, params, conn_params, conn, **kw)

    dbp.execute_query = execute

    # ... and on a space that has STATISTICS, as a real one does. The harness loads
    # each test's data with neither rdf_stats nor ANALYZE, so every pattern without
    # a constant object was unpriced and declined (~170 queries): a coverage figure
    # about the harness, not the planner. Recomputed when a test loads new data.
    from vitalgraph_sparql_sql_dev.dawg_test_impl import dawg_sql_v2_executor as X
    from vitalgraph_sparql_sql_dev.dawg_test_impl import dawg_test_runner as TR
    real_run = X.execute_query_via_v2_pipeline
    seen = {"key": object()}

    async def run(sparql, *a, **kw):
        conn, space = kw.get("conn"), kw.get("space_id", "dawg_test")
        key = getattr(TR.run_single_test_sql_v2, "_cache_key", None)
        if conn is not None and key != seen["key"]:
            from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables
            from vitalgraph.db.sparql_sql.space_names import space_prefix
            from vitalgraph.db.sparql_sql.generator import invalidate_stats_cache
            from vitalgraph.db.sparql_sql import qcard
            await recompute_stats_tables(conn, space)
            await conn.execute(f"ANALYZE {space_prefix(space)}_rdf_quad")
            invalidate_stats_cache(space)
            qcard.invalidate(space)
            seen["key"] = key
        return await real_run(sparql, *a, **kw)

    X.execute_query_via_v2_pipeline = run
