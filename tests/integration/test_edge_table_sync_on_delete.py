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
        """
        await _seed(space_impl, test_space, 7, "bound")
        assert await _orphan_count(pg_conn, test_space) == 0

        await space_impl.execute_sparql_update(
            test_space,
            f"DELETE WHERE {{ GRAPH <{GRAPH}> "
            f"{{ ?e <{HAS_EDGE_SOURCE}> ?s }} }}")

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
