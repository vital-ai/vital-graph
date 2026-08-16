"""Integration tests: `{space}_edge` stays in sync when quads are DELETED.

`test_edge_table_sync.py` covers the insert half. This is the mirror, which had
neither detection nor repair until 2026-08-10 and reached production twice:

* `issues/041` — edges never recorded on insert (~25% of a production edge table)
* `issues/064` — edge rows left behind on delete: **20,461 orphans across four
  spaces**, 20,306 of them (5.3%) in a production-shaped space, each answering
  frame traversals with an edge to nowhere

The delete half survived because the "background self-heal" it was deferred to is
`backfill_edge_table`, an `INSERT ... ON CONFLICT DO NOTHING`, which only ADDS.
Deferred inserts were reconciled; deferred deletes never were.

Two traps these tests are written around
----------------------------------------
**Assert referentially, never by count.** An orphan is an *extra* row, so a
count check reads a table with orphans as healthy — `edge_table_drift` compares
`hasEdgeSource` quads against edge rows and an orphan makes that difference
*smaller*. Orphans and missing edges can also cancel exactly. So every assertion
here asks whether each surviving edge row still has its defining quad in the same
context.

**Test WHERE-bound subjects separately from concrete ones.** The SPARQL UPDATE
path enumerates concrete subjects and syncs them directly; only subjects bound by
a WHERE clause are deferred. A test that deletes by concrete URI passes against
the broken code, which is presumably why one was never written.

See planning/planning_performance/edge_table_integrity_bug.md
"""

from __future__ import annotations

import pytest
from rdflib import URIRef

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

CORE = "http://vital.ai/ontology/vital-core#"
HAS_EDGE_SOURCE = URIRef(f"{CORE}hasEdgeSource")
HAS_EDGE_DEST = URIRef(f"{CORE}hasEdgeDestination")
VITALTYPE = URIRef(f"{CORE}vitaltype")
KG_SLOT_EDGE = URIRef("http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot")

GRAPH = URIRef("urn:test:edge_delete_graph")


async def _orphan_count(conn, space_id: str) -> int:
    """Edge rows with no `hasEdgeSource` quad in the SAME context.

    The referential check, not a count comparison. Context is part of it for the
    same reason it is in `edge_table_orphan_rate`: a row whose edge_uuid still
    resolves but whose context no longer matches is invisible to an
    identity-only test while being useless to every query.
    """
    return await conn.fetchval(
        f"""
        SELECT count(*) FROM {space_id}_edge e
        WHERE NOT EXISTS (
            SELECT 1 FROM {space_id}_rdf_quad q
            JOIN {space_id}_term t ON t.term_uuid = q.predicate_uuid
            WHERE q.subject_uuid = e.edge_uuid
              AND t.term_text = $1
              AND q.context_uuid = e.context_uuid)
        """,
        str(HAS_EDGE_SOURCE),
    )


async def _edge_rows(conn, space_id: str) -> int:
    return await conn.fetchval(f"SELECT count(*) FROM {space_id}_edge")


async def _seed(space_impl, space_id: str, n: int, tag: str) -> list:
    """Create n complete edges. Returns their URIs."""
    quads, uris = [], []
    for i in range(n):
        e = URIRef(f"urn:test:{tag}:edge:{i}")
        uris.append(str(e))
        quads += [
            (e, VITALTYPE, KG_SLOT_EDGE, GRAPH),
            (e, HAS_EDGE_SOURCE, URIRef(f"urn:test:{tag}:src:{i}"), GRAPH),
            (e, HAS_EDGE_DEST, URIRef(f"urn:test:{tag}:dst:{i}"), GRAPH),
        ]
    await space_impl.add_rdf_quads_batch(space_id, quads)
    return uris


