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
KG_NS = "http://vital.ai/ontology/haley-ai-kg#"
VITAL_NS = "http://vital.ai/ontology/vital-core#"


@pytest_asyncio.fixture(loop_scope="session")
async def del_space(make_space):
    return await make_space(f"{TEST_SPACE_PREFIX}delstats_{uuid.uuid4().hex[:8]}")


async def _remaining_pairs(space_impl, sid) -> int:
    """Distinct (predicate, object) pairs left in the quad table.

    The stats table cannot answer this once the survivors are singletons, and
    "the delete removed exactly the right quads" is the claim that matters.
    """
    async with space_impl.db_impl.connection_pool.acquire() as conn:
        return await conn.fetchval(
            f"SELECT count(*) FROM (SELECT DISTINCT predicate_uuid, object_uuid "
            f"FROM {sid}_rdf_quad) x")


async def _stats(conn, sid):
    return {r["k"]: r["row_count"] for r in await conn.fetch(
        f"SELECT predicate_uuid::text||'|'||object_uuid::text AS k, row_count "
        f"FROM {sid}_rdf_stats")}


async def test_fused_delete_keeps_stats_correct(space_impl, del_space):
    from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables

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
        # The delete no longer decrements anything — `recompute_stats_tables`
        # is the only writer (`issues/142`) — so this compares the rebuilt table
        # against the QUADS rather than an incremental result against a resync.
        #
        # That is the stronger comparison. The old one could only show that two
        # implementations agreed, and they agreed while both were wrong: the
        # accumulator decremented on delete and refused to re-add for a pruned
        # predicate, so counts ratcheted toward zero with every individual delta
        # looking correct.
        await recompute_stats_tables(conn, sid, keep_top_n=10_000)
        rebuilt = await _stats(conn, sid)
        truth = {f"{r['p']}|{r['o']}": r["n"] for r in await conn.fetch(
            f"SELECT predicate_uuid::text AS p, object_uuid::text AS o, "
            f"count(*) AS n FROM {sid}_rdf_quad GROUP BY 1, 2 HAVING count(*) >= 2")}

    # After deleting s1/s2 only sX's two (pred,obj) pairs remain, each count 1 —
    # below STATS_MIN_ROW_COUNT, so the correct rebuilt table is EMPTY. Absence
    # means one thing now, and this pins that it means it here.
    assert rebuilt == truth == {}, (rebuilt, truth)
    assert 2 == await _remaining_pairs(space_impl, sid), (
        "sX's two pairs should have survived the delete")


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
    from vitalgraph.db.sparql_sql import sync_entity_slot_sort
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid

    sid, g, e = del_space, "urn:g3", "urn:e3"
    gu = URIRef(g)
    await space_impl.add_rdf_quads_batch_bulk(sid, [
        (URIRef(e), URIRef(HGU), URIRef(e), gu),
        (URIRef("urn:m3"), URIRef(HGU), URIRef(e), gu)])

    pool = space_impl.db_impl.connection_pool
    # The seam used to be `sync_stats_after_delete`, which ran inside the delete
    # transaction after the DELETE. That function is gone (`issues/142`: the
    # write path no longer maintains stats), so the race is injected at the
    # slot-sort sync instead. It runs AFTER the membership snapshot, which is
    # the only property this test needs from the injection point — the late
    # quad survives the DELETE because its subject was never in the snapshot,
    # not because of when it was written relative to the DELETE.
    real = sync_entity_slot_sort.sync_entity_slot_sort_before_delete

    late_s = _generate_term_uuid("urn:late3", "U")
    p_uuid = _generate_term_uuid(HGU, "U")
    o_uuid, g_uuid = _generate_term_uuid(e, "U"), _generate_term_uuid(g, "U")
    async with pool.acquire() as conn:
        await conn.execute(
            f"INSERT INTO {sid}_term (term_uuid, term_text, term_type) "
            f"VALUES ($1, 'urn:late3', 'U') ON CONFLICT DO NOTHING", late_s)

    async def racing_writer(conn, space_id, subject_uuids, **kw):
        # Commits on its own connection after the snapshot, as an ingest would.
        # Raw INSERT, not add_rdf_quads_batch_bulk: that path takes locks this
        # still-open delete transaction holds, and would wait on a transaction
        # that cannot commit until this callback returns.
        result = await real(conn, space_id, subject_uuids, **kw)
        async with pool.acquire() as other:
            await other.execute(
                f"INSERT INTO {sid}_rdf_quad "
                f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
                f"VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
                late_s, p_uuid, o_uuid, g_uuid)
        return result

    monkeypatch.setattr(sync_entity_slot_sort,
                        "sync_entity_slot_sort_before_delete", racing_writer)

    with caplog.at_level("WARNING"):
        await space_impl.delete_entity_graph_bulk(sid, g, e)

    warned = [r.getMessage() for r in caplog.records
              if "still" in r.getMessage() and "issues/092" in r.getMessage()]
    assert warned, f"the surviving member was not reported: {caplog.records}"
    assert "1 quad(s)" in warned[0], warned[0]


async def test_a_fully_stamped_graph_deletes_clean(space_impl, del_space, caplog):
    """Every member carries hasKGGraphURI pointing at the entity, including the
    entity itself, so the whole graph goes.

    That is what entity-graph membership IS: the property names the enclosing
    entity, and the entity is a member of its own graph. A frame WITHOUT it is
    not an unstamped member, it is simply not in this graph — which is why the
    delete cannot infer a write bug from something it did not delete."""
    sid, g, e = del_space, "urn:g5", "urn:e5"
    gu = URIRef(g)
    frame, edge = URIRef("urn:m5"), URIRef("urn:edge5")
    await space_impl.add_rdf_quads_batch_bulk(sid, [
        (URIRef(e), URIRef(VITALTYPE), URIRef(KG_ENTITY), gu),
        (URIRef(e), URIRef(HGU), URIRef(e), gu),
        (frame, URIRef(VITALTYPE), URIRef(KG_FRAME), gu),
        (frame, URIRef(HGU), URIRef(e), gu),
        (edge, URIRef(VITALTYPE), URIRef(f"{KG_NS}Edge_hasKGFrame"), gu),
        (edge, URIRef(HGU), URIRef(e), gu),
        (edge, URIRef(f"{VITAL_NS}hasEdgeSource"), URIRef(e), gu),
        (edge, URIRef(f"{VITAL_NS}hasEdgeDestination"), frame, gu)])

    with caplog.at_level("WARNING"):
        await space_impl.delete_entity_graph_bulk(sid, g, e)

    async with space_impl.db_impl.connection_pool.acquire() as conn:
        left = await conn.fetchval(
            f"SELECT count(*) FROM {sid}_rdf_quad WHERE context_uuid = "
            f"(SELECT term_uuid FROM {sid}_term WHERE term_text = $1)", g)
    assert left == 0, f"{left} quad(s) survived a fully stamped graph delete"
