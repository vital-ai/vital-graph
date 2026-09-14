"""L2 bulk export/import benchmark: the COPY round-trip that restores a space.

`issues/192` lists bulk export as correctness-tested with zero bench cells.
`test_bulk_export` proves the round-trip is exact — identical row counts,
byte-exact quad_uuids, derived tables rebuilt — and nothing measured what it
COSTS. That matters because the import half is the restore path: how long a
space is unavailable after a failure is this number, and nobody has one.

BOTH HALVES, and the ratio between them. `export_space` runs its COPYs in one
REPEATABLE READ snapshot; `import_space` COPYs back and then RESYNCS the derived
tables, which is the expensive part and the half that has surprised this
repository repeatedly. Measuring export alone would report the cheap half and
call it the cost of a restore.

Ingest tier: it creates a space and writes into it.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
import uuid

import pytest
import pytest_asyncio

from .conftest import skip_no_pg

pytestmark = [pytest.mark.performance, pytest.mark.ingest_bench, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

# A loaded fixture with real derived tables, so the import's resync has work to
# do, and SMALL ENOUGH TO FINISH. `sp_graph_rel_10k` (2.9M quads) was tried
# first and the round-trip exceeded asyncpg's pool `command_timeout=60`, which
# fires in the DRIVER and surfaces as a bare CancelledError — the same
# cancellation that made the inline orphan cleanup clean nothing in
# `issues/079`. A bench that is cancelled measures nothing and says so
# confusingly, so the source is one that fits inside the budget.
#
# `sp_graph_skew_2k`: ~596k quads and ~39k edge rows, so the resync half still
# has real work rather than being a no-op.
SOURCE_SPACE = "sp_graph_skew_2k"

PG = dict(
    host=os.environ.get("VG_TEST_PG_HOST", "localhost"),
    port=int(os.environ.get("VG_TEST_PG_PORT", "5433")),
    database=os.environ.get("VG_TEST_PG_DATABASE", "sparql_sql_graph"),
    user=os.environ.get("VG_TEST_PG_USER", "postgres"),
    password=os.environ.get("VG_TEST_PG_PASSWORD", "testpass"),
)


@pytest_asyncio.fixture(loop_scope="session")
async def restore_target():
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
    from vitalgraph.space.space_manager import SpaceManager
    impl = SparqlSQLSpaceImpl(
        postgresql_config={"host": PG["host"], "port": PG["port"],
                           "database": PG["database"], "username": PG["user"],
                           "password": PG["password"],
                           "min_pool_size": 1, "max_pool_size": 4},
        sidecar_config={"url": os.environ.get("VG_TEST_SIDECAR_URL",
                                              "http://localhost:7071")})
    await impl.connect()
    mgr = SpaceManager(db_impl=getattr(impl, "db_impl", None), space_backend=impl)
    sid = f"perfimp_{uuid.uuid4().hex[:8]}"
    if not await mgr.create_space_with_tables(sid, sid):
        await impl.disconnect()
        pytest.skip(f"space manager failed to create {sid}")
    try:
        yield sid, impl
    finally:
        try:
            await mgr.delete_space_with_tables(sid)
        except Exception:
            pass
        await impl.disconnect()


@pytest.mark.bench("write.export.copy_round_trip")
async def test_export_import_round_trip(restore_target, perf_conn, perf_record):
    from vitalgraph.db.sparql_sql.bulk_export import export_space, import_space

    dst, impl = restore_target
    src_quads = await perf_conn.fetchval(
        f"SELECT count(*) FROM {SOURCE_SPACE}_rdf_quad")
    if not src_quads:
        pytest.skip(f"{SOURCE_SPACE} holds no quads, so a round-trip measures "
                    f"nothing")

    tmp = tempfile.mkdtemp(prefix="perf_export_")
    try:
        t0 = time.perf_counter()
        paths = await export_space(perf_conn, SOURCE_SPACE, tmp)
        export_s = time.perf_counter() - t0
        bytes_out = sum(os.path.getsize(p) for p in paths.values()
                        if os.path.exists(p))

        async with impl.db_impl._pool.acquire() as conn:
            t0 = time.perf_counter()
            counts = await import_space(conn, dst, paths)
            import_s = time.perf_counter() - t0
            restored = await conn.fetchval(f"SELECT count(*) FROM {dst}_rdf_quad")
            edges = await conn.fetchval(f"SELECT count(*) FROM {dst}_edge")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    assert restored == src_quads, (
        f"restored {restored:,} quads from a source of {src_quads:,} — the "
        f"timings below describe an incomplete restore")

    perf_record(
        kind="write", dataset=SOURCE_SPACE,
        metrics={
            "source_quads": src_quads,
            "export_s": round(export_s, 3),
            "export_quads_per_sec": round(src_quads / export_s) if export_s else 0,
            "export_bytes": bytes_out,
            "import_s": round(import_s, 3),
            "import_quads_per_sec": round(src_quads / import_s) if import_s else 0,
            # The restore is the half that matters operationally, and the resync
            # inside it is what makes the two differ.
            "import_over_export": round(import_s / export_s, 2) if export_s else 0,
            "edge_rows_rebuilt": edges,
        },
        notes="issues/192 — binary COPY export then import, including the "
              "derived-table resync the import performs")

    assert edges > 0, (
        f"the import restored {restored:,} quads but rebuilt no edge rows, so "
        f"the resync half — the expensive part this bench exists to measure — "
        f"did not run")