class TestEdgeTableSyncOnDelete:

    async def test_delete_data_concrete_subjects_leaves_no_orphans(
        self, test_space, space_impl, pg_conn
    ):
        """DELETE DATA naming edges explicitly removes their edge rows.

        The path that already worked — subjects are concrete, so
        `_concrete_subjects_from_update_ops` enumerates them and the hooks fire.
        Present so a regression in the working half is caught too.
        """
        uris = await _seed(space_impl, test_space, 5, "concrete")
        before = await _edge_rows(pg_conn, test_space)
        assert before >= 5, "seed did not create edge rows"

        triples = " ".join(
            f"<{u}> <{HAS_EDGE_SOURCE}> <urn:test:concrete:src:{i}> . "
            f"<{u}> <{HAS_EDGE_DEST}> <urn:test:concrete:dst:{i}> ."
            for i, u in enumerate(uris)
        )
        await space_impl.execute_sparql_update(
            test_space, f"DELETE DATA {{ GRAPH <{GRAPH}> {{ {triples} }} }}")

        assert await _orphan_count(pg_conn, test_space) == 0

    async def test_delete_where_bound_subjects_leaves_no_orphans(
        self, test_space, space_impl, pg_conn
    ):
        """DELETE WHERE with a VARIABLE subject — the case that was broken.

        Nothing can enumerate these subjects before executing, so they were
        deferred to a self-heal that only ever added rows. The edge rows
        survived their quads indefinitely.

        Deliberately deletes only the `hasEdgeSource` quads: an edge row is valid
        only while BOTH defining quads exist, so removing one is enough to
        orphan it — and it is the subtler case, since the edge_uuid still
        resolves and a naive identity check would call it healthy.

        DEFERRED, NOT SYNCHRONOUS. The cleanup used to run inline at the end of
        the update. It no longer does: it is O(edge table), measured at 181,212
        ms over 4.98M rows against a 60 s command_timeout, so inline it was
        cancelled every time and cleaned nothing (`issues/079`). The update now
        marks the space and `MaintenanceJob` sweeps it. Both halves are asserted
        here — the mark, and that sweeping actually clears the orphans —
        because dropping either one is silent: the mark alone cleans nothing,
        and a sweep nobody asks for never runs.
        """
        from vitalgraph.db.sparql_sql.sync_edge_table import (
            take_sweep_pending, cleanup_orphan_edges)

        await _seed(space_impl, test_space, 7, "bound")
        assert await _orphan_count(pg_conn, test_space) == 0
        take_sweep_pending()                    # ignore marks from seeding

        await space_impl.execute_sparql_update(
            test_space,
            f"DELETE WHERE {{ GRAPH <{GRAPH}> "
            f"{{ ?e <{HAS_EDGE_SOURCE}> ?s }} }}")

        assert test_space in take_sweep_pending(), (
            "the WHERE-bound delete did not mark the space for the referential "
            "sweep, so nothing will ever clean up after it (issues/064)")

        await cleanup_orphan_edges(pg_conn, test_space)

        orphans = await _orphan_count(pg_conn, test_space)
        assert orphans == 0, (
            f"{orphans} edge row(s) survived the deletion of their "
            f"hasEdgeSource quads. Frame traversals will follow them to nodes "
            f"that no longer exist, and no count-based check can see it — an "
            f"orphan makes edge_table_drift SMALLER. See issues/064.")

    async def test_drop_graph_leaves_no_edge_rows_for_that_context(
        self, test_space, space_impl, pg_conn
    ):
        """DROP GRAPH names no subjects at all, so per-subject hooks never fire.

        Before the fix this left the entire graph's edge table intact while its
        quads were gone — the largest possible version of the orphan case.
        """
        await _seed(space_impl, test_space, 6, "dropped")
        assert await _edge_rows(pg_conn, test_space) >= 6

        await space_impl.execute_sparql_update(
            test_space, f"DROP GRAPH <{GRAPH}>")

        assert await _orphan_count(pg_conn, test_space) == 0
        # And specifically: nothing left for that context.
        left = await pg_conn.fetchval(
            f"""
            SELECT count(*) FROM {test_space}_edge e
            JOIN {test_space}_term t ON t.term_uuid = e.context_uuid
            WHERE t.term_text = $1
            """, str(GRAPH))
        assert left == 0, f"{left} edge row(s) survived DROP GRAPH"

    async def test_insert_via_sparql_update_records_the_edge(
        self, test_space, space_impl, pg_conn
    ):
        """The insert half, through SPARQL UPDATE rather than the batch API.

        This is the direction that reached production as a ~25% incomplete edge
        table (`issues/041`). It has been fixed and had no test; a missing edge
        makes frame traversals skip rows silently, which no upper-bound
        performance assertion can detect.
        """
        e = URIRef("urn:test:inserted:edge:1")
        await space_impl.execute_sparql_update(
            test_space,
            f"INSERT DATA {{ GRAPH <{GRAPH}> {{ "
            f"<{e}> <{VITALTYPE}> <{KG_SLOT_EDGE}> . "
            f"<{e}> <{HAS_EDGE_SOURCE}> <urn:test:inserted:src:1> . "
            f"<{e}> <{HAS_EDGE_DEST}> <urn:test:inserted:dst:1> . }} }}")

        found = await pg_conn.fetchval(
            f"""
            SELECT count(*) FROM {test_space}_edge e
            JOIN {test_space}_term t ON t.term_uuid = e.edge_uuid
            WHERE t.term_text = $1
            """, str(e))
        assert found == 1, (
            "an edge inserted through SPARQL UPDATE was not recorded in the "
            "edge table, so frame traversals will not find it (issues/041)")
        assert await _orphan_count(pg_conn, test_space) == 0


