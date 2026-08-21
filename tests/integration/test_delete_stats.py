"""Integration: the fused DELETE ... RETURNING delete path keeps rdf_stats correct.

delete_entity_graph_bulk now decrements stats from the rows it deletes (via
DELETE ... RETURNING) instead of a separate read-before-delete scan (100x #10),
and sync_stats_after_delete prunes (pred,obj) rows that churn to empty. Guard
that the incremental rdf_stats after a delete converge exactly on a full resync
(no leftover row_count=0 rows).
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
VITALTYPE = "http://vital.ai/ontology/vital-core#vitaltype"
KG_ENTITY = "http://vital.ai/ontology/haley-ai-kg#KGEntity"
KG_FRAME = "http://vital.ai/ontology/haley-ai-kg#KGFrame"


@pytest_asyncio.fixture(loop_scope="session")
async def del_space(make_space):
    return await make_space(f"{TEST_SPACE_PREFIX}delstats_{uuid.uuid4().hex[:8]}")


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
        incremental = await _stats(conn, sid)        # includes any leftover 0-rows
        await resync_stats_tables(conn, sid)
        resynced = await _stats(conn, sid)

    # After deleting s1/s2, only sX's two (pred,obj) pairs remain, each count 1.
    # The delete path prunes zeroed rows, so it converges exactly on a resync.
    assert incremental == resynced == {k: 1 for k in resynced}, (incremental, resynced)
    assert len(resynced) == 2


async def test_delete_removes_an_entity_that_lacks_its_own_self_link(space_impl, del_space):
    """The entity goes even when nothing names it a member of its own graph.

    Membership is read from hasKGGraphURI, one mutable predicate. An entity is
    in that snapshot only if it carries a self-link, and issues/091 found 619
    entities across 12 spaces that did not. Deleting one took every member and
    left the typed root behind — an entity whose graph reads as empty.
    """
    sid, g, e = del_space, "urn:g2", "urn:e2"
    gu = URIRef(g)
    quads = [(URIRef(e), URIRef(VITALTYPE), URIRef(KG_ENTITY), gu),   # typed, NO self-link
             (URIRef("urn:m2"), URIRef(HGU), URIRef(e), gu),
             (URIRef("urn:m2"), URIRef(VITALTYPE), URIRef(KG_FRAME), gu)]
    await space_impl.add_rdf_quads_batch_bulk(sid, quads)

    deleted = await space_impl.delete_entity_graph_bulk(sid, g, e)
    assert deleted == 3, "the entity's own quad must go with its members"

    async with space_impl.db_impl.connection_pool.acquire() as conn:
        left = await conn.fetchval(
            f"SELECT count(*) FROM {sid}_rdf_quad q JOIN {sid}_term t "
            f"ON t.term_uuid = q.subject_uuid WHERE t.term_text = $1", e)
    assert left == 0, "the root survived its own graph delete"


async def test_delete_reports_members_that_arrive_after_the_membership_snapshot(
        space_impl, del_space, caplog, monkeypatch):
    """A member written mid-delete outlives its root, and the delete says so.

    The membership query matches one predicate at one instant, so anything
    written after it runs is not in the delete set and survives, pointing at an
    entity that no longer exists. That residue is issues/092 — 19 grouping
    targets with members and no typed root. It is reported, not deleted:
    removing it would be a second unbounded pass over rows the caller never
    named, and the safe half of the fix is for the delete to stop being silent.
    """
    from vitalgraph.db.sparql_sql import sync_stats_tables
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid

    sid, g, e = del_space, "urn:g3", "urn:e3"
    gu = URIRef(g)
    await space_impl.add_rdf_quads_batch_bulk(sid, [
        (URIRef(e), URIRef(HGU), URIRef(e), gu),
        (URIRef("urn:m3"), URIRef(HGU), URIRef(e), gu)])

    pool = space_impl.db_impl.connection_pool
    real = sync_stats_tables.sync_stats_after_delete

    late_s = _generate_term_uuid("urn:late3", "U")
    p_uuid = _generate_term_uuid(HGU, "U")
    o_uuid, g_uuid = _generate_term_uuid(e, "U"), _generate_term_uuid(g, "U")
    async with pool.acquire() as conn:
        await conn.execute(
            f"INSERT INTO {sid}_term (term_uuid, term_text, term_type) "
            f"VALUES ($1, 'urn:late3', 'U') ON CONFLICT DO NOTHING", late_s)

    async def racing_writer(conn, space_id, quad_rows):
        # Commits on its own connection after the snapshot, as an ingest would.
        # Raw INSERT, not add_rdf_quads_batch_bulk: that path would update the
        # rdf_stats rows this still-open delete transaction holds, and wait on a
        # transaction that cannot commit until this callback returns.
        await real(conn, space_id, quad_rows)
        async with pool.acquire() as other:
            await other.execute(
                f"INSERT INTO {sid}_rdf_quad "
                f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
                f"VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
                late_s, p_uuid, o_uuid, g_uuid)

    monkeypatch.setattr(sync_stats_tables, "sync_stats_after_delete", racing_writer)

    with caplog.at_level("WARNING"):
        await space_impl.delete_entity_graph_bulk(sid, g, e)

    warned = [r.getMessage() for r in caplog.records
              if "still" in r.getMessage() and "issues/092" in r.getMessage()]
    assert warned, f"the surviving member was not reported: {caplog.records}"
    assert "1 quad(s)" in warned[0], warned[0]
