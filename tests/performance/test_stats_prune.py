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
