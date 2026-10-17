"""The analytics job runs with the timeout it asks for, and counts predicates cheaply — issues/275.

`SET LOCAL statement_timeout = '120s'` on the job's autocommit connection was a
no-op: PostgreSQL warned and kept the instance default (60 s on production), so
every analytics query had half its budget, and on the 79.5M-quad main KG space
`COUNT(DISTINCT predicate_uuid)` — a scan of the whole `quad_po` index — failed
at ~59 s after every restart.

Checked here against a real database: the job's queries see the job's timeout
and the connection gets its own value back afterwards; and on a space above the
size guard the predicate count comes from `rdf_pred_stats` and equals the scan.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from rdflib import Literal, URIRef

from .conftest import skip_no_infra

from vitalgraph.process import analytics_job as A

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]


@pytest_asyncio.fixture(loop_scope="session")
async def seeded(test_space, space_impl):
    g = URIRef(f"urn:t275:{uuid.uuid4().hex[:8]}")
    quads = [(URIRef(f"urn:t275:s{i}"), URIRef(f"urn:t275:p{i % 7}"), Literal(f"v{i}"), g)
             for i in range(200)]
    await space_impl.add_rdf_quads_batch_bulk(test_space, quads)
    return test_space


async def test_the_job_queries_run_with_its_timeout_and_restore_it(
        seeded, monkeypatch):
    import asyncpg
    from .conftest import PG_DATABASE, PG_HOST, PG_PASSWORD, PG_PORT, PG_USER
    # ONE connection, so the connection the job used is the next one handed out
    # and its setting can be read after the job has given it back.
    pool = await asyncpg.create_pool(host=PG_HOST, port=PG_PORT, user=PG_USER,
                                     password=PG_PASSWORD, database=PG_DATABASE,
                                     min_size=1, max_size=1)
    seen = {}
    original = A.AnalyticsJob._compute_entity_analytics

    async def spy(self, conn, space_id, graph_ctx):
        seen["inside"] = await conn.fetchval("SHOW statement_timeout")
        return await original(self, conn, space_id, graph_ctx)

    monkeypatch.setattr(A.AnalyticsJob, "_compute_entity_analytics", spy)
    try:
        async with pool.acquire() as c:
            default = await c.fetchval("SHOW statement_timeout")
        await A.AnalyticsJob(pool)._compute_and_store(seeded)
        async with pool.acquire() as c:
            after = await c.fetchval("SHOW statement_timeout")
    finally:
        await pool.close()

    assert seen["inside"] == "2min", (
        f"the job's queries ran with statement_timeout={seen['inside']!r}, not "
        f"its 120 s — the setting did not apply")
    assert after == default, "the job left its timeout on a pooled connection"


async def test_a_large_space_counts_predicates_from_the_stats_table(
        seeded, pg_pool, monkeypatch):
    from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables
    async with pg_pool.acquire() as c:
        await recompute_stats_tables(c, seeded)
        exact = await c.fetchval(
            f"SELECT COUNT(DISTINCT predicate_uuid) FROM {seeded}_rdf_quad")
        job = A.AnalyticsJob(pg_pool)

        # Small as it is, treat the space as above the guard.
        monkeypatch.setattr(A, "_FRAME_ANALYTICS_MAX_QUADS", -2)  # reltuples is -1 before ANALYZE
        big = await job._compute_property_analytics(c, seeded, None)
        monkeypatch.setattr(A, "_FRAME_ANALYTICS_MAX_QUADS", 10**12)
        small = await job._compute_property_analytics(c, seeded, None)

    assert big["distinct_predicate_count_source"] == "rdf_pred_stats"
    assert big["distinct_predicate_count"] == exact
    assert small["distinct_predicate_count_source"] == "rdf_quad"
    assert small["distinct_predicate_count"] == exact
