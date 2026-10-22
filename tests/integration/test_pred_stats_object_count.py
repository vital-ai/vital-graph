"""Integration: `rdf_pred_stats.object_count`, distinct objects per predicate.

`issues/293`, stage 1 of its general solution. `row_count / object_count` is a
predicate's mean subjects per object: what a probe BY OBJECT returns, and the
number PostgreSQL could not see when it priced a `hasKGGraphURI` probe at ~10
rows that returned ~1,000.

Pinned here: the recompute writes the EXACT distinct count; the generator loads
it; and a space created before the column existed keeps every other statistic
(the column is read in its own query, so its absence cannot cost the rest).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from rdflib import Literal, URIRef

from .conftest import skip_no_infra, TEST_SPACE_PREFIX
from vitalgraph.db.sparql_sql.space_names import space_prefix

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

GRAPH = URIRef("urn:objcount:g")
GROUPED = URIRef("urn:objcount:inGraph")       # 5 objects x 12 subjects each
VALUE = URIRef("urn:objcount:value")           # 60 subjects, 4 distinct values


@pytest_asyncio.fixture(loop_scope="session")
async def counted_space(make_space, space_impl, pg_conn):
    from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables
    sid = await make_space(f"{TEST_SPACE_PREFIX}objcnt_{uuid.uuid4().hex[:7]}")
    quads = []
    for i in range(60):
        s = URIRef(f"urn:objcount:s{i}")
        quads += [(s, GROUPED, URIRef(f"urn:objcount:group{i % 5}"), GRAPH),
                  (s, VALUE, Literal(f"v{i % 4}"), GRAPH)]
    await space_impl.add_rdf_quads_batch(sid, quads)
    await recompute_stats_tables(pg_conn, sid)
    return sid


async def _uuid(conn, sid, text):
    return await conn.fetchval(
        f"SELECT term_uuid FROM {space_prefix(sid)}_term WHERE term_text = $1", text)


async def test_the_recompute_writes_exact_distinct_objects(counted_space, pg_conn):
    t = f"{space_prefix(counted_space)}_rdf_pred_stats"
    rows = {r["predicate_uuid"]: (r["row_count"], r["object_count"])
            for r in await pg_conn.fetch(f"SELECT * FROM {t}")}
    assert rows[await _uuid(pg_conn, counted_space, str(GROUPED))] == (60, 5)
    assert rows[await _uuid(pg_conn, counted_space, str(VALUE))] == (60, 4)
    assert all(oc is not None for _, oc in rows.values())


async def test_the_generator_loads_the_mean_fanout(counted_space, pg_conn):
    from vitalgraph.db.sparql_sql import generator as G
    from vitalgraph.db.sparql_sql.ir import AliasGenerator
    from vitalgraph.db.sparql_sql.slot_group_cte import mean_fanout
    G.invalidate_stats_cache(counted_space)
    a = AliasGenerator()
    await G._load_quad_stats(a, counted_space, conn=pg_conn)
    p = str(await _uuid(pg_conn, counted_space, str(GROUPED)))
    assert a.pred_object_counts[p] == 5
    assert mean_fanout(a.quad_stats, p, a.pred_stats, a.pred_object_counts) == 12


async def test_a_space_without_the_column_keeps_its_other_stats(counted_space, pg_pool):
    """Simulated inside a rolled-back transaction: the column dropped, as on a
    space created before the migration."""
    from vitalgraph.db.sparql_sql import generator as G
    from vitalgraph.db.sparql_sql.ir import AliasGenerator
    from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables
    t = f"{space_prefix(counted_space)}_rdf_pred_stats"
    async with pg_pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            await conn.execute(f"ALTER TABLE {t} DROP COLUMN object_count")
            await recompute_stats_tables(conn, counted_space)   # the old path
            G.invalidate_stats_cache(counted_space)
            a = AliasGenerator()
            await G._load_quad_stats(a, counted_space, conn=conn)
            assert a.pred_stats and a.quad_stats, "the other stats must survive"
            assert a.pred_object_counts == {}
        finally:
            await tx.rollback()
            G.invalidate_stats_cache(counted_space)
