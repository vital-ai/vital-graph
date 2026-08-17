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

from . import perf_record as perf_record_mod

PG_HOST = os.environ.get("VG_TEST_PG_HOST", "localhost")
# Defaults target the docker test stack (vg-test, port 5433), NOT the host
# cluster. issues/099: the fixture loaders default to 5433 and these
# defaulted to 5432, so fixtures were seeded into one cluster and read from
# the other — which held stale same-named spaces, so tests got plausible
# wrong answers instead of a connection error.
PG_PORT = int(os.environ.get("VG_TEST_PG_PORT", "5433"))
PG_DATABASE = os.environ.get("VG_TEST_PG_DATABASE", "sparql_sql_graph")
PG_USER = os.environ.get("VG_TEST_PG_USER", "postgres")
PG_PASSWORD = os.environ.get("VG_TEST_PG_PASSWORD", "testpass")

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

# ---------------------------------------------------------------------------
# API benches (kind="api") — REST latency against the running stack.
#
# Config comes from the same VG_TEST_* family as the PostgreSQL fixtures rather
# than the client's own LOCAL_CLIENT_* variables. One env set then drives the
# whole suite, and the ":8001 dev vs :8002 test" footgun — where a suite
# silently measures the wrong server — cannot happen here.
# ---------------------------------------------------------------------------

PERF_API_URL = os.environ.get("VG_TEST_API_URL", "http://localhost:8002")
PERF_API_USER = os.environ.get("VG_TEST_API_USER", "admin")
PERF_API_PASSWORD = os.environ.get("VG_TEST_API_PASSWORD", "admin")
# Distinct profile so these never collide with LOCAL_* in the project .env.
_API_PROFILE = "vgperf"


def _check_api() -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen(f"{PERF_API_URL}/health", timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


HAS_API = _check_api()
skip_no_api = pytest.mark.skipif(
    not HAS_API, reason=f"Requires the VitalGraph API at {PERF_API_URL}")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def perf_client():
    """Authenticated VitalGraphClient pointed at the stack under test.

    Session-scoped: login is not the thing being measured, and re-authenticating
    per bench would add a variable that has nothing to do with query cost.
    """
    from vitalgraph.client.vitalgraph_client import VitalGraphClient

    os.environ["VITALGRAPH_CLIENT_ENVIRONMENT"] = _API_PROFILE
    os.environ[f"{_API_PROFILE.upper()}_CLIENT_SERVER_URL"] = PERF_API_URL
    os.environ[f"{_API_PROFILE.upper()}_CLIENT_AUTH_USERNAME"] = PERF_API_USER
    os.environ[f"{_API_PROFILE.upper()}_CLIENT_AUTH_PASSWORD"] = PERF_API_PASSWORD

    client = VitalGraphClient()
    await client.open()
    try:
        yield client
    finally:
        try:
            await client.close()
        except Exception:
            pass


async def api_space_exists(client, space_id: str) -> bool:
    """True if `space_id` is present on the server (for require-dataset skips)."""
    try:
        resp = await client.spaces.list_spaces()
        return any(getattr(s, "space", getattr(s, "space_id", None)) == space_id
                   for s in (resp.spaces or []))
    except Exception:
        return False


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


# ---------------------------------------------------------------------------
# Result recording (see planning/planning_performance/
# performance_regression_tracking_plan.md). Inert unless VG_PERF_RECORD is set.
# ---------------------------------------------------------------------------

_RUN: "perf_record_mod.PerfRun | None" = None


def pytest_configure(config):
    global _RUN
    config.addinivalue_line(
        "markers", "bench(id): record this test's metrics under the given bench id")
    out = os.environ.get("VG_PERF_RECORD")
    if out:
        _RUN = perf_record_mod.PerfRun(out)


def pytest_sessionfinish(session, exitstatus):
    if _RUN is not None:
        _RUN.write()
        print(f"\n📊 perf run recorded → {_RUN.out_path}")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Record outcome for every @bench test — including skips.

    A bench that skipped is a coverage hole, not an implicit pass; the comparison
    tool fails when a bench present in the baseline is missing from the run.
    """
    outcome = yield
    if _RUN is None:
        return
    report = outcome.get_result()
    if report.when != "call" and not (report.when == "setup" and report.skipped):
        return
    bench_id = perf_record_mod.bench_id_for(item)
    if bench_id is None:
        return
    if report.skipped:
        reason = ""
        if isinstance(report.longrepr, tuple) and len(report.longrepr) == 3:
            reason = str(report.longrepr[2])
        _RUN.set_status(bench_id, "skipped", reason)
    elif report.failed:
        _RUN.set_status(bench_id, "failed", "assertion/error during call")
    elif report.passed:
        # `perf_record(...)` already set status="ok" plus metrics; if the test
        # passed without recording anything, flag it rather than invent a pass.
        rec = _RUN.records.get(bench_id)
        if rec is None or "metrics" not in rec:
            _RUN.set_status(bench_id, "unrecorded", "test passed but recorded no metrics")


@pytest_asyncio.fixture(loop_scope="session")
async def perf_record(request, perf_pool):
    """Record one measurement for the current @bench test.

    Call with a plan (metrics are derived via the harness extractors), explicit
    metrics, or both:

        perf_record(plan=plan, dataset="wordnet_frames")
        perf_record(metrics={"quads_per_sec": 41200}, kind="write")
    """
    if _RUN is not None and not _RUN.env["pg"]:
        async with perf_pool.acquire() as conn:
            _RUN.env["pg"] = await perf_record_mod.pg_stamp(conn)

    def _record(plan=None, metrics=None, *, bench_id=None, kind="query",
                dataset=None, notes=None, **extra):
        if _RUN is None:
            return
        bid = bench_id or perf_record_mod.bench_id_for(request.node)
        if bid is None:
            raise ValueError(
                f"{request.node.nodeid}: perf_record needs a @pytest.mark.bench(id) "
                f"marker or an explicit bench_id")
        merged = {}
        fields = {"kind": kind, "status": "ok"}
        if plan is not None:
            merged.update(perf_record_mod.metrics_from_plan(plan))
            fields["shape"] = perf_record_mod.shape_from_plan(plan)
        if metrics:
            merged.update(metrics)
        fields["metrics"] = merged
        if dataset is not None:
            fields["dataset"] = dataset
        if notes:
            fields["notes"] = notes
        fields.update(extra)
        _RUN.add(bid, **fields)

    return _record
