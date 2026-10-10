"""Integration: a stats recompute must not block the planner's stats reads.

`issues/264`. Every one of production's 8 `pair stats lookup failed ... lock
timeout` lines (2026-10-01 to 10-10) landed 100-190 ms before a
`recompute_stats_tables` finished. `145` had already moved the aggregate out of
the locked section, leaving only "TRUNCATE, re-insert, commit" — but TRUNCATE
takes ACCESS EXCLUSIVE, which conflicts with a plain SELECT, so a planner read
fenced at `STATS_LOCK_TIMEOUT_MS` failed whenever it landed in that window and
the query was planned with every leaf unmeasured.

DETERMINISTIC, not a race. The recompute runs inside an outer transaction, so
its own transaction becomes a savepoint and every lock it took is still held
when it returns: the reader below lands squarely in the window every time.
Under TRUNCATE that read always fails; under DELETE it must succeed and see the
PRE-recompute contents. The outer transaction is rolled back.
"""

from __future__ import annotations

import uuid

import asyncpg
import pytest
import pytest_asyncio
from rdflib import Literal, URIRef

from .conftest import skip_no_infra, TEST_SPACE_PREFIX

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

GRAPH = URIRef("urn:stats_reader:g")
VITALTYPE = URIRef("http://vital.ai/ontology/vital-core#vitaltype")
KGENTITY = URIRef("http://vital.ai/ontology/haley-ai-kg#KGEntity")


@pytest_asyncio.fixture(loop_scope="session")
async def stats_space(make_space, space_impl, pg_conn):
    from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables
    sid = await make_space(f"{TEST_SPACE_PREFIX}statsrd_{uuid.uuid4().hex[:7]}")
    quads = []
    for i in range(60):
        s = URIRef(f"urn:stats_reader:s{i}")
        quads += [(s, VITALTYPE, KGENTITY, GRAPH),
                  (s, URIRef("urn:stats_reader:p"), Literal(f"v{i % 4}"), GRAPH)]
    await space_impl.add_rdf_quads_batch(sid, quads)
    await recompute_stats_tables(pg_conn, sid)
    return sid


async def test_a_fenced_stats_read_succeeds_during_a_recompute(
        stats_space, pg_pool):
    from vitalgraph.db.sparql_sql.db_provider import STATS_LOCK_TIMEOUT_MS
    from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables
    sid = stats_space

    async with pg_pool.acquire() as writer, pg_pool.acquire() as reader:
        before_stats = await reader.fetchval(f"SELECT count(*) FROM {sid}_rdf_stats")
        before_pred = await reader.fetchval(f"SELECT count(*) FROM {sid}_rdf_pred_stats")
        assert before_stats > 0 and before_pred > 0, (
            "the seed produced no stats rows; the read below would prove nothing")

        tx = writer.transaction()
        await tx.start()
        try:
            await recompute_stats_tables(writer, sid)   # locks still held here

            await reader.execute(f"SET lock_timeout = '{STATS_LOCK_TIMEOUT_MS}ms'")
            try:
                for table, before in ((f"{sid}_rdf_stats", before_stats),
                                      (f"{sid}_rdf_pred_stats", before_pred)):
                    try:
                        seen = await reader.fetchval(f"SELECT count(*) FROM {table}")
                    except asyncpg.LockNotAvailableError:
                        pytest.fail(
                            f"a {STATS_LOCK_TIMEOUT_MS} ms-fenced read of {table} "
                            f"timed out while a recompute was uncommitted. The "
                            f"planner falls back to planning with every leaf "
                            f"unmeasured when this happens (issues/264).")
                    assert seen == before, (
                        f"{table}: a reader saw {seen} rows mid-recompute, expected "
                        f"the committed {before} — the rewrite must be invisible "
                        f"until it commits")
            finally:
                await reader.execute("RESET lock_timeout")
        finally:
            await tx.rollback()