class TestRestDeletePathsSyncTheEdgeTable:
    """`remove_rdf_quads_batch` — the REST delete path, not SPARQL UPDATE.

    The 2026-08-10 pass fixed the delete half for `execute_sparql_update` and
    for CLEAR/DROP, because those were the paths the production incident ran
    through. It produced the rule "a test per write MODE, not per structure" —
    and the gap was that "mode" was read as insert/update/delete when the real
    axis is (PATH x mode).

    `remove_rdf_quads_batch` is the delete mode of a path that was never in
    scope. It deleted quads and maintained nothing at all — not edge, not
    frame_entity, not stats — while `remove_rdf_quads_batch_bulk` beside it
    maintained all three. It is live product surface: `triples_endpoint`,
    `files_impl`, and `objects_impl` in two places.

    Same orphan class as `issues/064`, so the same referential assertion: an
    orphan is an EXTRA row, and a count check reads a table with orphans as
    healthy.
    """

    async def test_remove_rdf_quads_batch_leaves_no_orphans(
        self, test_space, space_impl, pg_conn
    ):
        uris = await _seed(space_impl, test_space, 5, "restbatch")
        assert await _edge_rows(pg_conn, test_space) >= 5
        assert await _orphan_count(pg_conn, test_space) == 0

        quads = [
            (URIRef(u), p, o, GRAPH)
            for u in uris
            for p, o in ((VITALTYPE, KG_SLOT_EDGE),
                         (HAS_EDGE_SOURCE,
                          URIRef(u.replace(":edge:", ":src:"))),
                         (HAS_EDGE_DEST,
                          URIRef(u.replace(":edge:", ":dst:"))))
        ]
        removed = await space_impl.remove_rdf_quads_batch(test_space, quads)
        assert removed == len(quads), f"removed {removed} of {len(quads)}"

        assert await _orphan_count(pg_conn, test_space) == 0, (
            "remove_rdf_quads_batch deleted the defining quads and left the "
            "edge rows behind — the issues/064 orphan class on the REST path")

    async def test_remove_rdf_quads_batch_decrements_stats(
        self, test_space, space_impl, pg_conn
    ):
        """Stats too, which the edge assertions above cannot see.

        A path can remove its edge rows correctly and still leave
        rdf_pred_stats counting quads that no longer exist, which is what makes
        a predicate look larger than it is to the join reorder.
        """
        uris = await _seed(space_impl, test_space, 4, "reststats")
        src_pred = await pg_conn.fetchval(
            f"SELECT term_uuid FROM {test_space}_term WHERE term_text = $1",
            str(HAS_EDGE_SOURCE))
        before = await pg_conn.fetchval(
            f"SELECT row_count FROM {test_space}_rdf_pred_stats "
            f"WHERE predicate_uuid = $1", src_pred)
        assert before and before >= 4

        quads = [(URIRef(u), HAS_EDGE_SOURCE,
                  URIRef(u.replace(":edge:", ":src:")), GRAPH) for u in uris]
        await space_impl.remove_rdf_quads_batch(test_space, quads)

        after = await pg_conn.fetchval(
            f"SELECT row_count FROM {test_space}_rdf_pred_stats "
            f"WHERE predicate_uuid = $1", src_pred)
        assert after == before - 4, (
            f"pred_stats went {before} -> {after} after deleting 4 quads; "
            f"expected {before - 4}. The delete path is not decrementing stats.")


