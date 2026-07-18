"""Integration: the fused DELETE ... RETURNING delete path keeps rdf_stats correct.

delete_entity_graph_bulk now decrements stats from the rows it deletes (via
DELETE ... RETURNING) instead of a separate read-before-delete scan (100x #10).
Guard that the incremental stats after a delete match a full resync (ignoring
the row_count=0 rows a resync prunes — a pre-existing cleanup gap, not this path).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from rdflib import URIRef, Literal

from .conftest import skip_no_infra, TEST_SPACE_PREFIX

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

HGU = "http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI"


@pytest_asyncio.fixture(loop_scope="session")
async def del_space(space_impl):
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    sid = f"{TEST_SPACE_PREFIX}delstats_{uuid.uuid4().hex[:8]}"
    async with space_impl.db_impl.connection_pool.acquire() as conn:
        await SparqlSQLSchema.create_space(conn, sid)
    yield sid
    async with space_impl.db_impl.connection_pool.acquire() as conn:
        await SparqlSQLSchema.drop_space(conn, sid)


async def _stats(conn, sid):
    return {r["k"]: r["row_count"] for r in await conn.fetch(
        f"SELECT predicate_uuid::text||'|'||object_uuid::text AS k, row_count "
        f"FROM {sid}_rdf_stats")}


async def test_fused_delete_keeps_stats_correct(space_impl, del_space):
    from vitalgraph.db.sparql_sql.sync_stats_tables import resync_stats_tables

    sid, g, e = del_space, "urn:g", "urn:e1"
    gu = URIRef(g)
    quads = []
    for s in ("urn:s1", "urn:s2"):               # entity-graph subjects
        quads += [(URIRef(s), URIRef(HGU), URIRef(e), gu),
                  (URIRef(s), URIRef("urn:p1"), URIRef("urn:oShared"), gu),
                  (URIRef(s), URIRef("urn:p2"), Literal("v"), gu)]
    quads += [(URIRef("urn:sX"), URIRef("urn:p1"), URIRef("urn:oShared"), gu),
              (URIRef("urn:sX"), URIRef("urn:pX"), URIRef("urn:oX"), gu)]  # unrelated
    await space_impl.add_rdf_quads_batch_bulk(sid, quads)

    deleted = await space_impl.delete_entity_graph_bulk(sid, g, e)
    assert deleted == 6                          # s1+s2 × 3 quads

    async with space_impl.db_impl.connection_pool.acquire() as conn:
        incr_nonzero = {k: v for k, v in (await _stats(conn, sid)).items() if v > 0}
        await resync_stats_tables(conn, sid)
        resynced = await _stats(conn, sid)

    # After deleting s1/s2, only sX's two (pred,obj) pairs remain, each count 1.
    assert incr_nonzero == resynced == {
        k: 1 for k in resynced}, (incr_nonzero, resynced)
    assert len(resynced) == 2
