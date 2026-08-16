"""P3 validation: bounded rdf_stats prune preserves the reorder's input.

prune_stats_tables removes the pairs the join reorder never reads (row_count=1
singletons — the scale flood — and > MAX super-common pairs) and hard-caps the
rest to the lowest-N. Asserts (a) the flood/super-common are gone, (b) the
reorder loader's result is byte-identical before/after when the cap is above the
useful-pair count, and (c) the hard cap keeps exactly the lowest-row_count pairs
(the window the loader draws from).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
from vitalgraph.db.sparql_sql.sync_stats_tables import (
    prune_stats_tables, STATS_MIN_ROW_COUNT, STATS_MAX_ROW_COUNT)
from .conftest import skip_no_pg

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]


@pytest_asyncio.fixture(loop_scope="session")
async def stats_space(perf_pool):
    schema = SparqlSQLSchema()
    sid = f"perf_statsprune_{uuid.uuid4().hex[:8]}"
    async with perf_pool.acquire() as conn:
        for s in schema.create_space_tables_sql(sid):
            await conn.execute(s)
    yield sid
    async with perf_pool.acquire() as conn:
        for s in schema.drop_space_tables_sql(sid):
            await conn.execute(s)


async def _populate(conn, sid, singletons, useful_counts, supercommon):
    """Insert stats rows: N singletons, one row per row_count in useful_counts,
    and N super-common (> MAX) rows."""
    t = SparqlSQLSchema.get_table_names(sid)
    await conn.execute(f"TRUNCATE {t['rdf_stats']}")
    rows = [(uuid.uuid4(), uuid.uuid4(), 1) for _ in range(singletons)]
    rows += [(uuid.uuid4(), uuid.uuid4(), c) for c in useful_counts]
    rows += [(uuid.uuid4(), uuid.uuid4(), STATS_MAX_ROW_COUNT + 100)
             for _ in range(supercommon)]
    await conn.executemany(
        f"INSERT INTO {t['rdf_stats']} (predicate_uuid, object_uuid, row_count) "
        f"VALUES ($1, $2, $3)", rows)


async def _reorder_load(conn, sid):
    """The exact set the generator's join reorder loads (order matters)."""
    t = SparqlSQLSchema.get_table_names(sid)
    return [(r["predicate_uuid"], r["object_uuid"], r["row_count"])
            for r in await conn.fetch(
                f"SELECT predicate_uuid::text, object_uuid::text, row_count "
                f"FROM {t['rdf_stats']} "
                f"WHERE row_count >= {STATS_MIN_ROW_COUNT} "
                f"AND row_count <= {STATS_MAX_ROW_COUNT} "
                f"ORDER BY row_count ASC LIMIT 10000")]


async def test_prune_drops_flood_and_preserves_reorder_input(perf_pool, stats_space):
    sid = stats_space
    useful = list(range(2, 42))     # 40 useful pairs, distinct row_counts
    async with perf_pool.acquire() as conn:
        await _populate(conn, sid, singletons=500, useful_counts=useful, supercommon=15)
        t = SparqlSQLSchema.get_table_names(sid)
        assert await conn.fetchval(f"SELECT count(*) FROM {t['rdf_stats']}") == 555
        before = await _reorder_load(conn, sid)

        kept = await prune_stats_tables(conn, sid, keep_top_n=50_000)
        after = await _reorder_load(conn, sid)

    assert kept == 40                       # only the useful pairs survive
    assert before == after                  # reorder input byte-identical
    assert len(before) == 40


async def test_prune_hard_cap_keeps_lowest_row_counts(perf_pool, stats_space):
    sid = stats_space
    useful = list(range(2, 102))    # 100 useful pairs, row_counts 2..101
    async with perf_pool.acquire() as conn:
        await _populate(conn, sid, singletons=100, useful_counts=useful, supercommon=5)
        kept = await prune_stats_tables(conn, sid, keep_top_n=10)
        t = SparqlSQLSchema.get_table_names(sid)
        counts = sorted(r["row_count"] for r in
                        await conn.fetch(f"SELECT row_count FROM {t['rdf_stats']}"))
    assert kept == 10
    assert counts == list(range(2, 12))     # the 10 lowest-cardinality pairs


async def test_prune_returns_the_space_it_frees(perf_pool, stats_space):
    """The prune must SHRINK THE FILE, not just remove rows.

    This is the property that regressed silently and stayed that way. The prune
    used three DELETEs; a plain VACUUM returns those pages to the free space
    map and never to the OS, so the file sat at its high-water mark holding a
    few thousand rows. Measured across four loaded spaces before the fix:

        wordnet_frames         6,427 rows    375 MB
        sp_graph_synth_100k   10,687 rows    752 MB
        sp_graph_synth_10k     8,710 rows     99 MB
        prolog_spike_synth     8,454 rows     68 MB

    441 MB of 447 MB came back when it was rewritten as select-keepers,
    TRUNCATE, re-insert. Nothing in this file noticed, because every existing
    assertion here is about WHICH ROWS survive — and they all passed throughout.
    Row-set correctness and storage behaviour are independent properties and
    this suite only had the first.

    Asserted as a ratio against the pre-prune size rather than an absolute
    number of bytes, so it does not encode a page size or a row width.
    """
    sid = stats_space
    t = SparqlSQLSchema.get_table_names(sid)
    # Enough rows that the file is meaningfully larger than its fixed overhead;
    # ~120k singletons all fail step 1, so nearly everything is removed.
    async with perf_pool.acquire() as conn:
        await conn.execute(f"TRUNCATE {t['rdf_stats']}")
        await conn.execute(
            f"INSERT INTO {t['rdf_stats']} (predicate_uuid, object_uuid, row_count) "
            f"SELECT gen_random_uuid(), gen_random_uuid(), 1 "
            f"FROM generate_series(1, 120000)")
        await conn.execute(
            f"INSERT INTO {t['rdf_stats']} (predicate_uuid, object_uuid, row_count) "
            f"SELECT gen_random_uuid(), gen_random_uuid(), g "
            f"FROM generate_series(2, 501) g")
        before_rows = await conn.fetchval(f"SELECT count(*) FROM {t['rdf_stats']}")
        before_size = await conn.fetchval(
            f"SELECT pg_total_relation_size('{t['rdf_stats']}')")

        kept = await prune_stats_tables(conn, sid)
        after_size = await conn.fetchval(
            f"SELECT pg_total_relation_size('{t['rdf_stats']}')")

    assert before_rows == 120_500
    assert kept == 500, f"expected the 500 useful pairs, kept {kept}"
    # >99% of rows went; the file must follow. A DELETE-based prune leaves this
    # at ~1.0 and that is exactly the regression being guarded.
    assert after_size < before_size * 0.25, (
        f"pruned {before_rows:,} rows to {kept:,} but the table went "
        f"{before_size/1024/1024:.1f} MB -> {after_size/1024/1024:.1f} MB "
        f"({after_size/before_size:.2f}x). The rows are gone and the pages are "
        f"not — the prune is deleting rather than rewriting.")