class TestSingleQuadInsertMaintainsStats:
    """`add_rdf_quad` — the last write path that did not maintain stats.

    It syncs edge and frame_entity, and its own comment explains why: "this
    path bypasses the bulk sync, so edge quads inserted here would otherwise
    never reach the edge table". Stats were not part of that thought, so
    rdf_pred_stats under-counted every quad inserted through it — which makes a
    predicate look SMALLER than it is to the join reorder, the direction that
    gets it driven first.

    Asserted as a delta rather than an absolute, so the test does not depend on
    what else the fixture has written.
    """

    async def test_add_rdf_quad_increments_pred_stats(
        self, test_space, space_impl, pg_conn
    ):
        pred = URIRef("urn:test:singlequad:pred")
        before = await pg_conn.fetchval(
            f"SELECT coalesce(row_count, 0) FROM {test_space}_rdf_pred_stats ps "
            f"JOIN {test_space}_term t ON t.term_uuid = ps.predicate_uuid "
            f"WHERE t.term_text = $1", str(pred)) or 0

        for i in range(3):
            ok = await space_impl.add_rdf_quad(
                test_space, (URIRef(f"urn:test:singlequad:s:{i}"), pred,
                             URIRef(f"urn:test:singlequad:o:{i}"), GRAPH))
            assert ok

        after = await pg_conn.fetchval(
            f"SELECT row_count FROM {test_space}_rdf_pred_stats ps "
            f"JOIN {test_space}_term t ON t.term_uuid = ps.predicate_uuid "
            f"WHERE t.term_text = $1", str(pred))
        assert after == before + 3, (
            f"pred_stats went {before} -> {after} after three single-quad "
            f"inserts; expected {before + 3}. Either the path is not "
            f"incrementing stats, or it is double counting.")

    async def test_add_rdf_quad_matches_the_quad_table(
        self, test_space, space_impl, pg_conn
    ):
        """The stronger check: stats must equal reality, not just move.

        A path that increments twice per quad also passes a delta test if the
        delta is read loosely. This compares the recorded count against an
        actual count of the quads.
        """
        pred = URIRef("urn:test:singlequad2:pred")
        for i in range(4):
            await space_impl.add_rdf_quad(
                test_space, (URIRef(f"urn:test:singlequad2:s:{i}"), pred,
                             URIRef(f"urn:test:singlequad2:o:{i}"), GRAPH))

        recorded, actual = await pg_conn.fetchrow(
            f"""SELECT
                  (SELECT row_count FROM {test_space}_rdf_pred_stats ps
                   WHERE ps.predicate_uuid = t.term_uuid) AS recorded,
                  (SELECT count(*) FROM {test_space}_rdf_quad q
                   WHERE q.predicate_uuid = t.term_uuid) AS actual
                FROM {test_space}_term t WHERE t.term_text = $1""", str(pred))
        assert recorded == actual, (
            f"rdf_pred_stats says {recorded}, the quad table holds {actual}")
